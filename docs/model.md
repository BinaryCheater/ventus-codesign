# Model, variables and MILP boundary

The fast performance model starts from decoded operations: path, registers,
dependencies, active lanes, addresses and warp/block identity. It advances ready
instructions through finite resources and source-derived control/pipeline stages.
It predicts model cycles and counters without computing tensor values. Fresh RTL
elaboration or compilation is not part of each candidate evaluation.

## Explicit design fields

There are **29 GPU hardware fields** and **3 external-memory target fields** in
`Hardware`. These are API fields, not a claim that upstream RTL exposes 29
independent knobs or that every point has been calibrated.

| Group | Fields |
|---|---|
| Replication and residency (4) | `sms`, `warps_per_sm`, `blocks_per_sm`, `threads` |
| RF, collection and writeback (7) | `rf_banks`, `rf_read_ports`, `rf_write_ports`, `writeback_ports`, `collectors`, `vgpr_slots`, `sgpr_slots` |
| Tensor (4) | `tensor_m`, `tensor_n`, `tensor_k`, `tensor_units` |
| LDS and shared line width (4) | `lds_bytes`, `lds_banks`, `lds_ports`, `line_bytes` |
| L1 (5) | `l1_sets`, `l1_ways`, `l1_mshrs`, `l1_subentries`, `l1_write_entries` |
| L2 (3) | `l2_sets`, `l2_ways`, `l2_mshrs` |
| LSU (2) | `lsu_entries`, `lsu_per_warp` |
| External memory (3) | `memory_channels`, `memory_bytes_per_cycle`, `memory_latency` |

The GPU field total is 4 + 7 + 4 + 4 + 5 + 3 + 2 = 29.
Tensor `n` is the upstream reduction dimension; `k` is output columns. Defaults
are 2 SMs, 8 warps/SM, 32 lanes, RF4, Tensor 4×8×4, 128 KiB LDS/SM, 64 KiB L1/SM,
128 KiB shared L2, and a separately specified simulator memory target.

The model also has software organization fields: warp count, dispatch tile
batching and elementary-function implementation. Workload shapes, addresses,
register assignment, operation mix, reuse, transpose/packing, dependencies and
lane masks are program inputs. They should enter a search as explicit software
choices when a generator can produce their concrete instruction organization.

## Size and coupling rules

- All hardware fields are positive integers. Several bank/cache/lane/line sizes
  are powers of two; Tensor `n` is a power of two greater than one.
- Each pairwise Tensor dimension product fits in the lane count. Tensor latency
  follows multiply and reduction stages, queues and final addition.
- VGPR and SGPR pools divide into RF banks. A line contains at least one 32-bit
  word per LDS bank. Blocks/SM do not exceed warp slots.
- Upstream ties collectors and LSU entries to warps, register pools to fixed
  multiples of warps, LDS banks to lanes, and the Tensor shape to lane presets;
  port counts and Tensor unit count are fixed. The model can separate these
  fields and reports the RTL unbinding needed. A report is not an RTL implementation.
- Cost modeling additionally enforces physical/addressable storage distinctions.
  The sampled SGPR bank interface addresses 1,024 slots although 2,048 are reserved.

Queue depths, arbitration policy, bypass/handshake rules and reduction topology
are currently mechanism rules. Only turn one into a design variable when there
is a meaningful implementation family, a legality constraint and an evaluation
rule. Counting every source statement or trick as a variable inflates the space
without adding a realizable design choice.

## Simulator and MILP

The simulator evaluates readiness, resource contention and resulting cycles for
one concrete program/configuration. It supplies independent execution checks for
an optimizer's proposed schedule. The current event MILP uses candidate selection,
event times, precedence, and resource order/capacity constraints. Synthesis cost
coefficients restrict feasible candidates before solving. The demo cross-checks
its finite-menu optimum by independently enumerating and executing that menu.
A redundant lower bound, `makespan >= sum(y_j * executed_cycles_j)`, strengthens
the fractional candidate relaxation. Each selected graph already implies that
bound, so integer feasible schedules and modeled cycles are unchanged. An executable incumbent from the same graph execution is also supplied. Solver
status/bound/gap still establish its reported proof; a warm start alone establishes
no optimality claim. These solve the Linux proof timeouts observed during extraction
without weakening replay.

