"""Paired ISA/timing lowering of the tested full-lane FP32 LayerNorm.

No tensor arithmetic is performed here. Addresses and constants are concrete;
whole rows use 32-lane LDS butterfly reductions and four Newton iterations.
"""

from .ir import Operation
from .program import fp32_word, vector


class LayerNormEmitter:
    def __init__(
        self, width, source, gamma, beta, output, scratch, *, block=0, warp=0, prefix="ln"
    ):
        if type(width) is not int or width < 32 or width % 32:
            raise ValueError("executable LayerNorm needs a multiple of 32 columns")
        self.width = width
        self.source, self.gamma, self.beta, self.output, self.scratch = (
            source,
            gamma,
            beta,
            output,
            scratch,
        )
        self.block, self.warp, self.prefix = block, warp, prefix
        self.words, self.ops = [], []

    def emit(self, word, kind, sources=(), dest=None, addresses=(), variant=None):
        self.words.append(word)
        self.ops.append(
            Operation(
                f"{self.prefix}.i{len(self.ops)}",
                kind,
                self.block,
                self.warp,
                tuple(sources),
                dest,
                tuple(addresses),
                variant=variant,
            )
        )

    def scalar(self, reg, value):
        value &= 0xFFFFFFFF
        upper = (value + 0x800) & 0xFFFFF000
        lower = (value - upper) & 0xFFF
        self.emit(upper | reg << 7 | 0x37, "scalar", dest=f"x{reg}")
        if lower:
            self.emit(lower << 20 | reg << 15 | reg << 7 | 0x13, "scalar", (f"x{reg}",), f"x{reg}")

    def constant(self, reg, value, *, bits=False):
        self.scalar(5, value if bits else fp32_word(value))
        self.emit(vector(0x17, 0, 5, 4, reg), "vector", ("x5",), f"v{reg}")

    def copy(self, dest, source):
        if dest != source:
            self.emit(
                vector(0x0A, source, source, 0, dest),
                "vector",
                (f"v{source}", f"v{source}"),
                f"v{dest}",
            )

    def add(self, dest, a, b, *, subtract=False):
        self.emit(
            vector(2 if subtract else 0, a if subtract else b, b if subtract else a, 1, dest),
            "fadd",
            (f"v{a}", f"v{b}"),
            f"v{dest}",
            variant="sub" if subtract else "add",
        )

    def fma(self, dest, a, b, c, *, negate=False):
        if dest != c and dest in (a, b):
            self.copy(30, dest)
            a = 30 if a == dest else a
            b = 30 if b == dest else b
        self.copy(dest, c)
        self.emit(
            vector(0x2F if negate else 0x2C, b, a, 1, dest),
            "fma",
            (f"v{a}", f"v{b}", f"v{dest}"),
            f"v{dest}",
            variant="fnmadd" if negate else "fmadd",
        )

    def memory(self, kind, reg, base, *, rotate=0):
        self.scalar(6, base)
        self.emit(vector(0x14, 0, 17, 2, 10), "vector", dest="v10")
        if rotate:
            self.scalar(7, rotate)
            self.emit(vector(0, 10, 7, 4, 10), "vector", ("v10", "x7"), "v10")
            self.scalar(7, 31)
            self.emit(vector(0x09, 10, 7, 4, 10), "vector", ("v10", "x7"), "v10")
        self.emit(vector(0x25, 10, 2, 3, 10), "vector", ("v10",), "v10")
        self.emit(vector(0, 10, 6, 4, 10), "vector", ("v10", "x6"), "v10")
        addresses = tuple(base + 4 * ((i + rotate) % 32) for i in range(32))
        if kind == "load":
            self.emit(10 << 15 | 2 << 12 | reg << 7 | 0x7B, kind, ("v10",), f"v{reg}", addresses)
        else:
            self.emit(
                reg << 20 | 10 << 15 | 6 << 12 | 0x7B, kind, ("v10", f"v{reg}"), addresses=addresses
            )

    def tree(self, reg, base):
        self.memory("store", reg, base)
        for distance in (16, 8, 4, 2, 1):
            self.memory("load", 4, base, rotate=distance)
            self.add(reg, reg, 4)
            self.memory("store", reg, base)

    def build(self):
        for reg, value in [(31, 0.0), (16, 1 / self.width), (17, 1e-5), (18, 0.5), (19, 1.5)]:
            self.constant(reg, value)
        self.constant(20, 0x5F3759DF, bits=True)
        self.copy(1, 31)
        self.copy(2, 31)
        for chunk in range(self.width // 32):
            self.memory("load", 3, self.source + chunk * 128)
            self.add(1, 1, 3)
            self.fma(2, 3, 3, 2)
        self.tree(1, self.scratch)
        self.tree(2, self.scratch + 256)
        self.fma(1, 1, 16, 31)
        self.fma(2, 2, 16, 31)
        self.fma(2, 1, 1, 2, negate=True)
        self.add(2, 2, 17)
        self.copy(5, 2)
        self.emit(vector(0x28, 5, 1, 3, 5), "vector", ("v5",), "v5")
        self.emit(vector(2, 20, 5, 0, 5), "vector", ("v20", "v5"), "v5")
        self.fma(8, 2, 18, 31)
        for _ in range(4):
            self.fma(6, 5, 5, 31)
            self.fma(7, 8, 6, 19, negate=True)
            self.fma(5, 5, 7, 31)
        for chunk in range(self.width // 32):
            self.memory("load", 3, self.source + chunk * 128)
            self.add(3, 3, 1, subtract=True)
            self.fma(3, 3, 5, 31)
            self.memory("load", 6, self.gamma + chunk * 128)
            self.memory("load", 7, self.beta + chunk * 128)
            self.fma(3, 3, 6, 7)
            self.memory("store", 3, self.output + chunk * 128)
        return tuple(self.words) + (0x400B,), tuple(self.ops)
