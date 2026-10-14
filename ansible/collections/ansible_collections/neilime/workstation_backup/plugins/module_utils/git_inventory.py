"""Discover project repositories and collect read-only Git recovery metadata."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn


def _raise_walk_error(error: OSError) -> NoReturn:
    """Fail inventory collection when a directory cannot be inspected."""

    raise error


# Inventory construction is the builder's single public operation.
# pylint: disable-next=too-few-public-methods
class GitRepositoryInventoryBuilder:
    """Prune ignored project trees before collecting repository metadata."""

    def __init__(self, run_command: Callable[..., tuple[int, str, str]]) -> None:
        self.run_command = run_command

    def build(self, projects_directory: str) -> list[dict[str, Any]]:
        """Return deterministic inventory records without changing any checkout."""

        projects_root = Path(projects_directory)
        if not projects_root.is_absolute():
            raise ValueError("The Git inventory projects directory must be an absolute path.")
        if not projects_root.exists():
            return []
        if not projects_root.is_dir():
            raise ValueError(f"The Git inventory projects path is not a directory: {projects_root}")
        return [self._metadata(repository, projects_root) for repository in self._discover(projects_root)]

    def _git(self, repository: Path, *arguments: str, allowed_codes: tuple[int, ...] = (0,)) -> tuple[int, str]:
        """Check exit codes without exposing Git diagnostics or remote credentials."""

        return_code, stdout, _stderr = self.run_command(
            ["git", "-C", str(repository), *arguments],
            environ_update={"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
        if return_code not in allowed_codes:
            raise ValueError(
                f"Git {arguments[0]} failed for {repository} (exit status {return_code}). "
                "Check that the repository is readable and valid, then retry backup."
            )
        return return_code, stdout

    def _discover(self, projects_root: Path) -> list[Path]:
        """Find physical .git directories without entering ignored directory trees."""

        ignored_by_repository: dict[Path, set[Path]] = {}
        for directory, subdirectories, _files in os.walk(projects_root, onerror=_raise_walk_error, followlinks=False):
            subdirectories.sort()
            path = Path(directory)
            if ".git" in subdirectories:
                subdirectories.remove(".git")
                if not (path / ".git").is_symlink():
                    ignored_by_repository[path] = self._ignored_directories(path)
            repository = next((parent for parent in (path, *path.parents) if parent in ignored_by_repository), None)
            if repository is not None:
                ignored = ignored_by_repository[repository]
                subdirectories[:] = [name for name in subdirectories if path / name not in ignored]
        return sorted(ignored_by_repository)

    def _ignored_directories(self, repository: Path) -> set[Path]:
        """List collapsed ignored trees once per repository without excluding tracked files."""

        _return_code, stdout = self._git(
            repository, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory"
        )
        return {repository / name.rstrip("/") for name in stdout.split("\0") if name.endswith("/")}

    def _metadata(self, repository: Path, projects_root: Path) -> dict[str, Any]:
        """Preserve branch, commit, remotes, and local-change fields for restoration."""

        remote_names = self._git(repository, "remote")[1].splitlines()
        remotes = []
        for name in remote_names:
            if name:
                url = self._git(repository, "remote", "get-url", name)[1].strip()
                if url:
                    remotes.append({"name": name, "url": url})
        primary_remote = next(
            (remote for remote in remotes if remote["name"] == "origin"),
            remotes[0] if remotes else {"name": "", "url": ""},
        )
        branch = self._git(repository, "symbolic-ref", "--quiet", "--short", "HEAD", allowed_codes=(0, 1))[1].strip()
        head_commit = self._git(repository, "rev-parse", "HEAD")[1].strip()
        status_lines = [
            line
            for line in self._git(repository, "status", "--porcelain", "--untracked-files=all")[1].splitlines()
            if line
        ]
        return {
            "relative_path": str(repository.relative_to(projects_root)),
            "root_path": str(repository),
            "head_commit": head_commit,
            "branch": branch,
            "primary_remote_name": primary_remote["name"],
            "primary_remote_url": primary_remote["url"],
            "remotes": remotes,
            "has_local_modifications": bool(status_lines),
            "status_lines": status_lines,
        }
