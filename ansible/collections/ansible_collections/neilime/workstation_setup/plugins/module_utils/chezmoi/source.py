"""Refresh the managed Chezmoi checkout without replacing unpublished source work."""

from __future__ import annotations

import base64
import shlex
from collections.abc import Callable
from pathlib import Path


class ChezmoiSourceError(ValueError):
    """Keep Git diagnostics private while reporting possible checkout changes."""

    def __init__(self, message: str, *, changed: bool = False, local_changes: bool = False) -> None:
        super().__init__(message)
        self.changed = changed
        self.local_changes = local_changes


# Updating a checkout is one transaction; only ensure is public.
# pylint: disable=too-few-public-methods
class ChezmoiSourceUpdater:
    """Fetch the existing tracking branch and accept only clean fast-forward updates."""

    def __init__(self, source: Path, run_command: Callable[..., tuple[int, str, str]], github_token: str = "") -> None:
        self.source, self.run_command = source, run_command
        self.changed = False
        self.stash_revision = ""
        self.environment = {"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
        if github_token:
            encoded = base64.b64encode(f"x-access-token:{github_token}".encode()).decode()
            self.environment.update(
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                GIT_CONFIG_VALUE_0=f"Authorization: Basic {encoded}",
            )

    def _git(self, *arguments: str, message: str = "Cannot inspect the Chezmoi source checkout") -> str:
        try:
            status, stdout, _stderr = self.run_command(
                ["git", "-C", str(self.source), *arguments], environ_update=self.environment
            )
        except OSError as error:
            raise self._error(message) from error
        if status:
            raise self._error(message)
        return stdout.strip()

    def _error(self, message: str, *, local_changes: bool = False) -> ChezmoiSourceError:
        if self.stash_revision:
            recovery = shlex.join(["git", "-C", str(self.source), "stash", "apply", "--index", self.stash_revision])
            message += f". Local source edits remain in stash {self.stash_revision}; recover them with: {recovery}"
        return ChezmoiSourceError(message, changed=self.changed, local_changes=local_changes)

    def _require_clean(self, *, reconcilable: bool = False) -> None:
        if self._git("status", "--porcelain", "--untracked-files=all"):
            raise self._error(
                "Chezmoi source has local changes; rerun setup interactively to stash them or skip Chezmoi, "
                "or commit and publish them before rerunning setup",
                local_changes=reconcilable,
            )

    def ensure(self, *, check_mode: bool = False, stash_local_changes: bool = False) -> dict:
        """Verify a fresh remote revision before allowing setup to inspect or apply dotfiles."""
        root = self._git("rev-parse", "--show-toplevel")
        if Path(root).resolve() != self.source.resolve():
            raise ChezmoiSourceError("Chezmoi source must be the root of its Git checkout")
        for operation in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD", "sequencer"):
            operation_path = Path(self._git("rev-parse", "--git-path", operation))
            if not operation_path.is_absolute():
                operation_path = self.source / operation_path
            if operation_path.exists():
                raise ChezmoiSourceError("Complete or abort the unfinished Git operation in the Chezmoi source first")
        before = self._git("rev-parse", "HEAD")
        branch = self._git(
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
            message="Chezmoi source has a detached HEAD; check out its intended tracking branch before setup",
        )
        tracking_error = "Chezmoi source branch has no upstream; configure its remote tracking branch before setup"
        remote = self._git("config", "--get", f"branch.{branch}.remote", message=tracking_error)
        remote_branch = self._git("config", "--get", f"branch.{branch}.merge", message=tracking_error)
        if remote == "." or not remote_branch.startswith("refs/heads/"):
            raise ChezmoiSourceError("Chezmoi source must track a branch in a remote repository")
        if not stash_local_changes:
            self._require_clean(reconcilable=True)
        if check_mode:
            return {"changed": False, "revision": before, "remote_verified": False}
        # Git's fixed fetch arguments are also used by backup; setup has its own stricter update policy.
        # pylint: disable=duplicate-code
        self._git(
            "fetch",
            "--no-tags",
            "--no-recurse-submodules",
            "--",
            remote,
            remote_branch,
            message="Cannot fetch the latest Chezmoi source; check remote access and rerun setup",
        )
        # pylint: enable=duplicate-code
        revision = self._git("rev-parse", "FETCH_HEAD")
        self._git(
            "merge-base",
            "--is-ancestor",
            before,
            revision,
            message=(
                "Chezmoi source has unpublished commits or rewritten upstream history; "
                "reconcile its tracking branch manually, then rerun setup"
            ),
        )
        if stash_local_changes and self._git("status", "--porcelain", "--untracked-files=all"):
            previous_stash = self._git("stash", "list", "--max-count=1", "--format=%H")
            # A failed stash can still have saved work or partially cleaned the checkout.
            self.changed = True
            self._git(
                "stash",
                "push",
                "--include-untracked",
                "--message",
                "workstation-manager setup: Chezmoi source edits",
                message="Cannot stash the Chezmoi source edits; inspect git status and git stash list before retrying",
            )
            stash_revision = self._git(
                "rev-parse",
                "--verify",
                "refs/stash",
                message="Cannot verify the saved Chezmoi edits; inspect git stash list before retrying",
            )
            if stash_revision == previous_stash:
                raise self._error(
                    "No new Chezmoi source stash was created; inspect git status and git stash list "
                    "and reconcile remaining edits manually"
                )
            self.stash_revision = stash_revision
        self._require_clean()
        if revision != before:
            self.changed = True
            self._git(
                "merge",
                "--ff-only",
                "--no-autostash",
                "--no-overwrite-ignore",
                revision,
                message="Cannot fast-forward the Chezmoi source; preserve local work and reconcile it before setup",
            )
        if self._git("rev-parse", "HEAD") != revision:
            raise self._error("Chezmoi source update was not verified; rerun setup")
        self._require_clean()
        return {
            "changed": self.changed,
            "revision": revision,
            "remote_verified": True,
            "stash_revision": self.stash_revision,
        }
