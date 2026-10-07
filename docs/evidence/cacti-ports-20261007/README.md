# CACTI multiport pilot — 2026-10-07

**Result:** all 60 configurations completed. Native multiport SRAM estimates give
RF area ratios of 1.71–1.93 (2R1W), 1.67–1.92 (1R2W), and 2.57–3.15 (2R2W), relative
to 1R1W at the same capacity, word width and technology. LDS 2RW/1RW ratios are
2.02–2.15. These support retaining port choices and replacing uniform multipliers
with structural estimates. The production cost function has **not** been changed.

## Source and reproduction

[HewlettPackard/CACTI](https://github.com/HewlettPackard/cacti) commit
`1ffd8dfb10303d306ecd8d215320aea07651e878`, built unmodified with `make -j4` on the
execution machine selected by the private project profile. The source and binary
remain in ignored results; the [upstream license](UPSTREAM-LICENSE) accompanies
configuration files derived from its `cache.cfg`.

```bash
git clone https://github.com/HewlettPackard/cacti.git <cacti-source>
git -C <cacti-source> checkout 1ffd8dfb10303d306ecd8d215320aea07651e878
make -C <cacti-source> -j4
python docs/evidence/cacti-ports-20261007/run_probe.py --source <cacti-source> --out <new-results-directory>
```

Run on the machine selected by your private profile. Do not overwrite `raw/`.
`run_probe.py` does not choose or contact a server itself.

[Original configurations, outputs and receipt](raw/report.json),
[derived ratios](ratios.json), [CSV](ratios.csv), and
[verification script](summarize.py) are preserved. Run
`python docs/evidence/cacti-ports-20261007/summarize.py` for read-only verification
of existing ratios. It verifies config hashes, echoed capacities/ports, RAM mode,
disabled ECC, successful exits and positive finite area/access/cycle values.
Raw outputs contain an irrelevant CACTI-IO `inf` for the inherited external-IO
configuration. Only the SRAM data-array section is used; IO numbers are discarded.

## What was modeled

Each run represents **one physical GPU bank**, modeled with one CACTI UCA bank.
No tags, ECC or whole-chip distribution network are included. The pilot uses
native multiport arrays, not a replicated LVT implementation.

| Family | Per-bank capacities | Word width | Ports |
|---|---|---|---|
| VGPR | 8 / 32 / 64 KiB | 1024 bits (32 lanes × 32 bits) | 1R1W, 2R1W, 1R2W, 2R2W |
| SGPR | 128 / 512 / 2048 B | 32 bits | 1R1W, 2R1W, 1R2W, 2R2W |
| LDS | 512 B / 4 KiB / 16 KiB | 32 bits | 1RW, 2RW |

The default points map to RF 4 banks, VGPR 1024 slots, SGPR 2048 slots;
LDS 128 KiB / 32 banks. VGPR word depth is slots/banks. RF read and write ports
are independent; an LDS RW port performs one read **or** one write per cycle.
No claim is made that the existing LDS event model covers all native multiport
read/write collision behavior.

Both 32 nm and 22 nm CACTI models were tested: 30 points per node. Optimization
is minimum array area, with broad delay/power tolerances and ED optimization
disabled. Each point may choose a different internal mat/mux organization.
This is an area-oriented family, not a set constrained to a common clock.
All 60 calls took 15.77 host seconds in aggregate, excluding build and transfer.

## Default-bank results (32 nm)

Multipliers are relative to the matching default bank with 1R1W (RF) or 1RW (LDS).
The old column is the **storage term's** multiplier, not the whole RF/LDS area.

| Bank / ports | Old storage multiplier | CACTI array area | Access time | Array cycle time |
|---|---:|---:|---:|---:|
| VGPR 2R1W | 2 | 1.853× | 1.278× | 1.322× |
| VGPR 1R2W | 2 | 1.842× | 1.279× | 1.323× |
| VGPR 2R2W | 4 | 2.960× | 1.591× | 1.680× |
| SGPR 2R1W | 2 | 1.709× | 1.119× | 1.128× |
| SGPR 1R2W | 2 | 1.699× | 1.119× | 1.128× |
| SGPR 2R2W | 4 | 2.649× | 0.927× | 0.998× |
| LDS 2RW | 2 | 2.065× | 1.589× | 1.595× |

SGPR 2R2W chooses a different internal mux organization, explaining why its
access time need not increase monotonically. Logs retain the selected organization.
Across matched points, switching 32 nm to 22 nm changes the area multiplier by
at most 3.65%. This is sensitivity within CACTI, **not** an ASAP7 accuracy bound.

## How to use this result

Keep all current variables. A next cost revision can tabulate capacity, width,
port and bank-dependent ratios for RF and LDS separately. This pilot samples
three capacities per family; it is not coverage of the entire search domain.
Native multiport arrays and LVT replication are alternative implementations:
do not multiply the native-array estimate by R×W again.

CACTI array area includes internal peripheral circuitry, while the current cost
model already has RF/LDS logic allowances. Before adoption, separate array
periphery from external collectors, arbitration and writeback to avoid double
counting. Establish base array anchors, then version coefficients and recompute
candidate costs. Keep native-ported logical capacity distinct from replication
bits in historical cost reports. FakeRAM's uncertain absolute density is not
resolved by these ratio experiments.

Array access time and cycle time must also be checked against the selected GPU
clock/pipeline policy. Do not directly translate 22/32 nm nanoseconds to ASAP7
cycles or silently retain the same latency for all area-minimum designs.
LVT selection/arbitration synthesis and common-cycle-time constrained array
experiments have not been performed in this pilot.
