"""Cost credibility: integration identities, explicit omissions, and menu budgets."""

import pytest

from codesign.ventus.config import Hardware
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.mip import Candidate
from codesign.ventus_costs import evaluate_cost, load_table, mip_coefficients, optimize_with_cost


def test_integrated_anchor_and_reserved_storage():
    points = load_table()["points"]
    fixed = points["gpu-fixed"]
    sm = points["sm-base"]
    cost = evaluate_cost(Hardware())
    assert cost["status"] == "estimated"
    assert cost["logic_area"] == pytest.approx(fixed["logic_area"] + 2 * sm["logic_area"])
    assert cost["memory_bits"] == fixed["memory_bits"] + 2 * sm["memory_bits"]
    # Inventory must include tags, I-cache and queues beyond the old data budget.
    assert cost["memory_bits"] > 8 * cost["data_resources"]["storage_bytes"]
    assert cost["storage_area"] is None
    assert cost["timing_feasible"] is None
    assert cost["energy"] is None


def test_bank_cost_keeps_capacity_but_charges_logic():
    four = evaluate_cost(Hardware())
    eight = evaluate_cost(Hardware(rf_banks=8))
    assert four["memory_bits"] == eight["memory_bits"]
    assert four["sgpr_addressability"]["bank_address_bits"] == 8
    assert eight["sgpr_addressability"]["bank_address_bits"] == 7
    assert four["sgpr_addressability"]["addressable_slots"] == 1024
    assert eight["sgpr_addressability"]["addressable_slots"] == 1024
    assert four["logic_area"] != eight["logic_area"]
    assert "rf_banks" in eight["implementation"]


@pytest.mark.parametrize("changes", [{"rf_read_ports": 2}, {"vgpr_slots": 2048}, {"l1_mshrs": 8}])
def test_missing_cost_is_never_zero(changes):
    cost = evaluate_cost(Hardware(**changes))
    assert cost["status"] == "unsupported"
    assert cost["logic_area"] is None
    assert cost["memory_bits"] is None
    assert cost["unsupported_reasons"]
    with pytest.raises(ValueError, match="unsupported"):
        mip_coefficients([Hardware(**changes)])


def test_activity_cannot_change_static_cost_and_overrides_are_validated():
    assert evaluate_cost({}) == evaluate_cost({}, activity={"operations": 100000})
    with pytest.raises(ValueError):
        evaluate_cost({"rf_banks": 3})
    with pytest.raises(ValueError, match="target"):
        evaluate_cost({}, target={"library": "another"})


def test_cost_budget_restricts_menu():
    work = Workload((Operation("add", "vector", destination="v1", sources=("v2",)),))
    small = Hardware(sms=1)
    big = Hardware(sms=2)
    cost = evaluate_cost(small)
    result = optimize_with_cost(
        [Candidate("big", big, work), Candidate("small", small, work)],
        logic_area_budget=cost["logic_area"],
        memory_bits_budget=cost["memory_bits"],
    )
    assert result["candidate"] == "small"
    assert result["cost"]["memory_bits"] <= cost["memory_bits"]
    rejected = optimize_with_cost(
        [Candidate("big", big, work)], logic_area_budget=1, memory_bits_budget=1
    )
    assert rejected["candidate"] is None
    assert rejected["status"] == "cost_budget_infeasible"


def test_lds_banks_preserve_capacity_and_parameter_depth():
    points = load_table()["points"]
    for banks in [8, 16, 32]:
        cost = evaluate_cost(Hardware(lds_banks=banks))
        assert cost["status"] == "estimated"
        assert cost["lds_organization"]["bank_depth"] == 32768 // banks
        memories = points[f"lds-{banks}-1024"]["memories"]
        arrays = [v for n, v in memories.items() if n.startswith("array_")]
        assert sum(v["bits"] * v["instances"] for v in arrays) == 131072 * 8
    small = evaluate_cost(Hardware(lds_banks=16, lds_bytes=16384))
    assert small["status"] == "estimated"
    assert small["lds_organization"]["parameter_depth"] == 128
    assert small["lds_organization"]["bank_depth"] == 256
