"""Run authentication modules through Ansible against disposable native-client fixtures."""

import sys

import pytest
from ansible_test_helpers import ansible_environment, run_playbook, write_local_playbook

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("state", ["available", "missing", "api_key", "preview"])
def test_provider_authentication_respects_persistent_login_and_preview(tmp_path, state):
    """The real module reports stored login, fails missing login and launches nothing in previews."""
    calls = tmp_path / "calls"
    executable = tmp_path / "codex"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:] == ['login', 'status']\n"
        "assert 'OPENAI_API_KEY' not in os.environ\n"
        f"Path({str(calls)!r}).touch()\n"
        + ("print('Not logged in', file=sys.stderr)\nsys.exit(1)\n" if state == "missing" else "")
        + (
            "print('Logged in using an API key - synthetic-private-marker', file=sys.stderr)\n"
            if state == "api_key"
            else "print('Logged in using ChatGPT', file=sys.stderr)\n"
        )
    )
    executable.chmod(0o700)
    task = {
        "neilime.workstation_setup.ai_provider_auth": {
            "home": str(tmp_path),
            "provider": "codex",
            "executable": str(executable),
        },
        "register": "login",
    }
    assertion = {
        "ansible.builtin.assert": {
            "that": [
                "not login.changed",
                "login.deferred == ansible_check_mode",
                "login.authenticated != ansible_check_mode",
            ]
        }
    }
    playbook = write_local_playbook(tmp_path / "auth.json", [task, assertion], {})
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)] + (["--check"] if state == "preview" else [])
    result = run_playbook(command, ansible_environment(tmp_path), cwd=tmp_path)
    assert "synthetic-private-marker" not in result.stdout + result.stderr
    if state in {"missing", "api_key"}:
        assert result.returncode != 0
        assert "run codex login" in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "changed=0" in result.stdout
    assert calls.exists() == (state != "preview")


def test_inaccessible_ai_client_reports_the_concrete_access_failure(tmp_path):
    """An unreachable client surfaces the concrete OS error and failing path for diagnosis."""
    missing = tmp_path / "absent-codex"
    task = {
        "neilime.workstation_setup.ai_provider_auth": {
            "home": str(tmp_path),
            "provider": "codex",
            "executable": str(missing),
        },
        "register": "login",
    }
    playbook = write_local_playbook(tmp_path / "auth.json", [task], {})
    result = run_playbook(
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        ansible_environment(tmp_path),
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "Cannot access the AI client or terminal" in result.stdout
    assert "absent-codex" in result.stdout


@pytest.mark.parametrize("state", ["available", "denied", "preview"])
def test_mcp_credentials_and_access_checks_remain_private(tmp_path, state):
    """Resolved credentials reach only the server, and service failures cannot pass discovery checks."""
    calls = tmp_path / "calls"
    server = tmp_path / "server.py"
    response = "authorized" if state == "available" else "synthetic-private-marker: denied"
    server.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "assert os.environ['TOKEN'] == 'synthetic-private-marker'\n"
        f"Path({str(calls)!r}).touch()\n"
        "print('synthetic-private-marker', file=sys.stderr)\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if 'id' not in request: continue\n"
        "    if request['method'] == 'initialize':\n"
        "        result = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}}}\n"
        "    elif request['method'] == 'tools/list':\n"
        "        result = {'tools': [{'name': 'whoami'}]}\n"
        "    else:\n"
        "        assert request['method'] == 'tools/call'\n"
        f"        result = {{'content': [{{'type': 'text', 'text': {response!r}}}]}}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)\n"
    )
    task = {
        "neilime.workstation_setup.ai_mcp_probe": {
            "home": str(tmp_path),
            "servers": {
                "service": {
                    "command": sys.executable,
                    "args": [str(server)],
                    "env": {"TOKEN": "synthetic-private-marker"},
                }
            },
            "authentication_checks": {"service": {"tool": "whoami", "arguments": {}, "expect_text": "authorized"}},
        },
        "register": "probe",
    }
    assertion = {
        "ansible.builtin.assert": {
            "that": [
                "not probe.changed",
                "probe.access_verified | length == (0 if ansible_check_mode else 1)",
                "probe.deferred | length == (1 if ansible_check_mode else 0)",
            ]
        }
    }
    playbook = write_local_playbook(tmp_path / "probe.json", [task, assertion], {})
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)] + (["--check"] if state == "preview" else [])
    result = run_playbook(command, ansible_environment(tmp_path), cwd=tmp_path)
    assert "synthetic-private-marker" not in result.stdout + result.stderr
    if state == "denied":
        assert result.returncode != 0
        assert "authentication/access verification failed" in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "changed=0" in result.stdout
    assert calls.exists() == (state != "preview")
