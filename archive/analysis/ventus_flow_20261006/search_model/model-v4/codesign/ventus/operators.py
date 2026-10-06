"""Executable fused epilogues and FFN, with explicit Tensor layout conversion.

All matrices are independently populated; integer-valued FP32 inputs keep the
reference exact. Stage boundaries refer to real PCs, never measured durations.
"""

from dataclasses import dataclass

from .config import Hardware
from .ir import Operation, Workload
from .program import Program, fp32_word, vector


def reference(depth, hidden, residual, seed):
    """Dense operator reference, independent of instruction packing."""
    x = [[(r * 3 + k * 2 + seed) % 7 - 3 for k in range(depth)] for r in range(4)]
    w1 = [[(k * 3 + j * 2 + seed) % 5 - 2 for j in range(hidden)] for k in range(depth)]
    bias1 = [(j + seed) % 5 - 2 for j in range(hidden)]
    h = [
        [max(0, sum(x[r][k] * w1[k][j] for k in range(depth)) + bias1[j]) for j in range(hidden)]
        for r in range(4)
    ]
    w2 = [[(k * 2 + j * 3 + seed) % 7 - 3 for j in range(4)] for k in range(hidden)]
    bias2 = [(j + seed) % 3 - 1 for j in range(4)]
    skip = [[(r * 2 + j + seed) % 5 - 2 for j in range(4)] for r in range(4)]
    y = [
        [
            sum(h[r][k] * w2[k][j] for k in range(hidden))
            + bias2[j]
            + (skip[r][j] if residual else 0)
            for j in range(4)
        ]
        for r in range(4)
    ]
    return x, w1, bias1, h, w2, bias2, skip, y


@dataclass(frozen=True)
class OperatorProgram:
    program: Program
    stages: tuple[tuple[str, int], ...]
    output_compute_pc: int


