"""Prepare and execute the four frozen Qwen baseline scenarios."""

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

from codesign.ventus_costs.unified import evaluate_unified_area

from .model_program import qwen_manifest
from .rust import source_hash

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {
    "Q-P128": ("prefill", 128),
    "Q-P512": ("prefill", 512),
    "Q-D128": ("decode", 128),
    "Q-D512": ("decode", 512),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--budget", type=float, default=7200)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--scenarios", nargs="+", choices=list(SCENARIOS), default=["Q-P128", "Q-D128"]
    )
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4 or not 0 < args.budget < float("inf"):
        parser.error("jobs must be 1..4 and per-scenario budget finite and positive")
    baseline = json.loads((ROOT / "examples/project-baseline-v2.json").read_text())
    for name, digest in baseline["sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"frozen input changed: {name}")
    args.out.mkdir(parents=True, exist_ok=False)
    hardware = ROOT / baseline["hardware_file"]
    (args.out / "hardware.json").write_bytes(hardware.read_bytes())
    (args.out / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
    (args.out / "cost.json").write_text(
        json.dumps(evaluate_unified_area(json.loads(hardware.read_text())), indent=2) + "\n"
    )
    plans = []
    for name in dict.fromkeys(args.scenarios):
        phase, context = SCENARIOS[name]
        program = args.out / (name + "-program")
        qwen_manifest(
            ROOT / baseline["software_baseline"]["qwen"]["bundle"],
            program,
            phase=phase,
            context=context,
            steps=16,
            mapping="packed64",
        )
        plans.append((name, program / "program.json"))
    if args.prepare_only:
        return
    start = perf_counter()

    def run_one(item):
        name, program = item
        command = [
            sys.executable,
            "-m",
            "codesign.ventus",
            "instructions",
            "--input",
            str(program),
            "--hardware",
            str(args.out / "hardware.json"),
            "--out",
            str(args.out / name),
            "--budget",
            str(args.budget),
        ]
        with (args.out / (name + ".log")).open("x") as log:
            status = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT
            ).returncode
        result_path = args.out / name / "experiment.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        row = {
            k: result.get(k)
            for k in ["completed", "cycles", "instructions", "host_seconds", "error"]
        }
        row.update(scenario=name, returncode=status)
        print(json.dumps(row), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = [
            future.result() for future in as_completed([pool.submit(run_one, p) for p in plans])
        ]
    estimates_path = ROOT / "examples/baseline-512-estimates-v1.json"
    estimates = json.loads(estimates_path.read_text()) if estimates_path.exists() else None
    summary = {
        "schema": "ventus-baseline-run-v1",
        "scenarios": sorted(results, key=lambda x: x["scenario"]),
        "jobs": args.jobs,
        "reference_512_estimates": estimates
        if not any("512" in name for name in args.scenarios)
        else None,
        "host_seconds": perf_counter() - start,
        "runtime_source_sha256": source_hash(),
        "completed": all(r["completed"] and r["returncode"] == 0 for r in results),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if not summary["completed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
