# Versioned Ventus cost models

The strict `ventus-synthesis-cost-v1` API and its frozen 15-point table remain
unchanged. The new `ventus-structural-cost-v2` estimates all **27 hardware design
fields** in [the Chinese task guide](project_tasks_cn.md), fixing 32 lanes,
128-byte cache lines and the common external-memory target. It does not require
synthesis during search. Both versions use library logic-area units and a separate
memory-bit budget; neither returns SRAM macro area, energy or timing closure.

## Current experiment policy

The main task uses [unified-area-policy-v2](area-budget.md): v2 logic plus estimated SRAM area, with one 1.104 mm² baseline budget and no aggregate bit cap. Query `./run costs --model unified-v2`. Fixed multi-precision assumptions require no additional RTL work for this experiment. The separate budgets below describe the preserved legacy v2 interface.

## Queries and capabilities

```bash
./run costs --model structural-v2
./run costs --model structural-v2 --precisions bf16 fp16 tf32
./run costs --model structural-v2 --hardware examples/rf8.json
./run costs --model structural-v2 --coefficients
```

The wrapper honors `local.toml`. Direct `python -m codesign.ventus_costs` runs on
the current machine. The CLI defaults to v1 to preserve existing consumers.

```python
from codesign.ventus_costs import evaluate_structural_cost, structural_target

target = structural_target(["bf16", "fp16", "tf32"])
baseline = evaluate_structural_cost({}, target)
candidate = evaluate_structural_cost({"rf_banks": 16, "collectors": 16}, target)
assert candidate["target"] == baseline["target"]
```

One target describes the whole chip's supported precision set. Workload activity
cannot change static area. Low-precision hardware has **not** been synthesized:
v2 conservatively retains the FP32 datapath estimate and adds 10% of Tensor area
for conversion/control per non-FP32 capability. There is no proportional
bit-width discount or claim of low-precision timing/throughput validation. The
three-mode baseline must use the three-mode cost budget, not the FP32 v1 budget.
Modes, assumptions, range, model/table/Hardware hashes and component scales are
reported; changed modes or sensitivity scales define a different target hash.

## Disjoint calibrated components

The SM anchor is partitioned into nonoverlapping RF/collector/writeback, Tensor,
LDS, DataCache, LSU and residency/control subtrees. Eight scoreboard instances
are counted. Their residual retains fixed ALU/FPU/multiply/issue logic and
instruction storage. The fixed GPU is partitioned into L2 and the shared
allocator/interconnect remainder. Ancestors and descendants are never summed
as independent modules. This partition preserves the FP32 default exactly:
**696,678.41448 library logic-area units and 8,008,970 bits**.

| Component | Calibration | Structural estimate beyond sampled points |
|---|---|---|
| RF, collectors, WB | Embedded subtree plus measured RF4/RF8 bank delta | Bank slope; collector size, read/write/WB ports and capacity interaction; physical VGPR/SGPR bits |
| Tensor | Six sampled FP32 shapes | Nonnegative fit in multiplier count, output count and constant; exact sampled values used where available; unit replication plus dispatch allowance |
| LDS | Embedded subtree and measured 8/16/32-bank deltas | Capacity factor and port replication; payload bits plus response-queue anchor |
| L1 | DataCache/tag/queue subtrees | Sets, ways, tag-address width, MSHR×subentries and write-entry costs |
| L2 | Fixed-top Scheduler and stored array/tag/queues | Sets, ways, tag-address width, MSHR logic and queue storage |
| Residency | Scoreboards, instruction buffer, SIMT stack, CSR, warp scheduler, CTA-to-warp | Warp/block control growth and stored per-warp state |
| LSU | LSUexe subtree | Total entries and warps×per-warp outstanding interaction |
| Shared overhead | Fixed GPU minus L2 | SM distribution and total warp/block residency tables |

RF uses R×W replicated single-read/single-write storage as a declared cost
assumption. Read selection, broadcast write distribution and writer arbitration
are included in the port factor. Conflicting multiwrites may require replay; this
cost assumption does not validate the performance model's multiport concurrency.
LDS ports replicate the payload bank storage and scale service logic. Replicas
consume physical bits, even when logical capacity is unchanged. Queue and tag
estimates retain their measured anchors and change with their governing fields.
RF full-bank addressing is a v2 implementation assumption: sampled SGPR ports
address only 1,024 total slots although 2,048 are reserved. Additional RTL work
is required for changed capacities, ports, queues and precision support.

