"""Verify the VM assertion runner with the real pytest SSH backend."""

from __future__ import annotations

import os
import pathlib
import shlex
import shutil
import subprocess

E2E_PATH = pathlib.Path(__file__).parents[2] / "e2e-tests"


def test_assertions_keep_ssh_sockets_outside_read_only_lima_state(tmp_path: pathlib.Path) -> None:
    """Pytest's real SSH backend overrides the socket while retaining Lima's connection options."""

    config = tmp_path / "lima.config"
    original = "Host *\n  User fixture-user\n  ControlMaster auto\n  ControlPath /read-only-lima/ssh.sock\n"
    config.write_text(original)
    config.chmod(0o400)
    effective_config = tmp_path / "effective-config"
    ssh_executable = shutil.which("ssh")
    assert ssh_executable is not None
    ssh = tmp_path / "ssh"
    ssh.write_text(
        f'#!/bin/sh\nset -eu\n{shlex.quote(ssh_executable)} -G "$@" >"$TEST_SSH_CONFIG"\nprintf \'fixture\\n\'\n'
    )
    ssh.chmod(0o700)
    test = tmp_path / "test_connection.py"
    test.write_text('def test_connection(host):\n    assert host.check_output("true") == "fixture"\n')
    subprocess.run(
        ["bash", str(E2E_PATH / "run-assertions.sh"), str(config), "-q", "--hosts=ssh://fixture", str(test)],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "TEST_SSH_CONFIG": str(effective_config)},
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    settings = dict(line.split(" ", 1) for line in effective_config.read_text().splitlines())
    assert pathlib.Path(settings["controlpath"]).parent == pathlib.Path("/tmp")
    assert settings["controlmaster"] == "auto"
    assert settings["user"] == "fixture-user"
    assert config.read_text() == original
