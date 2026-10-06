"""Read-only validation of frozen mixed-memory and producer-consumer RTL."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from memory_probes import build

from codesign.ventus.__main__ import model_hashes, read_candidate
from codesign.ventus.graph import execute
from codesign.ventus.timing import build_graph

ROOT = Path(__file__).parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check():
    rows = []
    identity = json.loads((ROOT.parent / "search_model/kernel-provenance-v3.json").read_text())[
        "hashes"
    ]
    hardware = {
        "rtl_binary_sha256": identity[
            "${REMOTE_PROJECT_ROOT}/sim-verilator/build/driver_example/debug/sim-VentusRTL"
        ],
        "rtl_library_sha256": identity[
            "${REMOTE_PROJECT_ROOT}/sim-verilator/build/libVentusRTL/debug/libVentusRTL.so"
        ],
        "trace_tool_sha256": identity["${REMOTE_FLOW_ROOT}/trace_rtl-v4.so"],
    }
    for source, observed, generator in [
        ("memory-probes", "memory-rf4-v7", "memory_probes.py"),
        ("combined-probes", "combined-rf4-v7", "combined_probe_frozen.py"),
    ]:
        frozen = json.loads((ROOT / source / "pre_run_predictions.json").read_text())
        if frozen["generator_sha256"] != digest(ROOT / generator):
            raise ValueError("frozen generator changed")
        for case in frozen["cases"]:
            for name, hash_value in case["input_sha256"].items():
                if digest(ROOT / source / case["name"] / name) != hash_value:
                    raise ValueError("frozen input changed")
            if source == "memory-probes":
                program = build(case["name"])
                if (
                    list(program.words) != case["words"]
                    or list(program.expected) != case["expected_words"]
                ):
                    raise ValueError("regenerated ISA/reference differs")
            candidate = read_candidate({"workload": case["workload"]})
            graph = build_graph(candidate.workload, candidate.hardware)
            predicted = execute(graph)
            compute = predicted["times"][graph.names.index(f"pc{case['final_pc']:08x}.writeback")]
            visible = predicted["times"][graph.names.index("outputs.visible")]
            if (compute, visible, predicted["counters"]) != (
                case["prediction"],
                case["predicted_visible"],
                case["counters"],
            ):
                raise ValueError("optimized engine changed frozen prediction")
            path = ROOT / observed / case["name"]
            raw = json.loads((path / "summary.json").read_text())
            if (
                raw["returncode"]
                or raw["warnings"]
                or raw["output_words"] != case["expected_words"]
            ):
                raise ValueError("RTL numeric/diagnostic failure")
            if (
                any(raw[k] != v for k, v in hardware.items())
                or raw["launch_not_before_cycle"] != 512
            ):
                raise ValueError("hardware identity/launch mismatch")
            trace = list(csv.reader((path / "trace.csv").open()))
            collected = [e for e in trace if e[1] == "collect"]
            if [(int(e[3], 16), int(e[4], 16)) for e in collected] != [
                (0x80000000 + 4 * i, w) for i, w in enumerate(case["words"])
            ] or any(e[2] != "0" for e in collected):
                raise ValueError("actual PC/word/warp stream differs")
            start = min(int(e[0]) for e in collected)
            ends = [
                int(e[0]) - start
                for e in trace
                if e[1] == "writeback" and int(e[3], 16) == case["final_pc"]
            ]
            if len(ends) != 1:
                raise ValueError("ambiguous compute endpoint")
            physical = [
                int(e[0]) - start
                for e in trace
                if e[1] == "memory.write" and int(e[3], 16) == 0x90002000
            ]
            actual_visible = max(physical)
            reads = sum(e[1] == "memory.read" and int(e[3], 16) >= 0x90000000 for e in trace)
            rows.append(
                dict(
                    name=case["name"],
                    prediction=compute,
                    rtl_compute=ends[0],
                    compute_error_percent=100 * (compute / ends[0] - 1),
                    predicted_visible=visible,
                    rtl_visible=actual_visible,
                    visible_error_percent=100 * (visible / actual_visible - 1),
                    model_external_read_lines=predicted["counters"]["memory_read_bytes"] // 128,
                    rtl_external_read_lines=reads,
                    output_bit_exact=True,
                    rtl_seconds=raw["wall_seconds"],
                    trace_sha256=digest(path / "trace.csv"),
                    summary_sha256=digest(path / "summary.json"),
                    prediction_source_hashes=frozen["code_sha256"],
                )
            )
    memory = rows[:4]
    ranking = sorted(memory, key=lambda r: r["prediction"])
    if [r["name"] for r in ranking] != [
        r["name"] for r in sorted(memory, key=lambda r: r["rtl_compute"])
    ]:
        raise ValueError("memory-strategy ranking differs")
    return dict(
        code_sha256=model_hashes(),
        cases=rows,
        ranking_matches=True,
        max_compute_error_percent=max(abs(r["compute_error_percent"]) for r in rows),
        max_visible_error_percent=max(abs(r["visible_error_percent"]) for r in rows),
        scope="four equal-Tensor-work single-warp memory patterns and one in-place GEMM-to-LayerNorm program; no full-network RTL claim",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = check()
    path = ROOT / "accuracy.json"
    if args.verify:
        if json.loads(path.read_text()) != result:
            raise ValueError("saved evidence receipt differs")
        print("Read-only v7 mixed-memory RTL replay verified.")
    else:
        with path.open("x") as f:
            f.write(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k not in {"cases", "code_sha256"}}))
