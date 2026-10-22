"""Exercise registry credential handling through the real isolated Ansible module."""

import json
import shlex
import sys
from pathlib import Path

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)
from entrypoint_test_helpers import terminal_command

COLLECTION = Path(__file__).parents[2] / "ansible/collections/ansible_collections/neilime/workstation_setup"
TOKEN = "synthetic-registry-credential"


@pytest.fixture(name="registry_environment")
def registry_environment_fixture(tmp_path):
    """Keep real module execution while replacing registry and keyring clients."""
    client = tmp_path / "client.py"
    client.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json, os, shlex, subprocess, sys
from pathlib import Path
home = Path(os.environ['HOME'])
args = sys.argv[1:]
name = Path(sys.argv[0]).name
assert not any(key.startswith('DOCKER_') for key in os.environ)
assert not os.environ.get('GH_TOKEN')
assert not os.environ.get('WORKSTATION_MANAGER_GHCR_TOKEN')
with (home / 'calls').open('a') as log:
    log.write(json.dumps([name, *args]) + '\n')
credential = home / 'credential'
token = 'synthetic-registry-credential'
if name == 'gh':
    if args[:2] == ['auth', 'status']:
        needs_scopes = any((home / marker).exists() for marker in ('separate-token', 'refresh-scopes'))
        scopes = 'repo' if needs_scopes else 'repo, write:packages'
        print(json.dumps({'hosts': {'github.com': [dict(state='success', active=True,
              login='fixture', tokenSource='keyring', scopes=scopes)]}}))
    elif args == ['config', 'get', 'browser']:
        print('')
    elif args[:2] == ['auth', 'refresh']:
        assert all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr))
        print('One-time code: fixture-code', file=sys.stderr, flush=True)
        print('Press Enter to open https://github.com/login/device', flush=True)
        assert input() == 'approved'
        opened = subprocess.run([*shlex.split(os.environ['GH_BROWSER']), 'https://github.com/login/device'],
                                check=False)
        if opened.returncode:
            print('Failed opening a web browser; open https://github.com/login/device manually', file=sys.stderr)
        (home / 'refresh-scopes').unlink()
    elif args[:2] == ['auth', 'token']:
        assert not (home / 'separate-token').exists(), 'Registry login must not read the user token'
        assert args[-2:] == ['--user', 'fixture']
        print(token)
    else:
        raise SystemExit('Unexpected GitHub operation')
elif name == 'docker':
    assert args[0] == '--config' and args[2:] == ['login', 'ghcr.io', '--username', 'fixture', '--password-stdin']
    assert sys.stdin.read() == token
    assert json.loads((Path(args[1]) / 'config.json').read_text()) == {'credHelpers': {'ghcr.io': 'secretservice'}}
    if (home / 'reject').exists():
        raise SystemExit(token)
    credential.write_text(json.dumps({'Username': 'fixture', 'Secret': token}))
elif name == 'helper':
    assert args == ['get'] and sys.stdin.read() == 'ghcr.io\n'
    if not credential.exists():
        raise SystemExit('credentials not found in native keychain')
    print(credential.read_text())
elif name == 'secret-tool':
    probe = home / 'probe'
    if args[0] == 'store': probe.write_text(sys.stdin.read())
    elif args[0] == 'lookup': print(probe.read_text())
    elif args[0] == 'clear': probe.unlink()
    else: raise SystemExit('Unexpected keyring operation')
elif name == 'browser':
    assert args == ['--profile', 'literal $HOME; $(touch unexpected-file)', 'https://github.com/login/device']
    print('browser-startup-stdout', flush=True)
    print('browser-startup-stderr', file=sys.stderr, flush=True)
    raise SystemExit(int((home / 'browser-status').read_text()))
else:
    raise SystemExit('Unexpected client')
