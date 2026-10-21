"""Exercise registry credential handling through the real isolated Ansible module."""

import json
import sys
from pathlib import Path

import pytest
from ansible_test_helpers import ansible_environment, run_playbook, write_local_playbook

COLLECTION = Path(__file__).parents[2] / "ansible/collections/ansible_collections/neilime/workstation_setup"
pytestmark = pytest.mark.integration
TOKEN = "synthetic-registry-credential"


@pytest.fixture(name="registry_environment")
def registry_environment_fixture(tmp_path):
    """Keep real module execution while replacing registry and keyring clients."""
    client = tmp_path / "client.py"
    client.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json, os, sys
from pathlib import Path
home = Path(os.environ['HOME'])
args = sys.argv[1:]
name = Path(sys.argv[0]).name
assert not any(key.startswith('DOCKER_') for key in os.environ)
assert not os.environ.get('GH_TOKEN')
with (home / 'calls').open('a') as log:
    log.write(json.dumps([name, *args]) + '\n')
credential = home / 'credential'
token = 'synthetic-registry-credential'
if name == 'gh':
    if args[:2] == ['auth', 'status']:
        print(json.dumps({'hosts': {'github.com': [dict(state='success', active=True,
              login='fixture', tokenSource='keyring', scopes='repo, write:packages')]}}))
    elif args[:2] == ['auth', 'token']:
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
else:
    raise SystemExit('Unexpected client')
"""
    )
    client.chmod(0o700)
    replacements = {
        "/usr/bin/gh": tmp_path / "gh",
        "/usr/bin/docker": tmp_path / "docker",
        "/usr/local/bin/docker-credential-secretservice": tmp_path / "helper",
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
    return ansible_environment(tmp_path, GIT_CONFIG_NOSYSTEM="1", GH_TOKEN="ignored-environment-token")


def test_registry_login_preview_rerun_and_failure_keep_credentials_private(tmp_path, registry_environment):
    """Ansible reports semantic changes, preserves other config, and redacts failed-client output."""
    playbook = write_local_playbook(
        tmp_path / "registry.json",
        [{"neilime.workstation_setup.ghcr_auth": {"home": str(tmp_path), "account": "fixture"}}],
        {},
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
