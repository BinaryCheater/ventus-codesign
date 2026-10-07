# Default-resource baseline with native-array costs

Policy `ventus-unified-area-policy-v4`, baseline manifest v4, 2026-10-07.
[Machine-readable baseline](baseline.json) and [minimum-area designs](minimum-area.json).

| Quantity | Value |
|---|---:|
| Logic area estimate | 0.76263041754 mm² |
| Default storage area anchor | 0.3413246644592285 mm² |
| Total baseline estimate | 1.1039550819992285 mm² |
| Experiment budget | 1.11 mm² |
| Q-P128 cycles | 812,589,857 |
| Q-D128 total cycles (16 steps) | 2,481,135,702 |
| Q-P512 cycles, extrapolated | 3,787,836,632 |
| Q-D512 total cycles, extrapolated (16 steps) | 2,894,095,806 |

Hardware uses the pinned Ventus default resource configuration. Fixed modeled
BF16/FP16/TF32 capability, 64 B/cycle and 100-cycle external memory, and packed64
software are project assumptions, not claims about an unmodified upstream GPU.
The default resource provenance remains in the
[physical collection](../default-physical-baseline-20261007/README.md).

The new cost policy normalizes CACTI native-array area to the existing default
FakeRAM anchors. Therefore the default area stays the same by construction;
it is not a new synthesis measurement. Candidate areas change with capacity,
banks, ports and physical padding. Base synthesized RF/LDS logic comes from
subtrees whose generated memory leaves were blackboxed: macro-internal circuitry
was not mapped there. External collectors, writeback and routing/arbitration
logic retain their declared structural scaling; its port factors remain estimates.
CACTI includes array peripherals inside the storage term. The former replicated
payload term is replaced, not added. Non-payload storage retains its old density.

The completed 128 results are reused from the
[original run](../baseline-run-20261007/README.md). Hardware dictionaries,
instruction targets, Rust source hashes and Python runtime hashes matched;
frozen ELF inputs were also checked through the manifest. The execution engine
and software inputs have not changed. **No new full-network execution** occurred.
512 results retain their original extrapolation status, with no restarted runs.

Minimum-area MIPs under the revised cost function give 0.268821 / 0.511925 /
0.755029 / 0.998133 / 1.970548 mm² for 1/2/3/4/8 SM. Thus the active SM menu stays
1/2/3/4. All port options remain enabled. These are minima of the cost model.
Old optimized candidates require new cost evaluation; old optimality does not
carry over. Shared-clock and candidate latency feasibility remain unvalidated:
CACTI access/cycle estimates are diagnostics, not automatic changes to GPU cycles.
