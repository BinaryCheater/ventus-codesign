# Validation and reproduction

The extraction adds portability and privacy checks without recalibrating the
model. A redundant event-MILP completion bound resolves the observed Linux proof
timeouts; read-only Transformer replay accepts a larger host budget on slower
machines. Neither change adjusts predicted cycles or synthesized costs. Code/receipt hash migration is documented in the export manifest. None of
these checks imply full-network RTL equivalence or arbitrary-parameter accuracy.

## Fast regressions

```bash
uv run ruff check codesign ventus_project tests
uv run ruff format --check codesign ventus_project tests
uv run pytest -q
```

For configured server execution use `ventus-project run tests -q`. Direct
commands above run locally, useful for a collaborator's independent checkout.
Tests include workload legality, source control-state timing, Tensor backpressure,
bank conflict/ports, parameter sensitivity, shared FP arbitration, Transformer
conservation, ISA/numerical fixtures and cost budget behavior.

## Frozen evidence replay

One configuration-aware command checks export integrity and the selected frozen
receipts on your default machine:

```bash
uv run ventus-project run evidence
```

Individual local commands, from the project root with its package installed:

```bash
uv run python analysis/ventus_flow_20261006/cost_model/scripts/build_table.py analysis/ventus_flow_20261006/cost_model/raw codesign/ventus_costs/table_v1.json --verify
uv run python analysis/ventus_flow_20261006/quick_complete_20261006/check.py --verify
uv run python analysis/ventus_flow_20261006/performance-v7/check.py --verify
uv run ventus-model verify-transformer --out analysis/ventus_flow_20261006/performance-v7/small-s16-final --budget 300
```

These consume saved RTL evidence and replay predictions. They do not rerun RTL or
synthesis. Whole-GPU traces start at the recorded instruction-collection endpoint;
compute completion and final memory visibility are distinct endpoints. Broader
observed kernel errors do not bound full Transformer error.

The official C++/SystemC comparison failed several timing/resource tests in the
original study. Current fast-model rules are extracted from RTL rather than fitted
to that simulator. Original comparator inputs, outputs and mismatch reports are
under `model_accuracy/` and `evidence/`; the upstream comparator source/toolchain
is not installed as a dependency of the Python model.

## New independent experiments

```bash
uv run ventus-model extract --rtl-root vendor/ventus-gpgpu --out results/source-rules.json
uv run ventus-model demo --out results/menu-001
uv run ventus-model verify --out results/menu-001
uv run python analysis/ventus_flow_20261006/cost_model/scripts/run_demo.py results/cost-menu-001
uv run ventus-model transformer --input examples/tiny-transformer.json --out results/tiny-001 --budget 60
uv run ventus-model verify-transformer --out results/tiny-001
uv run ventus-model transformer --preset gpt2 --mode census --out results/gpt2-census-001
```

Census is a shape/instruction-organization inventory, without a complete timed
execution. Full GPT-2 timed execution has not completed within the earlier budget.
Fresh hardware checks should target a changed parameter's realization and likely
bottleneck before claiming optimization gain. Retain failures and intervals.

The packaging verification outcome is recorded in `docs/extraction-checks.json`.

## Structural cost v2 checks (2026-10-07)

`tests/test_ventus_structural_costs.py` checks all 27 fields, baseline partition,
replicated-port storage, immutable targets, precision capabilities, random legal
factor reconstruction, sensitivity and actual HiGHS feasible/infeasible budgets.
It preserves the strict v1 rejection tests. The new evidence directory
`docs/evidence/cost-structural-v2-final-20261007/` records source/table hashes, fit
residuals and leave-one-out errors. These errors concern FP32 component shapes,
not an error guarantee for the wider architecture or precision implementation.


## Native compiled-program regressions

`tests/test_ventus_rust.py` compares the native executor with the Python detailed
path across mixed streams, shared pipelines, Tensor shapes, RF ports, cache and
LDS constraints, including barriers. `tests/test_ventus_instruction_program.py`
compares two real compiled vector-add implementations with expanded/native/Python
execution and repeated-dispatch cache state, and validates hashed-journal recovery.
`tests/test_ventus_compiled_precision.py` checks actual official BF16/FP16/TF32
MMA encodings, grouped A/B/C reads and eight destination writes, masked tails and
two-/four-byte traffic. It checks full Qwen dimensions, bias/weight tying, GQA
aliases, KV append bytes and cross-dispatch dependencies. Small complete compiled
programs check all declared address ranges and fast/per-cycle native equivalence
under several hardware configurations. Full-task receipts independently check
dynamic MMA counts against launch shapes.

[Native program execution and remaining accuracy gaps](instruction-programs.md)
are explicit. These comparisons validate executor semantics and program coverage;
they do not extend the existing local FP32 RTL error bound to full BF16 Qwen.
No fresh RTL or SystemC simulations were run for this delivery.

## Unified baseline validation

`tests/test_ventus_unified_area.py` checks frozen config hashes and instruction
targets, default structure, area arithmetic, explicit external-memory projection,
unsupported configurations, and an actual MIP storage/compute exchange. The latter
selects more physical storage than the baseline under the same total-area budget,
ensuring no hidden legacy bit cap remains. It tests the area interface, not full
network optimality. Query `./run costs --model unified-v2 --hardware
examples/baseline-hardware-v1.json` through the configured execution wrapper.
Historical v1/v2 receipts remain unchanged.

## Frozen baseline execution and range audit

[Two completed Qwen runs and two 512 extrapolations](evidence/baseline-run-20261007/README.md) use the frozen hardware and program settings. [Range checks](evidence/baseline-range-audit-20261007/README.md) exercise every legal option on a compiled GEMM, record conditional changes, and prove 8-SM cost infeasibility within the current menu/budget. Probe inactivity is not a global performance proof. `./run --local baseline --out results/prepare-check-new --prepare-only` validates hashes and generates both default scenarios without executing them.

Expanded-domain validation (2026-10-07): [cost minima and compiled register-capacity probes](evidence/search-expansion-20261007/README.md), with version/hash compatibility, fixed 3-SM MIP decode and shared-ELF timing regressions in `tests/test_ventus_search_expansion.py`. Full suite: 220 passed; Ruff check and format check passed. This validates model behavior, not new RTL configurations.
