"""Exercise Chezmoi setup with isolated paths and private command failures."""

from __future__ import annotations

import json
import os
import pathlib
import pwd
import subprocess
import sys

import pytest
from ansible.parsing.dataloader import DataLoader
from backup_prompt_helpers import run_interactive

TASK_DIRECTORY = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup"
    / "roles/home_environment/tasks"
)


@pytest.fixture(name="chezmoi_setup")
def fixture_chezmoi_setup(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, dict[str, str]]:
    """Model Chezmoi path selection and failures without modifying real dotfiles."""
    # Isolated role fixtures repeat Ansible play and environment declarations.
    # pylint: disable=duplicate-code
    home = tmp_path / "home"
    home.mkdir()
    (home / ".config").mkdir(mode=0o700)
    config = home / ".config/custom-chezmoi/machine.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("{}\n")
    source = home / ".local/share/chezmoi"
    binary = tmp_path / "chezmoi"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "root = pathlib.Path(os.environ['FIXTURE_ROOT'])\n"
        "with (root / 'calls.jsonl').open('a') as calls:\n"
        "    calls.write(json.dumps(args) + '\\n')\n"
        "def option(name, default):\n"
        "    return pathlib.Path(args[args.index(name) + 1]) if name in args else default\n"
        "home = pathlib.Path(os.environ['HOME'])\n"
        "source = option('--source', pathlib.Path(os.environ['XDG_DATA_HOME']) / 'chezmoi')\n"
        "config = option('--config', home / '.config/chezmoi/chezmoi.yaml')\n"
        "destination = option('--destination', pathlib.Path(os.environ['XDG_DATA_HOME']))\n"
        "if not config.is_file():\n"
        "    sys.exit(3)\n"
        "if 'init' in args:\n"
        "    source.mkdir(parents=True, exist_ok=True)\n"
        "    (source / 'dot_zshrc').write_text('# fixture configuration\\n')\n"
        "    sys.exit(0)\n"
        "if not source.is_dir():\n"
        "    sys.exit(4)\n"
        "if 'status' in args:\n"
        "    if (root / 'fail-status').exists():\n"
        "        print('fixture-private-value', file=sys.stderr)\n"
        "        sys.exit(5)\n"
        "    if (root / 'local-conflict').exists():\n"
        "        if (root / 'directory-conflict').exists():\n"
        "            print('MM .config')\n"
        "        else:\n"
        "            print('MM .zshrc')\n"
        "            print('DA .config/settings')\n"
        "        print(' M .gitconfig')\n"
        "        sys.exit(0)\n"
        "    if (root / 'new-conflict').exists():\n"
        "        print('MM .gitconfig')\n"
        "        sys.exit(0)\n"
        "    if not (destination / '.zshrc').exists():\n"
        "        print(' A .zshrc')\n"
        "    if not (root / 'applied').exists():\n"
        "        print(' R run_fixture')\n"
        "elif 'apply' in args:\n"
        "    if (root / 'fail-apply').exists():\n"
        "        print('fixture-private-value', file=sys.stderr)\n"
        "        sys.exit(6)\n"
        "    if '--force' in args:\n"
        "        if args[args.index('--') + 1:] != "
        "[str(destination / '.zshrc'), str(destination / '.config/settings')]:\n"
        "            sys.exit(8)\n"
        "        if '--recursive=false' not in args or '--exclude=scripts' not in args:\n"
        "            sys.exit(9)\n"
        "        if not (root / 'unresolved-conflict').exists():\n"
        "            (root / 'local-conflict').unlink()\n"
        "        if (root / 'introduce-conflict').exists():\n"
        "            (root / 'new-conflict').touch()\n"
        "        (destination / '.config/settings').write_text('restored\\n')\n"
        "    else:\n"
        "        if (root / 'local-conflict').exists() or (root / 'new-conflict').exists():\n"
        "            sys.exit(10)\n"
        "        (root / 'applied').touch()\n"
        "    (destination / '.zshrc').write_text((source / 'dot_zshrc').read_text())\n"
        "else:\n"
        "    sys.exit(7)\n"
    )
    binary.chmod(0o755)
    tasks = []
    for task in DataLoader().load_from_file(str(TASK_DIRECTORY / "main.yml")):
        if task["name"] in {
            "Resolve the managed Chezmoi command paths",
            "Inspect existing baseline user directory permissions",
            "Ensure baseline user directories exist without resetting their permissions",
            "Initialize the managed Chezmoi source repository",
        }:
            tasks.append(task)
        elif task["name"] == "Inspect and apply the managed Chezmoi dotfiles":
            task["ansible.builtin.import_tasks"] = str(TASK_DIRECTORY / "chezmoi_apply.yml")
            tasks.append(task)
    (tmp_path / "playbook.json").write_text(
        json.dumps(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "ansible_python_interpreter": sys.executable,
                        "workstation_manager_use_become": False,
                        "workstation_manager_resolved": {
                            "user": {
                                "name": pwd.getpwuid(os.getuid()).pw_name,
                                "home": str(home),
                                "projects_directory": str(home / "projects"),
                            },
                            "home_environment": {
                                "chezmoi": {"bin_path": str(binary), "apply": "{{ fixture_apply | default(true) }}"}
                            },
                        },
                        "workstation_manager_home_environment_chezmoi_config_path": str(config),
                        "workstation_manager_home_environment_chezmoi_source_dir": str(source),
                        "workstation_manager_home_environment_chezmoi_source_url": (
                            "https://github.com/fixture/dotfiles.git"
                        ),
                        "workstation_manager_home_environment_chezmoi_source_dir_stat": {"stat": {"exists": False}},
                    },
                    "tasks": tasks,
                }
            ]
        )
    )
    ansible_config = tmp_path / "ansible.cfg"
    ansible_config.write_text("[defaults]\n")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "LC_ALL": "C.UTF-8",
        "ANSIBLE_CONFIG": str(ansible_config),
        "ANSIBLE_HOME": str(tmp_path / ".ansible"),
        "XDG_DATA_HOME": str(tmp_path / "ide-data"),
        "FIXTURE_ROOT": str(tmp_path),
    }
    return tmp_path, env
    # pylint: enable=duplicate-code


