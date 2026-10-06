"""Generate the source-defined RF/collector subtree separately."""

import json
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
classes = root / "collector-classes"
classes.mkdir()
source = root / "EmitRF.scala"
source.write_text("""package top
object EmitRF extends App {
  chisel3.emitVerilog(new pipeline.operandCollector,
    Array("--target-dir", args(0), "--target", "verilog"))
}
""")
with (root / "collector-compile.log").open("w") as log:
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
for banks in [4, 8]:
    output = root / f"collector-rf{banks}"
    output.mkdir()
    cp = [str(classes), *([str(root / "parameter-classes")] if banks == 8 else []), *classpath]
    with (root / f"collector-rf{banks}.log").open("w") as log:
        subprocess.run(
            [str(java), "-Xmx8G", "-cp", ":".join(cp), "top.EmitRF", str(output)],
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    print(f"RF collector {banks} generated", flush=True)
