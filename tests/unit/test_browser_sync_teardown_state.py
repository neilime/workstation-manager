"""Preserve captured recovery state across interrupted E2E device teardown."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

MODULE_PATH = Path(__file__).parents[2] / "e2e-tests/browser_sync_teardown_state.py"
SPEC = importlib.util.spec_from_file_location("browser_sync_teardown_state", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
teardown_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(teardown_state)


@pytest.fixture(name="captured_profile")
def make_captured_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """Provide one captured tracker beside another profile that teardown cannot copy."""

    root = tmp_path / "browser"
    profile = root / "Profile 2"
    profile.mkdir(parents=True)
    (profile / "Preferences").write_text('{"captured": "encrypted-seed"}')
    tracker = profile / "Sync Data"
    tracker.mkdir()
    (tracker / "state").write_text("captured-guid-and-tracker")
    (profile / "tracker-link").symlink_to("Sync Data/state")
    (root / "Local State").write_text('{"os_crypt": {"encrypted_key": "private-key"}}')
    (root / "Everyday").mkdir()
    (root / "Everyday" / "Preferences").write_text('{"untracked": true}')
    state_directory = tmp_path / "state"
    state_directory.mkdir()
    monkeypatch.setattr(teardown_state, "browser_processes", lambda _root: [])
    return root, profile, state_directory


def test_teardown_clone_contains_only_the_captured_profile_and_root_encryption_state(captured_profile) -> None:
    """The private browser root preserves encryption and tracker files without other profiles."""

    root, profile, state_directory = captured_profile
    with teardown_state.teardown_profile(root, profile, state_directory) as copied:
        assert copied.parent.stat().st_mode & 0o777 == 0o700
        assert {path.name for path in copied.parent.iterdir()} == {profile.name, "Local State"}
        assert (copied.parent / "Local State").read_bytes() == (root / "Local State").read_bytes()
        assert (copied / "Preferences").read_bytes() == (profile / "Preferences").read_bytes()
        assert (copied / "Preferences").stat().st_ino != (profile / "Preferences").stat().st_ino
        assert (copied / "Sync Data" / "state").read_text() == "captured-guid-and-tracker"
        assert (copied / "tracker-link").is_symlink()
        assert (copied / "tracker-link").readlink() == Path("Sync Data/state")
    assert not copied.parent.exists()
    assert (root / "Everyday" / "Preferences").read_text() == '{"untracked": true}'


def test_interrupted_reset_cannot_destroy_the_original_profile_or_next_attempt(captured_profile) -> None:
    """Clearing a disposable profile before a protocol failure leaves a reusable exact snapshot."""

    root, profile, state_directory = captured_profile
    preferences = (profile / "Preferences").read_bytes()
    local_state = (root / "Local State").read_bytes()
    with (
        pytest.raises(RuntimeError, match="Protocol disconnected"),
        teardown_state.teardown_profile(root, profile, state_directory) as copied,
    ):
        (copied / "Preferences").write_text("{}")
        (copied / "Sync Data" / "state").unlink()
        (copied.parent / "Local State").write_text("{}")
        raise RuntimeError("Protocol disconnected")
    assert not copied.parent.exists()
    assert (profile / "Preferences").read_bytes() == preferences
    assert (root / "Local State").read_bytes() == local_state
    with teardown_state.teardown_profile(root, profile, state_directory) as retried:
        assert (retried / "Preferences").read_bytes() == preferences
        assert (retried / "Sync Data" / "state").read_text() == "captured-guid-and-tracker"
        assert (retried.parent / "Local State").read_bytes() == local_state


def test_teardown_clone_allows_absent_root_encryption_state(captured_profile) -> None:
    """A profile without root-scoped Local State can still be isolated."""

    root, profile, state_directory = captured_profile
    (root / "Local State").unlink()
    with teardown_state.teardown_profile(root, profile, state_directory) as copied:
        assert {path.name for path in copied.parent.iterdir()} == {profile.name}


@pytest.mark.parametrize("failed", [False, True])
def test_teardown_retains_the_private_copy_while_its_browser_is_running(
    captured_profile, failed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed shutdown cannot remove a live browser's files or report completed teardown."""

    root, profile, state_directory = captured_profile
    monkeypatch.setattr(teardown_state, "browser_processes", lambda _root: [123])
    expected_error = RuntimeError if failed else ValueError
    message = "Protocol disconnected" if failed else "still running"
    with (
        pytest.raises(expected_error, match=message),
        teardown_state.teardown_profile(root, profile, state_directory) as copied,
    ):
        if failed:
            raise RuntimeError("Protocol disconnected")
    assert copied.exists()
    assert copied.parent.stat().st_mode & 0o777 == 0o700
    assert (profile / "Preferences").read_text() == '{"captured": "encrypted-seed"}'


