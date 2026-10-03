"""Exercise Bitwarden collection authentication fallbacks with a local CLI fixture."""

# This fixture intentionally mirrors the Bitwarden CLI prompt flows exercised in
# lower-level auth tests so the production role can be verified end-to-end.
# pylint: disable=duplicate-code

from __future__ import annotations

import json
import os
import pathlib
import pwd
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Any

from ansible.parsing.dataloader import DataLoader

TASK_FILE = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup"
    / "roles/bitwarden_collection/tasks/main.yml"
)


def prepare_fixture(
    fixture: pathlib.Path,
    *,
    email_login_scenario: str = "code-required",
    sync_failures_before_success: int = 0,
    collection_items: list[dict] | None = None,
    initial_state: dict | None = None,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create a fake Bitwarden CLI and a playbook for the production role tasks."""

    audit_path = fixture / "commands.jsonl"
    bin_dir = fixture / "bin"
    bin_dir.mkdir()
    (bin_dir / "bw").write_text(
        f"""#!{sys.executable}
import json
import os
import pathlib
import sys

audit_path = pathlib.Path(os.environ["AUDIT_PATH"])
audit_path.parent.mkdir(parents=True, exist_ok=True)
args = sys.argv[1:]
session = os.environ.get("BW_SESSION", "")
if len(args) >= 2 and args[-2] == "--session":
    session = args[-1]
    args = args[:-2]
with audit_path.open("a", encoding="utf-8") as audit:
    audit.write(json.dumps(args) + "\\n")

config_home = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", str(pathlib.Path(os.environ["HOME"]) / ".config")))
state_path = pathlib.Path(os.environ.get("BITWARDENCLI_APPDATA_DIR", str(config_home / "Bitwarden CLI"))) / "state.json"
state_path.parent.mkdir(parents=True, exist_ok=True)
items = json.loads({json.dumps(collection_items or [])!r})
state = {{"authenticated": False, "unlocked": False, "sync_attempts": 0, "server": os.environ["EXPECTED_SERVER"]}}
state.update(json.loads({json.dumps(initial_state or {})!r}))
if state_path.exists():
    state.update(json.loads(state_path.read_text(encoding="utf-8")))
email_login_scenario = {email_login_scenario!r}
sync_failures_before_success = {sync_failures_before_success!r}

def save_state() -> None:
    state_path.write_text(json.dumps(state), encoding="utf-8")

expected_server = os.environ["EXPECTED_SERVER"]
expected_collection_id = os.environ["EXPECTED_COLLECTION_ID"]

if args == ["--version"]:
    print("2026.9.0")
    sys.exit(0)

if args == ["status"]:
    status = "locked" if state["authenticated"] else "unauthenticated"
    if state["unlocked"] and session == "fixture-session":
        status = "unlocked"
    print(json.dumps({{"status": status, "serverUrl": state["server"]}}))
    sys.exit(0)

if args == ["logout"]:
    if state.get("logout_failed"):
        print("Fixture logout failed.", file=sys.stderr)
        sys.exit(1)
    state["authenticated"] = False
    state["unlocked"] = False
    save_state()
    sys.exit(0)

if args == ["config", "server", expected_server]:
    if state["authenticated"]:
        print("Logout required before server config update.", file=sys.stderr)
        sys.exit(1)
    state["server"] = expected_server
    save_state()
    sys.exit(0)

if args == ["login", "fixture@example.com", "--passwordenv", "BITWARDEN_PASSWORD", "--method", "1", "--raw"]:
    if os.environ["BITWARDEN_PASSWORD"] != "fixture-password":
        print("Invalid master password.", file=sys.stderr)
        sys.exit(1)
    if email_login_scenario == "code-required":
        print("Code is required.")
        sys.exit(1)
    if email_login_scenario == "interactive-code":
        if not sys.stdin.isatty():
            print("Code is required.")
            sys.exit(1)
        print("Two-step login code:", end="", flush=True)
        code = sys.stdin.readline().strip()
        if code != "123456":
            print("\\nInvalid verification code.")
            sys.exit(1)
        state["authenticated"] = True
        save_state()
        print("\\nfixture-login-session")
        sys.exit(0)
    print("unexpected login scenario", email_login_scenario, file=sys.stderr)
    sys.exit(98)

if args == ["login", "--apikey"]:
    if os.environ.get("BW_CLIENTID") != "fixture-client" or os.environ.get("BW_CLIENTSECRET") != "fixture-secret":
        print("Invalid API key.", file=sys.stderr)
        sys.exit(1)
    state["authenticated"] = True
    save_state()
    sys.exit(0)

if args == ["unlock", "--passwordenv", "BITWARDEN_PASSWORD", "--raw"]:
    if not state["authenticated"]:
        print("Not authenticated.", file=sys.stderr)
        sys.exit(1)
    if os.environ["BITWARDEN_PASSWORD"] != "fixture-password":
        print("Invalid master password.", file=sys.stderr)
        sys.exit(1)
    state["unlocked"] = True
    save_state()
    print("fixture-session")
    sys.exit(0)

if args == ["sync"]:
    if not state["unlocked"] or session != "fixture-session":
        print("Vault is locked.", file=sys.stderr)
        sys.exit(1)
    state["sync_attempts"] += 1
    save_state()
    if state["sync_attempts"] <= sync_failures_before_success:
        print("Sync failed.", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

if args == ["list", "items", "--collectionid", expected_collection_id]:
    if not state["unlocked"] or session != "fixture-session":
        print("Vault is locked.", file=sys.stderr)
        sys.exit(1)
    if state.get("read_failed"):
        print("synthetic-read-secret", file=sys.stderr)
        sys.exit(1)
    if state.get("malformed_items"):
        print("not valid json: synthetic-read-secret")
    else:
        print(json.dumps(items))
    sys.exit(0)

if args[:2] == ["get", "item"]:
    if not state["unlocked"] or session != "fixture-session":
        print("Vault is locked.", file=sys.stderr)
        sys.exit(1)
    for item in items:
        if item["id"] == args[2]:
            print(json.dumps(item))
            sys.exit(0)
    print("Not found.", file=sys.stderr)
    sys.exit(1)

print("unexpected arguments", args, file=sys.stderr)
sys.exit(99)
""",
        encoding="utf-8",
    )
    (bin_dir / "bw").chmod(0o755)

    playbook = fixture / "playbook.json"
    playbook.write_text(
        json.dumps(
            [
                {
                    "name": "Exercise Bitwarden collection auth",
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "ansible_python_interpreter": sys.executable,
                        "workstation_manager_use_become": False,
                        "bitwarden_collection_id": "fixture-collection",
                        "bitwarden_collection_purpose": "Bitwarden SSH restore",
                        "workstation_manager_resolved": {
                            "user": {"name": pwd.getpwuid(os.getuid()).pw_name, "home": str(fixture)},
                            "secrets": {"bitwarden": {"server": "https://vault.example.invalid"}},
                            "system": {"packages": {"cache_valid_time": 3600}},
                        },
                    },
                    "tasks": [
                        {"ansible.builtin.import_role": {"name": "neilime.workstation_setup.bitwarden_collection"}},
                        {
                            "name": "Verify collection results without printing secrets",
                            "ansible.builtin.assert": {"that": "bitwarden_collection_items == fixture_expected_items"},
                            "vars": {"fixture_expected_items": collection_items or []},
                            "no_log": True,
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    return audit_path, playbook


class BitwardenCollectionRoleTests(unittest.TestCase):
    """Setup should authenticate Bitwarden collection access for setup roles."""

    def run_role(
        self,
        *,
        interactive: bool = False,
        include_api_key: bool = True,
        environment_overrides: dict[str, str] | None = None,
        playbook_arguments: tuple[str, ...] = (),
        **fixture_options: Any,
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        """Run the production role tasks against the fake Bitwarden CLI."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            audit_path, playbook = prepare_fixture(fixture, **fixture_options)
            (fixture / "ansible.cfg").write_text("[defaults]\n", encoding="utf-8")
            environment = {
                "PATH": f"{fixture / 'bin'}:{os.environ['PATH']}",
                "HOME": str(fixture),
                "LC_ALL": "C.UTF-8",
                "ANSIBLE_CONFIG": str(fixture / "ansible.cfg"),
                "ANSIBLE_HOME": str(fixture / ".ansible"),
                "ANSIBLE_LOG_PATH": str(fixture / "ansible.log"),
                "ANSIBLE_COLLECTIONS_PATH": os.environ["ANSIBLE_COLLECTIONS_PATH"],
                "AUDIT_PATH": str(audit_path),
                "EXPECTED_SERVER": "https://vault.example.invalid",
                "EXPECTED_COLLECTION_ID": "fixture-collection",
                "BITWARDEN_EMAIL": "fixture@example.com",
                "BITWARDEN_PASSWORD": "fixture-password",
                "WORKSTATION_MANAGER_INTERACTIVE": "1" if interactive else "0",
            }
            if include_api_key:
                environment["BITWARDEN_CLIENT_ID"] = "fixture-client"
                environment["BITWARDEN_CLIENT_SECRET"] = "fixture-secret"

            environment.update(environment_overrides or {})

            if interactive:
                command = shlex.join(
                    [
                        "/bin/sh",
                        "-c",
                        (
                            'WORKSTATION_MANAGER_TTY="${WORKSTATION_MANAGER_TTY:-$(tty)}"\n'
                            "export WORKSTATION_MANAGER_TTY\n"
                            f"exec ansible-playbook -i localhost, -c local {shlex.quote(str(playbook))}\n"
                        ),
                    ]
                )
                result = subprocess.run(
                    [
                        shutil.which("script") or "script",
                        "--quiet",
                        "--return",
                        "--command",
                        command,
                        os.devnull,
                    ],
                    cwd=fixture,
                    env=environment,
                    input="123456\n",
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            else:
                result = subprocess.run(
                    ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook), *playbook_arguments],
                    cwd=fixture,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            calls = (
                [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
                if audit_path.exists()
                else []
            )
            log = (fixture / "ansible.log").read_text(encoding="utf-8")
            self.assertNotIn("synthetic-read-secret", log)
            # Authentication command tracing precedes the lookup; check its error log separately.
            self.assertNotIn("fixture-session", log.split("Read Bitwarden collection items", 1)[-1])
            return result, calls

    def test_collection_lookup_preserves_empty_single_and_multiple_records(self) -> None:
        """The real upstream lookup must return complete records with a stable list shape."""

        for count in (0, 1, 2):
            with self.subTest(count=count):
                items = [
                    {"id": str(index), "name": f"Key {index}", "notes": "synthetic-read-secret"}
                    for index in range(count)
                ]
                result, calls = self.run_role(collection_items=items)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(calls[-2:], [["status"], ["list", "items", "--collectionid", "fixture-collection"]])
                self.assertNotIn("synthetic-read-secret", result.stdout + result.stderr)

    def test_lookup_read_failures_do_not_become_empty_collections(self) -> None:
        """CLI errors and malformed JSON must fail without disclosing vault contents."""

        for state in ({"read_failed": True}, {"malformed_items": True}):
            with self.subTest(state=state):
                result, _calls = self.run_role(initial_state=state, playbook_arguments=("-vvv",))
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("synthetic-read-secret", result.stdout + result.stderr)

    def test_lookup_reads_collections_during_dry_runs(self) -> None:
        """Both preview modes authenticate, sync, and read without replacing records."""

        for arguments in (("--check",), ("--extra-vars", '{"workstation_backup_dry_run": true}')):
            with self.subTest(arguments=arguments):
                result, calls = self.run_role(playbook_arguments=arguments)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(["sync"], calls)
                self.assertEqual(calls[-1], ["list", "items", "--collectionid", "fixture-collection"])

    def test_persistent_sync_failure_prevents_collection_reads(self) -> None:
        """Exhausted retries must fail before the lookup can consume stale records."""

        result, calls = self.run_role(sync_failures_before_success=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls.count(["sync"]), 4)
        self.assertFalse(any(call[0] == "list" for call in calls))

    def test_browser_collection_and_live_reads_share_managed_user_cache(self) -> None:
        """Root-style bootstrap must authenticate the same cache used by browser recovery."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            managed_home = fixture / "managed-home"
            managed_home.mkdir()
            item = {
                "id": "11111111-1111-4111-8111-111111111111",
                "type": 2,
                "name": "Fixture",
                "notes": "syntheticremote " * 24,
                "collectionIds": ["fixture-collection"],
                "fields": [{"name": "id", "value": "fixture"}, {"name": "directory", "value": "Default"}],
            }
            audit_path, playbook = prepare_fixture(fixture, collection_items=[item])
            config = fixture / "ansible.cfg"
            config.write_text("[defaults]\n", encoding="utf-8")
            collection_root = TASK_FILE.parents[3]
            probe = fixture / "read_browser_record.py"
            probe.write_text(
                "import os, subprocess, sys\n"
                "from ansible_collections.neilime.workstation_setup.plugins.module_utils "
                "import browser_profile_sync\n"
                "def run_command(argv, **kwargs):\n"
                "    result = subprocess.run(argv, env=kwargs['environ_update'], "
                "input=kwargs['data'], capture_output=True, check=False)\n"
                "    return result.returncode, result.stdout, result.stderr\n"
                "vault = browser_profile_sync.BrowserVault(os.environ['BW_SESSION'], "
                "'fixture-collection', run_command)\n"
                "vault.selected_item({'id': 'fixture', 'directory': 'Default', 'item_id': sys.argv[1]})\n",
                encoding="utf-8",
            )
            content = json.loads(playbook.read_text(encoding="utf-8"))
            content[0]["vars"]["workstation_manager_resolved"]["user"] = {
                "name": pwd.getpwuid(os.getuid()).pw_name,
                "home": str(managed_home),
            }
            content[0]["vars"]["workstation_manager_resolved"]["secrets"]["bitwarden"][
                "browser_profiles_collection_id"
            ] = "fixture-collection"
            content[0]["tasks"] = DataLoader().load_from_file(
                str(collection_root / "roles/browser_profile_collection/tasks/metadata.yml")
            )
            content[0]["tasks"].append(
                {
                    "name": "Read selected profile using the live browser vault helper",
                    "ansible.builtin.command": {
                        "argv": [sys.executable, str(probe), "{{ workstation_manager_browser_profiles[0].item_id }}"]
                    },
                    "environment": {
                        "HOME": str(managed_home),
                        "XDG_CONFIG_HOME": str(managed_home / ".config"),
                        "BW_SESSION": "{{ bitwarden_collection_session }}",
                    },
                    "changed_when": False,
                    "no_log": True,
                }
            )
            playbook.write_text(json.dumps(content), encoding="utf-8")
            environment = {
                "PATH": f"{fixture / 'bin'}:{os.environ['PATH']}",
                "HOME": str(fixture),
                "XDG_CONFIG_HOME": str(fixture / "bootstrap-config"),
                "LC_ALL": "C.UTF-8",
                "ANSIBLE_CONFIG": str(config),
                "ANSIBLE_HOME": str(fixture / ".ansible"),
                "ANSIBLE_LOG_PATH": str(fixture / "ansible.log"),
                "ANSIBLE_COLLECTIONS_PATH": os.environ["ANSIBLE_COLLECTIONS_PATH"],
                "PYTHONPATH": str(collection_root.parents[2]),
                "AUDIT_PATH": str(audit_path),
                "EXPECTED_SERVER": "https://vault.example.invalid",
                "EXPECTED_COLLECTION_ID": "fixture-collection",
                "BITWARDEN_EMAIL": "fixture@example.com",
                "BITWARDEN_PASSWORD": "fixture-password",
                "BITWARDEN_CLIENT_ID": "fixture-client",
                "BITWARDEN_CLIENT_SECRET": "fixture-secret",
                "WORKSTATION_MANAGER_INTERACTIVE": "0",
            }
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
                cwd=fixture,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((managed_home / ".config/Bitwarden CLI/state.json").exists())
            self.assertFalse((fixture / "bootstrap-config/Bitwarden CLI/state.json").exists())

    def test_noninteractive_email_code_challenge_falls_back_to_api_key(self) -> None:
        """CI-style runs should keep going when only the email login needs a verification code."""

        result, calls = self.run_role()
        output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(
            calls,
            [
                ["--version"],
                ["--version"],
                ["status"],
                ["login", "fixture@example.com", "--passwordenv", "BITWARDEN_PASSWORD", "--method", "1", "--raw"],
                ["login", "--apikey"],
                ["unlock", "--passwordenv", "BITWARDEN_PASSWORD", "--raw"],
                ["sync"],
                ["status"],
                ["list", "items", "--collectionid", "fixture-collection"],
            ],
        )
        self.assertNotIn("interactive Bitwarden verification code prompt", output)

    def test_interactive_email_code_challenge_uses_exported_tty_path(self) -> None:
        """Interactive setup should relay emailed verification codes through the exported TTY path."""

        result, calls = self.run_role(
            interactive=True,
            include_api_key=False,
            email_login_scenario="interactive-code",
        )
        output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(
            calls,
            [
                ["--version"],
                ["--version"],
                ["status"],
                ["login", "fixture@example.com", "--passwordenv", "BITWARDEN_PASSWORD", "--method", "1", "--raw"],
                ["unlock", "--passwordenv", "BITWARDEN_PASSWORD", "--raw"],
                ["sync"],
                ["status"],
                ["list", "items", "--collectionid", "fixture-collection"],
            ],
        )
        self.assertNotIn("interactive Bitwarden verification code prompt", output)

    def test_interactive_terminal_access_failure_has_actionable_diagnostic(self) -> None:
        """Managed-user permission failures must not claim the run is noninteractive."""

        result, _calls = self.run_role(
            interactive=True,
            include_api_key=False,
            email_login_scenario="interactive-code",
            environment_overrides={"WORKSTATION_MANAGER_TTY": "/dev/workstation-manager-missing-test-tty"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not open the terminal", result.stdout + result.stderr)
        self.assertNotIn("no interactive terminal is available", result.stdout + result.stderr)

    def test_interactive_terminal_access_failure_can_use_configured_api_key(self) -> None:
        """A configured API key remains a valid fallback when the terminal cannot open."""

        result, calls = self.run_role(
            interactive=True,
            email_login_scenario="interactive-code",
            environment_overrides={"WORKSTATION_MANAGER_TTY": "/dev/workstation-manager-missing-test-tty"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(["login", "--apikey"], calls)
        self.assertIn(["list", "items", "--collectionid", "fixture-collection"], calls)

    def test_server_switch_logs_out_and_authenticates_again(self) -> None:
        """Both locked and unlocked accounts must leave the old server before login."""

        for unlocked in (False, True):
            with self.subTest(unlocked=unlocked):
                result, calls = self.run_role(
                    initial_state={
                        "server": "https://old-vault.example.invalid",
                        "authenticated": True,
                        "unlocked": unlocked,
                    }
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(
                    calls[3:6], [["logout"], ["config", "server", "https://vault.example.invalid"], ["status"]]
                )
                self.assertIn(["login", "--apikey"], calls)
                self.assertIn(["list", "items", "--collectionid", "fixture-collection"], calls)

    def test_server_switch_does_not_logout_an_unauthenticated_cli(self) -> None:
        """Fresh CLI configuration can change server without a redundant logout."""

        result, calls = self.run_role(initial_state={"server": "https://old-vault.example.invalid"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(["logout"], calls)
        self.assertEqual(calls[3:5], [["config", "server", "https://vault.example.invalid"], ["status"]])

    def test_matching_server_preserves_authenticated_account(self) -> None:
        """Normal recovery reuses an existing account when its server is correct."""

        result, calls = self.run_role(initial_state={"authenticated": True})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(call[0] in {"logout", "config", "login"} for call in calls))
        self.assertIn(["unlock", "--passwordenv", "BITWARDEN_PASSWORD", "--raw"], calls)

    def test_server_switch_requires_credentials_before_logging_out(self) -> None:
        """Missing login or unlock inputs must leave the authenticated account intact."""

        missing_inputs = [
            {"BITWARDEN_EMAIL": "", "BITWARDEN_CLIENT_ID": "", "BITWARDEN_CLIENT_SECRET": ""},
            {"BITWARDEN_PASSWORD": ""},
        ]
        for environment in missing_inputs:
            with self.subTest(missing=list(environment)):
                result, calls = self.run_role(
                    initial_state={"server": "https://old-vault.example.invalid", "authenticated": True},
                    environment_overrides=environment,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [["--version"], ["--version"], ["status"]])

    def test_dry_runs_do_not_logout_or_change_servers(self) -> None:
        """Both setup check mode and backup previews reject the mismatch read-only."""

        for arguments in (("--check",), ("--extra-vars", '{"workstation_backup_dry_run": true}')):
            with self.subTest(arguments=arguments):
                result, calls = self.run_role(
                    initial_state={"server": "https://old-vault.example.invalid", "authenticated": True},
                    playbook_arguments=arguments,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("dry runs do not change the CLI server configuration", result.stdout + result.stderr)
                self.assertEqual(calls, [["--version"], ["--version"], ["status"]])

    def test_failed_logout_stops_before_configuring_server(self) -> None:
        """Failed logout cannot be ignored or followed by a server change."""

        result, calls = self.run_role(
            initial_state={"server": "https://old-vault.example.invalid", "authenticated": True, "logout_failed": True}
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Bitwarden could not log out before changing servers", result.stdout + result.stderr)
        self.assertEqual(calls, [["--version"], ["--version"], ["status"], ["logout"]])

    def test_sync_retries_after_transient_failure(self) -> None:
        """Transient Bitwarden sync failures should retry before the role gives up."""

        result, calls = self.run_role(sync_failures_before_success=1)
        output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(
            calls,
            [
                ["--version"],
                ["--version"],
                ["status"],
                ["login", "fixture@example.com", "--passwordenv", "BITWARDEN_PASSWORD", "--method", "1", "--raw"],
                ["login", "--apikey"],
                ["unlock", "--passwordenv", "BITWARDEN_PASSWORD", "--raw"],
                ["sync"],
                ["sync"],
                ["status"],
                ["list", "items", "--collectionid", "fixture-collection"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
