"""Validation of home-relative workstation recovery archives."""

from __future__ import annotations

import tarfile
from pathlib import Path, PurePosixPath


def validate_archive(archive_path: str, target_home: str) -> int:
    """Reject traversal, unsafe links and special files before extraction."""

    target = Path(target_home).resolve()
    count = 0
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        symlinks = {PurePosixPath(member.name) for member in members if member.issym()}
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError(f"unsafe archive member path: {member.name}")
            if any(parent in symlinks for parent in name.parents):
                raise ValueError(f"archive member traverses an archived symlink: {member.name}")
            destination = target.joinpath(*name.parts)
            if not destination.resolve().is_relative_to(target):
                raise ValueError(f"archive member escapes the target home: {member.name}")
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                if link.is_absolute():
                    raise ValueError(f"absolute archive link is not supported: {member.name}")
                link_base = destination.parent if member.issym() else target
                link_target = link_base.joinpath(*link.parts).resolve()
                if not link_target.is_relative_to(target):
                    raise ValueError(f"archive link escapes the target home: {member.name}")
            elif not member.isfile() and not member.isdir():
                raise ValueError(f"special archive file is not supported: {member.name}")
            count += 1
    return count
