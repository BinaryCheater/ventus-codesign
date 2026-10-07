"""Create fresh v2 evidence or verify a saved receipt without solving/writing."""

import argparse
import hashlib
import json
from pathlib import Path

import highspy
import numpy as np

from .structural import (
    evaluate_structural_cost,
    factorized_cost_coefficients,
    load_table,
    structural_target,
)
from .structural_mip import add_structural_cost_constraints, decode_structural_solution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    target = structural_target(["bf16", "fp16", "tf32"])
    baseline = evaluate_structural_cost({}, target)
    coefficients = factorized_cost_coefficients(target)
    (out / "coefficients.json").write_text(json.dumps(coefficients, indent=2) + "\n")
    shape_rows = []
    for name, p in load_table()["points"].items():
        if name.startswith("tc-"):
            m, n, k = map(int, name.split("-")[1:])
            shape_rows.append((name, [m * n * k, m * k, 1], p["logic_area"]))
    x = np.array([r[1] for r in shape_rows])
    y = np.array([r[2] for r in shape_rows])
    fit = np.linalg.lstsq(x, y, rcond=None)[0]
    shape_checks = []
    for i, (name, row, area) in enumerate(shape_rows):
        keep = np.arange(len(y)) != i
        holdout = float(np.dot(row, np.linalg.lstsq(x[keep], y[keep], rcond=None)[0]))
        shape_checks.append(
            {
                "point": name,
                "measured": area,
                "fit_relative_error": float((x[i] @ fit - area) / area),
                "leave_one_out_relative_error": (holdout - area) / area,
            }
        )
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    model.setOptionValue("time_limit", 5)
    binding = add_structural_cost_constraints(
        model,
        logic_area_budget=baseline["logic_area"],
        memory_bits_budget=baseline["memory_bits"],
        target=target,
        objective_weights={"sms": -1},
    )
    model.run()
    solution = model.getSolution()
    if not solution.value_valid:
        raise RuntimeError(f"no incumbent: {model.getModelStatus()}")
    candidate = decode_structural_solution(binding, solution.col_value)
    sensitivity = []
    for group in ("rf", "tensor", "l1", "l2", "residency", "lsu", "shared"):
        for scale in (0.75, 1.25):
            altered = structural_target(target["precisions"], {group: scale})
            base = evaluate_structural_cost({}, altered)
            cost = evaluate_structural_cost(candidate["hardware"], altered)
            sensitivity.append(
                {
                    "group": group,
                    "scale": scale,
                    "target_sha256": cost["provenance"]["target_sha256"],
                    "baseline_area": base["logic_area"],
                    "candidate_area": cost["logic_area"],
                    "candidate_bits": cost["memory_bits"],
                    "feasible": cost["logic_area"] <= base["logic_area"] + 1e-6
                    and cost["memory_bits"] <= base["memory_bits"],
                }
            )
    snapshot = out / "source"
    snapshot.mkdir()
    for filename in ("structural.py", "structural_mip.py", "check_v2.py", "table_v1.json"):
        source = Path(__file__).with_name(filename)
        (snapshot / filename).write_bytes(source.read_bytes())
    receipt = {
        "version": target["version"],
        "baseline": baseline,
        "candidate": candidate,
        "solver": {
            "status": str(model.getModelStatus()),
            "optimal": model.getModelStatus() == highspy.HighsModelStatus.kOptimal,
            "objective": model.getObjectiveValue(),
            "objective_bound": model.getInfo().mip_dual_bound,
            "gap": model.getInfo().mip_gap,
            "columns": model.getNumCol(),
            "rows": model.getNumRow(),
        },
        "scope": "all 27 hardware choices; maximize SM count under cost-only budgets; no program/performance objective or physical optimality claim",
        "coefficient_count": sum(len(rows) for rows in coefficients["groups"].values()),
        "tensor_fit_coefficients": fit.tolist(),
        "tensor_shape_checks": shape_checks,
        "sensitivity": sensitivity,
        "source_hashes": {p.name: digest(p) for p in snapshot.iterdir()},
        "coefficients_sha256": digest(out / "coefficients.json"),
        "new_synthesis_runs": 0,
    }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": receipt["solver"]["status"],
                "sms": candidate["hardware"]["sms"],
                "coefficient_count": receipt["coefficient_count"],
            }
        )
    )


def verify(out):
    receipt = json.loads((out / "receipt.json").read_text())
    if digest(out / "coefficients.json") != receipt["coefficients_sha256"]:
        raise ValueError("modified coefficient table")
    for name, value in receipt["source_hashes"].items():
        if name not in {"structural.py", "structural_mip.py", "check_v2.py", "table_v1.json"}:
            raise ValueError("unknown snapshot file")
        if (
            digest(out / "source" / name) != value
            or digest(Path(__file__).with_name(name)) != value
        ):
            raise ValueError(f"changed source: {name}")
    baseline = evaluate_structural_cost({}, receipt["baseline"]["target"])
    candidate = evaluate_structural_cost(receipt["candidate"]["hardware"], baseline["target"])
    if baseline != receipt["baseline"] or candidate != receipt["candidate"]["cost"]:
        raise ValueError("cost receipt changed")
    if (
        candidate["logic_area"] > baseline["logic_area"] + 1e-6
        or candidate["memory_bits"] > baseline["memory_bits"]
    ):
        raise ValueError("independent budget check failed")
    print("Read-only v2 source/coefficient/cost verification passed; no solver rerun.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    (verify if args.verify else run)(args.out)


if __name__ == "__main__":
    main()
