"""Test explicit SSH restoration with synthetic keys and isolated paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from ansible_collections.neilime.workstation_backup.plugins.module_utils.key_restore import (
    restore_key,
)


def _item() -> dict:
    return {
        "id": "fixture",
        "name": "fixture-key",
        "fields": [
            {"name": "private_key", "value": "synthetic-private"},
            {"name": "public_key", "value": "synthetic-public"},
        ],
    }


def test_ssh_restore_replaces_only_approved_pair_and_verifies_permissions(tmp_path: Path) -> None:
    """Selected remote values replace local ones; unrelated keys survive and repeats are idempotent."""

    directory = tmp_path / ".ssh"
    directory.mkdir()
    unrelated = directory / "other-key"
    unrelated.write_text("keep")
    for name in ("fixture-key", "fixture-key.pub"):
        (directory / name).write_text("old")
    assert restore_key("ssh", str(tmp_path), _item(), "fixture-key", run_command=Mock(), check_mode=True)
    assert (directory / "fixture-key").read_text() == "old"
    assert restore_key("ssh", str(tmp_path), _item(), "fixture-key", run_command=Mock())
    assert (directory / "fixture-key").read_text() == "synthetic-private\n"
    assert (directory / "fixture-key.pub").read_text() == "synthetic-public\n"
    assert (directory / "fixture-key").stat().st_mode & 0o777 == 0o600
    assert (directory / "fixture-key.pub").stat().st_mode & 0o777 == 0o644
    assert unrelated.read_text() == "keep"
    assert not restore_key("ssh", str(tmp_path), _item(), "fixture-key", run_command=Mock())


def test_missing_key_preview_does_not_create_a_directory(tmp_path: Path) -> None:
    """A remote-only key can be previewed without changing workstation paths."""

    assert restore_key("ssh", str(tmp_path), _item(), "fixture-key", run_command=Mock(), check_mode=True)
    assert not (tmp_path / ".ssh").exists()


@pytest.mark.parametrize("target", ["directory", "private", "public"])
def test_linked_destinations_fail_before_overwriting_any_key(tmp_path: Path, target: str) -> None:
    """Validate the entire pair before writing so a bad public destination cannot alter the private key."""

    directory = tmp_path / ".ssh"
    outside = tmp_path / "outside"
    outside.mkdir()
    if target == "directory":
        directory.symlink_to(outside)
    else:
        directory.mkdir()
        (directory / "fixture-key").write_text("original")
        destination = directory / ("fixture-key" if target == "private" else "fixture-key.pub")
        destination.unlink(missing_ok=True)
        destination.symlink_to(outside / "key")
    with pytest.raises(ValueError, match="link"):
        restore_key("ssh", str(tmp_path), _item(), "fixture-key", run_command=Mock())
    assert not (outside / "key").exists()
    if target == "public":
        assert (directory / "fixture-key").read_text() == "original"


def test_remote_identity_change_is_rejected_before_writing(tmp_path: Path) -> None:
    """A renamed vault record must not silently change the approved local destination."""

    with pytest.raises(ValueError, match="identity changed"):
        restore_key("ssh", str(tmp_path), _item(), "different-key", run_command=Mock())
    assert not (tmp_path / ".ssh").exists()
