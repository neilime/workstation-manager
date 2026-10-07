"""Verify Snap removal fails closed and preserves recoverable application data."""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.snap_removal import (
    SnapInventory,
    SnapRecoveryArchive,
    SnapRemoval,
)


@pytest.mark.parametrize("kind", ["kernel", "gadget", "unknown"])
def test_essential_or_unknown_snap_blocks_removal(kind: str) -> None:
    """A new or boot-critical snap type must never be treated as an optional app."""
    with pytest.raises(ValueError):
        SnapInventory.removal_groups({"on-classic": True}, [{"name": "platform", "type": kind}])


def test_non_classic_system_blocks_removal() -> None:
    """Ubuntu Core and an incomplete system probe cannot authorize removal."""
    for system in ({"on-classic": False}, {}, None):
        with pytest.raises(ValueError, match="essential"):
            SnapInventory.removal_groups(system, [])


def test_snap_removal_orders_and_deduplicates_revisions() -> None:
    """Applications are removed before bases, and snapd is removed last."""
    records = [
        {"name": "snapd", "type": "snapd"},
        {"name": "core24", "type": "base"},
        {"name": "example", "type": "app"},
        {"name": "example", "type": "app"},
    ]
    assert SnapInventory.removal_groups({"on-classic": True}, records) == [["example"], ["core24"], ["snapd"]]


def test_purge_includes_snap_launchers_and_preserves_native_app_packages() -> None:
    """Only Ubuntu transition packages depending on snapd belong to the purge."""
    installed = {
        "snapd": "installed\t\tlibc6",
        "gnome-software-plugin-snap": "config-files\t\t",
        "firefox": "installed\tdebconf, snapd (>= 2.0)\tdebconf",
        "thunderbird": "installed\t\tlibc6, libgtk-3-0",
    }

    def run(arguments):
        return (0, installed[arguments[-1]], "") if arguments[-1] in installed else (1, "", "not installed")

    assert SnapRemoval(run).installed_packages() == ["snapd", "gnome-software-plugin-snap", "firefox"]


def test_recovery_rejects_symlinks_and_bind_mounts(tmp_path: Path) -> None:
    """Cleanup cannot cross a redirected root or a mount boundary."""
    data = tmp_path / "snap"
    data.mkdir()
    redirected = tmp_path / "redirected"
    redirected.symlink_to(data)
    with pytest.raises(ValueError, match="redirected"):
        SnapRecoveryArchive.validate_paths([redirected], [])
    with pytest.raises(ValueError, match="mounted"):
        SnapRecoveryArchive.validate_paths([data], [data / "external-volume"])


def test_account_inventory_does_not_treat_the_snap_command_as_user_data(tmp_path: Path, monkeypatch) -> None:
    """The system bin account has /bin as its home, where snap is an executable."""
    homes = [tmp_path / name for name in ("bin", "user", "root")]
    for home in homes:
        home.mkdir()
    (homes[0] / "snap").write_text("snap executable fixture")
    (homes[1] / "snap").mkdir()
    (homes[2] / ".snap").mkdir()
    monkeypatch.setattr("pwd.getpwall", lambda: [SimpleNamespace(pw_dir=str(home)) for home in homes])
    assert SnapInventory.user_directories() == sorted([homes[1] / "snap", homes[2] / ".snap"])


