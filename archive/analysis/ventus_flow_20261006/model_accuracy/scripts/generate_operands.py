"""Hold instruction structure fixed while varying integer division operands."""

import json
import sys
from pathlib import Path

from generate_cases import i_type, store, v_type

root = Path(sys.argv[1])
source = root / "accuracy-cases-v2/vector_div-16"
destination = root / "accuracy-operands"
destination.mkdir()
lines = (source / "input.metadata").read_text().splitlines()
metadata = [int(lines[i], 16) | (int(lines[i + 1], 16) << 32) for i in range(0, len(lines), 2)]
sizes = metadata[14 + metadata[13] : 14 + 2 * metadata[13]]
bases = metadata[14 : 14 + metadata[13]]
offset = sum(sizes[: bases.index(0x80000000)]) // 4
length = sizes[bases.index(0x80000000)] // 4
cases = []
for name, operand, lui, immediate in [
    ("div-1-by-1", 1, 0, 1),
    ("div-maxint-by-1", 0x7FFFFFFF, 0x80000, -1),
]:
    program = [
        v_type(0x0B, 1, 1, 0, 1),
        (lui << 12) | (6 << 7) | 0x37,
        i_type(immediate, 6, 0, 6),
        i_type(1, 0, 0, 5),
        v_type(0, 1, 6, 4, 1),
    ]
    program += [v_type(0x21, 1, 5, 6, 1)] * 16
    program += [
        0x90002137,
        v_type(0x14, 0, 17, 2, 10),
        v_type(0x25, 10, 2, 3, 10),
        v_type(0, 10, 2, 4, 10),
        store(1, 10, 6, 0x7B),
        0x400B,
    ]
    data = [int(x, 16) for x in (source / "input.data").read_text().splitlines()]
    data[offset : offset + length] = program + [0x13] * (length - len(program))
    path = destination / name
    path.mkdir()
    (path / "input.metadata").write_bytes((source / "input.metadata").read_bytes())
    (path / "input.data").write_text("".join(f"{x:08x}\n" for x in data))
    case = {"name": name, "family": "div_operands", "n": 16, "expected_words": [operand] * 32}
    (path / "expected.json").write_text(json.dumps(case, indent=2) + "\n")
    cases.append(case)
(destination / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
