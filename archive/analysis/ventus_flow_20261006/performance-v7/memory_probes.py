"""Freeze equal-work Tensor programs with distinct memory reuse patterns."""

import argparse
import hashlib
import json
from pathlib import Path

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.ir import Workload
from codesign.ventus.layernorm import LayerNormEmitter
from codesign.ventus.program import Program, packed_gemm, vector
from codesign.ventus.timing import build_graph


def build(strategy):
    e = LayerNormEmitter(32, 0, 0, 0, 0, 0, prefix="probe")
    e.emit(vector(0x0B, 1, 1, 0, 1), "vector", ("v1", "v1"), "v1")
    payload = packed_gemm(steps=32)
    stride = 32768 if strategy == "conflict-return" else 128
    panels = 8 if strategy == "conflict-return" else 32 if strategy == "stream" else 1
    for step in range(32):
        index = step % panels
        if strategy != "resident" or step == 0:
            e.memory("load", 2, 0x90010000 + index * stride)
            e.memory("load", 3, 0x90100000 + index * stride)
        final_pc = 0x80000000 + 4 * len(e.words)
        e.emit(
            (3 << 26) | (1 << 25) | (3 << 20) | (2 << 15) | (4 << 12) | (1 << 7) | 0x0B,
            "tensor",
            ("v2", "v3", "v1"),
            "v1",
        )
    e.memory("store", 1, 0x90002000)
    store_pc = 0x80000000 + 4 * (len(e.words) - 1)
    words = tuple(e.words) + (0x400B,)
    a = [0] * ((panels - 1) * stride // 4 + 32)
    b = a[:]
    for i in range(panels):
        a[i * stride // 4 : i * stride // 4 + 32] = payload.panels_a[:32]
        b[i * stride // 4 : i * stride // 4 + 32] = payload.panels_b[:32]
    ops = tuple(
        __import__("dataclasses").replace(op, name=f"pc{0x80000000 + 4 * i:08x}")
        for i, op in enumerate(e.ops)
    )
    return Program(words, Workload(ops), payload.expected, tuple(a), tuple(b), final_pc, store_pc)


def freeze(destination):
    destination.mkdir()
    cases = []
    for strategy in ("resident", "reload", "stream", "conflict-return"):
        program = build(strategy)
        case_path = destination / strategy
        record = program.write(
            case_path,
            Path(
                "analysis/ventus_flow_20261006/search_model/kernel-probes-v3/stream-4-rf0-lds1/input"
            ),
        )
        metadata = case_path / "input.metadata"
        lines = metadata.read_text().splitlines()
        values = [int(lines[i], 16) | int(lines[i + 1], 16) << 32 for i in range(0, len(lines), 2)]
        n = values[13]
        for old, new in ((0x90000000, 0x90010000), (0x90001000, 0x90100000)):
            pos = values[14 : 14 + n].index(old)
            values[14 + pos] = new
        metadata.write_text("".join(f"{v & 0xFFFFFFFF:08x}\n{v >> 32:08x}\n" for v in values))
        record["input_sha256"]["input.metadata"] = hashlib.sha256(metadata.read_bytes()).hexdigest()
        graph = build_graph(program.workload, Hardware())
        result = execute(graph)
        record.update(
            name=strategy,
            words=list(program.words),
            final_pc=program.final_tensor_pc,
            prediction=result["times"][
                graph.names.index(f"pc{program.final_tensor_pc:08x}.writeback")
            ],
            predicted_visible=result["times"][graph.names.index("outputs.visible")],
            counters=result["counters"],
            model_version=MODEL_VERSION,
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
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    freeze(parser.parse_args().destination)
