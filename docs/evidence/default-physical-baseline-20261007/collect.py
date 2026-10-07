"""Reproduce a baseline collection; no simulator or live cost model is changed."""

import csv
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TABLE = ROOT / "codesign/ventus_costs/table_v1.json"
LIBS = ROOT / "archive/analysis/ventus_flow_20261006/cost_model/raw/libraries"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect():
    table = json.loads(TABLE.read_text())
    lef = (HERE / "source/asap7sc7p5t_28_R_1x_220121a.lef").read_text()
    dims = {
        name: float(w) * float(h)
        for name, w, h in re.findall(r"MACRO\s+(\S+).*?SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", lef, re.S)
    }
    cells = []
    for path in sorted(LIBS.glob("*.lib")):
        entries = re.findall(
            r"cell\s*\(\s*([^ )]+)\s*\).*?area\s*:\s*([\d.]+)", path.read_text(), re.S
        )
        for name, area in entries:
            assert name in dims, name
            assert abs(float(area) - dims[name]) < 1e-8, name
            cells.append(
                {
                    "library": path.name,
                    "cell": name,
                    "lib_area": float(area),
                    "lef_area_um2": dims[name],
                }
            )
    macros = []
    for path in sorted((HERE / "source").glob("fakeram*.lef")):
        body = path.read_text()
        width, height = map(float, re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", body).groups())
        props = dict(re.findall(r"PROPERTY\s+(width|depth|banks)\s+(\d+)", body))
        macros.append(
            {
                "name": path.stem,
                "width_um": width,
                "height_um": height,
                "area_um2": width * height,
                "properties": props,
                "kind": "FakeRAM abstract, not silicon-characterized SRAM",
            }
        )
    rows = []
    for point, copies in [("sm-base", 2), ("gpu-fixed", 1)]:
        for name, mem in table["points"][point]["memories"].items():
            count = copies * mem["instances"]
            rows.append(
                {
                    "scope": point,
                    "memory": name,
                    "instances": count,
                    "bits_per_instance": mem["bits"],
                    "total_bits": count * mem["bits"],
                    "source_sha256": mem["source_sha256"],
                }
            )
    bits = sum(row["total_bits"] for row in rows)
    assert bits == 8008970
    macro = next(m for m in macros if m["name"] == "fakeram7_256x256")
    density = macro["area_um2"] / (256 * 256)
    logic = 696678.41448
    # v2 assumption, explicitly distinct from the original default RTL.
    multi_logic = 762630.41754
    report = {
        "version": "default-physical-collection-v1",
        "ventus_commit": json.loads((ROOT / "vendor/ventus-gpgpu/SOURCE.json").read_text())[
            "commit"
        ],
        "orfs_commit": (HERE / "orfs-commit.txt").read_text().strip(),
        "default": table["baseline_hardware"],
        "logic_area_um2": logic,
        "memory_bits": bits,
        "checked_standard_cells": cells,
        "public_macro_points": macros,
        "illustrative_capacity_only_estimate": {
            "macro": macro["name"],
            "area_um2_per_bit": density,
            "storage_area_mm2": bits * density / 1e6,
            "default_fp32_logic_plus_storage_mm2": (logic + bits * density) / 1e6,
            "derived_multi_precision_logic_plus_storage_mm2": (multi_logic + bits * density) / 1e6,
            "status": "illustration only, not bank/port-mapped area or an approved search budget",
            "missing": [
                "per-leaf macro mapping/padding",
                "port compatibility and replication",
                "small memories implemented with flops and muxes",
                "floorplan whitespace, routing, CTS, PHY and IO",
            ],
        },
        "frequency": {
            "full_chip_fmax_hz": None,
            "abc_target_ps": 1000,
            "scalar_alu_only_arrival_ps": 972.3774,
            "note": "existing ideal virtual-clock ALU STA; excludes full-chip and SRAM paths",
        },
        "hashes": {
            str(p.relative_to(ROOT)): sha(p)
            for p in [
                TABLE,
                ROOT / "vendor/ventus-gpgpu/ventus/src/top/parameters.scala",
                *sorted(LIBS.glob("*.lib")),
                *sorted((HERE / "source").iterdir()),
            ]
        },
    }
    out = HERE / "collection.json"
    if out.exists():
        assert json.loads(out.read_text()) == report, (
            "preserve existing evidence; use a new directory"
        )
    else:
        out.write_text(json.dumps(report, indent=2) + "\n")
        with (HERE / "memory-inventory.csv").open("x") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(
        json.dumps(
            {
                "cells": len(cells),
                "memory_groups": len(rows),
                "estimate": report["illustrative_capacity_only_estimate"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    collect()