@pytest.mark.parametrize("linked", ["root", "profile", "Preferences", "Local State", "state_directory"])
def test_teardown_clone_rejects_linked_fixture_boundaries(captured_profile, linked: str) -> None:
    """A linked identity, encryption state, or browser root cannot authorize a clone."""

    root, profile, state_directory = captured_profile
    selected = {
        "root": root,
        "profile": profile,
        "Preferences": profile / "Preferences",
        "Local State": root / "Local State",
        "state_directory": state_directory,
    }[linked]
    original = selected.with_name(selected.name + "-original")
    selected.rename(original)
    selected.symlink_to(original)
    with (
        pytest.raises(ValueError, match="linked browser fixture"),
        teardown_state.teardown_profile(root, profile, state_directory),
    ):
        pytest.fail("Linked fixture was copied")


def test_teardown_clone_rejects_profiles_outside_the_owned_root(captured_profile) -> None:
    """Only a direct profile child of the captured browser root may be copied."""

    root, profile, state_directory = captured_profile
    with (
        pytest.raises(ValueError, match="directly inside"),
        teardown_state.teardown_profile(root, profile / "nested", state_directory),
    ):
        pytest.fail("Unowned profile was copied")


@pytest.mark.parametrize("absolute", [False, True])
def test_teardown_clone_rejects_links_that_could_mutate_original_data(captured_profile, absolute: bool) -> None:
    """Preserved links must stay inside the disposable copy when the browser follows them."""

    root, profile, state_directory = captured_profile
    target = profile / "Sync Data" / "state" if absolute else Path("../Everyday/Preferences")
    (profile / "external-link").symlink_to(target)
    with (
        pytest.raises(ValueError, match="link outside"),
        teardown_state.teardown_profile(root, profile, state_directory),
    ):
        pytest.fail("A writable link escaped the disposable copy")


def test_private_manifest_updates_replace_complete_json_with_private_permissions(tmp_path: Path) -> None:
    """Confirmed fixture state is published completely with restricted permissions."""

    manifest = tmp_path / "fixture.json"
    manifest.write_text('{"devices": {"Default": "captured"}}')
    manifest.chmod(0o644)
    teardown_state.write_private_json(manifest, {"devices": {}})
    assert json.loads(manifest.read_text()) == {"devices": {}}
    assert manifest.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [manifest]


def test_failed_manifest_publication_preserves_the_previous_ownership_record(tmp_path: Path) -> None:
    """Failure before atomic replacement leaves a complete original record for the next attempt."""

    manifest = tmp_path / "fixture.json"
    original = '{"devices": {"Default": "captured"}}'
    manifest.write_text(original)
    with (
        mock.patch.object(teardown_state.os, "replace", side_effect=OSError("Write failed")),
        pytest.raises(OSError, match="Write failed"),
    ):
        teardown_state.write_private_json(manifest, {"devices": {}})
    assert manifest.read_text() == original
    assert list(tmp_path.iterdir()) == [manifest]


def test_private_manifest_writer_rejects_linked_records(tmp_path: Path) -> None:
    """A linked manifest never overwrites another file or becomes a fixture ownership record."""

    other = tmp_path / "other.json"
    other.write_text('{"unrelated": true}')
    manifest = tmp_path / "fixture.json"
    manifest.symlink_to(other)
    with pytest.raises(ValueError, match="linked browser fixture"):
        teardown_state.write_private_json(manifest, {"devices": {}})
    assert manifest.is_symlink()
    assert json.loads(other.read_text()) == {"unrelated": True}
