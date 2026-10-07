"""Native multiport array estimates, normalized to declared ASAP7/FakeRAM anchors.

The CACTI table models internal array periphery. Synthesized external RF/LDS
logic remains in structural v2.1; its blackboxed memory leaves contain no mapped
array periphery. These estimates do not establish a common clock or timing closure.
"""

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

VERSION = "ventus-native-arrays-v1"
TABLE = Path(__file__).with_name("native_arrays_v1.json")


@lru_cache(maxsize=1)
def _table():
    return json.loads(TABLE.read_text())


def manifest():
    return {"version": VERSION, "table_sha256": hashlib.sha256(TABLE.read_bytes()).hexdigest()}


def bank(family, capacity_bytes, read_ports=0, write_ports=0, rw_ports=0):
    """Select a characterized bank; small banks use explicit physical padding."""
    table = _table()
    minimum = table["minimum_bank_bytes"][family]
    physical = max(capacity_bytes, minimum)
    key = f"{family}:{physical}:{rw_ports}:{read_ports}:{write_ports}"
    if key not in table["banks"]:
        raise ValueError(f"uncharacterized native memory bank: {key}")
    row = dict(table["banks"][key])
    return {
        **row,
        "logical_bytes": capacity_bytes,
        "physical_bytes": physical,
        "padding_bytes": physical - capacity_bytes,
    }


def group_storage(name, hardware, density):
    """Return per-instance array area and physical bits for an RF or LDS group."""
    h = hardware
    if type(density) not in (int, float) or not math.isfinite(density) or density <= 0:
        raise ValueError("storage density must be positive and finite")
    table = _table()
    if name == "rf":
        specifications = [
            ("vgpr", h.vgpr_slots * 128 // h.rf_banks, h.rf_banks),
            ("sgpr", h.sgpr_slots * 4 // h.rf_banks, h.rf_banks),
        ]
    elif name == "lds":
        specifications = [("lds", h.lds_bytes // h.lds_banks, h.lds_banks)]
    else:
        raise ValueError("native storage group must be rf or lds")
    result = {"area_um2": 0.0, "physical_bits": 0, "banks": []}
    for family, size, count in specifications:
        row = bank(
            family,
            size,
            h.rf_read_ports if name == "rf" else 0,
            h.rf_write_ports if name == "rf" else 0,
            h.lds_ports if name == "lds" else 0,
        )
        anchor = table["anchors"][family]
        area = count * anchor["capacity_bytes"] * 8 * density * row["area_mm2"] / anchor["area_mm2"]
        result["area_um2"] += area
        result["physical_bits"] += count * row["physical_bytes"] * 8
        result["banks"].append(
            {
                "family": family,
                "count": count,
                **row,
                "area_um2": area,
                "relative_access_time": row["access_ns"] / anchor["access_ns"],
                "relative_cycle_time": row["cycle_ns"] / anchor["cycle_ns"],
            }
        )
    return result


def storage_estimate(hardware, legacy_cost, density):
    """Replace legacy replicated payloads, retaining separately counted metadata."""
    bits = legacy_cost["memory_bits"]
    area = bits * density
    groups = {}
    for name in ("rf", "lds"):
        old = legacy_cost["components"][name]
        new = group_storage(name, hardware, density)
        old_payload = (
            (hardware.vgpr_slots * 128 + hardware.sgpr_slots * 4)
            * 8
            * hardware.rf_read_ports
            * hardware.rf_write_ports
            if name == "rf"
            else hardware.lds_bytes * 8 * hardware.lds_ports
        )
        instances = old["instances"]
        area += instances * (new["area_um2"] - old_payload * density)
        bits += instances * (new["physical_bits"] - old_payload)
        groups[name] = new
    return {
        "storage_area_um2": area,
        "physical_memory_bits": bits,
        "array_groups_per_sm": groups,
        **manifest(),
        "timing_status": "area-characterized; shared-clock and candidate timing not validated",
    }
