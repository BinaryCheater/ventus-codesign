"""Read-only RTL evidence replay; predictions never consume observed timings."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.mip import Candidate, optimize
from codesign.ventus.program import packed_gemm
from codesign.ventus.timing import build_graph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    holdout = json.loads((args.root / "kernel-holdout-v3/pre_run_predictions.json").read_text())
    if holdout["version"] != MODEL_VERSION or holdout["code_sha256"] != model_hashes():
        raise ValueError("model differs from frozen pre-RTL predictions")
    rows, total_seconds = [], 0
    for batch in ["kernel-warm-v3", "kernel-holdout-v3"]:
        for path in sorted((args.root / "evidence" / batch).glob("*/summary.json")):
            raw = path.read_bytes()
            case = json.loads(raw)
            source = (
                args.root
                / ("kernel-probes-v3" if batch == "kernel-warm-v3" else batch)
                / case["name"]
            )
            for name, sha in case["input_sha256"].items():
                if hashlib.sha256((source / name).read_bytes()).hexdigest() != sha:
                    raise ValueError("RTL input hash changed")
            if case["returncode"] or case["warnings"] or not case["output_matches"]:
                raise ValueError("RTL completion/numerical check failed")
            trace_path = path.with_name("trace.csv")
            trace = [line.split(",") for line in trace_path.read_text().splitlines()]
            collects = [row for row in trace if row[1] == "collect"]
            program = packed_gemm(
                case["steps"],
                strategy=case["strategy"],
                rf_conflict=case["rf_conflict"],
                lds_stride=case["lds_stride"],
            )
            if case["output_words"] != list(program.expected):
                raise ValueError("dense GEMM reference differs from RTL output")
            if [(int(x[3], 16), int(x[4], 16)) for x in collects] != [
                (0x80000000 + i * 4, word) for i, word in enumerate(program.words)
            ]:
                raise ValueError("RTL trace does not execute emitted instruction stream")
            first = min(int(x[0]) for x in collects)
            last = [
                int(x[0])
                for x in trace
                if x[1] == "writeback" and int(x[3], 16) == program.final_tensor_pc
            ]
            writes = [
                int(x[0]) for x in trace if x[1] == "memory.write" and int(x[3], 16) == 0x90002000
            ]
            if len(last) != 1 or len(writes) != 1:
                raise ValueError("ambiguous RTL completion endpoint")
            begin = perf_counter()
            graph = build_graph(program.workload, Hardware())
            result = execute(graph)
            total_seconds += perf_counter() - begin
            predicted = result["times"][
                graph.names.index(f"pc{program.final_tensor_pc:08x}.writeback")
            ]
            visible = result["times"][graph.names.index("outputs.visible")]
            if batch == "kernel-holdout-v3" and (
                predicted != case["predicted_compute_cycles"]
                or visible != case["predicted_visible_cycles"]
            ):
                raise ValueError("holdout prediction changed after RTL")
            rows.append(
                dict(
                    name=case["name"],
                    batch=batch,
                    steps=case["steps"],
                    strategy=case["strategy"],
                    predicted_compute=predicted,
                    rtl_compute=last[0] - first,
                    compute_error_pct=100 * (predicted / (last[0] - first) - 1),
                    predicted_visible=visible,
                    rtl_visible=writes[0] - first,
                    visible_error_pct=100 * (visible / (writes[0] - first) - 1),
                    rtl_host_dispatch_to_finish=case["dispatch_to_finish_cycles"],
                    output_bit_exact=True,
                    instruction_count=len(program.words),
                    evidence_sha256=hashlib.sha256(raw).hexdigest(),
                    trace_sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest(),
                )
            )
    if len(rows) != 14:
        raise ValueError("incomplete RTL evidence")
    # Same matrix/input family and hardware: select among genuinely executable programs.
    candidates = [
        Candidate(
            name, Hardware(), packed_gemm(16, strategy=strategy, rf_conflict=conflict).workload
        )
        for name, strategy, conflict in [
            ("stream-16-rf0-lds1", "stream", False),
            ("resident-16-rf0-lds1", "resident", False),
            ("resident-16-rf1-lds1", "resident", True),
        ]
    ]
    if args.verify:
        prior = json.loads(args.out.read_text())
        solution = prior["search"]
        scores = {
            c.name: execute(build_graph(c.workload, c.hardware))["cycles"] for c in candidates
        }
        if (
            solution["cycles"] != min(scores.values())
            or scores[solution["candidate"]] != solution["cycles"]
        ):
            raise ValueError("saved search differs from independent enumeration")
    else:
        solution = optimize(candidates, budgets=Hardware().resources())
    relevant = [r for r in rows if r["name"] in {c.name for c in candidates}]
    if solution["candidate"] != min(relevant, key=lambda r: r["rtl_visible"])["name"]:
        raise ValueError("model selection differs from RTL selection")
    receipt = dict(
        version=MODEL_VERSION,
        code_sha256=model_hashes(),
        results=rows,
        search=solution,
        max_compute_error_pct=max(abs(r["compute_error_pct"]) for r in rows),
        max_visible_error_pct=max(abs(r["visible_error_pct"]) for r in rows),
        initial_state=holdout["initial_state"],
        timing_window=holdout["timing_window"],
        verification_excludes_solver=bool(args.verify),
        evaluation_seconds=total_seconds,
    )
    if args.verify:
        for key in [
            "version",
            "code_sha256",
            "results",
            "search",
            "max_compute_error_pct",
            "max_visible_error_pct",
            "initial_state",
            "timing_window",
        ]:
            if receipt[key] != prior[key]:
                raise ValueError(f"frozen evidence differs: {key}")
    else:
        with args.out.open("x") as file:
            json.dump(receipt, file, indent=2)
            file.write("\n")
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in [
                    "version",
                    "max_compute_error_pct",
                    "max_visible_error_pct",
                    "evaluation_seconds",
                ]
            }
        )
    )


if __name__ == "__main__":
    main()
