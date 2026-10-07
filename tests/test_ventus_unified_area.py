import hashlib
import json
from pathlib import Path

import highspy
import pytest

from codesign.ventus.config import Hardware
from codesign.ventus.model_program import TARGET
from codesign.ventus_costs.unified import (
    add_unified_area_constraints,
    decode_unified_solution,
    evaluate_unified_area,
)

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_baseline_and_sources():
    manifest = json.loads((ROOT / "examples/project-baseline-v1.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    assert manifest["instruction_target"] == TARGET
    result = evaluate_unified_area()
    assert result["area_feasible"]
    assert result["total_area_mm2"] == pytest.approx(manifest["budget_total_area_mm2"])
    original = Hardware().to_dict()
    for key, value in result["hardware"].items():
        if key not in ("memory_channels", "memory_bytes_per_cycle", "memory_latency"):
            assert value == original[key]
    assert result["hardware"]["memory_latency"] == 100
    assert result["cost_api_hardware"]["memory_latency"] == 2


def test_area_rejects_invalid_or_unsupported_hardware():
    with pytest.raises(ValueError):
        evaluate_unified_area({"memory_latency": 2})
    with pytest.raises(ValueError):
        evaluate_unified_area({"rf_banks": 3})
    assert evaluate_unified_area({"threads": 64})["total_area_mm2"] is None
    assert not evaluate_unified_area({"sms": 8})["area_feasible"]


def test_unified_mip_allows_storage_compute_tradeoff():
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    model.setOptionValue("time_limit", 20)
    binding = add_unified_area_constraints(model)
    assert set(binding["budgets"]) == {"total_area_mm2"}
    for choices in binding["groups"].values():
        for col, choice in choices:
            model.changeColCost(col, -choice["memory_bits"])
    model.run()
    assert model.getSolution().value_valid
    result = decode_unified_solution(binding, model.getSolution().col_value)
    assert result["cost"]["area_feasible"]
    assert result["cost"]["physical_memory_bits"] > evaluate_unified_area()["physical_memory_bits"]
    assert result["hardware"]["memory_bytes_per_cycle"] == 64
