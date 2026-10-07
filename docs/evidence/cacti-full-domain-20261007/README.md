# Full-domain native-array characterization

This extends the [60-point pilot](../cacti-ports-20261007/README.md) using the same
pinned, unmodified CACTI build and minimum-area settings. [run_probe.py](run_probe.py)
uses the same `--source` and fresh `--out` arguments. [Raw receipt](raw/report.json)
retains all **128 attempted runs** at 22/32 nm; 104 have valid SRAM results.

Twenty-four attempts are invalid: VGPR 2 KiB banks and SGPR 32/64 B banks at both
nodes. Some invalid runs return zero but omit array results; these are rejected,
not assigned zero cost. Runtime mapping pads a too-small VGPR bank to 4 KiB and
SGPR bank to 128 B. This is an explicit minimum-macro assumption, not a claim
that a small flop implementation has the same area. Logical capacity is unchanged.

[build_table.py](build_table.py) verifies input hashes and retains 52 successful
32-nm bank entries in `codesign/ventus_costs/native_arrays_v1.json`. The 22-nm
measurements remain a sensitivity reference. The table covers every current
RF/LDS choice after explicit padding, including bank-capacity combinations.

VGPR: 1024-bit words, capacities 2–64 KiB; SGPR: 32-bit words, 32 B–2 KiB;
LDS: 32-bit words, 512 B–16 KiB. RF uses independent 1/2 read and 1/2 write ports;
LDS uses 1/2 shared read/write ports. Arrays are native multiport structures,
without LVT replication. See the pilot's license and methodology.

This characterization supplies estimated area ratios and diagnostic access/cycle
times. It does not establish ASAP7 timing, physical macro availability or a shared
clock across candidates. Active instruction timing is unchanged in this revision.
