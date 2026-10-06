"""Load an optional, private machine profile; never supply an implicit server."""

import shlex
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_profile(root=ROOT):
    path = root / "local.toml"
    return tomllib.loads(path.read_text()) if path.is_file() else {}


def execution_mode(profile, override=None):
    mode = override or profile.get("execution", {}).get("mode", "local")
    if mode not in {"local", "remote"}:
        raise ValueError("execution.mode must be local or remote")
    return mode


def remote_settings(profile):
    remote = profile.get("remote", {})
    if remote.get("enabled") is not True:
        raise ValueError(
            "Remote execution is disabled. Configure your own ignored local.toml first."
        )
    for key in ("host", "run_root", "python"):
        if not isinstance(remote.get(key), str) or not remote[key].strip():
            raise ValueError(f"Missing remote.{key} in local.toml; no SSH connection attempted.")
    if remote["host"].startswith("-") or any(c.isspace() for c in remote["host"]):
        raise ValueError("remote.host must be one SSH destination, without options")
    if not remote["run_root"].startswith("/") or remote["run_root"] == "/":
        raise ValueError("remote.run_root must be an absolute project directory")
    return remote


def remote_command(remote, module, arguments):
    root = shlex.quote(remote["run_root"])
    setup = remote.get("environment_script")
    prefix = f". {shlex.quote(setup)} && " if setup else ""
    python = shlex.quote(f"{remote['run_root']}/.venv/bin/python")
    command = shlex.join([module, *arguments])
    return f"cd {root} && mkdir -p results && {prefix}{python} -m {command}"
