"""Validation of home-relative workstation recovery archives."""

from __future__ import annotations

import posixpath
import tarfile
from pathlib import Path, PurePosixPath


def _validate_link(
    member: tarfile.TarInfo,
    destination: Path,
    extraction_root: Path,
    target: Path,
    symlinks: set[PurePosixPath],
) -> None:
    """Validate relative link targets and reject unsafe hard links."""

    link = PurePosixPath(member.linkname)
    if member.issym() and link.is_absolute():
        return
    if link.is_absolute():
        raise ValueError(f"absolute archive link is not supported: {member.name}")
    hard_link = PurePosixPath(posixpath.normpath(member.linkname))
    if member.islnk() and any(path in symlinks for path in (hard_link, *hard_link.parents)):
        raise ValueError(f"archive hard link traverses an archived symlink: {member.name}")
    link_base = destination.parent if member.issym() else extraction_root
    link_path = link_base.joinpath(*link.parts)
    # Symlink creation does not access the referent. Resolve only hard
    # links; a relative symlink may refer to an external interpreter
    # through another existing symlink inside the restored tree.
    link_target = Path(posixpath.normpath(str(link_path))) if member.issym() else link_path.resolve()
    if not link_target.is_relative_to(target):
        raise ValueError(f"archive link escapes the target home: {member.name}")


def validate_archive(archive_path: str, target_home: str, *, extraction_directory: str | None = None) -> int:
    """Reject traversal, unsafe links and special files before extraction."""

    target = Path(target_home).resolve()
    extraction_root = Path(extraction_directory).absolute() if extraction_directory is not None else target
    if not extraction_root.resolve().is_relative_to(target):
        raise ValueError("archive extraction directory escapes the target home")
    count = 0
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        symlinks = {PurePosixPath(member.name) for member in members if member.issym()}
        seen_names: set[PurePosixPath] = set()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError(f"unsafe archive member path: {member.name}")
            if any(parent in symlinks for parent in name.parents):
                raise ValueError(f"archive member traverses an archived symlink: {member.name}")
            if name in symlinks and name in seen_names:
                raise ValueError(f"duplicate archive member at a symlink path: {member.name}")
            seen_names.add(name)
            destination = extraction_root.joinpath(*name.parts)
            # Creating a symlink writes its parent directory, not its referent.
            checked_destination = destination.parent if member.issym() else destination
            if not checked_destination.resolve().is_relative_to(target):
                raise ValueError(f"archive member escapes the target home: {member.name}")
            if member.issym() or member.islnk():
                _validate_link(member, destination, extraction_root, target, symlinks)
            elif not member.isfile() and not member.isdir():
                raise ValueError(f"special archive file is not supported: {member.name}")
            count += 1
    return count