"""
    )
    client.chmod(0o700)
    replacements = {
        "/usr/bin/gh": tmp_path / "gh",
        "/usr/bin/docker": tmp_path / "docker",
        "/usr/local/bin/docker-credential-secretservice": tmp_path / "helper",
        "secret-tool": tmp_path / "secret-tool",
    }
    for executable in replacements.values():
        executable.symlink_to(client)
    (tmp_path / ".gitconfig").write_text(
        '[credential "https://github.com"]\n\thelper = !' + str(tmp_path / "gh") + " auth git-credential\n"
    )
    isolated = tmp_path / "collections/ansible_collections/neilime/workstation_setup"
    for relative in (
        "plugins/modules/ghcr_auth.py",
        "plugins/module_utils/ghcr_auth.py",
        "plugins/module_utils/github_auth.py",
        "plugins/module_utils/desktop_session.py",
    ):
        destination = isolated / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = (COLLECTION / relative).read_text()
        for original, replacement in replacements.items():
            source = source.replace(original, str(replacement))
        destination.write_text(source)
    tasks = DataLoader().load_from_file(str(COLLECTION / "roles/development_tooling/tasks/ghcr.yml"))
    for task in tasks:
        if "ansible.builtin.get_url" in task:
            # The VM checks the installed binary; this fixture isolates registry and keyring clients.
            task["ansible.builtin.debug"] = {"msg": task.pop("ansible.builtin.get_url")}
    task_file = isolated / "roles/development_tooling/tasks/ghcr.yml"
    task_file.parent.mkdir(parents=True)
    task_file.write_text(json.dumps(tasks))
    return ansible_environment(tmp_path, GIT_CONFIG_NOSYSTEM="1", GH_TOKEN="ignored-environment-token")


@pytest.mark.parametrize("browser_status", [0, 7])
def test_scope_authorization_keeps_prompts_and_browser_failure_visible_without_browser_noise(
    tmp_path, registry_environment, browser_status
):
    """GHCR permission refresh confines browser streams while retaining native prompts and manual fallback."""
    (tmp_path / "refresh-scopes").touch()
    (tmp_path / "browser-status").write_text(str(browser_status))
    browser = tmp_path / "browser"
    browser.symlink_to(tmp_path / "client.py")
    registry_environment["GH_BROWSER"] = shlex.join(
        [str(browser), "--profile", "literal $HOME; $(touch unexpected-file)"]
    )
    playbook = write_local_playbook(
        tmp_path / "authorize.json",
        [
            {
                "neilime.workstation_setup.ghcr_auth": {
                    "home": str(tmp_path),
                    "account": "fixture",
                    "terminal": "{{ lookup('ansible.builtin.env', 'WORKSTATION_MANAGER_TTY') }}",
                }
            }
        ],
        {},
    )
    command = terminal_command(
        [
            "sh",
            "-c",
            'export WORKSTATION_MANAGER_TTY="$(tty)"; exec "$@"',
            "sh",
            "ansible-playbook",
            "-i",
            "localhost,",
            str(playbook),
        ]
    )
    result = run_playbook(command, registry_environment, cwd=tmp_path, input_text="approved\n", start_new_session=True)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "One-time code: fixture-code" in output
    assert "Press Enter to open https://github.com/login/device" in output
    assert ("Failed opening a web browser" in output) == bool(browser_status)
    assert "browser-startup-" not in output
    assert TOKEN not in output
    assert not (tmp_path / "unexpected-file").exists()
    assert not (tmp_path / "probe").exists()
    assert json.loads((tmp_path / "credential").read_text())["Username"] == "fixture"
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    assert [
        "browser",
        "--profile",
        "literal $HOME; $(touch unexpected-file)",
        "https://github.com/login/device",
    ] in calls


@pytest.mark.parametrize("separate_token", [False, True])
def test_registry_login_preview_rerun_and_failure_keep_credentials_private(
    tmp_path, registry_environment, separate_token
):
    """Ansible reports semantic changes, preserves other config, and redacts failed-client output."""
    if separate_token:
        (tmp_path / "separate-token").touch()
        registry_environment["WORKSTATION_MANAGER_GHCR_TOKEN"] = TOKEN
    playbook = write_local_playbook(
        tmp_path / "registry.json",
        [
            {
                "ansible.builtin.import_role": {
                    "name": "neilime.workstation_setup.development_tooling",
                    "tasks_from": "ghcr",
                }
            }
        ],
        {
            "workstation_manager_use_become": False,
            "workstation_manager_native_arch": "amd64",
            "workstation_manager_resolved": {
                "user": managed_user(tmp_path),
                "development": {
                    "github": {"account": "fixture"},
                    "docker": {"credential_helper_version": "0.0.0"},
                },
            },
        },
    )
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    configuration = tmp_path / ".docker/config.json"
    for flags, changed in ((["--check"], 1), ([], 1), ([], 0)):
        result = run_playbook([*command, *flags], registry_environment, cwd=tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"changed={changed}" in result.stdout
        assert TOKEN not in result.stdout + result.stderr
        if flags:
            assert not configuration.exists() and not (tmp_path / "credential").exists()
        else:
            assert json.loads(configuration.read_text())["credHelpers"]["ghcr.io"] == "secretservice"
            assert TOKEN not in configuration.read_text()
    configuration.write_text('{"auths":{"ghcr.io":{"auth":"recoverable"}},"currentContext":"fixture"}')
    original = configuration.read_bytes()
    (tmp_path / "reject").touch()
    result = run_playbook(command, registry_environment, cwd=tmp_path)
    assert result.returncode != 0 and "Docker login to ghcr.io failed" in result.stdout
    assert TOKEN not in result.stdout + result.stderr
    assert configuration.read_bytes() == original
    assert TOKEN not in (tmp_path / "calls").read_text()
