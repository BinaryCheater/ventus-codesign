"""Generate corrected RF subtree and insert it into the unchanged original chip.

The source bank parameter affects operandCollector/regfile, plus disabled GVM
exports. Preserve all other module definitions byte for byte. Check the complete
external collector interface before composition; namespace new dependencies.
"""

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

root = Path("${REMOTE_FLOW_ROOT}/parameter-rtl-v4")
upstream = Path("${REMOTE_PROJECT_ROOT}")
java = next((root / "tools").glob("jdk*/bin/java"))
values = json.loads((upstream / "out/ventus/6.4.0/runClasspath.json").read_text())["value"]
classpath = [value.split(":", 3)[-1] for value in values]
classpath = [value for value in classpath if Path(value).exists()]
compiler = next(Path("${REMOTE_HOME}/.cache/coursier").rglob("scala-compiler-2.13.12.jar"))
plugin = next(Path("${REMOTE_HOME}/.cache/coursier").rglob("chisel-plugin_2.13.12-6.4.0.jar"))
classes = root / "collector-fixed-classes"
classes.mkdir(exist_ok=True)
original = upstream / "ventus/src/pipeline/operandCollector.scala"
source = root / "operandCollector.scala"
s = original.read_text()
for name in ["wbVecBankId", "wbScaBankId"]:
    old = f"val {name} = Wire(UInt(2.W))"
    assert s.count(old) == 1
    s = s.replace(old, f"val {name} = Wire(UInt(log2Ceil(num_bank).W))")
