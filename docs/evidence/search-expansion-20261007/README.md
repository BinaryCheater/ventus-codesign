# Expanded search domain — 2026-10-07

[Audit data](audit.json) and [reproduction script](audit.py) cover structural cost
v2.1 and unified area policy v2. Run from the repository root with
`uv run python -m docs.evidence.search-expansion-20261007.audit`.
Existing output is compared read-only. No full-network or RTL run is involved.

The active SM choices are 1/2/3/4; VGPR slots are 256/512/1024/2048;
SGPR slots are 128/256/512/1024/2048. Other choices stay the same.
The structural domain also retains 8 SM for larger-budget experiments.

Exact minimum-area MIPs over this domain yield 0.247732, 0.469748, 0.691763,
0.913778 and 1.801839 mm² for 1, 2, 3, 4 and 8 SM respectively.
Thus 8 SM remains infeasible at the unchanged 1.103955 mm² budget.
These minima use the estimated cost function, not synthesis of each candidate.
New small register sizes inherit the capacity/port scaling formula, without new
physical calibration. Hardware cost coefficients and baseline values are unchanged.

A compiled BF16 reuse GEMM (256×256×64, 32 single-warp blocks) exercises the new
choices. The probe has 16 warp/block slots per SM and 2048 VGPR slots so SGPR
constraints can become visible. At SGPR 128 it takes 501,870 cycles, versus
475,088 at SGPR 256 or more. The kernel uses 14 SGPR and 98 VGPR slots per warp:
SGPR 128 limits residency to 9 blocks; VGPR 256/512/1024 allows 2/5/10.
VGPR cycles are 485,444 / 490,823 / 474,599 / 475,088 respectively. More capacity
does not guarantee monotonic cycles: scheduling and shared-resource contention
also change. This is evidence that the options reach timing mechanisms, not a
claim that all larger configurations improve performance.

At 1/2/3/4 SM the same probe takes 944,202 / 475,088 / 325,372 / 242,400 cycles.
These isolated probes are not all area-feasible optimization candidates; their
hardware and area are recorded in the JSON. Whole-network improvements still
need evaluation of the selected design.

The active domain contains 34,673,723,965,440 structurally legal combinations
before the area constraint (about 2.96× the previous domain). This accounts for
legal tensor shapes and block/warp coupling; bank divisibility holds throughout.
It does not count software choices and does not claim distinct performance for
every combination. No new estimate of the area-feasible count is asserted.

The baseline hardware, software and timing parameters are unchanged. Previously
saved 128 runs and explicitly labelled 512 extrapolations remain applicable;
no 512 run was restarted.
