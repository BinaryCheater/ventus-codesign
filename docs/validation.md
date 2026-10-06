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
