"""Small compiled-kernel probes and exact minimum-area MIPs; no network runs."""

import hashlib
import json
import math
from pathlib import Path

import highspy

from codesign.ventus.config import Hardware
from codesign.ventus.elf import ELFProgram
from codesign.ventus.model_program import TARGET
from codesign.ventus.rust import PreparedProgram, RustSession, source_hash
from codesign.ventus_costs.structural import EXPANDED_VERSION, structural_target
from codesign.ventus_costs.structural_mip import (
    add_structural_cost_constraints,
    decode_structural_solution,
)
from codesign.ventus_costs.unified import POLICY, evaluate_unified_area

root = Path(__file__).resolve().parents[3]
policy = json.loads(POLICY.read_text())
minimum = []
for sms in [1, 2, 3, 4, 8]:
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    binding = add_structural_cost_constraints(
        model,
        target=structural_target(policy["precisions"], version=EXPANDED_VERSION),
        fixed={"sms": sms},
        total_area_budget_mm2=100,
        storage_area_um2_per_bit=policy["storage_area_um2_per_physical_bit"],
    )
    for choices in binding["groups"].values():
        for col, choice in choices:
            model.changeColCost(
                col,
                (
                    choice["logic_area"]
                    + policy["storage_area_um2_per_physical_bit"] * choice["memory_bits"]
                )
                / 1e6,
            )
    model.run()
    assert model.getModelStatus() == highspy.HighsModelStatus.kOptimal
    decoded = decode_structural_solution(binding, model.getSolution().col_value)
    minimum.append(
        {
            "sms": sms,
            "minimum_area_mm2": decoded["cost"]["total_area_mm2"],
            "hardware": decoded["hardware"],
        }
    )

elf_path = root / "tests/fixtures/compiled-transformer/reuse.elf"
elf = ELFProgram.read(elf_path)
launch = elf.launch(
    "mma_reuse_bf16",
    [0x10000000, 0x90000000, 0, 0x10010000, 256, 256, 64, 0, 1],
    global_size=(1024, 1, 1),
)
program = PreparedProgram.from_elf(elf, launch)
base = Hardware(**policy["baseline_hardware"]).with_changes(
    warps_per_sm=16, blocks_per_sm=16, vgpr_slots=2048
)
rows = []
for field, values in {
    "sms": [1, 2, 3, 4],
    "vgpr_slots": [256, 512, 1024, 2048],
    "sgpr_slots": [128, 256, 512, 1024, 2048],
}.items():
    for value in values:
        hw = base.with_changes(**{field: value})
        with RustSession(hw, instruction_target=TARGET) as session:
            result = session.dispatch(program)
        rows.append(
            {
                "field": field,
                "value": value,
                "cycles": result["cycles"],
                "instructions": result["instructions"],
                "counters": result["counters"],
                "area_mm2": evaluate_unified_area(hw)["total_area_mm2"],
            }
        )
space = json.loads((root / "examples/search-space-v2.json").read_text())
ranges = space["active_budget_ranges"]
raw = math.prod(map(len, ranges.values()))
legal = raw * len(space["legal_tensor_shapes"]) // 36 * 9 // 12
report = {
    "version": "search-expansion-v2",
    "scope": "Model probes, not RTL validation. 32 one-warp blocks of compiled reuse GEMM; each parameter varied separately from probe_hardware.",
    "probe_hardware": base.to_dict(),
    "instruction_target": TARGET,
    "elf_sha256": hashlib.sha256(elf_path.read_bytes()).hexdigest(),
    "timing_source_hash": source_hash(),
    "kernel_resources": elf.resources,
    "minimum_area": minimum,
    "rows": rows,
    "raw_active_combinations": raw,
    "structurally_legal_active_combinations_before_area": legal,
    "budget_mm2": policy["baseline_total_area_mm2"],
}
out = Path(__file__).with_name("audit.json")
if out.exists():
    assert json.loads(out.read_text()) == report
else:
    out.write_text(json.dumps(report, indent=2) + "\n")
print(
    json.dumps(
        {
            "minima": [(x["sms"], x["minimum_area_mm2"]) for x in minimum],
            "probes": [(x["field"], x["value"], x["cycles"]) for x in rows],
            "legal": legal,
        },
        indent=2,
    )
)
