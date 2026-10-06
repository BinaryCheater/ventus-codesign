"""Freeze or read-only verify source-model predictions against fresh RTL records."""

import argparse
import hashlib
import json
from itertools import pairwise
from pathlib import Path

from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.ir import Operation, Workload
from codesign.ventus.timing import simulate
from codesign.ventus.workloads import chain


def prediction(family, count):
    if family.startswith("tensor"):
        work = chain("tensor", count, conflicts=family == "tensor-conflict")
    elif family.startswith("lds-"):
        conflict = int(family.removeprefix("lds-").removesuffix("way"))
        work = chain("load", count, lds_conflict=conflict)
    else:
        stride = int(family.removeprefix("global-stride"))
        operations = []
        for i in range(count):
            operations.extend(
                [
                    Operation(
                        f"load{i}",
                        "load",
                        sources=("v10",),
                        destination="v1",
                        addresses=tuple(
                            0x90000000 + i * stride + lane * 4 for lane in range(32)
                        ),
                    ),
                    Operation(
                        f"advance{i}",
                        "vector",
                        sources=("v10", "x6"),
                        destination="v10",
                    ),
                ]
            )
        work = Workload(tuple(operations))
    return simulate(work, Hardware())["cycles"]


def evaluate(root):
    pairs, fingerprints = [], {}
    groups = [
        ("rtl-probes-v3", "probes-v1"),
        ("rtl-memory-v1", "memory-probes-v1"),
        ("rtl-memory-holdout-v1", "memory-holdout-v1"),
    ]
    run_count, unique_inputs = 0, set()
    for evidence, inputs in groups:
        file = root / evidence / "results.json"
        fingerprints[str(file.relative_to(root))] = hashlib.sha256(
            file.read_bytes()
        ).hexdigest()
        families = {}
        for case in json.loads(file.read_text()):
            if (
                case["returncode"] != 0
                or case["warnings"]
                or case["checked_words"] != 32
            ):
                raise ValueError("RTL observation failed")
            for name, expected in case["input_sha256"].items():
                p = root / inputs / case["name"] / name
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
                if digest != expected:
                    raise ValueError("RTL input hash changed")
                fingerprints[str(p.relative_to(root))] = digest
            if (
                case["family"].startswith(("tensor", "lds"))
                and not case["all_output_zero"]
            ):
                raise ValueError("zero probe output changed")
            unique_inputs.add(tuple(sorted(case["input_sha256"].items())))
            run_count += 1
            families.setdefault(case["family"], []).append(case)
        for family, cases in families.items():
            cases.sort(key=lambda c: c["n"])
            for first, last in pairwise(cases):
                actual = (
                    last["dispatch_to_finish_cycles"]
                    - first["dispatch_to_finish_cycles"]
                )
                predicted = prediction(family, last["n"]) - prediction(
                    family, first["n"]
                )
                pairs.append(
                    {
                        "evidence": evidence,
                        "family": family,
                        "counts": [first["n"], last["n"]],
                        "rtl_increment": actual,
                        "predicted_increment": predicted,
                        "relative_error": (predicted - actual) / actual,
                        "prediction_before_rtl": evidence == "rtl-memory-holdout-v1"
                        or family.startswith("tensor"),
                    }
                )
    return {
        "model_sha256": model_hashes(),
        "evidence_sha256": fingerprints,
        "runs": run_count,
        "unique_program_inputs": len(unique_inputs),
        "comparisons": pairs,
        "scope": "Incremental decoded-body timing; all runs use one unchanged default RTL configuration.",
        "numerical_gemm_verified": False,
        "rtl_hardware_search_gain_verified": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.root)
    if args.verify:
        if json.loads(args.out.read_text()) != result:
            raise ValueError("frozen accuracy replay changed")
        print("Accuracy replay verified; no solver or result writes.")
    else:
        with args.out.open("x") as file:
            json.dump(result, file, indent=2)
            file.write("\n")
        print(
            json.dumps(
                {
                    "runs": result["runs"],
                    "unique_inputs": result["unique_program_inputs"],
                    "comparisons": len(result["comparisons"]),
                }
            )
        )


if __name__ == "__main__":
    main()
