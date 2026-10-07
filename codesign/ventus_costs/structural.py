"""Public structural estimates calibrated to v1, with no synthesis during queries."""

import hashlib
import inspect
import json
import math
from copy import deepcopy
from itertools import product
from pathlib import Path

from codesign.ventus.config import Hardware

from .model import TABLE, load_table

VERSION = "ventus-structural-cost-v2"
RANGES = {
    "sms": [1, 2, 4, 8],
    "warps_per_sm": [4, 8, 16],
    "blocks_per_sm": [2, 4, 8, 16],
    "rf_banks": [4, 8, 16],
    "rf_read_ports": [1, 2],
    "rf_write_ports": [1, 2],
    "writeback_ports": [1, 2],
    "collectors": [4, 8, 16],
    "vgpr_slots": [512, 1024, 2048],
    "sgpr_slots": [1024, 2048, 4096],
    "tensor_m": [2, 4, 8],
    "tensor_n": [2, 4, 8, 16],
    "tensor_k": [2, 4, 8],
    "tensor_units": [1, 2, 4],
    "lds_bytes": [16384, 32768, 65536, 131072],
    "lds_banks": [8, 16, 32],
    "lds_ports": [1, 2],
    "l1_sets": [64, 128, 256, 512],
    "l1_ways": [1, 2, 4],
    "l1_mshrs": [2, 4, 8, 16],
    "l1_subentries": [1, 2, 4, 8],
    "l1_write_entries": [2, 4, 8, 16],
    "l2_sets": [32, 64, 128, 256],
    "l2_ways": [4, 8, 16],
    "l2_mshrs": [8, 16, 32, 64],
    "lsu_entries": [4, 8, 16],
    "lsu_per_warp": [1, 2, 4, 8],
}
EXPANDED_VERSION = "ventus-structural-cost-v2.1"
EXPANDED_RANGES = deepcopy(RANGES)
EXPANDED_RANGES.update(
    sms=[1, 2, 3, 4, 8],
    vgpr_slots=[256, 512, 1024, 2048],
    sgpr_slots=[128, 256, 512, 1024, 2048],
)


def ranges_for_version(version):
    if version == VERSION:
        return deepcopy(RANGES)
    if version == EXPANDED_VERSION:
        return deepcopy(EXPANDED_RANGES)
    raise ValueError("unsupported structural cost version")


GROUPS = {
    "residency": ("warps_per_sm", "blocks_per_sm"),
    "rf": (
        "rf_banks",
        "rf_read_ports",
        "rf_write_ports",
        "writeback_ports",
        "collectors",
        "vgpr_slots",
        "sgpr_slots",
    ),
    "tensor": ("tensor_m", "tensor_n", "tensor_k", "tensor_units"),
    "lds": ("lds_bytes", "lds_banks", "lds_ports"),
    "l1": ("l1_sets", "l1_ways", "l1_mshrs", "l1_subentries", "l1_write_entries"),
    "l2": ("l2_sets", "l2_ways", "l2_mshrs"),
    "lsu": ("warps_per_sm", "lsu_entries", "lsu_per_warp"),
}
ASSUMPTIONS = {
    "memory_ports": "R*W coherent single-read/single-write replicas; broadcast writes, conflict/replay for multiwrite; arbitration charged in logic; concurrency not validated",
    "rf_capacity_logic_fraction": 0.15,
    "lds_capacity_logic_fraction": 0.10,
    "tensor_extra_unit_dispatch_fraction": 0.08,
    "precision_conversion_fraction_per_mode": 0.10,
    "precision_implementation": "shared FP32 datapath envelope plus conversion/control allowance for each non-FP32 mode; no precision-width area discount or throughput claim",
    "l1_logic_fractions": {"fixed": 0.20, "array": 0.40, "miss": 0.25, "write": 0.15},
    "l2_logic_fractions": {"fixed": 0.10, "array": 0.20, "miss": 0.70},
    "lsu_logic_fractions": {"fixed": 0.40, "entries": 0.30, "outstanding": 0.30},
    "residency_logic_fractions": {"warps": 0.80, "blocks": 0.20},
    "shared_logic_fractions": {"fixed": 0.30, "sms": 0.40, "residency": 0.30},
}