def fused_operator(*, kind="ffn", depth=16, hidden=8, intermediate="lds", residual=False, seed=1):
    if kind not in {"epilogue", "ffn"} or intermediate not in {"lds", "global"}:
        raise ValueError("unknown operator or intermediate storage")
    if type(depth) is not int or depth not in {8, 16, 24, 32}:
        raise ValueError("depth must be 8, 16, 24 or 32")
    if type(hidden) is not int or hidden not in {4, 8, 16}:
        raise ValueError("hidden must be 4, 8 or 16")
    if kind == "epilogue" and (hidden != 4 or residual):
        raise ValueError("epilogue has four columns and no residual")
    if kind == "ffn" and hidden == 4:
        raise ValueError("FFN hidden size must be a multiple of Tensor reduction size eight")
    if type(seed) is not int or not 0 <= seed <= 10 or type(residual) is not bool:
        raise ValueError("invalid seed/residual")
    x, w1, bias1, h, w2, bias2, skip, y = reference(depth, hidden, residual, seed)
    words, ops, pa, pb, stages = [], [], [], [], []

    def emit(word, kind, sources=(), destination=None, addresses=()):
        pc = 0x80000000 + 4 * len(words)
        words.append(word)
        ops.append(
            Operation(
                f"pc{pc:08x}", kind, sources=sources, destination=destination, addresses=addresses
            )
        )
        return pc

    def zero(reg):
        return emit(vector(0x0B, reg, reg, 0, reg), "vector", (f"v{reg}", f"v{reg}"), f"v{reg}")

    def vid(reg):
        emit(vector(0x14, 0, 17, 2, reg), "vector", destination=f"v{reg}")

    def immediate(fn, reg, value):
        emit(vector(fn, reg, value, 3, reg), "vector", (f"v{reg}",), f"v{reg}")

    def base(reg, scalar, addr):
        upper = (addr + 0x800) & 0xFFFFF000
        lower = addr - upper
        emit(upper | scalar << 7 | 0x37, "scalar", destination=f"x{scalar}")
        if lower:
            emit(
                (lower & 0xFFF) << 20 | scalar << 15 | scalar << 7 | 0x13,
                "scalar",
                (f"x{scalar}",),
                f"x{scalar}",
            )
        emit(vector(0, reg, scalar, 4, reg), "vector", (f"v{reg}", f"x{scalar}"), f"v{reg}")

    def address(reg, scalar, addr):
        vid(reg)
        immediate(0x25, reg, 2)
        base(reg, scalar, addr)

    def scatter(addr, width, col):
        # C is 4x4 in lanes 0..15. Lanes 16..31 contain zero; store them
        # into four extra rows, avoiding predication and overlapping writes.
        vid(12)
        vid(15)
        immediate(0x28, 12, 2)
        immediate(0x25, 12, (width * 4).bit_length() - 1)
        immediate(0x09, 15, 3)
        immediate(0x25, 15, 2)
        emit(vector(0, 12, 15, 0, 12), "vector", ("v12", "v15"), "v12")
        base(12, 8, addr + col * 4)
        return tuple(addr + ((i // 4) * width + i % 4 + col) * 4 for i in range(32))

    def load(reg, adr, addresses):
        return emit(
            adr << 15 | 2 << 12 | reg << 7 | 0x7B, "load", (f"v{adr}",), f"v{reg}", addresses
        )

    def store(reg, adr, addresses):
        return emit(
            reg << 20 | adr << 15 | 6 << 12 | 0x7B,
            "store",
            (f"v{adr}", f"v{reg}"),
            addresses=addresses,
        )

    def constant(reg, payload, pool, adr):
        address_value = (0x90000000 if pool is pa else 0x90001000) + len(pool) * 4
        pool.extend(fp32_word(v) for v in payload)
        if len(pool) * 4 > (4096 if pool is pa else 3072):
            raise ValueError("fixture constants exceed allocated buffer")
        address(adr, 5 if pool is pa else 6, address_value)
        load(reg, adr, tuple(address_value + i * 4 for i in range(32)))

    def tensor():
        return emit(
            3 << 26 | 1 << 25 | 3 << 20 | 2 << 15 | 4 << 12 | 1 << 7 | 0x0B,
            "tensor",
            ("v2", "v3", "v1"),
            "v1",
        )

    def add_bias(values):
        constant(4, list(values) * 4 + [0] * 16, pa, 10)
        return emit(vector(0, 4, 1, 1, 1), "fadd", ("v1", "v4"), "v1")

    zero(28)
    intermediate_base = 0x70000000 if intermediate == "lds" else 0x90001C00
    for col in range(0, hidden, 4):
        zero(1)
        for start in range(0, depth, 8):
            constant(2, [x[r][k] for r in range(4) for k in range(start, start + 8)], pa, 10)
            constant(
                3, [w1[k][j] for j in range(col, col + 4) for k in range(start, start + 8)], pb, 11
            )
            tc_pc = tensor()
        stages.append((f"first_gemm_tile{col // 4}", tc_pc))
        add_bias(bias1[col : col + 4])
        relu_pc = emit(vector(6, 28, 1, 1, 1), "fmax", ("v1", "v28"), "v1")
        stages.append((f"relu_tile{col // 4}", relu_pc))
        if kind == "ffn":
            store(1, 12, scatter(intermediate_base, hidden, col))
    if kind == "ffn":
        zero(1)
        for start in range(0, hidden, 8):
            # Pack four rows by gathering each row's eight consecutive elements.
            vid(13)
            vid(15)
            immediate(0x28, 13, 3)
            immediate(0x25, 13, (hidden * 4).bit_length() - 1)
            immediate(0x09, 15, 7)
            immediate(0x25, 15, 2)
            emit(vector(0, 13, 15, 0, 13), "vector", ("v13", "v15"), "v13")
            base(13, 9, intermediate_base + start * 4)
            load(
                2,
                13,
                tuple(
                    intermediate_base + ((i // 8) * hidden + i % 8 + start) * 4 for i in range(32)
                ),
            )
            constant(3, [w2[k][j] for j in range(4) for k in range(start, start + 8)], pb, 11)
            tc_pc = tensor()
        stages.append(("second_gemm", tc_pc))
        end_pc = add_bias(bias2)
        stages.append(("second_bias", end_pc))
        if residual:
            constant(6, [v for row in skip for v in row] + [0] * 16, pa, 10)
            end_pc = emit(vector(0, 6, 1, 1, 1), "fadd", ("v1", "v6"), "v1")
            stages.append(("residual", end_pc))
        expected = [v for row in y for v in row] + [0] * 16
    else:
        end_pc = relu_pc
        expected = [v for row in h for v in row] + [0] * 16
    address(14, 2, 0x90002000)
    out_pc = store(1, 14, tuple(0x90002000 + i * 4 for i in range(32)))
    words.append(0x400B)
    program = Program(
        tuple(words),
        Workload(tuple(ops)).validate(Hardware()),
        tuple(map(fp32_word, expected)),
        tuple(pa),
        tuple(pb),
        tc_pc,
        out_pc,
    )
    return OperatorProgram(program, tuple(stages), end_pc)
