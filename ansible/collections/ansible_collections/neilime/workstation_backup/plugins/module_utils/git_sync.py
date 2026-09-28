"""Verify and explicitly reconcile an existing Git checkout with its upstream."""

from __future__ import annotations

import base64
import os
from collections.abc import Callable
from pathlib import Path


class GitSyncError(ValueError):
    """Report a failed synchronization and whether it may have changed the checkout."""

    def __init__(self, message: str, *, changed: bool = False) -> None:
        super().__init__(message)
        self.changed = changed


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


class _GitCheckout:
    """Run Git commands with scoped credentials and track requested mutations."""

    def __init__(self, source: str, run_command: Callable[..., tuple[int, str, str]], github_token: str) -> None:
        self.source = source
        self.run_command = run_command
        self.environment = _git_environment(github_token)
        self.changed = False

    def git(self, *arguments: str, message: str = "Git inspection failed.", mutates: bool = False) -> str:
        """Keep command diagnostics private and preserve change reporting on failure."""

        self.changed = self.changed or mutates
        return_code, stdout, _stderr = self.run_command(
            ["git", "-C", self.source, *arguments],
            environ_update=self.environment,
        )
        if return_code:
            # Git diagnostics can contain credentials embedded in remote URLs.
            raise GitSyncError(message, changed=self.changed)
        return stdout.rstrip("\n")

    def require_finished_operations(self) -> None:
        """Never commit or publish a user's unfinished merge, rebase, or cherry-pick."""

        for operation in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD", "sequencer"):
            operation_path = Path(self.git("rev-parse", "--git-path", operation))
            if not operation_path.is_absolute():
                operation_path = Path(self.source) / operation_path
            if operation_path.exists():
                raise GitSyncError(
                    "Repository has an unfinished Git operation. "
                    "Complete or abort it manually in the source checkout, then retry backup.",
                    changed=self.changed,
                )

    def inspect(self, *, dry_run: bool = False) -> dict:
        """Validate the checkout and inspect its actual remote tracking branch."""

        root = self.git("rev-parse", "--show-toplevel", message="Repository source is not a Git checkout.")
        if Path(root).resolve() != Path(self.source).resolve():
            raise GitSyncError("Repository source must be the root of its Git checkout.")
        self.require_finished_operations()
        branch = self.git(
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
            message="Repository checkout has a detached HEAD. Check out its intended branch before backup.",
        )
        upstream = self.git(
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
            message="Repository branch has no upstream. Publish it and configure its tracking branch before backup.",
        )
        remote = self.git("config", "--get", f"branch.{branch}.remote")
        remote_branch = self.git("config", "--get", f"branch.{branch}.merge")
        if remote == "." or not remote_branch.startswith("refs/heads/"):
            raise GitSyncError("Repository must track a branch in a remote repository before backup.")
        if not dry_run:
            self.git(
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
        commit = self.git("rev-parse", "@{upstream}" if dry_run else "FETCH_HEAD")
        ahead, behind = map(int, self.git("rev-list", "--left-right", "--count", f"HEAD...{commit}").split())
        status = self.git("status", "--short", "--untracked-files=normal")
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

    def commit_changes(self) -> None:
        """Save all source edits before an explicitly requested merge or publication."""

        self.git("add", "--all", mutates=True, message="Could not stage repository changes for the requested action.")
        self.git(
            "commit",
            "-m",
            "Update managed dotfiles",
            mutates=True,
            message="Could not commit repository changes. Check Git identity and hooks, then retry backup.",
        )

    def require_safe_discard_scope(self, commit: str) -> None:
        """Keep nested repositories and ignored files outside automatic replacement."""

        for entry in self.git("ls-files", "--stage", "-z").split("\0"):
            if entry.startswith("160000 "):
                raise GitSyncError("Source contains submodules. Reconcile it manually before backup.")
        for path in self.git("ls-files", "--others", "--exclude-standard", "-z").split("\0"):
            if path and (Path(self.source) / path / ".git").exists():
                raise GitSyncError("Source contains a nested Git repository. Reconcile it manually before backup.")
        target_entries = self.git("ls-tree", "-r", "-z", commit).split("\0")
        if any(entry.startswith("160000 ") for entry in target_entries):
            raise GitSyncError("Tracking branch contains submodules. Reconcile it manually before backup.")
        target_paths = [entry.partition("\t")[2] for entry in target_entries if entry]
        ignored_paths = self.git("ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z").split(
            "\0"
        )
        for ignored in filter(None, ignored_paths):
            ignored = ignored.rstrip("/")
            if any(
                target == ignored or target.startswith(ignored + "/") or ignored.startswith(target + "/")
                for target in filter(None, target_paths)
            ):
                raise GitSyncError(
                    "Using the remote version would overwrite ignored source files. "
                    "Move or reconcile those files manually before backup."
                )

    def use_remote(self, state: dict) -> dict:
        """Replace local source changes only after the caller explicitly requests it."""

        if not (state["behind"] or state["needs_publish"]):
            return state
        self.require_safe_discard_scope(state["upstream_commit"])
        # Clean before resetting so local ignore rules still protect ignored data.
        self.git(
            "clean",
            "-fd",
            mutates=True,
            message="Could not remove untracked source files. Inspect the checkout before retrying backup.",
        )
        self.git(
            "reset",
            "--hard",
            "--no-recurse-submodules",
            state["upstream_commit"],
            mutates=True,
            message="Could not reset the source checkout. Inspect it before retrying backup.",
        )
        state = self.inspect()
        if state["behind"] or state["needs_publish"]:
            raise GitSyncError(
                "Remote replacement is incomplete or the tracking branch changed. "
                "Review the remaining source changes before retrying backup. Nothing was pushed.",
                changed=self.changed,
            )
        return state


def synchronize_git(
    source: str,
    *,
    run_command: Callable[..., tuple[int, str, str]],
    action: str = "inspect",
    dry_run: bool = False,
    github_token: str = "",
) -> dict:
    """Inspect tracking state; modify the checkout only for an explicit action."""

    if action not in {"inspect", "merge", "use-remote", "publish"}:
        raise GitSyncError("Choose one Git action: inspect, merge, use-remote, or publish.")
    checkout = _GitCheckout(source, run_command, github_token)
    state = checkout.inspect(dry_run=dry_run)
    if dry_run:
        return {"changed": False, "state": state}
    if action == "use-remote":
        state = checkout.use_remote(state)
    if action == "merge" and state["behind"]:
        if state["status"]:
            checkout.commit_changes()
        checkout.git(
            "merge",
            "--ff",
            "--commit",
            "--no-edit",
            "--no-autostash",
            "-m",
            "Merge upstream managed dotfiles",
            state["upstream_commit"],
            mutates=True,
            message=(
                "Could not merge the tracking branch. Local work remains in the source checkout. "
                "Inspect git status there; resolve conflicts and complete the merge, or use git merge --abort "
                "if a merge is in progress, then retry backup. Nothing was pushed."
            ),
        )
        state = checkout.inspect()
        if state["behind"]:
            raise GitSyncError("The tracking branch changed during reconciliation. Retry backup.", changed=True)
    if action == "publish" and state["behind"]:
        raise GitSyncError(
            "Repository is behind or diverged from its tracking branch. "
            "Review and reconcile the checkout manually, then retry backup."
        )
    if action == "publish" and state["needs_publish"]:
        if state["status"]:
            checkout.commit_changes()
        remote = checkout.git("config", "--get", f"branch.{state['branch']}.remote")
        remote_branch = checkout.git("config", "--get", f"branch.{state['branch']}.merge")
        checkout.git(
            "push",
            "--",
            remote,
            f"HEAD:{remote_branch}",
            mutates=True,
            message=(
                "Could not push repository changes. Local changes remain available; resolve the error and retry backup."
            ),
        )
        state = checkout.inspect()
        if state["needs_publish"] or state["behind"]:
            raise GitSyncError(
                "Repository publication is incomplete. Resolve the remaining Git changes before backup.", changed=True
            )
    return {"changed": checkout.changed, "state": state}
