"""Exercise both metadata directions without contacting a vault or using real profiles."""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_profile_sync as sync,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.bitwarden_browser_profiles import (
    bitwarden_browser_profiles,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_seed import (
    seed_browser_profiles,
)

ITEM_ID = "11111111-1111-4111-8111-111111111111"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z/D/PwAG/gL+DHWJ3gAAAABJRU5ErkJggg=="
)


class MemoryVault(sync.BrowserVault):
    """Preserve complete records while modeling authenticated item and attachment operations."""

    def __init__(self) -> None:
        super().__init__("fixture-session", "fixture-collection", Mock())
        fields = [
            {"name": "id", "value": "fixture"},
            {"name": "directory", "value": "Default"},
            {"name": "theme_colors", "value": "#123456, #ABCDEF"},
            {"name": "unrelated", "value": "keep-me"},
        ]
        self.record: dict = {
            "id": ITEM_ID,
            "name": "Remote",
            "type": 2,
            "notes": "synthetic-recovery-note",
            "collectionIds": ["fixture-collection"],
            "fields": fields,
            "attachments": [],
        }
        self.attachments: dict[str, bytes] = {}
        self.calls: list[tuple[str, ...]] = []
        self.corrupt = False
        self.fail_upload = False

    def item(self, _item_id: str) -> dict:
        """Return a detached snapshot like the CLI does."""

        return copy.deepcopy(self.record)

    def run(self, *arguments: str, data: bytes | None = None) -> bytes:
        """Implement only the documented operations required by profile synchronization."""

        self.calls.append(arguments)
        if arguments == ("status",):
            return b'{"status":"unlocked"}'

        if arguments == ("encode",):
            assert data is not None
            return base64.b64encode(data)
        if arguments[:2] == ("edit", "item"):
            assert data is not None
            self.record = json.loads(base64.b64decode(data))
            if self.corrupt:
                self.record["notes"] = "unexpected-change"
            return json.dumps(self.record).encode()
        if arguments[:2] == ("create", "attachment"):
            if self.fail_upload:
                raise ValueError("Fixture upload failed")
            self.attachments["new"] = Path(arguments[3]).read_bytes()
            self.record["attachments"].append({"id": "new", "fileName": "avatar.png"})
            return b"{}"
        if arguments[:2] == ("get", "attachment"):
            return self.attachments[arguments[2]]
        if arguments[:2] == ("delete", "attachment"):
            self.record["attachments"] = [entry for entry in self.record["attachments"] if entry["id"] != arguments[2]]
        elif arguments != ("sync",):
            raise AssertionError(arguments)
        return b""


@pytest.fixture(name="fixture")
def browser_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, MemoryVault, list[dict]]:
    """Create deliberately drifted names/colors while retaining synthetic browsing data."""

    monkeypatch.setattr(sync, "_brave_running", lambda: False)
    vault = MemoryVault()
    profiles = [dict(profile) for profile in bitwarden_browser_profiles([vault.record])]
    seed_browser_profiles(str(tmp_path), [{**profiles[0], "label": "Local", "theme_colors": ["#654321"]}])
    path = tmp_path / "Default/Preferences"
    preferences = json.loads(path.read_text())
    preferences.update(pinned_tabs=[{"url": "https://example.invalid"}], brave_sync_v2={"seed": "synthetic-seed"})
    path.write_text(json.dumps(preferences))
    return tmp_path, vault, profiles


def test_remote_sync_restores_metadata_and_preserves_browser_data(fixture: tuple) -> None:
    """Remote direction may rename existing profiles only after explicit selection."""

    root, vault, profiles = fixture
    before = (root / "Default/Preferences").read_bytes()
    assert sync.sync_browser_profiles(str(root), profiles, "restore", vault, check_mode=True)
    assert (root / "Default/Preferences").read_bytes() == before
    assert sync.sync_browser_profiles(str(root), profiles, "restore", vault)
    preferences = json.loads((root / "Default/Preferences").read_text())
    assert preferences["profile"]["name"] == "Remote"
    assert preferences["brave_sync_v2"]["seed"] == "synthetic-seed"
    assert preferences["pinned_tabs"] == [{"url": "https://example.invalid"}]
    assert sync.inspect_browser_profiles(str(root), profiles)["drift"] == []
    assert not vault.calls
    assert not sync.sync_browser_profiles(str(root), profiles, "restore", vault)


