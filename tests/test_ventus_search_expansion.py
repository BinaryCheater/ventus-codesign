"""Versioned ranges, budget coupling, and small compiled occupancy probes."""

import hashlib
import json
from pathlib import Path

import highspy
import pytest

from codesign.ventus.config import Hardware
from codesign.ventus.elf import ELFProgram
from codesign.ventus.model_program import TARGET
from codesign.ventus.rust import PreparedProgram, RustSession
from codesign.ventus_costs.structural import EXPANDED_RANGES
from codesign.ventus_costs.unified import (
    LEGACY_POLICY,
    add_unified_area_constraints,
    decode_unified_solution,
    evaluate_unified_area,
)

ROOT = Path(__file__).resolve().parents[1]


def test_expanded_manifest_and_legacy_policy():
    manifest = json.loads((ROOT / "examples/project-baseline-v2.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    space = json.loads((ROOT / manifest["search_space_file"]).read_text())
    assert space["ranges"] == EXPANDED_RANGES
    assert space["active_budget_ranges"]["sms"] == [1, 2, 3, 4]
    assert (
        evaluate_unified_area()["total_area_mm2"]
        == evaluate_unified_area(policy_path=LEGACY_POLICY)["total_area_mm2"]
    )
    for changes in [{"sms": 3}, {"vgpr_slots": 256}, {"sgpr_slots": 128}]:
        assert evaluate_unified_area(changes)["status"] == "estimated"
        assert evaluate_unified_area(changes, policy_path=LEGACY_POLICY)["status"] == "unsupported"


def test_expanded_mip_fixed_choices_decode_independently():
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    binding = add_unified_area_constraints(
        model, fixed={"sms": 3, "vgpr_slots": 256, "sgpr_slots": 128}
    )
    model.run()
    assert model.getModelStatus() == highspy.HighsModelStatus.kOptimal
    result = decode_unified_solution(binding, model.getSolution().col_value)
    assert result["hardware"]["sms"] == 3
    assert result["hardware"]["vgpr_slots"] == 256
    assert result["hardware"]["sgpr_slots"] == 128
    assert result["cost"]["area_feasible"]
    with pytest.raises(ValueError, match="ranges"):
        add_unified_area_constraints(highspy.Highs(), fixed={"sms": 3}, policy_path=LEGACY_POLICY)


def test_compiled_register_capacity_changes_timing_without_recompiling():
    elf = ELFProgram.read(ROOT / "tests/fixtures/compiled-transformer/reuse.elf")
    launch = elf.launch(
        "mma_reuse_bf16",
        [0x10000000, 0x90000000, 0, 0x10010000, 256, 256, 64, 0, 1],
        global_size=(1024, 1, 1),
    )
    program = PreparedProgram.from_elf(elf, launch)
    hardware = Hardware(
        **json.loads((ROOT / "examples/baseline-hardware-v1.json").read_text())
    ).with_changes(warps_per_sm=16, blocks_per_sm=16, vgpr_slots=2048)
    results = []
    for overrides in [{"sgpr_slots": 128}, {"sgpr_slots": 256}, {"vgpr_slots": 256}]:
        with RustSession(hardware.with_changes(**overrides), instruction_target=TARGET) as session:
            results.append(session.dispatch(program))
    assert len({x["instructions"] for x in results}) == 1
    assert results[0]["cycles"] > results[1]["cycles"]
    assert results[2]["cycles"] != results[1]["cycles"]
