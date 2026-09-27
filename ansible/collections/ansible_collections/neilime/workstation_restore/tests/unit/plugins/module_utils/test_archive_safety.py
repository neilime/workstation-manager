"""Tests protecting archive restoration before any target mutation."""

from __future__ import annotations

import io
import tarfile

import pytest
from ansible_collections.neilime.workstation_restore.plugins.module_utils.archive_safety import (
    validate_archive,
)


def make_archive(tmp_path, members):
    """Create small synthetic archives without touching a real home directory."""

    archive_path = tmp_path / "recovery.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for member in members:
            if member.isfile():
                member.size = 4
                archive.addfile(member, io.BytesIO(b"data"))
            else:
                archive.addfile(member)
    return str(archive_path)


def test_general_archive_keeps_home_relative_paths(tmp_path) -> None:
    """Any selected home-relative files, including browser data, remain compatible."""

    members = [
        tarfile.TarInfo(name)
        for name in [
            ".config/workstation-manager/config.json",
            ".config/BraveSoftware/Brave-Browser/Default/Bookmarks",
            "Documents/dev-projects/project/notes.txt",
            "Documents/dev-projects/project/README.md",
        ]
    ]
    assert validate_archive(make_archive(tmp_path, members), str(tmp_path / "home")) == 4


@pytest.mark.parametrize("name", ["/etc/passwd", "../outside", ".config/../../outside"])
def test_archive_rejects_traversal(tmp_path, name: str) -> None:
    """No archive name can resolve outside the target home."""

    with pytest.raises(ValueError, match="unsafe archive member path"):
        validate_archive(make_archive(tmp_path, [tarfile.TarInfo(name)]), str(tmp_path / "home"))


@pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
@pytest.mark.parametrize("link_target", ["/tmp/outside", "../outside"])
def test_archive_rejects_links_outside_home(tmp_path, link_type, link_target: str) -> None:
    """Both symbolic and hard links are validated."""

    member = tarfile.TarInfo("link")
    member.type = link_type
    member.linkname = link_target
    with pytest.raises(ValueError, match="archive link"):
        validate_archive(make_archive(tmp_path, [member]), str(tmp_path / "home"))


def test_archive_rejects_members_below_archived_symlink(tmp_path) -> None:
    """A later entry cannot exploit an earlier symlink, even within the home."""

    link = tarfile.TarInfo("directory")
    link.type = tarfile.SYMTYPE
    link.linkname = "other"
    with pytest.raises(ValueError, match="archived symlink"):
        validate_archive(make_archive(tmp_path, [link, tarfile.TarInfo("directory/file")]), str(tmp_path / "home"))


def test_archive_rejects_existing_target_symlink_escape(tmp_path) -> None:
    """Existing filesystem aliases must not redirect restored files outside home."""

    home = tmp_path / "home"
    home.mkdir()
    (home / "redirect").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes the target home"):
        validate_archive(make_archive(tmp_path, [tarfile.TarInfo("redirect/file")]), str(home))


def test_archive_rejects_special_files(tmp_path) -> None:
    """Recovery archives must not create device files or FIFOs."""

    member = tarfile.TarInfo("pipe")
    member.type = tarfile.FIFOTYPE
    with pytest.raises(ValueError, match="special archive file"):
        validate_archive(make_archive(tmp_path, [member]), str(tmp_path / "home"))


def test_archive_accepts_safe_relative_link(tmp_path) -> None:
    """Normal project symlinks within the restored tree remain supported."""

    member = tarfile.TarInfo("project/link")
    member.type = tarfile.SYMTYPE
    member.linkname = "file"
    assert (
        validate_archive(make_archive(tmp_path, [tarfile.TarInfo("project/file"), member]), str(tmp_path / "home")) == 2
    )


def test_restore_allows_shared_config_parent_directory(tmp_path) -> None:
    """General config archives can retain their normal parent directories."""

    directory = tarfile.TarInfo(".config")
    directory.type = tarfile.DIRTYPE
    assert (
        validate_archive(
            make_archive(tmp_path, [directory, tarfile.TarInfo(".config/workstation-manager/config")]),
            str(tmp_path / "home"),
        )
        == 2
    )