def _module(point, prefix):
    matches = [v for k, v in point["modules"].items() if k.split("$")[0] == prefix]
    if len(matches) != 1:
        raise ValueError(f"ambiguous or missing calibration module {prefix}")
    return matches[0]


def calibration():
    """Disjoint subtrees; their remainder preserves the measured full SM anchor."""
    table = load_table()
    points = table["points"]
    sm = points["sm-base"]
    prefixes = {
        "rf": "operandCollector",
        "tensor": "vTCexe",
        "lds": "SharedMemory",
        "l1": "DataCache",
        "lsu": "LSUexe",
    }
    anchors = {k: deepcopy(_module(sm, p)) for k, p in prefixes.items()}
    residence = [
        ("Scoreboard", 8),
        ("InstrBufferV2", 1),
        ("branch_join", 1),
        ("CSRexe", 1),
        ("warp_scheduler", 1),
        ("CTA2warp", 1),
    ]
    anchors["residency"] = {
        key: sum(_module(sm, p)[key] * count for p, count in residence)
        for key in ("logic_area", "memory_bits")
    }
    anchors["rf"]["logic_area"] += _module(sm, "Writeback")["logic_area"]
    anchors["l2"] = deepcopy(_module(points["gpu-fixed"], "Scheduler"))
    anchors["sm_fixed"] = {
        key: sm[key] - sum(anchors[g][key] for g in GROUPS if g != "l2")
        for key in ("logic_area", "memory_bits")
    }
    anchors["shared"] = {
        key: points["gpu-fixed"][key] - anchors["l2"][key] for key in ("logic_area", "memory_bits")
    }
    if any(v[key] < 0 for v in anchors.values() for key in ("logic_area", "memory_bits")):
        raise ValueError("overlapping calibration subtrees")
    # Nonnegative least-squares solution for this frozen six-point dataset.
    import numpy as np

    rows, areas = [], []
    for k, p in points.items():
        if k.startswith("tc-"):
            m, n, q = map(int, k.split("-")[1:])
            rows.append([m * n * q, m * q, 1])
            areas.append(p["logic_area"])
    fit = np.linalg.lstsq(rows, areas, rcond=None)[0]
    if any(fit < 0):
        raise ValueError("tensor fit must have nonnegative structural coefficients")
    return {
        "anchors": anchors,
        "points": points,
        "tensor_fit": fit.tolist(),
        "table_sha256": hashlib.sha256(TABLE.read_bytes()).hexdigest(),
    }


# Cached internally, public functions always return independent output objects.
from functools import lru_cache  # noqa: E402


@lru_cache(maxsize=1)
def _calibration():
    return calibration()


def structural_target(precisions=("fp32",), scales=None, *, version=VERSION):
    """One hardware capability target shared by all workloads and budget comparisons."""
    ranges_for_version(version)
    if isinstance(precisions, str):
        raise ValueError("precisions must be a sequence of mode names")
    modes = sorted(set(precisions))
    if not modes or any(m not in {"fp32", "bf16", "fp16", "tf32"} for m in modes):
        raise ValueError("unsupported precision capability")
    scales = {} if scales is None else dict(scales)
    for key, value in scales.items():
        if (
            key not in set(GROUPS) | {"shared", "sm_fixed"}
            or type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0.5 <= value <= 1.5
        ):
            raise ValueError("cost scales must name a component and lie in [0.5, 1.5]")
    old = load_table()["target"]
    return {
        "version": version,
        "technology": {
            k: old[k]
            for k in (
                "library",
                "pvt",
                "area_unit",
                "area_conversion",
                "abc_delay_target_ps",
                "storage",
                "tools",
                "libraries_sha256",
                "mapping_lib_sha256",
            )
        },
        "calibration_table_sha256": _calibration()["table_sha256"],
        "precisions": modes,
        "component_scales": scales,
        "assumptions": deepcopy(ASSUMPTIONS),
        "fixed": {
            "threads": 32,
            "line_bytes": 128,
            "memory_channels": 1,
            "memory_bytes_per_cycle": 128,
            "memory_latency": 2,
        },
        "frequency_validated": False,
    }


