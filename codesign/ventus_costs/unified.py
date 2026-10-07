"""Experiment area policy over immutable v2; external DRAM is outside its scope."""

import argparse
import json
from pathlib import Path

from codesign.ventus.config import Hardware

from .structural import evaluate_structural_cost, structural_target

ROOT = Path(__file__).resolve().parents[2]
LEGACY_POLICY = ROOT / "examples/unified-area-policy-v1.json"
POLICY = ROOT / "examples/unified-area-policy-v2.json"


def evaluate_unified_area(hardware=None, *, policy_path=POLICY):
    policy = json.loads(Path(policy_path).read_text())
    values = dict(policy["baseline_hardware"])
    values.update(hardware.to_dict() if isinstance(hardware, Hardware) else (hardware or {}))
    h = Hardware(**values).validate()
    external = ("memory_channels", "memory_bytes_per_cycle", "memory_latency")
    if any(getattr(h, key) != policy["baseline_hardware"][key] for key in external):
        raise ValueError("experiment external-memory target must remain fixed")
    target = structural_target(policy["precisions"], version=policy["base_cost_version"])
    # v2 fixes legacy wrapper memory values; none affects its on-chip area arithmetic.
    cost_h = h.with_changes(**{key: target["fixed"][key] for key in external})
    cost = evaluate_structural_cost(cost_h, target)
    area = None
    if cost["status"] == "estimated":
        area = (
            cost["logic_area"] * policy["logic_area_um2_per_library_unit"]
            + cost["memory_bits"] * policy["storage_area_um2_per_physical_bit"]
        ) / 1e6
    budget = policy["baseline_total_area_mm2"]
    return {
        "version": policy["version"],
        "base_cost_version": cost["version"] if "version" in cost else policy["base_cost_version"],
        "status": cost["status"],
        "unsupported_reasons": cost.get("unsupported_reasons", []),
        "hardware": h.to_dict(),
        "cost_api_hardware": cost_h.to_dict(),
        "precisions": policy["precisions"],
        "logic_area_um2": cost["logic_area"],
        "physical_memory_bits": cost["memory_bits"],
        "total_area_mm2": area,
        "budget_mm2": budget,
        "area_feasible": None if area is None else area <= budget + 1e-12,
        "independent_memory_bit_cap": None,
        "scope": policy["scope"],
    }


def add_unified_area_constraints(highs, *, fixed=None, objective_weights=None, policy_path=POLICY):
    """Use the frozen experiment target and one area budget, with no bit cap."""
    from .structural_mip import add_structural_cost_constraints

    p = json.loads(Path(policy_path).read_text())
    binding = add_structural_cost_constraints(
        highs,
        target=structural_target(p["precisions"], version=p["base_cost_version"]),
        fixed=fixed,
        objective_weights=objective_weights,
        total_area_budget_mm2=p["baseline_total_area_mm2"],
        storage_area_um2_per_bit=p["storage_area_um2_per_physical_bit"],
    )

    binding["area_policy_version"] = p["version"]
    return binding


def decode_unified_solution(binding, column_values):
    from .structural_mip import decode_structural_solution

    decoded = decode_structural_solution(binding, column_values)
    policy_path = (
        LEGACY_POLICY
        if binding.get("area_policy_version", "ventus-unified-area-policy-v1")
        == "ventus-unified-area-policy-v1"
        else POLICY
    )
    p = json.loads(policy_path.read_text())
    hardware = dict(decoded["hardware"])
    for key in ("memory_channels", "memory_bytes_per_cycle", "memory_latency"):
        hardware[key] = p["baseline_hardware"][key]
    cost = evaluate_unified_area(hardware, policy_path=policy_path)
    if not cost["area_feasible"]:
        raise ValueError("decoded hardware exceeds unified area budget")
    return {"hardware": hardware, "cost": cost}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hardware", type=Path)
    args = parser.parse_args()
    hardware = json.loads(args.hardware.read_text()) if args.hardware else None
    print(json.dumps(evaluate_unified_area(hardware), indent=2))


if __name__ == "__main__":
    main()
