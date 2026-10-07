"""Run pinned CACTI on individual RF/LDS banks; preserve inputs and raw outputs."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from time import perf_counter

COMMIT = "1ffd8dfb10303d306ecd8d215320aea07651e878"


def configure(template, values):
    lines = template.splitlines()
    for key, value in values.items():
        matches = [i for i, line in enumerate(lines) if line.startswith(key + " ")]
        if len(matches) != 1:
            raise ValueError(f"expected one active configuration entry: {key}")
        lines[matches[0]] = f"{key} {value}"
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    assert revision == COMMIT
    args.out.mkdir(parents=True, exist_ok=False)
    template = (source / "cache.cfg").read_text()
    profiles = (
        [(f"vgpr_{2**i}", 2**i, 1024, "RF") for i in range(11, 17)]
        + [(f"sgpr_{2**i}", 2**i, 32, "RF") for i in range(5, 12)]
        + [(f"lds_{2**i}", 2**i, 32, "LDS") for i in range(9, 15)]
    )
    if args.smoke:
        profiles = [profiles[1]]
    rows = []
    for tech in [32] if args.smoke else [32, 22]:
        for name, capacity, width, family in profiles:
            ports = (
                [(0, 1, 1), (0, 2, 1), (0, 1, 2), (0, 2, 2)]
                if family == "RF"
                else [(1, 0, 0), (2, 0, 0)]
            )
            for rw, rd, wr in ports:
                ident = f"{name}-{tech}nm-{rw}RW-{rd}R-{wr}W"
                cfg = configure(
                    template,
                    {
                        "-size (bytes)": capacity,
                        "-block size (bytes)": width // 8,
                        "-associativity": 1,
                        "-read-write port": rw,
                        "-exclusive read port": rd,
                        "-exclusive write port": wr,
                        "-single ended read ports": 0,
                        "-UCA bank count": 1,
                        "-technology (u)": tech / 1000,
                        "-output/input bus width": width,
                        "-cache type": '"ram"',
                        "-Add ECC -": '"false"',
                        "-Optimize ED or ED^2 (ED, ED^2, NONE):": '"NONE"',
                        "-design objective (weight delay, dynamic power, leakage power, cycle time, area)": "0:0:0:0:100",
                        "-deviate (delay, dynamic power, leakage power, cycle time, area)": "100000:100000:100000:100000:100000",
                    },
                )
                config_path = args.out / (ident + ".cfg")
                config_path.write_text(cfg)
                begin = perf_counter()
                try:
                    run = subprocess.run(
                        [str(source / "cacti"), "-infile", str(config_path.resolve())],
                        cwd=source,
                        capture_output=True,
                        text=True,
                        timeout=45,
                    )
                    output = run.stdout + run.stderr
                    code = run.returncode
                except subprocess.TimeoutExpired as error:
                    output = (error.stdout or b"").decode(errors="replace") + "\nTIMEOUT\n"
                    code = None
                # CACTI may echo its command; never export host-specific paths.
                output = output.replace(str(config_path.resolve()), config_path.name).replace(
                    str(source), "<CACTI_SOURCE>"
                )
                (args.out / (ident + ".log")).write_text(output)

                def number(pattern):
                    match = re.search(pattern + r"\s*([0-9.eE+-]+)", output)
                    return float(match[1]) if match else None

                row = dict(
                    id=ident,
                    family=family,
                    capacity_bytes=capacity,
                    width_bits=width,
                    tech_nm=tech,
                    rw_ports=rw,
                    read_ports=rd,
                    write_ports=wr,
                    exit_code=code,
                    host_seconds=perf_counter() - begin,
                    config_sha256=hashlib.sha256(cfg.encode()).hexdigest(),
                    area_mm2=number(r"Data array: Area \(mm2\):"),
                    access_ns=number(r"Access time \(ns\):"),
                    cycle_ns=number(r"Cycle time \(ns\):"),
                )
                rows.append(row)
                print(ident, code, row["area_mm2"], flush=True)
                (args.out / "report.json").write_text(
                    json.dumps(
                        {
                            "source_commit": revision,
                            "source_url": "https://github.com/HewlettPackard/cacti",
                            "binary_sha256": hashlib.sha256(
                                (source / "cacti").read_bytes()
                            ).hexdigest(),
                            "rows": rows,
                        },
                        indent=2,
                    )
                    + "\n"
                )


if __name__ == "__main__":
    main()
