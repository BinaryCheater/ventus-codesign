"""Compile local structural choices to linear budget constraints in HiGHS."""

import math

from codesign.ventus.config import Hardware

from .structural import evaluate_structural_cost, factorized_cost_coefficients


def add_structural_cost_constraints(
    highs,
    *,
    logic_area_budget=None,
    memory_bits_budget=None,
    target=None,
    fixed=None,
    objective_weights=None,
    total_area_budget_mm2=None,
    storage_area_um2_per_bit=None,
):
    """Attach cost rows to an existing model; returned field columns are reusable.

    Objective weights, if supplied, minimize their weighted hardware-field values.
    This function adds no timing surrogate. The calling optimizer owns software,
    performance, occupancy and instruction-compatibility constraints.
    """
    from highspy import HighsVarType

    unified = total_area_budget_mm2 is not None
    if unified:
        if logic_area_budget is not None or memory_bits_budget is not None:
            raise ValueError("unified area replaces the separate budgets")
        if (
            type(storage_area_um2_per_bit) not in (int, float)
            or not math.isfinite(storage_area_um2_per_bit)
            or storage_area_um2_per_bit <= 0
        ):
            raise ValueError("storage area coefficient must be positive and finite")
    budgets = (total_area_budget_mm2,) if unified else (logic_area_budget, memory_bits_budget)
    for budget in budgets:
        if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0:
            raise ValueError("budgets must be positive and finite")
    coefficients = factorized_cost_coefficients(target)
    ranges = coefficients["ranges"]
    fixed = {} if fixed is None else dict(fixed)
    weights = {} if objective_weights is None else dict(objective_weights)
    if any(k not in ranges or type(v) is not int or v not in ranges[k] for k, v in fixed.items()):
        raise ValueError("fixed choices must lie in the structural ranges")
    if any(
        k not in ranges or type(v) not in (int, float) or not math.isfinite(v)
        for k, v in weights.items()
    ):
        raise ValueError("objective weights must be finite and name hardware fields")

    def binary(cost=0):
        col = highs.getNumCol()
        highs.addCol(cost, 0, 1, 0, [], [])
        highs.changeColIntegrality(col, HighsVarType.kInteger)
        return col

    def row(terms, lo, hi):
        highs.addRow(lo, hi, len(terms), list(terms), list(terms.values()))

    fields = {}
    for key, values in ranges.items():
        fields[key] = {
            v: binary(weights.get(key, 0) * v)
            for v in values
            if key not in fixed or fixed[key] == v
        }
        row(dict.fromkeys(fields[key].values(), 1.0), 1, 1)
    groups, area, bits = {}, {}, {}
    for name, choices in coefficients["groups"].items():
        columns = []
        for choice in choices:
            if any(k in fixed and fixed[k] != v for k, v in choice["choice"].items()):
                continue
            col = binary()
            columns.append((col, choice))
            area[col] = choice["logic_area"]
            bits[col] = choice["memory_bits"]
        groups[name] = columns
        row({col: 1.0 for col, _ in columns}, 1, 1)
        keys = set().union(*(c["choice"].keys() for _, c in columns)) if columns else set()
        for key in keys:
            for value, global_col in fields[key].items():
                terms = {col: 1.0 for col, choice in columns if choice["choice"][key] == value}
                terms[global_col] = -1.0
                row(terms, 0, 0)
    if unified:
        row(
            {col: (area[col] + storage_area_um2_per_bit * bits[col]) / 1e6 for col in area},
            -math.inf,
            total_area_budget_mm2,
        )
    else:
        row(area, -math.inf, logic_area_budget)
        row(bits, -math.inf, memory_bits_budget)
    return {
        "fields": fields,
        "groups": groups,
        "target": coefficients["target"],
        "budgets": (
            {"total_area_mm2": total_area_budget_mm2}
            if unified
            else {"logic_area": logic_area_budget, "memory_bits": memory_bits_budget}
        ),
        "storage_area_um2_per_bit": storage_area_um2_per_bit if unified else None,
    }


def decode_structural_solution(binding, column_values):
    """Decode global choices; independent arithmetic cost check uses no solver rows."""
    choices = {}
    for key, values in binding["fields"].items():
        selected = [v for v, col in values.items() if column_values[col] > 0.5]
        if len(selected) != 1:
            raise ValueError("solution is not an integral hardware choice")
        choices[key] = selected[0]
    h = Hardware(**choices).validate()
    cost = evaluate_structural_cost(h, target=binding["target"])
    if "total_area_mm2" in binding["budgets"] and cost["status"] == "estimated":
        cost["total_area_mm2"] = (
            cost["logic_area"] + binding["storage_area_um2_per_bit"] * cost["memory_bits"]
        ) / 1e6
    if cost["status"] != "estimated" or any(
        cost[k] > limit + 1e-6 * max(1, limit) for k, limit in binding["budgets"].items()
    ):
        raise ValueError("decoded solution violates independently evaluated cost budgets")
    return {"hardware": h.to_dict(), "cost": cost}