def test_restore_supports_default_profile_directory(fixture: tuple) -> None:
    """Selecting metadata repairs retains normalized IDs and optional directory defaults."""

    root, vault, _profiles = fixture
    profiles = [{"id": " fixture ", "label": "Remote", "item_id": ITEM_ID}]
    assert sync.sync_browser_profiles(str(root), profiles, "restore", vault)
    preferences = json.loads((root / "managed-fixture/Preferences").read_text())
    assert preferences["profile"]["name"] == "Remote"
    assert not sync.sync_browser_profiles(str(root), profiles, "restore", vault)
    assert not vault.calls


def test_local_sync_preserves_recovery_words_fields_and_secondary_colors(fixture: tuple) -> None:
    """Local direction changes only approved managed metadata and verifies complete note retention."""

    root, vault, profiles = fixture
    before = (root / "Default/Preferences").read_bytes()
    assert sync.sync_browser_profiles(str(root), profiles, "save", vault, check_mode=True)
    assert not vault.calls
    assert sync.sync_browser_profiles(str(root), profiles, "save", vault)
    assert vault.record["name"] == "Local"
    assert vault.record["notes"] == "synthetic-recovery-note"
    fields = {field["name"]: field["value"] for field in vault.record["fields"]}
    assert fields["theme_colors"] == "#654321, #ABCDEF"
    assert fields["unrelated"] == "keep-me"
    assert (root / "Default/Preferences").read_bytes() == before
    assert not sync.inspect_browser_profiles(
        str(root), [dict(profile) for profile in bitwarden_browser_profiles([vault.record])]
    )["drift"]


def test_failed_save_verification_stops_synchronization(fixture: tuple) -> None:
    """Successful CLI execution cannot hide an unexpected change to the saved recovery note."""

    root, vault, profiles = fixture
    vault.corrupt = True
    with pytest.raises(ValueError, match="metadata verification failed"):
        sync.sync_browser_profiles(str(root), profiles, "save", vault)


@pytest.mark.parametrize("direction", ["save", "restore"])
def test_running_browser_blocks_both_directions(fixture: tuple, direction: str) -> None:
    """Unflushed preferences cannot be treated as authoritative local metadata."""

    root, vault, profiles = fixture
    (root / "SingletonLock").symlink_to("fixture-lock")
    with pytest.raises(ValueError, match="Close Brave"):
        sync.sync_browser_profiles(str(root), profiles, direction, vault)
    assert not vault.calls


def test_sync_pairing_and_unrecorded_profiles_are_not_guessed() -> None:
    """Directions cannot manufacture recovery words or claim chain enrollment."""

    assert sync.browser_sync_directions({"drift": [{"kind": "undeclared"}], "sync_issues": [{}]}) == {}
    assert list(sync.browser_sync_directions({"drift": [{"kind": "missing", "id": "missing"}]})) == ["restore"]


def test_missing_local_profile_does_not_delete_remote_record(fixture: tuple) -> None:
    """An absent local profile is restored only by selecting the remote direction."""

    root, vault, profiles = fixture
    extra = {**profiles[0], "id": "other", "directory": "Profile 2", "item_id": "22222222-2222-4222-8222-222222222222"}
    assert sync.sync_browser_profiles(str(root), [*profiles, extra], "save", vault)
    assert vault.record["id"] == ITEM_ID
    assert not (root / "Profile 2").exists()
    assert sync.sync_browser_profiles(str(root), [*profiles, extra], "restore", vault)
    assert (root / "Profile 2/Preferences").exists()


