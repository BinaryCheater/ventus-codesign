"""Finish generated C++ with task-local compression development headers."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

root = Path("${REMOTE_FLOW_ROOT}/parameter-rtl-v4")
dev = root / "tools/dev"
dev.mkdir(exist_ok=True)
for package in (root / "tools").glob("*.deb"):
    subprocess.run(["dpkg-deb", "-x", str(package), str(dev)], check=True)
config = root / "rf-banks8-fixed3"
sim = config / "sim-verilator"
header = sim / "build/libVentusRTL/debug"
env = os.environ.copy()
env.update(
    PATH="${REMOTE_HOME}/oss-cad-suite/bin:" + env.get("PATH", ""),
    CPLUS_INCLUDE_PATH=str(dev / "usr/include") + ":${REMOTE_SPDLOG_ROOT}/include",
    LIBRARY_PATH=str(dev / "usr/lib/x86_64-linux-gnu") + ":${REMOTE_SPDLOG_ROOT}/lib",
    LD_LIBRARY_PATH="${REMOTE_SPDLOG_ROOT}/lib",
    RTL_GVM_ENABLED="false",
)
with (root / "subtree-cpp-resume.log").open("w") as log:
    subprocess.run(
        ["make", "-j12", "-f", "Vdut.mk", "libVdut.a", "libverilated.a"],
        cwd=header,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
    subprocess.run(
        [
            "make",
            "-j12",
            "VLIB_NPROC_CPU=12",
            "VLIB_VERILATOR=verilator --top-module GPGPU_SimTop -Wno-DEPRECATED",
            "VLIB_NPROC_DUT=4",
            "CXXFLAGS=-g -O0 -std=c++20 -MMD -MP -DSPDLOG_FMT_EXTERNAL",
            "VLIB_CXXFLAGS=-g -O0 -fPIC -std=c++20 -DSPDLOG_ACTIVE_LEVEL=SPDLOG_LEVEL_TRACE -DSPDLOG_FMT_EXTERNAL",
            "VLIB_LDFLAGS=-lc -llz4 -lzstd",
        ],
        cwd=sim,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
with (root / "subtree-shim-build3.log").open("w") as log:
    subprocess.run(
        [
            "g++",
            "-std=c++20",
            "-shared",
            "-fPIC",
            "-O2",
            "-I" + str(header),
            "-I${REMOTE_HOME}/oss-cad-suite/share/verilator/include",
            "${REMOTE_FLOW_ROOT}/trace_rtl-v4.cpp",
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
print("Corrected RF8 RTL built and observation shim ready", flush=True)