def run_setup(fixture: tuple[pathlib.Path, dict[str, str]], *options: str) -> subprocess.CompletedProcess[str]:
    """Execute the production initialization and application tasks in the fixture."""
    root, env = fixture
    return subprocess.run(
        [
            "ansible-playbook",
            "--inventory",
            "localhost,",
            str(root / "playbook.json"),
            *options,
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.mark.parametrize("authenticated", [False, True])
def test_explicit_paths_apply_dotfiles_and_repeated_setup_is_unchanged(chezmoi_setup, authenticated: bool) -> None:
    """Honor the managed source and custom config despite an inherited IDE data path."""
    root, env = chezmoi_setup
    if authenticated:
        env["WORKSTATION_MANAGER_GITHUB_TOKEN"] = "fixture-token"
    initial = run_setup(chezmoi_setup)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    assert (root / "home/.zshrc").read_text() == "# fixture configuration\n"
    assert not (root / "ide-data").exists()
    assert (root / "home/.config").stat().st_mode & 0o777 == 0o700
    repeated = run_setup(chezmoi_setup)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    assert sum("apply" in call for call in calls) == 1
    assert "fixture-token" not in initial.stdout + initial.stderr


@pytest.mark.parametrize(
    "options",
    [
        ("--check",),
        (
            "--extra-vars",
            '{"fixture_apply":false}',
        ),
    ],
)
def test_preview_or_disabled_application_does_not_apply_dotfiles(chezmoi_setup, options: tuple[str, ...]) -> None:
    """A check run and an explicit apply=false must not write managed dotfiles."""
    root, _ = chezmoi_setup
    result = run_setup(chezmoi_setup, *options)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / "home/.zshrc").exists()
    calls_file = root / "calls.jsonl"
    if calls_file.exists():
        calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
        assert not any("apply" in call or "status" in call for call in calls)


@pytest.mark.parametrize("operation", ["status", "apply"])
def test_command_errors_fail_with_private_output_and_actionable_diagnostics(chezmoi_setup, operation: str) -> None:
    """Keep error text private while reporting the failed operation and command."""
    root, _ = chezmoi_setup
    (root / f"fail-{operation}").touch()
    result = run_setup(chezmoi_setup)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "fixture-private-value" not in output
    assert "to see the underlying error" in output
    assert "--config" in output
    assert "--source" in output
    assert not (root / "home/.zshrc").exists()
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    if operation == "status":
        assert not any("apply" in call for call in calls)


def test_local_conflicts_are_reported_before_any_apply(chezmoi_setup) -> None:
    """Name modified and deleted files without running scripts or overwriting them."""
    root, _ = chezmoi_setup
    (root / "local-conflict").touch()
    startup = root / "home/.zshrc"
    startup.write_text("# preserve local edit\n")
    result = run_setup(chezmoi_setup)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "local changes that differ from the source dotfiles" in output
    assert "MM .zshrc" in output
    assert "DA .config/settings" in output
    assert "MM .zshrc\nDA .config/settings" in output
    assert "Chezmoi will ask before replacing" in output
    assert "# preserve local edit" not in output
    assert startup.read_text() == "# preserve local edit\n"
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    assert not any("apply" in call for call in calls)


def test_interactive_approval_reconciles_only_conflicts_and_continues_setup(chezmoi_setup) -> None:
    """Approved paths are reconciled before normal application and script execution."""
    root, env = chezmoi_setup
    env["WORKSTATION_MANAGER_INTERACTIVE"] = "1"
    (root / "local-conflict").touch()
    (root / "home/.zshrc").write_text("# preserve local edit\n")
    command = ["ansible-playbook", "--inventory", "localhost,", str(root / "playbook.json")]
    returncode, output = run_interactive(command, root, env, [("Type apply, skip, or abort", "apply")])
    assert returncode == 0, output
    assert (root / "home/.zshrc").read_text() == "# fixture configuration\n"
    assert (root / "home/.config/settings").read_text() == "restored\n"
    assert (root / "applied").exists()
    assert "MM .zshrc" in output
    assert "DA .config/settings" in output
    assert "MM .zshrc\nDA .config/settings" in output.replace("\r", "")
    assert "fixture-private-value" not in output
    assert "# preserve local edit" not in output
    repeated = run_setup(chezmoi_setup)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout


@pytest.mark.parametrize("answer", ["abort", ""])
def test_interactive_abort_preserves_dotfiles_without_running_scripts(chezmoi_setup, answer: str) -> None:
    """Aborting or submitting an empty answer cannot authorize replacement."""
    root, env = chezmoi_setup
    env["WORKSTATION_MANAGER_INTERACTIVE"] = "1"
    (root / "local-conflict").touch()
    startup = root / "home/.zshrc"
    startup.write_text("# preserve local edit\n")
    command = ["ansible-playbook", "--inventory", "localhost,", str(root / "playbook.json")]
    returncode, output = run_interactive(command, root, env, [("Type apply, skip, or abort", answer)])
    assert returncode != 0, output
    assert "local changes were left unchanged" in output
    assert startup.read_text() == "# preserve local edit\n"
    assert not (root / "applied").exists()
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    assert not any("apply" in call for call in calls)


@pytest.mark.parametrize("directory_conflict", [False, True])
@pytest.mark.parametrize("answers", [("skip",), (" SKIP ",), ("invalid", "skip")])
def test_interactive_skip_preserves_dotfiles_and_continues_setup(
    chezmoi_setup, directory_conflict: bool, answers: tuple[str, ...]
) -> None:
    """An explicit skip preserves conflicts and pending dotfiles without running scripts."""
    root, env = chezmoi_setup
    env["WORKSTATION_MANAGER_INTERACTIVE"] = "1"
    (root / "local-conflict").touch()
    if directory_conflict:
        (root / "directory-conflict").touch()
    startup = root / "home/.zshrc"
    startup.write_text("# preserve local edit\n")
    playbook_path = root / "playbook.json"
    playbook = json.loads(playbook_path.read_text())
    playbook[0]["tasks"].append(
        {
            "name": "Continue setup after Chezmoi",
            "ansible.builtin.debug": {"msg": "Fixture setup continued after Chezmoi."},
        }
    )
    playbook_path.write_text(json.dumps(playbook))
    command = ["ansible-playbook", "--inventory", "localhost,", str(playbook_path)]

    returncode, output = run_interactive(
        command, root, env, [("Type apply, skip, or abort", answer) for answer in answers]
    )

    assert returncode == 0, output
    assert "Skipped Chezmoi dotfile application and scripts for this setup run" in output
    assert "Fixture setup continued after Chezmoi." in output
    assert (root / "local-conflict").exists()
    assert startup.read_text() == "# preserve local edit\n"
    assert (root / "home/.config").stat().st_mode & 0o777 == 0o700
    assert not (root / "home/.config/settings").exists()
    assert not (root / "home/.gitconfig").exists()
    assert not (root / "applied").exists()
    assert "# preserve local edit" not in output
    assert ("MM .config" if directory_conflict else "MM .zshrc") in output
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    assert not any("apply" in call for call in calls)


def test_skip_does_not_disable_a_later_application_in_the_same_playbook(chezmoi_setup) -> None:
    """Skipping one invocation cannot suppress dotfiles in a later conflict-free invocation."""
    root, env = chezmoi_setup
    env["WORKSTATION_MANAGER_INTERACTIVE"] = "1"
    conflict = root / "local-conflict"
    conflict.touch()
    (root / "home/.zshrc").write_text("# preserve local edit\n")
    playbook_path = root / "playbook.json"
    playbook = json.loads(playbook_path.read_text())
    playbook[0]["tasks"].extend(
        [
            {
                "name": "Resolve fixture conflicts before the next invocation",
                "ansible.builtin.file": {"path": str(conflict), "state": "absent"},
            },
            {
                "name": "Apply dotfiles in a later invocation",
                "ansible.builtin.import_tasks": str(TASK_DIRECTORY / "chezmoi_apply.yml"),
            },
        ]
    )
    playbook_path.write_text(json.dumps(playbook))
    command = ["ansible-playbook", "--inventory", "localhost,", str(playbook_path)]

    returncode, output = run_interactive(command, root, env, [("Type apply, skip, or abort", "skip")])

    assert returncode == 0, output
    assert (root / "home/.zshrc").read_text() == "# fixture configuration\n"
    assert (root / "applied").exists()
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    assert sum("apply" in call for call in calls) == 1
    assert not any("--force" in call for call in calls)


def test_interactive_flag_without_a_terminal_cannot_authorize_replacement(chezmoi_setup) -> None:
    """A stale interactive signal must not approve a skipped Ansible pause."""
    root, env = chezmoi_setup
    env["WORKSTATION_MANAGER_INTERACTIVE"] = "1"
    (root / "local-conflict").touch()
    startup = root / "home/.zshrc"
    startup.write_text("# preserve local edit\n")
    result = run_setup(chezmoi_setup)
    assert result.returncode != 0
    assert startup.read_text() == "# preserve local edit\n"
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    assert not any("apply" in call for call in calls)


@pytest.mark.parametrize("marker", ["unresolved-conflict", "introduce-conflict", "fail-apply"])
def test_approved_reconciliation_must_succeed_before_running_scripts(chezmoi_setup, marker: str) -> None:
    """A failed restore or newly detected conflict stops setup before general application."""
    root, env = chezmoi_setup
    env["WORKSTATION_MANAGER_INTERACTIVE"] = "1"
    (root / "local-conflict").touch()
    (root / marker).touch()
    command = ["ansible-playbook", "--inventory", "localhost,", str(root / "playbook.json")]
    returncode, output = run_interactive(command, root, env, [("Type apply, skip, or abort", "apply")])
    assert returncode != 0, output
    assert not (root / "applied").exists()
    assert "fixture-private-value" not in output
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    assert all("--force" in call for call in calls if "apply" in call)
