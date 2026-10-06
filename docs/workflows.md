# Environment and execution

An AI assistant can prepare these environments. Ask it to read this file and
configure the machine selected by your private `local.toml`, then run the smoke
commands and tests. No owner server information is needed for a collaborator.

## Git checkout

Install Git LFS and run `git lfs pull` after cloning. Only two large synthesized
netlists use LFS; they retain their original filenames and hashes. Timing/cost
queries do not read them, but full raw-table integrity/replay needs their contents.
An AI can install Git LFS together with the Python environment below.

## Existing server workflow

`./run model demo --out results/demo-001` and `./run costs` honor the remote
default in your private profile. On the controlling Mac, Python 3.12+ is enough;
no local model dependencies or GPU tools are needed. Model dependencies are
installed on the selected server. Set `VENTUS_CONTROL_PYTHON` only if your local
Python command differs. AI can configure the server using the requirements below.

## Fast model, cost and MILP

Required: Python 3.12+, NumPy 2.x and HiGHS (`highspy` 1.15+). Tests use pytest;
formatting uses Ruff. macOS arm64 and Linux can run this Python layer. `uv.lock`
pins the shared dependency resolution; no cross-architecture container is needed.

```bash
uv sync --extra dev --python 3.12
mkdir -p results
uv run ventus-project doctor
uv run ventus-project run model demo --out results/demo-001
uv run ventus-project run model verify --out results/demo-001
uv run ventus-project run costs
uv run ventus-project run tests -q
```

With an owner remote profile, these `run` commands execute on the configured
server. Without a profile they run on the local machine. `doctor` only reads
configuration and never connects. Add `run --local` or `run --remote` to override.
On a server without uv, `python3 -m venv .venv` followed by
`.venv/bin/python -m pip install -e ".[dev]"` installs the same declared package;
use uv when exact lockfile resolution is required.

## Configure or deploy a server

Copy `local.example.toml` to ignored `local.toml`; set `execution.mode = "remote"`,
`remote.enabled = true`, and your SSH destination, project directory and Python
command (and optional `remote.uv` path). The run directory must contain this standalone project and its `.venv`.
An optional toolchain environment script can be sourced before commands.

```bash
uv run ventus-project share --out dist/ventus-codesign.tar.gz
uv run ventus-project deploy --package dist/ventus-codesign.tar.gz
```

Deployment creates a **fresh** configured directory and installs a virtual
environment. It uses uv with the lockfile when available; otherwise Python
venv/pip must be installed. On minimal Linux images, using uv avoids missing
`ensurepip` / `python3-venv` problems. It refuses an existing directory. Set a new `remote.run_root` for
another deployment; preserve previous results. AI can also copy the project and
install it manually. No synchronization with the old parent project is required.
Server settings and credentials never enter the package.

## Hardware checks and new costs

These are separate, optional environments. They are unnecessary for routine
search using frozen evidence.

- RTL generation: pinned Ventus Scala/Chisel sources and dependencies, Java/JDK,
  the upstream Mill build tool and its pinned Scala packages.
- Small native RTL probes: Verilator, a C++ compiler and Make. These can run on Mac.
- Full GPU RTL: Verilator and the upstream C++ harness/dependencies, including
  fmt/spdlog and runtime input/driver support. Existing observers and patches are
  archived; AI must adapt configured paths before rerunning them.
- Official C++/SystemC simulator: CMake, C++ toolchain, SystemC and upstream
  dependencies. This is a separate comparator with known failed timing checks.
- Cost collection: Yosys with the appropriate slang frontend, ABC, the pinned
  Liberty target and scripts. OpenSTA is optional for timing experiments; physical
  flow tools/PDK setup are not included.

Start by replaying frozen checks, then use fresh RTL only for selected kernels
and parameter changes. Record all tool versions, source hashes, input hashes,
measurement intervals and failures in a new result directory. Historical scripts
contain symbolic path labels and are reference material; AI should adapt them
through `local.toml` before treating them as runnable hardware workflows.

## Host runtime observations

The same tiny instruction program predicted 23,383 cycles and 13,770 instructions
on both machines. A recorded Mac run took about 0.4 seconds and the configured
server about 5 seconds. A separate single-core integer test was about 5.3× slower
on the server; its P-core stayed near 800 MHz during that test. These observations
concern host throughput, not GPU timing-model accuracy. Power settings were left
unchanged. Interpreter, core placement and solver platform differences can also
affect runtime. Use `./run --local ...` for an explicit local override, while
keeping the private profile's default remote execution.
