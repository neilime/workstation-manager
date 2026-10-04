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
@pytest.mark.parametrize("link_target", ["../outside"])
def test_archive_rejects_links_outside_home(tmp_path, link_type, link_target: str) -> None:
    """Relative symbolic and hard links cannot escape the target home."""

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


def test_shortened_archive_checks_hard_links_against_the_extraction_directory(tmp_path) -> None:
    """A corrected Documents destination must not validate links against the wrong directory."""

    home = tmp_path / "home"
    documents = home / "Documents"
    documents.mkdir(parents=True)
    (home / "referent").write_text("safe home file")
    (documents / "referent").symlink_to(tmp_path / "outside")
    member = tarfile.TarInfo("dev-projects/link")
    member.type = tarfile.LNKTYPE
    member.linkname = "referent"
    with pytest.raises(ValueError, match="archive link escapes"):
        validate_archive(make_archive(tmp_path, [member]), str(home), extraction_directory=str(documents))


def test_shortened_archive_allows_relative_symlinks_within_the_home(tmp_path) -> None:
    """The home boundary still allows project links to sibling home data."""

    home = tmp_path / "home"
    member = tarfile.TarInfo("dev-projects/link")
    member.type = tarfile.SYMTYPE
    member.linkname = "../../shared.txt"
    assert (
        validate_archive(make_archive(tmp_path, [member]), str(home), extraction_directory=str(home / "Documents")) == 1
    )


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


@pytest.mark.parametrize("link_target", ["/usr/bin/python3", "/missing/python3"])
def test_archive_accepts_absolute_leaf_symlink(tmp_path, link_target: str) -> None:
    """Virtual environment links can reference an external or missing interpreter."""

    member = tarfile.TarInfo("project/.venv-pptx/bin/python3")
    member.type = tarfile.SYMTYPE
    member.linkname = link_target
    home = tmp_path / "home"
    destination = home / member.name
    destination.parent.mkdir(parents=True)
    destination.symlink_to(link_target)
    assert validate_archive(make_archive(tmp_path, [member]), str(home)) == 1


def test_archive_rejects_absolute_hard_link(tmp_path) -> None:
    """Hard links must never reference external filesystem contents."""

    member = tarfile.TarInfo("link")
    member.type = tarfile.LNKTYPE
    member.linkname = "/etc/passwd"
    with pytest.raises(ValueError, match="absolute archive link"):
        validate_archive(make_archive(tmp_path, [member]), str(tmp_path / "home"))


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("attack", ["descendant", "duplicate", "hard-link", "normalized-hard-link"])
def test_archive_rejects_writes_through_absolute_symlink(tmp_path, attack: str, reverse: bool) -> None:
    """No entry order can use an absolute symlink to redirect restored writes."""

    link = tarfile.TarInfo("redirect")
    link.type = tarfile.SYMTYPE
    link.linkname = "/tmp/outside"
    entry = tarfile.TarInfo("redirect/file" if attack == "descendant" else "redirect")
    if attack in {"hard-link", "normalized-hard-link"}:
        entry.name = "alias"
        entry.type = tarfile.LNKTYPE
        entry.linkname = "unused/../redirect" if attack == "normalized-hard-link" else "redirect"
    members = [entry, link] if reverse else [link, entry]
    with pytest.raises(ValueError, match="symlink"):
        validate_archive(make_archive(tmp_path, members), str(tmp_path / "home"))


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_archive_accepts_virtual_environment_symlink_chain(tmp_path, existing: bool, reverse: bool) -> None:
    """Interpreter aliases remain safe on fresh and repeated restores in either order."""

    home = tmp_path / "home"
    base = "dev-projects/project/.venv-pptx/bin"
    interpreter = tarfile.TarInfo(f"{base}/python3")
    interpreter.type = tarfile.SYMTYPE
    interpreter.linkname = "/usr/bin/python3"
    alias = tarfile.TarInfo(f"{base}/python")
    alias.type = tarfile.SYMTYPE
    alias.linkname = "python3"
    if existing:
        directory = home / base
        directory.mkdir(parents=True)
        (directory / "python3").symlink_to(interpreter.linkname)
        (directory / "python").symlink_to(alias.linkname)
    members = [alias, interpreter] if reverse else [interpreter, alias]
    assert validate_archive(make_archive(tmp_path, members), str(home)) == 2


def test_archive_rejects_hard_link_through_existing_interpreter_alias(tmp_path) -> None:
    """Accepting a symlink referent must not permit hard links outside the home."""

    home = tmp_path / "home"
    home.mkdir()
    (home / "python3").symlink_to("/usr/bin/python3")
    member = tarfile.TarInfo("hard-link")
    member.type = tarfile.LNKTYPE
    member.linkname = "python3"
    with pytest.raises(ValueError, match="archive link escapes"):
        validate_archive(make_archive(tmp_path, [member]), str(home))
