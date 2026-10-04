"""Verify archive root reconstruction and validation before extraction."""

from __future__ import annotations

import io
import tarfile

import pytest
from ansible_collections.neilime.workstation_restore.plugins.module_utils.restore_planning import (
    ArchiveRestorePlanner,
)


def make_plan(tmp_path, names, manifest=None):
    """Inspect synthetic file-only archives against a fresh home."""

    archive_path = tmp_path / "backup.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in names:
            member = tarfile.TarInfo(name)
            if name.endswith("/"):
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            else:
                member.size = 4
                archive.addfile(member, io.BytesIO(b"data"))
    manifest_path = None
    if manifest is not None:
        manifest_path = tmp_path / "backup.manifest.txt"
        manifest_path.write_text(manifest)
    return ArchiveRestorePlanner().build(
        str(archive_path), str(tmp_path / "home"), str(manifest_path) if manifest_path else None
    )


@pytest.mark.parametrize("prefix", ["", "Documents/"])
def test_manifest_distinguishes_shortened_and_home_relative_project_archives(tmp_path, prefix):
    """Missing source records identify the source home without changing a correct archive layout."""

    manifest = (
        "include\tdev-projects\t/home/source-user/Documents/dev-projects\n"
        "missing\tworkstation-manager-user-config\t/home/source-user/.config/workstation-manager\n"
    )
    result = make_plan(tmp_path, [prefix + "dev-projects/", prefix + "dev-projects/client/note.txt"], manifest)
    expected = tmp_path / "home" if prefix else tmp_path / "home/Documents"
    assert result["destination"] == str(expected)
    assert result["members"] == 2


def test_manifest_reconstructs_a_shortened_root_with_additional_document_sources(tmp_path):
    """Older project archives with extra sibling paths share the original Documents root."""

    manifest = (
        "include\tdev-projects\t/home/source-user/Documents/dev-projects\n"
        "missing\tworkstation-manager-user-config\t/home/source-user/.config/workstation-manager\n"
        "include\textra\t/home/source-user/Documents/notes\n"
    )
    result = make_plan(tmp_path, ["dev-projects/", "dev-projects/note.txt", "notes/", "notes/other.txt"], manifest)
    assert result["destination"] == str(tmp_path / "home/Documents")


def test_manifest_normalizes_source_paths_before_reconstructing_the_archive_root(tmp_path):
    """Recorded source paths may contain parent segments even though tar entry paths must not."""

    manifest = "include\tdev-projects\t/home/source-user/Documents/../Documents/dev-projects\n"
    result = make_plan(tmp_path, ["dev-projects/", "dev-projects/note.txt"], manifest)
    assert result["destination"] == str(tmp_path / "home/Documents")


def test_manifest_preserves_explicit_extra_directory_named_dev_projects(tmp_path):
    """A same-named extra path at the home root must not be mistaken for the default source."""

    manifest = (
        "missing\tdev-projects\t/home/source-user/Documents/dev-projects\n"
        "missing\tworkstation-manager-user-config\t/home/source-user/.config/workstation-manager\n"
        "include\textra\t/home/source-user/dev-projects\n"
    )
    result = make_plan(tmp_path, ["dev-projects/", "dev-projects/note.txt"], manifest)
    assert result["destination"] == str(tmp_path / "home")


@pytest.mark.parametrize(
    "name", ["notes/file.txt", "Documents/dev-projects/file.txt", ".config/workstation-manager/state"]
)
def test_general_archives_keep_their_home_relative_layout(tmp_path, name):
    """Ordinary archives retain all relative paths without heuristic remapping."""

    result = make_plan(tmp_path, [name])
    assert result["destination"] == str(tmp_path / "home")


@pytest.mark.parametrize("name", ["dev-projects/../../outside", "/dev-projects/file.txt"])
def test_planning_still_rejects_unsafe_entry_names(tmp_path, name):
    """Recognizing a shortened root must never bypass path traversal protection."""

    with pytest.raises(ValueError, match="unsafe archive member path"):
        make_plan(tmp_path, [name])
