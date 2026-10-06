"""Read-only reproducible evidence for the ready-driven v5 execution engine."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes, read_candidate
from codesign.ventus.config import Hardware
from codesign.ventus.elastic import ElasticPipeline
from codesign.ventus.graph import execute
from codesign.ventus.operators import fused_operator
from codesign.ventus.program import packed_gemm
from codesign.ventus.timing import build_graph


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def times(workload, hardware):
    graph = build_graph(workload, hardware)
    result = execute(graph)
    return dict(zip(graph.names, result["times"], strict=True)), result


def concurrent(root):
    frozen_path = root / "online-probes-v5/pre_run_predictions.json"
    frozen = json.loads(frozen_path.read_text())
    archive = root / "model-v5-pre-rtl"
    if frozen["code_sha256"] != json.loads((archive / "source_hashes.json").read_text()):
        raise ValueError("pre-RTL model archive mismatch")
    for name, digest in frozen["code_sha256"].items():
        if sha(archive / "codesign/ventus" / name) != digest:
            raise ValueError("pre-RTL source changed")
    changed = {
        name
        for name in frozen["code_sha256"]
        if frozen["code_sha256"][name] != model_hashes()[name]
    }
    # After freezing execution predictions, only MIP numerical conditioning and
    # the extraction helper's explanatory scheduling metadata were repaired.
    if changed - {"mip.py", "source.py"}:
        raise ValueError("timing code differs from the pre-RTL freeze")
    original = json.loads((root / "kernel-provenance-v3.json").read_text())["hashes"]
    modified = json.loads(
        (root / "parameter-rtl-v4/complete-subtree-provenance4.json").read_text()
    )["binary_sha256"]
    receipts = []
    for case in frozen["cases"]:
        for banks in [4, 8]:
            raw = root / f"evidence/online-rf{banks}-v5" / case["name"] / "summary.json"
            observed = json.loads(raw.read_text())
            trace_path = raw.with_name("trace.csv")
            trace = [line.split(",") for line in trace_path.read_text().splitlines()]
            provenance = original if banks == 4 else modified
            base = (
                "${REMOTE_PROJECT_ROOT}"
                if banks == 4
                else "${REMOTE_FLOW_ROOT}/parameter-rtl-v4/rf-banks8-fixed3"
            )
            for field, binary in [
                (
                    "rtl_binary_sha256",
                    base + "/sim-verilator/build/driver_example/debug/sim-VentusRTL",
                ),
                (
                    "rtl_library_sha256",
                    base + "/sim-verilator/build/libVentusRTL/debug/libVentusRTL.so",
                ),
                (
                    "trace_tool_sha256",
                    "${REMOTE_FLOW_ROOT}/trace_rtl-v4.so"
                    if banks == 4
                    else base + "/trace.so",
                ),
            ]:
                if observed[field] != provenance[binary]:
                    raise ValueError("different compiled RTL or observer")
            if (
                observed["returncode"]
                or observed["warnings"]
                or observed["launch_not_before_cycle"] != 512
            ):
                raise ValueError("invalid RTL execution or initial state")
            if observed["output_words"] != case["expected_words"] or not observed["output_matches"]:
                raise ValueError("private per-warp GEMM output differs from dense reference")
            for name, digest in case["input_sha256"].items():
                if sha(root / "online-probes-v5" / case["name"] / name) != digest:
                    raise ValueError("numerical/program input changed")
            collects = [row for row in trace if row[1] == "collect"]
            begin = min(int(row[0]) for row in collects)
            for warp in range(case["warps"]):
                actual_stream = [
                    (int(row[3], 16), int(row[4], 16)) for row in collects if int(row[2]) == warp
                ]
                if actual_stream != [
                    (0x80000000 + i * 4, word) for i, word in enumerate(case["words"])
                ]:
                    raise ValueError("different per-warp instruction stream")
            end = [
                row
                for row in trace
                if row[1] == "writeback" and int(row[3], 16) == case["final_tensor_pc"]
            ]
            if len(end) != case["warps"] or sorted(int(row[2]) for row in end) != list(
                range(case["warps"])
            ):
                raise ValueError("ambiguous Tensor endpoint")
            prediction = case["predictions"][int(banks == 8)]
            candidate = read_candidate(
                dict(workload=case["workload"], hardware=prediction["hardware"])
            )
            clock, result = times(candidate.workload, candidate.hardware)
            per_warp = [
                clock[f"w{warp}.pc{case['final_tensor_pc']:08x}.writeback"]
                for warp in range(case["warps"])
            ]
            if prediction["cycles"] != result["cycles"] or prediction["per_warp"] != per_warp:
                raise ValueError("pre-RTL execution prediction changed")
            actual = max(int(row[0]) for row in end) - begin
            receipts.append(
                dict(
                    name=case["name"],
                    rf_banks=banks,
                    warps=case["warps"],
                    steps=case["steps"],
                    predicted=prediction["cycles"],
                    rtl=actual,
                    error_pct=100 * (prediction["cycles"] / actual - 1),
                    predicted_per_warp=per_warp,
                    rtl_per_warp=[
                        int(next(row for row in end if int(row[2]) == warp)[0]) - begin
                        for warp in range(case["warps"])
                    ],
                    first_collect_per_warp=[
                        min(int(row[0]) for row in collects if int(row[2]) == warp) - begin
                        for warp in range(case["warps"])
                    ],
                    output_bit_exact=True,
                    evidence_sha256=sha(raw),
                    trace_sha256=sha(trace_path),
                )
            )
    increments = []
    for banks in [4, 8]:
        for warps in [2, 4, 8]:
            pair = sorted(
                [row for row in receipts if row["rf_banks"] == banks and row["warps"] == warps],
                key=lambda row: row["steps"],
            )
            increments.append(
                dict(
                    rf_banks=banks,
                    warps=warps,
                    predicted=pair[1]["predicted"] - pair[0]["predicted"],
                    rtl=pair[1]["rtl"] - pair[0]["rtl"],
                )
            )
    return dict(
        pre_run_sha256=sha(frozen_path),
        prediction_code_sha256=frozen["code_sha256"],
        changed_non_timing_files=sorted(changed),
        results=receipts,
        increments=increments,
        max_error_pct=max(abs(row["error_pct"]) for row in receipts),
    )


def elastic(root):
    path = root / "primitive-parameters-v4/results.json"
    rows = []
    for case in json.loads(path.read_text()):
        if case["kind"] != "tensor":
            continue
        for observed in case["modes"]:
            hw = Hardware().with_changes(tensor_m=case["m"], tensor_n=case["n"], tensor_k=case["k"])
            pipe = ElasticPipeline(hw.tensor_latency)
            accepted, returned, stalls = [], [], 0
            for cycle in range(500):
                valid = len(accepted) < 64 and (observed["mode"] == 0 or cycle % 3 != 1)
                fire, token = pipe.advance(
                    len(accepted) if valid else None, observed["mode"] == 0 or cycle % 11 < 6
                )
                stalls += int(valid and not fire)
                if fire:
                    accepted.append(cycle)
                if token is not None:
                    returned.append((cycle, token, cycle - accepted[token]))
                if len(returned) == 64:
                    break
            if [token for _, token, _ in returned] != list(range(64)):
                raise ValueError("elastic pipeline loses/reorders outputs")
            prediction = dict(
                accepted=len(accepted),
                outputs=len(returned),
                first_output=returned[0][0],
                last_output=returned[-1][0],
                min_latency=min(row[2] for row in returned),
                max_latency=max(row[2] for row in returned),
                input_stalls=stalls,
            )
            if any(observed[key] != value for key, value in prediction.items()):
                raise ValueError("elastic control differs from component RTL")
            rows.append(dict(name=case["name"], mode=observed["mode"], **prediction))
    return dict(
        evidence_sha256=sha(path),
        results=rows,
        scope="control timing; numerical payloads checked by the preserved RTL harness",
    )


def regressions(root):
    rows = []
    rf_cases = {
        row["name"]: row
        for row in json.loads((root / "parameter-rf8-v4b/pre_run_predictions.json").read_text())[
            "cases"
        ]
    }
    for saved in [
        "operators-combined-v4.json",
        "accuracy-v3.json",
        "parameter-accuracy-rf8-v4.json",
    ]:
        prior = json.loads((root / saved).read_text())
        for row in prior["results"]:
            config = rf_cases[row["name"]] if saved == "parameter-accuracy-rf8-v4.json" else row
            if "config" in config:
                operator = fused_operator(**config["config"])
                program, endpoint = operator.program, operator.output_compute_pc
            else:
                program = packed_gemm(
                    config["steps"],
                    strategy=config["strategy"],
                    rf_conflict="rf1" in row["name"],
                    lds_stride=int(row["name"].split("lds")[-1]),
                )
                endpoint = program.final_tensor_pc
            hardware = Hardware().with_changes(
                rf_banks=8 if saved == "parameter-accuracy-rf8-v4.json" else 4
            )
            clock, _ = times(program.workload, hardware)
            predicted_compute, predicted_visible = (
                clock[f"pc{endpoint:08x}.writeback"],
                clock["outputs.visible"],
            )
            rows.append(
                dict(
                    source=saved,
                    name=row["name"],
                    predicted_compute=predicted_compute,
                    rtl_compute=row["rtl_compute"],
                    predicted_visible=predicted_visible,
                    rtl_visible=row["rtl_visible"],
                    compute_error_pct=100 * (predicted_compute / row["rtl_compute"] - 1),
                    visible_error_pct=100 * (predicted_visible / row["rtl_visible"] - 1),
                )
            )
    return dict(
        kind="retrospective replay of preserved prior RTL, not new blinded measurements",
        evidence_sha256={name: sha(root / name) for name in {row["source"] for row in rows}},
        results=rows,
    )


def structural(root):
    path = root / "parameter-counterexamples-v4.json"
    old = json.loads(path.read_text())
    rows = []
    for section in ["cache", "cta"]:
        for prior in old[section]["results"]:
            candidate = read_candidate(
                dict(workload=old[section]["workload"], hardware=prior["hardware"])
            )
            clock, result = times(candidate.workload, candidate.hardware)
            names = (
                ["fastB.issue", "fastB.address", "fastA.address", "slowA.address"]
                if section == "cache"
                else ["b1.0.writeback", "b2.0.collect"]
            )
            if (
                section == "cache"
                and not clock["fastB.address"] < clock["fastA.address"] < clock["slowA.address"]
            ):
                raise ValueError("future slow warp still blocks memory admission")
            if (
                section == "cta"
                and prior["hardware"]["sms"] == 2
                and clock["b2.0.collect"] != clock["b1.0.writeback"]
            ):
                raise ValueError("finished block still waits for a cohort")
            rows.append(
                dict(
                    section=section,
                    hardware=prior["hardware"],
                    old_cycles=prior["cycles"],
                    cycles=result["cycles"],
                    events={name: clock[name] for name in names},
                )
            )
    return dict(
        evidence_sha256=sha(path),
        results=rows,
        scope="source-contract regressions; no RTL percentage claimed",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    begin = perf_counter()
    receipt = dict(
        version=MODEL_VERSION,
        code_sha256=model_hashes(),
        concurrent=concurrent(args.root),
        elastic=elastic(args.root),
        regressions=regressions(args.root),
        structural=structural(args.root),
    )
    receipt["evaluation_seconds"] = perf_counter() - begin
    if args.verify:
        prior = json.loads(args.out.read_text())
        if any(prior[key] != receipt[key] for key in receipt.keys() - {"evaluation_seconds"}):
            raise ValueError("saved receipt differs")
    else:
        with args.out.open("x") as out:
            json.dump(receipt, out, indent=2)
            out.write("\n")
    print(
        json.dumps(
            dict(
                version=MODEL_VERSION,
                concurrent_cases=len(receipt["concurrent"]["results"]),
                concurrent_max_error_pct=receipt["concurrent"]["max_error_pct"],
                elastic_cases=len(receipt["elastic"]["results"]),
                regression_cases=len(receipt["regressions"]["results"]),
                evaluation_seconds=receipt["evaluation_seconds"],
            )
        )
    )


if __name__ == "__main__":
    main()
