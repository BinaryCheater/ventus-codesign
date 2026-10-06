"""Check a legacy Ventus testcase and preserve its exact execution evidence."""

import hashlib
import json
import re
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


case_dir, upstream = map(Path, sys.argv[1:])
log = (case_dir / "stdout.log").read_text()
words = {
    int(address, 16): int(value, 16)
    for address, value in re.findall(
        r"dump-mem: mem\[0x([0-9A-Fa-f]+) \+: 4\] = 0x([0-9A-Fa-f]+)", log
    )
}
addresses = range(0x90002000, 0x90003000, 4)
correct = all(words.get(address) == 0x44800000 for address in addresses)
finish = re.search(r"@([0-9]+).*kernel0\s+vecadd\s+finished", log)
result = {
    "testcase": "upstream vecadd_32b8w8t",
    "completed": finish is not None,
    "output_correct": correct,
    "checked_words": len([address for address in addresses if address in words]),
    "expected_fp32_value": 1024.0,
    "kernel_finish_simulation_time_unit": int(finish[1]) if finish else None,
    "wall_seconds": float((case_dir / "wall_seconds.txt").read_text()),
    "memory_errors": re.findall(r".*PMEM.*", log),
    "artifacts_sha256": {
        "metadata": sha256(case_dir / "vecadd.metadata"),
        "data": sha256(case_dir / "vecadd.data"),
        "generated_rtl": sha256(upstream / "sim-verilator/dut.v"),
        "parameters": sha256(upstream / "sim-verilator/parameters.json"),
        "simulator": sha256(upstream / "sim-verilator/build/driver_example/debug/sim-VentusRTL"),
    },
}
(case_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
if not correct or finish is None:
    raise SystemExit("Completion and all 1024 output words must both pass.")
