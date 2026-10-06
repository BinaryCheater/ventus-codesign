"""Frozen prediction vs fresh broader RTL; exclusive receipts/read-only replay."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from isa_check import execute as decode_isa
from isa_check import number

from codesign.ventus.__main__ import model_hashes, read_candidate
from codesign.ventus.graph import execute
from codesign.ventus.timing import build_graph

ROOT = Path(__file__).parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check():
    frozen = json.loads((ROOT / "probes/pre_run_predictions.json").read_text())
    if frozen["code_sha256"] != model_hashes() or frozen["generator_sha256"] != digest(
        ROOT / "generate.py"
    ):
        raise ValueError("prediction source changed")
    hashes = json.loads((ROOT.parent / "search_model/kernel-provenance-v3.json").read_text())[
        "hashes"
    ]
    identity = {
        "rtl_binary_sha256": hashes[
            "${REMOTE_PROJECT_ROOT}/sim-verilator/build/driver_example/debug/sim-VentusRTL"
        ],
        "rtl_library_sha256": hashes[
            "${REMOTE_PROJECT_ROOT}/sim-verilator/build/libVentusRTL/debug/libVentusRTL.so"
        ],
        "trace_tool_sha256": hashes["${REMOTE_FLOW_ROOT}/trace_rtl-v4.so"],
    }
    rows = []
    for case in frozen["cases"]:
        for name, value in case["input_sha256"].items():
            if digest(ROOT / "probes" / case["name"] / name) != value:
                raise ValueError("input hash differs")
        snapshots = []
        accesses = decode_isa(case, ROOT / "probes" / case["name"], snapshots=snapshots)
        candidate = read_candidate({"workload": case["workload"]})
        graph = build_graph(candidate.workload, candidate.hardware)
        predicted = execute(graph)
        names = (
            [f"w{w}.pc{case['final_pc']:08x}.writeback" for w in range(case["warps"])]
            if case["warps"] > 1
            else [f"pc{case['final_pc']:08x}.writeback"]
        )
        pcompute = max(predicted["times"][graph.names.index(n)] for n in names)
        pvisible = predicted["times"][graph.names.index("outputs.visible")]
        if (pcompute, pvisible, predicted["counters"]) != (
            case["prediction"],
            case["predicted_visible"],
            case["counters"],
        ):
            raise ValueError("frozen prediction differs")
        path = ROOT / "rtl" / case["name"]
        raw = json.loads((path / "summary.json").read_text())
        if raw["returncode"] or raw["warnings"] or raw["output_words"] != case["expected_words"]:
            raise ValueError("RTL numeric/diagnostic failure")
        if any(raw[k] != v for k, v in identity.items()) or raw["launch_not_before_cycle"] != 512:
            raise ValueError("DUT/observer/launch differs")
        trace = list(csv.reader((path / "trace.csv").open()))
        collect = [e for e in trace if e[1] == "collect"]
        for warp in range(case["warps"]):
            stream = [(int(e[3], 16), int(e[4], 16)) for e in collect if int(e[2]) == warp]
            if stream != [(0x80000000 + 4 * i, w) for i, w in enumerate(case["words"])]:
                raise ValueError("actual warp instruction stream differs")
        if {int(e[2]) for e in collect} != set(range(case["warps"])):
            raise ValueError("unexpected warp")
        start = min(int(e[0]) for e in collect)
        endpoints = [e for e in trace if e[1] == "writeback" and int(e[3], 16) == case["final_pc"]]
        if len(endpoints) != case["warps"]:
            raise ValueError("ambiguous endpoint")
        compute = max(int(e[0]) - start for e in endpoints)
        stores = [
            e
            for e in trace
            if e[1] == "memory.write"
            and 0x90002000 <= int(e[3], 16) < 0x90002000 + len(case["expected_words"]) * 4
        ]
        if {int(e[3], 16) for e in stores} != {0x90002000 + 128 * w for w in range(case["warps"])}:
            raise ValueError("missing output line")
        visible = max(int(e[0]) - start for e in stores)
        stages = []
        for stage in case["metadata"].get("stages", []):
            actual = [
                int(e[0]) - start
                for e in trace
                if e[1] == "writeback" and int(e[3], 16) == stage["pc"]
            ]
            if len(actual) != 1:
                raise ValueError("stage endpoint differs")
            p = predicted["times"][graph.names.index(f"pc{stage['pc']:08x}.writeback")]
            stages.append(
                dict(name=stage["name"], prediction=p, rtl=actual[0], error_cycles=p - actual[0])
            )
        numeric_stages = []
        if case["name"] == "chain-w1":
            if len(snapshots) != 4:
                raise ValueError("numeric stage count differs")
            values = [np.array(list(map(number, words))) for _, words in snapshots]
            x = values[0]
            gamma = 0.5 + np.arange(32) % 5 / 8
            beta = 0.25 + np.arange(32) % 7 / 16
            norm = (x - x.mean()) / np.sqrt(np.mean((x - x.mean()) ** 2) + 1e-5) * gamma + beta
            gelu = 0.5 * norm * (1 + np.tanh(np.sqrt(2 / np.pi) * (norm + 0.044715 * norm**3)))
            softmax = np.exp(gelu - gelu.max())
            softmax /= softmax.sum()
            for name, actual, expected in zip(
                ("LayerNorm", "GELU", "softmax"), values[1:], (norm, gelu, softmax)
            ):
                error = float(np.max(np.abs(actual - expected)))
                if error > 5e-6:
                    raise ValueError("numeric dense error exceeds contract")
                numeric_stages.append(dict(name=name, max_abs_error=error))
        rows.append(
            dict(
                name=case["name"],
                warps=case["warps"],
                instructions_per_warp=len(case["words"]),
                checked_output_words=len(raw["output_words"]),
                output_bit_exact=True,
                decoded_active_word_accesses=accesses,
                prediction=pcompute,
                rtl_compute=compute,
                compute_error_percent=100 * (pcompute / compute - 1),
                predicted_visible=pvisible,
                rtl_visible=visible,
                visible_error_percent=100 * (pvisible / visible - 1),
                stages=stages,
                numeric_stages=numeric_stages,
                model_external_read_lines=predicted["counters"]["memory_read_bytes"] // 128,
                rtl_external_read_lines=sum(
                    e[1] == "memory.read" and int(e[3], 16) >= 0x90000000 for e in trace
                ),
                rtl_seconds=raw["wall_seconds"],
                trace_sha256=digest(path / "trace.csv"),
                summary_sha256=digest(path / "summary.json"),
            )
        )
    return dict(
        version=frozen["version"],
        code_sha256=model_hashes(),
        generator_sha256=frozen["generator_sha256"],
        results=rows,
        max_compute_error_percent=max(abs(r["compute_error_percent"]) for r in rows),
        max_visible_error_percent=max(abs(r["visible_error_percent"]) for r in rows),
        scope="concrete nonlinear chain and 2/4-warp mixed-memory programs; not complete Transformer attention or official software",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = check()
    path = ROOT / "accuracy.json"
    if args.verify:
        if json.loads(path.read_text()) != result:
            raise ValueError("receipt differs")
        print("Read-only broader RTL receipt verified.")
    else:
        with path.open("x") as f:
            f.write(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    k: v
                    for k, v in result.items()
                    if k not in {"results", "code_sha256", "generator_sha256"}
                }
            )
        )
