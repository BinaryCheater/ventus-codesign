"""Read-only accounting of frozen Transformer and full-DUT LayerNorm evidence."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path, sources):
    sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return json.loads(path.read_text())


def audit():
    sources = {}
    transformer = []
    for name in ("small-s16-final", "small-s64-final2"):
        receipt = read(ROOT / "performance-v6" / name / "experiment.json", sources)
        result = receipt["result"]
        if not result["completed"] or receipt["rtl_full_network_verified"]:
            raise ValueError("unexpected frozen evidence status")
        kinds = defaultdict(lambda: {"cycles": 0, "dispatches": 0})
        for stage in result["stages"]:
            if not stage["completed"]:
                raise ValueError("incomplete stage")
            kinds[stage["kind"]]["cycles"] += stage["end"] - stage["start"]
            kinds[stage["kind"]]["dispatches"] += stage["dispatches"]
        if sum(value["cycles"] for value in kinds.values()) != result["cycles"]:
            raise ValueError("stage cycle accounting differs")
        transformer.append(
            {
                "name": name,
                "cycles": result["cycles"],
                "host_seconds": result["host_seconds"],
                "instructions": result["instructions"],
                "dispatches": sum(value["dispatches"] for value in kinds.values()),
                "by_kind": {
                    kind: {**value, "share_percent": 100 * value["cycles"] / result["cycles"]}
                    for kind, value in kinds.items()
                },
                "full_network_rtl_verified": False,
            }
        )
    layernorm = []
    accuracy = read(ROOT / "layernorm_rtl_20261006/accuracy.json", sources)
    for case in accuracy["results"]:
        directory = ROOT / "layernorm_rtl_20261006/rtl-c" / case["name"]
        raw = read(directory / "summary.json", sources)
        trace_path = directory / "trace.csv"
        sources[str(trace_path.relative_to(ROOT))] = hashlib.sha256(
            trace_path.read_bytes()
        ).hexdigest()
        rows = [line.split(",") for line in trace_path.read_text().splitlines()]
        collect = min(int(row[0]) for row in rows if row[1] == "collect")
        finish = max(int(row[0]) for row in rows if row[1] == "host.finish")
        dispatch = finish - raw["dispatch_to_finish_cycles"]
        if dispatch != raw["launch_not_before_cycle"]:
            raise ValueError("launch boundary differs")
        layernorm.append(
            {
                "name": case["name"],
                "host_wall_seconds": raw["wall_seconds"],
                "launch_cycle": dispatch,
                "first_collect_cycle": collect,
                "host_finish_cycle": finish,
                "rtl_dispatch_to_finish_cycles": raw["dispatch_to_finish_cycles"],
                "prediction_first_collect_to_compute_cycles": case["predicted_compute"],
                "prediction_first_collect_to_visible_cycles": case["predicted_visible"],
                "launch_to_first_collect_cycles": collect - dispatch,
                "visible_to_host_finish_cycles": finish - collect - case["rtl_visible"],
                "end_to_end_prediction_available": False,
            }
        )
    return {
        "source_sha256": sources,
        "transformer": transformer,
        "layernorm": layernorm,
        "accuracy_claim": "Full Transformer accuracy has not been measured.",
        "overhead_policy": "Observed launch/tail gaps describe these four probes only; do not add them as a fitted per-dispatch constant.",
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
