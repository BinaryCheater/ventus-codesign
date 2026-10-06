"""Build an isolated RF-bank variant; original source and RTL artifacts stay intact.

Reuse upstream compiled Scala modules, overriding only the parameter definitions.
All getters retain their names/types; Chisel elaborates a fresh full-chip design.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

root = Path("${REMOTE_FLOW_ROOT}/parameter-rtl-v4")
upstream = Path("${REMOTE_PROJECT_ROOT}")
tools = root / "tools"
with tarfile.open(tools / "jdk.tar.gz") as archive:
    archive.extractall(tools, filter="data")
java = next(tools.glob("jdk*/bin/java"))
metadata = json.loads((upstream / "out/ventus/6.4.0/runClasspath.json").read_text())["value"]
classpath = [value.split(":", 3)[-1] for value in metadata]
classpath = [str(Path(value)) for value in classpath if Path(value).exists()]
compiler = next((Path("${REMOTE_HOME}/.cache/coursier")).rglob("scala-compiler-2.13.12.jar"))
plugin = next(Path("${REMOTE_HOME}/.cache/coursier").rglob("chisel-plugin_2.13.12-6.4.0.jar"))
classes = root / "parameter-classes"
classes.mkdir()
original = upstream / "ventus/src/top/parameters.scala"
modified = root / "parameters.scala"
text = original.read_text()
assert "def num_bank = 4" in text
modified.write_text(text.replace("def num_bank = 4", "def num_bank = 8"))
manifest = dict(
    changes={"rf_banks": [4, 8]},
    original_parameters_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
    modified_parameters_sha256=hashlib.sha256(modified.read_bytes()).hexdigest(),
    java_version=subprocess.check_output(
        [str(java), "-version"], stderr=subprocess.STDOUT
    ).decode(),
)
compile_cmd = [
    str(java),
    "-Xmx4G",
    "-cp",
    ":".join([str(compiler), *classpath]),
    "scala.tools.nsc.Main",
    "-classpath",
    ":".join(classpath),
    "-Xplugin:" + str(plugin),
    "-d",
    str(classes),
    str(modified),
]
manifest["parameter_compile_command"] = compile_cmd
with (root / "parameter-compile.log").open("w") as log:
    subprocess.run(compile_cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
config = root / "rf-banks8"
config.mkdir()
sim = config / "sim-verilator"
shutil.copytree(
    upstream / "sim-verilator",
    sim,
    ignore=shutil.ignore_patterns("build", "logs", "dut.v", "parameters.json", "*.fst", "*.vcd"),
)
(config / "ventus/src").mkdir(parents=True)
# The override directory precedes all original Scala classes.
env = os.environ.copy()
env["CHISEL_FIRTOOL_PATH"] = "${REMOTE_HOME}/.cache/llvm-firtool/1.62.0/bin"
env["RTL_GVM_ENABLED"] = "false"
emit_cmd = [
    str(java),
    "-Xmx32G",
    "-Xss192m",
    "-cp",
    ":".join([str(classes), *classpath]),
    "top.emitVerilog",
]
manifest["elaboration_command"] = emit_cmd
with (root / "elaboration.log").open("w") as log:
    subprocess.run(emit_cmd, cwd=config, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
(sim / "GPGPU_SimTop.v").rename(sim / "dut.v")
parameters = json.loads((sim / "parameters.json").read_text())
manifest["generated_parameters"] = parameters
manifest["dut_sha256"] = hashlib.sha256((sim / "dut.v").read_bytes()).hexdigest()
(root / "build-provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")
env["PATH"] = "${REMOTE_HOME}/oss-cad-suite/bin:" + env.get("PATH", "")
env["CPLUS_INCLUDE_PATH"] = "${REMOTE_SPDLOG_ROOT}/include"
env["LIBRARY_PATH"] = "${REMOTE_SPDLOG_ROOT}/lib"
env["LD_LIBRARY_PATH"] = "${REMOTE_SPDLOG_ROOT}/lib"
with (root / "verilator-build.log").open("w") as log:
    subprocess.run(
        ["make", "-j12", "VLIB_NPROC_CPU=12", "VLIB_NPROC_DUT=4"],
        cwd=sim,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
header = sim / "build/libVentusRTL/debug"
shim_cmd = [
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
]
with (root / "shim-build.log").open("w") as log:
    subprocess.run(shim_cmd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
for path in [
    sim / "build/driver_example/debug/sim-VentusRTL",
    header / "libVentusRTL.so",
    config / "trace.so",
]:
    manifest.setdefault("binary_sha256", {})[str(path)] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
(root / "complete-provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("RF-bank8 full-chip RTL and driver built", flush=True)
