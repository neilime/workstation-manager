"""Exercise shared bootstrap behavior with interactive and automation inputs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from entrypoint_input_helpers import assert_supplied_inputs, prepare_input_runner

ROOT = Path(__file__).parents[2]


@pytest.fixture(name="input_runner")
def input_runner_fixture(tmp_path):
    """Prepare isolated controller and credential inputs for shell contracts."""
    return prepare_input_runner(tmp_path)


@pytest.mark.parametrize(
    "arguments,status",
    [(["setup", "--dry-run"], 0), (["backup"], 0), (["cleanup", "--dry-run"], 23)],
)
def test_supplied_inputs_use_the_shared_bootstrap(input_runner, arguments, status):
    """Unattended bootstrap preserves supplied inputs, action options, and failures."""
    assert_supplied_inputs(input_runner, arguments, terminal=False, status=status)


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
