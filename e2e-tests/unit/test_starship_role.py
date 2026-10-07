"""Resolve Starship's executable without assuming mise's installation layout."""

import subprocess

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    SETUP_ROLES,
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)

pytestmark = pytest.mark.integration


def test_starship_link_uses_the_resolved_binary_and_converges(tmp_path):
    """Preview preserves the home; setup repairs the link and refuses an unavailable executable."""
    home = tmp_path / "home"
    mise = home / ".local/bin/mise"
    mise.parent.mkdir(parents=True)
    executable = home / "tools/starship/.mise-bins/starship"
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/bin/sh\nprintf "starship fixture\\n"\n')
    executable.chmod(0o755)
    mise.write_text(
        r"""#!/bin/sh
set -eu
[ "$PWD" = "$HOME" ]
[ "$XDG_CONFIG_HOME" = "$HOME/.config" ]
[ "$#" -eq 4 ]
[ "$1" = which ]
[ "$2" = starship ]
[ "$3" = --tool ]
[ "$4" = aqua:starship/starship@1.2.3 ]
executable="$HOME/tools/starship/.mise-bins/starship"
if [ ! -x "$executable" ]; then
    printf '%s\n' 'configured Starship executable is unavailable' >&2
    exit 1
fi
printf '%s\n' "$executable"
"""
    )
    mise.chmod(0o755)
    link = mise.parent / "starship"
    previous_target = home / "unavailable-starship"
    link.symlink_to(previous_target)
    role = SETUP_ROLES / "development_tooling"
    tasks = []
    for task in DataLoader().load_from_file(str(role / "tasks/main.yml")):
        if "starship" in task["name"].lower():
            if "ansible.builtin.import_tasks" in task:
                task["ansible.builtin.import_tasks"] = str(role / "tasks" / task["ansible.builtin.import_tasks"])
            tasks.append(task)
    assert tasks
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        tasks,
        {
            "workstation_manager_use_become": False,
            "workstation_manager_resolved": {
                "user": managed_user(home),
                "development": {"mise": {"tools": {"aqua:starship/starship": "1.2.3"}}},
            },
        },
    )
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    environment = ansible_environment(tmp_path)
    preview = run_playbook([*command, "--check"], environment)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert link.readlink() == previous_target
    for repeated in (False, True):
        result = run_playbook(command, environment)
        assert result.returncode == 0, result.stdout + result.stderr
        assert link.resolve(strict=True) == executable
        assert subprocess.check_output([str(link), "--version"], text=True).strip() == "starship fixture"
        if repeated:
            assert "changed=0" in result.stdout
    executable.unlink()
    result = run_playbook(command, environment)
    assert result.returncode != 0
    assert "configured Starship executable is unavailable" in result.stdout + result.stderr
    assert link.readlink() == executable