A full structural MILP would additionally encode component counts/capacities,
software mapping and their couplings, then verify the solution in the executor.
Those variables and constraints are not implemented merely by exposing the 32
performance API fields. Full Transformer performance execution exists; full
Transformer joint structural MILP remains an additional integration task.

## Source evidence

`vendor/ventus-gpgpu/SOURCE.json` pins the upstream commit, dependencies and
working-tree hashes. `ventus-model extract --rtl-root vendor/ventus-gpgpu --out
results/source-rules.json` checks declarations and source anchors against that
snapshot. Mechanism fidelity and remaining approximations appear in its output.
Detailed historical variable surveys are under
`archive/analysis/ventus_variable_audit_20261003/`; their source-description counts
are separate from the live model's explicit design fields.

## Structural cost factorization (2026-10-07)

Cost v2 exposes the 27 choices of the internal task guide. Each local factor has
binary variables z[g,o], sum_o z[g,o]=1. Global one-hot y[p,v] represents each
hardware field value; sum_{o: o[p]=v} z[g,o]=y[p,v] for every factor containing p.
SM replication is included in local coefficients and linked globally, avoiding
continuous products. Residency choices enforce blocks<=warps and Tensor choices
enforce pairwise lane packing. Area and bit budgets are sum_{g,o} A[g,o]z[g,o]<=A0
and sum_{g,o} B[g,o]z[g,o]<=B0. Shared overhead is counted in residency and the fixed
SM remainder has its own factor. This is an exact linear representation of the
v2 approximation. Program occupancy, instruction shapes and performance need their
own couplings. See [cost model](cost-model.md).


## Compiled instructions and Rust execution

[The native program contract](instruction-programs.md) adds actual Ventus ELF
inputs, control/address execution and compact instruction ABI v9. Instructions
retain grouped register reads/writes, access width, SIMT active mask, warp identity
and resources; the timing core receives no operator/model names. Compatibility
with compact v7/v8 inputs is retained. Per-warp interleaving is computed anew for
each hardware configuration rather than replaying a stored global schedule.

The v7 calibrated FP32 paths remain separate from the explicit extended-ISA
target. BF16/FP16/TF32 MMA share configured Tensor units, grouped scoreboard and
RF/writeback service; conversion, packed arithmetic, shuffle and SFU have declared
latencies. New defaults are structural assumptions, not another RTL measurement
or a SystemC fit. Integer multiply/divide currently retain the basic scalar/vector
timing classes; dedicated unit latency is an accuracy gap.

Resident instructions and live state are recycled. Idle jumps and pipeline ring
advancement preserve elastic capacity/backpressure. Per-line merge history is
discarded only after L1 eviction has waited for the old fill. Fenced checkpoints
retain caches, replacement state, cumulative counters and cycle offset, and reject
program/hardware/target/runtime changes. No per-layer timing multiplication is used.

## Unified experiment area policy

The active experiment uses [current baseline](baseline_cn.md) and [one total-area constraint](area-budget.md). In unified policy v4, local coefficients become `(logic_area + storage_area_um2)/1e6`, with native-array lookup for RF/LDS and density scaling for other storage; their sum must not exceed the experiment budget of 1.11 mm². No separate total-bit cap is added. Occupancy/capacity and shared-field consistency remain. The old dual-budget derivation above describes historical v2. Precision target constants are fixed; no extra precision-switch penalty is introduced.

Current search choices are frozen in [search-space-v3](../examples/search-space-v3.json). Cost target v2.1 expands SM and register capacities; instruction timing mechanisms are unchanged. [Compiled probes](evidence/search-expansion-20261007/README.md) confirm that smaller register pools affect admission and cycles without recompiling kernels.
