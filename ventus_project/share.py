"""Allowlisted, privacy-checked exports, with no machine config or result cache."""

import hashlib
import re
import tarfile
from pathlib import Path

from .config import ROOT, load_profile

ITEMS = (
    "README.md",
    "run",
    "AGENTS.md",
    ".gitignore",
    ".gitattributes",
    "pyproject.toml",
    "uv.lock",
    "local.example.toml",
    "codesign",
    "ventus_project",
    "tests",
    "docs",
    "examples",
    "prompts",
    "patches",
    "archive",
    "vendor",
)
EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".DS_Store", "target"}
GENERIC_PRIVATE = re.compile(rb"/Users/[A-Za-z0-9_.-]+|/home/[A-Za-z0-9_.-]+")


def share_files(root=ROOT):
    for item in ITEMS:
        path = root / item
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for candidate in candidates:
            if any(part in EXCLUDED for part in candidate.relative_to(root).parts):
                continue
            if candidate.suffix == ".pyc" or candidate.is_symlink():
                continue
            if candidate.is_file():
                yield candidate


def audit(root=ROOT):
    profile = load_profile(root)
    literals = list(profile.get("privacy", {}).get("redactions", []))
    # Include newly configured destinations/paths automatically. Very short user
    # names and interpreter names are not unique private literals.
    for section in ("remote", "owner"):
        for key, value in profile.get(section, {}).items():
            if key not in {"python", "user"} and isinstance(value, str) and len(value) > 3:
                literals.append(value)
    pattern = (
        re.compile(b"|".join(re.escape(x.encode()) for x in literals if x)) if literals else None
    )
    errors = []
    count = total = 0
    for path in share_files(root):
        data = path.read_bytes()
        count += 1
        total += len(data)
        # Match owner values even in binaries. Generic home paths are text-only;
        # numeric scientific data and public IP examples are not owner addresses.
        if pattern and pattern.search(data):
            errors.append(path.relative_to(root).as_posix())
        elif (
            path.relative_to(root).parts[0] != "vendor"
            and b"\0" not in data[:8192]
            and GENERIC_PRIVATE.search(data)
        ):
            # Public upstream source fixtures may include users' example paths.
            # Private profile literals are still checked everywhere, including vendor.
            errors.append(path.relative_to(root).as_posix())
    if errors:
        raise ValueError("Private/machine-specific values in shareable files: " + ", ".join(errors))
    return {"files": count, "bytes": total, "private_values_detected": False}


def pack(output: Path, root=ROOT):
    audit(root)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    # No output is generated under an allowlisted directory.
    if any(output.is_relative_to(root / name) for name in ITEMS if (root / name).is_dir()):
        raise ValueError("Write share packages outside source and evidence directories")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream, tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for path in share_files(root):
            info = archive.gettarinfo(
                str(path), "ventus-codesign/" + path.relative_to(root).as_posix()
            )
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as source:
                archive.addfile(info, source)
        # Include an empty output directory, never the owner's generated results.
        results = tarfile.TarInfo("ventus-codesign/results")
        results.type = tarfile.DIRTYPE
        results.mode = 0o755
        archive.addfile(results)
        # Relative compatibility link for historical test and replay paths.
        link = tarfile.TarInfo("ventus-codesign/analysis")
        link.type = tarfile.SYMTYPE
        link.linkname = "archive/analysis"
        archive.addfile(link)
    return {"archive": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
