# Runnable baseline results

2026-10-07. Frozen default-structure hardware, packed64 compiled Qwen software,
fixed precision target, 64 B/cycle and 100-cycle external memory. Same unified
area budget: 1.1039550819992285 mm². No RTL or numerical tensor execution.

| Scenario | Device cycles | Status | Observed host time |
|---|---:|---|---:|
| Q-P128 | 812,589,857 | Complete instruction simulation | 269.82 s |
| Q-D128, 16 steps | 2,481,135,702 | Complete instruction simulation | 650.18 s |
| Q-P512 | 3,787,836,632 | Extrapolated | Not a completed host-time measurement |
| Q-D512, 16 steps | 2,894,095,806 | Extrapolated | Not a completed host-time measurement |

D128 averages 155,070,981.375 cycles/step; D512 estimated mean is
180,880,987.875. Host runs initially had four concurrent scenarios; after the
user requested extrapolation the two 512 processes were terminated. These host
times are not isolated execution benchmarks. P128 had 386,261,868 dynamic
instructions; D128 had 920,857,472.

## Extrapolation

P512 preserves 493 actually executed dispatches (including seven complete layers),
then fills unexecuted layer stages using the median matching stage from complete
512 layers 0–6. Final RMS uses four times the P128 cost; the last-token LM head
and remaining tail retain their P128 cost. The operation-level reconstruction is
in `prefill512-extrapolation.csv`. This is a stage extrapolation, not S512=4×S128.

D512 preserves nine complete steps, fits a line to steps 1–8, and predicts the
remaining seven. Partial step 9 is excluded from that sum to avoid double counting.
`estimates.json` contains observed steps, the slope and predictions. Neither
estimate establishes an error bound or validates later cache behavior. Do not
apply these baseline ratios unchanged to different hardware/software candidates.

## Run and inspect

```bash
./run baseline --out results/baseline-001 --jobs 1 --budget 7200
```

This executes P128/D128 and attaches the saved 512 reference estimates. Use
`--local` before `baseline` for explicit local execution; private defaults remain
unchanged. `--prepare-only` generates selected programs without executing them.
A later explicit `--scenarios Q-P512 Q-D512` runs 512; it was not rerun in this task.

`summary.json` separates complete measurements and extrapolations. Individual
128 receipts preserve execution identities/counters. CSV stage journals preserve
all completed stage timings and program hashes, including the two partial 512
runs. The exact raw outputs, logs, program manifests, ELF copies and checkpoints
remain in `results/baseline-full-20261007-01` (ignored local result storage); the
portable evidence here is retained in the repository. Frozen config copies and
`hashes.json` identify this collection. Source/runtime hashes are in the receipts.
The original four-process orchestrator correctly reports incomplete due to the
intentional 512 stops; its raw summary is not rewritten as fully simulated.

See [baseline specification](../../baseline_cn.md), [task](../../project_tasks_cn.md),
and [variable audit](../baseline-range-audit-20261007/README.md).
