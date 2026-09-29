"""Keep numeric Docker users resolvable without relying on host home directories."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).parents[2]


@pytest.mark.parametrize("uid,gid", [(os.getuid(), os.getgid()), (12345, 12346)])
@pytest.mark.parametrize("status", [0, 47])
def test_tooling_account_and_cleanup(tmp_path: Path, uid: int, gid: int, status: int) -> None:
    """The launched process sees a usable account, and failures still clean up account files."""

    trace = tmp_path / "trace.json"
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "assert args[0] == 'run'\n"
        "uid, gid = map(int, args[args.index('--user') + 1].split(':'))\n"
        "mounts = [args[i + 1].split(':') for i, value in enumerate(args) if value == '--volume']\n"
        "accounts = {}\n"
        "for source, target, mode in mounts:\n"
        "    assert mode == 'ro'\n"
        "    path = pathlib.Path(source)\n"
        "    assert path.stat().st_mode & 0o444 == 0o444\n"
        "    assert path.parent.stat().st_mode & 0o111 == 0o111\n"
        "    records = [line.split(':') for line in path.read_text().splitlines()]\n"
        "    number = uid if target == '/etc/passwd' else gid\n"
        "    matches = [record for record in records if int(record[2]) == number]\n"
        "    assert len(matches) == 1\n"
        "    assert sum(record[0] == matches[0][0] for record in records) == 1\n"
        "    accounts[target] = matches[0]\n"
        "assert accounts['/etc/passwd'][3] == str(gid)\n"
        "assert accounts['/etc/passwd'][5:] == ['/tmp', '/bin/bash']\n"
        "assert args[-3:] == ['fixture-image', 'bash', '-i']\n"
        "pathlib.Path(os.environ['TEST_TRACE']).write_text(json.dumps(mounts))\n"
        "sys.exit(int(os.environ['TEST_STATUS']))\n"
    )
    docker.chmod(0o755)
    originals = {path: path.read_bytes() for path in (Path("/etc/passwd"), Path("/etc/group"))}
    result = subprocess.run(
        [
            "bash",
            str(WORKSPACE / "ci/run-tooling.sh"),
            str(uid),
            str(gid),
            "--rm",
            "fixture-image",
            "bash",
            "-i",
        ],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "TEST_TRACE": str(trace),
            "TEST_STATUS": str(status),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == status, result.stdout + result.stderr
    for source, _target, _mode in json.loads(trace.read_text()):
        assert not Path(source).parent.exists()
    assert {path: path.read_bytes() for path in originals} == originals
