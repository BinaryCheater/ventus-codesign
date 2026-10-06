"""Measured component deltas plus a measured fixed GPU baseline.

Memory bits are a separate budget, never converted to silicon area. Changes to
uncollected dimensions fail closed. SM replication is an explicit estimate.
"""

import hashlib
import inspect
import json
import math
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from codesign.ventus.config import Hardware

TABLE = Path(__file__).with_name("table_v1.json")
VARIABLES = {"sms", "rf_banks", "tensor_m", "tensor_n", "tensor_k", "lds_banks", "lds_bytes"}
EXTERNAL = {"memory_channels", "memory_bytes_per_cycle", "memory_latency"}


@lru_cache(maxsize=4)
def _read_table(path=TABLE):
    return json.loads(Path(path).read_text())


def load_table(path=TABLE):
    """Return an independent copy of the frozen measurement library."""
    return deepcopy(_read_table(path))


def evaluate_cost(hardware, target=None, activity=None):
    """Return static costs in raw Liberty units and bits; unsupported costs are null."""
    if isinstance(hardware, dict):
        hardware = Hardware(**hardware)
    if not isinstance(hardware, Hardware):
        raise TypeError("hardware must be Hardware or a field dictionary")
    hardware.validate()
    table = _read_table()
    declared = table["target"]
    if target is not None and target != declared:
        raise ValueError("target must match the frozen table target")
    base = table["baseline_hardware"]
    values = hardware.to_dict()
    contract_hash = hashlib.sha256(Path(inspect.getfile(Hardware)).read_bytes()).hexdigest()
    reasons = [
        f"uncollected {key}={value} (baseline {base.get(key)})"
        for key, value in values.items()
        if key not in VARIABLES | EXTERNAL and value != base.get(key)
    ]
    if contract_hash != declared["hardware_contract_sha256"]:
        reasons.append("Hardware contract differs from the frozen cost target")
    if set(values) != set(table["baseline_hardware"]):
        reasons.append("Hardware fields differ from the frozen cost target")
    if hardware.sms > 8:
        reasons.append("SM replication estimate restricted to 1..8")
    tc = f"tc-{hardware.tensor_m}-{hardware.tensor_n}-{hardware.tensor_k}"
    rf = f"rf{hardware.rf_banks}"
    lds_depth, rem = divmod(hardware.lds_bytes, hardware.threads * 4)
    lds = f"lds-{hardware.lds_banks}-{lds_depth}"
    points = table["points"]
    for key in (tc, rf, lds):
        if key not in points or (key == lds and rem):
            reasons.append(f"uncollected component {key}")
    address_ports = points.get(rf, {}).get("sgpr_address_ports")
    address_bits = min(address_ports.values()) if address_ports else None
    result = {
        "version": declared["version"],
        "status": "unsupported" if reasons else "estimated",
        "hardware": values,
        "target": deepcopy(declared),
        "hardware_contract_sha256": contract_hash,
        "hardware_sha256": hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest(),
        "table_sha256": hashlib.sha256(TABLE.read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "logic_area": None,
        "area_unit": declared["area_unit"],
        "storage_area": None,
        "memory_bits": None,
        "data_resources": hardware.resources(),
        "lds_organization": {
            "banks": hardware.lds_banks,
            "bank_depth": hardware.lds_bytes // (hardware.lds_banks * 4),
            "parameter_depth": lds_depth,
        },
        "sgpr_addressability": {
            "bank_address_bits": address_bits,
            "ports": address_ports,
            "reserved_slots": hardware.sgpr_slots,
            "addressable_slots": min(hardware.sgpr_slots // hardware.rf_banks, 1 << address_bits)
            * hardware.rf_banks
            if address_bits is not None
            else None,
            "scope": "measured RegFileBank ports; does not validate allocator behavior",
        },
        "timing_feasible": None,
        "energy": None,
        "energy_status": "unmodeled",
        "unsupported_reasons": reasons,
        "rtl_unbinding_required": hardware.rtl_bindings(),
        "implementation": {
            "rf_banks": "source-generated, bank-width patch required for 8",
            "tensor_shape": "source-generated module with parameter unbinding",
            "lds_organization": "source-generated module with bank/lane unbinding",
            "sm_count": "replication estimate; shared allocator/interconnect fixed at 2-SM baseline",
        },
        "missing": [
            "memory macro area, decoder/mux/periphery and timing inside blackboxed leaves",
            "post-placement/routing, clock tree, pads and physical overhead",
            "STA/common frequency validation; ABC delay target is not timing proof",
            "power/activity energy model; external DRAM/controller/PHY cost",
            "SM-dependent shared allocator/interconnect resizing",
        ],
    }
    if reasons:
        return result
    fixed = points["gpu-fixed"]
    sm = points["sm-base"]
    fixed_area = fixed["logic_area"]
    sm_mean = sm["logic_area"]
    rf_delta = points[rf]["logic_area"] - points["rf4"]["logic_area"]
    tc_delta = points[tc]["logic_area"] - points["tc-4-8-4"]["logic_area"]
    lds_delta = points[lds]["logic_area"] - points["lds-32-1024"]["logic_area"]
    per_sm_bits = sm["memory_bits"]
    fixed_bits = fixed["memory_bits"]
    bits_delta = (
        points[rf]["memory_bits"]
        - points["rf4"]["memory_bits"]
        + points[lds]["memory_bits"]
        - points["lds-32-1024"]["memory_bits"]
    )
    if min(fixed_area, fixed_bits, sm_mean + rf_delta + tc_delta + lds_delta) < 0:
        raise ValueError("inconsistent integration anchors")
    result.update(
        logic_area=fixed_area + hardware.sms * (sm_mean + rf_delta + tc_delta + lds_delta),
        memory_bits=fixed_bits + hardware.sms * (per_sm_bits + bits_delta),
        components={
            "shared_fixed_logic": fixed_area,
            "baseline_logic_per_sm": sm_mean,
            "rf_delta_per_sm": rf_delta,
            "tensor_delta_per_sm": tc_delta,
            "lds_delta_per_sm": lds_delta,
            "fixed_memory_bits": fixed_bits,
            "memory_bits_per_sm": per_sm_bits + bits_delta,
        },
        storage_components=deepcopy(
            {
                "fixed": fixed["memories"],
                "rf_per_sm": points[rf]["memories"],
                "lds_per_sm": points[lds]["memories"],
                "other_sm_memory_bits": per_sm_bits
                - points["rf4"]["memory_bits"]
                - points["lds-32-1024"]["memory_bits"],
                "sm_instances": hardware.sms,
            }
        ),
        measurement_keys=["gpu-fixed", "sm-base", rf, tc, lds],
        source="shared fixed top + standalone SM mapped synthesis + measured component deltas",
    )
    return result


def mip_coefficients(hardware_menu):
    """Coefficients for sum(area[h]*y[h]) <= budget and a separate bit budget."""
    costs = [evaluate_cost(h) for h in hardware_menu]
    if any(c["status"] == "unsupported" for c in costs):
        raise ValueError("unsupported hardware in cost menu")
    return {
        "logic_area": [c["logic_area"] for c in costs],
        "memory_bits": [c["memory_bits"] for c in costs],
        "area_unit": costs[0]["area_unit"] if costs else _read_table()["target"]["area_unit"],
    }


def optimize_with_cost(candidates, *, logic_area_budget, memory_bits_budget, time_limit=30):
    """Exact budget filtering for the one-of-N menu, then existing event MILP."""
    from codesign.ventus.mip import optimize

    for value in (logic_area_budget, memory_bits_budget):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("cost budgets must be positive finite numbers")
    if not candidates or len({c.name for c in candidates}) != len(candidates):
        raise ValueError("nonempty candidate menu with unique names required")
    if type(time_limit) not in (int, float) or not math.isfinite(time_limit) or time_limit <= 0:
        raise ValueError("time_limit must be positive and finite")
    costs = [evaluate_cost(c.hardware) for c in candidates]
    if any(c["status"] == "unsupported" for c in costs):
        raise ValueError("unsupported candidate; inspect evaluate_cost before optimizing")
    allowed = [
        candidate
        for candidate, cost in zip(candidates, costs, strict=True)
        if cost["logic_area"] <= logic_area_budget and cost["memory_bits"] <= memory_bits_budget
    ]
    if not allowed:
        return {"status": "cost_budget_infeasible", "candidate": None, "optimal": False}
    result = optimize(allowed, time_limit=time_limit)
    result["cost_budgets"] = {
        "logic_area": logic_area_budget,
        "memory_bits": memory_bits_budget,
    }
    if result["candidate"] is not None:
        result["cost"] = evaluate_cost(Hardware(**result["hardware"]))
    return result
