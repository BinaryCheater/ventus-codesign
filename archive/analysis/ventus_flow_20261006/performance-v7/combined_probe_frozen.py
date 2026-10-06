"""Freeze Tensor GEMM -> global output -> in-place LayerNorm in one program."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

from memory_probes import build

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.ir import Workload
from codesign.ventus.layernorm import LayerNormEmitter
from codesign.ventus.program import Program
from codesign.ventus.timing import build_graph

root = Path(__file__).parent
first = build("resident")
refpath = root.parent / "layernorm_rtl_20261006/generate.py"
spec = importlib.util.spec_from_file_location("independent_ln", refpath)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)
numeric = ref.Emitter(32, 1)
numeric.x = [ref.decode(w) for w in first.expected]
numeric.pa = list(first.expected)
numeric.memory.update({0x90000000 + 4 * i: w for i, w in enumerate(first.expected)})
reference, metadata = numeric.build()
words, operations = LayerNormEmitter(
    32, 0x90002000, 0x90100100, 0x90100180, 0x90002000, 0x70000000
).build()
prefix = len(first.words) - 1
ops = tuple(
    replace(op, name=f"pc{0x80000000 + 4 * i:08x}")
    for i, op in enumerate((*first.workload.operations, *operations))
)
program = Program(
    first.words[:-1] + words,
    Workload(ops, lds_per_block=512),
    reference.expected,
    first.panels_a,
    first.panels_b + (0,) * 32 + reference.panels_b,
    0x80000000 + 4 * (prefix + len(words) - 7),
    0x80000000 + 4 * (prefix + len(words) - 2),
)
# Last arithmetic precedes the output address sequence (scalar/VID/shift/add/store).
final_op = next(op for op in reversed(ops) if op.kind == "fma")
program = replace(program, final_tensor_pc=int(final_op.name[2:], 16))
destination = root / "combined-probes"
destination.mkdir()
path = destination / "gemm-layernorm"
record = program.write(
    path,
    Path("analysis/ventus_flow_20261006/search_model/kernel-probes-v3/stream-4-rf0-lds1/input"),
)
lines = (path / "input.metadata").read_text().splitlines()
values = [int(lines[i], 16) | int(lines[i + 1], 16) << 32 for i in range(0, len(lines), 2)]
n = values[13]
for old, new in ((0x90000000, 0x90010000), (0x90001000, 0x90100000)):
    values[14 + values[14 : 14 + n].index(old)] = new
(path / "input.metadata").write_text(
    "".join(f"{v & 0xFFFFFFFF:08x}\n{v >> 32:08x}\n" for v in values)
)
import hashlib

record["input_sha256"]["input.metadata"] = hashlib.sha256(
    (path / "input.metadata").read_bytes()
).hexdigest()
graph = build_graph(program.workload, Hardware())
result = execute(graph)
record.update(
    name="gemm-layernorm",
    words=list(program.words),
    final_pc=program.final_tensor_pc,
    prediction=result["times"][graph.names.index(final_op.name + ".writeback")],
    predicted_visible=result["times"][graph.names.index("outputs.visible")],
    max_abs_error_vs_float64=metadata["max_abs_error_vs_float64"],
    counters=result["counters"],
)
(destination / "cases.json").write_text(json.dumps([record], indent=2) + "\n")
(destination / "pre_run_predictions.json").write_text(
    json.dumps(
        dict(
            version=MODEL_VERSION,
            code_sha256=model_hashes(),
            generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            cases=[record],
        ),
        indent=2,
    )
    + "\n"
)
print(
    json.dumps(
        {
            k: record[k]
            for k in ("name", "prediction", "predicted_visible", "max_abs_error_vs_float64")
        }
    )
)
