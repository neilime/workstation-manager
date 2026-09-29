"""Exercise GPG backup collection without accessing a real keyring or vault."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

COLLECTIONS_PATH = pathlib.Path(__file__).parents[2] / "ansible" / "collections"
TASK_FILE = (
    COLLECTIONS_PATH
    / "ansible_collections/neilime/workstation_backup/roles/secret_manager_keys/tasks/collect_gpg_key.yml"
)
FINGERPRINT = "A" * 40
OTHER_FINGERPRINT = "B" * 40


def run_gpg_collection(
    ownertrust: str,
    expected_ownertrust: str | None,
    *,
    check_mode: bool,
    export_status: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Run the real collection tasks against an isolated GPG command fixture."""

    with tempfile.TemporaryDirectory() as temporary_dir:
        fixture = pathlib.Path(temporary_dir)
        (fixture / "ansible.cfg").write_text("[defaults]\n")
        user_home = fixture / "home"
        user_home.mkdir()
        gpg = fixture / "gpg"
        # Model GPG's argument contract, including failure after partial output.
        gpg.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            f"assert os.environ['HOME'] == {str(user_home)!r}\n"
            f"assert os.environ['GNUPGHOME'] == {str(user_home / '.gnupg')!r}\n"
            f"if sys.argv[1:] == ['--batch', '--armor', '--export-secret-keys', {FINGERPRINT!r}]:\n"
            "    print('synthetic-private-key')\n"
            f"elif sys.argv[1:] == ['--batch', '--armor', '--export', {FINGERPRINT!r}]:\n"
            "    print('synthetic-public-key')\n"
            "elif sys.argv[1:] == ['--batch', '--export-ownertrust']:\n"
            f"    sys.stdout.write({ownertrust!r})\n"
            f"    sys.exit({export_status})\n"
            "else:\n"
            "    sys.exit(2)\n"
        )
        gpg.chmod(0o755)
        variables = {
            "ansible_python_interpreter": sys.executable,
            "workstation_manager_use_become": False,
            "workstation_manager_resolved": {"user": {"name": "fixture", "home": str(user_home)}},
            "item": FINGERPRINT,
            "expected_key": {
                "fingerprint": FINGERPRINT,
                "private_key": "synthetic-private-key",
                "public_key": "synthetic-public-key",
                "ownertrust": expected_ownertrust,
            },
        }
        playbook = fixture / "playbook.json"
        playbook.write_text(
            json.dumps(
                [
                    {
                        "name": "Verify GPG backup collection",
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "vars": variables,
                        "tasks": [
                            {"ansible.builtin.include_tasks": str(TASK_FILE)},
                            {
                                "name": "Verify collected key and optional ownertrust",
                                "ansible.builtin.assert": {
                                    "that": ["workstation_backup_local_gpg_keys == [expected_key]"]
                                },
                                "no_log": True,
                            },
                        ],
                    }
                ]
            )
        )
        command = ["ansible-playbook", "--inventory", "localhost,", str(playbook)]
        if check_mode:
            command.append("--check")
        return subprocess.run(
            command,
            cwd=fixture,
            env={
                "PATH": str(fixture) + os.pathsep + os.environ["PATH"],
                "HOME": str(fixture),
                "GNUPGHOME": str(fixture / "controller-gnupg"),
                "LC_ALL": "C.UTF-8",
                "ANSIBLE_CONFIG": str(fixture / "ansible.cfg"),
                "ANSIBLE_HOME": str(fixture / ".ansible"),
                "ANSIBLE_COLLECTIONS_PATH": str(COLLECTIONS_PATH),
            },
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )


@pytest.mark.parametrize("check_mode", [False, True])
@pytest.mark.parametrize(
    "ownertrust, expected_ownertrust",
    [
        (
            f"# Ownertrust export\n{OTHER_FINGERPRINT}:3:\n{FINGERPRINT}:6:\n{FINGERPRINT}00:4:\n",
            f"{FINGERPRINT}:6:",
        ),
        (f"# Ownertrust export\n{OTHER_FINGERPRINT}:3:\n{FINGERPRINT}00:4:\n", None),
        ("", None),
    ],
)
def test_gpg_backup_selects_only_the_current_keys_ownertrust(
    check_mode: bool, ownertrust: str, expected_ownertrust: str | None
) -> None:
    """A complete export must select only the exact fingerprint, allowing absent trust."""

    result = run_gpg_collection(ownertrust, expected_ownertrust, check_mode=check_mode)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0" in result.stdout
    assert "synthetic-private-key" not in result.stdout + result.stderr
    assert "synthetic-public-key" not in result.stdout + result.stderr


@pytest.mark.parametrize("check_mode", [False, True])
def test_gpg_ownertrust_export_failure_stops_backup(check_mode: bool) -> None:
    """Partial stdout from a failed export must never be recorded as a verified key."""

    result = run_gpg_collection(f"{FINGERPRINT}:6:\n", None, check_mode=check_mode, export_status=2)
    assert result.returncode != 0
    assert "Record the local GPG key for synchronization" not in result.stdout
    assert "synthetic-private-key" not in result.stdout + result.stderr