@pytest.mark.parametrize("fail_upload", [False, True])
def test_avatar_replacement_is_verified_before_old_attachment_removal(fixture: tuple, fail_upload: bool) -> None:
    """A failed new attachment cannot destroy the previous recoverable logo."""

    root, vault, profiles = fixture
    vault.record["attachments"] = [{"id": "old", "fileName": "avatar.png"}]
    vault.attachments["old"] = PNG
    vault.fail_upload = fail_upload
    profiles[0]["avatar_png"] = base64.b64encode(PNG).decode()
    # Seed a valid local logo, then simulate a different stored image without reading secrets.
    seed_browser_profiles(str(root), profiles)
    observed = sync.inspect_browser_profiles(str(root), profiles)["profiles"][0]
    if fail_upload:
        with pytest.raises(ValueError, match="upload failed"):
            sync._save_local_profile(vault, root, profiles[0], observed, {"avatar"})  # pylint: disable=protected-access
        assert vault.record["attachments"] == [{"id": "old", "fileName": "avatar.png"}]
    else:
        sync._save_local_profile(vault, root, profiles[0], observed, {"avatar"})  # pylint: disable=protected-access
        assert vault.record["attachments"] == [{"id": "new", "fileName": "avatar.png"}]
        assert vault.attachments["new"] == PNG


def test_local_sync_restores_a_palette_removed_from_the_remote_record_during_the_prompt(fixture: tuple) -> None:
    """A fresh vault record can omit a previously managed optional field without losing the chosen local value."""

    root, vault, profiles = fixture
    vault.record["fields"] = [field for field in vault.record["fields"] if field["name"] != "theme_colors"]
    vault.record["attachments"] = None
    assert sync.sync_browser_profiles(str(root), profiles, "save", vault)
    fields = {field["name"]: field["value"] for field in vault.record["fields"]}
    assert fields["theme_colors"] == "#654321"
    assert vault.record["notes"] == "synthetic-recovery-note"


def test_moved_remote_record_is_not_updated_outside_its_approved_collection(fixture: tuple) -> None:
    """Approval applies to the configured recovery source even if the vault changes during the prompt."""

    root, vault, profiles = fixture
    vault.record["collectionIds"] = ["other-collection"]
    with pytest.raises(ValueError, match="left its recovery collection"):
        sync.sync_browser_profiles(str(root), profiles, "save", vault)
    assert not any(call[0] in {"edit", "create", "delete"} for call in vault.calls)


@pytest.fixture(name="sync_only")
def sync_only_fixture(fixture: tuple) -> tuple:
    """Keep profile metadata synchronized while explicitly disabling Sync everything."""

    root, vault, profiles = fixture
    seed_browser_profiles(str(root), profiles, replace_names=True)
    path = root / "Default/Preferences"
    preferences = json.loads(path.read_text())
    preferences["sync"] = {"keep_everything_synced": False, "bookmarks": False, "has_setup_completed": True}
    path.write_text(json.dumps(preferences))
    return root, vault, profiles


def test_sync_only_restore_is_explicit_verified_and_idempotent(sync_only: tuple) -> None:
    """A disabled setting offers restore and changes only that setting without a vault write."""

    root, vault, profiles = sync_only
    path = root / "Default/Preferences"
    before = path.read_bytes()
    inspection = sync.inspect_browser_profiles(str(root), profiles)
    assert inspection["drift"] == []
    assert sync.browser_sync_directions(inspection) == {"restore": "Close Brave, then enable Sync everything."}
    assert sync.sync_browser_profiles(str(root), profiles, "restore", vault, check_mode=True)
    assert path.read_bytes() == before
    assert not sync.sync_browser_profiles(str(root), profiles, "save", vault)
    assert path.read_bytes() == before
    assert sync.sync_browser_profiles(str(root), profiles, "restore", vault)
    expected = json.loads(before)
    expected["sync"]["keep_everything_synced"] = True
    assert json.loads(path.read_text()) == expected
    assert path.stat().st_mode & 0o777 == 0o600
    assert sync.inspect_browser_profiles(str(root), profiles)["sync_issues"] == []
    assert not sync.sync_browser_profiles(str(root), profiles, "restore", vault)
    assert not vault.calls


