# Ventus Co-Design

A standalone research case for source-derived GPU timing, synthesis-based cost
budgets, and finite-menu MILP optimization. It includes the current implementation,
its tests, pinned Ventus RTL, and the experiments that support its claims.

## What exists today

| Component | Available capability | Current boundary |
|---|---|---|
| Fast timing model, v7 | Instruction dependencies, operand collection, RF banks/ports, shared FP pipelines, FP32 Tensor, LDS and cache/memory transactions; 29 hardware fields plus 3 external-memory fields | Some arbitration/cache behavior is approximate; a modeled parameter change may require an RTL change |
| Transformer frontend | A complete small GPT-2-shaped FP32 prefill/decode instruction graph, with no numerical tensor computation | LayerNorm uses a validated instruction emitter; softmax/GELU templates need binding to the newer validated probes; full GPT-2 timed execution remains incomplete |
| Cost model, v1 | 15 synthesis points; SM replication, RF 4/8 banks, six Tensor shapes and four LDS organizations | Logic area in library units; blackboxed memory bits separate; no SRAM macro area, energy or timing closure |
| MILP | Select a resource/cost-feasible candidate and schedule its event graph; verify finite-menu results independently | Full Transformer joint structural optimization is still future work |
| Validation | Saved RTL traces, numerical checks and read-only replay; latest six kernel cases have at most 4.079% compute-span error | This is a local kernel result, without a full-network or arbitrary-configuration error guarantee |

The upstream RTL includes an **FP32 Tensor core**. The fast model here is our
source-derived implementation. The official C++/SystemC simulator is a separate
historical comparison; see [validation](docs/validation.md).

## Clone

Install Git LFS before cloning, then use the repository URL shown on GitHub:

```bash
git lfs install
git clone <repository-url>
cd ventus-codesign
git lfs pull
```

Source, docs, tests, RTL and experiment records are normal project files. The two
mapped netlists exceeding GitHub's ordinary file limit use Git LFS at their
original paths; `git lfs pull` retrieves their original bytes. No private machine
profile is part of the repository.

## Run

For the existing server workflow, use `./run model ...` or `./run costs`; the
local controller needs only Python 3.12+ and reads your private profile. It does
not require a local GPU toolchain or NumPy/HiGHS installation.

Python 3.12+, NumPy and HiGHS on the execution machine are sufficient for timing,
cost queries and search.
AI can install the environment from [the short setup guide](docs/workflows.md).

```bash
uv sync --extra dev --python 3.12
uv run ventus-project doctor
uv run ventus-project run model demo --out results/demo-001
uv run ventus-project run model verify --out results/demo-001
uv run ventus-project run costs
```

**Your ignored `local.toml` selects the default execution machine.** A private
remote profile keeps server execution as the default. With no private profile,
commands run locally and never attempt to reach the project owner's server.
`run --local` and `run --remote` are explicit overrides. Collaborators needing
SSH copy `local.example.toml` and enter their own server settings.

To run the Transformer frontend:

```bash
uv run ventus-project run model transformer --input examples/tiny-transformer.json --out results/tiny-001 --budget 60
uv run ventus-project run model verify-transformer --out results/tiny-001
```

Every result directory must be new. Verification replays an existing result
without replacing it. Direct `ventus-model` / `ventus-costs` commands always run
on the machine where they are invoked.

## Files

| Path | Contents |
|---|---|
| `codesign/ventus/` | Live timing model, instruction IR, operators, Transformer frontend and MILP |
| `codesign/ventus_costs/` | Live cost API and frozen synthesis table |
| `ventus_project/` | Private-profile loading, SSH dispatch, deployment and checked sharing |
| `examples/`, `prompts/` | Runnable inputs and English prompts for the next experiments |
| `tests/` | Extracted Ventus regression tests and portability/privacy tests |
| `vendor/ventus-gpgpu/` | RTL working-tree snapshot including dependencies; `SOURCE.json` pins commit and file hashes |
| `archive/` | Privacy-sanitized historical experiments, raw synthesis, traces, frozen code and source-project context |
| `analysis` | Relative compatibility link into `archive/analysis` for historical replay paths |
| `results/` | New local results; ignored by Git |
| `local.toml` | Your machine settings and private values; ignored by Git and excluded from shares |

Start with [current status](docs/status.md). Mechanisms and variables are explained
in [model](docs/model.md), cost coverage in [cost model](docs/cost-model.md), and
reproduction commands in [validation](docs/validation.md). Every collected dataset and packaged synthesis library is linked in
[data and evidence](docs/data.md); historical organization is explained in
[archive](docs/archive.md). Maintained documentation is English;
original Chinese research reports are preserved as historical evidence.

## Share

```bash
uv run ventus-project audit
uv run ventus-project share --out dist/ventus-codesign.tar.gz
```

The share contains code, docs, tests, RTL and evidence. It excludes your private
profile, Git metadata, virtual environments, new results and machine caches.
Historical machine paths are symbolic references such as `${REMOTE_PROJECT_ROOT}`;
original and exported hashes are recorded in `archive/export-manifest.json`.
See [private configuration](docs/local-configuration.md) before configuring a server.
