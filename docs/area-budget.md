# Unified experiment area budget

Current policy: `ventus-unified-area-policy-v4`, 2026-10-07.
The [policy](../examples/unified-area-policy-v4.json) fixes a **1.11 mm²** budget.
The default-resource baseline estimate is **1.1039550819992285 mm²**:
0.76263041754 mm² logic plus 0.3413246644592285 mm² storage. See the
[baseline data](evidence/baseline-native-arrays-20261007/README.md).

The hardware resource baseline is the pinned Ventus default. Modeled low-precision
capability, external memory and software mapping remain explicit project settings;
see [baseline](baseline_cn.md). No independent total-memory-bit cap is imposed.

## Native-array model

Logic uses structural-v2.1, calibrated to ASAP7 synthesis. Generated memory leaves
were blackboxed. Existing collector, writeback and external arbitration logic
remains separately costed; its port factors are still approximate.

RF and LDS use `ventus-native-arrays-v1`, a table of CACTI native-multiport array
areas normalized to default per-bank FakeRAM area anchors:

> Array area = bank count × default bank area × CACTI(candidate bank) / CACTI(default bank).

The ratio depends on capacity, width and ports, not only port count. RF has
independent read/write ports; LDS has shared read-or-write ports. Native arrays
replace the former R×W/port-count replicated payload. Do not apply replication
again. Physical capacity includes explicit minimum-bank padding; it does not
multiply by native port count. Remaining metadata/cache storage uses the previous
0.0426177978515625 µm²/bit coefficient.

[128 attempted characterizations](evidence/cacti-full-domain-20261007/README.md)
provide 52 successful 32-nm bank entries plus 22-nm sensitivity evidence. CACTI
cannot represent the smallest banks: VGPR banks below 4 KiB and SGPR banks below
128 B are padded to those sizes for area, while logical capacities remain as
configured. The table covers the full current RF/LDS domain with this assumption.

CACTI arrays include their internal peripheral circuits. The synthesized external
logic above excludes the blackboxed memory interiors; no CACTI peripheral area
is added there a second time. FakeRAM absolute density remains an uncalibrated
ASAP7 reference. There is no claim of foundry macro mapping, routed die area,
clock-tree/PHY/IO area or timing closure.

## Query and MIP

```bash
./run costs --model unified-v4
./run costs --model unified-v4 --hardware examples/baseline-hardware-v1.json
```

`evaluate_unified_area` returns logic and storage areas, physical bits, total area,
budget feasibility, table hash and per-family array diagnostics. The project
execution default is respected. `unified-v1/v2/v3` preserve earlier policies.

```python
from codesign.ventus_costs.unified import (
    add_unified_area_constraints, decode_unified_solution,
)
binding = add_unified_area_constraints(model)
# Add performance/software constraints; solve; then independently check:
result = decode_unified_solution(binding, model.getSolution().col_value)
```

For v4, local MIP coefficients expose `logic_area`, `storage_area_um2` and physical
`memory_bits`; sum `(logic_area + storage_area_um2)/1e6` for the area budget.
One-hot and shared-field consistency constraints remain. Raw structural-v2/v2.1
coefficients still represent the historical replication model; use the unified
adapter for v4. The adapter supplies costs, not a full Transformer timing MIP.

## Timing and retained baseline

Default array anchors, hardware, software and instruction timing are unchanged,
so the baseline area and previously completed 128-scenario cycles are unchanged.
Their hardware/target/source/runtime hashes were checked. 512 values remain
labelled extrapolations; no new full-network run is claimed.

CACTI access and array cycle times are returned as diagnostics only. A common
clock/pipeline constraint across candidates is not yet implemented. The active
performance model still uses its declared port throughput and latency assumptions.
Consequently v4 is a better area estimate, **not** a joint physical timing-closure
model. Preserve all port choices, and report optimized cycles as model predictions.

Old candidates must be recosted under v4; their previous optimality does not carry
over. The exact cost-model minimum for 8 SM is 1.970548 mm², exceeding the budget;
1/2/3/4 SM remain the active menu. Old evidence is preserved.
