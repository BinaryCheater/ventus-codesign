"""Concurrent Tensor/LDS predictions frozen before fresh RTL."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from generate_probes import emit, v

from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.ir import Workload
from codesign.ventus.timing import simulate
from codesign.ventus.workloads import chain


def workload(kind, count, warps):
    stream = chain(kind, count).operations
    operations = tuple(
        replace(op, name=f"w{warp}.{op.name}", warp=warp)
        for op in stream
        for warp in range(warps)
    )
    return Workload(operations, warps_per_block=warps)


def main(root, warp_counts, kinds, counts):
    root.mkdir()
    cases = []
    for warps in warp_counts:
        for kind in kinds:
            for count in counts:
                if kind == "tensor":
                    init = [v(0x0B, i, i, 0, i) for i in [1, 2, 3]]
                    instruction = (
                        (3 << 26)
                        | (1 << 25)
                        | (2 << 20)
                        | (3 << 15)
                        | (4 << 12)
                        | (1 << 7)
                        | 0x0B
                    )
                else:
                    init = [
                        v(0x0B, 1, 1, 0, 1),
                        0x700002B7,
                        v(0x14, 0, 17, 2, 10),
                        v(0x25, 10, 2, 3, 10),
                        v(0, 10, 5, 4, 10),
                        (1 << 20) | (10 << 15) | (6 << 12) | 0x7B,
                    ]
                    instruction = (10 << 15) | (2 << 12) | (1 << 7) | 0x7B
                result = simulate(workload(kind, count, warps), Hardware())
                name = f"multi-{kind}-w{warps}-{count}"
                case = emit(
                    root,
                    name,
                    init + [instruction] * count,
                    count,
                    f"multi-{kind}-w{warps}",
                    None,
                    warps,
                )
                case["predicted_segment_cycles"] = result["cycles"]
                case["warps"] = warps
                cases.append(case)
    frozen = {"model_sha256": model_hashes(), "cases": cases}
    (root / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (root / "pre_run_predictions.json").write_text(json.dumps(frozen, indent=2) + "\n")
    for family in dict.fromkeys(case["family"] for case in cases):
        series = [case for case in cases if case["family"] == family]
        first, last = series[0], series[-1]
        print(
            family, last["predicted_segment_cycles"] - first["predicted_segment_cycles"]
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--warps", type=int, nargs="+", default=[2, 8])
    parser.add_argument(
        "--kinds", choices=["tensor", "load"], nargs="+", default=["tensor", "load"]
    )
    parser.add_argument("--counts", type=int, nargs="+", default=[16, 64])
    args = parser.parse_args()
    main(args.destination, args.warps, args.kinds, args.counts)