def _target(target):
    target = structural_target() if target is None else deepcopy(target)
    if target != structural_target(
        target.get("precisions", []),
        target.get("component_scales", {}),
        version=target.get("version"),
    ):
        raise ValueError("target must match this version's complete structural target")
    return target


def _interpolate(points, value):
    keys = sorted(points)
    lo, hi = keys[:2] if value <= keys[0] else keys[-2:]
    for a, b in zip(keys, keys[1:]):
        if a <= value <= b:
            lo, hi = a, b
            break
    return points[lo] + (value - lo) * (points[hi] - points[lo]) / (hi - lo)


def _components(h, target):
    """Each component depends only on its declared local factor fields."""
    c = _calibration()
    a, p = c["anchors"], c["points"]
    components = deepcopy(a)
    warp, block = h.warps_per_sm / 8, h.blocks_per_sm / 8
    components["residency"] = {
        "logic_area": a["residency"]["logic_area"] * (0.8 * warp + 0.2 * block),
        "memory_bits": round(a["residency"]["memory_bits"] * warp),
    }
    # Residency-dependent shared tables and SM distribution are costed separately.
    shared_scale = 0.3 + 0.4 * h.sms / 2 + 0.3 * h.sms / 2 * (warp + block) / 2
    components["shared"] = {
        "logic_area": a["shared"]["logic_area"] * shared_scale,
        "memory_bits": round(a["shared"]["memory_bits"] * h.sms / 2 * (warp + block) / 2),
    }
    bank_delta = (p["rf8"]["logic_area"] - p["rf4"]["logic_area"]) * (h.rf_banks - 4) / 4
    capacity = (h.vgpr_slots * 32 * 32 + h.sgpr_slots * 32) / a["rf"]["memory_bits"]
    rf_network = a["rf"]["logic_area"] + bank_delta
    collector_scale = h.collectors / 8
    port_scale = (h.rf_read_ports + h.rf_write_ports + h.writeback_ports) / 3
    components["rf"] = {
        "logic_area": rf_network
        * (0.35 + 0.65 * collector_scale)
        * port_scale
        * (0.85 + 0.15 * capacity),
        "memory_bits": (h.vgpr_slots * 32 * 32 + h.sgpr_slots * 32)
        * h.rf_read_ports
        * h.rf_write_ports,
    }
    shape = f"tc-{h.tensor_m}-{h.tensor_n}-{h.tensor_k}"
    mul, out, intercept = c["tensor_fit"]
    tc_area = (
        p[shape]["logic_area"]
        if shape in p
        else mul * h.tensor_m * h.tensor_n * h.tensor_k + out * h.tensor_m * h.tensor_k + intercept
    )
    context = a["tensor"]["logic_area"] - p["tc-4-8-4"]["logic_area"]
    precision_scale = 1 + 0.10 * sum(m != "fp32" for m in target["precisions"])
    components["tensor"] = {
        "logic_area": (context + tc_area * h.tensor_units * (1 + 0.08 * (h.tensor_units - 1)))
        * precision_scale,
        "memory_bits": 0,
    }
    lds_sample = _interpolate(
        {banks: p[f"lds-{banks}-1024"]["logic_area"] for banks in [8, 16, 32]}, h.lds_banks
    )
    lds_area = a["lds"]["logic_area"] + lds_sample - p["lds-32-1024"]["logic_area"]
    lds_capacity = h.lds_bytes / 131072
    components["lds"] = {
        "logic_area": lds_area * (0.9 + 0.1 * lds_capacity) * h.lds_ports,
        "memory_bits": h.lds_bytes * 8 * h.lds_ports + (a["lds"]["memory_bits"] - 131072 * 8),
    }
    sets, ways = h.l1_sets / 256, h.l1_ways / 2
    miss = h.l1_mshrs / 4 * h.l1_subentries / 2
    write = h.l1_write_entries / 4
    tag_bits = _module(p["sm-base"], "L1TagAccess")["memory_bits"]
    # Tags grow with lines and address width; widths remain positive over ranges.
    tags = round(tag_bits * sets * ways * (32 - int(math.log2(h.l1_sets))) / 24)
    queue = a["l1"]["memory_bits"] - 256 * 2 * 128 * 8 - tag_bits
    components["l1"] = {
        "logic_area": a["l1"]["logic_area"]
        * (0.20 + 0.40 * ways * math.sqrt(sets) + 0.25 * miss + 0.15 * write),
        "memory_bits": h.l1_sets * h.l1_ways * 128 * 8
        + tags
        + round(queue * (0.5 + 0.25 * miss + 0.25 * write)),
    }
    sets, ways, miss = h.l2_sets / 64, h.l2_ways / 16, h.l2_mshrs / 32
    tag_bits = p["gpu-fixed"]["memories"]["array_64x304"]["bits"]
    tags = round(tag_bits * sets * ways * (32 - int(math.log2(h.l2_sets))) / 26)
    queue = a["l2"]["memory_bits"] - 64 * 16 * 128 * 8 - tag_bits
    components["l2"] = {
        "logic_area": a["l2"]["logic_area"] * (0.10 + 0.20 * ways * math.sqrt(sets) + 0.70 * miss),
        "memory_bits": h.l2_sets * h.l2_ways * 128 * 8 + tags + round(queue * miss),
    }
    entry = h.lsu_entries / 8
    outstanding = h.warps_per_sm * h.lsu_per_warp / 32
    components["lsu"] = {
        "logic_area": a["lsu"]["logic_area"] * (0.40 + 0.30 * entry + 0.30 * outstanding),
        "memory_bits": round(a["lsu"]["memory_bits"] * entry * outstanding),
    }
    for name, values in components.items():
        values["logic_area"] *= target["component_scales"].get(name, 1)
        values["instances"] = 1 if name in {"l2", "shared"} else h.sms
    return components


