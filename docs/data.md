# Collected data and source snapshots

All collected Ventus experiment files are retained here. The original project is
also left intact. Private machine references were replaced with symbolic labels;
original and exported SHA-256 values are indexed in the
[export manifest](../archive/export-manifest.json). Numeric inputs, measurements,
failed experiments, traces, intermediate RTL and reports remain available.
Only regenerated Python caches and Git metadata are omitted. Profiling files are
retained in valid format with private filenames sanitized.

## Cost measurements and synthesis inputs

The [cost study](../archive/analysis/ventus_flow_20261006/cost_model/report_cn.md)
explains the collection flow. The
[measurement CSV](../archive/analysis/ventus_flow_20261006/cost_model/measurements_v1.csv)
and [live coefficient table](../codesign/ventus_costs/table_v1.json) contain the 15
successful points. [Raw reports](../archive/analysis/ventus_flow_20261006/cost_model/raw/)
retain each point's `source.v`, `logic.v`, `mapped.v`, `manifest.json`,
`statistics.json`, `synth.ys`, stdout/Yosys logs and original manifests. `sm-base`
and `gpu-fixed` also retain intermediate processing needed to explain replication
and subsystem exclusions. [Collection and table-building scripts](../archive/analysis/ventus_flow_20261006/cost_model/scripts/)
are included; new runs must use newly configured paths and output directories.

The complete synthesis target is packaged:

- [Target/PVT, library hashes and tool metadata](../archive/analysis/ventus_flow_20261006/cost_model/raw/target.json).
- [Five ASAP7 7.5T RVT TT source Liberty libraries](../archive/analysis/ventus_flow_20261006/cost_model/raw/libraries/):
  AO, INVBUF, OA, SEQ and SIMPLE, retaining their original bytes and headers.
- [Combined mapping library](../archive/analysis/ventus_flow_20261006/cost_model/raw/mapping.lib)
  and [SM-specific copy](../archive/analysis/ventus_flow_20261006/cost_model/raw/sm-base/mapping.lib).
- [Baseline hardware](../archive/analysis/ventus_flow_20261006/cost_model/baseline_hardware.json),
  [menu validation](../archive/analysis/ventus_flow_20261006/cost_model/menu_validation_v1.json),
  [final validation](../archive/analysis/ventus_flow_20261006/cost_model/validation_final_v1.json),
  and [default integrated estimate](../archive/analysis/ventus_flow_20261006/cost_model/default_cost_v1_final.json).

The `sm-base/mapped.v` and `rf8/mapped.v` files are stored with Git LFS in the
public Git repository, at their original paths and without compression. Run
`git lfs pull` to retrieve them after cloning.

These files reproduce the recorded mapping target; an installed synthesis toolchain
is still required to collect new points. Library units, blackboxed memory and
unverified timing/energy limitations are explained in [cost-model.md](cost-model.md).

## Performance and RTL evidence

