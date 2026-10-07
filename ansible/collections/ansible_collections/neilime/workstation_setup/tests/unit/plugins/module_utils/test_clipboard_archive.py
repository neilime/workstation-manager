"""Reject incompatible or unsafe extension artifacts before switching managers."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.clipboard_archive import (
    ClipboardArchive,
)


def archive_fixture(tmp_path, **metadata):
    """Create a synthetic extension, independent of the maintained release pin."""
    path = tmp_path / "extension.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "metadata.json",
            json.dumps(
                {"uuid": "clipboard-indicator@tudmotu.com", "version": 123, "shell-version": ["999"], **metadata}
            ),
        )
        archive.writestr("extension.js", "// synthetic extension")
    return path


def validate(path, **overrides):
    """Validate against synthetic pins and a synthetic future Shell release."""
    return ClipboardArchive.validate(
        **{
            "path": str(path),
            "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
            "version": "123",
            "shell_version": "GNOME Shell 999.2",
            **overrides,
        }
    )


def test_compatible_pinned_archive_is_read_only(tmp_path):
    """Inspection returns metadata without extracting or changing the artifact."""
    path = archive_fixture(tmp_path)
    before = path.read_bytes()
    assert validate(path)["version"] == 123
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"checksum": "0" * 64}, "checksum"),
        ({"version": "124"}, "version"),
        ({"shell_version": "GNOME Shell 998.1"}, "does not support"),
    ],
)
def test_wrong_pin_or_unsupported_shell_fails(tmp_path, override, error):
    """A pin change or Shell upgrade requires a compatible reviewed artifact."""
    with pytest.raises(ValueError, match=error):
        validate(archive_fixture(tmp_path), **override)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "folder/../../escape", "folder\\escape", "symlink"])
def test_unsafe_archive_members_fail(tmp_path, name):
    """Even checksum-matching inputs must not escape the installation directory."""
    path = archive_fixture(tmp_path)
    with zipfile.ZipFile(path, "a") as archive:
        member = zipfile.ZipInfo(name)
        if name == "symlink":
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(member, "outside")
    with pytest.raises(ValueError, match="unsafe"):
        validate(path)


def test_other_extension_identity_fails(tmp_path):
    """A different extension cannot satisfy the clipboard contract."""
    with pytest.raises(ValueError, match="identity"):
        validate(archive_fixture(tmp_path, uuid="other@example.test"))
