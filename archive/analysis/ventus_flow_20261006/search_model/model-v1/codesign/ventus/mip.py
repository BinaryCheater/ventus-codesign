"""Conditional event constraints select hardware and a software template jointly.

Cache outcomes and resource service order are compiled separately for each finite
candidate. The MILP does not optimize replacement policy or hardware arbitration.
"""

from dataclasses import dataclass

import highspy

from codesign.solver import SparseMilpMatrix

from .config import Hardware
from .graph import TimingGraph, execute
from .ir import Workload
from .timing import build_graph


@dataclass(frozen=True)
class Candidate:
    name: str
    hardware: Hardware
    workload: Workload


def optimize(candidates, *, budgets=None, time_limit=30):
    if not candidates or len({c.name for c in candidates}) != len(candidates):
        raise ValueError("nonempty candidate menu with unique names required")
    if type(time_limit) not in {int, float} or not 0 < time_limit < float("inf"):
        raise ValueError("time_limit must be finite and positive")
    budgets = budgets or {}
    allowed = {"storage_bytes", "tensor_multipliers"}
    if set(budgets) - allowed or any(type(x) is not int or x <= 0 for x in budgets.values()):
        raise ValueError("budgets must be positive integer resource limits")
    graphs: list[TimingGraph] = [build_graph(c.workload, c.hardware) for c in candidates]
    # Sum of maximum incoming delays is a safe graph-specific longest-path bound.
    horizon = (
        max(
            sum(max((lag for _, lag in edges), default=0) for edges in g.predecessors)
            for g in graphs
        )
        + 1
    )
    matrix = SparseMilpMatrix()
    selected = [matrix.var(integer=True) for _ in candidates]
    matrix.row([(v, 1) for v in selected], lower=1, upper=1)
    makespan = matrix.var(upper=horizon, cost=1)
    for resource, budget in budgets.items():
        matrix.row(
            [(selected[j], c.hardware.resources()[resource]) for j, c in enumerate(candidates)],
            upper=budget,
        )
    for j, graph in enumerate(graphs):
        clock = [matrix.var(upper=0)]
        clock += [matrix.var(upper=horizon) for _ in graph.names[1:]]
        for event, edges in enumerate(graph.predecessors[1:], 1):
            # Nonselected candidates have all event times zero.
            matrix.row([(clock[event], 1), (selected[j], -horizon)], upper=0)
            for previous, delay in edges:
                matrix.row(
                    [(clock[event], 1), (clock[previous], -1), (selected[j], -horizon)],
                    lower=delay - horizon,
                )
        matrix.row(
            [(makespan, 1), (clock[graph.terminal], -1), (selected[j], -horizon)], lower=-horizon
        )
    solver = matrix.highs(
        {"experiment": {"time_limit_s": time_limit, "relative_gap": 0, "solver_seed": 0}}
    )
    solver.run()
    status = solver.getModelStatus()
    solution = solver.getSolution()
    if not solution.value_valid:
        return {"status": str(status), "candidate": None, "optimal": False}
    chosen = [j for j, v in enumerate(selected) if solution.col_value[v] > 0.5]
    if len(chosen) != 1:
        raise RuntimeError("MILP returned invalid candidate selection")
    index = chosen[0]
    # Independent graph execution checks the chosen schedule without solver objects.
    replay = execute(graphs[index])
    score = solution.col_value[makespan]
    if score + 1e-6 < replay["cycles"]:
        raise RuntimeError("MILP clock understates independently executed completion")
    if status == highspy.HighsModelStatus.kOptimal and abs(score - replay["cycles"]) > 1e-6:
        raise RuntimeError("optimal MILP clock differs from graph execution")
    for name, limit in budgets.items():
        if candidates[index].hardware.resources()[name] > limit:
            raise RuntimeError("chosen hardware exceeds resource budget")
    info = solver.getInfo()
    return {
        "status": str(status),
        "optimal": status == highspy.HighsModelStatus.kOptimal,
        "candidate": candidates[index].name,
        "cycles": replay["cycles"],
        "objective": score,
        "objective_bound": info.mip_dual_bound,
        "gap": info.mip_gap,
        "columns": len(matrix.lower),
        "rows": len(matrix.row_lower),
        "integer_choices": len(selected),
        "hardware": candidates[index].hardware.to_dict(),
        "rtl_unbinding_required": candidates[index].hardware.rtl_bindings(),
        "resources": candidates[index].hardware.resources(),
        "counters": replay["counters"],
        "scope": "Optimality is within the declared finite menu and compiled transaction timing model.",
    }
