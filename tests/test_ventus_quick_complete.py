"""Independent numeric/address checks for the broader frozen real ISA cases."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path("analysis/ventus_flow_20261006/quick_complete_20261006")
SPEC = importlib.util.spec_from_file_location("quick_isa_check", ROOT / "isa_check.py")
DECODER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DECODER)
CASES = json.loads((ROOT / "probes/cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_real_words_outputs_addresses_and_private_warp_slices(case):
    assert DECODER.execute(case, ROOT / "probes" / case["name"]) > 0
    if case["warps"] > 1:
        stores = [op for op in case["workload"]["operations"] if op["kind"] == "store"]
        assert len(stores) == case["warps"]
        assert len({a for op in stores for a in op["addresses"]}) == 32 * case["warps"]
    else:
        values = np.array([DECODER.number(w) for w in case["expected_words"]])
        assert np.all(values >= 0) and abs(values.sum() - 1) < 2e-6


def test_each_nonlinear_stage_against_float64_dense_function():
    case = next(c for c in CASES if c["name"] == "chain-w1")
    snapshots = []
    DECODER.execute(case, ROOT / "probes" / case["name"], snapshots=snapshots)
    assert len(snapshots) == 4
    values = [np.array(list(map(DECODER.number, words))) for _, words in snapshots]
    x = values[0]
    gamma = 0.5 + np.arange(32) % 5 / 8
    beta = 0.25 + np.arange(32) % 7 / 16
    norm = (x - x.mean()) / np.sqrt(np.mean((x - x.mean()) ** 2) + 1e-5) * gamma + beta
    gelu = 0.5 * norm * (1 + np.tanh(np.sqrt(2 / np.pi) * (norm + 0.044715 * norm**3)))
    softmax = np.exp(gelu - gelu.max())
    softmax /= softmax.sum()
    for actual, expected in zip(values[1:], (norm, gelu, softmax)):
        assert np.max(np.abs(actual - expected)) < 5e-6
