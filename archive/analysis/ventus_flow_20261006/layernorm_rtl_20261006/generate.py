"""Freeze executable FP32 LayerNorm kernels before RTL observations.

This independent ISA lowering uses full-lane LDS butterfly reductions. It is
not the masked pseudo-instruction template in transformer.Emitter.row_reduce.
"""

import argparse
import ctypes
import hashlib
import json
import struct
from dataclasses import asdict
from pathlib import Path

import numpy as np

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.program import Program, fp32_word, vector
from codesign.ventus.timing import build_graph

fmaf = ctypes.CDLL(None).fmaf
fmaf.argtypes = (ctypes.c_float, ctypes.c_float, ctypes.c_float)
fmaf.restype = ctypes.c_float


def decode(word):
    return struct.unpack("<f", struct.pack("<I", word))[0]


class Emitter:
    def __init__(self, width, seed, constant=False):
        if width not in (32, 64):
            raise ValueError("tested widths are 32/64")
        self.width = width
        self.x = [4.0 if constant else ((i * 7 + seed * 3) % 17 - 8) / 4 for i in range(width)]
        self.gamma = [0.5 + (i % 5) / 8 for i in range(width)]
        self.beta = [0.25 + (i % 7) / 16 for i in range(width)]
        self.pa = list(map(fp32_word, self.x))
        self.pb = list(map(fp32_word, self.gamma + self.beta))
        self.memory = {0x90000000 + 4 * i: v for i, v in enumerate(self.pa)}
        self.memory.update({0x90001000 + 4 * i: v for i, v in enumerate(self.pb)})
        self.values = {f"v{i}": [0] * 32 for i in range(32)}
        self.values.update({f"x{i}": 0 for i in range(32)})
        self.words, self.ops, self.stages = [], [], []

    def emit(self, word, kind, sources=(), dest=None, addresses=(), variant=None):
        pc = 0x80000000 + 4 * len(self.words)
        self.words.append(word)
        self.ops.append(
            Operation(
                f"pc{pc:08x}",
                kind,
                sources=tuple(sources),
                destination=dest,
                addresses=tuple(addresses),
                variant=variant,
            )
        )
        return pc

    def mark(self, name):
        operation = next(op for op in reversed(self.ops) if op.kind in {"fadd", "fma"})
        self.stages.append({"name": name, "pc": int(operation.name[2:], 16)})

    def scalar(self, reg, value):
        value &= 0xFFFFFFFF
        upper = (value + 0x800) & 0xFFFFF000
        lower = (value - upper) & 0xFFF
        self.emit(upper | reg << 7 | 0x37, "scalar", dest=f"x{reg}")
        if lower:
            self.emit(lower << 20 | reg << 15 | reg << 7 | 0x13, "scalar", (f"x{reg}",), f"x{reg}")
        self.values[f"x{reg}"] = value

    def constant(self, reg, value, *, bits=False):
        payload = value if bits else fp32_word(value)
        self.scalar(5, payload)
        self.emit(vector(0x17, 0, 5, 4, reg), "vector", ("x5",), f"v{reg}")
        self.values[f"v{reg}"] = [payload] * 32

    def copy(self, dest, source):
        if dest != source:
            self.emit(
                vector(0x0A, source, source, 0, dest),
                "vector",
                (f"v{source}", f"v{source}"),
                f"v{dest}",
            )
            self.values[f"v{dest}"] = self.values[f"v{source}"][:]

    def float_binary(self, dest, a, b, *, subtract=False):
        aa, bb = self.values[f"v{a}"][:], self.values[f"v{b}"][:]
        self.emit(
            vector(2 if subtract else 0, a if subtract else b, b if subtract else a, 1, dest),
            "fadd",
            (f"v{a}", f"v{b}"),
            f"v{dest}",
            variant="sub" if subtract else "add",
        )
        self.values[f"v{dest}"] = [
            fp32_word(decode(x) - decode(y) if subtract else decode(x) + decode(y))
            for x, y in zip(aa, bb)
        ]

    def fma(self, dest, a, b, c, *, negate=False):
        aa, bb, cc = (self.values[f"v{r}"][:] for r in (a, b, c))
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
        self.values[f"v{dest}"] = [
            fp32_word(fmaf(-decode(x) if negate else decode(x), decode(y), decode(z)))
            for x, y, z in zip(aa, bb, cc)
        ]

    def address(self, base, *, rotate=0):
        self.scalar(6, base)
        self.emit(vector(0x14, 0, 17, 2, 10), "vector", dest="v10")
        indices = list(range(32))
        if rotate:
            self.scalar(7, rotate)
            self.emit(vector(0, 10, 7, 4, 10), "vector", ("v10", "x7"), "v10")
            self.scalar(7, 31)
            self.emit(vector(0x09, 10, 7, 4, 10), "vector", ("v10", "x7"), "v10")
            indices = [(i + rotate) % 32 for i in indices]
        self.emit(vector(0x25, 10, 2, 3, 10), "vector", ("v10",), "v10")
        self.emit(vector(0, 10, 6, 4, 10), "vector", ("v10", "x6"), "v10")
        addresses = tuple(base + 4 * i for i in indices)
        self.values["v10"] = list(addresses)
        return addresses

    def load(self, reg, base, *, rotate=0):
        addresses = self.address(base, rotate=rotate)
        self.emit(10 << 15 | 2 << 12 | reg << 7 | 0x7B, "load", ("v10",), f"v{reg}", addresses)
        self.values[f"v{reg}"] = [self.memory[a] for a in addresses]

    def store(self, reg, base):
        addresses = self.address(base)
        pc = self.emit(
            reg << 20 | 10 << 15 | 6 << 12 | 0x7B, "store", ("v10", f"v{reg}"), addresses=addresses
        )
        for a, v in zip(addresses, self.values[f"v{reg}"]):
            self.memory[a] = v
        return pc

    def tree(self, reg, base):
        self.store(reg, base)
        for distance in (16, 8, 4, 2, 1):
            self.load(4, base, rotate=distance)
            self.float_binary(reg, reg, 4)
            self.store(reg, base)

    def build(self):
        for reg, value in [(31, 0.0), (16, 1 / self.width), (17, 1e-5), (18, 0.5), (19, 1.5)]:
            self.constant(reg, value)
        self.constant(20, 0x5F3759DF, bits=True)
        self.copy(1, 31)
        self.copy(2, 31)
        for chunk in range(self.width // 32):
            self.load(3, 0x90000000 + chunk * 128)
            self.float_binary(1, 1, 3)
            self.fma(2, 3, 3, 2)
        self.tree(1, 0x70000000)
        self.mark("sum_reduction")
        self.tree(2, 0x70000100)
        self.mark("squares_reduction")
        self.fma(1, 1, 16, 31)
        self.fma(2, 2, 16, 31)
        self.fma(2, 1, 1, 2, negate=True)
        self.float_binary(2, 2, 17)
        self.mark("variance_epsilon")
        self.copy(5, 2)
        self.emit(vector(0x28, 5, 1, 3, 5), "vector", ("v5",), "v5")
        self.values["v5"] = [x >> 1 for x in self.values["v5"]]
        self.emit(vector(2, 20, 5, 0, 5), "vector", ("v20", "v5"), "v5")
        self.values["v5"] = [
            (x - y) & 0xFFFFFFFF for x, y in zip(self.values["v20"], self.values["v5"])
        ]
        self.fma(8, 2, 18, 31)
        for _ in range(4):
            self.fma(6, 5, 5, 31)
            self.fma(7, 8, 6, 19, negate=True)
            self.fma(5, 5, 7, 31)
        self.mark("inverse_sqrt")
        for chunk in range(self.width // 32):
            self.load(3, 0x90000000 + chunk * 128)
            self.float_binary(3, 3, 1, subtract=True)
            self.fma(3, 3, 5, 31)
            self.load(6, 0x90001000 + chunk * 128)
            self.load(7, 0x90001000 + self.width * 4 + chunk * 128)
            self.fma(3, 3, 6, 7)
            self.mark(f"affine_chunk{chunk}")
            store_pc = self.store(3, 0x90002000 + chunk * 128)
        self.words.append(0x400B)
        expected = tuple(self.memory[0x90002000 + 4 * i] for i in range(self.width))
        x, g, b = map(lambda v: np.array(v, dtype=np.float64), (self.x, self.gamma, self.beta))
        dense = (x - x.mean()) / np.sqrt(np.mean((x - x.mean()) ** 2) + 1e-5) * g + b
        output = np.array(list(map(decode, expected)))
        error = float(np.max(np.abs(output - dense)))
        if error > 2e-6:
            raise ValueError(f"ISA reference differs from dense LayerNorm: {error}")
        program = Program(
            tuple(self.words),
            Workload(
                tuple(self.ops), vgpr_per_warp=32, sgpr_per_warp=16, lds_per_block=512
            ).validate(Hardware()),
            expected,
            tuple(self.pa),
            tuple(self.pb),
            self.stages[-1]["pc"],
            store_pc,
        )
        return program, dict(
            max_abs_error_vs_float64=error,
            input=self.x,
            gamma=self.gamma,
            beta=self.beta,
            epsilon=1e-5,
            stages=self.stages,
        )


def generate(out):
    out.mkdir()
    cases = []
    for width, seed, constant in [(32, 1, False), (64, 2, False), (64, 3, False), (64, 0, True)]:
        emitter = Emitter(width, seed, constant)
        program, metadata = emitter.build()
        name = f"layernorm-d{width}-s{seed}-c{int(constant)}"
        path = out / name
        program.write(
            path,
            Path(
                "analysis/ventus_flow_20261006/search_model/kernel-probes-v3/stream-4-rf0-lds1/input"
            ),
        )
        # Enlarge the output allocation; preserve all other driver buffers.
        lines = (path / "input.metadata").read_text().splitlines()
        meta = [int(lines[i], 16) | int(lines[i + 1], 16) << 32 for i in range(0, len(lines), 2)]
        data = [int(x, 16) for x in (path / "input.data").read_text().splitlines()]
        count = meta[13]
        sizes = meta[14 + count : 14 + 2 * count]
        pos = meta[14 : 14 + count].index(0x90002000)
        offset = sum(sizes[:pos]) // 4
        data[offset : offset + sizes[pos] // 4] = [0] * width
        meta[14 + count + pos] = meta[14 + 2 * count + pos] = width * 4
        (path / "input.metadata").write_text(
            "".join(f"{v & 0xFFFFFFFF:08x}\n{v >> 32:08x}\n" for v in meta)
        )
        (path / "input.data").write_text("".join(f"{v:08x}\n" for v in data))
        graph = build_graph(program.workload, Hardware())
        result = execute(graph)
        for stage in metadata["stages"]:
            stage["predicted"] = result["times"][
                graph.names.index(f"pc{stage['pc']:08x}.writeback")
            ]
        cases.append(
            dict(
                name=name,
                width=width,
                seed=seed,
                constant=constant,
                words=list(program.words),
                workload=asdict(program.workload),
                expected_words=list(program.expected),
                prediction=metadata["stages"][-1]["predicted"],
                predicted_visible=result["times"][graph.names.index("outputs.visible")],
                metadata=metadata,
                input_sha256={
                    n: hashlib.sha256((path / n).read_bytes()).hexdigest()
                    for n in ("input.metadata", "input.data")
                },
            )
        )
    frozen = dict(
        version=MODEL_VERSION,
        code_sha256=model_hashes(),
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        initial_state="SRAM reset finished; cold caches; gate=512",
        window="first collector -> last affine WB; separate output visibility",
        software="full-lane LDS butterfly + bit seed + four correct rsqrt Newton iterations",
        cases=cases,
    )
    (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (out / "pre_run_predictions.json").write_text(json.dumps(frozen, indent=2) + "\n")
    print(
        json.dumps([{k: c[k] for k in ("name", "prediction", "predicted_visible")} for c in cases])
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    generate(parser.parse_args().out)
