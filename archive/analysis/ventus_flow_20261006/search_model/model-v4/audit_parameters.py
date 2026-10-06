"""Audit parameter mechanisms without compiling or running RTL.

These checks establish arithmetic and primitive consistency of the abstraction;
they do not establish non-default RTL accuracy.
"""

import argparse
import json
from dataclasses import fields
from pathlib import Path

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.timing import simulate
from codesign.ventus.workloads import chain, gemm

parser = argparse.ArgumentParser()
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--verify", action="store_true")
args = parser.parse_args()
hardware = Hardware()
rf_rows = []
for ports, expected in [(1, 161), (2, 152), (3, 143)]:
    result = simulate(
        chain("tensor", 9, conflicts=True), hardware.with_changes(rf_read_ports=ports)
    )
    if result["cycles"] != expected:
        raise ValueError("RF supply rounds violate independently derived dependency recurrence")
    rf_rows.append(dict(read_ports=ports, cycles=result["cycles"]))
lds_rows = []
for banks, ports, rounds, cycles in [(32, 1, 5, 54), (16, 1, 10, 59), (16, 2, 5, 54)]:
    result = simulate(chain("load", 5), hardware.with_changes(lds_banks=banks, lds_ports=ports))
    if (result["counters"]["lds_rounds"], result["cycles"]) != (rounds, cycles):
        raise ValueError("LDS bank/port service violates request counts")
    lds_rows.append(dict(banks=banks, ports=ports, rounds=rounds, cycles=cycles))
tensor_rows = []
original = gemm(hardware, m=8, n=8, k=16, shared=False)
for reduction in [8, 4]:
    target = hardware.with_changes(tensor_n=reduction)
    regenerated = gemm(target, m=8, n=8, k=16, shared=False)
    result = simulate(regenerated, target)
    flops = result["counters"]["tensor"] * target.tensor_flops_per_instruction
    if flops != 2 * 8 * 8 * 16:
        raise ValueError("changing Tensor shape changed the regenerated mathematical workload")
    reused = simulate(original, target)
    tensor_rows.append(
        dict(
            reduction=reduction,
            instructions=result["counters"]["tensor"],
            flops=flops,
            latency=target.tensor_latency,
            cycles=result["cycles"],
            incorrectly_reused_ir_flops=reused["counters"]["tensor"]
            * target.tensor_flops_per_instruction,
            incorrectly_reused_ir_cycles=reused["cycles"],
        )
    )
receipt = dict(
    version=MODEL_VERSION,
    code_sha256=model_hashes(),
    hardware_fields=len(fields(hardware)) - 3,
    external_memory_fields=3,
    rf=rf_rows,
    lds=lds_rows,
    same_gemm=tensor_rows,
    requires_rtl_compilation=False,
    checks="Primitive recurrence, request counts and arithmetic conservation; no RTL observations",
    limits=[
        "Non-default mixed scheduling and cache timing remain approximate",
        "Executable FFN emitter is fixed to default shape; generic timing GEMM can regenerate",
        "Tensor unit replication retains one vector issue per cycle",
        "Full-line LDS control template is not a general online coalescer",
    ],
)
if args.verify:
    if receipt != json.loads(args.out.read_text()):
        raise ValueError("saved parameter audit differs")
else:
    with args.out.open("x") as out:
        json.dump(receipt, out, indent=2)
        out.write("\n")
print(json.dumps(receipt, indent=2))