All fractions and implementation assumptions are public in `ASSUMPTIONS` in
`structural.py`. v2 uses assumed interactions and fits, not full integration
measurements. It deliberately does not promise exact agreement with every v1
variant: embedded and standalone synthesis contexts differ. Out-of-range or
fixed-target deviations return unsupported/null costs; illegal Hardware fails
validation after overrides. New source measurements should produce a new cost
version and fresh experiment records.

## Factorized MIP budget interface

With the legacy v2 target, `factorized_cost_coefficients(target)` produces **6,388 local choices** (including
SM count in each factor), rather than enumerating the global Cartesian product.
RF ports, banks, collector and capacities share a factor; LSU warps/outstanding
and Tensor dimensions are also jointly tabulated. Choose one row in each group,
link each field to its common global one-hot choice, and add area/bit contributions.
The residency factor includes shared overhead; a separate fixed-SM factor retains
the residual. This exactly reproduces v2 arithmetic over the declared ranges.

```python
import highspy
from codesign.ventus_costs import add_structural_cost_constraints

model = highspy.Highs()
binding = add_structural_cost_constraints(
    model,
    logic_area_budget=baseline["logic_area"],
    memory_bits_budget=baseline["memory_bits"],
    target=target,
)
# binding["fields"][field][value] gives the global choice column.
# Attach program, occupancy and performance constraints to the same model.
```

The adapter adds exactly-one, field consistency, local legality and linear
budget rows. `decode_structural_solution` validates decoded Hardware and recomputes
cost independently of solver rows. The adapter supplies cost constraints; it
does not implement a full Transformer performance objective or numerical proof.
The older event MILP and finite-menu demo remain unchanged.

## Sensitivity and evidence

Use `structural_target(..., scales={"rf": 1.25})` or 0.75 to perturb one component.
Recompute **both candidate and baseline** with that same target; keep precision
capabilities fixed across all models. Storage bits remain physical capacity,
while scales vary logic coefficients. Sensitivity tests measure dependence on
assumptions, not physical error bounds.

The new receipt, coefficient table, source snapshot, fit/holdout checks and
sensitivity example are in [v2 evidence](../docs/evidence/cost-structural-v2-final-20261007/).
No new synthesis was run for v2. The 15 original points, libraries and RTL remain
unchanged in the historical archive. Valuable next measurements are actual
multi-precision Tensor logic and supply networks, followed by cache/MSHR and
residency variations; uncertainty is explicit while search can proceed.

## Collected default physical reference

The [default physical baseline collection](evidence/default-physical-baseline-20261007/README.md)
checks all 202 standard cells against public 1× LEF geometry, establishing µm²
for the collected Liberty area numbers. It preserves default RTL dimensions,
38 scoped storage groups, four public ASAP7 FakeRAM footprints, and the existing
scalar-ALU timing evidence. Capacity-only logic-plus-storage illustrations are
1.038 mm² for the FP32 default and 1.104 mm² for the derived multi-precision target.
They are not bank/port-mapped core areas or a new v2 budget. Live v1/v2 APIs and
saved results remain unchanged. The separate unified-area policy adopts this capacity approximation for the experiment; it does not claim detailed macro mapping.

Search revision (2026-10-07): structural cost v2.1 adds 3 SM and VGPR 256, and uses SGPR 128/256/512/1024/2048. Cost formulas and baseline area are unchanged. Unified policy v2 selects this range; `--model unified-v1` and `--model structural-v2` retain legacy ranges. See [expanded-domain evidence](evidence/search-expansion-20261007/README.md).

The expanded v2.1 target produces 11,945 local factor choices, including the 8-SM structural option. These are module choices linked by shared hardware fields, not 11,945 whole-chip candidates. Pass `structural_target(precisions, version="ventus-structural-cost-v2.1")` explicitly to the low-level API; the unified v2 API selects it automatically.
