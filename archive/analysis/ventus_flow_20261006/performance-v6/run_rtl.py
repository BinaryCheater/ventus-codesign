"""Fresh RTL timing observations; model predictions are never inputs to RTL."""

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
source = root / sys.argv[3]
dest = root / "evidence" / sys.argv[2]
cases = json.loads((source / "cases.json").read_text())
banks = int(sys.argv[4])
if banks not in {4, 8}:
    raise ValueError("unsupported compiled target")
rtl = Path(
    "${REMOTE_PROJECT_ROOT}/sim-verilator/build/driver_example/debug/sim-VentusRTL"
    if banks == 4
    else "${REMOTE_FLOW_ROOT}/parameter-rtl-v4/rf-banks8-fixed3/sim-verilator/build/driver_example/debug/sim-VentusRTL"
)
shim = root / ("trace_rtl-v4.so" if banks == 4 else "parameter-rtl-v4/rf-banks8-fixed3/trace.so")
for required in (rtl, shim):
    if not required.is_file():
        raise FileNotFoundError(required)
dest.mkdir()


def run(case):
    cwd = dest / case["name"]
    cwd.mkdir()
    cmd = [
        str(rtl),
        "--kernel",
        f"name={case['name']},metafile={source / case['name'] / 'input.metadata'},datafile={source / case['name'] / 'input.data'}",
        "--sim-time-max",
        "2000000",
        "--snapshot",
        "20000000",
        "--dump-mem",
        f"0x90002000,0x{0x90002000 + len(case['expected_words']) * 4 - 4:08x}",
    ]
    start = time.monotonic()
    with (cwd / "stdout.log").open("w") as out, (cwd / "stderr.log").open("w") as err:
        env = os.environ.copy()
        env["VENTUS_LAUNCH_NOT_BEFORE"] = "512"
        env["LD_PRELOAD"] = str(shim)
        env["VENTUS_TRACE_PATH"] = str(cwd / "trace.csv")
        env["LD_LIBRARY_PATH"] = "${REMOTE_SPDLOG_ROOT}/lib:" + env.get("LD_LIBRARY_PATH", "")
        p = subprocess.run(
            ["timeout", "180", *cmd],
            cwd=cwd,
            env=env,
            stdout=out,
            stderr=err,
            check=False,
        )
    log = (cwd / "stdout.log").read_text(errors="replace")
    stderr = (cwd / "stderr.log").read_text(errors="replace")
    if "cannot be preloaded" in stderr or not (cwd / "trace.csv").is_file():
        raise RuntimeError(f"timing observer failed: {case['name']}")
    starts = re.findall(r"@(\d+) block0\s+dispatched", log)
    ends = re.findall(r"@(\d+) kernel0 .* finished", log)
    words = [
        int(x, 16) for x in re.findall(r"dump-mem: mem\[0x[0-9A-F]+ \+: 4\] = 0x([0-9A-F]+)", log)
    ]
    result = {
        **case,
        "returncode": p.returncode,
        "rf_banks": banks,
        "wall_seconds": time.monotonic() - start,
        "dispatch_to_finish_cycles": (int(ends[-1]) - int(starts[0])) // 10
        if starts and ends
        else None,
        "checked_words": len(words),
        "all_output_zero": words == [0] * 32,
        "output_matches": words == case["expected_words"],
        "output_words": words,
        "warnings": [x for x in log.splitlines() if "[RTL    error]" in x],
        "rtl_binary_sha256": hashlib.sha256(rtl.read_bytes()).hexdigest(),
        "rtl_library_sha256": hashlib.sha256(
            (rtl.parents[2] / "libVentusRTL/debug/libVentusRTL.so").read_bytes()
        ).hexdigest(),
        "trace_tool_sha256": hashlib.sha256(shim.read_bytes()).hexdigest(),
        "launch_not_before_cycle": 512,
    }
    (cwd / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in {"workload", "expected_words", "output_words"}
            }
        ),
        flush=True,
    )
    return result


with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    results = list(pool.map(run, cases))
(dest / "results.json").write_text(json.dumps(results, indent=2) + "\n")
