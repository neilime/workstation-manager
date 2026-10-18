"""Exercise shared bootstrap behavior with interactive and automation inputs."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from entrypoint_test_helpers import (
    entrypoint_source_with_mock_controller,
    terminal_command,
)

ROOT = Path(__file__).parents[2]


@pytest.fixture(name="input_runner")
def input_runner_fixture(tmp_path):
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
        '         "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0",\n'
        '         "WORKSTATION_MANAGER_TTY", "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR",\n'
        '         "WORKSTATION_MANAGER_RESTORE_ARCHIVE"]\n'
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
        "WORKSTATION_MANAGER_TTY": "/dev/inherited-terminal",
        "WORKSTATION_MANAGER_INTERACTIVE": "1",
        "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR": str(tmp_path / "backup's files"),
        "WORKSTATION_MANAGER_RESTORE_ARCHIVE": str(tmp_path / "restore's archive.tar.gz"),
        "TEST_INVOCATION": str(tmp_path / "invocation.json"),
        "TEST_SUDO_CALLED": str(tmp_path / "sudo-called"),
    }
    return script, environment


@pytest.mark.parametrize(
    "arguments,terminal,status",
    [
        (["setup", "--dry-run"], False, 0),
        (["backup"], False, 0),
        (["cleanup", "--dry-run"], False, 23),
        pytest.param([], True, 0, marks=pytest.mark.integration, id="prefilled-inputs-with-terminal"),
    ],
)
def test_supplied_inputs_use_the_shared_bootstrap(input_runner, arguments, terminal, status):
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


@pytest.mark.parametrize(
    "missing",
    ["BITWARDEN_CLIENT_ID", "BITWARDEN_CLIENT_SECRET", "BITWARDEN_PASSWORD", "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR"],
)
def test_missing_inputs_without_a_terminal_stop_before_the_action(input_runner, missing):
    """Unattended calls fail before the workstation action when required input cannot be collected."""
    script, environment = input_runner
    del environment[missing]
    result = subprocess.run(
        ["sh", str(script), "backup"],
        env=environment,
        capture_output=True,
        text=True,
        start_new_session=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert missing in result.stderr
    assert "fixture-client-secret" not in result.stdout + result.stderr
    assert Path(environment["TEST_SUDO_CALLED"]).exists() == (missing != "WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR")
    assert not Path(environment["TEST_INVOCATION"]).exists()


def test_terminal_prompts_complete_missing_credentials(tmp_path):
    """Incomplete automation credentials fall back to the same account prompts, independent of CI flags."""
    definitions = (ROOT / "workstation.sh").read_text().rsplit('main "$@"', 1)[0]
    result = subprocess.run(
        ["sh", "-s"],
        input=definitions
        + r"""
