"""Encode Tensor and LDS timing probes from the pinned Ventus ISA."""

import hashlib
import json
import sys
from pathlib import Path


def v(fn, b, a, mode, d):
    return (
        (fn << 26) | (1 << 25) | (b << 20) | (a << 15) | (mode << 12) | (d << 7) | 0x57
    )


def emit(root, name, words, n, kind, prediction, warps=1):
    upstream = Path("${OWNER_UPSTREAM_CHECKOUT}/sim-verilator/testcase/vecadd")
    lines = (upstream / "vecadd_32b8w8t.metadata").read_text().splitlines()
    meta = [
        int(lines[i], 16) | (int(lines[i + 1], 16) << 32)
        for i in range(0, len(lines), 2)
    ]
    data = [
        int(x, 16) for x in (upstream / "vecadd_32b8w8t.data").read_text().splitlines()
    ]
    bases = meta[14 : 14 + meta[13]]
    sizes = meta[14 + meta[13] : 14 + 2 * meta[13]]
    pos = bases.index(0x80000000)
    offset, count = sum(sizes[:pos]) // 4, sizes[pos] // 4
    meta[2], meta[5], meta[6] = 1, 32, warps
    words += [
        0x90002137,
        v(0x14, 0, 17, 2, 10),
        v(0x25, 10, 2, 3, 10),
        v(0, 10, 2, 4, 10),
        (1 << 20) | (10 << 15) | (6 << 12) | 0x7B,
        0x400B,
    ]
    assert len(words) <= count
    data[offset : offset + count] = words + [0x13] * (count - len(words))
    out = root / name
    out.mkdir()
    (out / "input.metadata").write_text(
        "".join(f"{x & 0xFFFFFFFF:08x}\n{x >> 32:08x}\n" for x in meta)
    )
    (out / "input.data").write_text("".join(f"{x:08x}\n" for x in data))
    return {
        "name": name,
        "n": n,
        "family": kind,
        "predicted_body_interval": prediction,
        "input_sha256": {
            x: hashlib.sha256((out / x).read_bytes()).hexdigest()
            for x in ["input.metadata", "input.data"]
        },
    }


def main(destination):
    destination.mkdir()
    cases = []
    for n in [16, 64, 192]:
        init = [v(0x0B, i, i, 0, i) for i in [1, 2, 3]]
        # VFTTA_VV: funct6=000011, funct3=100, opcode=0001011.
        tc = (3 << 26) | (1 << 25) | (2 << 20) | (3 << 15) | (4 << 12) | (1 << 7) | 0x0B
        cases.append(
            emit(
                destination,
                f"tensor-distinct-{n}",
                init + [tc] * n,
                n,
                "tensor-distinct",
                16,
            )
        )
    for n in [16, 64]:
        tc = (3 << 26) | (1 << 25) | (1 << 20) | (1 << 15) | (4 << 12) | (1 << 7) | 0x0B
        cases.append(
            emit(
                destination,
                f"tensor-conflict-{n}",
                [v(0x0B, 1, 1, 0, 1)] + [tc] * n,
                n,
                "tensor-conflict",
                18,
            )
        )
    for shift in [0, 1, 2, 5]:
        for n in [16, 64]:
            init = [
                v(0x0B, 1, 1, 0, 1),
                0x700002B7,
                v(0x14, 0, 17, 2, 10),
                v(0x25, 10, 2, 3, 10),
                v(0, 10, 5, 4, 10),
                (1 << 20) | (10 << 15) | (6 << 12) | 0x7B,
            ]
            # Make all test words initialized, then form 1/2/4/32-way bank conflicts.
            init += [
                v(0x14, 0, 17, 2, 10),
                v(0x28, 10, shift, 3, 10),
                v(0x25, 10, 2, 3, 10),
                v(0, 10, 5, 4, 10),
            ]
            load = (10 << 15) | (2 << 12) | (1 << 7) | 0x7B
            cases.append(
                emit(
                    destination,
                    f"lds-{1 << shift}way-{n}",
                    init + [load] * n,
                    n,
                    f"lds-{1 << shift}way",
                    None,
                )
            )
    (destination / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (destination / "pre_run_predictions.json").write_text(
        json.dumps(
            {
                "tensor_pipeline_cycles": 12,
                "collector_distinct_cycles": 3,
                "collector_conflict_cycles": 5,
                "scoreboard_clear_cycle": 1,
                "not_fitted": True,
                "cases": cases,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
