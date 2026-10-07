# Baseline search-range audit

2026-10-07. Source checks plus real execution of one compiled BF16 GEMM (32×64×64,
eight single-warp blocks). Each legal one-field variant was evaluated with the
fixed experiment memory/timing target. Warp/block changes use a paired adjustment
when needed for legality. `audit.json` preserves all cycles, changed counters,
area checks, launch resources and compiler resource records. Run
`PYTHONPATH=. python docs/evidence/baseline-range-audit-20261007/audit.py` to
recompute and compare without replacing the receipt.

## Conclusions for search

The 27 fields form a reasonable broad *structural* domain, not 27 independent,
equally influential performance axes. [Machine-readable choices](../../../examples/search-space-v1.json)
include the 21 legal Tensor triples; only five multiplier-product values
(8/16/32/64/128) occur. The compiled grouped-MMA timing path depends on the product,
not the three dimensions separately. Area also depends on output count m×k.
Treat shape as a coupled choice; do not claim a three-axis geometry timing model.

The ELF frontend uses one warp per block. Residency is
min(block slots, warp slots, floor(VGPR/usage), floor(SGPR/usage), floor(LDS/usage)).
Current fixtures require at most 22 scalar slots per warp and 128 LDS bytes per
block after launch alignment. Even 16 resident blocks need only 352 scalar slots
and 2 KiB LDS. Thus the current SGPR choices (1024/2048/4096) and LDS capacities
(16–128 KiB) do not cross capacity limits for these programs. The minimum is a
reasonable fixed-software pruning choice; retain larger capacities for reference
and new software. This does not make LDS ports/banks irrelevant: stack traffic
uses LDS and different access patterns can change bank conflicts.

The packed64 reuse kernel requires 98 vector slots per warp; 512 slots permit at
most five such resident blocks, versus ten for 1024 and twenty for 2048 before
other limits. Keep the VGPR capacity choices and their occupancy coupling.

Two RF write ports cannot be exploited through a one-credit writeback path;
search port counts jointly. Per-warp LSU quotas above global LSU capacity are
redundant for throughput; use capacity constraints and local pruning. Increasing
SMs, banks, ports or queues can exceed the area budget when all other baseline
resources stay fixed; do not remove them merely on that basis—joint area exchange
may make them feasible. SM counts 1/2/4/8 are discrete research samples, not an
RTL power-of-two requirement; intermediate counts are not in the current v2 menu.

## Observed probe behavior

Baseline: 14,701 cycles. One SM: 27,917; four SMs: 8,414 (over budget if changed
alone). L1 write entries 2/4/8/16: 25,977/14,701/9,150/6,813 cycles. LSU per-warp
quota 1/2/4/8: 16,599/14,801/14,701/14,654 cycles. These demonstrate actual parameter
use, not full-network speedups or monotonic guarantees. Smaller Tensor capacity
slightly improves this memory-dominated probe by changing request/interleaving
order; use a compute-heavy probe or final network to assess compute capacity.
A parameter with unchanged cycles here is not proven globally irrelevant.

The public ranges remain unchanged to preserve v2 evidence. Corrections are an
explicit legal-shape list, software occupancy bounds, and conditional/dominance
advice; no synthetic extra variables or unsupported hardware ranges were added.

## Whole-domain area feasibility

A separate factorized cost MIP minimized area at fixed SM count. Exact menu
minima are 0.261575 / 0.497434 / 0.969150 mm² for 1 / 2 / 4 SMs; 8 SMs is infeasible
under 1.103955 mm² even after joint resource minimization. This is a cost-domain
result, not a performance optimum. `sm-feasibility.json` preserves solver status
and feasible minima. The active baseline-budget menu therefore uses **1/2/4 SMs**;
the broader structural range retains 8 for experiments with larger budgets.
