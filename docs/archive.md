# Historical evidence

The original parent project remains unchanged. This project's archive is a
privacy-sanitized export of its Ventus work, with relative paths and symbolic
machine references. Numeric measurements, input bytes and model behavior are
preserved. Text hashes changed where machine paths or referenced hashes changed, and for
explicitly documented provenance/solver/replay portability extensions. Timing
executor rules and cost coefficients are unchanged. The initial portable sources
and receipts also remain under `archive/export-lineage/`.
`archive/export-manifest.json` records original/exported hashes and sanitized
profiling records. Exported frozen receipts bind exported code;
use the version's frozen code for older receipts.

| Directory under `archive/analysis/ventus_flow_20261006/` | Evidence |
|---|---|
| `evidence/`, `model_accuracy/` | Upstream simulator/RTL comparisons, patches, primitive RTL and timing failures |
| `search_model/` | Earlier v1–v5 models, event-MIP demos, parameter probes and multiwarp counterexamples |
| `performance-v6/` | Shared FP pipeline, first Transformer frontend and execution summary work |
| `layernorm_rtl_20261006/` | Real LayerNorm emitter, ISA/numerical checks, whole-kernel RTL and failed attempts |
| `performance-v7/` | Mixed Tensor/memory validation, integrated LayerNorm, S16/S64 and sensitivity runs |
| `quick_complete_20261006/` | Latest six broader compute/memory kernel checks |
| `cost_model/` | Raw 15-point synthesis, target libraries, mapped RTL, frozen table and cost-budget demo |
| `readiness_20261007_*/` | Cost/performance interoperability check |
| `scripts/`, `prompts/`, `report_cn.md` | Original flow scripts and historical research prompts/report |

`archive/analysis/ventus_variable_audit_20261003/` contains the wider source-variable
survey. `archive/source-project-docs/` preserves parent-project context; it contains
unrelated parent capabilities and historical instructions. It is not the current
standalone specification. Current English docs and AGENTS.md take precedence.

Do not run old remote scripts without adapting their symbolic path references.
Supported local replay commands are in [validation](validation.md). Fresh results
go under ignored `results/`; never regenerate into historical directories.
