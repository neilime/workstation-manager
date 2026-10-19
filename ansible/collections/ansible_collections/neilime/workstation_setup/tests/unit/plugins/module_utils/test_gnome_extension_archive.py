"""Reject incompatible or unsafe managed GNOME extension artifacts before installation."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.clipboard_archive import (
    ClipboardArchive,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.gnome_extension_archive import (
    GnomeExtensionArchive,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.system_monitor_archive import (
    SystemMonitorArchive,
)

IDENTITY = ("synthetic@example.test", "Synthetic Extension")


def archive_fixture(tmp_path, **metadata):
    """Create a synthetic extension, independent of the maintained release pin."""
    path = tmp_path / "extension.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "metadata.json",
            json.dumps({"uuid": IDENTITY[0], "version": 123, "shell-version": ["999"], **metadata}),
        )
        archive.writestr("extension.js", "// synthetic extension")
    return path


def archive_arguments(path, **overrides):
    """Build synthetic pins independent of maintained releases and the installed Shell."""
    return {
        "path": str(path),
        "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
        "version": "123",
        "shell_version": "GNOME Shell 999.2",
        **overrides,
    }


def validate(path, **overrides):
    """Exercise the common archive safety contract with a synthetic extension."""
    return GnomeExtensionArchive.validate(**archive_arguments(path, **overrides), identity=IDENTITY)


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
    """An artifact must belong to the configured extension."""
    with pytest.raises(ValueError, match="identity"):
        validate(archive_fixture(tmp_path, uuid="other@example.test"))


@pytest.mark.parametrize(
    ("validator", "uuid"),
    [
        pytest.param(ClipboardArchive, "clipboard-indicator@tudmotu.com", id="clipboard"),
        pytest.param(SystemMonitorArchive, "Vitals@CoreCoding.com", id="system-monitor"),
    ],
)
def test_managed_extension_adapter_requires_its_identity(tmp_path, validator, uuid):
    """Each managed adapter accepts its own extension and rejects other artifacts."""
    path = archive_fixture(tmp_path, uuid=uuid)
    assert validator.validate(**archive_arguments(path))["uuid"] == uuid
    with pytest.raises(ValueError, match="identity"):
        validator.validate(**archive_arguments(archive_fixture(tmp_path)))