@pytest.fixture(name="removal_fixture")
def make_removal_fixture(tmp_path: Path, monkeypatch):
    """Run real archive verification with all package and service operations isolated."""
    data = tmp_path / "snap"
    data.mkdir()
    (data / "document.txt").write_text("original user document\n")
    calls = []
    state = {"installed": True, "failure": ""}

    def run(arguments):
        calls.append(arguments)
        if arguments[0] == "tar":
            if arguments[1] == state["failure"]:
                return 1, "", "fixture archive failure"
            result = subprocess.run(arguments, capture_output=True, text=True, check=False)
            return result.returncode, result.stdout, result.stderr
        if arguments[:2] == ["apt-get", "--simulate"]:
            extra = "Remv unrelated-package\n" if state["failure"] == "dependency" else ""
            return 0, "Purg snapd\n" + extra, ""
        if arguments[:2] == ["apt-get", "--yes"]:
            state["installed"] = False
        if arguments[:2] == ["snap", "remove"] and state["failure"] == "remove":
            return 1, "", "fixture removal failure"
        return 0, "", ""

    removal = SnapRemoval(run)
    monkeypatch.setattr(
        removal, "inspect", lambda: [["example"], ["core24"], ["snapd"]] if state["installed"] else [[], [], []]
    )
    monkeypatch.setattr(removal, "installed_packages", lambda: ["snapd"] if state["installed"] else [])
    monkeypatch.setattr(removal, "require_closed_applications", lambda: None)
    monkeypatch.setattr(SnapInventory, "read", lambda _endpoint: [])
    monkeypatch.setattr(SnapInventory, "mounts", lambda: [])
    monkeypatch.setattr(SnapInventory, "user_directories", lambda: [data] if data.exists() else [])
    monkeypatch.setattr(SnapRemoval, "SYSTEM_PATHS", ())
    return removal, data, tmp_path / "recovery", calls, state


def test_check_mode_only_inspects(removal_fixture) -> None:
    """A preview may simulate APT resolution but cannot stop or remove anything."""
    removal, data, destination, calls, _state = removal_fixture
    assert removal.remove(str(destination), check_mode=True)["changed"]
    assert data.is_dir()
    assert not destination.exists()
    assert all(command[:2] == ["apt-get", "--simulate"] for command in calls)


@pytest.mark.parametrize("failure", ["--create", "--compare", "dependency"])
def test_failed_preservation_or_unrelated_removal_keeps_originals(removal_fixture, failure: str) -> None:
    """No snap or original user file is deleted when a prerequisite fails."""
    removal, data, destination, calls, state = removal_fixture
    state["failure"] = failure
    with pytest.raises(ValueError):
        removal.remove(str(destination), check_mode=False)
    assert (data / "document.txt").read_text() == "original user document\n"
    assert not any(command[:2] == ["snap", "remove"] for command in calls)


def test_removal_preserves_verified_archive_and_orders_packages(removal_fixture) -> None:
    """Successful removal retains original content outside the cleaned directories."""
    removal, data, destination, calls, _state = removal_fixture
    result = removal.remove(str(destination), check_mode=False)
    archive = Path(result["backup_archive"])
    assert not data.exists()
    assert archive.stat().st_mode & 0o777 == 0o600
    with tarfile.open(archive) as saved:
        member = saved.extractfile(str(data / "document.txt").lstrip("/"))
        assert member is not None
        assert member.read() == b"original user document\n"
    removed = [command[3:] for command in calls if command[:2] == ["snap", "remove"]]
    assert removed == [["example"], ["core24"], ["snapd"]]
    assert calls.index(next(command for command in calls if command[:2] == ["tar", "--compare"])) < calls.index(
        next(command for command in calls if command[:2] == ["snap", "remove"])
    )
    before = calls.copy()
    assert removal.remove(str(destination), check_mode=False) == {"changed": False, "backup_archive": ""}
    assert calls == before


def test_package_failure_retains_data_and_archive(removal_fixture) -> None:
    """An unsuccessful snap removal must not be followed by deleting residual data."""
    removal, data, destination, calls, state = removal_fixture
    state["failure"] = "remove"
    with pytest.raises(ValueError, match="removal failed"):
        removal.remove(str(destination), check_mode=False)
    assert data.exists()
    assert list(destination.glob("snap-*/data.tar"))
    assert not any(command[:2] == ["apt-get", "--yes"] for command in calls)


def test_recovery_directory_cannot_be_purged_with_snap_data(removal_fixture) -> None:
    """The only recovery copy must never be written under a directory being removed."""
    removal, data, _destination, _calls, _state = removal_fixture
    with pytest.raises(ValueError, match="outside"):
        removal.remove(str(data / "backup"), check_mode=False)
