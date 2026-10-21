"""Exercise provider adapters in isolated homes without launching real clients or servers."""

import json
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible.utils.vars import merge_hash
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
    DesiredStateConfigNormalizer,
)
from ansible_test_helpers import (
    SETUP_ROLES,
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)

pytestmark = pytest.mark.integration


@pytest.fixture(name="cli_installation")
def fixture_cli_installation(tmp_path):
    """Isolate provider installation with a synthetic npm registry and self-updating executable."""
    home = tmp_path / "home"
    user = managed_user(home)
    provider = {"npm": "@example/agent-cli", "version": "9.8.7", "command": "agent-cli"}
    commands = tmp_path / "bin"
    commands.mkdir()
    previous = tmp_path / "existing-cli"
    previous.write_text("Existing installation\n")
    command_link = commands / provider["command"]
    command_link.symlink_to(previous)
    client = f"#!{sys.executable}\n" + textwrap.dedent("""\
        import sys
        import tempfile
        from pathlib import Path

        if sys.argv[1] == '--version':
            print('fixture-agent')
        elif sys.argv[1] == '--update':
            executable = Path(__file__).resolve()
            with tempfile.TemporaryDirectory(prefix='.copilot-update-', dir=executable.parent) as directory:
                replacement = Path(directory) / 'agent'
                replacement.write_bytes(executable.read_bytes())
                replacement.chmod(0o700)
                replacement.replace(executable)
        else:
            raise SystemExit('Unexpected client operation')
        """)
    calls = tmp_path / "npm-calls.jsonl"
    state = tmp_path / "npm-state.json"
    state.write_text("{}")
    executable = tmp_path / "npm"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"state = Path({str(state)!r})\n"
        "prefix = Path(os.environ['NPM_CONFIG_PREFIX'])\n"
        f"with Path({str(calls)!r}).open('a') as log:\n"
        "    log.write(json.dumps({'args': sys.argv[1:], 'prefix': str(prefix),\n"
        "                          'home': os.environ['HOME'], 'cache': os.environ.get('NPM_CONFIG_CACHE')}) + '\\n')\n"
        "installed = json.loads(state.read_text())\n"
        "if sys.argv[1] == 'list':\n"
        "    print(json.dumps({'dependencies': installed}))\n"
        "elif sys.argv[1] == 'install':\n"
        f"    assert prefix.is_relative_to(Path({str(home)!r})), 'CLI packages must install in the managed home'\n"
        "    package, version = sys.argv[-1].rsplit('@', 1)\n"
        "    installed[package] = {'version': version}\n"
        "    state.write_text(json.dumps(installed))\n"
        "    binary = prefix / 'lib/node_modules' / package / 'node_modules/@example/agent-platform/agent'\n"
        "    binary.parent.mkdir(parents=True)\n"
        f"    binary.write_text({client!r})\n"
        "    binary.chmod(0o700)\n"
        "    (prefix / 'bin').mkdir()\n"
        f"    (prefix / 'bin' / {provider['command']!r}).symlink_to(binary)\n"
        "else:\n"
        "    raise SystemExit('Unexpected npm operation')\n"
    )
    executable.chmod(0o700)
    tasks = DataLoader().load_from_file(str(SETUP_ROLES / "ai_tools/tasks/npm_tools.yml"))
    for group in tasks:
        for task in group.get("block", [group]):
            if "community.general.npm" in task:
                task["community.general.npm"]["executable"] = str(executable)
            if task.get("ansible.builtin.file", {}).get("state") == "link":
                task["ansible.builtin.file"].update(
                    dest=str(commands / "{{ item.value.command }}"), owner=user["name"], group=user["name"]
                )
            if "ansible.builtin.command" in task:
                task["ansible.builtin.command"]["argv"][-2] = str(commands / "{{ item.value.command }}")
    variables = {
        "workstation_manager_use_become": False,
        "workstation_manager_resolved": {
            "user": user,
            "development": {"ai_tools": {"providers": {"agent": provider}}},
        },
    }
    return {
        "home": home,
        "user": user,
        "provider": provider,
        "command_link": command_link,
        "previous": previous,
        "client": client,
        "calls": calls,
        "state": state,
        "environment": ansible_environment(tmp_path),
        "command": [
            "ansible-playbook",
            "--inventory",
            "localhost,",
            str(write_local_playbook(tmp_path / "install.json", tasks, variables)),
        ],
    }


