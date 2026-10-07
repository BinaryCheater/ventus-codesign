# Structural cost v2 evidence — 2026-10-07

The public target includes BF16, FP16 and TF32 capabilities on the same chip.
The baseline costs **762,630.41754 library logic-area units** and **8,008,970 bits**.
This target uses an FP32 arithmetic envelope plus conversion/control allowances;
there are no new low-precision synthesis or performance measurements.

The actual HiGHS test opens all 27 fields and maximizes SM count under the
baseline's two cost budgets. It proves a cost-only optimum of 4 SMs, with area
726,706.66980 and 5,688,782 bits, using smaller compute and storage organizations.
This result is a constraint-interface test, not a faster GPU or a performance
optimum. Program, occupancy and timing constraints must still be attached.

Six FP32 Tensor points calibrate multiplier/output/constant coefficients. Maximum
fitted relative error is 0.743%; leave-one-shape-out maximum is 1.393%. Exact
sampled shapes use measured costs. These local errors do not bound unsampled
precision, interconnect, port, cache or integrated-chip errors.

Each of seven component coefficients was independently varied by ±25%, recomputing
both candidate and baseline with the same target. The candidate becomes
area-infeasible when Tensor cost is reduced 25%; the other 13 perturbations retain
cost feasibility. This exposes dependence on the cost assumption and is not an
uncertainty guarantee. Storage-bit budgets do not change with logic-area scales.

- `receipt.json`: target, baseline, candidate, solver status/bound/gap, shape checks,
  sensitivity and source/table hashes.
- `coefficients.json`: all 6,388 factor choices and their linear area/bit coefficients.
- `source/`: the v2 arithmetic, MIP adapter, experiment runner and frozen calibration
  table as used for this experiment.

Read-only verification checks source/coefficient hashes, recomputes both costs and
checks independent budgets. It does not rerun the solver or overwrite artifacts:

```bash
python -m codesign.ventus_costs.check_v2 --out docs/evidence/cost-structural-v2-final-20261007 --verify
```

A new experiment requires a fresh directory:

```bash
python -m codesign.ventus_costs.check_v2 --out results/cost-v2-new
```

The strict v1 table and archived measurements were not modified. This experiment
ran locally; the project's configuration-aware `./run costs` continues to respect
the private profile. Timing/executor semantics are unchanged. A local variable in
the concurrently added ELF frontend was renamed solely to resolve a Ruff E741
failure, with no arithmetic change.
