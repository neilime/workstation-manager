"""Verify mise command selection and required releases without installing host tools."""

import os
import sys

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


def test_php_and_composer_are_verified_through_the_managed_mise_configuration(tmp_path):
    """Render real config, skip probes during previews, and fail for missing or mismatched tools."""
    home = tmp_path / "home"
    mise = home / ".local/bin/mise"
    mise.parent.mkdir(parents=True)
    config = home / ".config/mise/config.toml"
    config.parent.mkdir(parents=True)
    php = home / "php-version"
    composer = home / "composer-version"
    php.write_text("1.2.3")
    composer.write_text("Composer version 2.3.4 fixture")
    mise.write_text(
        f"#!{sys.executable}\n"
        + r"""
import os
from pathlib import Path
import sys
import tomllib

home = Path(os.environ["HOME"])
assert Path.cwd() == home
assert sys.argv[1:3] == ["exec", "--"]
config = Path(os.environ["XDG_CONFIG_HOME"]) / "mise/config.toml"
tools = tomllib.loads(config.read_text())["tools"]
assert tools["vfox:jdx/vfox-php"] == "1.2.3"
assert tools["github:composer/composer"] == {
    "version": "2.3.4", "asset_pattern": "composer.phar", "bin": "composer"
}
command = sys.argv[3]
assert sys.argv[4:] == ({"php": ["-r", "echo PHP_VERSION;"], "composer": ["--version", "--no-ansi"]}[command])
with (home / "probes").open("a") as audit:
    audit.write(command + "\n")
print((home / (command + "-version")).read_text())
"""
    )
    mise.chmod(0o755)
    role = SETUP_ROLES / "development_tooling"
    tasks = []
    for task in DataLoader().load_from_file(str(role / "tasks/main.yml")):
        if task.get("ansible.builtin.import_tasks") == "php.yml":
            task["ansible.builtin.import_tasks"] = str(role / "tasks/php.yml")
            tasks.append(task)
        elif task.get("ansible.builtin.template", {}).get("src") == "mise.toml.j2":
            template = task["ansible.builtin.template"]
            template["src"] = str(role / "templates/mise.toml.j2")
            template["group"] = str(os.getgid())
            tasks.append(task)
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        tasks,
        {
            "workstation_manager_use_become": False,
            "workstation_manager_resolved": {
                "user": managed_user(home),
                "development": {
                    "mise": {"tools": {"vfox:jdx/vfox-php": "1.2.3", "github:composer/composer": "2.3.4"}},
                },
            },
        },
    )
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    environment = ansible_environment(tmp_path)
    result = run_playbook([*command, "--check"], environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / "probes").exists()
    assert not config.exists()

    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / "probes").read_text().splitlines() == ["php", "composer"]

    composer.write_text("Composer version 2.3.40 fixture")
    result = run_playbook(command, environment)
    assert result.returncode != 0
    assert "2.3.40" in result.stdout

    php.unlink()
    result = run_playbook(command, environment)
    assert result.returncode != 0
    assert (home / "probes").read_text().splitlines()[-1] == "php"
