"""Collaborators cannot inherit or accidentally contact an owner's server."""

import json
import tarfile

import pytest

from ventus_project.config import execution_mode, load_profile, remote_command, remote_settings
from ventus_project.share import audit, pack


def test_missing_profile_is_local_and_cannot_select_server(tmp_path):
    profile = load_profile(tmp_path)
    assert profile == {}
    assert execution_mode(profile) == "local"
    with pytest.raises(ValueError, match="disabled"):
        remote_settings(profile)


def test_owner_can_keep_remote_default_and_command_arguments_are_quoted():
    profile = {
        "execution": {"mode": "remote"},
        "remote": {
            "enabled": True,
            "host": "test-host",
            "run_root": "/work/project",
            "python": "python3",
        },
    }
    assert execution_mode(profile) == "remote"
    assert execution_mode(profile, "local") == "local"
    remote = remote_settings(profile)
    command = remote_command(
        remote, "codesign.ventus", ["demo", "--out", "results/a;touch injected"]
    )
    assert "'results/a;touch injected'" in command


def test_remote_rejected_before_subprocess_when_incomplete():
    with pytest.raises(ValueError, match="no SSH connection attempted"):
        remote_settings({"remote": {"enabled": True, "host": "test-host"}})
    with pytest.raises(ValueError, match="without options"):
        remote_settings(
            {
                "remote": {
                    "enabled": True,
                    "host": "-oProxyCommand=bad",
                    "run_root": "/work/project",
                    "python": "python3",
                }
            }
        )


def test_share_omits_private_profile_and_archive_owner_metadata(tmp_path):
    root = tmp_path / "case"
    root.mkdir()
    (root / "README.md").write_text("Portable model.\n")
    (root / "local.toml").write_text(
        '[remote]\nhost="private-example"\n[privacy]\nredactions=["private-example"]\n'
    )
    (root / "results").mkdir()
    (root / "results/private.log").write_text("private-example")
    (root / ".git").mkdir()
    (root / ".git/config").write_text("private-example")
    package = tmp_path / "share.tar.gz"
    pack(package, root)
    with tarfile.open(package) as archive:
        names = archive.getnames()
        assert names == [
            "ventus-codesign/README.md",
            "ventus-codesign/results",
            "ventus-codesign/analysis",
        ]
        for member in archive.getmembers():
            assert not member.uname and not member.gname
        assert archive.getmember("ventus-codesign/analysis").linkname == "archive/analysis"


def test_audit_checks_binaries_and_private_values_without_echoing_them(tmp_path):
    (tmp_path / "README.md").write_bytes(b"\0confidential-server")
    (tmp_path / "local.toml").write_text('[privacy]\nredactions=["confidential-server"]\n')
    with pytest.raises(ValueError) as error:
        audit(tmp_path)
    assert "README.md" in str(error.value)
    assert "confidential-server" not in str(error.value)


def test_manifest_paths_do_not_escape_and_package_has_no_parent_dependency():
    from pathlib import Path

    from codesign.ventus.config import Hardware

    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "vendor/ventus-gpgpu/SOURCE.json").read_text())
    assert all(not Path(p).is_absolute() and ".." not in Path(p).parts for p in manifest["files"])
    import inspect

    assert Path(inspect.getfile(Hardware)).is_relative_to(root)


@pytest.mark.parametrize("budget", [0, -1, float("nan"), float("inf"), True, "60"])
def test_replay_budget_validated_before_reading_or_writing_receipt(tmp_path, budget):
    from codesign.ventus.transformer_cli import verify

    with pytest.raises(ValueError, match="finite and positive"):
        verify(tmp_path, time_budget=budget)
    assert not list(tmp_path.iterdir())
