"""Bounded real-ISA nonlinear chains and concurrent mixed-memory experiments."""

import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.program import Program, fp32_word, vector
from codesign.ventus.timing import build_graph

ROOT = Path(__file__).parent
FLOW = ROOT.parent
sys.path.insert(0, str(FLOW / "performance-v7"))
from memory_probes import build as memory_program  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "ln_numeric", FLOW / "layernorm_rtl_20261006/generate.py"
)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


class Nonlinear(reference.Emitter):
    def __init__(self, *, chain=False):
        super().__init__(32, 1)
        self.chain = chain
        if chain:
            self.x = [reference.decode(w) for w in memory_program("resident").expected]
            self.pa = list(map(fp32_word, self.x))
            self.memory = {0x90002000 + 4 * i: w for i, w in enumerate(self.pa)}
            self.memory.update({0x90100100 + 4 * i: w for i, w in enumerate(self.pb)})

    def load(self, reg, base, *, rotate=0):
        if self.chain:
            if 0x90000000 <= base < 0x90000080:
                base += 0x2000
            elif 0x90001000 <= base < 0x90001100:
                base += 0xFF100
        super().load(reg, base, rotate=rotate)

    def maximum(self, dest, a, b):
        aa, bb = self.values[f"v{a}"][:], self.values[f"v{b}"][:]
        self.emit(vector(6, b, a, 1, dest), "fmax", (f"v{a}", f"v{b}"), f"v{dest}")
        self.values[f"v{dest}"] = [
            fp32_word(max(reference.decode(x), reference.decode(y))) for x, y in zip(aa, bb)
        ]

    def exp(self, src, dest):
        # exp(x/16), degree8 Horner, then four squarings. Tested input range
        # [-4,8]; this is a declared concrete implementation, not official libm.
        self.constant(16, 1 / 16)
        self.fma(12, src, 16, 31)
        self.constant(17, 1 / math.factorial(8))
        self.copy(13, 17)
        for degree in range(7, -1, -1):
            self.constant(17, 1 / math.factorial(degree))
            self.fma(13, 13, 12, 17)
        for _ in range(4):
            self.fma(13, 13, 13, 31)
        self.copy(dest, 13)

    def reciprocal(self, src, dest):
        self.constant(18, 0x7EF311C3, bits=True)
        self.copy(dest, src)
        self.emit(vector(2, 18, dest, 0, dest), "vector", ("v18", f"v{dest}"), f"v{dest}")
        self.values[f"v{dest}"] = [(0x7EF311C3 - w) & 0xFFFFFFFF for w in self.values[f"v{src}"]]
        self.constant(19, 2)
        for _ in range(4):
            self.fma(14, src, dest, 19, negate=True)
            self.fma(dest, dest, 14, 31)

    def gelu(self):
        self.constant(31, 0)
        self.load(1, 0x90002000)
        self.fma(3, 1, 1, 31)
        self.fma(3, 3, 1, 31)
        self.constant(16, 0.044715)
        self.fma(3, 3, 16, 1)
        self.constant(16, 2 * math.sqrt(2 / math.pi))
        self.fma(3, 3, 16, 31)
        self.exp(3, 4)
        self.constant(16, 1)
        self.float_binary(3, 4, 16, subtract=True)
        self.float_binary(5, 4, 16)
        self.reciprocal(5, 6)
        self.fma(3, 3, 6, 31)
        self.float_binary(3, 3, 16)
        self.constant(16, 0.5)
        self.fma(1, 1, 16, 31)
        self.fma(1, 1, 3, 31)
        self.mark("gelu")
        self.store(1, 0x90002000)

    def softmax(self):
        self.constant(31, 0)
        source = 0x90002000 if self.chain else 0x90000000
        # Bypass the LayerNorm input relocation hook for the actual source.
        reference.Emitter.load(self, 1, source)
        self.copy(2, 1)
        self.store(2, 0x70000000)
        for distance in (16, 8, 4, 2, 1):
            self.load(4, 0x70000000, rotate=distance)
            self.maximum(2, 2, 4)
            self.store(2, 0x70000000)
        self.float_binary(1, 1, 2, subtract=True)
        self.exp(1, 3)
        self.copy(1, 3)
        self.copy(2, 3)
        self.tree(2, 0x70000100)
        self.reciprocal(2, 5)
        self.fma(1, 1, 5, 31)
        self.mark("softmax_normalize")
        self.store(1, 0x90002000)

    def program(self):
        prefix = memory_program("resident") if self.chain else None
        if self.chain:
            super().build()
            self.words.pop()  # remove ENDPRG before continuing the same program
            self.gelu()
        self.softmax()
        self.words.append(0x400B)
        prefix_words = prefix.words[:-1] if prefix else ()
        prefix_ops = prefix.workload.operations if prefix else ()
        offset = len(prefix_words)
        words = (*prefix_words, *self.words)
        ops = tuple(
            replace(op, name=f"pc{0x80000000 + 4 * i:08x}")
            for i, op in enumerate((*prefix_ops, *self.ops))
        )
        expected = tuple(self.memory[0x90002000 + 4 * i] for i in range(32))
        x = np.array(self.x, dtype=np.float64)
        if self.chain:
            x = (x - x.mean()) / np.sqrt(np.mean((x - x.mean()) ** 2) + 1e-5) * np.array(
                self.gamma
            ) + np.array(self.beta)
            x = 0.5 * x * (1 + np.tanh(np.sqrt(2 / np.pi) * (x + 0.044715 * x**3)))
        dense = np.exp(x - x.max())
        dense /= dense.sum()
        error = float(np.max(np.abs(np.array(list(map(reference.decode, expected))) - dense)))
        if error > 5e-6:
            raise ValueError(f"dense reference error {error}")
        last = self.stages[-1]["pc"] + offset * 4
        program = Program(
            tuple(words),
            Workload(ops, lds_per_block=512),
            expected,
            prefix.panels_a if prefix else tuple(self.pa),
            prefix.panels_b + (0,) * 32 + tuple(self.pb) if prefix else tuple(self.pb),
            last,
            0x80000000 + 4 * (len(words) - 2),
        )
        return program, dict(
            max_abs_error_vs_float64=error,
            stages=[{**s, "pc": s["pc"] + offset * 4} for s in self.stages],
        )


