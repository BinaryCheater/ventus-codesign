"""Reproduce structural limitations without claiming new RTL cycle measurements."""

import argparse
import json
from pathlib import Path

from codesign.ventus.__main__ import model_hashes, read_candidate
from codesign.ventus.graph import execute
from codesign.ventus.timing import build_graph

parser = argparse.ArgumentParser()
parser.add_argument("--input", type=Path, required=True)
args = parser.parse_args()
saved = json.loads(args.input.read_text())
if saved["code_sha256"] != model_hashes():
    raise ValueError("different model version")
for section in ["cache", "cta"]:
    for row in saved[section]["results"]:
        candidate = read_candidate(
            {"hardware": row["hardware"], "workload": saved[section]["workload"]}
        )
        graph = build_graph(candidate.workload, candidate.hardware)
        result = execute(graph)
        times = dict(zip(graph.names, result["times"], strict=True))
        if result["cycles"] != row["cycles"]:
            raise ValueError("counterexample changed")
        if section == "cache":
            if (
                row["events"] != {name: times[name] for name in row["events"]}
                or result["counters"] != row["counters"]
            ):
                raise ValueError("different memory ordering")
        elif (times["b2.0.collect"], times["b1.0.writeback"]) != (
            row["block2_first_collect"],
            row["block1_end"],
        ):
            raise ValueError("different block release ordering")
print("Two structural counterexamples reproduced; no RTL error percentage asserted.")
