"""Build isolated entrypoint inputs and check their shared forwarding contract."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

from entrypoint_test_helpers import (
    entrypoint_source_with_mock_controller,
    terminal_command,
)


def prepare_input_runner(tmp_path):
    """Replace system commands while retaining input collection and shared Ansible execution."""
    commands = tmp_path / "bin"
    commands.mkdir()
    sudo = commands / "sudo"
    sudo.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        'pathlib.Path(os.environ["TEST_SUDO_CALLED"]).touch()\n'
        'if args == ["-v"]: sys.exit(0)\n'
        'if args[0].startswith("--preserve-env="): args.pop(0)\n'
        'os.environ.pop("ANSIBLE_PIPELINING", None)\n'
        "os.execvp(args[0], args)\n"
    )
    sudo.chmod(0o700)
    chown = commands / "chown"
    chown.write_text("#!/bin/sh\nexit 0\n")
    chown.chmod(0o700)
    controller = commands / "ansible-pull"
    controller.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        'names = ["BITWARDEN_EMAIL", "BITWARDEN_CLIENT_ID", "BITWARDEN_CLIENT_SECRET", "BITWARDEN_PASSWORD",\n'
        '         "WORKSTATION_MANAGER_GITHUB_TOKEN", "WORKSTATION_MANAGER_INTERACTIVE",\n'
        '         "WORKSTATION_MANAGER_GHCR_TOKEN",\n'
        '         "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0",\n'
        '         "WORKSTATION_MANAGER_TTY", "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR",\n'
        '         "WORKSTATION_MANAGER_RESTORE_ARCHIVE", "ANSIBLE_PIPELINING"]\n'
        'record = {"args": sys.argv[1:], "stdin_tty": sys.stdin.isatty(),\n'
        '          "environment": {name: os.environ.get(name) for name in names}}\n'
        'pathlib.Path(os.environ["TEST_INVOCATION"]).write_text(json.dumps(record))\n'
        'print(" ".join(sys.argv))\n'
        'sys.exit(int(os.environ.get("TEST_EXIT_STATUS", "0")))\n'
    )
    controller.chmod(0o700)
    script = tmp_path / "workstation.sh"
    definitions = entrypoint_source_with_mock_controller().rsplit('main "$@"', 1)[0]
    script.write_text(
        definitions
        + "\nprepare_action_dependencies() {\n"
        + "    require_sudo\n"
        + "    TARGET_USER=fixture\n"
        + '    TARGET_USER_HOME="$HOME"\n'
        + '    COLLECTIONS_INSTALL_DIR="$HOME/.ansible/collections"\n'
        + '}\nmain "$@"\n'
    )
    environment = {
        "PATH": f"{commands}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "REPOSITORY_URL": "https://github.com/example/workstation-manager.git",
        "REPOSITORY_BRANCH": "fixture-ref",
        "BITWARDEN_CLIENT_ID": "fixture-client",
        "BITWARDEN_CLIENT_SECRET": "fixture-client-secret",
        "BITWARDEN_PASSWORD": "fixture'password $HOME $(false)",
        "WORKSTATION_MANAGER_GITHUB_TOKEN": "fixture-token",
        "WORKSTATION_MANAGER_GHCR_TOKEN": "fixture-registry-token",
        "WORKSTATION_MANAGER_TTY": "/dev/inherited-terminal",
        "WORKSTATION_MANAGER_INTERACTIVE": "1",
        "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR": str(tmp_path / "backup's files"),
        "WORKSTATION_MANAGER_RESTORE_ARCHIVE": str(tmp_path / "restore's archive.tar.gz"),
        "TEST_INVOCATION": str(tmp_path / "invocation.json"),
        "TEST_SUDO_CALLED": str(tmp_path / "sudo-called"),
    }
    return script, environment


def assert_supplied_inputs(input_runner, arguments, terminal, status):
    """Supplied credentials skip prompts while terminal handling, previews and failures remain unchanged."""
    script, environment = input_runner
    environment.update(TEST_EXIT_STATUS=str(status), CI="true", GITHUB_ACTIONS="true")
    command = ["sh", str(script), *arguments]
    if terminal:
        command = terminal_command(command)
    result = subprocess.run(
        command, env=environment, capture_output=True, text=True, start_new_session=True, timeout=10, check=False
    )
    assert result.returncode == status, result.stdout + result.stderr
    invocation = json.loads(Path(environment["TEST_INVOCATION"]).read_text(encoding="utf-8"))
    actual = invocation["environment"]
    assert actual["ANSIBLE_PIPELINING"] == environment.get("ANSIBLE_PIPELINING", "true")
    assert actual["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    encoded = base64.b64encode(f"x-access-token:{environment['WORKSTATION_MANAGER_GITHUB_TOKEN']}".encode()).decode()
    assert actual["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {encoded}"
    assert encoded not in result.stdout + result.stderr
    assert actual["WORKSTATION_MANAGER_INTERACTIVE"] == str(int(terminal))
    assert bool(actual["WORKSTATION_MANAGER_TTY"]) == terminal
    assert actual["WORKSTATION_MANAGER_TTY"] != environment["WORKSTATION_MANAGER_TTY"]
    assert actual["BITWARDEN_EMAIL"] == ""
    assert invocation["stdin_tty"] == terminal
    for name in (
        "BITWARDEN_CLIENT_ID",
        "BITWARDEN_CLIENT_SECRET",
        "BITWARDEN_PASSWORD",
        "WORKSTATION_MANAGER_GITHUB_TOKEN",
        "WORKSTATION_MANAGER_GHCR_TOKEN",
    ):
        assert actual[name] == environment[name]
        assert environment[name] not in result.stdout + result.stderr
    action = arguments[0] if arguments else "setup"
    assert f"ansible/{action}.yml" in invocation["args"]
    assert ("--check" in invocation["args"]) == ("--dry-run" in arguments)
    assert ("--diff" in invocation["args"]) == ("--dry-run" in arguments)
    if action == "backup":
        assert actual["WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR"] == environment["WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR"]
    if action == "setup":
        assert actual["WORKSTATION_MANAGER_RESTORE_ARCHIVE"] == environment["WORKSTATION_MANAGER_RESTORE_ARCHIVE"]
    assert ("Workstation command completed" in result.stdout) == (status == 0)
