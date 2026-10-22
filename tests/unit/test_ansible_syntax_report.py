"""Unit tests for the Ansible syntax SARIF generator."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock

MODULE_PATH = pathlib.Path(__file__).parents[2] / "ci" / "ansible_syntax_report.py"


def load_module() -> types.ModuleType:
    """Load the report helper without making ci a package."""
    spec = importlib.util.spec_from_file_location("ansible_syntax_report", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ansible_syntax_report = load_module()


class ParseIssueTests(unittest.TestCase):
    """Exercise normalization of ansible-playbook syntax failures."""

    def test_parses_origin_and_error_message(self) -> None:
        """It extracts the primary error text and origin coordinates."""
        output = """[ERROR]: conflicting action statements: ansible.builtin.set_fact, ansible.builtin.shell
Origin: /workspace/ansible/tasks/main.yml:83:3

81 some line
82 another line
83 failing line
     ^ column 3
"""

        issue = ansible_syntax_report.parse_issue("ansible/setup.yml", output)

        self.assertEqual(issue.level, "ERROR")
        self.assertEqual(
            issue.message, "conflicting action statements: ansible.builtin.set_fact, ansible.builtin.shell"
        )
        self.assertEqual(issue.path, "/workspace/ansible/tasks/main.yml")
        self.assertEqual(issue.line, 83)
        self.assertEqual(issue.column, 3)

    def test_falls_back_to_playbook_when_origin_is_missing(self) -> None:
        """It uses the playbook path when Ansible does not report an origin."""
        output = "plain failure without origin"

        issue = ansible_syntax_report.parse_issue("ansible/setup.yml", output)

        self.assertEqual(issue.path, "ansible/setup.yml")
        self.assertEqual(issue.line, 1)
        self.assertEqual(issue.column, 1)

    def test_builds_sarif_with_workspace_relative_uri(self) -> None:
        """It rewrites absolute workspace paths into SARIF source-root URIs."""
        issue = ansible_syntax_report.SyntaxIssue(
            playbook="ansible/setup.yml",
            level="ERROR",
            message="broken syntax",
            output="[ERROR]: broken syntax",
            path=str(pathlib.Path.cwd() / "ansible" / "setup.yml"),
            line=12,
            column=4,
        )

        sarif = ansible_syntax_report.build_sarif([issue])
        result = sarif["runs"][0]["results"][0]

        self.assertEqual(result["ruleId"], "ansible-playbook-syntax-check")
        self.assertEqual(
            result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
            "ansible/setup.yml",
        )


class RunTests(unittest.TestCase):
    """Keep failures visible even when a later playbook passes."""

    def test_preserves_earlier_failure_with_and_without_a_report(self) -> None:
        """Optional reporting must not change the syntax-check exit status."""
        for report_file in (None, "/tmp/syntax.sarif"):
            with self.subTest(report_file=report_file):
                args = types.SimpleNamespace(
                    inventory="inventory.yml", report_file=report_file, playbooks=["bad.yml", "good.yml"]
                )
                with (
                    mock.patch.object(ansible_syntax_report, "parse_args", return_value=args),
                    mock.patch.object(ansible_syntax_report, "stream_command", side_effect=[(17, "failure"), (0, "")]),
                    mock.patch.object(ansible_syntax_report, "write_sarif") as write_report,
                ):
                    self.assertEqual(ansible_syntax_report.run(), 17)
                    self.assertEqual(write_report.call_count, int(report_file is not None))


if __name__ == "__main__":
    unittest.main()
