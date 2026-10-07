# Native instruction measurements — 2026-10-07

`measurements.json` records measured local host time, model cycles, instruction
counts, RSS, targets, hashes and per-step totals. Prefill 512 is incomplete: its
26–28 minute figure is an estimate from completed full-size layers. It was stopped
when the user clarified that approximate timings were sufficient. Complete fenced
cache state and the exact matching runtime were preserved in the ignored result.
No incomplete receipt is presented as a complete inference.

The unchanged full prefill-128 program improved from 453.82 to 398.38 host seconds,
with identical cycles, instructions, bytes and resource counters. Peak RSS fell
from 1233.91 to 493.92 MiB. The separate packed64 software program took 297.33
seconds and changes GPU model cycles/instruction counts. These effects must be
reported separately. The unchanged cold LM-head comparison preserves final cache
state as well: 16.17→13.17 seconds and 1162.28→53.50 MiB.

`sensitivity.json` compares two actual compiled matrix programs performing the
same 128×256×256 multiply-accumulates. It retains their resources, instruction
counts, traffic and hardware changes. LSU/MSHR constraints increase cycles; RF
ports reduce writeback stalls but can alter cache order and need not improve total
cycles. LDS ports have no effect on this particular mapping.

These are single host measurements, some with concurrent tasks. Extended-ISA
timing is an explicit uncalibrated target; no new RTL/SystemC/synthesis was run.
Reproduction commands and accuracy gaps are in `docs/instruction-programs.md`.