def evaluate_structural_cost(hardware, target=None, activity=None):
    """27-field estimate with explicit assumptions, physical storage and provenance."""
    h = Hardware(**hardware) if isinstance(hardware, dict) else hardware
    if not isinstance(h, Hardware):
        raise TypeError("hardware must be Hardware or a field dictionary")
    h.validate()
    target = _target(target)
    reasons = [
        f"outside v2 range: {k}={getattr(h, k)}"
        for k, values in ranges_for_version(target["version"]).items()
        if getattr(h, k) not in values
    ]
    reasons += [
        f"fixed target field: {k}" for k, v in target["fixed"].items() if getattr(h, k) != v
    ]
    table = load_table()
    if set(h.to_dict()) != set(table["baseline_hardware"]):
        reasons.append("Hardware field contract changed")
    result = {
        "version": target["version"],
        "status": "unsupported" if reasons else "estimated",
        "hardware": h.to_dict(),
        "target": target,
        "logic_area": None,
        "memory_bits": None,
        "area_unit": "liberty_area_unit",
        "storage_area": None,
        "timing_feasible": None,
        "energy": None,
        "energy_status": "unmodeled",
        "unsupported_reasons": reasons,
        "rtl_unbinding_required": h.rtl_bindings(),
        "provenance": {
            "calibration_table_sha256": _calibration()["table_sha256"],
            "model_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "hardware_contract_sha256": hashlib.sha256(
                Path(inspect.getfile(Hardware)).read_bytes()
            ).hexdigest(),
            "target_sha256": hashlib.sha256(
                json.dumps(target, sort_keys=True).encode()
            ).hexdigest(),
        },
        "implementation_status": "Ventus-derived structural assumption; changed ports/queues/precision require RTL work",
        "missing": [
            "SRAM macro area and physical peripheral implementation",
            "placement/routing, clock/pads",
            "timing and energy",
            "low-precision RTL calibration",
            "cross-component integration and expanded queue/residency calibration",
        ],
        "sgpr_addressability": {
            "reserved_slots": h.sgpr_slots,
            "derived_required_address_bits": (h.sgpr_slots // h.rf_banks - 1).bit_length(),
            "scope": "v2 assumes repaired full bank addressing; sampled v1 ports cover only 1024 total slots",
        },
        "memory_replication": {"rf": h.rf_read_ports * h.rf_write_ports, "lds": h.lds_ports},
    }
    if reasons:
        return result
    result["components"] = _components(h, target)
    for key in ("logic_area", "memory_bits"):
        result[key] = sum(v[key] * v["instances"] for v in result["components"].values())
    result["component_basis"] = {
        "rf": "RF4/RF8 measured bank slope; assumed collector/port/capacity factors",
        "tensor": "six measured shapes; nonnegative structural fit otherwise; FP32 envelope for precision",
        "lds": "measured bank interpolation; assumed capacity/port factors",
        "l1": "measured DataCache/tag/queue anchor; assumed association and miss/write scaling",
        "l2": "measured fixed-top L2/array/tag/queue anchor; assumed association and MSHR scaling",
        "residency": "disjoint measured warp/control subtrees; assumed warp/block scaling",
        "lsu": "measured LSU subtree; assumed entry and per-warp outstanding scaling",
        "shared": "fixed-top remainder with assumed dispatch/residency scaling",
        "sm_fixed": "measured residual SM logic and fixed instruction memory",
    }
    return result


