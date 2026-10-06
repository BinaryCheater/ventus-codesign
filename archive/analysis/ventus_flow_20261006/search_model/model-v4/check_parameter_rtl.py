"""Cross-configuration RTL checks with pre-run, source-derived predictions."""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.operators import fused_operator
from codesign.ventus.program import packed_gemm
from codesign.ventus.timing import build_graph

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--verify", action="store_true")
parser.add_argument("--evidence-batch", default="parameter-rf8-v4d")
args = parser.parse_args()
batch = "parameter-rf8-v4b"
frozen = json.loads((args.root / batch / "pre_run_predictions.json").read_text())
if frozen["version"] != MODEL_VERSION or frozen["code_sha256"] != model_hashes():
    raise ValueError("model changed since prediction")
provenance = json.loads(
    (args.root / "parameter-rtl-v4/complete-subtree-provenance4.json").read_text()
)
if provenance["generated_parameters"]["num_bank"] != 8:
    raise ValueError("RTL did not change bank count")
expected_binaries = provenance["binary_sha256"]
baseline_files = [args.root / "accuracy-v3.json", args.root / "operators-combined-v4.json"]
baselines = {
    row["name"]: row for path in baseline_files for row in json.loads(path.read_text())["results"]
}
rows = []
for case in frozen["cases"]:
    raw_path = args.root / "evidence" / args.evidence_batch / case["name"] / "summary.json"
    observed = json.loads(raw_path.read_text())
    if observed["returncode"] or observed["warnings"] or not observed["output_matches"]:
        raise ValueError(f"RTL execution/numerical check failed: {case['name']}")
    for field, suffix in [
        ("rtl_binary_sha256", "sim-VentusRTL"),
        ("rtl_library_sha256", "libVentusRTL.so"),
        ("trace_tool_sha256", "trace.so"),
    ]:
        expected = next(
            value for path, value in expected_binaries.items() if path.endswith("/" + suffix)
        )
        if observed[field] != expected:
            raise ValueError("different RTL binary/library/observer")
    if observed["hardware"] != frozen["hardware"] or case["hardware"] != frozen["hardware"]:
        raise ValueError("different hardware configuration")
    if observed["launch_not_before_cycle"] != 512:
        raise ValueError("different initialization window")
    for name, sha in case["input_sha256"].items():
        if (
            hashlib.sha256((args.root / batch / case["name"] / name).read_bytes()).hexdigest()
            != sha
        ):
            raise ValueError("RTL inputs changed")
    if "config" in case:
        op = fused_operator(**case["config"])
        program = op.program
        endpoint = op.output_compute_pc
    else:
        program = packed_gemm(
            case["steps"],
            strategy=case["strategy"],
            rf_conflict=case["rf_conflict"],
            lds_stride=case["lds_stride"],
        )
        endpoint = program.final_tensor_pc
    if json.loads(json.dumps(asdict(program.workload))) != case["workload"]:
        raise ValueError("frozen IR differs from current source lowering")
    if list(program.expected) != observed["output_words"]:
        raise ValueError("independent dense result mismatch")
    trace_path = raw_path.with_name("trace.csv")
    trace = [line.split(",") for line in trace_path.read_text().splitlines()]
    collects = [r for r in trace if r[1] == "collect"]
    if [(int(r[3], 16), int(r[4], 16)) for r in collects] != [
        (0x80000000 + i * 4, w) for i, w in enumerate(program.words)
    ]:
        raise ValueError("wrong instruction sequence")
    first = min(int(r[0]) for r in collects)
    if first < 512:
        raise ValueError("launch gate not effective")
    final = [int(r[0]) - first for r in trace if r[1] == "writeback" and int(r[3], 16) == endpoint]
    visible = [
        int(r[0]) - first for r in trace if r[1] == "memory.write" and int(r[3], 16) == 0x90002000
    ]
    if len(final) != 1 or len(visible) != 1:
        raise ValueError("ambiguous endpoint")
    graph = build_graph(program.workload, Hardware(**case["hardware"]))
    times = execute(graph)["times"]
    predicted = times[graph.names.index(f"pc{endpoint:08x}.writeback")]
    predicted_visible = times[graph.names.index("outputs.visible")]
    if (predicted, predicted_visible) != (
        case["predicted_compute_cycles"],
        case["predicted_visible_cycles"],
    ):
        raise ValueError("prediction changed after RTL")
    baseline = baselines[case["name"]]
    old_raw = args.root / "evidence" / baseline["batch"] / case["name"] / "summary.json"
    old_trace = old_raw.with_name("trace.csv")
    if hashlib.sha256(old_raw.read_bytes()).hexdigest() != baseline["evidence_sha256"]:
        raise ValueError("default evidence changed")
    if hashlib.sha256(old_trace.read_bytes()).hexdigest() != baseline["trace_sha256"]:
        raise ValueError("default trace changed")
    if json.loads(old_raw.read_text())["input_sha256"] != case["input_sha256"]:
        raise ValueError("not the same executable/data as default configuration")
    default_graph = build_graph(program.workload, Hardware())
    default_times = execute(default_graph)["times"]
    if (
        default_times[default_graph.names.index(f"pc{endpoint:08x}.writeback")]
        != baseline["predicted_compute"]
    ):
        raise ValueError("default prediction changed")
    if default_times[default_graph.names.index("outputs.visible")] != baseline["predicted_visible"]:
        raise ValueError("default visible prediction changed")
    rows.append(
        dict(
            name=case["name"],
            predicted_compute=predicted,
            rtl_compute=final[0],
            predicted_visible=predicted_visible,
            rtl_visible=visible[0],
            compute_error_pct=100 * (predicted / final[0] - 1),
            visible_error_pct=100 * (predicted_visible / visible[0] - 1),
            output_bit_exact=True,
            rf4_predicted_compute=baseline["predicted_compute"],
            rf4_rtl_compute=baseline["rtl_compute"],
            rf4_predicted_visible=baseline["predicted_visible"],
            rf4_rtl_visible=baseline["rtl_visible"],
            predicted_compute_change=predicted - baseline["predicted_compute"],
            rtl_compute_change=final[0] - baseline["rtl_compute"],
            predicted_visible_change=predicted_visible - baseline["predicted_visible"],
            rtl_visible_change=visible[0] - baseline["rtl_visible"],
            trace_sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            evidence_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        )
    )
receipt = dict(
    version=MODEL_VERSION,
    code_sha256=model_hashes(),
    hardware=frozen["hardware"],
    results=rows,
    rtl_provenance_sha256=hashlib.sha256(
        (args.root / "parameter-rtl-v4/complete-subtree-provenance4.json").read_bytes()
    ).hexdigest(),
    baseline_receipt_sha256={
        str(p.relative_to(args.root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in baseline_files
    },
    source_batch=batch,
    evidence_batch=args.evidence_batch,
    initial_state=frozen["initial_state"],
    timing_window="First collector admission to arithmetic WB / physical external output write",
    mean_visible_error_pct=sum(abs(r["visible_error_pct"]) for r in rows) / len(rows),
    max_compute_error_pct=max(abs(r["compute_error_pct"]) for r in rows),
    max_visible_error_pct=max(abs(r["visible_error_pct"]) for r in rows),
)
if args.verify:
    if receipt != json.loads(args.out.read_text()):
        raise ValueError("saved evidence differs")
else:
    with args.out.open("x") as out:
        json.dump(receipt, out, indent=2)
        out.write("\n")
print(json.dumps(receipt, indent=2))
