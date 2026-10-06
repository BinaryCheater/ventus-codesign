"""Build a relocatable frozen lookup table from raw synthesis reports."""

import argparse
import hashlib
import json
import re
from functools import cache
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_point(path):
    manifest = json.loads((path / "manifest.json").read_text())
    stats = json.loads((path / "statistics.json").read_text())
    if digest(path / "logic.v") != manifest["logic_rtl_sha256"]:
        raise ValueError("modified synthesis input")
    if digest(path / "source.v") != manifest["rtl_sha256"]:
        raise ValueError("modified original RTL")
    if stats["design"]["num_processes"]:
        raise ValueError("unlowered RTLIL processes would undercount area")
    modules = {n.lstrip("\\"): v for n, v in stats["modules"].items()}
    memory = manifest["memory_modules"]
    for name, module in modules.items():
        if "area" not in module and (
            module["num_cells"]
            or any(
                modules.get(child, {}).get("area", 0) > 0
                for child in module["num_cells_by_type"]
            )
        ):
            raise ValueError(f"missing area for nonempty logic {name}")

    @cache
    def inventory(name):
        if name.split("$")[0] in memory:
            return {name.split("$")[0]: 1}
        result = {}
        for child, count in modules[name]["num_cells_by_type"].items():
            if child not in modules and child.split("$")[0] not in memory:
                if child.split("$")[0] in manifest.get("excluded_subsystems", []):
                    continue
                if not child.endswith("_ASAP7_75t_R"):
                    raise ValueError(f"unmapped cell: {child}")
                continue
            for leaf, number in inventory(child).items():
                result[leaf] = result.get(leaf, 0) + number * count
        return result

    counts = inventory(manifest["top"])
    address_ports = None
    if manifest["name"] in {"rf4", "rf8"}:
        header = (
            (path / "source.v")
            .read_text()
            .split("module RegFileBank(", 1)[1]
            .split(");", 1)[0]
        )
        address_ports = {
            mode: int(re.search(r"input\s+\[(\d+):0\]\s+io_" + port, header)[1]) + 1
            for mode, port in [("read_bits", "rsidx"), ("write_bits", "rdidx")]
        }
    return {
        "flow": manifest.get("flow"),
        "sgpr_address_ports": address_ports,
        "excluded_subsystems": manifest.get("excluded_subsystems", []),
        "logic_area": stats["design"]["area"],
        "sequential_area": stats["design"]["sequential_area"],
        "memory_bits": sum(memory[n]["bits"] * c for n, c in counts.items()),
        "memories": {n: {"instances": c, **memory[n]} for n, c in counts.items()},
        "rtl_sha256": manifest["rtl_sha256"],
        "statistics_sha256": digest(path / "statistics.json"),
        "synthesis_script_sha256": digest(path / "synth.ys"),
        "manifest_sha256": digest(path / "manifest.json"),
        "mapped_sha256": digest(path / "mapped.v"),
        "modules": {
            n: {
                "logic_area": v.get("area", 0),
                "sequential_area": v.get("sequential_area", 0),
                "memory_bits": sum(
                    memory[k]["bits"] * c for k, c in inventory(n).items()
                ),
            }
            for n, v in modules.items()
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.out.exists() and not args.verify:
        raise FileExistsError(args.out)
    target = json.loads((args.raw / "target.json").read_text())
    completion = json.loads((args.raw / "completion.json").read_text())
    if any(p["returncode"] for p in completion):
        raise ValueError("incomplete synthesis batch")
    table = {
        "target": target,
        "baseline_hardware": json.loads(
            (args.raw / "baseline_hardware.json").read_text()
        ),
        "points": {p["name"]: read_point(args.raw / p["name"]) for p in completion},
        "builder_sha256": digest(Path(__file__)),
    }
    if args.verify:
        saved = json.loads(args.out.read_text())
        # Verify measurements even if this convenience builder is later formatted.
        saved.pop("builder_sha256", None)
        table.pop("builder_sha256", None)
        if saved != table:
            raise ValueError("frozen cost table differs from raw reports")
        print("Frozen synthesis table verified")
    else:
        args.out.write_text(json.dumps(table, indent=2) + "\n")


if __name__ == "__main__":
    main()
