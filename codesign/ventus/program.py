"""Small executable FP32 GEMM family paired with its exact timing IR.

One warp computes a 4x4 output. Packed 4x8 / 8x4 input panels repeat,
so hoisting their loads is numerically legal. No measured timing enters IR.
This is a bounded ISA emitter, not a general compiler or functional simulator.
"""

import hashlib
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Hardware
from .ir import Operation, Workload


def vector(fn, rs2, rs1, mode, rd):
    return (fn << 26) | (1 << 25) | (rs2 << 20) | (rs1 << 15) | (mode << 12) | (rd << 7) | 0x57


def fp32_word(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


@dataclass(frozen=True)
class Program:
    words: tuple[int, ...]
    workload: Workload
    expected: tuple[int, ...]
    panels_a: tuple[int, ...]
    panels_b: tuple[int, ...]
    final_tensor_pc: int
    output_store_pc: int

    def write(self, destination: Path, fixture: Path):
        """Reuse only the upstream driver's allocation/metadata ABI."""
        destination.mkdir()
        lines = fixture.with_suffix(".metadata").read_text().splitlines()
        meta = [int(lines[i], 16) | (int(lines[i + 1], 16) << 32) for i in range(0, len(lines), 2)]
        data = [int(x, 16) for x in fixture.with_suffix(".data").read_text().splitlines()]
        count = meta[13]
        bases = meta[14 : 14 + count]
        sizes = meta[14 + count : 14 + 2 * count]
        segments = []
        offset = 0
        for size in sizes:
            segments.append(data[offset : offset + size // 4])
            offset += size // 4
        for address, payload in [
            (0x80000000, self.words),
            (0x90000000, self.panels_a),
            (0x90001000, self.panels_b),
        ]:
            pos = bases.index(address)
            new_size = max(sizes[pos], len(payload) * 4)
            segments[pos] = list(payload) + [0] * (new_size // 4 - len(payload))
            meta[14 + count + pos] = new_size
            meta[14 + 2 * count + pos] = new_size
        meta[2], meta[5], meta[6] = 1, 32, 1
        (destination / "input.metadata").write_text(
            "".join(f"{x & 0xFFFFFFFF:08x}\n{x >> 32:08x}\n" for x in meta)
        )
        (destination / "input.data").write_text(
            "".join(f"{x:08x}\n" for segment in segments for x in segment)
        )
        return {
            "input_sha256": {
                name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                for name in ["input.metadata", "input.data"]
            },
            "expected_words": list(self.expected),
            "final_tensor_pc": self.final_tensor_pc,
            "output_store_pc": self.output_store_pc,
            "workload": asdict(self.workload),
            "instruction_count": len(self.words),
        }


def packed_gemm(steps=8, *, strategy="stream", rf_conflict=False, lds_stride=1):
    if type(steps) is not int or not 1 <= steps <= 32:
        raise ValueError("steps must be an integer in [1,32]")
    if strategy not in {"stream", "reload", "resident", "shared"}:
        raise ValueError("unknown GEMM strategy")
    if lds_stride not in {1, 2, 4}:
        raise ValueError("LDS stride must be 1, 2 or 4")
    a, b, c = (5, 9, 1) if rf_conflict else (2, 3, 1)
    words, ops = [], []

    def emit(word, kind, sources=(), destination=None, addresses=(), dependencies=()):
        name = f"pc{0x80000000 + len(words) * 4:08x}"
        words.append(word)
        ops.append(
            Operation(
                name,
                kind,
                sources=sources,
                destination=destination,
                addresses=addresses,
                dependencies=dependencies,
            )
        )
        return name

    def vid(rd):
        emit(vector(0x14, 0, 17, 2, rd), "vector", destination=f"v{rd}")

    def address(rd, scalar, base, shift=2):
        emit((base & 0xFFFFF000) | (scalar << 7) | 0x37, "scalar", destination=f"x{scalar}")
        if base & 0xFFF:
            emit(
                ((base & 0xFFF) << 20) | (scalar << 15) | (scalar << 7) | 0x13,
                "scalar",
                (f"x{scalar}",),
                f"x{scalar}",
            )
        vid(rd)
        emit(vector(0x25, rd, shift, 3, rd), "vector", (f"v{rd}",), f"v{rd}")
        emit(vector(0, rd, scalar, 4, rd), "vector", (f"v{rd}", f"x{scalar}"), f"v{rd}")

    def load(reg, addr, addresses, dependencies=()):
        return emit(
            (addr << 15) | (2 << 12) | (reg << 7) | 0x7B,
            "load",
            (f"v{addr}",),
            f"v{reg}",
            addresses,
            dependencies,
        )

    def store(reg, addr, addresses):
        return emit(
            (reg << 20) | (addr << 15) | (6 << 12) | 0x7B,
            "store",
            (f"v{addr}", f"v{reg}"),
            addresses=addresses,
        )

    emit(vector(0x0B, c, c, 0, c), "vector", (f"v{c}", f"v{c}"), f"v{c}")
    address(10, 5, 0x90000000)
    address(11, 6, 0x90001000)
    if strategy == "stream" or strategy == "shared":
        emit((128 << 20) | (7 << 7) | 0x13, "scalar", ("x0",), "x7")
    if strategy == "shared":
        address(12, 8, 0x70000000, 2 + (lds_stride.bit_length() - 1))
        address(13, 9, 0x70000200, 2 + (lds_stride.bit_length() - 1))
    for step in range(steps):
        if strategy != "resident" or step == 0:
            offset = step * 128 if strategy in {"stream", "shared"} else 0
            load(a, 10, tuple(0x90000000 + offset + i * 4 for i in range(32)))
            load(b, 11, tuple(0x90001000 + offset + i * 4 for i in range(32)))
            if strategy == "shared":
                for reg, addr, base in [(a, 12, 0x70000000), (b, 13, 0x70000200)]:
                    addresses = tuple(base + i * lds_stride * 4 for i in range(32))
                    store(reg, addr, addresses)
                    # AddrCalculate and the LDS request port preserve memory order.
                    # A following load need not await the store's completion response.
                    load(reg, addr, addresses)
            if strategy in {"stream", "shared"} and step + 1 < steps:
                for addr in [10, 11]:
                    emit(vector(0, addr, 7, 4, addr), "vector", (f"v{addr}", "x7"), f"v{addr}")
        final_tensor_pc = 0x80000000 + len(words) * 4
        emit(
            (3 << 26) | (1 << 25) | (b << 20) | (a << 15) | (4 << 12) | (c << 7) | 0x0B,
            "tensor",
            (f"v{a}", f"v{b}", f"v{c}"),
            f"v{c}",
        )
    address(14, 2, 0x90002000)
    output_store_pc = 0x80000000 + len(words) * 4
    store(c, 14, tuple(0x90002000 + i * 4 for i in range(32)))
    words.append(0x400B)
    # Distinct signed, small integer-valued FP32 inputs make exact bit comparison possible.
    panel_a = [[(row * 3 + red) % 7 - 3 for red in range(8)] for row in range(4)]
    panel_b = [[(col * 2 + red) % 5 - 2 for red in range(8)] for col in range(4)]
    expected = [
        sum(panel_a[row][red] * panel_b[col][red] for red in range(8)) * steps
        for row in range(4)
        for col in range(4)
    ] + [0] * 16
    return Program(
        tuple(words),
        Workload(tuple(ops)).validate(Hardware()),
        tuple(map(fp32_word, expected)),
        tuple(fp32_word(x) for row in panel_a for x in row) * steps,
        tuple(fp32_word(x) for row in panel_b for x in row) * steps,
        final_tensor_pc,
        output_store_pc,
    )
