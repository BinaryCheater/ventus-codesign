"""Reproducible source extraction, finite-menu search and read-only verification."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from . import MODEL_VERSION
from .config import Hardware
from .ir import Operation, Workload
from .mip import Candidate, optimize
from .source import extract
from .timing import simulate
from .workloads import gemm


def read_candidate(raw, name="input"):
    hardware = Hardware(**raw.get("hardware", {})).validate()
    data = dict(raw["workload"])
    operations = []
    for item in data.pop("operations"):
        item = dict(item)
        for field in ["sources", "addresses", "dependencies", "active_lanes"]:
            if field in item and item[field] is not None:
                item[field] = tuple(item[field])
        operations.append(Operation(**item))
    workload = Workload(tuple(operations), **data).validate(hardware)
    return Candidate(raw.get("name", name), hardware, workload)


def menu():
    h = Hardware()
    configs = [
        h,
        h.with_changes(rf_banks=8),
        h.with_changes(l1_sets=16, l1_ways=1),
        h.with_changes(tensor_n=4),
        h.with_changes(lds_banks=16),
        h.with_changes(sms=1, tensor_units=2),
    ]
    return [
        Candidate(f"h{i}-w{w}-b{int(t)}", c, gemm(c, m=8, n=8, k=16, warps=w, transpose_b=t))
        for i, c in enumerate(configs)
        for w in [1, 2]
        for t in [False, True]
    ]


def model_hashes():
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }


def run_demo(out):
    out.mkdir()
    cases = menu()
    budgets = Hardware().resources()
    begin = perf_counter()
    rows = []
    for c in cases:
        result = simulate(c.workload, c.hardware)
        rows.append(
            {
                "candidate": c.name,
                "hardware": c.hardware.to_dict(),
                "resources": c.hardware.resources(),
                "rtl_unbinding_required": c.hardware.rtl_bindings(),
                "cycles": result["cycles"],
                "events": result["events"],
                "counters": result["counters"],
                "limitations": result["limitations"],
            }
        )
    evaluation_seconds = perf_counter() - begin
    begin = perf_counter()
    solution = optimize(cases, budgets=budgets)
    mip_seconds = perf_counter() - begin
    feasible = [r for r in rows if all(r["resources"][k] <= v for k, v in budgets.items())]
    best = min(r["cycles"] for r in feasible)
    if not solution["optimal"] or solution["cycles"] != best:
        raise RuntimeError("finite-menu MIP and independent exhaustive execution differ")
    receipt = {
        "version": MODEL_VERSION,
        "code_sha256": model_hashes(),
        "workload": {"m": 8, "n": 8, "k": 16, "dtype": "FP32", "numerical_payload": False},
        "budgets": budgets,
        "results": rows,
        "solution": solution,
        "exhaustive_best_cycles": best,
        "evaluation_seconds": evaluation_seconds,
        "mip_seconds": mip_seconds,
        "rtl_optimization_gain_verified": False,
    }
    with (out / "experiment.json").open("x") as file:
        json.dump(receipt, file, indent=2)
        file.write("\n")
    print(
        json.dumps(
            {
                "out": str(out),
                "candidate": solution["candidate"],
                "cycles": best,
                "candidates": len(rows),
                "evaluation_seconds": evaluation_seconds,
                "mip_seconds": mip_seconds,
            }
        )
    )


def verify(out):
    receipt = json.loads((out / "experiment.json").read_text())
    if receipt["version"] != MODEL_VERSION or receipt["code_sha256"] != model_hashes():
        raise ValueError("frozen model version/hash changed")
    cases = menu()
    for candidate, expected in zip(cases, receipt["results"], strict=True):
        result = simulate(candidate.workload, candidate.hardware)
        if (
            candidate.name != expected["candidate"]
            or candidate.hardware.to_dict() != expected["hardware"]
            or result["cycles"] != expected["cycles"]
            or result["counters"] != expected["counters"]
        ):
            raise ValueError("read-only model replay differs")
    feasible = [
        r
        for r in receipt["results"]
        if all(r["resources"][k] <= v for k, v in receipt["budgets"].items())
    ]
    chosen = next(r for r in feasible if r["candidate"] == receipt["solution"]["candidate"])
    if (
        min(r["cycles"] for r in feasible) != chosen["cycles"]
        or chosen["cycles"] != receipt["solution"]["cycles"]
    ):
        raise ValueError("stored selection is not optimal within the stored menu")
    print("Read-only replay verified; no solver or result writes.")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["demo", "verify"]:
        p = sub.add_parser(command)
        p.add_argument("--out", type=Path, required=True)
    for command in ["simulate", "search"]:
        p = sub.add_parser(command)
        p.add_argument("--input", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("extract")
    p.add_argument("--rtl-root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("transformer")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--preset", choices=["small", "gpt2"], default="small")
    p.add_argument("--prefill", type=int, default=16)
    p.add_argument("--decode-steps", type=int, default=2)
    p.add_argument("--mode", choices=["summary", "detailed", "census"], default="summary")
    p.add_argument("--budget", type=float, default=60)
    p.add_argument("--input", type=Path)
    p = sub.add_parser("verify-transformer")
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "transformer":
        from .transformer_cli import run

        run(
            args.out,
            preset=args.preset,
            prefill=args.prefill,
            decode_steps=args.decode_steps,
            mode=args.mode,
            budget=args.budget,
            input_path=args.input,
        )
    elif args.command == "verify-transformer":
        from .transformer_cli import verify as verify_transformer

        verify_transformer(args.out)
    elif args.command == "demo":
        run_demo(args.out)
    elif args.command == "verify":
        verify(args.out)
    elif args.command in {"simulate", "search"}:
        raw = json.loads(args.input.read_text())
        if args.command == "simulate":
            candidate = read_candidate(raw)
            result = simulate(candidate.workload, candidate.hardware)
        else:
            result = optimize(
                [read_candidate(c) for c in raw["candidates"]],
                budgets=raw.get("budgets"),
                time_limit=raw.get("time_limit", 30),
            )
        result.update(
            {
                "version": MODEL_VERSION,
                "code_sha256": model_hashes(),
                "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
            }
        )
        with args.out.open("x") as file:
            json.dump(result, file, indent=2)
            file.write("\n")
        print(json.dumps({"out": str(args.out), "cycles": result.get("cycles")}))
    else:
        result = extract(args.rtl_root)
        with args.out.open("x") as file:
            json.dump(result, file, indent=2)
            file.write("\n")
        print(f"Extracted source rules to {args.out}")


if __name__ == "__main__":
    main()
