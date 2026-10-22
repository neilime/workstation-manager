"""End-to-end checks for the completed backup phase's immutable artifacts."""

import json
from types import MappingProxyType

import pytest

BACKUP_ROOT = "/tmp/workstation-manager-e2e-backup"


@pytest.fixture(name="backup_paths", scope="module")
def backup_paths_fixture(host):
    """Discover the completed backup once before setup starts its separate phase."""
    archives = host.check_output(
        "find %s -maxdepth 1 -type f -name %s", BACKUP_ROOT, "workstation-manager-backup-*.tar.gz"
    ).splitlines()
    assert len(archives) == 1, f"Expected one completed backup archive in {BACKUP_ROOT}, found {archives}"
    archive_path = archives[0]
    basename = archive_path.removesuffix(".tar.gz")
    paths = {
        "archive": archive_path,
        "manifest": basename + ".manifest.txt",
        "git_inventory": basename + ".git-repositories.json",
        "restore_command": basename + ".restore-command.txt",
        "browser_export": basename + ".browser-profiles.json",
    }
    for artifact in ("archive", "manifest", "git_inventory", "restore_command"):
        path = paths[artifact]
        assert host.file(path).is_file, f"Required backup {artifact} is missing or is not a regular file: {path}"
    return MappingProxyType(paths)


@pytest.fixture(name="backup_manifest", scope="module")
def backup_manifest_fixture(host, backup_paths):
    """Share the manifest's immutable records across its independent safety checks."""
    return tuple(host.file(backup_paths["manifest"]).content_string.splitlines())


@pytest.fixture(name="backup_git_inventory", scope="module")
def backup_git_inventory_fixture(host, backup_paths):
    """Read Git recovery fields once without sharing mutable parsed records."""
    repositories = json.loads(host.file(backup_paths["git_inventory"]).content_string)
    fields = ("relative_path", "primary_remote_name", "primary_remote_url", "branch")
    return tuple(MappingProxyType({field: repository[field] for field in fields}) for repository in repositories)


def test_backup_outputs_are_owned_by_the_managed_user(host, backup_paths) -> None:
    """Elevating the controller must not create root-owned recovery artifacts."""
    expected_user = host.check_output("id -un")
    paths = [
        BACKUP_ROOT,
        *(backup_paths[artifact] for artifact in ("archive", "manifest", "git_inventory", "restore_command")),
    ]
    for path in paths:
        assert host.file(path).user == expected_user, f"Backup output is not owned by {expected_user}: {path}"


def test_backup_manifest_records_expected_entries(backup_paths, backup_manifest) -> None:
    """The backup manifest should reflect the generated archive and core inputs."""
    expected = (
        f"archive\t{backup_paths['archive']}",
        "dry_run\t0",
        f"export\tgit-repositories\t{backup_paths['git_inventory']}",
        f"export\trestore-command\t{backup_paths['restore_command']}",
    )
    for record in expected:
        assert record in backup_manifest, f"Missing backup manifest record: {record}"


def test_backup_restore_command_matches_the_generated_archive(host, backup_paths) -> None:
    """The restore-command sidecar should be ready to paste on another machine."""
    restore_file = host.file(backup_paths["restore_command"])
    restore_command = restore_file.content_string
    assert restore_command.startswith("wget -qO- https://raw.githubusercontent.com/")
    assert restore_file.mode == 0o600
    assert restore_command.endswith(f"WORKSTATION_MANAGER_RESTORE_ARCHIVE={backup_paths['archive']} sh -s -- setup\n")


def test_backup_browser_export_matches_manifest(host, backup_paths, backup_manifest) -> None:
    """A generated browser sidecar must have exactly one matching manifest record."""
    browser_export_path = backup_paths["browser_export"]
    browser_export = host.file(browser_export_path)
    present = browser_export.exists
    export_lines = [line for line in backup_manifest if line.startswith("export\tbrowser-profiles\t")]
    assert export_lines == ([f"export\tbrowser-profiles\t{browser_export_path}"] if present else [])
    if present:
        assert browser_export.is_file
        assert browser_export.mode == 0o600
        assert browser_export.user == host.check_output("id -un")


def test_backup_verifies_recovery_without_skips(backup_manifest) -> None:
    """Prepared recovery sources must pass the normal noninteractive checks."""
    assert not any("recovery_skipped\t" in record for record in backup_manifest)
    assert not any("recovery_status\tincomplete" in record for record in backup_manifest)


def test_backup_exports_git_inventory_for_dev_projects(backup_git_inventory) -> None:
    """The backup flow should record Git remotes and branch state for dev-projects."""
    assert {
        "relative_path": "client-restore",
        "primary_remote_name": "origin",
        "primary_remote_url": "/tmp/workstation-manager-e2e-origin-client-restore.git",
        "branch": "main",
    } in backup_git_inventory


def test_backup_omits_ignored_dependency_repositories(backup_git_inventory) -> None:
    """The dependency fixture must stay outside the project recovery inventory."""
    assert not any(
        repository["relative_path"].startswith("client-restore/tools/vendor/") for repository in backup_git_inventory
    )


def test_backup_archive_omits_git_ignored_files_and_keeps_local_edits(host, backup_paths) -> None:
    """Project recovery should retain source edits without ignored dependencies or secrets."""
    archive_path = backup_paths["archive"]
    members = host.check_output("tar -tzf %s", archive_path).splitlines()
    assert not any("/.git/" in name or name.endswith("/.git") for name in members)
    assert not any("/tools/vendor/" in name or name.endswith(".private") for name in members)
    prefix = "Documents/dev-projects/client-restore/"
    assert prefix + "local-note.txt" in members
    assert host.check_output("tar -xOzf %s %s", archive_path, prefix + "tracked.txt") == "remote-base\nlocal-change"
    assert host.file(archive_path).mode == 0o600
