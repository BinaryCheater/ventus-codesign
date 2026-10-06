import csv
import hashlib
import json
import sys
from pathlib import Path

from codesign.ventus.__main__ import read_candidate
from codesign.ventus.timing import simulate

root = Path("analysis/ventus_flow_20261006/performance-v6")
rows = json.loads((root / "mixed-rf4-v6/results.json").read_text())
out = []
for row in rows:
    candidate = read_candidate({"workload": row["workload"]})
    assert simulate(candidate.workload, candidate.hardware)["cycles"] == row["prediction"]
    events = list(
        csv.DictReader(
            (root / "mixed-rf4-v6" / row["name"] / "trace.csv").open(),
            fieldnames=["cycle", "kind", "warp", "pc", "word"],
        )
    )
    starts = [int(e["cycle"]) for e in events if e["kind"] == "collect"]
    ends = [
        int(e["cycle"])
        for e in events
        if e["kind"] == "writeback" and int(e["pc"], 16) == row["final_pc"]
    ]
    # Fused accumulate starts from +0; Python's 12*x*y reference preserves
    # negative zero for negative*zero. IEEE (-0)+(+0) under RNE yields +0.
    corrected = [0 if w == 0x80000000 else w for w in row["expected_words"]]
    actual = int(max(ends) - min(starts)) if len(ends) == row["warps"] else None
    streams = {
        w: [(e["pc"], e["word"]) for e in events if e["kind"] == "collect" and int(e["warp"]) == w]
        for w in range(row["warps"])
    }
    expected = [(f"{0x80000000 + 4 * i:08x}", f"{word:08x}") for i, word in enumerate(row["words"])]
    stream_ok = all(s == expected for s in streams.values())
    assert row["returncode"] == 0 and stream_ok and corrected == row["output_words"]
    for n, digest in row["input_sha256"].items():
        assert (
            hashlib.sha256((root / "mixed-probes" / row["name"] / n).read_bytes()).hexdigest()
            == digest
        )
    out.append(
        dict(
            trace_sha256=hashlib.sha256(
                (root / "mixed-rf4-v6" / row["name"] / "trace.csv").read_bytes()
            ).hexdigest(),
            name=row["name"],
            prediction=row["prediction"],
            rtl_cycles=actual,
            error_percent=100 * (row["prediction"] / actual - 1) if actual else None,
            original_reference_matches=row["output_matches"],
            corrected_reference_matches=corrected == row["output_words"],
            zero_sign_reference_corrections=sum(
                a != b for a, b in zip(corrected, row["expected_words"])
            ),
            collector_stream_matches=stream_ok,
            wall_seconds=row["wall_seconds"],
            returncode=row["returncode"],
        )
    )
receipt = {
    "cases": out,
    "reference_correction": "RNE fused accumulation of negative-zero product into +0 yields +0; frozen original reference retained",
}
if "--verify" in sys.argv:
    assert json.loads((root / "mixed-accuracy-final.json").read_text()) == receipt
    print("Read-only mixed RTL receipt verified.")
else:
    with (root / "mixed-accuracy-final.json").open("x") as f:
        f.write(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(out, indent=2))
