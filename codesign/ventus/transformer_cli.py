"""Exclusive-write Transformer receipts and read-only timing replay."""

import hashlib
import json
import math
import resource
import sys
from pathlib import Path

from . import MODEL_VERSION
from .config import Hardware
from .transformer import Software, TransformerSpec, census, execute_transformer, lower_transformer


def code_hashes():
    from .rust import source_hash

    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(__file__).parent.glob("*.py"))
    } | {"rust_core": source_hash()}


def run(
    out, *, preset="small", prefill=16, decode_steps=2, mode="summary", budget=60, input_path=None
):
    raw = json.loads(input_path.read_text()) if input_path else {}
    spec_data = {"prefill": prefill, "decode_steps": decode_steps, **raw.get("spec", {})}
    spec = TransformerSpec.gpt2(**spec_data) if preset == "gpt2" else TransformerSpec(**spec_data)
    program = lower_transformer(
        spec, Hardware(**raw.get("hardware", {})), Software(**raw.get("software", {}))
    )
    out.mkdir()
    result = (
        {"completed": False, "cycles": None, "mode": "census", "census": census(program)}
        if mode == "census"
        else execute_transformer(program, mode=mode, time_budget=budget)
    )
    # ru_maxrss is bytes on Darwin, KiB on Linux. This is the process high-water
    # mark, including the frontend; never label it per-batch allocated memory.
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result["process_peak_rss_mib"] = rss / (1024**2 if sys.platform == "darwin" else 1024)
    receipt = {
        "version": MODEL_VERSION,
        "code_sha256": code_hashes(),
        "program": program.describe(),
        "result": result,
        "time_budget_seconds": budget,
        "rtl_full_network_verified": False,
    }
    (out / "experiment.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "out": str(out),
                **{
                    k: result.get(k)
                    for k in (
                        "completed",
                        "cycles",
                        "host_seconds",
                        "process_peak_rss_mib",
                        "instructions",
                    )
                },
            }
        )
    )


def verify(out, *, time_budget=None):
    if time_budget is not None and (
        type(time_budget) not in {int, float} or not math.isfinite(time_budget) or time_budget <= 0
    ):
        raise ValueError("replay time budget must be finite and positive")
    receipt = json.loads((out / "experiment.json").read_text())
    if receipt["version"] != MODEL_VERSION or receipt["code_sha256"] != code_hashes():
        raise ValueError("frozen Transformer model version/hash changed")
    data = receipt["program"]
    program = lower_transformer(
        TransformerSpec(**data["spec"]), Hardware(**data["hardware"]), Software(**data["software"])
    )
    # JSON normalizes tuples to lists.
    if json.loads(json.dumps(program.describe())) != data:
        raise ValueError("regenerated program/address map differs")
    expected = receipt["result"]
    if expected["mode"] == "census":
        if census(program) != expected["census"]:
            raise ValueError("shape census differs")
    elif expected["completed"]:
        result = execute_transformer(
            program,
            mode=expected["mode"],
            time_budget=max(
                receipt["time_budget_seconds"], expected["host_seconds"] * 3, time_budget or 0
            ),
        )
        for key in (
            "completed",
            "cycles",
            "instructions",
            "events",
            "requested_bytes",
            "counters",
            "stages",
            "census",
        ):
            if result[key] != expected[key]:
                raise ValueError(f"read-only replay differs: {key}")
    else:
        raise ValueError("incomplete timed run has no complete-network timing receipt to verify")
    print("Read-only Transformer replay verified; no solver or result writes.")
