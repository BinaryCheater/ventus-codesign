"""Held-out global load probes, with predictions frozen before fresh RTL."""

import argparse
import json
from pathlib import Path

from generate_probes import emit, v

from codesign.ventus.config import Hardware
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.timing import simulate

parser = argparse.ArgumentParser()
parser.add_argument("destination", type=Path)
parser.add_argument("--strides", type=int, nargs="+", default=[0, 128])
parser.add_argument("--counts", type=int, nargs="+", default=[16, 64])
args = parser.parse_args()
root = args.destination
root.mkdir()
cases = []
for stride in args.strides:
    for count in args.counts:
        init = [
            v(0x0B, 1, 1, 0, 1),
            0x900002B7,
            (stride << 20) | (6 << 7) | 0x13,
            v(0x14, 0, 17, 2, 10),
            v(0x25, 10, 2, 3, 10),
            v(0, 10, 5, 4, 10),
        ]
        load = (10 << 15) | (2 << 12) | (1 << 7) | 0x7B
        advance = v(0, 10, 6, 4, 10)
        body = []
        for i in range(count):
            body.extend([load, advance])
        name = f"global-stride{stride}-{count}"
        ops = []
        for i in range(count):
            ops += [
                Operation(
                    f"load{i}",
                    "load",
                    sources=("v10",),
                    destination="v1",
                    addresses=tuple(
                        0x90000000 + i * stride + lane * 4 for lane in range(32)
                    ),
                ),
                Operation(
                    f"advance{i}", "vector", sources=("v10", "x6"), destination="v10"
                ),
            ]
        prediction = simulate(Workload(tuple(ops)), Hardware())
        case = emit(root, name, init + body, count, f"global-stride{stride}", None)
        case["predicted_segment_cycles"] = prediction["cycles"]
        case[
            "expected_words"
        ] = []  # Numerical values are independently observable but not model inputs.
        cases.append(case)
(root / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
(root / "pre_run_predictions.json").write_text(
    json.dumps({"cases": cases, "uses_fitted_timing": False}, indent=2) + "\n"
)
