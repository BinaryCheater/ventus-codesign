"""Build a runtime table from successful 32-nm entries, preserving failed probes."""

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
report = ROOT / "raw/report.json"
raw = json.loads(report.read_text())
banks = {}
failed = []
for row in raw["rows"]:
    cfg = ROOT / "raw" / (row["id"] + ".cfg")
    assert hashlib.sha256(cfg.read_bytes()).hexdigest() == row["config_sha256"]
    if row["exit_code"] != 0 or any(
        row[k] is None or not math.isfinite(row[k]) or row[k] <= 0
        for k in ["area_mm2", "access_ns", "cycle_ns"]
    ):
        failed.append(row["id"])
        continue
    if row["tech_nm"] != 32:
        continue
    family = row["id"].split("_")[0]
    key = f"{family}:{row['capacity_bytes']}:{row['rw_ports']}:{row['read_ports']}:{row['write_ports']}"
    banks[key] = {k: row[k] for k in ["area_mm2", "access_ns", "cycle_ns"]}
    banks[key]["source_id"] = row["id"]
anchors = {}
for family, size, ports in [
    ("vgpr", 32768, "0:1:1"),
    ("sgpr", 2048, "0:1:1"),
    ("lds", 4096, "1:0:0"),
]:
    anchors[family] = {"capacity_bytes": size, **banks[f"{family}:{size}:{ports}"]}
table = {
    "version": "ventus-native-arrays-v1",
    "source_commit": raw["source_commit"],
    "raw_report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
    "technology_nm": 32,
    "minimum_bank_bytes": {"vgpr": 4096, "sgpr": 128, "lds": 512},
    "scope": "CACTI area-minimum native arrays; ratios to baseline FakeRAM anchors; not ASAP7 timing characterization",
    "anchors": anchors,
    "banks": banks,
    "failed_probes": failed,
}
text = json.dumps(table, indent=2) + "\n"
out = ROOT.parents[2] / "codesign/ventus_costs/native_arrays_v1.json"
if out.exists():
    assert out.read_text() == text
else:
    out.write_text(text)
print(
    json.dumps(
        {"probes": len(raw["rows"]), "failed": len(failed), "runtime_bank_entries": len(banks)}
    )
)
