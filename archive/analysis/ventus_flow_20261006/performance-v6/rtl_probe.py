"""Freeze actual Tensor/FMA/FADD/FCMP programs for bounded fresh RTL checks."""

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.program import fp32_word, packed_gemm, vector
from codesign.ventus.timing import build_graph

root = Path("analysis/ventus_flow_20261006/performance-v6")
dest = root / "mixed-probes"
dest.mkdir()
cases = []
for warps in (1, 2):
    for pattern in ("mixed", "fma"):
        base = packed_gemm(1, strategy="resident")
        prefix = (base.final_tensor_pc - 0x80000000) // 4 + 1
        words = list(base.words[:prefix])
        ops = list(base.workload.operations[:prefix])

        def emit(word, kind, sources=(), dest=None, addresses=()):
            name = f"pc{0x80000000 + len(words) * 4:08x}"
            words.append(word)
            ops.append(
                Operation(name, kind, sources=sources, destination=dest, addresses=addresses)
            )
            return 0x80000000 + (len(words) - 1) * 4

        for reg in (4, 5, 6):
            emit(vector(0x0B, reg, reg, 0, reg), "vector", (f"v{reg}", f"v{reg}"), f"v{reg}")
        for i in range(12):
            emit(vector(0x2C, 2, 3, 1, 4), "fma", ("v3", "v2", "v4"), "v4")
            if pattern == "mixed":
                emit(vector(0, 3, 2, 1, 5), "fadd", ("v2", "v3"), "v5")
                emit(vector(6, 3, 2, 1, 6), "fmax", ("v2", "v3"), "v6")
                emit(
                    3 << 26 | 1 << 25 | 3 << 20 | 2 << 15 | 4 << 12 | 1 << 7 | 0x0B,
                    "tensor",
                    ("v2", "v3", "v1"),
                    "v1",
                )
        final = 0x80000000 + (len(words) - 1) * 4
        # Store private 3*128 bytes per warp; CSR threadid gives warp*32.
        emit(0x90002137, "scalar", dest="x2")
        emit((0x800 << 20) | (2 << 12) | (17 << 7) | 0x73, "scalar", dest="x17")
        emit((12 << 20) | (7 << 7) | 0x13, "scalar", ("x0",), "x7")
        # mul x17,x17,x7 (RISC-V M extension)
        emit((1 << 25) | (7 << 20) | (17 << 15) | (17 << 7) | 0x33, "scalar", ("x17", "x7"), "x17")
        for index, reg in enumerate((4, 5, 6)):
            emit(vector(0x14, 0, 17, 2, 14), "vector", dest="v14")
            emit(vector(0x25, 14, 2, 3, 14), "vector", ("v14",), "v14")
            emit(vector(0, 14, 2, 4, 14), "vector", ("v14", "x2"), "v14")
            emit(vector(0, 14, 17, 4, 14), "vector", ("v14", "x17"), "v14")
            if index:
                emit((index * 128 << 20) | (8 << 7) | 0x13, "scalar", ("x0",), "x8")
                emit(vector(0, 14, 8, 4, 14), "vector", ("v14", "x8"), "v14")
            emit(
                reg << 20 | 14 << 15 | 6 << 12 | 0x7B,
                "store",
                ("v14", f"v{reg}"),
                addresses=tuple(0x90002000 + index * 128 + i * 4 for i in range(32)),
            )
        words.append(0x400B)
        import struct

        def decode(w):
            return struct.unpack("<f", struct.pack("<I", w))[0]

        a = list(map(decode, base.panels_a[:32]))
        b = list(map(decode, base.panels_b[:32]))
        expected = (
            tuple(fp32_word(sum((x * y for _ in range(12)), 0.0)) for x, y in zip(a, b))
            + tuple(fp32_word(x + y if pattern == "mixed" else 0) for x, y in zip(a, b))
            + tuple(fp32_word(max(x, y) if pattern == "mixed" else 0) for x, y in zip(a, b))
        )
        name = f"{pattern}-w{warps}"
        path = dest / name
        replace(base, words=tuple(words)).write(
            path,
            Path(
                "analysis/ventus_flow_20261006/search_model/kernel-probes-v3/stream-4-rf0-lds1/input"
            ),
        )
        lines = (path / "input.metadata").read_text().splitlines()
        meta = [int(lines[i], 16) | int(lines[i + 1], 16) << 32 for i in range(0, len(lines), 2)]
        data = [int(x, 16) for x in (path / "input.data").read_text().splitlines()]
        count = meta[13]
        sizes = meta[14 + count : 14 + 2 * count]
        pos = meta[14 : 14 + count].index(0x90002000)
        offset = sum(sizes[:pos]) // 4
        data[offset : offset + sizes[pos] // 4] = [0] * 96 * warps
        meta[6] = warps
        meta[14 + count + pos] = meta[14 + 2 * count + pos] = 384 * warps
        (path / "input.metadata").write_text(
            "".join(f"{x & 0xFFFFFFFF:08x}\n{x >> 32:08x}\n" for x in meta)
        )
        (path / "input.data").write_text("".join(f"{x:08x}\n" for x in data))
        # Model only the frozen compute window, excluding CSR/multiply epilogue.
        prefix_ops = ops[: (final - 0x80000000) // 4 + 1]
        workload = Workload(
            tuple(
                replace(op, name=f"w{warp}.{op.name}", warp=warp)
                for op in prefix_ops
                for warp in range(warps)
            ),
            warps_per_block=warps,
            lds_per_block=0,
        )
        g = build_graph(workload, Hardware())
        r = execute(g)
        cases.append(
            dict(
                name=name,
                warps=warps,
                words=words,
                expected_words=list(expected) * warps,
                final_pc=final,
                workload=asdict(workload),
                prediction=r["cycles"],
                input_sha256={
                    n: hashlib.sha256((path / n).read_bytes()).hexdigest()
                    for n in ("input.metadata", "input.data")
                },
            )
        )
(dest / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
(dest / "pre_run_predictions.json").write_text(
    json.dumps(dict(code_sha256=model_hashes(), cases=cases), indent=2) + "\n"
)
print([(c["name"], c["prediction"]) for c in cases])