@pytest.mark.parametrize("check", [False, True])
def test_provider_installation_is_user_writable_and_idempotent(cli_installation, check):
    """Pinned CLIs support user updates through stable commands, with safe setup previews."""
    command = cli_installation["command"] + (["--check"] if check else [])
    result = run_playbook(command, cli_installation["environment"])
    assert result.returncode == 0, result.stdout + result.stderr
    invocations = [json.loads(line) for line in cli_installation["calls"].read_text().splitlines()]
    installs = [call["args"] for call in invocations if call["args"][0] == "install"]
    home = cli_installation["home"]
    command_link = cli_installation["command_link"]
    for call in invocations:
        assert call["home"] == str(home)
        assert Path(call["prefix"]).is_relative_to(home)
        assert Path(call["cache"]).is_relative_to(home)
    assert cli_installation["previous"].read_text() == "Existing installation\n"
    if check:
        assert installs == []
        assert json.loads(cli_installation["state"].read_text()) == {}
        assert not home.exists()
        assert command_link.resolve() == cli_installation["previous"]
    else:
        assert len(installs) == 1
        provider = cli_installation["provider"]
        assert f"{provider['npm']}@{provider['version']}" in installs[0]
        binary = command_link.resolve()
        assert binary.is_relative_to(home)
        assert binary.owner() == cli_installation["user"]["name"]
        update = subprocess.run(
            [str(command_link), "--update"], capture_output=True, text=True, check=False, timeout=10
        )
        assert update.returncode == 0, update.stdout + update.stderr
        assert binary.read_text() == cli_installation["client"]
        repeated = run_playbook(command, cli_installation["environment"])
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        assert "changed=0" in repeated.stdout


def apply(root: Path, *, check=False, extensions=False):
    """Run actual Ansible adapters against fixture files only."""
    home = root / "home"
    state = home / ".local/state/workstation-manager/ai-tools"
    variables = {
        "workstation_manager_use_become": False,
        "workstation_manager_resolved": {
            "user": managed_user(home),
            "development": {
                "editor_packages": [],
                "ai_tools": {
                    "providers": {
                        "codex": {"npm": "@openai/codex", "version": "1.2.3", "command": "codex"},
                        "copilot": {"npm": "@github/copilot", "version": "1.2.3", "command": "copilot"},
                    },
                    "skills": [],
                    "mcp_servers": [],
                },
            },
        },
        "workstation_ai_state": str(state),
        "workstation_ai_skills": [],
        "workstation_ai_servers": {
            "example": {"command": "/installed/example", "args": [], "env": {"TOKEN": "synthetic-private-marker"}}
        },
    }
    roles = (
        []
        if extensions
        else [
            "neilime.workstation_setup.ai_tool_codex",
            "neilime.workstation_setup.ai_tool_copilot",
        ]
    )
    tasks = (
        [{"ansible.builtin.import_role": {"name": "neilime.workstation_setup.ai_tools", "tasks_from": "extensions"}}]
        if extensions
        else []
    )
    playbook = write_local_playbook(root / "playbook.json", tasks, variables, roles=roles)
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)] + (["--check"] if check else [])
    return run_playbook(command, ansible_environment(root), cwd=root)


def test_adapters_write_native_private_formats_and_are_idempotent(tmp_path):
    """Adapters write native private formats and are idempotent."""
    result = apply(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "synthetic-private-marker" not in result.stdout + result.stderr
    home = tmp_path / "home"
    codex = home / ".codex/config.toml"
    copilot = home / ".copilot/mcp-config.json"
    assert tomllib.loads(codex.read_text())["mcp_servers"]["example"]["command"] == "/installed/example"
    assert json.loads(copilot.read_text())["mcpServers"]["example"]["command"] == "/installed/example"
    assert json.loads(copilot.read_text())["mcpServers"]["example"]["type"] == "stdio"
    assert json.loads(copilot.read_text())["mcpServers"]["example"]["tools"] == ["*"]
    assert codex.stat().st_mode & 0o777 == 0o600
    assert copilot.stat().st_mode & 0o777 == 0o600
    repeated = apply(tmp_path)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout


@pytest.mark.parametrize("extensions", [False, True])
def test_extension_previews_neither_create_files_nor_require_installed_clients(tmp_path, extensions):
    """Extension previews neither create files nor require installed clients."""
    result = apply(tmp_path, check=True, extensions=extensions)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "home").exists()
    assert "synthetic-private-marker" not in result.stdout + result.stderr
    if extensions:
        assert "deferred in check mode" in result.stdout


