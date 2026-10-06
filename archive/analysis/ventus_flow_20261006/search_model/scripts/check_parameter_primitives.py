"""Verify frozen source contracts against parameterized component RTL."""

import argparse
import hashlib
import json
from pathlib import Path

from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--verify", action="store_true")
args = parser.parse_args()
frozen = json.loads((args.root / "pre_run_predictions.json").read_text())
if frozen["code_sha256"] != model_hashes():
    raise ValueError("model changed after prediction freeze")
observed = json.loads((args.root / "results.json").read_text())
if len(observed) != len(frozen["tensor"]) + len(frozen["lds"]):
    raise ValueError("missing configuration")
rows = []
for row in observed:
    top = "vTCexe" if row["kind"] == "tensor" else "SharedMemory"
    rtl = args.root / row["name"] / f"{top}.v"
    if hashlib.sha256(rtl.read_bytes()).hexdigest() != row["rtl_sha256"]:
        raise ValueError("different generated RTL")
    if row["kind"] == "tensor":
        expected = next(x for x in frozen["tensor"] if all(x[k] == row[k] for k in ["m", "n", "k"]))
        latency = (
            Hardware()
            .with_changes(tensor_m=row["m"], tensor_n=row["n"], tensor_k=row["k"])
            .tensor_latency
        )
        if latency != expected["latency"]:
            raise ValueError("changed Tensor prediction")
        steady = next(x for x in row["modes"] if x["mode"] == 0)
        stalled = next(x for x in row["modes"] if x["mode"] == 1)
        if any(
            x["accepted"] != 64 or x["outputs"] != 64 or not x["bit_exact"] for x in row["modes"]
        ):
            raise ValueError("wrong tensor outputs or ordering")
        if (
            steady["min_latency"],
            steady["max_latency"],
            steady["last_output"] - steady["first_output"],
        ) != (latency, latency, 63):
            raise ValueError("Tensor source latency/initiation interval mismatch")
        rows.append(
            dict(
                name=row["name"],
                kind="tensor",
                shape=[row[k] for k in ["m", "n", "k"]],
                predicted_latency=latency,
                rtl_latency=steady["min_latency"],
                initiation_interval=1,
                flops_per_instruction=expected["flops"],
                instructions=128,
                bit_exact=True,
                stalled_latency_range=[stalled["min_latency"], stalled["max_latency"]],
                stalled_input_stalls=stalled["input_stalls"],
            )
        )
    else:
        expected = next(
            x for x in frozen["lds"] if x["banks"] == row["banks"] and x["depth"] == row["depth"]
        )
        cases = []
        if len(row["cases"]) != 10:
            raise ValueError("missing LDS read/write case")
        for case in row["cases"]:
            prediction = next(x for x in expected["cases"] if x["stride"] == case["stride"])
            if not case["bit_exact"] or case["lane_mask"] != 2**32 - 1:
                raise ValueError("LDS lane/data mismatch")
            if (case["responses"], case["first_latency"], case["last_latency"]) != (
                prediction["rounds"],
                3,
                prediction["last_latency"],
            ):
                raise ValueError("LDS bank rounds/response timing mismatch")
            cases.append(
                dict(
                    stride=case["stride"],
                    write=case["write"],
                    predicted_rounds=prediction["rounds"],
                    rtl_rounds=case["responses"],
                    predicted_last_latency=prediction["last_latency"],
                    rtl_last_latency=case["last_latency"],
                    bit_exact=True,
                )
            )
        rows.append(
            dict(
                name=row["name"],
                kind="lds",
                banks=row["banks"],
                capacity_bytes=row["depth"] * 128,
                cases=cases,
                capacity_boundary_tested=False,
            )
        )
source_paths = (
    list(args.root.glob("*.scala"))
    + list(args.root.glob("*harness.cpp"))
    + [
        args.root / "primitive-unbinding.patch",
        args.root / "pre_run_predictions.json",
        args.root / "results.json",
    ]
)
receipt = dict(
    version="ventus-source-events-v4",
    scope="Component RTL contracts, not new full-chip GEMM/FFN or all-parameter accuracy",
    code_sha256=model_hashes(),
    source_sha256={
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_paths)
    },
    results=rows,
    tensor_instructions=768,
    lds_transactions=40,
    verified_timing_error_cycles=0,
    limitations=[
        "Tensor output backpressure tested for data/order; v4 does not implement full elastic pipeline/queue blocking.",
        "LDS tests use one line at set 0; no capacity pressure or coalescer/MSHR integration.",
        "No new port replication, cache pressure, or ready-aware multi-warp/CTA timing validation.",
    ],
)
if args.verify:
    if receipt != json.loads(args.out.read_text()):
        raise ValueError("saved receipt differs")
else:
    with args.out.open("x") as out:
        json.dump(receipt, out, indent=2)
        out.write("\n")
print(
    json.dumps(
        {
            k: receipt[k]
            for k in ["tensor_instructions", "lds_transactions", "verified_timing_error_cycles"]
        }
    )
)
