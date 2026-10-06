"""Deduplicate text-identical lowered modules before mapping the SM once."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("input", type=Path, help="collected sm-base directory")
parser.add_argument("output", type=Path, help="new output directory; must not exist")
args = parser.parse_args()
root = args.output.resolve()
root.mkdir()
old = args.input.resolve()
for name in ["logic.v", "source.v", "manifest.json"]:
    (root / name).write_bytes((old / name).read_bytes())
(root / "mapping.lib").write_bytes((old.parent / "mapping.lib").read_bytes())
(root / "lower.ys").write_text("""plugin -i slang
read_slang --top SM_wrapper --keep-hierarchy --ignore-assertions --ignore-initial logic.v
hierarchy -check -top SM_wrapper
proc
opt_expr
opt_clean
write_verilog -noattr lowered.v
write_json lowered.json
""")
with (root / "lower.stdout.log").open("w") as log:
    subprocess.run(
        ["yosys", "-Q", "-l", "lower.log", "lower.ys"],
        cwd=root,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
raw = (root / "lowered.v").read_text()
modules = {
    m[1]: m[0]
    for m in re.finditer(
        r"^module\s+(\S+)\s*\(.*?^endmodule", raw, re.MULTILINE | re.DOTALL
    )
}
design = json.loads((root / "lowered.json").read_text())["modules"]
# Verilog escaped identifiers include a leading backslash; JSON names do not.
name_by_json = {name.lstrip("\\"): name for name in modules}
representatives = {}
signatures = {}
visiting = set()


def resolve(name):
    if name in representatives:
        return representatives[name]
    if name in visiting:
        raise ValueError("recursive hardware hierarchy")
    visiting.add(name)
    body = modules[name]
    deps = {
        c["type"]
        for c in design[name.lstrip("\\")]["cells"].values()
        if c["type"] in name_by_json
    }
    for dep in sorted(deps):
        child = name_by_json[dep]
        chosen = resolve(child)
        # Replace only an exact escaped/simple identifier followed by whitespace.
        body = re.sub(
            re.escape(child) + r"(?=\s)",
            lambda _, replacement=chosen: replacement,
            body,
        )
    signature = re.sub(r"^module\s+\S+", "module SAME", body, count=1)
    signature = re.sub(r"//[^\n]*", "", signature)
    signature = " ".join(signature.split())
    # Same original source class AND exactly the same lowered body, with equivalent
    # child definitions substituted. No functional or numeric fitting is used.
    key = (
        name.lstrip("\\").split("$")[0],
        hashlib.sha256(signature.encode()).hexdigest(),
    )
    if key in signatures:
        representatives[name] = signatures[key]
    else:
        signatures[key] = name
        representatives[name] = name
        modules[name] = body
    visiting.remove(name)
    return representatives[name]


for name in list(modules):
    resolve(name)
kept = [name for name in modules if representatives[name] == name]
(root / "deduplicated.v").write_text("\n\n".join(modules[name] for name in kept) + "\n")
(root / "dedup.json").write_text(
    json.dumps(
        {
            "input_modules": len(modules),
            "kept_modules": len(kept),
            "representatives": representatives,
            "source_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        },
        indent=2,
    )
    + "\n"
)
print(
    json.dumps({"input_modules": len(modules), "kept_modules": len(kept)}), flush=True
)
# Empty memory modules are emitted separately with their blackbox declarations.
mem = []
source = (root / "logic.v").read_text()
for m in re.finditer(
    r"^\(\* blackbox \*\) module .*?^endmodule", source, re.MULTILINE | re.DOTALL
):
    mem.append(m[0])
(root / "memories.v").write_text("\n".join(mem) + "\n")
(root / "map.ys").write_text("""read_verilog -sv memories.v deduplicated.v
hierarchy -check -top SM_wrapper
proc
opt_expr
opt_clean
techmap
opt_expr
opt_clean
dfflibmap -liberty mapping.lib
abc -liberty mapping.lib -D 1000
clean
tee -o statistics.json stat -json -liberty mapping.lib
write_verilog -noattr mapped.v
""")
with (root / "stdout.log").open("w") as log:
    subprocess.run(
        ["yosys", "-Q", "-l", "yosys.log", "map.ys"],
        cwd=root,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=True,
    )
print("SM deduplicated mapping complete", flush=True)
