"""Evidence preservation, all design fields, conservative ports and factorization."""

import random

import highspy
import pytest

from codesign.ventus.config import Hardware
from codesign.ventus_costs import (
    add_structural_cost_constraints,
    decode_structural_solution,
    evaluate_cost,
    evaluate_structural_cost,
    factorized_cost_coefficients,
    structural_target,
)
from codesign.ventus_costs.structural import RANGES


def test_baseline_conserves_measured_partition_and_v1_stays_strict():
    v1, v2 = evaluate_cost({}), evaluate_structural_cost({})
    assert v1["logic_area"] == pytest.approx(v2["logic_area"])
    assert v1["memory_bits"] == v2["memory_bits"]
    assert evaluate_cost({"rf_read_ports": 2})["status"] == "unsupported"
    assert v2["storage_area"] is None and v2["timing_feasible"] is None
    assert v2["energy"] is None
    assert all(c["logic_area"] > 0 for c in v2["components"].values())


@pytest.mark.parametrize("field", list(RANGES))
def test_every_open_field_has_cost_effect(field):
    baseline = Hardware()
    options = [v for v in RANGES[field] if v != getattr(baseline, field)]
    for value in options:
        try:
            hardware = baseline.with_changes(**{field: value})
        except ValueError:
            continue
        cost = evaluate_structural_cost(hardware)
        assert cost["status"] == "estimated"
        default = evaluate_structural_cost(baseline)
        assert (cost["logic_area"], cost["memory_bits"]) != (
            default["logic_area"],
            default["memory_bits"],
        )
        return
    pytest.fail(f"no legal variation of {field}")


def test_ports_charge_replication_and_logic_and_precision_is_static():
    base = evaluate_structural_cost({})
    ports = evaluate_structural_cost({"rf_read_ports": 2, "rf_write_ports": 2, "lds_ports": 2})
    assert ports["components"]["rf"]["memory_bits"] == base["components"]["rf"]["memory_bits"] * 4
    assert ports["memory_bits"] > base["memory_bits"]
    assert ports["logic_area"] > base["logic_area"]
    target = structural_target(["bf16", "fp16", "tf32"])
    multi = evaluate_structural_cost({}, target)
    assert multi["logic_area"] > base["logic_area"]
    assert multi == evaluate_structural_cost(
        {}, target, activity={"format": "bf16", "operations": 100}
    )
    assert multi["target"]["precisions"] == ["bf16", "fp16", "tf32"]
    with pytest.raises(ValueError):
        structural_target(["int8"])
    altered = structural_target()
    altered["assumptions"]["rf_capacity_logic_fraction"] = 0
    with pytest.raises(ValueError, match="target"):
        evaluate_structural_cost({}, altered)
    assert (
        evaluate_structural_cost({"threads": 16, "tensor_m": 2, "tensor_n": 4, "tensor_k": 2})[
            "status"
        ]
        == "unsupported"
    )


def test_factorized_coefficients_reconstruct_joint_cost_without_full_menu():
    factors = factorized_cost_coefficients(structural_target(["bf16", "fp16", "tf32"]))
    assert sum(len(v) for v in factors["groups"].values()) < 10000
    rng = random.Random(7107)
    for _ in range(25):
        while True:
            values = {k: rng.choice(v) for k, v in RANGES.items()}
            try:
                h = Hardware(**values).validate()
                break
            except ValueError:
                pass
        sums = {"logic_area": 0.0, "memory_bits": 0}
        for rows in factors["groups"].values():
            matches = [r for r in rows if all(values[k] == v for k, v in r["choice"].items())]
            assert len(matches) == 1
            for key in sums:
                sums[key] += matches[0][key]
        direct = evaluate_structural_cost(h, factors["target"])
        assert sums["logic_area"] == pytest.approx(direct["logic_area"])
        assert sums["memory_bits"] == direct["memory_bits"]


def test_mip_budget_rows_decode_and_reject_infeasible_choices():
    baseline = evaluate_structural_cost({})
    fixed = {
        k: getattr(Hardware(), k) for k in RANGES if k not in {"sms", "collectors", "tensor_units"}
    }
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    binding = add_structural_cost_constraints(
        model,
        logic_area_budget=baseline["logic_area"],
        memory_bits_budget=baseline["memory_bits"],
        fixed=fixed,
        objective_weights={"sms": -1},
    )
    model.run()
    assert model.getModelStatus() == highspy.HighsModelStatus.kOptimal
    decoded = decode_structural_solution(binding, model.getSolution().col_value)
    assert decoded["cost"]["logic_area"] <= baseline["logic_area"] + 1e-6
    assert decoded["cost"]["memory_bits"] <= baseline["memory_bits"]
    assert decoded["hardware"]["sms"] == 2
    # Zero bits cannot silently make an infeasible target acceptable.
    with pytest.raises(ValueError):
        add_structural_cost_constraints(model, logic_area_budget=1, memory_bits_budget=0)
    broken = highspy.Highs()
    broken.setOptionValue("output_flag", False)
    add_structural_cost_constraints(broken, logic_area_budget=1, memory_bits_budget=1, fixed=fixed)
    broken.run()
    assert broken.getModelStatus() == highspy.HighsModelStatus.kInfeasible


def test_sensitivity_versions_both_baseline_and_candidate_and_does_not_mutate():
    target = structural_target(scales={"rf": 1.25})
    base = evaluate_structural_cost({})
    scaled = evaluate_structural_cost({}, target)
    assert scaled["logic_area"] == pytest.approx(
        base["logic_area"] + base["components"]["rf"]["logic_area"] * 2 * 0.25
    )
    scaled["target"]["assumptions"]["l1_logic_fractions"]["fixed"] = 0
    assert evaluate_structural_cost({}, target)["target"] == target
