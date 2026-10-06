# Synthesis cost model

`codesign.ventus_costs.evaluate_cost` queries a frozen 15-point synthesis table.
No synthesis runs inside candidate evaluation. `mip_coefficients` returns area
and memory-bit coefficients; `optimize_with_cost` filters unsupported and
budget-infeasible configurations before the finite-menu event MILP.

Supported dimensions: SM replication (1–8), RF banks (4 or 8), six sampled FP32
Tensor shapes, and four sampled LDS capacity/bank organizations. Other fields
must retain supported defaults. Exact points are listed in `table_v1.json` and
the historical CSV. Unmeasured RF capacities/ports and cache changes are rejected.

Default configuration: logic area **696,678.41448 library area units**, blackboxed
memory **8,008,970 bits**. RF8 costs **733,158.85752** with the same reserved bits.
Area values are ASAP7 7.5T RVT TT mapping results, without a conversion to mm².
The model combines fixed GPU logic with replicated standalone SM estimates and
module deltas. Shared overhead retains the two-SM baseline and cross-component
interactions are approximate.

Memory capacity includes generated storage leaves, tags, queues and instruction
storage. It is a separate bit budget: SRAM macro area/periphery is absent.
`storage_area`, `timing_feasible` and `energy` remain null. An ABC delay target
is not timing closure. Physical implementation after synthesis has not been run.

Examples:

```bash
uv run ventus-project run costs
uv run ventus-project run costs --hardware examples/rf8.json
```

For a local raw-table consistency check, use the command in
[validation](validation.md). Raw RTL, mapped RTL, mapping libraries, synthesis
scripts, reports and hashes are preserved under `archive/analysis/.../cost_model`.
Technology library copyright/license headers are preserved. Check their terms
before redistributing or using the libraries commercially. The upstream RTL's
licenses are kept in the vendor snapshot.