has_interactive_terminal() { return 0; }
prompt_for_required_value() {
    case "$1" in
    BITWARDEN_EMAIL) printf fixture@example.test ;;
    BITWARDEN_PASSWORD) printf entered-password ;;
    *) exit 99 ;;
    esac
}
prepare_action_dependencies() { :; }
run_ansible_pull_with_bitwarden_retry() {
    [ "$PROMPTED_BITWARDEN_EMAIL" = fixture@example.test ] || exit 91
    [ "$BITWARDEN_PASSWORD_VALUE" = entered-password ] || exit 92
    [ -z "$BITWARDEN_CLIENT_ID_VALUE$BITWARDEN_CLIENT_SECRET_VALUE" ] || exit 93
}
main setup
""",
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "CI": "true",
            "BITWARDEN_CLIENT_ID": "ambient-client",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "prompting for credentials" in result.stdout
    for secret in ("ambient-client", "entered-password"):
        assert secret not in result.stdout + result.stderr


def test_reusable_bitwarden_session_detection_prefers_unlocked_vaults(tmp_path):
    """The session probe reuses an unlocked vault and falls back to prompting when it is locked."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sudo").write_text('#!/bin/sh\nshift 2\nexec "$@"\n')
    (bin_dir / "sudo").chmod(0o755)
    (bin_dir / "bw").write_text(
        "#!/bin/sh\n"
        '[ "$1" = status ] || exit 2\n'
        'printf \'{"status":"%s","serverUrl":"https://x"}\' "${FIXTURE_BW_STATUS:-locked}"\n'
    )
    (bin_dir / "bw").chmod(0o755)
    definitions = (ROOT / "workstation.sh").read_text().rsplit('main "$@"', 1)[0]
    probe = (
        definitions
        + '\nTARGET_USER=tester\nTARGET_USER_HOME="$HOME"\n'
        + "if reusable_bitwarden_session_available; then echo DECISION=reuse; else echo DECISION=prompt; fi\n"
    )
    for status, expected in (("unlocked", "reuse"), ("locked", "prompt")):
        result = subprocess.run(
            ["sh", "-s"],
            input=probe,
            env={
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "HOME": str(tmp_path),
                "BW_SESSION": "fixture-session",
                "FIXTURE_BW_STATUS": status,
            },
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert f"DECISION={expected}" in result.stdout, f"{status}: {result.stdout}{result.stderr}"


def test_terminal_prompts_are_skipped_when_a_session_is_reused(tmp_path):
    """A reusable session is passed to Ansible without prompting for Bitwarden credentials."""
    definitions = (ROOT / "workstation.sh").read_text().rsplit('main "$@"', 1)[0]
    result = subprocess.run(
        ["sh", "-s"],
        input=definitions
        + r"""
has_interactive_terminal() { return 0; }
reusable_bitwarden_session_available() { BITWARDEN_SESSION_VALUE=reused-session; return 0; }
prompt_for_bitwarden_login() { echo PROMPT_SHOULD_NOT_RUN; exit 90; }
prepare_action_dependencies() { :; }
run_ansible_pull_with_bitwarden_retry() {
    [ "$BITWARDEN_SESSION_VALUE" = reused-session ] || exit 91
    [ -z "$PROMPTED_BITWARDEN_EMAIL" ] || exit 92
}
main setup
""",
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "will reuse the unlocked Bitwarden CLI session" in result.stdout
    assert "PROMPT_SHOULD_NOT_RUN" not in result.stdout


@pytest.mark.parametrize("arguments", [["help"], ["--help"], ["backup", "--help"]])
def test_help_requires_neither_credentials_nor_terminal(arguments):
    """Help documents normal usage without requiring credentials or a terminal."""
    result = subprocess.run(
        ["sh", str(ROOT / "workstation.sh"), *arguments],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Optional user inputs" in result.stdout
    for automation_input in (
        "BITWARDEN_CLIENT_ID",
        "BITWARDEN_CLIENT_SECRET",
        "BITWARDEN_PASSWORD",
        "WORKSTATION_MANAGER_GITHUB_TOKEN",
        "REPOSITORY_URL",
        "REPOSITORY_BRANCH",
        "WORKSTATION_MANAGER_PRIVATE_OVERRIDE_FILE",
    ):
        assert automation_input not in result.stdout


@pytest.mark.parametrize("transport,action", [("attached", "backup"), ("detached", "cleanup")])
def test_vm_transports_use_the_public_action(tmp_path, transport, action):
    """Both VM transports call the public action with no alternative execution options."""
    arguments = tmp_path / "arguments"
    result = subprocess.run(
        ["bash", "-s", "--", str(ROOT / "e2e-tests/e2e-common.sh")],
        input=r"""
set -eu
source "$1"
stream_e2e_entrypoint_script() { printf 'printf "%%s\\n" "$@" >"$TEST_ARGUMENTS"\n'; }
run_e2e_lima_shell() { "$@"; }
run_e2e_lima_control_command() {
    shift
    case "$1" in
    id) printf fixture ;;
    env) printf /home/fixture ;;
    sh) cat >/dev/null ;;
    sudo)
        case "$3" in
        systemd-run) printf '%s\n' "$@" >"$TEST_ARGUMENTS" ;;
        systemctl)
            if [ "$4" = show ]; then
                printf 'ActiveState=active\nSubState=exited\nResult=success\nExecMainStatus=0\n'
            fi
            ;;
        journalctl) : ;;
        *) return 99 ;;
        esac
        ;;
    rm) : ;;
    *) return 99 ;;
    esac
}
if [ "$TEST_TRANSPORT" = attached ]; then
    run_e2e_workstation_action "$TEST_ACTION"
else
    run_e2e_detached_workstation_action "$TEST_ACTION"
fi
""",
        env={
            "PATH": os.environ["PATH"],
            "TEST_ARGUMENTS": str(arguments),
            "TEST_TRANSPORT": transport,
            "TEST_ACTION": action,
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    captured = arguments.read_text().splitlines()
    action_arguments = captured if transport == "attached" else captured[captured.index("/bin/sh") + 2 :]
    assert action_arguments == [action]
