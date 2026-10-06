# Current status

Snapshot: 2026-10-07. Timing semantics: `ventus-source-events-v7`.
Cost semantics: `ventus-synthesis-cost-v1`. Packaging: `ventus-codesign 0.1.0`.

The standalone extraction preserves the timing executor, hardware validation,
workload generation and numerical cost coefficients. It preserves the MILP
integer feasible schedules and objective, while strengthening its relaxation
with an independently derived completion bound and an executable incumbent.
The solver must still report status/bound/gap; a warm start is not a proof. The source extractor
has a provenance-only extension: it accepts the checked-in source manifest when
an upstream Git directory is absent. Exported receipts bind the exported hashes;
original hashes remain in the export manifest. Read-only Transformer verification
also accepts an explicit host-time budget for slower execution machines. The
initial portable code and receipts remain in `archive/export-lineage/`.
These portability changes are not new
hardware measurements or a new timing calibration.

## Results already obtained

- The online executor models readiness, finite operand collectors, RF bank/port
  contention, scoreboard dependencies, shared FADD/FMA arbitration, elastic Tensor
  stages, LSU occupancy, per-block release, and transaction-level memory supply.
- A small complete Transformer template runs prefill and decode without executing
  numerical tensors. Historical two-layer D64/H4/FFN256, S16 + two decode steps:
  333,660 modeled cycles, 285,328 instructions, 8.69 host seconds and 42.50 MiB
  process peak RSS. S64: 1,054,599 cycles and 30.05 seconds. Host times are single
  recorded measurements and vary by machine.
- Real LayerNorm machine instructions and performance IR share an emitter for
  supported 32-lane, multiple-of-32 widths. D32/D64 RTL probes were bit-exact and
  matched compute timing across 23 stage endpoints.
- Five mixed Tensor/memory kernels reached a maximum compute-span error of 3.04%.
  A later six-case extension includes softmax, GEMM–LayerNorm–GELU–softmax,
  two/four-warp streaming and cache-conflict-return; maximum compute-span error
  is 4.079%, with 448 checked output words bit-exact.
- Frozen synthesis coefficients support local cost queries and budget-constrained
  finite-menu MILP. One-layer D32 Transformer interoperability probes conserved
  the same mathematical work across RF/Tensor/LDS/software variants.

## Boundaries to preserve

The current frontend's softmax/GELU software is not yet the exact instruction
organization of the latest RTL probes. Complete attention, KV-cache behavior,
cross-kernel launch/synchronization and full-network RTL accuracy remain unverified.
Some older eight-warp tests have 7–16% errors. Instruction fetch, CTA dispatch and
parts of flush/visibility timing are outside the core modeled interval.

All 32 fields can be evaluated under declared model constraints; they do not all
have validated RTL realizations or synthesized costs. `Hardware.rtl_bindings()`
reports departures from tied upstream choices. Cost queries reject unsupported
configurations rather than assign zero cost. The official upstream simulator
should not be used as an accuracy oracle without an independent RTL check.

## Next optimization case

Use one fixed small Transformer workload and a cost-supported hardware menu:
SM count, RF banks, Tensor shape and LDS organization. Regenerate software and
addresses for each hardware/software choice; retain the same semantic workload.
Start with software warp count and dispatch grouping. Record latency, logic area,
memory bits, supported implementation, and model limitations for every candidate.

Select under explicit area/bit budgets, compare with exhaustive enumeration and
baselines, then independently check the mechanisms most relevant to the chosen
changes in RTL. The existing MILP covers an event workload and a finite candidate
menu; a complete Transformer optimization wrapper and broader structural MILP
still need implementation. English prompts are in `prompts/`.
