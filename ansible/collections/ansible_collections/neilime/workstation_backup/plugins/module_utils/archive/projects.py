"""Stream project backups without visiting excluded dependency trees."""

from __future__ import annotations

import filecmp
import fnmatch
import os
import stat
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any


def archive_staging_path(destination: str) -> Path:
    """Keep incomplete output separate from an existing completed backup."""

    return Path(destination + ".partial")


# The writer exposes one operation to its Ansible adapter.
# pylint: disable-next=too-few-public-methods
class ProjectArchiveWriter:
    """Apply Git's own ignore rules once per repository and archive each entry once."""

    def __init__(self, run_command: Callable[..., tuple[int, str, str]]) -> None:
        self.run_command = run_command
        self.ignored_paths: dict[Path, set[Path]] = {}

    # These arguments mirror the module options; root and check mode stay keyword-only.
    # pylint: disable-next=too-many-arguments
    def create(
        self,
        paths: list[str],
        destination: str,
        exclusion_patterns: list[str],
        *,
        root: str | None = None,
        check_mode: bool = False,
    ) -> dict[str, Any]:
        """Write a private gzip tar, publishing it only after all sources succeed."""

        self.ignored_paths.clear()
        sources = sorted({Path(os.path.abspath(path)) for path in paths})
        if not sources:
            raise ValueError("No backup source paths were supplied.")
        output = Path(os.path.abspath(destination))
        for source in sources:
            metadata = source.lstat()
            if output.resolve() == source.resolve():
                raise ValueError("The backup destination must not overwrite a source path.")
            if stat.S_ISDIR(metadata.st_mode) and output.resolve().is_relative_to(source.resolve()):
                raise ValueError("The backup destination must be outside every source directory.")
        if output.is_symlink():
            raise ValueError("The backup destination must not be a symbolic link.")
        if not output.parent.is_dir():
            raise ValueError(f"The backup destination directory does not exist: {output.parent}")
        archive_root = (
            Path(os.path.abspath(root))
            if root is not None
            else Path(os.path.commonpath([str(source.parent) for source in sources]))
        )
        if not archive_root.is_dir():
            raise ValueError(f"The archive root directory does not exist: {archive_root}")
        if any(not source.is_relative_to(archive_root) for source in sources):
            raise ValueError("Every backup source must be inside the archive root directory.")
        # Overlapping requested sources must not duplicate entries or repeat traversal.
        sources = [
            source
            for source in sources
            if not any(parent in sources and not parent.is_symlink() for parent in source.parents)
        ]
        entries = self._entries(sources, archive_root, exclusion_patterns)
        if check_mode:
            count = sum(1 for _entry in entries)
            changed = True
        else:
            changed, count = self._write(entries, archive_root, output)
        return {"changed": changed, "dest": str(output), "arcroot": str(archive_root), "archived_count": count}

    def _write(self, entries: Iterator[Path], root: Path, output: Path) -> tuple[bool, int]:
        """Stream selected entries and atomically replace the destination after success."""

        staging = archive_staging_path(str(output))
        try:
            descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise ValueError(
                f"Incomplete backup already exists: {staging}. "
                "Check that no backup is running, then move it aside before retrying."
            ) from error
        count = 0
        try:
            with os.fdopen(descriptor, "wb") as raw:
                os.fchmod(raw.fileno(), 0o600)
            with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".workstation-backup-files-") as selected:
                for entry in entries:
                    selected.write(os.fsencode(str(entry.relative_to(root))) + b"\0")
                    count += 1
                selected.flush()
                self._compress(selected.name, staging, root)
            changed = not output.exists() or not filecmp.cmp(staging, output, shallow=False)
            if changed:
                os.replace(staging, output)
            elif stat.S_IMODE(output.stat().st_mode) != 0o600:
                output.chmod(0o600)
                changed = True
        finally:
            staging.unlink(missing_ok=True)
        return changed, count

    def _compress(self, selected: str, staging: Path, root: Path) -> None:
        """Let native tar stream only selected entries, without recursive expansion."""

        # Stable headers let repeated backups compare without decompressing.
        return_code, _stdout, stderr = self.run_command(
            [
                "tar",
                "--create",
                "--file",
                str(staging),
                "--directory",
                str(root),
                "--format=pax",
                "--pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime",
                "--use-compress-program=gzip --fast --no-name",
                "--no-recursion",
                "--null",
                "--verbatim-files-from",
                "--files-from",
                selected,
            ],
            environ_update={"LC_ALL": "C", "TAR_OPTIONS": "", "GZIP": ""},
        )
        if return_code != 0:
            reason = (
                "A source file changed while being read; stop writes to project files and retry."
                if "file changed as we read it" in stderr
                else "Check source permissions, available disk space, and that tar and gzip are installed."
            )
            raise ValueError(f"Backup archive creation failed (exit status {return_code}). {reason}")

    def _ignored(self, repository: Path) -> set[Path]:
        """Ask Git for ignored files and collapsed ignored directories, using NUL paths."""

        if repository not in self.ignored_paths:
            return_code, stdout, _stderr = self.run_command(
                [
                    "git",
                    "-C",
                    str(repository),
                    "ls-files",
                    "-z",
                    "--others",
                    "--ignored",
                    "--exclude-standard",
                    "--directory",
                ],
                environ_update={"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
            )
            if return_code != 0:
                raise ValueError(
                    f"Git ignore inspection failed for {repository} (exit status {return_code}). "
                    "Check that the repository is readable and valid, then retry backup."
                )
            self.ignored_paths[repository] = {repository / name.rstrip("/") for name in stdout.split("\0") if name}
        return self.ignored_paths[repository]

    @staticmethod
    def _repository(path: Path) -> Path | None:
        """Find enclosing Git metadata, including worktree and submodule gitfiles."""

        for directory in (path, *path.parents):
            marker = directory / ".git"
            if not marker.is_symlink() and (marker.is_dir() or marker.is_file()):
                return directory
        return None

    def _entries(self, sources: list[Path], root: Path, patterns: list[str]) -> Iterator[Path]:
        """Preserve physical files, directories and symlinks without following links."""

        for source in sources:
            repository = self._repository(source.parent)
            ignored = self._ignored(repository) if repository is not None else set()
            if any(parent in ignored for parent in source.parents):
                continue
            yield from self._walk(source, root, patterns, ignored)

    def _walk(self, path: Path, root: Path, patterns: list[str], ignored: set[Path]) -> Iterator[Path]:
        """Prune ignored and excluded directories before inspecting their contents."""

        name = str(path.relative_to(root))
        if path.name == ".git" or any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
            return
        if path in ignored:
            return
        metadata = path.lstat()
        is_directory = stat.S_ISDIR(metadata.st_mode)
        if not (is_directory or stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)):
            raise ValueError(
                f"Unsupported backup source type: {path}. Only files, directories and symlinks are supported."
            )
        yield path
        if not is_directory or any(fnmatch.fnmatchcase(name + "/", pattern) for pattern in patterns):
            return
        marker = path / ".git"
        if not marker.is_symlink() and (marker.is_dir() or marker.is_file()):
            ignored = self._ignored(path)
        with os.scandir(path) as directory:
            children = sorted(entry.name for entry in directory)
        for child in children:
            yield from self._walk(path / child, root, patterns, ignored)
