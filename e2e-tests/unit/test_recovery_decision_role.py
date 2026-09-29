"""Exercise shared backup decisions with real Ansible and an isolated terminal."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

from backup_prompt_helpers import run_interactive

WORKSPACE = pathlib.Path(__file__).parents[2]


def decision(identifier="fixture", *, needed=True, scope="ssh-keys") -> dict:
    """Supply safe fixture instructions to the real shared role."""

    return {
        "ansible.builtin.include_role": {"name": "neilime.workstation_backup.recovery_decision"},
        "vars": {
            "workstation_backup_recovery_id": identifier,
            "workstation_backup_recovery_needed": needed,
            "workstation_backup_recovery_request": {
                "scope": scope,
                "summary": "Fixture recovery needs attention.",
                "actions": {"proceed": "Approve this fixture action."},
                "skip": "Leave this fixture unchanged and continue with other checks.",
                "abort_message": "Fixture recovery was declined.",
            },
        },
    }


class RecoveryDecisionRoleTests(unittest.TestCase):
    """No decision may reuse stale approval, silently skip, or act during a preview."""

    def setUp(self) -> None:
        self.interactive = True

    def run_decisions(self, tasks, answers=(), *, assertions=(), check=False) -> tuple[int, str]:
        """Drive production pause tasks without using real workstation state or accounts."""

        with tempfile.TemporaryDirectory() as temporary:
            fixture = pathlib.Path(temporary)
            (fixture / "ansible.cfg").write_text("[defaults]\n")
            playbook = fixture / "playbook.json"
            variables = {
                "ansible_python_interpreter": sys.executable,
                "workstation_backup_dry_run": "{{ ansible_check_mode }}",
                "workstation_backup_recovery_choices": {"fixture": "proceed"},
            }
            playbook.write_text(
                json.dumps(
                    [
                        {
                            "hosts": "localhost",
                            "connection": "local",
                            "gather_facts": False,
                            "vars": variables,
                            "tasks": tasks
                            + ([{"ansible.builtin.assert": {"that": list(assertions)}}] if assertions else []),
                        }
                    ]
                )
            )
            command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
            if check:
                command.append("--check")
            return run_interactive(
                command,
                fixture,
                {
                    "PATH": os.environ["PATH"],
                    "HOME": str(fixture),
                    "ANSIBLE_CONFIG": str(fixture / "ansible.cfg"),
                    "ANSIBLE_HOME": str(fixture / ".ansible"),
                    "ANSIBLE_COLLECTIONS_PATH": str(WORKSPACE / "ansible/collections"),
                    "WORKSTATION_MANAGER_INTERACTIVE": "1" if self.interactive else "0",
                },
                answers,
            )

    def test_invalid_answer_is_retried_and_explicit_answer_is_normalized(self) -> None:
        """A typo cannot select a default action, while case and surrounding space are tolerated."""

        code, output = self.run_decisions(
            [decision()],
            (("[proceed/skip/abort]", "not-an-action"), ("[proceed/skip/abort]", "  PrOcEeD  ")),
            assertions=(
                "workstation_backup_recovery_choices.fixture == 'proceed'",
                "workstation_backup_recovery_skips is not defined",
            ),
        )
        self.assertEqual(code, 0, output)

    def test_exhausted_invalid_answers_stop_without_approval(self) -> None:
        """An unresolved decision must fail once its bounded input retries are exhausted."""

        code, output = self.run_decisions([decision()], (("[proceed/skip/abort]", "invalid"),) * 4)
        self.assertNotEqual(code, 0, output)
        self.assertNotIn(
            "TASK [neilime.workstation_backup.recovery_decision : Record the explicit recovery decision]", output
        )

    def test_unnecessary_decision_clears_prior_approval_without_reading_its_request(self) -> None:
        """A later clean check cannot inherit approval or depend on unavailable inspection values."""

        unnecessary = decision(needed=False)
        unnecessary["vars"]["workstation_backup_recovery_request"] = "{{ unavailable_inspection }}"
        code, output = self.run_decisions(
            [decision(), unnecessary],
            (("[proceed/skip/abort]", "proceed"),),
            assertions=("workstation_backup_recovery_choices.fixture == ''",),
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(output.count("Choose [proceed/skip/abort]"), 1)

    def test_skip_does_not_skip_the_next_decision_in_the_same_scope(self) -> None:
        """Category-level incomplete coverage must not authorize skipping or applying another key."""

        code, output = self.run_decisions(
            [decision(), decision()],
            (("[proceed/skip/abort]", "skip"), ("[proceed/skip/abort]", "proceed")),
            assertions=(
                "workstation_backup_recovery_choices.fixture == 'proceed'",
                "workstation_backup_recovery_skips == ['ssh-keys']",
            ),
        )
        self.assertEqual(code, 0, output)

    def test_preview_and_noninteractive_runs_cannot_reuse_prior_approval(self) -> None:
        """Previews report pending work; unattended live decisions fail without inventing a skip."""

        self.interactive = False
        code, output = self.run_decisions([decision()])
        self.assertNotEqual(code, 0, output)
        self.assertIn("requires an interactive run", output)
        code, output = self.run_decisions(
            [decision()],
            check=True,
            assertions=(
                "workstation_backup_recovery_choices.fixture == ''",
                "workstation_backup_recovery_skips is not defined",
            ),
        )
        self.assertEqual(code, 0, output)
        self.assertIn("Fixture recovery needs attention.", output)
        self.assertNotIn("Choose [", output)

    def test_abort_stops_the_shared_flow(self) -> None:
        """Abort cannot be recorded as a skip or allowed to continue the caller."""

        code, output = self.run_decisions([decision()], (("[proceed/skip/abort]", "abort"),))
        self.assertNotEqual(code, 0, output)
        self.assertIn("Fixture recovery was declined.", output)


if __name__ == "__main__":
    unittest.main()
