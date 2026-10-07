# Current status

Snapshot: 2026-10-07. Timing semantics: `ventus-source-events-v7`; compiled-program extension: `ventus-instruction-rust-v9-1`.
Cost semantics: strict `ventus-synthesis-cost-v1` plus `ventus-structural-cost-v2`. Packaging: `ventus-codesign 0.1.0`.

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

## Frozen standalone experiment

[Baseline v1](baseline_cn.md) fixes default Ventus structure, modeled multi-precision capability, packed64 Qwen software and external memory settings. The four Qwen scenarios form the required task; GPT-2/Pythia transfer is optional until launchers exist. [Unified area](area-budget.md) replaces the aggregate bit cap with one logic-plus-storage budget. Query and MIP adapters are implemented; full performance optimization still needs integration. P128 and D128 have now completed under this frozen baseline. The two 512 runs were stopped at user request and extrapolated from their completed prefixes. [Results and statuses](evidence/baseline-run-20261007/README.md) preserve the distinction.

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

The legacy template frontend's softmax/GELU software is not yet the exact
instruction organization of the latest RTL probes. The compiled Qwen frontend
checks attention/GQA/KV launch behavior and retains cross-kernel cache state, but
full-network numerical/RTL accuracy and host-launch/flush timing remain unverified.
Some older eight-warp tests have 7–16% errors. Instruction fetch, CTA dispatch and
parts of flush/visibility timing are outside the core modeled interval.

All 32 fields can be evaluated under declared model constraints; they do not all
have validated RTL realizations or synthesized costs. `Hardware.rtl_bindings()`
reports departures from tied upstream choices. Cost queries reject unsupported
configurations rather than assign zero cost. The official upstream simulator
should not be used as an accuracy oracle without an independent RTL check.

## Current structural cost support

The v2 cost model supports the 27 hardware choices in the Chinese task guide,
with one common precision-capability target, nonzero service/port costs and
factorized linear MIP budgets. It reuses the 15 original synthesis points and
explicit assumptions; no new synthesis or timing calibration was run. Cost-only
constraints now exist independently of a finite full-chip candidate menu. Program
and performance couplings for full Transformer joint optimization remain a separate
integration task. See [cost mechanisms, assumptions and evidence](cost-model.md).

The strict v1 API still rejects unmeasured choices and all historical receipts
remain unchanged. Use v2 explicitly for broad derived-architecture exploration.


## Compiled programs and local speed measurements

The generic Rust executor now consumes official-compiler ELF programs, dynamically
executes control/address behavior, and schedules grouped precision instructions
through configurable resources. Full Qwen uses the frozen official configuration
and explicit device software variants, including final LM head, BF16 traffic, GQA
and continuous KV decode. [Commands and boundaries](instruction-programs.md)
distinguish these programs from the legacy GPT-2 template.

An unchanged complete cold LM-head dispatch improved from 16.17 to 13.17 host
seconds and 1162.28 to 53.50 MiB process peak RSS, with identical cycles (40,270,818),
instructions (14,006,600), resource counters and final cache state. The software
`packed64` full prefill-128 run completed in 297.33 seconds, with 812,589,857 model
cycles and 386,261,868 instructions. The earlier valid `packed` run took 453.82
seconds for 1,164,672,889 cycles and 496,471,792 instructions. Changing software
accounts for part of this speed difference and also changes GPU model cycles.

Local decode-16 completed in 640.13 seconds after context 128 and 806.75 seconds
after context 512. Prefill 512 was interrupted after the user clarified that
approximate timing was sufficient; 26–28 minutes is an estimate, not a completed
measurement. The unchanged full prefill-128 program took 398.38 seconds with
identical cycles/counters and 493.92 MiB peak RSS after executor changes.
[Portable measurements and sensitivity](evidence/instruction-rust-20261007/README.md)
retain completion status, source hashes and per-step totals. Extended instruction timing
and dedicated integer MUL/DIV-unit timing remain uncalibrated/incomplete; these
are concrete limits on prediction accuracy, independent of host execution speed.

Search revision (2026-10-07): structural cost v2.1 adds 3 SM and VGPR 256, and uses SGPR 128/256/512/1024/2048. Cost formulas and baseline area are unchanged. Unified policy v2 selects this range; `--model unified-v1` and `--model structural-v2` retain legacy ranges. See [expanded-domain evidence](evidence/search-expansion-20261007/README.md).

Budget revision (2026-10-07): unified policy v3 sets an explicit 1.11 mm² experiment budget. The baseline estimate and all cost coefficients remain unchanged. Policies v1/v2 and their results retain their original budgets. New candidates must be evaluated with v3; historical optimization results are not claimed optimal under the expanded budget.

Multiport pilot (2026-10-07): [60 CACTI RF/LDS configurations](evidence/cacti-ports-20261007/README.md) completed at 22/32 nm. Area/access/cycle ratios and raw inputs/outputs are retained. This is exploratory evidence for a future cost revision; active port costs and timing remain unchanged.

Current baseline: [manifest v4](../examples/project-baseline-v4.json), unified area policy v4, native-array v1. Area 1.103955 mm² against 1.11 mm² budget; 128 timing receipts reused after identity checks; 512 extrapolations retained. [Evidence](evidence/baseline-native-arrays-20261007/README.md). Array-area coverage is complete over the configured domain with explicit padding; candidate common-clock timing validation remains pending.
