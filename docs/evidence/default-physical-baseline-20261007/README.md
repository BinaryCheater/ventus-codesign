# Default Ventus physical baseline collection

Collected 2026-10-07. This collection identifies the project-pinned default RTL,
checks the area scale against public physical views, and collects SRAM area
references. It changes no live cost or timing semantics and runs no synthesis.

## Default configuration

The source is `vendor/ventus-gpgpu/ventus/src/top/parameters.scala` in the
project snapshot at commit `681172541a8a34ffb43c483a19c075acbc11a4eb`.
The snapshot may contain preserved working-tree changes; the collected file hash
is authoritative. This is the project-pinned default, not a claim about every
Ventus release or a fabricated production chip.

| Resource | Default |
|---|---|
| SMs | 2 |
| Residency per SM | 8 warps, 8 blocks, 32 threads per warp |
| RF per SM | 4 banks; 1024 vector slots × 32 lanes × 32 bits = 128 KiB; 2048 scalar slots × 32 bits = 8 KiB reserved |
| Collectors | 8 per SM |
| Tensor per SM | one FP32 unit, project dimensions (4,8,4), middle dimension is reduction |
| LDS per SM | 128 KiB, 32 banks |
| Data L1 per SM | 256 sets × 2 ways × 128 bytes = 64 KiB |
| Shared L2 | 64 sets × 16 ways × 128 bytes = 128 KiB |
| LSU per SM | 8 entries; per-warp outstanding limit 4 |

The sampled SGPR address interface exposes fewer slots than its reserved physical
storage; keep the existing v1/v2 addressing distinction. Multi-precision support
in cost v2 is an added architectural assumption, not part of this FP32 default.
External memory wrapper timing is not a chip frequency specification.

The existing synthesized storage inventory has 38 scoped memory groups:
2 × 3,424,026 bits per SM + 1,160,918 shared bits = **8,008,970 bits**.
This includes more than programmer-visible payload: instruction storage, tags,
queues and control arrays also consume storage. These leaves were blackboxed;
they have not yet been mapped individually to SRAM macros or flip-flops.

## Area units and SRAM references

All **202 cells** across the five collected RVT TT Liberty files match the
same-named cell's width × height in the public **1× LEF** within 1e-8.
Consequently their area numbers have a direct square-micrometre interpretation
for these files. The existing default logic estimate is **696,678.41448 µm² =
0.69667841448 mm²**. Its structure/integration estimation errors are unchanged.
The v2 BF16/FP16/TF32 derived baseline is **0.76263041754 mm² of logic**.
These are placed-cell-equivalent sums, without placement whitespace or SRAM.

Public OpenROAD ASAP7 macro abstracts collected from a pinned commit:

| Macro | LEF width × height (µm) | Footprint (µm²) |
|---|---|---:|
| fakeram7_256x32 | 8.36 × 42 | 351.12 |
| fakeram7_128x64 | 16.72 × 21.6 | 361.152 |
| fakeram7_64x256 | 33.25 × 46.8 | 1,556.1 |
| fakeram7_256x256 | 33.25 × 84 | 2,793 |

The 256×256 macro's Liberty explicitly specifies 8 address bits and 256 data
bits. Its Liberty area is 2,751.883 µm²; its rounded LEF footprint is 2,793 µm².
For physical footprint calculations use the LEF value. These are **FakeRAM
abstract estimates**, not foundry-characterized SRAM macros. The platform config
itself labels its inputs tentative. Read/write port compatibility and timing
must not be inferred from the name or area. Preserve source headers; the included
ORFS build-script license does not override any upstream platform-specific terms.

A capacity-only illustration using 2,793 / 65,536 = 0.0426178 µm²/bit yields:

| Quantity | Estimate (mm²) |
|---|---:|
| All 8,008,970 bits at this density | 0.341325 |
| FP32 default logic + capacity-only storage | 1.038003 |
| Derived multi-precision logic + capacity-only storage | 1.103955 |

**These totals are scale illustrations, not the final optimization budget.**
Small memories, depth/width padding, banking, multiport implementation and
standard-cell storage can materially change the result. Map the collected leaves
to compatible macros (or flop/mux implementations), then sum logic and storage
in the same units. Count external selection logic once, not both in the existing
logic anchor and an added peripheral allowance. Baseline and candidates must use
one versioned mapping rule. A final total-area constraint can then replace the
independent aggregate bit cap while retaining per-program capacity constraints.
Physical core area additionally needs an explicit utilization/halo/CTS policy;
PHY, pads and external DRAM are outside the present compute-core boundary.

## Frequency evidence

The existing `scalar-alu-sta.log` reports 972.3774 ps data arrival against an ideal
1000 ps virtual clock, with 27.6226 ps slack. This is a scalar combinational ALU
probe, not a full SM or GPU timing result. The cost collection's 1000 ps ABC target
also does not establish 1 GHz operation. No full-chip maximum frequency is
assigned by this collection. Next timing checks should include RF supply,
Tensor stages, cache/tag access and actual macro timing assumptions.

## Reproduction and sources

Run `python docs/evidence/default-physical-baseline-20261007/collect.py` from the
project environment. It verifies an existing JSON result without overwriting it.
`collection.json` contains library/RTL/source hashes and all 202 cell checks;
`memory-inventory.csv` preserves each scoped memory group's count and bits.
`source/` preserves public physical views. `orfs-commit.txt` pins their revision.

- [Pinned ORFS platform](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/tree/9b26ff8ff651fc0b696f7ef20a356865ca6068bb/flow/platforms/asap7)
- [OpenROAD generated-memory documentation](https://openroad-flow-scripts.readthedocs.io/en/latest/user/AutoMemories.html): abstract area/timing limitations; this is separate from claiming the collected pre-existing macros use the latest generator.
- [ASAP7 research paper](https://pages.hmc.edu/harris/research/asap7.pdf): predictive PDK context.
- [Existing cost model](../../cost-model.md) and [task specification](../../project_tasks_cn.md).