def test_existing_user_entries_are_preserved_and_conflicts_fail(tmp_path):
    """Existing user entries are preserved and conflicts fail."""
    path = tmp_path / "home/.copilot/mcp-config.json"
    path.parent.mkdir(parents=True)
    original = '{"mcpServers":{"example":{"command":"/personal"}}}'
    path.write_text(original)
    result = apply(tmp_path)
    assert result.returncode != 0
    assert path.read_text() == original
    assert "synthetic-private-marker" not in result.stdout + result.stderr


def ai_resource_directory_tasks():
    """Load actual AI resource directory tasks without running installation or authentication."""

    def directory_tasks(tasks):
        for task in tasks:
            if "ansible.builtin.file" in task:
                yield task
            yield from directory_tasks(task.get("block", []))

    tasks = []
    for filename in ("extensions.yml", "mcp/package.yml"):
        content = DataLoader().load_from_file(str(SETUP_ROLES / "ai_tools/tasks" / filename))
        tasks.extend(directory_tasks(content))
    return tasks


def test_ai_resource_directories_use_normalized_user_ownership(tmp_path, public_defaults, private_overrides):
    """AI state and MCP package directories accept the production user schema and stay private."""
    home = tmp_path / "home"
    resolved = merge_hash(public_defaults, private_overrides)
    resolved["user"] = managed_user(home)
    resolved = DesiredStateConfigNormalizer().normalize(resolved)
    root = home / ".local/share/workstation-manager/ai-tools"
    state = home / ".local/state/workstation-manager/ai-tools"
    package = root / "npm/example/1.2.3"
    variables = {
        "workstation_manager_resolved": resolved,
        "workstation_ai_root": str(root),
        "workstation_ai_state": str(state),
        "workstation_ai_package_dir": str(package),
    }
    command = [
        "ansible-playbook",
        "-i",
        "localhost,",
        str(write_local_playbook(tmp_path / "directories.json", ai_resource_directory_tasks(), variables)),
    ]
    environment = ansible_environment(tmp_path)
    result = run_playbook(command, environment, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    for directory in (root, state, package):
        assert directory.is_dir()
        assert directory.owner() == resolved["user"]["name"]
        assert directory.group() == resolved["user"]["name"]
        assert directory.stat().st_mode & 0o777 == 0o700
    stable = package.parent / "current"
    assert stable.is_symlink()
    assert stable.resolve() == package.resolve()
    repeated = run_playbook(command, environment, cwd=tmp_path)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout


@pytest.mark.parametrize("authenticate", [True, False])
def test_provider_authentication_deferral_is_explicit_and_reported(tmp_path, authenticate):
    """Only an explicit false skips native login; setup reports the unverified boundary."""
    content = DataLoader().load_from_file(str(SETUP_ROLES / "ai_tools/tasks/extensions.yml"))
    provision = next(task["block"] for task in content[0]["block"] if "block" in task)
    tasks = [
        task
        for task in provision
        if task.get("ansible.builtin.include_role", {}).get("tasks_from") == "authenticate"
        or "ansible.builtin.debug" in task
    ]
    variables = {
        "workstation_manager_use_become": False,
        "workstation_ai_config": {
            "authenticate": authenticate,
            "providers": {"codex": {"command": "fixture-client-not-installed"}},
        },
        "workstation_manager_resolved": {"user": managed_user(tmp_path)},
    }
    playbook = write_local_playbook(tmp_path / "auth-policy.json", tasks, variables)
    result = run_playbook(["ansible-playbook", "-i", "localhost,", str(playbook)], ansible_environment(tmp_path))
    if authenticate:
        assert result.returncode != 0
        assert "Cannot access the AI client" in result.stdout, result.stdout + result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "provider logins are not verified" in result.stdout
        assert "Native provider logins are available" not in result.stdout
