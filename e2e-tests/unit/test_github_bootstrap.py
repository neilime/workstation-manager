"""Exercise GitHub bootstrap and account verification through isolated Ansible runs."""

import json
import sys
from pathlib import Path

import pytest
from ansible_test_helpers import (
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)
from entrypoint_test_helpers import terminal_command

ROOT = Path(__file__).parents[2]
COLLECTION = ROOT / "ansible/collections/ansible_collections/neilime/workstation_setup"
pytestmark = pytest.mark.integration
TOKEN = "synthetic-github-credential"


@pytest.fixture(name="github_environment")
def github_environment_fixture(tmp_path):
    """Replace native clients and package installation while retaining the real auth module and playbook."""
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json, os, subprocess, sys
from pathlib import Path
home = Path(os.environ['HOME'])
args = sys.argv[1:]
assert not any(os.environ.get(name) for name in ('GH_TOKEN', 'GITHUB_TOKEN'))
with (home / 'calls').open('a') as log:
    log.write(json.dumps(args) + '\n')
state = home / 'login'
if args[:2] == ['auth', 'status']:
    entries = [dict(state='success', active=True, login='fixture', tokenSource='keyring')] if state.exists() else []
    print(json.dumps({'hosts': {'github.com': entries}}))
elif args[:2] == ['auth', 'login']:
    if '--web' in args:
        assert all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr))
        print('Approve GitHub sign-in', flush=True)
        assert input() == 'approved'
    else:
        assert '--with-token' in args
        assert sys.stdin.read() == 'synthetic-github-credential'
    state.touch()
elif args[:2] == ['auth', 'setup-git']:
    helper = '!' + str(Path(sys.argv[0])) + ' auth git-credential'
    subprocess.run(['git', 'config', '--file', os.environ['GIT_CONFIG_GLOBAL'],
                    'credential.https://github.com.helper', helper], check=True)
else:
    raise SystemExit('Unexpected GitHub command')
"""
    )
    gh.chmod(0o700)
    secret_tool = tmp_path / "secret-tool"
    secret_tool.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\nfrom pathlib import Path\n"
        "probe = Path(os.environ['HOME']) / 'probe'\n"
        "if sys.argv[1] == 'store': probe.write_text(sys.stdin.read())\n"
        "elif sys.argv[1] == 'lookup': print(probe.read_text())\n"
        "elif sys.argv[1] == 'clear': probe.unlink()\n"
        "else: raise SystemExit('Unexpected credential-store command')\n"
    )
    secret_tool.chmod(0o700)
    collection_root = tmp_path / "collections"
    isolated = collection_root / "ansible_collections/neilime/workstation_setup"
    for relative in (
        "plugins/modules/github_auth.py",
        "plugins/module_utils/github_auth.py",
        "plugins/module_utils/desktop_session.py",
    ):
        destination = isolated / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = (COLLECTION / relative).read_text()
        source = source.replace("/usr/bin/gh", str(gh)).replace('"secret-tool"', repr(str(secret_tool)))
        destination.write_text(source)
    tasks = isolated / "roles/development_tooling/tasks"
    tasks.mkdir(parents=True)
    (tasks / "github_cli.yml").write_text(
        json.dumps(
            [
                {"ansible.builtin.stat": {"path": str(gh)}, "register": "fixture_cli"},
                {"ansible.builtin.assert": {"that": ["fixture_cli.stat.executable"]}},
            ]
        )
    )
    (tasks / "github_auth.yml").write_text((COLLECTION / "roles/development_tooling/tasks/github_auth.yml").read_text())
    # Playbook-adjacent collections take precedence over environment paths.
    # Run the unchanged playbook beside the isolated clients and installer boundary.
    (tmp_path / "github_bootstrap.yml").write_text((ROOT / "ansible/github_bootstrap.yml").read_text())
    variables = tmp_path / "group_vars"
    variables.mkdir()
    (variables / "all.yml").write_text((ROOT / "ansible/group_vars/all.yml").read_text())
    environment = ansible_environment(
        tmp_path,
        WORKSTATION_MANAGER_USE_BECOME="false",
        WORKSTATION_MANAGER_USER=managed_user(tmp_path)["name"],
        WORKSTATION_MANAGER_USER_HOME=str(tmp_path),
        GH_TOKEN="inherited-token-must-not-be-used",
        GIT_CONFIG_NOSYSTEM="1",
    )
    environment["ANSIBLE_COLLECTIONS_PATH"] = str(collection_root) + ":" + environment["ANSIBLE_COLLECTIONS_PATH"]
    return environment


@pytest.mark.parametrize("method", ["browser", "token"])
def test_bootstrap_login_is_reused_and_checked_against_private_account(tmp_path, github_environment, method):
    """Browser and token login persist before private config, then account checks reuse the saved credentials."""
    environment = github_environment
    command = [
        "ansible-playbook",
        "-i",
        "localhost,",
        str(tmp_path / "github_bootstrap.yml"),
        "-e",
        f"ansible_python_interpreter={sys.executable}",
    ]
    if method == "token":
        environment["WORKSTATION_MANAGER_GITHUB_TOKEN"] = TOKEN
        result = run_playbook(command, environment, cwd=tmp_path)
    else:
        # Give the module a real terminal without attaching it to the pytest session.
        command = terminal_command(
            [
                "sh",
                "-c",
                'export WORKSTATION_MANAGER_INTERACTIVE=1 WORKSTATION_MANAGER_TTY="$(tty)"; exec "$@"',
                "sh",
                *command,
            ]
        )
        result = run_playbook(
            command,
            environment,
            cwd=tmp_path,
            input_text="approved\n",
            start_new_session=True,
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert TOKEN not in result.stdout + result.stderr
    assert (tmp_path / "login").exists()
    assert not (tmp_path / "probe").exists()
    environment.pop("WORKSTATION_MANAGER_GITHUB_TOKEN", None)
    for account in ("fixture", "other"):
        playbook = write_local_playbook(
            tmp_path / "verify.json",
            [
                {
                    "ansible.builtin.import_role": {
                        "name": "neilime.workstation_setup.development_tooling",
                        "tasks_from": "github_auth",
                    }
                }
            ],
            {
                "workstation_manager_use_become": False,
                "workstation_manager_resolved": {
                    "user": managed_user(tmp_path),
                    "development": {"github": {"host": "github.com", "account": account}},
                },
            },
        )
        checked = run_playbook(["ansible-playbook", "-i", "localhost,", str(playbook)], environment, cwd=tmp_path)
        if account == "fixture":
            assert checked.returncode == 0, checked.stdout + checked.stderr
            assert "changed=0" in checked.stdout
        else:
            assert checked.returncode != 0
            assert "configured GitHub account" in checked.stdout
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    assert sum(call[:2] == ["auth", "login"] for call in calls) == 1
    assert any(call[:2] == ["auth", "setup-git"] for call in calls)
