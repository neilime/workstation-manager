"""Verify and explicitly publish an existing Git checkout."""

from __future__ import annotations

import base64
import os
from collections.abc import Callable
from pathlib import Path


def _git_environment(github_token: str) -> dict[str, str]:
    """Add noninteractive Git settings and optional authentication without logging secrets."""

    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    if github_token:
        index = int(environment.get("GIT_CONFIG_COUNT", "0"))
        environment["GIT_CONFIG_COUNT"] = str(index + 1)
        environment[f"GIT_CONFIG_KEY_{index}"] = "http.https://github.com/.extraheader"
        encoded = base64.b64encode(f"x-access-token:{github_token}".encode()).decode()
        environment[f"GIT_CONFIG_VALUE_{index}"] = f"Authorization: Basic {encoded}"
    return environment


def synchronize_git(
    source: str,
    *,
    run_command: Callable[..., tuple[int, str, str]],
    publish: bool = False,
    dry_run: bool = False,
    github_token: str = "",
) -> dict:
    """Fetch and inspect tracking state; publish only when explicitly requested."""

    environment = _git_environment(github_token)

    def git(*arguments: str, message: str = "Git inspection failed.") -> str:
        return_code, stdout, _stderr = run_command(
            ["git", "-C", source, *arguments],
            environ_update=environment,
        )
        if return_code:
            # Git diagnostics can contain credentials embedded in remote URLs.
            raise ValueError(message)
        return stdout.rstrip("\n")

    root = git("rev-parse", "--show-toplevel", message="Repository source is not a Git checkout.")
    if Path(root).resolve() != Path(source).resolve():
        raise ValueError("Repository source must be the root of its Git checkout.")
    branch = git(
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        message="Repository checkout has a detached HEAD. Check out its intended branch before backup.",
    )
    upstream = git(
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        message="Repository branch has no upstream. Publish it and configure its tracking branch before backup.",
    )
    remote = git("config", "--get", f"branch.{branch}.remote")
    remote_branch = git("config", "--get", f"branch.{branch}.merge")
    if remote == "." or not remote_branch.startswith("refs/heads/"):
        raise ValueError("Repository must track a branch in a remote repository before backup.")

    def inspect() -> dict:
        if not dry_run:
            git(
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                "--",
                remote,
                remote_branch,
                message="Could not fetch the repository tracking branch. Check remote access and retry backup.",
            )
        # FETCH_HEAD verifies the remote branch, including deletion or rewrite.
        # Only dry-run reporting may use a stale local tracking ref.
        commit = git("rev-parse", "@{upstream}" if dry_run else "FETCH_HEAD")
        ahead, behind = map(int, git("rev-list", "--left-right", "--count", f"HEAD...{commit}").split())
        status = git("status", "--short", "--untracked-files=normal")
        return {
            "repo_root": root,
            "branch": branch,
            "upstream": upstream,
            "upstream_commit": commit,
            "status": status,
            "ahead": ahead,
            "behind": behind,
            "needs_publish": bool(status or ahead),
            "remote_verified": not dry_run,
        }

    state = inspect()
    if dry_run:
        return {"changed": False, "state": state}
    if publish and state["behind"]:
        raise ValueError(
            "Repository is behind or diverged from its tracking branch. "
            "Review and reconcile the checkout manually, then retry backup."
        )
    changed = False
    if publish and state["needs_publish"]:
        if state["status"]:
            git("add", "--all", message="Could not stage repository changes for the requested publication.")
            git(
                "commit",
                "-m",
                "Update managed dotfiles",
                message="Could not commit repository changes. Check Git identity and hooks, then retry backup.",
            )
        git(
            "push",
            "--",
            remote,
            f"HEAD:{remote_branch}",
            message=(
                "Could not push repository changes. Local changes remain available; resolve the error and retry backup."
            ),
        )
        changed = True
        state = inspect()
        if state["needs_publish"] or state["behind"]:
            raise ValueError("Repository publication is incomplete. Resolve the remaining Git changes before backup.")
    return {"changed": changed, "state": state}
