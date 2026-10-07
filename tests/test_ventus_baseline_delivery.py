import csv
import json
from pathlib import Path

from codesign.ventus.baseline import main
from codesign.ventus.config import Hardware
from codesign.ventus_costs.structural import RANGES

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_baseline_defaults_do_not_start_512(tmp_path, monkeypatch):
    out = tmp_path / "baseline"
    monkeypatch.setattr("sys.argv", ["baseline", "--out", str(out), "--prepare-only"])
    main()
    assert (out / "Q-P128-program/program.json").is_file()
    assert (out / "Q-D128-program/program.json").is_file()
    assert not (out / "Q-P512-program").exists()
    assert json.loads((out / "cost.json").read_text())["area_feasible"]


def test_published_cycles_reconcile_with_stage_journals():
    folder = ROOT / "docs/evidence/baseline-run-20261007"
    receipt = json.loads((folder / "summary.json").read_text())
    for row in receipt["measured"]:
        with (folder / (row["scenario_id"] + "-stages.csv")).open() as file:
            stages = list(csv.DictReader(file))
        assert sum(int(s["cycles"]) for s in stages) == row["cycles"]
        assert row["completed"] and row["error"] is None
    estimates = receipt["estimates"]
    with (folder / "prefill512-extrapolation.csv").open() as file:
        assert (
            round(sum(float(s["cycles"]) for s in csv.DictReader(file)))
            == estimates["prefill512"]["estimated_cycles"]
        )
    decode = estimates["decode512"]
    assert len(decode["measured_step_cycles"]) + len(decode["forecast_step_cycles"]) == 16
    assert (
        sum(decode["measured_step_cycles"]) + sum(decode["forecast_step_cycles"])
        == decode["estimated_cycles_16_steps"]
    )


def test_search_domain_lists_only_legal_tensor_shapes():
    space = json.loads((ROOT / "examples/search-space-v1.json").read_text())
    assert space["ranges"] == RANGES
    assert space["active_budget_ranges"]["sms"] == [1, 2, 4]
    assert len(space["legal_tensor_shapes"]) == 21
    for m, n, k in space["legal_tensor_shapes"]:
        Hardware(tensor_m=m, tensor_n=n, tensor_k=k).validate()
