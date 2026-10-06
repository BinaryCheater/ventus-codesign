"""Read-only replay of frozen LayerNorm timing, ISA and fresh RTL evidence."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from generate import Emitter
from isa_reference import execute as execute_isa

from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.timing import build_graph


def check(root):
    frozen = json.loads((root / "probes-c/pre_run_predictions.json").read_text())
    if frozen["code_sha256"] != model_hashes():
        raise ValueError("model changed after prediction freeze")
    if (
        frozen["generator_sha256"]
        != hashlib.sha256((root / "generate.py").read_bytes()).hexdigest()
    ):
        raise ValueError("ISA generator changed after prediction freeze")
    provenance = json.loads(
        Path("analysis/ventus_flow_20261006/search_model/kernel-provenance-v3.json").read_text()
    )["hashes"]
    expected_identity = {
        "rtl_binary_sha256": provenance[
            "${REMOTE_PROJECT_ROOT}/sim-verilator/build/driver_example/debug/sim-VentusRTL"
        ],
        "rtl_library_sha256": provenance[
            "${REMOTE_PROJECT_ROOT}/sim-verilator/build/libVentusRTL/debug/libVentusRTL.so"
        ],
        "trace_tool_sha256": provenance["${REMOTE_FLOW_ROOT}/trace_rtl-v4.so"],
    }
    rows = []
    for case in frozen["cases"]:
        path = root / "rtl-c" / case["name"]
        raw = json.loads((path / "summary.json").read_text())
        if raw["returncode"] or raw["warnings"] or not raw["output_matches"]:
            raise ValueError(f"RTL output/diagnostic failure: {case['name']}")
        if (
            any(raw[k] != v for k, v in expected_identity.items())
            or raw["launch_not_before_cycle"] != 512
        ):
            raise ValueError("hardware/observer/initial-state mismatch")
        for name, digest in case["input_sha256"].items():
            if (
                hashlib.sha256((root / "probes-c" / case["name"] / name).read_bytes()).hexdigest()
                != digest
            ):
                raise ValueError("frozen input changed")
        program, metadata = Emitter(case["width"], case["seed"], case["constant"]).build()
        decoded, _ = execute_isa(program)
        if (
            list(program.words) != case["words"]
            or list(decoded) != case["expected_words"]
            or list(decoded) != raw["output_words"]
        ):
            raise ValueError("ISA decoder, generated reference or RTL disagree")
        graph = build_graph(program.workload, Hardware())
        predicted = execute(graph)
        trace = list(csv.reader((path / "trace.csv").open()))
        collects = [e for e in trace if e[1] == "collect"]
        if [(int(e[3], 16), int(e[4], 16)) for e in collects] != [
            (0x80000000 + 4 * i, w) for i, w in enumerate(program.words)
        ]:
            raise ValueError("actual collector PC/word stream differs")
        if any(int(e[2]) != 0 for e in collects):
            raise ValueError("unexpected warp in single-warp probe")
        start = min(int(e[0]) for e in collects)
        stages = []
        for stage in case["metadata"]["stages"]:
            times = [
                int(e[0]) - start
                for e in trace
                if e[1] == "writeback" and int(e[3], 16) == stage["pc"]
            ]
            p = predicted["times"][graph.names.index(f"pc{stage['pc']:08x}.writeback")]
            if len(times) != 1 or p != stage["predicted"]:
                raise ValueError("stage endpoint ambiguity or changed prediction")
            stages.append(
                {
                    "name": stage["name"],
                    "prediction": p,
                    "rtl": times[0],
                    "error_cycles": p - times[0],
                }
            )
        physical = [
            e
            for e in trace
            if e[1] == "memory.write"
            and 0x90002000 <= int(e[3], 16) < 0x90002000 + case["width"] * 4
        ]
        if {int(e[3], 16) for e in physical} != {
            0x90002000 + 128 * i for i in range(case["width"] // 32)
        } or len(physical) != case["width"] // 32:
            raise ValueError("final output lines not written exactly once")
        visible = max(int(e[0]) - start for e in physical)
        p_visible = predicted["times"][graph.names.index("outputs.visible")]
        if p_visible != case["predicted_visible"]:
            raise ValueError("output visibility prediction changed")
        compute = stages[-1]["rtl"]
        rows.append(
            dict(
                name=case["name"],
                width=case["width"],
                output_words=len(decoded),
                output_bit_exact=True,
                dense_max_abs_error=metadata["max_abs_error_vs_float64"],
                instructions=len(program.words),
                predicted_compute=case["prediction"],
                rtl_compute=compute,
                compute_error_percent=100 * (case["prediction"] / compute - 1),
                predicted_visible=p_visible,
                rtl_visible=visible,
                visible_error_percent=100 * (p_visible / visible - 1),
                stages=stages,
                rtl_seconds=raw["wall_seconds"],
                trace_sha256=hashlib.sha256((path / "trace.csv").read_bytes()).hexdigest(),
                summary_sha256=hashlib.sha256((path / "summary.json").read_bytes()).hexdigest(),
            )
        )
    return dict(
        code_sha256=model_hashes(),
        initial_state=frozen["initial_state"],
        results=rows,
        max_compute_error_percent=max(abs(r["compute_error_percent"]) for r in rows),
        max_visible_error_percent=max(abs(r["visible_error_percent"]) for r in rows),
        max_stage_error_cycles=max(abs(s["error_cycles"]) for r in rows for s in r["stages"]),
        rtl_total_seconds=sum(r["rtl_seconds"] for r in rows),
        verified_scope="four single-warp concrete LayerNorm kernels; not the Transformer pseudo-template or full network",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = check(args.root)
    path = args.root / "accuracy.json"
    if args.verify:
        if json.loads(path.read_text()) != result:
            raise ValueError("saved RTL receipt differs")
        print("Read-only LayerNorm RTL replay verified.")
    else:
        with path.open("x") as f:
            f.write(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k not in {"code_sha256", "results"}}))
