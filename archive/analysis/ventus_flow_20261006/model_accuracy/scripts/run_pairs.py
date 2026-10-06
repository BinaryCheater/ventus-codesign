"""Run each backend without editing its hardware or timing implementation."""

import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
cases_dir = root / (sys.argv[2] if len(sys.argv) > 2 else "accuracy-cases-v2")
destination = root / "evidence" / (sys.argv[3] if len(sys.argv) > 3 else "accuracy-pairs")
destination.mkdir()
cases = json.loads((cases_dir / "cases.json").read_text())
rtl = Path("${REMOTE_PROJECT_ROOT}/sim-verilator/build/driver_example/debug/sim-VentusRTL")
cyclesim = root / "accuracy-driver-v2/main"


def run_backend(backend):
    results = []
    for case in cases:
        name = case["name"]
        cwd = destination / (name + "-" + backend)
        cwd.mkdir()
        source = cases_dir / name
        inputs = [
            "--kernel",
            f"name={name},metafile={source / 'input.metadata'},datafile={source / 'input.data'}",
            "--sim-time-max",
            "2000000",
        ]
        expected = case["expected_words"]
        environment = os.environ.copy()
        if backend == "rtl":
            cmd = [
                str(rtl),
                *inputs,
                "--snapshot",
                "20000000",
                "--dump-mem",
                f"0x90002000,0x{0x90002000 + (len(expected) - 1) * 4:x}",
            ]
        else:
            cmd = [str(cyclesim), *inputs]
            environment["VENTUS_TEST_WORDS"] = str(len(expected))
        begin = time.monotonic()
        with (cwd / "stdout.log").open("w") as out, (cwd / "stderr.log").open("w") as err:
            process = subprocess.run(
                ["timeout", "600", *cmd], cwd=cwd, env=environment, stdout=out, stderr=err
            )
        wall = time.monotonic() - begin
        stdout = (cwd / "stdout.log").read_text()
        if backend == "rtl":
            output = [
                int(x, 16)
                for x in re.findall(r"dump-mem: mem\[0x[0-9A-F]+ \+: 4\] = 0x([0-9A-F]+)", stdout)
            ]
            starts = [int(x) for x in re.findall(r"@(\d+) block\d+\s+dispatched to GPU", stdout)]
            finishes = [int(x) for x in re.findall(r"@(\d+) kernel 0 .* finished", stdout)]
            if not finishes:
                finishes = [int(x) for x in re.findall(r"@(\d+) block\d+\s+finished", stdout)]
        else:
            output = [int(x, 16) for x in re.findall(r"TEST_OUTPUT \d+ ([0-9a-f]+)", stdout)]
            starts = [int(x) for x in re.findall(r"receive kernel .* @(\d+)ns", stdout)]
            finishes = [int(x) for x in re.findall(r"TEST_KERNEL_FINISH_NS (\d+)", stdout)]
        result = {
            "case": name,
            "backend": backend,
            "family": case["family"],
            "n": case["n"],
            "returncode": process.returncode,
            "wall_seconds": wall,
            "first_dispatch_time": min(starts) if starts else None,
            "kernel_finish_time": max(finishes) if finishes else None,
            "output_correct": output == expected,
            "checked_words": len(output),
            "warnings": [
                x
                for x in stdout.splitlines()
                if "[RTL    error]" in x or "out of range" in x or "error:" in x
            ],
            "input_sha256": {
                x: hashlib.sha256((source / x).read_bytes()).hexdigest()
                for x in ["input.metadata", "input.data"]
            },
        }
        if starts and finishes:
            result["dispatch_to_finish_cycles"] = (max(finishes) - min(starts)) / 10
        (cwd / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        results.append(result)
        print(json.dumps(result), flush=True)
    return results


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(run_backend, backend) for backend in ["rtl", "systemc"]]
    results = [x for future in futures for x in future.result()]
(destination / "results.json").write_text(json.dumps(results, indent=2) + "\n")