| Dataset | Explanation and main links |
|---|---|
| Initial flow / official simulator comparison | [Research report](../archive/analysis/ventus_flow_20261006/report_cn.md), [backend comparison](../archive/analysis/ventus_flow_20261006/evidence/backend-comparison.json), [primitive/native checks and logs](../archive/analysis/ventus_flow_20261006/evidence/), [detailed simulator accuracy study](../archive/analysis/ventus_flow_20261006/model_accuracy/details_cn.md). Includes comparator inputs and failed timing tests. |
| v1–v5 search/model work | [Detailed record](../archive/analysis/ventus_flow_20261006/search_model/details_cn.md), [input example](../archive/analysis/ventus_flow_20261006/search_model/input-example.json), [menu example](../archive/analysis/ventus_flow_20261006/search_model/menu-example.json), [parameter audit](../archive/analysis/ventus_flow_20261006/search_model/parameter-audit-v4.json), [counterexamples](../archive/analysis/ventus_flow_20261006/search_model/parameter-counterexamples-v4.json). The directory includes frozen models, per-probe trace/summary/input files, and result receipts. |
| Shared FP and first Transformer integration, v6 | [Report](../archive/analysis/ventus_flow_20261006/performance-v6/report_cn.md), [mixed-kernel accuracy](../archive/analysis/ventus_flow_20261006/performance-v6/mixed-accuracy-final.json), [Python before/after comparison](../archive/analysis/ventus_flow_20261006/performance-v6/python-ab.json), [profiling data](../archive/analysis/ventus_flow_20261006/performance-v6/profile.stats). Saved inputs, complete small-template results, failed/budget-limited runs and frozen sources remain in the directory. |
| LayerNorm real instructions | [Report](../archive/analysis/ventus_flow_20261006/layernorm_rtl_20261006/report_cn.md), [accuracy receipt](../archive/analysis/ventus_flow_20261006/layernorm_rtl_20261006/accuracy.json), [emitter](../archive/analysis/ventus_flow_20261006/layernorm_rtl_20261006/generate.py), [independent ISA reference](../archive/analysis/ventus_flow_20261006/layernorm_rtl_20261006/isa_reference.py). RTL inputs, traces, output words and failed attempts remain available. |
| Mixed Tensor/memory and integrated frontend, v7 | [Report](../archive/analysis/ventus_flow_20261006/performance-v7/report_cn.md), [accuracy receipt](../archive/analysis/ventus_flow_20261006/performance-v7/accuracy.json), [S16 complete-template receipt](../archive/analysis/ventus_flow_20261006/performance-v7/small-s16-final/experiment.json), [S64 receipt](../archive/analysis/ventus_flow_20261006/performance-v7/small-s64-final/experiment.json), [profiling data](../archive/analysis/ventus_flow_20261006/performance-v7/s16-profile.pstats). Frozen pre/post optimization sources, sensitivity results and all RTL trace folders are preserved. |
| Latest six broader kernels | [Report](../archive/analysis/ventus_flow_20261006/quick_complete_20261006/report_cn.md), [accuracy receipt](../archive/analysis/ventus_flow_20261006/quick_complete_20261006/accuracy.json), [frozen predictions](../archive/analysis/ventus_flow_20261006/quick_complete_20261006/probes/pre_run_predictions.json), [actual RTL traces](../archive/analysis/ventus_flow_20261006/quick_complete_20261006/rtl/). These are the 448-word bit-exact tests; complete-network accuracy is unmeasured. |
| Transformer reliability audit | [Report](../archive/analysis/ventus_flow_20261006/transformer_reliability_20261006/report_cn.md), [audit data](../archive/analysis/ventus_flow_20261006/transformer_reliability_20261006/audit.json). Clarifies graph coverage and software/numerical validation boundaries. |
| Cost/performance integration | [Interoperability probe](../archive/analysis/ventus_flow_20261006/readiness_20261007_gs7n7ouv/integration.json). Checks fixed semantic work across small hardware/software variants, without new RTL or a joint-optimization claim. |

## Extraction lineage

[Initial portable source and receipts](../archive/export-lineage/initial-portable-model/README.md)
retain the first packaging state before the solver/replay portability extensions.
The original parent-project source/evidence remains untouched as well.

## Variables and upstream source

The [source-variable report](../archive/analysis/ventus_variable_audit_20261003/report_cn.md)
is backed by [structured inventory](../archive/analysis/ventus_variable_audit_20261003/inventory.json),
[CSV](../archive/analysis/ventus_variable_audit_20261003/inventory.csv),
[parameter declarations](../archive/analysis/ventus_variable_audit_20261003/top_parameter_declarations.json)
and [source details](../archive/analysis/ventus_variable_audit_20261003/source_details_cn.md).
Its historical description counts should be read using its stated categories;
current executable model fields are listed in [model.md](model.md).

The [RTL snapshot](../vendor/ventus-gpgpu/) includes dependencies. Its
[source manifest](../vendor/ventus-gpgpu/SOURCE.json) pins commit
`681172541a8a34ffb43c483a19c075acbc11a4eb`, dependency revisions and file checksums.
[Parent-project context](../archive/source-project-docs/) preserves the earlier
shared specifications; it is historical context, with unrelated parent capabilities.
The current standalone implementation is documented by this project's English docs.

Read-only reproduction commands are in [validation.md](validation.md). Use the
manifest to check export integrity; never overwrite historical evidence.
