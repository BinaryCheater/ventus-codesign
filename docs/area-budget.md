# Unified experiment area budget

Policy: `ventus-unified-area-policy-v2`, 2026-10-07. The baseline is the pinned
Ventus default **structure**, with fixed modeled BF16/FP16/TF32 capability and
experiment external-memory settings. It is not an implemented official
multi-precision RTL configuration. See the [complete baseline](baseline_cn.md).

The [policy JSON](../examples/unified-area-policy-v2.json) fixes:

- Logic: structural-v2, library area verified as µm² against 202 physical cells.
- Storage: 0.0426177978515625 µm² per physical bit, from the 256×256 FakeRAM LEF.
- Total: `(logic_um2 + density * physical_bits) / 1e6`, in mm².
- Baseline budget: **1.1039550819992285 mm²**. Compare to the computed full value.
- No independent aggregate memory-bit cap. Program capacity constraints remain.
- No assumed validated frequency, power budget or physical-design closure.

This is a logic-plus-capacity-equivalent storage estimate, excluding floorplan
whitespace, CTS, PHY and I/O. It uses a uniform storage density; bank padding,
small-array implementation and port-specific macro timing remain approximate.
The v2 physical-bit counts include its declared replication assumptions.
Precision conversion/control uses the existing 10% Tensor-area allowance per
non-FP32 mode. Those assumptions are fixed across candidates; no extra precision
switch penalty is introduced. This research target does not claim a calibrated
physical correspondence between low-precision timing and synthesized circuitry.

## Query and optimize

```bash
./run costs --model unified-v2
./run costs --model unified-v2 --hardware examples/baseline-hardware-v1.json
```

These commands honor private execution configuration. The original v1 and
structural-v2 CLI modes remain available for historical comparisons.
`evaluate_unified_area` returns the logic area, memory capacity, total area and
budget feasibility. It validates the experiment memory target, then explicitly
projects only the external-memory fields to the legacy v2 wrapper settings for
cost evaluation: external DRAM is outside this area scope. Performance always
uses the original experiment hardware settings (64 B/cycle, 100 cycles).

```python
import highspy
from codesign.ventus_costs.unified import (
    add_unified_area_constraints, decode_unified_solution,
)
model = highspy.Highs()
binding = add_unified_area_constraints(model)
# Bind timing/software variables to binding["fields"], then solve.
# result = decode_unified_solution(binding, model.getSolution().col_value)
```

The area coefficient of each local module option is
`(logic_area + density * memory_bits) / 1e6`. Exactly-one, field consistency and
hardware legality remain; the two legacy budget rows are replaced by one total
area row. Decode recomputes costs and restores the experiment external-memory
settings. This adapter supplies resource costs, not a full-network performance
objective. Direct `add_structural_cost_constraints` retains legacy dual budgets
unless its explicit total-area mode is requested.

Old evidence and numeric semantics are preserved. The physical collection's
1.038/1.104 mm² figures were initially illustrative; this policy adopts that
explicit approximation for comparisons, without adding physical validation.
[Collected sources](evidence/default-physical-baseline-20261007/README.md).

Search revision (2026-10-07): structural cost v2.1 adds 3 SM and VGPR 256, and uses SGPR 128/256/512/1024/2048. Cost formulas and baseline area are unchanged. Unified policy v2 selects this range; `--model unified-v1` and `--model structural-v2` retain legacy ranges. See [expanded-domain evidence](evidence/search-expansion-20261007/README.md).
