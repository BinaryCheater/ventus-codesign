import json
from pathlib import Path

from codesign.ventus.config import Hardware
from codesign.ventus.elf import ELFProgram
from codesign.ventus.model_program import TARGET
from codesign.ventus.rust import PreparedProgram, RustSession
from codesign.ventus_costs.structural import RANGES
from codesign.ventus_costs.unified import evaluate_unified_area

root = Path.cwd()
out = root / "docs/evidence/baseline-range-audit-20261007"
h = Hardware(**json.load(open("examples/baseline-hardware-v1.json")))
elf = ELFProgram.read(Path("tests/fixtures/compiled-transformer/packed.elf"))
launch = elf.launch(
    "mma_packed_bf16",
    [0x10000000, 0x90000000, 0, 0x10010000, 32, 64, 64, 0],
    global_size=(256, 1, 1),
)
program = PreparedProgram.from_elf(elf, launch)


def run(hw):
    with RustSession(hw, instruction_target=TARGET) as session:
        r = session.dispatch(program)
    return {k: r[k] for k in ["cycles", "instructions", "requested_bytes", "counters"]}


base = run(h)
rows = []
for key, values in RANGES.items():
    for value in values:
        changes = {key: value}
        if key == "warps_per_sm" and value < h.blocks_per_sm:
            changes["blocks_per_sm"] = value
        if key == "blocks_per_sm" and value > h.warps_per_sm:
            changes["warps_per_sm"] = value
        try:
            hw = h.with_changes(**changes)
        except ValueError as e:
            rows.append(
                {"field": key, "value": value, "changes": changes, "legal": False, "reason": str(e)}
            )
            continue
        result = run(hw)
        cost = evaluate_unified_area(hw)
        rows.append(
            {
                "field": key,
                "value": value,
                "changes": changes,
                "legal": True,
                "cycles": result["cycles"],
                "cycle_ratio": result["cycles"] / base["cycles"],
                "counter_changes": {
                    k: v for k, v in result["counters"].items() if v != base["counters"].get(k)
                },
                "area_mm2": cost["total_area_mm2"],
                "area_feasible": cost["area_feasible"],
            }
        )
        print(key, value, result["cycles"], flush=True)
resources = {}
for name in ["generic", "packed", "reuse", "mma"]:
    e = ELFProgram.read(Path(f"tests/fixtures/compiled-transformer/{name}.elf"))
    resources[name] = e.resources
report = {
    "scope": "single compiled 32x64x64 BF16 GEMM, 8 single-warp blocks; inactivity here is not a global proof",
    "baseline": base,
    "launch_resources": launch[4:9],
    "rows": rows,
    "compiled_resources": resources,
}
path = out / "audit.json"
if path.exists():
    assert json.loads(path.read_text()) == report, "preserve old evidence; use a new version"
else:
    path.write_text(json.dumps(report, indent=2) + "\n")
