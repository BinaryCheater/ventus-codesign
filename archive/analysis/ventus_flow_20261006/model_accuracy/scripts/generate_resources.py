"""Reserve valid RF/LDS amounts while holding instructions and input data fixed."""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
source = root / "accuracy-cases-v2/vecadd-wg8"
destination = root / "accuracy-resources"
destination.mkdir()
lines = (source / "input.metadata").read_text().splitlines()
base = [int(lines[i], 16) | (int(lines[i + 1], 16) << 32) for i in range(0, len(lines), 2)]
original = json.loads((source / "expected.json").read_text())
cases = []
for name, field, value in [("vecadd-vgpr256", 11, 256), ("vecadd-lds96k", 8, 96 * 1024)]:
    path = destination / name
    path.mkdir()
    metadata = base.copy()
    metadata[field] = value
    (path / "input.metadata").write_text(
        "".join(f"{x & 0xFFFFFFFF:08x}\n{x >> 32:08x}\n" for x in metadata)
    )
    (path / "input.data").write_bytes((source / "input.data").read_bytes())
    case = {**original, "name": name, "reservation_field": field, "reservation_value": value}
    (path / "expected.json").write_text(json.dumps(case, indent=2) + "\n")
    cases.append(case)
(destination / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
