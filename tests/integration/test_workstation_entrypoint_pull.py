"""Exercise remote bootstrap host selection with real Ansible and a disposable Git repository."""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from ansible_test_helpers import ansible_environment, write_local_playbook

ENTRYPOINT = Path(__file__).parents[2] / "workstation.sh"


@pytest.mark.parametrize("fail", [False, True])
def test_remote_pull_ignores_hostname_aliases_and_preserves_task_diagnostics(tmp_path, fail):
    """Checkout and execution use localhost without hostname warnings, while task warnings and errors remain visible."""
    source = tmp_path / "source"
    source.mkdir()
    library = source / "library"
    library.mkdir()
    (library / "fixture_probe.py").write_text(
        "from ansible.module_utils.basic import AnsibleModule\n"
        "module = AnsibleModule(argument_spec={'fail': {'type': 'bool'}})\n"
        "module.warn('Fixture task warning remains visible')\n"
        "if module.params['fail']:\n"
        "    module.fail_json(msg='Fixture task failure remains visible')\n"
        "module.exit_json(changed=False)\n"
    )
    write_local_playbook(
        source / "playbook.yml",
        [
            {"ansible.builtin.assert": {"that": ["ansible_play_hosts_all == ['localhost']"]}},
            {"fixture_probe": {"fail": fail}},
        ],
        {},
    )
    environment = ansible_environment(tmp_path, GIT_CONFIG_NOSYSTEM="1")
    for arguments in (
        ["init", "--initial-branch=fixture"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "--no-gpg-sign",
            "-m",
            "fixture",
        ],
    ):
        subprocess.run(["git", *arguments], cwd=source, env=environment, capture_output=True, check=True, timeout=10)
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(remote)],
        env=environment,
        capture_output=True,
        check=True,
        timeout=10,
    )
    controller = tmp_path / "controller"
    binary = controller / "bin"
    binary.mkdir(parents=True)
    for command in ("ansible", "ansible-playbook"):
        # Keep diagnostics on one stream so pull's bytewise relay cannot interleave their text.
        client = binary / command
        client.write_text(f'#!/bin/sh\nexec {shlex.quote(shutil.which(command))} "$@" 2>&1\n')
        client.chmod(0o700)
    # Make the workstation names deterministic while retaining Ansible's real checkout and execution.
    pull = binary / "ansible-pull"
    pull.write_text(
        f"#!{sys.executable}\n"
        "from ansible.cli.pull import PullCLI\n"
        "import platform, socket\n"
        "platform.node = lambda: 'fixture-workstation'\n"
        "socket.getfqdn = lambda: 'fixture-workstation.example.test'\n"
        "PullCLI.cli_executor()\n"
    )
    pull.chmod(0o700)
    checkout = tmp_path / "checkout"
    result = subprocess.run(
        ["sh", "-s"],
        input=ENTRYPOINT.read_text().rsplit('main "$@"', 1)[0]
        + '\nANSIBLE_VENV_DIR="$TEST_CONTROLLER"\n'
        + 'ANSIBLE_CHECKOUT_DIR="$TEST_CHECKOUT"\n'
        + 'TARGET_USER="$(id -un)"\nTARGET_USER_HOME="$HOME"\n'
        + 'COLLECTIONS_INSTALL_DIR="$HOME/.ansible/collections"\n'
        + "has_interactive_terminal() { return 1; }\nrun_ansible_pull playbook.yml 0\n",
        env={
            **environment,
            "REPOSITORY_URL": remote.as_uri(),
            "REPOSITORY_BRANCH": "fixture",
            "WORKSTATION_MANAGER_SKIP_SUDO": "1",
            "TEST_CONTROLLER": str(controller),
            "TEST_CHECKOUT": str(checkout),
        },
        capture_output=True,
        text=True,
        check=False,
        start_new_session=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    assert (result.returncode != 0) == fail, output
    assert "Fixture task warning remains visible" in output, output
    assert ("Fixture task failure remains visible" in output) == fail
    assert "Could not match supplied host pattern" not in output
    assert not checkout.exists()