def test_setup_still_preserves_disabled_sync_everything(sync_only: tuple) -> None:
    """Normal setup must not inherit approval from backup's explicit restore action."""

    root, _vault, profiles = sync_only
    path = root / "Default/Preferences"
    before = path.read_bytes()
    assert not seed_browser_profiles(str(root), profiles)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value,issue",
    [
        ("requested", False, "sync_not_requested"),
        ("has_setup_completed", False, "sync_setup_incomplete"),
        ("managed", True, "sync_disabled_by_policy"),
        ("seed", "", "missing_sync_seed"),
    ],
)
def test_sync_restore_does_not_invent_pairing_or_bypass_manual_checks(
    sync_only: tuple, field: str, value: object, issue: str
) -> None:
    """Restoring the selection flag must leave missing pairing, setup, and policy failures visible."""

    root, vault, profiles = sync_only
    path = root / "Default/Preferences"
    before = json.loads(path.read_text())
    before["brave_sync_v2" if field == "seed" else "sync"][field] = value
    path.write_text(json.dumps(before))
    assert sync.sync_browser_profiles(str(root), profiles, "restore", vault)
    before["sync"]["keep_everything_synced"] = True
    assert json.loads(path.read_text()) == before
    inspection = sync.inspect_browser_profiles(str(root), profiles)
    assert inspection["sync_issues"] == [{"directory": "Default", "issues": [issue]}]
    assert sync.browser_sync_directions(inspection) == {}


@pytest.mark.parametrize("guard", ["lock", "process", "symlink"])
def test_sync_only_restore_respects_browser_and_path_guards(
    sync_only: tuple, monkeypatch: pytest.MonkeyPatch, guard: str
) -> None:
    """The new repair cannot bypass protections used for other profile writes."""

    root, vault, profiles = sync_only
    path = root / "Default/Preferences"
    before = path.read_bytes()
    if guard == "lock":
        (root / "SingletonLock").symlink_to("fixture-lock")
    elif guard == "process":
        monkeypatch.setattr(sync, "_brave_running", lambda: True)
    else:
        outside = root / "outside"
        path.rename(outside)
        path.symlink_to(outside)
    with pytest.raises(ValueError, match="Close Brave|symlink"):
        sync.sync_browser_profiles(str(root), profiles, "restore", vault)
    assert path.read_bytes() == before
    assert not vault.calls


def test_sync_restore_verification_failure_stops_backup(sync_only: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """A claimed write cannot conceal a disabled setting that survives the restore."""

    root, vault, profiles = sync_only
    monkeypatch.setattr(sync, "_write_file", lambda *_args, **_kwargs: None)
    with pytest.raises(ValueError, match="settings verification failed"):
        sync.sync_browser_profiles(str(root), profiles, "restore", vault)


def test_sync_restore_does_not_change_undeclared_profiles(sync_only: tuple) -> None:
    """Profiles outside the configured recovery collection retain their own Sync choices."""

    root, vault, profiles = sync_only
    other = root / "Profile 9/Preferences"
    other.parent.mkdir()
    other.write_text('{"sync":{"keep_everything_synced":false}}')
    before = other.read_bytes()
    assert sync.sync_browser_profiles(str(root), profiles, "restore", vault)
    assert other.read_bytes() == before
    inspection = sync.inspect_browser_profiles(str(root), profiles)
    assert sync.browser_sync_directions(inspection) == {}
    assert any(record["directory"] == "Profile 9" for record in inspection["sync_issues"])