def multi(strategy, warps):
    source = memory_program(strategy)
    # Replace output address setup with CSR.threadid-derived private warp slice.
    prefix = len(source.words) - 6
    ewords = list(source.words[:prefix])
    eops = list(source.workload.operations[:prefix])

    def emit(word, kind, sources=(), dest=None, addresses=()):
        pc = 0x80000000 + 4 * len(ewords)
        ewords.append(word)
        eops.append(
            Operation(
                f"pc{pc:08x}",
                kind,
                sources=tuple(sources),
                destination=dest,
                addresses=tuple(addresses),
            )
        )

    emit(0x90002337, "scalar", dest="x6")
    emit(vector(0x14, 0, 17, 2, 10), "vector", dest="v10")
    emit(vector(0x25, 10, 2, 3, 10), "vector", ("v10",), "v10")
    emit(vector(0, 10, 6, 4, 10), "vector", ("v10", "x6"), "v10")
    emit((0x800 << 20) | (2 << 12) | (17 << 7) | 0x73, "scalar", dest="x17")
    emit((2 << 20) | (17 << 15) | (1 << 12) | (17 << 7) | 0x13, "scalar", ("x17",), "x17")
    emit(vector(0, 10, 17, 4, 10), "vector", ("v10", "x17"), "v10")
    emit(
        (1 << 20) | (10 << 15) | (6 << 12) | 0x7B,
        "store",
        ("v10", "v1"),
        addresses=tuple(0x90002000 + 4 * i for i in range(32)),
    )
    ewords.append(0x400B)
    operations = tuple(
        replace(
            op,
            name=f"w{w}.{op.name}",
            warp=w,
            addresses=tuple(a + 128 * w for a in op.addresses)
            if op.kind == "store"
            else op.addresses,
        )
        for op in eops
        for w in range(warps)
    )
    return replace(
        source,
        words=tuple(ewords),
        workload=Workload(operations, warps_per_block=warps),
        expected=source.expected * warps,
        output_store_pc=0x80000000 + 4 * (len(ewords) - 2),
    ), {}


def write(program, path, *, relocate, warps):
    record = program.write(path, FLOW / "search_model/kernel-probes-v3/stream-4-rf0-lds1/input")
    lines = (path / "input.metadata").read_text().splitlines()
    meta = [int(lines[i], 16) | int(lines[i + 1], 16) << 32 for i in range(0, len(lines), 2)]
    data = [int(x, 16) for x in (path / "input.data").read_text().splitlines()]
    count = meta[13]
    sizes = meta[14 + count : 14 + 2 * count]
    pos = meta[14 : 14 + count].index(0x90002000)
    offset = sum(sizes[:pos]) // 4
    data[offset : offset + sizes[pos] // 4] = [0] * len(program.expected)
    meta[14 + count + pos] = meta[14 + 2 * count + pos] = 4 * len(program.expected)
    meta[6] = warps
    if relocate:
        for old, new in ((0x90000000, 0x90010000), (0x90001000, 0x90100000)):
            meta[14 + meta[14 : 14 + count].index(old)] = new
    (path / "input.metadata").write_text(
        "".join(f"{v & 0xFFFFFFFF:08x}\n{v >> 32:08x}\n" for v in meta)
    )
    (path / "input.data").write_text("".join(f"{v:08x}\n" for v in data))
    record["input_sha256"] = {
        n: hashlib.sha256((path / n).read_bytes()).hexdigest()
        for n in ("input.metadata", "input.data")
    }
    return record


def generate():
    destination = ROOT / "probes"
    destination.mkdir()
    cases = []
    configurations = [
        ("softmax", 1),
        ("chain", 1),
        ("stream", 2),
        ("stream", 4),
        ("conflict-return", 2),
        ("conflict-return", 4),
    ]
    for kind, warps in configurations:
        program, metadata = (
            Nonlinear(chain=kind == "chain").program()
            if kind in {"softmax", "chain"}
            else multi(kind, warps)
        )
        name = f"{kind}-w{warps}"
        record = write(program, destination / name, relocate=kind != "softmax", warps=warps)
        graph = build_graph(program.workload, Hardware())
        prediction = execute(graph)
        names = (
            [f"w{w}.pc{program.final_tensor_pc:08x}.writeback" for w in range(warps)]
            if warps > 1
            else [f"pc{program.final_tensor_pc:08x}.writeback"]
        )
        record.update(
            name=name,
            warps=warps,
            words=list(program.words),
            final_pc=program.final_tensor_pc,
            prediction=max(prediction["times"][graph.names.index(n)] for n in names),
            predicted_visible=prediction["times"][graph.names.index("outputs.visible")],
            counters=prediction["counters"],
            metadata=metadata,
        )
        cases.append(record)
    (destination / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (destination / "pre_run_predictions.json").write_text(
        json.dumps(
            dict(
                version=MODEL_VERSION,
                code_sha256=model_hashes(),
                generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                cases=cases,
            ),
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps([{k: r[k] for k in ("name", "prediction", "predicted_visible")} for r in cases])
    )


if __name__ == "__main__":
    generate()
