"""Freeze implementation identity and observation boundaries for paired tests."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
rtl = Path("${REMOTE_PROJECT_ROOT}")


def git(*args):
    return subprocess.check_output(["git", "-C", str(rtl), *args], text=True).strip()


compiled = "681172541a8a34ffb43c483a19c075acbc11a4eb"
official = "f5853809f114192b99657e7021d1e50dfe961fe1"
changed = git("diff", "--name-only", compiled, official).splitlines()
relevant = git(
    "diff",
    "--name-only",
    compiled,
    official,
    "--",
    "ventus",
    "sim-verilator",
    "dependencies",
    "build.sc",
    "common.sc",
).splitlines()
assert not relevant
files = {
    "generated_rtl": rtl / "sim-verilator/dut.v",
    "rtl_parameters": rtl / "sim-verilator/parameters.json",
    "rtl_simulator": rtl / "sim-verilator/build/driver_example/debug/sim-VentusRTL",
    "systemc_library": root / "cyclesim-build/libVentusCycleSim.so",
    "accuracy_driver": root / "accuracy-driver-v2/main",
    "accuracy_driver_source": root / "accuracy-driver-v2/main.cpp",
}
hashes = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}
assert (
    hashes["systemc_library"] == "2285395f6bddf755e4fd94bb5b0138b3cbe52e84fe8c06c687fd36ed53db92eb"
)
manifest = {
    "official_env_commit": "7e9790708d58ebf697d74fa8dadbaafa1232ca1d",
    "official_rtl_commit": official,
    "compiled_rtl_commit": compiled,
    "systemc_commit": "335ba24d2c7763c87e8c9bfe889c9074763a32f7",
    "all_changed_paths_between_rtl_commits": changed,
    "changed_hardware_build_simulator_paths": relevant,
    "rtl_submodule_commits": git("submodule", "status").splitlines(),
    "sha256": hashes,
    "paths": {k: str(p) for k, p in files.items()},
    "rtl_cycles_per_time_unit": 0.1,
    "systemc_cycles_per_ns": 0.1,
    "ddr_timing_enabled": False,
    "library_timing_code_modified": False,
    "driver_modifications": [
        "disable DDR through official config",
        "read output before virtual memory teardown",
        "print finish time",
    ],
    "boundary_note": "RTL starts at host WG accepted; SystemC starts at SM warp received. Within-family increments cancel fixed dispatch offsets and include instruction fetch and pipeline stalls.",
    "rtl_output_observation": "after the original driver extra 10000 half-cycle steps; drain is excluded from kernel timing",
}
with (root / "evidence/accuracy-provenance.json").open("x") as file:
    file.write(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(hashes, indent=2))
