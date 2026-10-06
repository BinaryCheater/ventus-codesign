"""Preserve successful points from the actual batches in a new immutable raw root."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    coarse = Path("${REMOTE_STORAGE_ROOT}/ventus-cost-v1c-20261006")
    native = Path("${REMOTE_STORAGE_ROOT}/ventus-cost-v1-20261006")
    extra = Path("${REMOTE_STORAGE_ROOT}/ventus-cost-components-v1-20261006")
    fixed = Path("${REMOTE_STORAGE_ROOT}/ventus-cost-fixed-v1-20261006")
    sources = [Path("${REMOTE_STORAGE_ROOT}/ventus-cost-sm-processed-v1-20261006")]
    sources += [coarse / n for n in ["l2-base", "rf4"]]
    sources += [extra / "rf8", fixed / "gpu-fixed"]
    sources += sorted(native.glob("tc-*/statistics.json"))
    sources = [p.parent if p.name == "statistics.json" else p for p in sources]
    sources += sorted(extra.glob("lds-*/statistics.json"))
    sources = [p.parent if p.name == "statistics.json" else p for p in sources]
    assert len(sources) == 15
    for p in sources:
        assert "End of script." in (p / "stdout.log").read_text(), p
        assert (p / "mapped.v").exists() and (p / "statistics.json").exists(), p
    args.out.mkdir()  # never overwrite
    target = json.loads((coarse / "target.json").read_text())
    target["flow"] = (
        "native optimized Tensor; coarse slang mapping for other components"
    )
    target["integration_scope"] = (
        "shared GPU fixed logic + standalone SM replication; estimated"
    )
    target["hardware_contract_sha256"] = digest(args.contract)
    target["collection_scripts_sha256"] = {
        "coarse": target["script_sha256"],
        "native": json.loads((native / "target.json").read_text())["script_sha256"],
    }
    shutil.copyfile(coarse / "mapping.lib", args.out / "mapping.lib")
    shutil.copyfile(args.baseline, args.out / "baseline_hardware.json")
    shutil.copyfile(args.contract, args.out / "hardware_config.py")
    libs = args.out / "libraries"
    libs.mkdir()
    for name, expected in target["libraries_sha256"].items():
        p = Path(name)
        assert digest(p) == expected
        shutil.copyfile(p, libs / p.name)
    completion = []
    for source in sources:
        mapper = (
            source / "mapping.lib"
            if (source / "mapping.lib").exists()
            else source.parent / "mapping.lib"
        )
        assert digest(mapper) == target["mapping_lib_sha256"]
        point_name = (
            "sm-base"
            if source.name == "ventus-cost-sm-processed-v1-20261006"
            else source.name
        )
        out = args.out / point_name
        shutil.copytree(source, out)
        manifest = json.loads((out / "manifest.json").read_text())
        shutil.copyfile(out / "manifest.json", out / "original_manifest.json")
        input_source = Path(manifest["source"])
        assert digest(input_source) == manifest["rtl_sha256"]
        if not (out / "source.v").exists():
            shutil.copyfile(input_source, out / "source.v")
        manifest["flow"] = "native-synth" if source.parent == native else "coarse-slang"
        if point_name == "sm-base":
            manifest["flow"] = "coarse-slang-deduplicated-then-proc"
            lowered = Path("${REMOTE_STORAGE_ROOT}/ventus-cost-sm-dedup-v1-20261006")
            shutil.copyfile(lowered / "lowered.v", out / "lowered.v")
            manifest["lowered_sha256"] = digest(out / "lowered.v")
            manifest["deduplicated_sha256"] = digest(out / "deduplicated.v")
            manifest["dedup_receipt_sha256"] = digest(out / "dedup.json")
        manifest["original_manifest_sha256"] = digest(out / "original_manifest.json")
        if source.name == "gpu-fixed":
            manifest["excluded_subsystems"] = ["SM_wrapper", "SM_wrapper_1"]
            manifest["original_gpu_sha256"] = digest(fixed / "original_gpu.v")
            shutil.copyfile(fixed / "original_gpu.v", out / "original_gpu.v")
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        completion.append(
            {"name": point_name, "returncode": 0, "raw_batch": str(source.parent)}
        )
    (args.out / "target.json").write_text(json.dumps(target, indent=2) + "\n")
    (args.out / "completion.json").write_text(json.dumps(completion, indent=2) + "\n")
    shutil.copyfile(
        coarse / "executed_collect.py", args.out / "executed_coarse_collect.py"
    )
    shutil.copyfile(
        "${REMOTE_STORAGE_ROOT}/ventus-cost-collect-20261006.py",
        args.out / "executed_native_collect.py",
    )
    shutil.copyfile(Path(__file__), args.out / "executed_assemble_raw.py")
    print("Preserved 15 successful cost points")


if __name__ == "__main__":
    main()
