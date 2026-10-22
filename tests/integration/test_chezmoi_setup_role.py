"""Exercise Chezmoi setup with isolated paths and private command failures."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)
from backup_prompt_helpers import run_interactive

TASK_DIRECTORY = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup"
    / "roles/home_environment/tasks"
)


def git(repository: pathlib.Path, *arguments: str) -> str:
    """Run isolated Git operations without reading host identities or credential helpers."""
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "0",
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.test",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.test",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return result.stdout.strip()


@pytest.fixture(name="chezmoi_setup")
def fixture_chezmoi_setup(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, dict[str, str]]:
    """Model Chezmoi path selection and failures without modifying real dotfiles."""
    published = tmp_path / "published"
    published.mkdir()
    git(published, "init", "--initial-branch=fixture")
    (published / "dot_zshrc").write_text("# fixture configuration\n")
    git(published, "add", ".")
    git(published, "commit", "-m", "Fixture dotfiles")
    git(tmp_path, "clone", "--bare", str(published), str(tmp_path / "remote.git"))
    git(published, "remote", "add", "origin", str(tmp_path / "remote.git"))
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
        "import json, os, pathlib, subprocess, sys\n"
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
        "    if (root / 'fail-init').exists():\n"
        "        sys.exit('private-initialization-diagnostic')\n"
        "    subprocess.run(['git', 'clone', str(root / 'remote.git'), str(source)], "
        "capture_output=True, check=True)\n"
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
        "    if not (destination / '.zshrc').exists() or "
        "(destination / '.zshrc').read_text() != (source / 'dot_zshrc').read_text():\n"
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
            "Render the managed Chezmoi machine-data config",
        }:
            tasks.append(task)
        elif task["name"] == "Initialize and refresh the managed Chezmoi source":
            task["ansible.builtin.import_tasks"] = str(TASK_DIRECTORY / "chezmoi_source.yml")
            tasks.append(task)
        elif task["name"] == "Inspect and apply the managed Chezmoi dotfiles":
            task["ansible.builtin.import_tasks"] = str(TASK_DIRECTORY / "chezmoi_apply.yml")
            tasks.append(task)
    write_local_playbook(
        tmp_path / "playbook.json",
        tasks,
        {
            "workstation_manager_use_become": False,
            "workstation_manager_resolved": {
                "user": managed_user(home, projects_directory=str(home / "projects")),
                "home_environment": {"chezmoi": {"bin_path": str(binary)}},
            },
            "workstation_manager_home_environment_chezmoi_config_path": str(config),
            "workstation_manager_home_environment_chezmoi_source_dir": str(source),
            "workstation_manager_home_environment_chezmoi_source_url": "https://github.com/fixture/dotfiles.git",
            "workstation_manager_home_environment_chezmoi_source_dir_stat": {"stat": {"exists": False}},
            "workstation_manager_home_environment_chezmoi_template_data": {"fixture": "machine-data"},
        },
    )
    env = ansible_environment(
        tmp_path,
        HOME=str(home),
        XDG_DATA_HOME=str(tmp_path / "ide-data"),
        FIXTURE_ROOT=str(tmp_path),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    return tmp_path, env


def run_setup(fixture: tuple[pathlib.Path, dict[str, str]], *options: str) -> subprocess.CompletedProcess[str]:
    """Execute the production initialization and application tasks in the fixture."""
    root, env = fixture
    return run_playbook(
        ["ansible-playbook", "--inventory", "localhost,", str(root / "playbook.json"), *options], env, cwd=root
    )


@pytest.mark.parametrize("authenticated", [False, True])
def test_explicit_paths_apply_dotfiles_and_repeated_setup_is_unchanged(chezmoi_setup, authenticated: bool) -> None:
    """Pin source, target, and permissions independently of inherited shell and IDE settings."""
    root, env = chezmoi_setup
    if authenticated:
        env["WORKSTATION_MANAGER_GITHUB_TOKEN"] = "fixture-token"
    initial = run_setup(chezmoi_setup)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    assert (root / "home/.zshrc").read_text() == "# fixture configuration\n"
    assert not (root / "ide-data").exists()
    assert (root / "home/.config").stat().st_mode & 0o777 == 0o700
    config = root / "home/.config/custom-chezmoi/machine.yaml"
    assert config.stat().st_mode & 0o777 == 0o600
    assert DataLoader().load_from_file(str(config)) == {"umask": 0o022, "data": {"fixture": "machine-data"}}
    repeated = run_setup(chezmoi_setup)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    assert sum("apply" in call for call in calls) == 1
    assert "fixture-token" not in initial.stdout + initial.stderr


def test_preview_does_not_apply_dotfiles(chezmoi_setup) -> None:
    """A check run must not write managed dotfiles."""
    root, _ = chezmoi_setup
    result = run_setup(chezmoi_setup, "--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / "home/.zshrc").exists()
    calls_file = root / "calls.jsonl"
    if calls_file.exists():
        calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
        assert not any("apply" in call or "status" in call for call in calls)


def test_initial_clone_failure_reports_safe_actionable_diagnostics(chezmoi_setup) -> None:
    """Private clone failures stop setup before inspecting or applying dotfiles."""
    root, _environment = chezmoi_setup
    (root / "fail-init").touch()
    failed = run_setup(chezmoi_setup)
    output = failed.stdout + failed.stderr
    assert failed.returncode != 0
    assert "Cannot initialize the Chezmoi source" in output
    assert "private-initialization-diagnostic" not in output
    assert not (root / "home/.zshrc").exists()


def test_repeated_setup_fetches_and_applies_the_latest_published_dotfiles(chezmoi_setup) -> None:
    """A new remote commit reaches the existing source and target before setup can report success."""
    root, env = chezmoi_setup
    env["WORKSTATION_MANAGER_GITHUB_TOKEN"] = "synthetic-source-token"
    initial = run_setup(chezmoi_setup)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    published = root / "published"
    (published / "dot_zshrc").write_text("# latest published configuration\n")
    git(published, "commit", "-am", "Publish updated dotfiles")
    git(published, "push", "origin", "fixture")
    source = root / "home/.local/share/chezmoi"
    before = git(source, "rev-parse", "HEAD")
    preview = run_setup(chezmoi_setup, "--check")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert git(source, "rev-parse", "HEAD") == before
    assert (root / "home/.zshrc").read_text() == "# fixture configuration\n"
    updated = run_setup(chezmoi_setup)
    assert updated.returncode == 0, updated.stdout + updated.stderr
    assert git(source, "rev-parse", "HEAD") == git(published, "rev-parse", "HEAD")
    assert (root / "home/.zshrc").read_text() == "# latest published configuration\n"
    repeated = run_setup(chezmoi_setup)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert "synthetic-source-token" not in updated.stdout + updated.stderr + (source / ".git/config").read_text()


@pytest.mark.parametrize("problem", ["edited", "untracked", "ahead", "diverged", "unavailable", "detached"])
def test_source_update_failures_preserve_source_and_target_without_applying_dotfiles(chezmoi_setup, problem) -> None:
    """Stale or unpublished source state cannot be silently reused, discarded, or applied."""
    root, _env = chezmoi_setup
    initial = run_setup(chezmoi_setup)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    source = root / "home/.local/share/chezmoi"
    published = root / "published"
    if problem in {"edited", "ahead", "diverged"}:
        (source / "dot_zshrc").write_text("# preserve unpublished source\n")
        if problem != "edited":
            git(source, "commit", "-am", "Unpublished dotfiles")
    elif problem == "untracked":
        (source / "untracked-user-file").write_text("private synthetic data\n")
    elif problem == "unavailable":
        git(source, "remote", "set-url", "origin", str(root / "missing-private-remote"))
    else:
        git(source, "checkout", "--detach")
    if problem == "diverged":
        (published / "dot_zshrc").write_text("# different published configuration\n")
        git(published, "commit", "-am", "Remote changes")
        git(published, "push", "origin", "fixture")
    before = git(source, "rev-parse", "HEAD")
    contents = (source / "dot_zshrc").read_bytes()
    calls_before = (root / "calls.jsonl").read_bytes()
    failed = run_setup(chezmoi_setup)
    output = failed.stdout + failed.stderr
    assert failed.returncode != 0, output
    assert "Chezmoi source" in output
    assert "missing-private-remote" not in output
    assert git(source, "rev-parse", "HEAD") == before
    assert (source / "dot_zshrc").read_bytes() == contents
    assert (root / "home/.zshrc").read_text() == "# fixture configuration\n"
    assert (root / "calls.jsonl").read_bytes() == calls_before
    if problem == "untracked":
        assert (source / "untracked-user-file").read_text() == "private synthetic data\n"
    if problem in {"edited", "untracked"}:
        assert "interactive terminal to stash source edits or skip Chezmoi" in output
        assert str(source) in output
        assert "status --short" in output


@pytest.fixture(name="dirty_chezmoi_source")
def fixture_dirty_chezmoi_source(chezmoi_setup):
    """Keep staged, unstaged, and untracked edits separate from published dotfiles."""
    root, env = chezmoi_setup
    initial = run_setup(chezmoi_setup)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    source = root / "home/.local/share/chezmoi"
    (source / "dot_zshrc").write_text("# staged source edit\n")
    git(source, "add", "dot_zshrc")
    (source / "dot_zshrc").write_text("# unstaged source edit\n")
    (source / "untracked-user-file").write_text("private synthetic source data\n")
    env["WORKSTATION_MANAGER_INTERACTIVE"] = "1"
    return source


@pytest.mark.parametrize("answers", [("skip",), ("invalid", " SKIP "), ("abort",), ("",)])
def test_source_prompt_skip_and_abort_preserve_edits_and_do_not_apply(chezmoi_setup, dirty_chezmoi_source, answers):
    """Only an explicit source skip continues setup, leaving source, dotfiles, and scripts untouched."""
    root, env = chezmoi_setup
    source = dirty_chezmoi_source
    before = git(source, "status", "--porcelain")
    calls_before = (root / "calls.jsonl").read_bytes()
    playbook_path = root / "playbook.json"
    playbook = json.loads(playbook_path.read_text())
    playbook[0]["tasks"].append({"ansible.builtin.debug": {"msg": "Fixture setup continued after source prompt."}})
    playbook_path.write_text(json.dumps(playbook))
    command = ["ansible-playbook", "--inventory", "localhost,", str(playbook_path)]

    returncode, output = run_interactive(
        command, root, env, [("Type stash, skip, or abort", answer) for answer in answers]
    )

    skipped = answers[-1].strip().lower() == "skip"
    assert (returncode == 0) == skipped, output
    assert ("Fixture setup continued after source prompt." in output) == skipped
    assert ("Skipped Chezmoi source update, dotfile application and scripts" in output) == skipped
    assert git(source, "status", "--porcelain") == before
    assert git(source, "stash", "list") == ""
    assert (source / "dot_zshrc").read_text() == "# unstaged source edit\n"
    assert git(source, "show", ":dot_zshrc") == "# staged source edit"
    assert (source / "untracked-user-file").read_text() == "private synthetic source data\n"
    assert (root / "calls.jsonl").read_bytes() == calls_before
    assert "private synthetic source data" not in output


def test_source_stash_approval_preserves_edits_and_applies_published_dotfiles(chezmoi_setup, dirty_chezmoi_source):
    """An approved stash retains staged and untracked data while setup applies the fetched revision."""
    root, env = chezmoi_setup
    source = dirty_chezmoi_source
    published = root / "published"
    (published / "dot_new_setting").write_text("# newly published configuration\n")
    git(published, "add", ".")
    git(published, "commit", "-m", "Publish another dotfile")
    git(published, "push", "origin", "fixture")
    (source / ".git/info/exclude").write_text("ignored-user-file\n")
    (source / "ignored-user-file").write_text("keep ignored data\n")
    # Existing saved work must survive creating the setup stash.
    git(source, "stash", "push", "--include-untracked", "-m", "Existing saved work")
    previous_stash = git(source, "rev-parse", "refs/stash")
    git(source, "stash", "apply", "--index", previous_stash)
    (source / "untracked-user-file").write_text("private synthetic source data\nnew edit\n")
    (root / "applied").unlink()
    command = ["ansible-playbook", "--inventory", "localhost,", str(root / "playbook.json")]

    returncode, output = run_interactive(command, root, env, [("Type stash, skip, or abort", "stash")])

    assert returncode == 0, output
    assert git(source, "status", "--porcelain") == ""
    assert git(source, "rev-parse", "HEAD") == git(published, "rev-parse", "HEAD")
    assert (root / "home/.zshrc").read_text() == "# fixture configuration\n"
    assert (root / "applied").exists()
    assert (source / "ignored-user-file").read_text() == "keep ignored data\n"
    stash = git(source, "rev-parse", "refs/stash")
    assert stash != previous_stash
    assert git(source, "rev-parse", "stash@{1}") == previous_stash
    assert stash in output
    assert "stash apply --index" in output
    assert "private synthetic source data" not in output
    assert "# unstaged source edit" not in output
    git(source, "stash", "apply", "--index", stash)
    assert (source / "dot_zshrc").read_text() == "# unstaged source edit\n"
    assert git(source, "show", ":dot_zshrc") == "# staged source edit"
    assert (source / "untracked-user-file").read_text() == "private synthetic source data\nnew edit\n"


def test_dirty_source_preview_and_missing_terminal_cannot_authorize_stashing(chezmoi_setup, dirty_chezmoi_source):
    """A dirty checkout remains untouched by dry runs and by a stale interactive environment flag."""
    root, _env = chezmoi_setup
    source = dirty_chezmoi_source
    calls_before = (root / "calls.jsonl").read_bytes()
    before = git(source, "status", "--porcelain")
    preview = run_setup(chezmoi_setup, "--check")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert "Type stash, skip, or abort" not in preview.stdout
    failed = run_setup(chezmoi_setup)
    assert failed.returncode != 0
    assert "source edits were left unchanged" in failed.stdout
    assert git(source, "status", "--porcelain") == before
    assert git(source, "stash", "list") == ""
    assert (root / "calls.jsonl").read_bytes() == calls_before


def test_failed_update_after_stashing_preserves_ignored_files_and_reports_recovery(chezmoi_setup, dirty_chezmoi_source):
    """An update that would overwrite ignored data fails and leaves approved source edits recoverable."""
    root, env = chezmoi_setup
    source = dirty_chezmoi_source
    published = root / "published"
    (published / "ignored-user-file").write_text("published replacement\n")
    git(published, "add", ".")
    git(published, "commit", "-m", "Publish conflicting path")
    git(published, "push", "origin", "fixture")
    (source / ".git/info/exclude").write_text("ignored-user-file\n")
    (source / "ignored-user-file").write_text("private ignored data\n")
    calls_before = (root / "calls.jsonl").read_bytes()
    before = git(source, "rev-parse", "HEAD")
    command = ["ansible-playbook", "--inventory", "localhost,", str(root / "playbook.json")]

    returncode, output = run_interactive(command, root, env, [("Type stash, skip, or abort", "stash")])

    assert returncode != 0, output
    stash = git(source, "rev-parse", "refs/stash")
    assert stash in output
    assert "stash apply --index" in output
    assert "private ignored data" not in output
    assert (source / "ignored-user-file").read_text() == "private ignored data\n"
    assert git(source, "rev-parse", "HEAD") == before
    assert (root / "calls.jsonl").read_bytes() == calls_before
    git(source, "stash", "apply", "--index", stash)
    assert (source / "dot_zshrc").read_text() == "# unstaged source edit\n"
    assert (source / "untracked-user-file").read_text() == "private synthetic source data\n"


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


@pytest.mark.parametrize(
    "directory_conflict,answers", [(False, ("skip",)), (True, (" SKIP ",)), (False, ("invalid", "skip"))]
)
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
