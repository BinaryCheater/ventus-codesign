"""Finite FFN software-menu MIP; saved result can be replayed without solving."""

import argparse
import json
from itertools import groupby
from pathlib import Path
from time import perf_counter

from codesign.ventus import MODEL_VERSION
from codesign.ventus.__main__ import model_hashes
from codesign.ventus.config import Hardware
from codesign.ventus.graph import execute
from codesign.ventus.mip import Candidate, optimize
from codesign.ventus.operators import fused_operator
from codesign.ventus.timing import build_graph

parser = argparse.ArgumentParser()
parser.add_argument("--accuracy", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--verify", action="store_true")
args = parser.parse_args()
accuracy = json.loads(args.accuracy.read_text())
if accuracy["version"] != MODEL_VERSION or accuracy["code_sha256"] != model_hashes():
    raise ValueError("accuracy belongs to a different model")
prior = json.loads(args.out.read_text()) if args.verify else None


def key(row):
    c = row["config"]
    return c["depth"], c["hidden"], bool(c.get("residual")), c["seed"]


rows, seconds = [], 0
for group, cases in groupby(
    sorted([r for r in accuracy["results"] if r["config"]["kind"] == "ffn"], key=key), key=key
):
    cases = list(cases)
    menu = [
        Candidate(r["name"], Hardware(), fused_operator(**r["config"]).program.workload)
        for r in cases
    ]
    if len(menu) != 2:
        raise ValueError("missing LDS/global pair")
    scores = {c.name: execute(build_graph(c.workload, c.hardware))["cycles"] for c in menu}
    begin = perf_counter()
    if args.verify:
        solution = next(
            r["solution"] for r in prior["results"] if tuple(r["shape_residual_seed"]) == group
        )
    else:
        solution = optimize(menu, budgets=Hardware().resources())
    seconds += perf_counter() - begin
    if (
        solution["cycles"] != min(scores.values())
        or scores[solution["candidate"]] != solution["cycles"]
    ):
        raise ValueError("MIP differs from enumeration")
    rtl_best = min(cases, key=lambda r: r["rtl_visible"])
    if solution["candidate"] != rtl_best["name"]:
        raise ValueError("MIP ranking differs from RTL")
    rows.append(
        dict(
            shape_residual_seed=group,
            solution=solution,
            predicted_drained=scores,
            rtl_visible={r["name"]: r["rtl_visible"] for r in cases},
            ranking_matches=True,
        )
    )
receipt = dict(version=MODEL_VERSION, code_sha256=model_hashes(), results=rows)
if args.verify:
    # JSON converts tuples to lists; normalize before checking saved evidence.
    if json.loads(json.dumps(receipt)) != prior:
        raise ValueError("saved search differs")
else:
    with args.out.open("x") as out:
        json.dump(receipt, out, indent=2)
        out.write("\n")
print(json.dumps(dict(pairs=len(rows), mip_seconds=seconds, all_rankings_match=True)))
