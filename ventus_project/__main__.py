"""Select local or configured SSH execution and prepare a portable share."""

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from .config import ROOT, execution_mode, load_profile, remote_command, remote_settings
from .share import audit, pack

MODULES = {
    "model": "codesign.ventus",
    "baseline": "codesign.ventus.baseline",
    "costs": "codesign.ventus_costs",
    "tests": "pytest",
    "evidence": "ventus_project.evidence",
}


def deploy(profile, package):
    remote = remote_settings(profile)
    root = shlex.quote(remote["run_root"])
    uv = shlex.quote(remote.get("uv") or "uv")
    python = shlex.quote(remote["python"])
    # Require a fresh server directory, protecting every existing experiment.
    command = (
        f"set -eu; mkdir {root}; "
        f"tar -xzf - --strip-components=1 -C {root}; "
        f"cd {root}; if command -v {uv} >/dev/null 2>&1; then "
        f"{uv} sync --frozen --extra dev --python {python}; "
        f"else {python} -m venv .venv; "
        '.venv/bin/python -m pip install -e ".[dev]"; fi'
    )
    with package.open("rb") as stream:
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", remote["host"], command], stdin=stream, check=True
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Show capability and profile status without connecting")
    sub.add_parser("audit", help="Scan shareable files; never prints private values")
    share = sub.add_parser("share", help="Create an allowlisted, privacy-checked .tar.gz")
    share.add_argument("--out", type=Path, required=True)
    deploy_parser = sub.add_parser(
        "deploy", help="Install on your configured server in a fresh folder"
    )
    deploy_parser.add_argument("--package", type=Path, required=True)
    run = sub.add_parser("run", help="Use your private default; no profile defaults to local")
    run.add_argument("--local", action="store_true")
    run.add_argument("--remote", action="store_true")
    run.add_argument("tool", choices=MODULES)
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    profile = load_profile()
    try:
        if args.command == "doctor":
            print(
                json.dumps(
                    {
                        "python": sys.version.split()[0],
                        "private_profile_present": (ROOT / "local.toml").is_file(),
                        "default_execution": execution_mode(profile),
                        "remote_enabled": profile.get("remote", {}).get("enabled", False),
                        "ssh_connection_attempted": False,
                        "local_requirements": ["Python >=3.12", "numpy", "highspy"],
                        "hardware_tools_required_for_model_queries": False,
                    },
                    indent=2,
                )
            )
        elif args.command == "audit":
            print(json.dumps(audit(), indent=2))
        elif args.command == "share":
            print(json.dumps(pack(args.out), indent=2))
        elif args.command == "deploy":
            remote_settings(profile)  # Validate before any subprocess.
            if not args.package.is_file():
                raise ValueError("Create a share package first")
            deploy(profile, args.package)
        else:
            if args.local and args.remote:
                raise ValueError("Choose one execution override")
            override = "local" if args.local else "remote" if args.remote else None
            mode = execution_mode(profile, override)
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            module = MODULES[args.tool]
            if mode == "remote":
                remote = remote_settings(profile)
                command = remote_command(remote, module, arguments)
                subprocess.run(["ssh", "-o", "BatchMode=yes", remote["host"], command], check=True)
            else:
                (ROOT / "results").mkdir(exist_ok=True)
                subprocess.run([sys.executable, "-m", module, *arguments], cwd=ROOT, check=True)
    except (ValueError, FileExistsError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