def factorized_cost_coefficients(target=None):
    """Local choice coefficients, avoiding enumeration of the full 27-field product.

    Select exactly one row per group. Match shared field values between groups.
    All rows contain sms; enforce one global sms choice. Each row has its final
    chip contribution, so area/bit sums are linear. Residency rows include shared
    cost. A constant holds fixed compute/instruction storage, replicated by sms.
    """
    target = _target(target)
    ranges = ranges_for_version(target["version"])
    groups = {**GROUPS, "sm_fixed": ()}
    output = {}
    for name, fields in groups.items():
        rows = []
        for sms in ranges["sms"]:
            for values in product(*(ranges[k] for k in fields)):
                values = dict(zip(fields, values))
                # Update dependent defaults to keep partial choices legal.
                if name == "residency" and values["blocks_per_sm"] > values["warps_per_sm"]:
                    continue
                if name == "tensor" and any(
                    values[a] * values[b] > 32
                    for a, b in [
                        ("tensor_m", "tensor_n"),
                        ("tensor_n", "tensor_k"),
                        ("tensor_m", "tensor_k"),
                    ]
                ):
                    continue
                if name == "lsu":
                    values["blocks_per_sm"] = min(8, values["warps_per_sm"])
                h = Hardware(sms=sms, **values).validate()
                components = _components(h, target)
                selected = [components[name]]
                if name == "residency":
                    selected.append(components["shared"])
                rows.append(
                    {
                        "choice": {"sms": sms, **{k: getattr(h, k) for k in fields}},
                        **{
                            key: sum(v[key] * v["instances"] for v in selected)
                            for key in ("logic_area", "memory_bits")
                        },
                    }
                )
        output[name] = rows
    return {
        "version": target["version"],
        "target": target,
        "ranges": ranges,
        "groups": output,
        "coupling": "one row/group; shared fields equal the same global one-hot values; all contributions add",
        "objective_scope": "cost constraints only; performance/program constraints must be attached separately",
    }
