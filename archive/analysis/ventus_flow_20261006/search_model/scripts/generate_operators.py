"""Freeze executable complex-operator inputs and predictions before RTL."""

import argparse
import json
from pathlib import Path

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.operators import fused_operator
from codesign.ventus.timing import build_graph

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--batch", required=True)
parser.add_argument("--holdout", action="store_true")
args = parser.parse_args()
dest = args.root / args.batch
dest.mkdir()
configs = (
    [
        dict(kind="epilogue", depth=24, hidden=4, seed=4),
        dict(kind="ffn", depth=24, hidden=8, seed=3),
        dict(kind="ffn", depth=8, hidden=16, residual=True, seed=2),
        dict(kind="ffn", depth=32, hidden=16, residual=True, seed=5),
    ]
    if args.holdout
    else [
        dict(kind="epilogue", depth=16, hidden=4, seed=1),
        dict(kind="epilogue", depth=32, hidden=4, seed=2),
        dict(kind="ffn", depth=8, hidden=8, seed=1),
        dict(kind="ffn", depth=16, hidden=16, residual=True, seed=1),
    ]
)
cases = []
for config in configs:
    for storage in ["lds", "global"] if config["kind"] == "ffn" else ["lds"]:
        config = dict(config, intermediate=storage)
        name = f"{config['kind']}-d{config['depth']}-h{config['hidden']}-{storage}-r{int(config.get('residual', False))}-s{config['seed']}"
        op = fused_operator(**config)
        case = op.program.write(dest / name, args.root / "kernel-probes-v3/stream-4-rf0-lds1/input")
        graph = build_graph(op.program.workload, Hardware())
        times = execute(graph)["times"]
        case.update(
            name=name,
            config=config,
            output_compute_pc=op.output_compute_pc,
            stages=[
                dict(name=n, pc=pc, predicted=times[graph.names.index(f"pc{pc:08x}.writeback")])
                for n, pc in op.stages
            ],
            predicted_compute_cycles=times[
                graph.names.index(f"pc{op.output_compute_pc:08x}.writeback")
            ],
            predicted_visible_cycles=times[graph.names.index("outputs.visible")],
        )
        cases.append(case)
(dest / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
(dest / "pre_run_predictions.json").write_text(
    json.dumps(
        dict(
            version=MODEL_VERSION,
            code_sha256=model_hashes(),
            cases=cases,
            initial_state="SRAM reset finished; I/data caches cold; host launch gated to cycle 512",
            timing_window="first collector admission -> final arithmetic writeback / final output memory acceptance",
        ),
        indent=2,
    )
    + "\n"
)
print(
    json.dumps(
        [
            {
                k: c[k]
                for k in [
                    "name",
                    "instruction_count",
                    "predicted_compute_cycles",
                    "predicted_visible_cycles",
                ]
            }
            for c in cases
        ]
    )
)
