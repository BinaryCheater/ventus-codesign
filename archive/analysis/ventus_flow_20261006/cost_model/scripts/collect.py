"""Coarse mapped logic with explicit blackboxed memory inventory, on ${REMOTE_HOST}."""

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_case(name, source, top, root):
    out = root / name
    out.mkdir()
    raw = source.read_text()
    memories = {}
    excluded = ["SM_wrapper", "SM_wrapper_1"] if name == "gpu-fixed" else []
    (out / "source.v").write_text(raw)

    def strip(match):
        name = match[1]
        if name in excluded:
            header = match[0][: match[0].index(");") + 2]
            return "(* blackbox *) " + header + "\nendmodule"
        arrays = re.findall(r"reg\s+(?:\[(\d+):0\]\s+)?(\w+)\s*\[0:(\d+)\]", match[0])
        if not arrays:
            return match[0]
        # Generated array modules are leaves; retain every port, reserve all bits.
        header = match[0][: match[0].index(");") + 2]
        memories[name] = {
            "bits": sum((int(w or 0) + 1) * (int(d) + 1) for w, _, d in arrays),
            "arrays": arrays,
            "source_sha256": hashlib.sha256(match[0].encode()).hexdigest(),
        }
        return "(* blackbox *) " + header + "\nendmodule"

    stripped = re.sub(
        r"^module (\w+)\(.*?^endmodule", strip, raw, flags=re.MULTILINE | re.DOTALL
    )
    (out / "logic.v").write_text(stripped)
    manifest = {
        "name": name,
        "top": top,
        "source": str(source),
        "rtl_sha256": sha(source),
        "logic_rtl_sha256": sha(out / "logic.v"),
        "memory_modules": memories,
        "excluded_subsystems": excluded,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if name.startswith("tc-"):
        frontend = f"read_verilog -sv logic.v\nhierarchy -check -top {top}\nsynth -top {top} -noabc"
        flow = "native-synth"
    else:
        frontend = f"plugin -i slang\nread_slang --top {top} --keep-hierarchy --ignore-assertions --ignore-initial logic.v\nhierarchy -check -top {top}\nproc\nopt_expr\nopt_clean\ntechmap\nopt_expr\nopt_clean"
        flow = "coarse-slang"
    manifest["flow"] = flow
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    script = f"""{frontend}
 dfflibmap -liberty {root / "mapping.lib"}
abc -liberty {root / "mapping.lib"} -D 1000
clean
tee -o statistics.json stat -json -liberty {root / "mapping.lib"}
write_verilog -noattr mapped.v
"""
    (out / "synth.ys").write_text(script)
    with (out / "stdout.log").open("w") as log:
        p = subprocess.run(
            ["yosys", "-Q", "-l", "yosys.log", "synth.ys"],
            cwd=out,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return {"name": name, "returncode": p.returncode}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir()  # new results only
    libraries = sorted(
        Path("${REMOTE_LIBERTY_ROOT}").glob("asap7sc7p5t_*RVT_TT*.lib")
    )
    cells = []
    for library in libraries:
        content = library.read_text()
        for m in re.finditer(r"\bcell\s*\([^)]*\)\s*\{", content):
            depth, quoted, escaped, index = 1, False, False, m.end()
            while depth:
                char = content[index]
                if escaped:
                    escaped = False
                elif char == "\\" and quoted:
                    escaped = True
                elif char == '"':
                    quoted = not quoted
                elif not quoted:
                    depth += (char == "{") - (char == "}")
                index += 1
            cells.append(content[m.start() : index])
    header = libraries[0].read_text()
    first = re.search(r"\bcell\s*\([^)]*\)\s*\{", header)
    (root / "mapping.lib").write_text(
        header[: first.start()] + "\n".join(cells) + "\n}\n"
    )
    target = {
        "version": "ventus-synthesis-cost-v1",
        "library": "ASAP7 7.5T RVT TT",
        "pvt": "TT, 0.7V, library nominal temperature",
        "area_unit": "liberty_area_unit",
        "area_conversion": None,
        "abc_delay_target_ps": 1000,
        "timing_feasible": None,
        "flow": "native optimized synthesis for Tensor; coarse slang mapping for other components",
        "storage": "blackboxed generated memory leaves; bits separate",
        "libraries_sha256": {str(p): sha(p) for p in libraries},
        "mapping_lib_sha256": sha(root / "mapping.lib"),
        "script_sha256": sha(Path(__file__)),
        "tools": subprocess.check_output(["yosys", "-V"], text=True).strip(),
    }
    (root / "target.json").write_text(json.dumps(target, indent=2) + "\n")
    base = Path("${REMOTE_FLOW_ROOT}")
    dut = Path("${REMOTE_PROJECT_ROOT}/sim-verilator/dut.v")
    cases = [
        ("gpu-fixed", dut, "GPU"),
        ("sm-base", dut, "SM_wrapper"),
        ("l2-base", dut, "Scheduler"),
        (
            "rf4",
            base / "parameter-rtl-v4/collector-rf4/operandCollector.v",
            "operandCollector",
        ),
        (
            "rf8",
            base / "parameter-rtl-v4/collector-rf8-fixed/operandCollector.v",
            "operandCollector",
        ),
    ]
    for p in sorted((base / "primitive-parameters-v4").glob("tc-*/vTCexe.v")):
        cases.append((p.parent.name, p, "vTCexe"))
    for p in sorted((base / "primitive-parameters-v4").glob("lds-*/SharedMemory.v")):
        cases.append((p.parent.name, p, "SharedMemory"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        futures = [pool.submit(run_case, n, p, t, root) for n, p, t in cases]
        results = []
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result), flush=True)
    (root / "completion.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
