"""Verify frozen predictions against fresh complex-operator RTL execution."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.operators import fused_operator
from codesign.ventus.timing import build_graph

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--batches", nargs="+", required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--verify", action="store_true")
args = parser.parse_args()
provenance = json.loads((args.root / "kernel-provenance-v3.json").read_text())["hashes"]
expected_rtl = {
    "rtl_binary_sha256": provenance[
        "${REMOTE_PROJECT_ROOT}/sim-verilator/build/driver_example/debug/sim-VentusRTL"
    ],
    "rtl_library_sha256": provenance[
        "${REMOTE_PROJECT_ROOT}/sim-verilator/build/libVentusRTL/debug/libVentusRTL.so"
    ],
    "trace_tool_sha256": provenance["${REMOTE_FLOW_ROOT}/trace_rtl-v4.so"],
}
rows, total = [], 0
for batch in args.batches:
    frozen = json.loads((args.root / batch / "pre_run_predictions.json").read_text())
    if frozen["version"] != MODEL_VERSION or frozen["code_sha256"] != model_hashes():
        raise ValueError("model differs from frozen pre-RTL predictions")
    for case in frozen["cases"]:
        source = args.root / batch / case["name"]
        raw_path = args.root / "evidence" / batch / case["name"] / "summary.json"
        observed = json.loads(raw_path.read_text())
        if any(observed[field] != sha for field, sha in expected_rtl.items()):
            raise ValueError("RTL binary/library or observer differs from pinned provenance")
        if observed["launch_not_before_cycle"] != 512:
            raise ValueError("RTL initial state differs from prediction")
        trace_path = raw_path.with_name("trace.csv")
        trace = [line.split(",") for line in trace_path.read_text().splitlines()]
        if observed["returncode"] or observed["warnings"] or not observed["output_matches"]:
            raise ValueError(f"RTL failed: {case['name']}")
        for name, sha in case["input_sha256"].items():
            if hashlib.sha256((source / name).read_bytes()).hexdigest() != sha:
                raise ValueError("input changed")
        program = fused_operator(**case["config"])
        if observed["output_words"] != list(program.program.expected):
            raise ValueError("RTL differs from independent dense reference")
        collects = [r for r in trace if r[1] == "collect"]
        if [(int(r[3], 16), int(r[4], 16)) for r in collects] != [
            (0x80000000 + i * 4, word) for i, word in enumerate(program.program.words)
        ]:
            raise ValueError("RTL executed a different instruction stream")
        first = min(int(r[0]) for r in collects)
        begin = perf_counter()
        graph = build_graph(program.program.workload, Hardware())
        times = execute(graph)["times"]
        total += perf_counter() - begin
        stages = []
        for stage in case["stages"]:
            observed_times = [
                int(r[0]) for r in trace if r[1] == "writeback" and int(r[3], 16) == stage["pc"]
            ]
            if len(observed_times) != 1:
                raise ValueError("ambiguous arithmetic endpoint")
            predicted = times[graph.names.index(f"pc{stage['pc']:08x}.writeback")]
            if predicted != stage["predicted"]:
                raise ValueError("stage prediction changed after RTL")
            stages.append(
                dict(
                    name=stage["name"],
                    predicted=predicted,
                    rtl=observed_times[0] - first,
                    error_cycles=predicted - (observed_times[0] - first),
                )
            )
        visible_times = [
            int(r[0]) for r in trace if r[1] == "memory.write" and int(r[3], 16) == 0x90002000
        ]
        if len(visible_times) != 1:
            raise ValueError("ambiguous final output write")
        compute = stages[-1]["rtl"]
        visible = visible_times[0] - first
        predicted_compute = times[graph.names.index(f"pc{program.output_compute_pc:08x}.writeback")]
        predicted_visible = times[graph.names.index("outputs.visible")]
        if (predicted_compute, predicted_visible) != (
            case["predicted_compute_cycles"],
            case["predicted_visible_cycles"],
        ):
            raise ValueError("prediction changed after RTL")
        rows.append(
            dict(
                name=case["name"],
                batch=batch,
                config=case["config"],
                stages=stages,
                predicted_compute=predicted_compute,
                rtl_compute=compute,
                predicted_visible=predicted_visible,
                rtl_visible=visible,
                compute_error_pct=100 * (predicted_compute / compute - 1),
                visible_error_pct=100 * (predicted_visible / visible - 1),
                output_bit_exact=True,
                instruction_count=len(program.program.words),
                rtl_host_dispatch_to_finish=observed["dispatch_to_finish_cycles"],
                evidence_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                trace_sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest(),
                rtl_binary_sha256=observed["rtl_binary_sha256"],
                rtl_library_sha256=observed["rtl_library_sha256"],
            )
        )
receipt = dict(
    version=MODEL_VERSION,
    code_sha256=model_hashes(),
    results=rows,
    max_compute_error_pct=max(abs(r["compute_error_pct"]) for r in rows),
    max_visible_error_pct=max(abs(r["visible_error_pct"]) for r in rows),
    mean_visible_error_pct=sum(abs(r["visible_error_pct"]) for r in rows) / len(rows),
    evaluation_seconds=total,
    initial_state=frozen["initial_state"],
    timing_window=frozen["timing_window"],
)
if args.verify:
    prior = json.loads(args.out.read_text())
    for key in receipt.keys() - {"evaluation_seconds"}:
        if receipt[key] != prior[key]:
            raise ValueError(f"saved evidence differs: {key}")
else:
    with args.out.open("x") as out:
        json.dump(receipt, out, indent=2)
        out.write("\n")
print(
    json.dumps(
        {
            k: v
            for k, v in receipt.items()
            if k not in {"code_sha256", "initial_state", "timing_window"}
        },
        indent=2,
    )
)
