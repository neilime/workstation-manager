"""Exercise backup decisions with real Ansible prompts and isolated Git checkouts."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from backup_prompt_helpers import run_interactive

COLLECTIONS_PATH = pathlib.Path(__file__).parents[2] / "ansible" / "collections"


class ChezmoiBackupRoleTests(unittest.TestCase):
    """Git reconciliation must precede file reconciliation and publication approval."""

    def setUp(self) -> None:
        # enterContext keeps fixture cleanup registered even when setup fails.
        # pylint: disable-next=consider-using-with
        self.fixture = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.environment = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.fixture),
            "LC_ALL": "C.UTF-8",
            "ANSIBLE_CONFIG": str(self.fixture / "ansible.cfg"),
            "ANSIBLE_HOME": str(self.fixture / ".ansible"),
            "ANSIBLE_COLLECTIONS_PATH": str(COLLECTIONS_PATH),
            "WORKSTATION_MANAGER_INTERACTIVE": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        (self.fixture / "ansible.cfg").write_text("[defaults]\n")
        self.home = self.fixture / "home"
        self.source = self.home / ".local/share/chezmoi"
        self.source.mkdir(parents=True)
        self.remote = self.fixture / "remote.git"
        self.git(self.fixture, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.source, "init", "--initial-branch=main")
        self.git(self.source, "config", "user.name", "Fixture")
        self.git(self.source, "config", "user.email", "fixture@example.invalid")
        (self.source / "dot_settings").write_text("original\n")
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-m", "Initial")
        self.git(self.source, "remote", "add", "origin", str(self.remote))
        self.git(self.source, "push", "--set-upstream", "origin", "main")
        (self.home / ".settings").write_text("original\n")
        self.original = self.git(self.source, "rev-parse", "HEAD")
        peer = self.fixture / "peer"
        self.git(self.fixture, "clone", str(self.remote), str(peer))
        self.git(peer, "config", "user.name", "Fixture")
        self.git(peer, "config", "user.email", "fixture@example.invalid")
        (peer / "dot_settings").write_text("upstream\n")
        self.git(peer, "commit", "-am", "Upstream")
        self.git(peer, "push")
        self.upstream = self.git(self.remote, "rev-parse", "main")
        config = self.home / ".config/chezmoi/chezmoi.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("{}\n")
        # Model one managed file; Git and the Ansible role/prompts are real.
        chezmoi = self.fixture / "chezmoi"
        chezmoi.write_text(
            '#!/bin/sh\nset -eu\nsource_file="$HOME/.local/share/chezmoi/dot_settings"\n'
            'case "$1" in\n'
            '  --version) printf "fixture\\n" ;;\n'
            '  status) cmp -s "$source_file" "$HOME/.settings" || printf " M .settings\\n" ;;\n'
            '  apply) cp "$source_file" "$HOME/.settings" ;;\n'
            '  re-add) cp "$HOME/.settings" "$source_file" ;;\n'
            "  *) exit 1 ;;\nesac\n"
        )
        chezmoi.chmod(0o755)
        variables = {
            "ansible_python_interpreter": sys.executable,
            "workstation_manager_use_become": False,
            "workstation_backup_dry_run": "{{ ansible_check_mode }}",
            "workstation_manager_resolved": {
                "user": {"name": "fixture", "home": str(self.home)},
                "home_environment": {"chezmoi": {"config_path": str(config), "bin_path": str(chezmoi)}},
            },
        }
        (self.fixture / "playbook.json").write_text(
            json.dumps(
                [
                    {
                        "name": "Exercise backup synchronization decisions",
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "vars": variables,
                        "roles": ["neilime.workstation_backup.chezmoi"],
                        "tasks": [
                            {
                                "ansible.builtin.copy": {
                                    "dest": str(self.fixture / "recovery-skips.json"),
                                    "content": "{{ workstation_backup_recovery_skips | default([]) | to_json }}",
                                    "mode": "0600",
                                }
                            }
                        ],
                    }
                ]
            )
        )

    def git(self, path: pathlib.Path, *arguments: str) -> str:
        """Run fixture Git commands without the developer's identity or hooks."""

        return subprocess.run(
            ["git", "-C", str(path), *arguments],
            env=self.environment,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def run_backup(self, answers=(), *, check=False) -> tuple[int, str]:
        """Answer real pause prompts through a terminal, failing on unexpected prompts."""

        command = ["ansible-playbook", "--inventory", "localhost,", str(self.fixture / "playbook.json")]
        if check:
            command.append("--check")
        return run_interactive(command, self.fixture, self.environment, answers)

    def test_skip_tracking_or_discard_preserves_all_local_changes(self) -> None:
        """Either skip must leave staged edits, workstation files, and both branches intact."""

        (self.source / "dot_settings").write_text("local edit\n")
        self.git(self.source, "add", ".")
        for answers in (
            (("[merge/use-remote/retry/skip/abort]", "skip"),),
            (("[merge/use-remote/retry/skip/abort]", "use-remote"), ("[discard/skip/abort]", "skip")),
        ):
            with self.subTest(answers=answers):
                code, output = self.run_backup(answers)
                self.assertEqual(code, 0, output)
                self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.original)
                self.assertEqual(self.git(self.remote, "rev-parse", "main"), self.upstream)
                self.assertEqual(self.git(self.source, "diff", "--cached", "--name-only"), "dot_settings")
                self.assertEqual((self.source / "dot_settings").read_text(), "local edit\n")
                self.assertEqual((self.home / ".settings").read_text(), "original\n")
                self.assertEqual(json.loads((self.fixture / "recovery-skips.json").read_text()), ["chezmoi"])
                self.assertNotIn("Choose [re-add/apply/skip/abort]", output)
                self.assertNotIn("Choose [publish/skip/abort]", output)

    def test_skip_file_drift_or_publication_keeps_prior_approved_changes(self) -> None:
        """Skipping a later decision neither rolls back a merge nor implicitly publishes it."""

        for stage in ("files", "publication"):
            with self.subTest(stage=stage):
                self.git(self.source, "reset", "--hard", self.original)
                answers = [("[merge/use-remote/retry/skip/abort]", "merge")]
                answers.append(("[re-add/apply/skip/abort]", "skip" if stage == "files" else "re-add"))
                if stage == "publication":
                    answers.append(("[publish/skip/abort]", "skip"))
                code, output = self.run_backup(answers)
                self.assertEqual(code, 0, output)
                self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.upstream)
                self.assertEqual(self.git(self.remote, "rev-parse", "main"), self.upstream)
                expected = "upstream\n" if stage == "files" else "original\n"
                self.assertEqual((self.source / "dot_settings").read_text(), expected)
                self.assertEqual((self.home / ".settings").read_text(), "original\n")
                self.assertEqual(json.loads((self.fixture / "recovery-skips.json").read_text()), ["chezmoi"])

    def test_merge_then_apply_checks_new_upstream_file_drift(self) -> None:
        """Updating Git must prompt for the resulting change to managed files."""

        code, output = self.run_backup(
            (("[merge/use-remote/retry/skip/abort]", "merge"), ("[re-add/apply/skip/abort]", "apply"))
        )
        self.assertEqual(code, 0, output)
        self.assertEqual((self.home / ".settings").read_text(), "upstream\n")
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.upstream)
        self.assertNotIn("Choose [publish/skip/abort]", output)

    def test_merge_then_readd_requires_separate_publication(self) -> None:
        """Keeping workstation files after a merge requires approving their new commit."""

        code, output = self.run_backup(
            (
                ("[merge/use-remote/retry/skip/abort]", "merge"),
                ("[re-add/apply/skip/abort]", "re-add"),
                ("[publish/skip/abort]", "publish"),
            )
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(self.git(self.remote, "show", "main:dot_settings"), "original")
        self.assertEqual(self.git(self.source, "status", "--porcelain"), "")
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.git(self.remote, "rev-parse", "main"))

    def test_abort_preserves_source_worktree_and_remote(self) -> None:
        """Declining reconciliation must stop backup before touching managed files."""

        code, output = self.run_backup((("[merge/use-remote/retry/skip/abort]", "abort"),))
        self.assertNotEqual(code, 0, output)
        self.assertIn("has not been reconciled", output)
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.original)
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), self.upstream)
        self.assertEqual((self.home / ".settings").read_text(), "original\n")

    def test_retry_does_not_bypass_unresolved_drift(self) -> None:
        """Retry rechecks the upstream instead of assuming manual work is complete."""

        code, output = self.run_backup((("[merge/use-remote/retry/skip/abort]", "retry"),))
        self.assertNotEqual(code, 0, output)
        self.assertIn("still behind", output)
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.original)

    def test_retry_accepts_completed_manual_reconciliation(self) -> None:
        """Work done in another terminal can continue into the managed file checks."""

        def reconcile_manually() -> str:
            self.git(self.source, "merge", "--ff-only", "origin/main")
            return "retry"

        code, output = self.run_backup(
            (("[merge/use-remote/retry/skip/abort]", reconcile_manually), ("[re-add/apply/skip/abort]", "apply"))
        )
        self.assertEqual(code, 0, output)
        self.assertEqual((self.home / ".settings").read_text(), "upstream\n")
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.upstream)

    def test_declining_publication_keeps_captured_files_local(self) -> None:
        """A merge approval must not authorize pushing subsequently captured files."""

        code, output = self.run_backup(
            (
                ("[merge/use-remote/retry/skip/abort]", "merge"),
                ("[re-add/apply/skip/abort]", "re-add"),
                ("[publish/skip/abort]", "abort"),
            )
        )
        self.assertNotEqual(code, 0, output)
        self.assertIn("have not been published", output)
        self.assertEqual((self.source / "dot_settings").read_text(), "original\n")
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), self.upstream)
        self.assertEqual(self.git(self.remote, "show", "main:dot_settings"), "upstream")

    def test_use_remote_discards_source_changes_only_after_confirmation(self) -> None:
        """Users may discard both local-only commits and edits without publishing them."""

        (self.source / "dot_settings").write_text("local commit\n")
        self.git(self.source, "commit", "-am", "Local")
        (self.source / "dot_settings").write_text("local edit\n")
        (self.source / "untracked").write_text("discard me\n")
        (self.home / ".settings").write_text("unwanted workstation edit\n")
        code, output = self.run_backup(
            (
                ("[merge/use-remote/retry/skip/abort]", "use-remote"),
                ("[discard/skip/abort]", "discard"),
                ("[re-add/apply/skip/abort]", "apply"),
            )
        )
        self.assertEqual(code, 0, output)
        self.assertEqual((self.home / ".settings").read_text(), "upstream\n")
        self.assertFalse((self.source / "untracked").exists())
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.upstream)
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), self.upstream)
        self.assertNotIn("Choose [publish/skip/abort]", output)

    def test_declining_discard_preserves_local_edits_and_commits(self) -> None:
        """Selecting use-remote alone is not sufficient approval to discard edits."""

        (self.source / "dot_settings").write_text("local commit\n")
        self.git(self.source, "commit", "-am", "Local")
        local_head = self.git(self.source, "rev-parse", "HEAD")
        (self.source / "dot_settings").write_text("local edit\n")
        code, output = self.run_backup(
            (("[merge/use-remote/retry/skip/abort]", "use-remote"), ("[discard/skip/abort]", "abort"))
        )
        self.assertNotEqual(code, 0, output)
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), local_head)
        self.assertEqual((self.source / "dot_settings").read_text(), "local edit\n")
        self.assertEqual((self.home / ".settings").read_text(), "original\n")

    def test_use_remote_is_available_without_incoming_commits(self) -> None:
        """Locally modified source files can be discarded even when Git is not behind."""

        self.git(self.source, "fetch", "origin")
        self.git(self.source, "merge", "--ff-only", "origin/main")
        (self.source / "dot_settings").write_text("unwanted local edit\n")
        code, output = self.run_backup(
            (
                ("[keep/use-remote/retry/skip/abort]", "use-remote"),
                ("[discard/skip/abort]", "discard"),
                ("[re-add/apply/skip/abort]", "apply"),
            )
        )
        self.assertEqual(code, 0, output)
        self.assertEqual((self.home / ".settings").read_text(), "upstream\n")
        self.assertEqual(self.git(self.source, "status", "--porcelain"), "")

    def test_keep_retains_local_source_for_separate_publication(self) -> None:
        """A local-only change can still take the existing apply-and-publish path."""

        self.git(self.source, "fetch", "origin")
        self.git(self.source, "merge", "--ff-only", "origin/main")
        (self.source / "dot_settings").write_text("wanted local edit\n")
        code, output = self.run_backup(
            (
                ("[keep/use-remote/retry/skip/abort]", "keep"),
                ("[re-add/apply/skip/abort]", "apply"),
                ("[publish/skip/abort]", "publish"),
            )
        )
        self.assertEqual(code, 0, output)
        self.assertEqual((self.home / ".settings").read_text(), "wanted local edit\n")
        self.assertEqual(self.git(self.remote, "show", "main:dot_settings"), "wanted local edit")

    def test_noninteractive_run_requires_a_decision(self) -> None:
        """An unattended backup must not integrate upstream or change managed files."""

        self.environment["WORKSTATION_MANAGER_INTERACTIVE"] = "0"
        code, output = self.run_backup()
        self.assertNotEqual(code, 0, output)
        self.assertIn("interactive terminal", output)
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.original)

    def test_dry_run_does_not_prompt_fetch_or_change_files(self) -> None:
        """A preview succeeds without access to the remote and reports unverified state."""

        self.remote.rename(self.fixture / "unavailable.git")
        code, output = self.run_backup(check=True)
        self.assertEqual(code, 0, output)
        self.assertIn("remote completion is unverified", output)
        self.assertFalse((self.source / ".git/FETCH_HEAD").exists())
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.original)
        self.assertEqual((self.home / ".settings").read_text(), "original\n")


if __name__ == "__main__":
    unittest.main()
