import hashlib
import itertools
import json
from pathlib import Path

import highspy
import pytest

from codesign.ventus.config import Hardware
from codesign.ventus_costs.native_arrays import bank, group_storage, manifest
from codesign.ventus_costs.structural import EXPANDED_RANGES
from codesign.ventus_costs.unified import (
    V3_POLICY,
    add_unified_area_constraints,
    decode_unified_solution,
    evaluate_unified_area,
)

ROOT = Path(__file__).resolve().parents[1]


def test_native_baseline_and_versioned_inputs():
    current = evaluate_unified_area()
    legacy = evaluate_unified_area(policy_path=V3_POLICY)
    assert current["total_area_mm2"] == legacy["total_area_mm2"]
    assert current["physical_memory_bits"] == legacy["physical_memory_bits"]
    assert current["budget_mm2"] == 1.11
    assert current["native_array_estimate"]["table_sha256"] == manifest()["table_sha256"]
    baseline = json.loads((ROOT / "examples/project-baseline-v4.json").read_text())
    for name, digest in baseline["sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest


def test_entire_rf_lds_search_domain_has_characterized_or_padded_arrays():
    for banks, vgpr, sgpr, rd, wr in itertools.product(
        EXPANDED_RANGES["rf_banks"],
        EXPANDED_RANGES["vgpr_slots"],
        EXPANDED_RANGES["sgpr_slots"],
        [1, 2],
        [1, 2],
    ):
        h = Hardware(
            rf_banks=banks, vgpr_slots=vgpr, sgpr_slots=sgpr, rf_read_ports=rd, rf_write_ports=wr
        )
        result = group_storage("rf", h, 0.0426177978515625)
        assert result["area_um2"] > 0
        assert result["physical_bits"] >= (vgpr * 128 + sgpr * 4) * 8
    for size, banks, ports in itertools.product(
        EXPANDED_RANGES["lds_bytes"], EXPANDED_RANGES["lds_banks"], [1, 2]
    ):
        result = group_storage(
            "lds", Hardware(lds_bytes=size, lds_banks=banks, lds_ports=ports), 0.0426177978515625
        )
        assert result["physical_bits"] == size * 8


def test_multiport_area_is_not_replication_and_padding_is_explicit():
    one = evaluate_unified_area()
    two = evaluate_unified_area({"rf_read_ports": 2, "rf_write_ports": 2, "lds_ports": 2})
    assert two["physical_memory_bits"] == one["physical_memory_bits"]
    assert two["total_area_mm2"] > one["total_area_mm2"]
    rf = two["native_array_estimate"]["array_groups_per_sm"]["rf"]["area_um2"]
    assert 2 < rf / one["native_array_estimate"]["array_groups_per_sm"]["rf"]["area_um2"] < 4
    assert bank("sgpr", 32, 1, 1)["padding_bytes"] == 96
    assert bank("vgpr", 2048, 1, 1)["padding_bytes"] == 2048
    with pytest.raises(ValueError, match="uncharacterized"):
        bank("vgpr", 65536, 3, 1)


def test_native_mip_cost_matches_independent_evaluation():
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    binding = add_unified_area_constraints(
        model, fixed={"sms": 2, "rf_read_ports": 2, "rf_write_ports": 2, "lds_ports": 2}
    )
    model.run()
    assert model.getModelStatus() == highspy.HighsModelStatus.kOptimal
    decoded = decode_unified_solution(binding, model.getSolution().col_value)
    assert decoded["cost"]["area_feasible"]
    assert decoded["cost"] == evaluate_unified_area(decoded["hardware"])
    values = model.getSolution().col_value
    selected = [
        choice
        for choices in binding["groups"].values()
        for col, choice in choices
        if values[col] > 0.5
    ]
    assert sum(c["logic_area"] + c["storage_area_um2"] for c in selected) / 1e6 == pytest.approx(
        decoded["cost"]["total_area_mm2"]
    )
    assert sum(c["memory_bits"] for c in selected) == decoded["cost"]["physical_memory_bits"]
