"""Frozen cost-menu search; no synthesis in the optimization loop."""

import argparse
import hashlib
import json
from pathlib import Path

from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.mip import Candidate
from codesign.ventus.program import packed_gemm
from codesign.ventus.timing import build_graph
from codesign.ventus_costs import evaluate_cost, mip_coefficients, optimize_with_cost


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.mkdir()  # do not overwrite old results
    program = packed_gemm(16, strategy="resident", rf_conflict=True)
    candidates = [
        Candidate(f"sm{sm}-rf{rf}", Hardware(sms=sm, rf_banks=rf), program.workload)
        for sm in [1, 2]
        for rf in [4, 8]
    ]
    costs = [evaluate_cost(c.hardware) for c in candidates]
    coefficients = mip_coefficients([c.hardware for c in candidates])
    budget = max(costs[0]["logic_area"], costs[1]["logic_area"])
    bits = max(costs[0]["memory_bits"], costs[1]["memory_bits"])
    result = optimize_with_cost(
        candidates, logic_area_budget=budget, memory_bits_budget=bits
    )
    enumerated = [
        {
            "name": c.name,
            "cycles": execute(build_graph(c.workload, c.hardware))["cycles"],
            "cost": cost,
        }
        for c, cost in zip(candidates, costs, strict=True)
    ]
    feasible = [
        p
        for p in enumerated
        if p["cost"]["logic_area"] <= budget and p["cost"]["memory_bits"] <= bits
    ]
    best = min(p["cycles"] for p in feasible)
    assert result["optimal"] and result["cycles"] == best
    receipt = {
        "mip": result,
        "enumeration": enumerated,
        "coefficients": coefficients,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "finite menu; synthesis area plus separate blackboxed-memory bit budget; model cycles",
    }
    (args.out / "experiment.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "candidate": result["candidate"],
                "cycles": result["cycles"],
                "logic_area_budget": budget,
                "memory_bits_budget": bits,
            }
        )
    )


if __name__ == "__main__":
    main()
