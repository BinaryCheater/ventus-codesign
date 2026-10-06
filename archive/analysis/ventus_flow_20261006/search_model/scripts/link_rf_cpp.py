"""Link compression libraries after generated objects, then build the observer."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

root = Path("${REMOTE_FLOW_ROOT}/parameter-rtl-v4")
config = root / "rf-banks8-fixed3"
sim = config / "sim-verilator"
header = sim / "build/libVentusRTL/debug"
env = os.environ.copy()
env.update(
    CPLUS_INCLUDE_PATH=str(root / "tools/dev/usr/include") + ":${REMOTE_SPDLOG_ROOT}/include",
    LIBRARY_PATH=str(root / "tools/dev/usr/lib/x86_64-linux-gnu") + ":${REMOTE_SPDLOG_ROOT}/lib",
    LD_LIBRARY_PATH="${REMOTE_SPDLOG_ROOT}/lib",
)
with (root / "subtree-final-link2.log").open("w") as log:
    subprocess.run(
        [
            "g++",
            "-shared",
            "-o",
            "libVentusRTL.so",
            "ventus_rtlsim.o",
            "libVdut.a",
            "libverilated.a",
            "-lspdlog",
            "-lfmt",
            "-pthread",
            "-lz",
            "-latomic",
            "-llz4",
            "-lzstd",
        ],
        cwd=header,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
    subprocess.run(
        [
            "g++",
            "-o",
            "sim-VentusRTL",
            "sim_main.o",
            "cmdarg.o",
            "kernel.o",
            "-lspdlog",
            "-lfmt",
            "-L" + str(header),
            "-lVentusRTL",
            "-Wl,-rpath=" + str(header),
        ],
        cwd=sim / "build/driver_example/debug",
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
with (root / "subtree-shim-build3b.log").open("w") as log:
    subprocess.run(
        [
            "g++",
            "-std=c++20",
            "-shared",
            "-fPIC",
            "-O2",
            "-I" + str(header),
            "-I${REMOTE_HOME}/oss-cad-suite/share/verilator/include",
            "${REMOTE_FLOW_ROOT}/parameter-rtl-v4/trace_rf8.cpp",
            "-ldl",
            "-o",
            str(config / "trace.so"),
        ],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
manifest = json.loads((root / "subtree-build-provenance3.json").read_text())
manifest["tool_versions"] = dict(
    verilator=subprocess.check_output(["${REMOTE_HOME}/oss-cad-suite/bin/verilator", "--version"])
    .decode()
    .strip()
)
for path in [
    sim / "build/driver_example/debug/sim-VentusRTL",
    header / "libVentusRTL.so",
    config / "trace.so",
]:
    manifest.setdefault("binary_sha256", {})[str(path)] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
(root / "complete-subtree-provenance3.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("RF8 build and observation shim completed", flush=True)
