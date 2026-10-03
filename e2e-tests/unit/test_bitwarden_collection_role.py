"""Exercise Bitwarden collection authentication fallbacks with a local CLI fixture."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from ansible.parsing.dataloader import DataLoader

TASK_FILE = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup"
    / "roles/bitwarden_collection/tasks/main.yml"
)


def prepare_fixture(fixture: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Create a fake Bitwarden CLI and a playbook for the production role tasks."""

    audit_path = fixture / "commands.jsonl"
    state_path = fixture / "state.json"
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
with audit_path.open("a", encoding="utf-8") as audit:
    audit.write(json.dumps(sys.argv[1:]) + "\\n")

state_path = pathlib.Path({str(state_path)!r})
state = {{"authenticated": False, "unlocked": False}}
if state_path.exists():
    state.update(json.loads(state_path.read_text(encoding="utf-8")))

def save_state() -> None:
    state_path.write_text(json.dumps(state), encoding="utf-8")

args = sys.argv[1:]
expected_server = os.environ["EXPECTED_SERVER"]
expected_collection_id = os.environ["EXPECTED_COLLECTION_ID"]

if args == ["--version"]:
    print("2026.9.0")
    sys.exit(0)

if args == ["status"]:
    print(json.dumps({{"status": "unauthenticated", "serverUrl": expected_server}}))
    sys.exit(0)

if args == ["config", "server", expected_server]:
    sys.exit(0)

if args == ["login", "fixture@example.com", "--passwordenv", "BITWARDEN_PASSWORD", "--method", "1", "--raw"]:
    if os.environ["BITWARDEN_PASSWORD"] != "fixture-password":
        print("Invalid master password.", file=sys.stderr)
        sys.exit(1)
    print("Code is required.")
    sys.exit(1)

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
    if not state["unlocked"]:
        print("Vault is locked.", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

if args == ["list", "items", "--collectionid", expected_collection_id]:
    if not state["unlocked"]:
        print("Vault is locked.", file=sys.stderr)
        sys.exit(1)
    print("[]")
    sys.exit(0)

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
                            "secrets": {"bitwarden": {"server": "https://vault.example.invalid"}},
                            "system": {"packages": {"cache_valid_time": 3600}},
                        },
                    },
                    "tasks": DataLoader().load_from_file(str(TASK_FILE)),
                }
            ]
        ),
        encoding="utf-8",
    )
    return audit_path, playbook


class BitwardenCollectionRoleTests(unittest.TestCase):
    """Setup should reuse API-key authentication when email login needs a hidden code."""

    def run_role(self) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        """Run the production role tasks against the fake Bitwarden CLI."""

        with tempfile.TemporaryDirectory() as temporary_dir:
            fixture = pathlib.Path(temporary_dir)
            audit_path, playbook = prepare_fixture(fixture)
            config = fixture / "ansible.cfg"
            config.write_text("[defaults]\n", encoding="utf-8")
            environment = {
                "PATH": f"{fixture / 'bin'}:{os.environ['PATH']}",
                "HOME": str(fixture),
                "LC_ALL": "C.UTF-8",
                "ANSIBLE_CONFIG": str(config),
                "ANSIBLE_HOME": str(fixture / ".ansible"),
                "ANSIBLE_COLLECTIONS_PATH": os.environ["ANSIBLE_COLLECTIONS_PATH"],
                "AUDIT_PATH": str(audit_path),
                "EXPECTED_SERVER": "https://vault.example.invalid",
                "EXPECTED_COLLECTION_ID": "fixture-collection",
                "BITWARDEN_EMAIL": "fixture@example.com",
                "BITWARDEN_CLIENT_ID": "fixture-client",
                "BITWARDEN_CLIENT_SECRET": "fixture-secret",
                "BITWARDEN_PASSWORD": "fixture-password",
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
            calls = (
                [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
                if audit_path.exists()
                else []
            )
            return result, calls

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
                ["list", "items", "--collectionid", "fixture-collection"],
            ],
        )
        self.assertNotIn("interactive Bitwarden verification code prompt", output)


if __name__ == "__main__":
    unittest.main()
