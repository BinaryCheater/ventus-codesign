"""Freeze existing executable workloads under a new hardware configuration."""

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.operators import fused_operator
from codesign.ventus.program import packed_gemm
from codesign.ventus.timing import build_graph

root = Path("analysis/ventus_flow_20261006/search_model")
dest = root / "parameter-rf8-v4b"
dest.mkdir()
hardware = Hardware().with_changes(rf_banks=8)
sources = [
    ("kernel-probes-v3", "resident-16-rf1-lds1"),
    ("kernel-probes-v3", "resident-16-rf0-lds1"),
    ("kernel-probes-v3", "stream-16-rf0-lds1"),
    ("kernel-probes-v3", "shared-4-rf0-lds4"),
    ("operators-probes-v4", "ffn-d16-h16-lds-r1-s1"),
    ("operators-probes-v4", "ffn-d16-h16-global-r1-s1"),
]
cases = []
for batch, name in sources:
    source_case = next(
        c for c in json.loads((root / batch / "cases.json").read_text()) if c["name"] == name
    )
    case = dict(source_case)
    shutil.copytree(root / batch / name, dest / name)
    if "config" in case:
        generated = fused_operator(**case["config"])
        program = generated.program
    else:
        program = packed_gemm(
            case["steps"],
            strategy=case["strategy"],
            rf_conflict=case["rf_conflict"],
            lds_stride=case["lds_stride"],
        )
    work = program.workload
    case["workload"] = asdict(work)
    graph = build_graph(work, hardware)
    result = execute(graph)
    end_pc = case.get("output_compute_pc", case["final_tensor_pc"])
    case.update(
        source_batch=batch,
        hardware=hardware.to_dict(),
        output_compute_pc=end_pc,
        predicted_compute_cycles=result["times"][graph.names.index(f"pc{end_pc:08x}.writeback")],
        predicted_visible_cycles=result["times"][graph.names.index("outputs.visible")],
    )
    if "stages" in case:
        case["stages"] = [
            dict(s, predicted=result["times"][graph.names.index(f"pc{s['pc']:08x}.writeback")])
            for s in case["stages"]
        ]
    cases.append(case)
(dest / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
(dest / "pre_run_predictions.json").write_text(
    json.dumps(
        dict(
            version=MODEL_VERSION,
            code_sha256=model_hashes(),
            hardware=hardware.to_dict(),
            cases=cases,
            initial_state="Cold cache after SRAM reset, external host launch at or after cycle 512",
        ),
        indent=2,
    )
    + "\n"
)
print(
    json.dumps(
        [
            {k: c[k] for k in ["name", "predicted_compute_cycles", "predicted_visible_cycles"]}
            for c in cases
        ]
    )
)
