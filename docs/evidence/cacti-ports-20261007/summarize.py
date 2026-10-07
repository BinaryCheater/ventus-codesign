"""Verify saved CACTI outputs and derive paired ratios without rerunning CACTI."""

import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    report = json.loads((ROOT / "raw/report.json").read_text())
    rows = report["rows"]
    assert len(rows) == 60 and len({r["id"] for r in rows}) == 60
    output = []
    for row in rows:
        ident = row["id"]
        config = (ROOT / "raw" / (ident + ".cfg")).read_bytes()
        assert hashlib.sha256(config).hexdigest() == row["config_sha256"]
        log = (ROOT / "raw" / (ident + ".log")).read_text()
        assert row["exit_code"] == 0
        for label, key in [
            ("Cache size", "capacity_bytes"),
            ("Block size", "width_bits"),
            ("Read only ports", "read_ports"),
            ("Write only ports", "write_ports"),
            ("Read write ports", "rw_ports"),
        ]:
            value = int(re.search(r"^" + label + r"\s*:\s*(\d+)", log, re.M)[1])
            assert value == (row[key] // 8 if key == "width_bits" else row[key])
        assert "Scratch RAM" in log and "ECC overhead                  : 0" in log
        for key in ["area_mm2", "access_ns", "cycle_ns"]:
            assert math.isfinite(row[key]) and row[key] > 0
        profile = ident.split("-")[0]
        baseline = next(
            r
            for r in rows
            if r["id"].split("-")[0] == profile
            and r["tech_nm"] == row["tech_nm"]
            and (
                (r["rw_ports"], r["read_ports"], r["write_ports"])
                == ((0, 1, 1) if row["family"] == "RF" else (1, 0, 0))
            )
        )
        ratios = {
            key.replace("_mm2", "").replace("_ns", "") + "_ratio": row[key] / baseline[key]
            for key in ["area_mm2", "access_ns", "cycle_ns"]
        }
        org = dict(re.findall(r"Best (Nd[^:]+?)\s*:\s*(\S+)", log))
        output.append(
            {
                "id": ident,
                "profile": profile,
                "tech_nm": row["tech_nm"],
                "capacity_bytes": row["capacity_bytes"],
                "width_bits": row["width_bits"],
                "ports": f"{row['rw_ports']}RW-{row['read_ports']}R-{row['write_ports']}W",
                **ratios,
                "organization": org,
            }
        )
    spreads = []
    for a in [x for x in output if x["tech_nm"] == 32]:
        b = next(
            x
            for x in output
            if x["profile"] == a["profile"] and x["ports"] == a["ports"] and x["tech_nm"] == 22
        )
        spreads.append(abs(b["area_ratio"] / a["area_ratio"] - 1))
    summary = {
        "scope": "Exploratory native multiport SRAM ratios at CACTI 22/32 nm, independently area-optimized; not ASAP7 calibration or GPU timing validation.",
        "source_commit": report["source_commit"],
        "verified_cases": len(rows),
        "total_host_seconds": sum(x["host_seconds"] for x in rows),
        "max_relative_area_ratio_difference_between_nodes": max(spreads),
        "rows": output,
    }
    text = json.dumps(summary, indent=2) + "\n"
    path = ROOT / "ratios.json"
    if path.exists():
        assert path.read_text() == text
    else:
        path.write_text(text)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=[k for k in output[0] if k != "organization"], lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows({k: v for k, v in x.items() if k != "organization"} for x in output)
    path = ROOT / "ratios.csv"
    if path.exists():
        assert path.read_text() == stream.getvalue()
    else:
        path.write_text(stream.getvalue())
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
