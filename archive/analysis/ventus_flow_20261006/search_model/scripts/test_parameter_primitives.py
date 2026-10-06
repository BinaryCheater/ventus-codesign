"""Source-generated Tensor/LDS variants; no full-chip accuracy is implied."""

import concurrent.futures
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

root = Path("${REMOTE_FLOW_ROOT}/primitive-parameters-v4")
upstream = Path("${REMOTE_PROJECT_ROOT}")
java = next((root.parent / "parameter-rtl-v4/tools").glob("jdk*/bin/java"))
classpath = [
    p.split(":", 3)[-1]
    for p in json.loads((upstream / "out/ventus/6.4.0/runClasspath.json").read_text())["value"]
]
classpath = [p for p in classpath if Path(p).exists()]
compiler = next(Path("${REMOTE_HOME}/.cache/coursier").rglob("scala-compiler-2.13.12.jar"))
plugin = next(Path("${REMOTE_HOME}/.cache/coursier").rglob("chisel-plugin_2.13.12-6.4.0.jar"))
classes = root / "classes"
classes.mkdir()
patches = []
source_names = ["parameters", "ShareMemParameters", "BankConflictArbiter", "ShareMem"]
for name in source_names:
    before = (root / f"{name}.original.scala").read_text()
    after = before
    if name == "parameters":
        after = re.sub(
            r"def tc_dim: Seq\[Int\] = \{.*?\n  \}",
            'def tc_dim: Seq[Int] = Seq("m", "n", "k").map(x => sys.props("tc." + x).toInt)',
            after,
            flags=re.S,
        )
        after = after.replace(
            "def sharedmem_depth = 1024",
            'def sharedmem_depth = sys.props.getOrElse("lds.depth", "1024").toInt',
        )
    elif name == "ShareMemParameters":
        after = after.replace(
            "def NBanks = NLanes", 'def NBanks = sys.props.getOrElse("lds.banks", "32").toInt'
        )
    elif name == "BankConflictArbiter":
        after = after.replace(
            "class DataCrossbar(implicit p: Parameters)",
            "class DataCrossbar(inputs: Int = 0, outputs: Int = 0)(implicit p: Parameters)",
        )
        a = after.index("class DataCrossbar(")
        b = after.index("class AddrBundle1T", a)
        chunk = (
            after[a:b]
            .replace(
                "val io=IO",
                "val nIn = if(inputs == 0) NBanks else inputs\n  val nOut = if(outputs == 0) NLanes else outputs\n  val io=IO",
            )
            .replace("Vec(NBanks, UInt(WordLength.W))", "Vec(nIn, UInt(WordLength.W))")
            .replace("Vec(NLanes, UInt(WordLength.W))", "Vec(nOut, UInt(WordLength.W))")
            .replace("Vec(NLanes, UInt(NBanks.W))", "Vec(nOut, UInt(nIn.W))")
            .replace("(0 until NLanes)", "(0 until nOut)")
        )
        after = after[:a] + chunk + after[b:]
        after = after.replace(
            "val dataCrsbarSel1H = Output(Vec(NBanks, UInt(NBanks.W)))",
            "val writeSel1H = Output(Vec(NBanks, UInt(NLanes.W)))\n    val readSel1H = Output(Vec(NLanes, UInt(NBanks.W)))",
        )
        after = after.replace(
            "(0 until NBanks).foreach{ i =>\n    ActiveLaneWhenConflict1H(i)",
            "(0 until NLanes).foreach{ i =>\n    ActiveLaneWhenConflict1H(i)",
        )
        after = after.replace(
            "io.dataCrsbarSel1H := Mux(isWrite,perBankActiveLaneWhenConflict1H,bankIdxMasked)",
            "io.writeSel1H := perBankActiveLaneWhenConflict1H\n  io.readSel1H := bankIdxMasked",
        )
    elif name == "ShareMem":
        after = after.replace("Module(new DataCrossbar)", "Module(new DataCrossbar())")
        after = after.replace(
            "val DataCorssBarForWrite = Module(new DataCrossbar())",
            "val DataCorssBarForWrite = Module(new DataCrossbar(NLanes, NBanks))",
        )
        after = after.replace("BankConfArb.io.dataCrsbarSel1H", "BankConfArb.io.writeSel1H", 2)
        # The second selector pipeline must remain the read lane->bank selection.
        after = after.replace(
            "val arbDataCrsbarSel1H_st2 = RegNext(arbDataCrsbarSel1H_st1)",
            "val arbDataCrsbarSel1H_st2 = ShiftRegister(BankConfArb.io.readSel1H, 2)",
        )
    if after == before:
        raise ValueError(f"patch not applied: {name}")
    (root / f"{name}.scala").write_text(after)
    patches.extend(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile=f"a/{name}.scala",
            tofile=f"b/{name}.scala",
        )
    )