source.write_text(s)
(root / "rf-bank-width.patch").write_text(
    "".join(
        difflib.unified_diff(
            original.read_text().splitlines(keepends=True),
            s.splitlines(keepends=True),
            fromfile="a/ventus/src/pipeline/operandCollector.scala",
            tofile="b/ventus/src/pipeline/operandCollector.scala",
        )
    )
)
with (root / "collector-fixed-compile.log").open("w") as log:
    subprocess.run(
        [
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
            str(source),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
cp = [str(classes), str(root / "parameter-classes"), str(root / "collector-classes"), *classpath]
output = root / "collector-rf8-fixed"
output.mkdir(exist_ok=True)
with (root / "collector-rf8-fixed.log").open("w") as log:
    subprocess.run(
        [str(java), "-Xmx8G", "-cp", ":".join(cp), "top.EmitRF", str(output)],
        cwd=root,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
base = (upstream / "sim-verilator/dut.v").read_text()
new = (output / "operandCollector.v").read_text()
pattern = re.compile(r"^module\s+(\w+)\b.*?^endmodule\b[^\n]*", re.M | re.S)
old_modules = {m[1]: m for m in pattern.finditer(base)}
new_modules = {m[1]: m for m in pattern.finditer(new)}


def interface(module):
    header = module[: module.index(");")]
    header = re.sub(r"//[^\n]*", "", header)
    header = header[header.index("(") + 1 :]
    result, direction, width = {}, None, 1
    for part in header.split(","):
        part = part.strip()
        match = re.match(r"(input|output|inout)\s+(?:\[(\d+):(\d+)\]\s*)?(\w+)$", part)
        if match:
            direction, upper, lower, name = match.groups()
            width = int(upper) - int(lower) + 1 if upper else 1
        else:
            name = part
        if not re.fullmatch(r"\w+", name) or direction is None:
            raise ValueError("unrecognized port declaration")
        result[name] = (direction, width)
    return result


old_ports = interface(old_modules["operandCollector"][0])
new_ports = interface(new_modules["operandCollector"][0])
if any(new_ports.get(name) != value for name, value in old_ports.items()):
    raise ValueError("existing collector external port names/types/widths changed")
extra = {name: value for name, value in new_ports.items() if name not in old_ports}
# Whole-chip elaboration prunes unused scalar mask/ready outputs and debug
# writeback inputs. Standalone elaboration retains them. Confirm the exact same
# extras exist under default bank count; no new functional interface is added.
default_text = (root / "collector-rf4/operandCollector.v").read_text()
default_module = next(m[0] for m in pattern.finditer(default_text) if m[1] == "operandCollector")
if extra != {
    name: value for name, value in interface(default_module).items() if name not in old_ports
}:
    raise ValueError("additional standalone ports depend on RF parameter")
if any(value[0] == "input" and "spike_info" not in name for name, value in extra.items()):
    raise ValueError("unexpected functional input absent from original whole-chip interface")
# Every regenerated dependency receives a private namespace.
names = {
    name: ("operandCollector" if name == "operandCollector" else "rf8_" + name)
    for name in new_modules
}
if any(name in old_modules for name in names.values() if name != "operandCollector"):
    raise ValueError("module namespace collision")
token_pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b")
renamed = {
    name: token_pattern.sub(lambda m: names[m[0]], module[0])
    for name, module in new_modules.items()
}
old_collector = old_modules["operandCollector"]
combined = (
    base[: old_collector.start()] + renamed.pop("operandCollector") + base[old_collector.end() :]
)
# Explicitly terminate ports pruned by original full-chip elaboration.
connections = [
    f".{name}({width}'h0)" if direction == "input" else f".{name}()"
    for name, (direction, width) in extra.items()
]
instance_pattern = re.compile(r"(\boperandCollector\s+\w+\s*\()(.*?)(\);)", re.S)


def extend_instance(match):
    return (
        match[1]
        + re.sub(r"//[^\n]*", "", match[2]).rstrip()
        + ",\n    "
        + ",\n    ".join(connections)
        + "\n  "
        + match[3]
    )


combined, instance_count = instance_pattern.subn(extend_instance, combined)
if instance_count != 2:
    raise ValueError("unexpected collector instance count in pipe module")
combined += "\n" + "\n\n".join(renamed.values()) + "\n"
config = root / "rf-banks8-fixed3"
config.mkdir()
sim = config / "sim-verilator"
shutil.copytree(
    upstream / "sim-verilator",
    sim,
    ignore=shutil.ignore_patterns("build", "logs", "dut.v", "parameters.json", "*.fst", "*.vcd"),
)
(config / "ventus/src").mkdir(parents=True)
(sim / "dut.v").write_text(combined)
with (root / "parameters-fixed.log").open("w") as log:
    subprocess.run(
        [str(java), "-cp", ":".join(cp), "top.paramToJson"],
        cwd=config,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
parameters = json.loads((sim / "parameters.json").read_text())
assert parameters["num_bank"] == 8
manifest = dict(
    changes={"rf_banks": [4, 8], "writeback_bank_index_width": [2, 3]},
    generated_parameters=parameters,
    collector_existing_interface_unchanged=True,
    standalone_pruned_ports=extra,
    composition="Source-generated RF/collector subtree; all other original modules preserved byte-for-byte",
    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    original_source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
    source_patch_sha256=hashlib.sha256((root / "rf-bank-width.patch").read_bytes()).hexdigest(),
    original_dut_sha256=hashlib.sha256((upstream / "sim-verilator/dut.v").read_bytes()).hexdigest(),
    collector_rtl_sha256=hashlib.sha256((output / "operandCollector.v").read_bytes()).hexdigest(),
    composed_dut_sha256=hashlib.sha256((sim / "dut.v").read_bytes()).hexdigest(),
    unchanged_modules=len(old_modules) - 1 - instance_count,
    interface_only_parent_change="pipe: explicit unused output/debug input termination",
    regenerated_modules=len(new_modules),
)
(root / "subtree-build-provenance3.json").write_text(json.dumps(manifest, indent=2) + "\n")
env = os.environ.copy()
env.update(
    PATH="${REMOTE_HOME}/oss-cad-suite/bin:" + env.get("PATH", ""),
    CPLUS_INCLUDE_PATH="${REMOTE_SPDLOG_ROOT}/include",
    LIBRARY_PATH="${REMOTE_SPDLOG_ROOT}/lib",
    LD_LIBRARY_PATH="${REMOTE_SPDLOG_ROOT}/lib",
    RTL_GVM_ENABLED="false",
)
with (root / "subtree-verilator-build3.log").open("w") as log:
    subprocess.run(
        [
            "make",
            "-j12",
            "VLIB_NPROC_CPU=12",
            "VLIB_VERILATOR=verilator --top-module GPGPU_SimTop -Wno-DEPRECATED",
            "VLIB_NPROC_DUT=4",
            "CXXFLAGS=-g -O0 -std=c++20 -MMD -MP -DSPDLOG_FMT_EXTERNAL",
            "VLIB_CXXFLAGS=-g -O0 -fPIC -std=c++20 -DSPDLOG_ACTIVE_LEVEL=SPDLOG_LEVEL_TRACE -DSPDLOG_FMT_EXTERNAL",
        ],
        cwd=sim,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
header = sim / "build/libVentusRTL/debug"
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
for path in [
    sim / "build/driver_example/debug/sim-VentusRTL",
    header / "libVentusRTL.so",
    config / "trace.so",
]:
    manifest.setdefault("binary_sha256", {})[str(path)] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
(root / "complete-subtree-provenance3.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Corrected RF-bank8 full-chip simulation built", flush=True)
