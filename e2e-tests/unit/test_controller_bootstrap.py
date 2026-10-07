"""Verify that bootstrap installs the repository's isolated controller runtime."""

from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
import sys

import pytest
from entrypoint_test_helpers import sudo_passthrough_script

ROOT = pathlib.Path(__file__).parents[2]


@pytest.mark.parametrize("failed_command", ["", "apt-get", "python3", "python"])
def test_bootstrap_uses_shared_manifest_even_with_system_ansible(tmp_path: pathlib.Path, failed_command: str) -> None:
    """An arbitrary existing Ansible command must not bypass the tested runtime."""
    repository = tmp_path / "repository"
    (repository / "ansible").mkdir(parents=True)
    for name in ("requirements.txt", "ubuntu-version"):
        (repository / "ansible" / name).write_text((ROOT / "ansible" / name).read_text())
    commands = tmp_path / "bin"
    commands.mkdir()
    controller = tmp_path / "controller"
    (controller / "bin").mkdir(parents=True)
    log = tmp_path / "commands.log"
    logger = (
        '#!/bin/sh\nprintf "%s\\n" "$0 $*" >>"$TEST_COMMAND_LOG"\n'
        'if [ "${0##*/}" = "$TEST_FAILED_COMMAND" ]; then exit 23; fi\n'
    )
    for name in ("apt-get", "python3", "ansible-playbook", "ansible-pull"):
        path = commands / name
        path.write_text(logger)
        path.chmod(0o700)
    python = controller / "bin/python"
    python.write_text(logger + 'if [ "${3:-}" = install ]; then cat "$6" >>"$TEST_COMMAND_LOG"; fi\n')
    python.chmod(0o700)
    sudo = commands / "sudo"
    sudo.write_text(sudo_passthrough_script('if [ "$1" = "-v" ]; then exit 0; fi\n', suffix='exec env "$@"\n'))
    sudo.chmod(0o700)
    definitions = (ROOT / "workstation.sh").read_text().rsplit('main "$@"', 1)[0]
    # Exercise the real guard against a fixture OS, independent of the test host.
    os_release = tmp_path / "os-release"
    os_release.write_text(f"ID=ubuntu\nVERSION_ID={(ROOT / 'ansible/ubuntu-version').read_text().strip()}\n")
    definitions = definitions.replace(". /etc/os-release", f". {shlex.quote(str(os_release))}")
    result = subprocess.run(
        ["sh", "-s"],
        input=definitions
        + f"\nREPOSITORY_URL={shlex.quote(str(repository))}\n"
        + f"ANSIBLE_VENV_DIR={shlex.quote(str(controller))}\n"
        + "if install_ansible_packages; then exit 0; else exit $?; fi\n",
        env={
            **os.environ,
            "PATH": f"{commands}:/usr/bin:/bin",
            "TMPDIR": str(tmp_path),
            "TEST_COMMAND_LOG": str(log),
            "TEST_FAILED_COMMAND": failed_command,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    calls = log.read_text()
    assert not list(tmp_path.glob("workstation-manager-bootstrap-*"))
    if failed_command:
        assert result.returncode != 0, result.stdout + result.stderr
        assert calls.splitlines()[-1].split()[0].endswith(f"/{failed_command}")
        assert "-m pip check" not in calls
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{controller}/bin/python -m pip install" in calls
    assert (ROOT / "ansible/requirements.txt").read_text().strip() in calls
    assert "-m pip check" in calls
    assert "ansible-playbook" not in calls


def test_unsupported_ubuntu_fails_before_package_installation(tmp_path: pathlib.Path) -> None:
    """The release guard rejects a mismatched baseline without running APT."""
    (tmp_path / "ansible").mkdir()
    (tmp_path / "ansible/ubuntu-version").write_text("00.00\n")
    (tmp_path / "ansible/requirements.txt").write_text((ROOT / "ansible/requirements.txt").read_text())
    commands = tmp_path / "bin"
    commands.mkdir()
    sudo = commands / "sudo"
    sudo.write_text('#!/bin/sh\ntouch "$TEST_PACKAGE_MARKER"\nexit 99\n')
    sudo.chmod(0o700)
    marker = tmp_path / "packages-touched"
    definitions = (ROOT / "workstation.sh").read_text().rsplit('main "$@"', 1)[0]
    result = subprocess.run(
        ["sh", "-s"],
        input=definitions + f"\nREPOSITORY_URL={shlex.quote(str(tmp_path))}\ninstall_ansible_packages\n",
        env={**os.environ, "PATH": f"{commands}:/usr/bin:/bin", "TEST_PACKAGE_MARKER": str(marker)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert "requires Ubuntu 00.00" in result.stderr
    assert not marker.exists()


def test_private_caller_can_install_a_shared_controller(tmp_path: pathlib.Path) -> None:
    """A private fixture's umask must not hide the root-owned controller from users."""
    commands = tmp_path / "bin"
    commands.mkdir()
    sudo = commands / "sudo"
    sudo.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = python3 ]; then\n'
        '  shift; exec "$TEST_PYTHON" "$@" --without-pip\n'
        "fi\n"
        "# Stand in for pip; the real venv above exercises directory permissions.\n"
        'if [ "${4:-}" = install ]; then\n'
        '  printf "# package fixture\\n" >"$TEST_CONTROLLER/lib/package.py"\n'
        "fi\n"
    )
    sudo.chmod(0o700)
    controller = tmp_path / "shared/controller"
    definitions = (ROOT / "workstation.sh").read_text().rsplit('main "$@"', 1)[0]
    result = subprocess.run(
        ["sh", "-s"],
        input=definitions
        + "\ninstall_bootstrap_packages() { :; }\nvalidate_supported_ubuntu() { :; }\n"
        + f"REPOSITORY_URL={shlex.quote(str(ROOT))}\n"
        + f"ANSIBLE_VENV_DIR={shlex.quote(str(controller))}\n"
        + 'umask 077\ninstall_ansible_packages\n: >"$TMPDIR/private-after-bootstrap"\n',
        env={
            **os.environ,
            "PATH": f"{commands}:/usr/bin:/bin",
            "TMPDIR": str(tmp_path),
            "TEST_PYTHON": sys.executable,
            "TEST_CONTROLLER": str(controller),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for directory in (controller.parent, controller, controller / "bin", controller / "lib"):
        assert directory.stat().st_mode & 0o777 == 0o755, directory
    for file in (controller / "pyvenv.cfg", controller / "lib/package.py"):
        assert file.stat().st_mode & 0o777 == 0o644, file
    assert (tmp_path / "private-after-bootstrap").stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("workstation-manager-bootstrap-*"))
