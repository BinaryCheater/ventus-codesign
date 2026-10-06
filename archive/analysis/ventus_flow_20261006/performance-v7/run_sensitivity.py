"""Bounded model-only cache/latency sensitivity, never an RTL accuracy claim."""

import json
from pathlib import Path

from codesign.ventus.transformer_cli import run

root = Path(__file__).parent
for name, changes in [
    ("default", {}),
    ("memory-latency100", {"memory_latency": 100}),
    ("small-l1", {"l1_sets": 4}),
]:
    source = root / f"sensitivity-{name}.json"
    with source.open("x") as f:
        f.write(
            json.dumps(
                {"spec": {"layers": 1, "prefill": 4, "decode_steps": 1}, "hardware": changes},
                indent=2,
            )
            + "\n"
        )
    run(root / f"sensitivity-{name}", input_path=source, budget=60)
