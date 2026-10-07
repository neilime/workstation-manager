"""Exercise GitHub authentication in development tooling without downloading tools."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import ansible_environment, run_playbook, write_local_playbook

pytestmark = pytest.mark.integration

ROLE_PATH = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup/roles/development_tooling"
)
TOKEN = "synthetic-development-tooling-token"
INSTALL_TASK = "Install globally configured mise tools"
EXTENSION_TASK = "Install declared pinned GitHub CLI extensions"


def prepare_fixture(fixture: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Create fake CLIs and a playbook containing the role's unchanged tool tasks."""
    user_home = fixture / "home"
    binary_dir = user_home / ".local/bin"
    binary_dir.mkdir(parents=True)
    for directory in ("mise", "workstation-manager"):
        (user_home / ".config" / directory).mkdir(parents=True)
    audit_path = fixture / "commands.jsonl"
    stub = (
        f"#!{sys.executable}\n"
        + r"""
import json
import os
import pathlib
import sys

tool = pathlib.Path(sys.argv[0]).name
if sys.argv[1] == "activate":
    sys.exit(0)
token_name = "MISE_GITHUB_TOKEN" if tool == "mise" else "GH_TOKEN"
assert os.environ.get(token_name) == os.environ["EXPECTED_TOKEN"], "GitHub authentication was not forwarded"
assert os.environ["HOME"] == os.environ["EXPECTED_HOME"], "Incorrect managed user home"
assert os.environ["XDG_CONFIG_HOME"] == os.environ["EXPECTED_HOME"] + "/.config"
with open(os.environ["AUDIT_PATH"], "a", encoding="utf-8") as audit:
    audit.write(json.dumps([tool, *sys.argv[1:]]) + "\n")
if " ".join([tool, *sys.argv[1:]]) == os.environ["FAIL_COMMAND"]:
    print("Simulated installation failure: " + os.environ[token_name], file=sys.stderr)
    sys.exit(1)
if tool == "gh":
    pin = pathlib.Path(os.environ["HOME"]) / "extension-pin"
    if sys.argv[1:3] == ["extension", "install"]:
        pin.write_text(sys.argv[-1])
    if sys.argv[1:3] == ["extension", "list"] and pin.exists():
        print("gh fixture\texample/gh-fixture\t" + pin.read_text())
"""
    )
    for name in ("mise", "gh"):
        binary = binary_dir / name
        binary.write_text(stub)
        binary.chmod(0o755)

    tasks = []
    source_tasks = DataLoader().load_from_file(str(ROLE_PATH / "tasks/main.yml"))
    source_tasks += DataLoader().load_from_file(str(ROLE_PATH / "tasks/github_extensions.yml"))
    for task in source_tasks:
        if task["name"] in {INSTALL_TASK, EXTENSION_TASK}:
            if task["name"] == EXTENSION_TASK:
                task["environment"] = task["environment"].replace(
                    "'/usr/bin:/bin'", repr(str(binary_dir) + ":/usr/bin:/bin")
                )
            tasks.append(task)
        elif task["name"] in {"Render global mise tool configuration", "Render mise shell activation fragment"}:
            template = task["ansible.builtin.template"]
            template["src"] = str(ROLE_PATH / "templates" / template["src"])
            # Container users may have different numeric UID and GID values without account entries.
            template["group"] = str(os.getgid())
            tasks.append(task)
    playbook = fixture / "playbook.json"
    write_local_playbook(
        playbook,
        tasks,
        {
            "workstation_manager_use_become": False,
            "workstation_manager_development_mise_binary": {"stat": {"exists": True}},
            "workstation_manager_resolved": {
                "user": {"name": str(os.getuid()), "home": str(user_home), "state_dir": str(user_home / "state")},
                "development": {
                    "mise": {"tools": {"aqua:starship/starship": "1.2.3"}},
                    "github": {"extensions": {"example/gh-fixture": "v1.2.3"}},
                },
            },
        },
    )
    return user_home, audit_path, playbook


class DevelopmentToolingAuthTests(unittest.TestCase):
    """Run the real installation tasks with local stand-ins for mise and gh."""

    def run_installation(
        self, *, token: str | None, failure_command: str = "", check_mode: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]], str]:
        """Capture command behavior and Ansible output in an isolated temporary home."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            user_home, audit_path, playbook = prepare_fixture(fixture)
            environment = ansible_environment(
                fixture,
                MISE_GITHUB_TOKEN="existing-mise-token",
                GH_TOKEN="existing-gh-token",
                EXPECTED_TOKEN=TOKEN if token else "",
                EXPECTED_HOME=str(user_home),
                AUDIT_PATH=str(audit_path),
                FAIL_COMMAND=failure_command,
            )
            if token is not None:
                environment["WORKSTATION_MANAGER_GITHUB_TOKEN"] = token
            if not token:
                # Native CLI authentication must survive when no manager token was supplied.
                environment["MISE_GITHUB_TOKEN"] = environment["GH_TOKEN"] = "existing-native-token"
                environment["EXPECTED_TOKEN"] = "existing-native-token"
            command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
            if check_mode:
                command.append("--check")
            result = run_playbook(command, environment, cwd=fixture)
            calls = [json.loads(line) for line in audit_path.read_text().splitlines()] if audit_path.exists() else []
            generated = "".join(path.read_text() for path in (user_home / ".config").rglob("*") if path.is_file())
            return result, calls, generated

    def test_manager_token_reaches_mise_and_github_extensions(self) -> None:
        """The supplied token overrides native tokens without entering config files or output."""
        result, calls, generated = self.run_installation(token=TOKEN)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(
            calls,
            [
                ["mise", "install"],
                ["gh", "extension", "list"],
                ["gh", "extension", "install", "example/gh-fixture", "--pin", "v1.2.3"],
                ["gh", "extension", "list"],
            ],
        )
        self.assertIn('"aqua:starship/starship" = "1.2.3"', generated)
        self.assertNotIn(TOKEN, generated + output)

    def test_missing_manager_token_preserves_native_authentication(self) -> None:
        """Absent and empty optional tokens must not override existing CLI authentication."""
        for token in (None, ""):
            with self.subTest(token=token):
                result, calls, _ = self.run_installation(token=token)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(len(calls), 4)

    def test_authenticated_failure_is_redacted(self) -> None:
        """Even a failing CLI that prints the supplied token must not expose it in Ansible output."""
        for command in ("mise install", "gh extension list", "gh extension install example/gh-fixture --pin v1.2.3"):
            with self.subTest(command=command):
                result, calls, _ = self.run_installation(token=TOKEN, failure_command=command)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls[-1], command.split())
                self.assertIn("censored", output)
                self.assertNotIn(TOKEN, output)

    def test_failure_without_manager_token_remains_diagnosable(self) -> None:
        """Do not censor diagnostics when the manager has no token to forward."""
        result, _, _ = self.run_installation(token=None, failure_command="mise install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Simulated installation failure", result.stdout + result.stderr)

    def test_dry_run_does_not_install_tools(self) -> None:
        """Check mode must not invoke either installer even when credentials are available."""
        result, calls, _ = self.run_installation(token=TOKEN, check_mode=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