(root / "primitive-unbinding.patch").write_text("".join(patches))
(root / "EmitPrimitive.scala").write_text("""package top
object EmitPrimitive extends App {
  implicit val p: config.config.Parameters = (new L1Cache.MyConfig).toInstance
  if(args(0) == "tensor") chisel3.emitVerilog(new pipeline.vTCexe,
    Array("--target-dir", args(1), "--target", "verilog"))
  else chisel3.emitVerilog(new L1Cache.ShareMem.SharedMemory,
    Array("--target-dir", args(1), "--target", "verilog"))
}
""")
with (root / "compile.log").open("w") as log:
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
            *[str(root / f"{name}.scala") for name in source_names],
            str(root / "EmitPrimitive.scala"),
        ],
        check=True,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
configs = [
    dict(kind="tensor", m=m, n=n, k=k)
    for m, n, k in [(4, 8, 4), (4, 4, 4), (2, 16, 2), (8, 4, 4), (2, 4, 2), (4, 2, 4)]
]
configs += [
    dict(kind="lds", banks=b, depth=d) for b, d in [(32, 1024), (16, 1024), (8, 1024), (16, 128)]
]
(root / "configs.json").write_text(json.dumps(configs, indent=2) + "\n")
for config in configs:
    name = (
        "tc-{m}-{n}-{k}".format(**config)
        if config["kind"] == "tensor"
        else "lds-{banks}-{depth}".format(**config)
    )
    config["name"] = name
    dest = root / name
    dest.mkdir()
    settings = dict(
        **{"tc." + x: str(config.get(x, {"m": 4, "n": 8, "k": 4}[x])) for x in ["m", "n", "k"]},
        **{"lds.banks": str(config.get("banks", 32)), "lds.depth": str(config.get("depth", 1024))},
    )
    with (dest / "elaboration.log").open("w") as log:
        subprocess.run(
            [
                str(java),
                "-Xmx4G",
                *[f"-D{k}={v}" for k, v in settings.items()],
                "-cp",
                ":".join([str(classes), *classpath]),
                "top.EmitPrimitive",
                config["kind"],
                str(dest),
            ],
            check=True,
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    top = "vTCexe" if config["kind"] == "tensor" else "SharedMemory"
    (dest / "harness.cpp").write_text(
        (
            root / ("tensor_harness.cpp" if config["kind"] == "tensor" else "lds_harness.cpp")
        ).read_text()
    )
    config["rtl_sha256"] = hashlib.sha256((dest / f"{top}.v").read_bytes()).hexdigest()
    print("generated", name, flush=True)


def build_run(config):
    dest = root / config["name"]
    top = "vTCexe" if config["kind"] == "tensor" else "SharedMemory"
    with (dest / "build.log").open("w") as log:
        subprocess.run(
            [
                "${REMOTE_HOME}/oss-cad-suite/bin/verilator",
                "--cc",
                str(dest / f"{top}.v"),
                "--top-module",
                top,
                "--prefix",
                "Vdut",
                "--exe",
                str(dest / "harness.cpp"),
                "--build",
                "-j",
                "8",
                "-Wno-fatal",
                "--assert",
                "-CFLAGS",
                "-O1",
                "--Mdir",
                str(dest / "obj"),
            ],
            check=True,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    binary = dest / "obj/Vdut"
    arguments = (
        [str(config[x]) for x in ["m", "n", "k"]]
        if config["kind"] == "tensor"
        else [str(config["banks"])]
    )
    completed = subprocess.run(
        [str(binary), *arguments], capture_output=True, text=True, check=True
    )
    (dest / "run.log").write_text(completed.stdout + completed.stderr)
    result = json.loads(completed.stdout)
    result.update(config, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    (dest / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    return result


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(build_run, configs))
(root / "results.json").write_text(json.dumps(results, indent=2) + "\n")
