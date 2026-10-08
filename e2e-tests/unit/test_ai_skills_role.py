"""Exercise global Skillshare provisioning and provider links in disposable homes."""

import sys

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state_ai_tools import (
    AiToolsNormalizer,
)
from ansible_test_helpers import (
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)

pytestmark = pytest.mark.integration


@pytest.fixture(name="skill_home")
def prepare_skill_home(tmp_path):
    """Keep the actual provisioning tasks while replacing network and tool installation."""
    home = tmp_path / "home"
    binaries = home / ".local/bin"
    binaries.mkdir(parents=True)
    source = home / ".agents/skills/local"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("User-authored skill\n")
    personal_config = home / ".config/skillshare/config.yaml"
    personal_config.parent.mkdir(parents=True)
    personal_config.write_text("Personal Skillshare configuration\n")
    skillshare = binaries / "skillshare"
    # Independent CLI fixtures share this interpreter and import preamble.
    # pylint: disable=duplicate-code
    skillshare.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
assert args[:2] == ["install", "-g"] and args[3] == "--name" and len(args) == 5
assert Path.cwd() == Path(os.environ["HOME"])
assert os.environ["XDG_CONFIG_HOME"] == os.environ["HOME"] + "/.config"
assert os.environ["GIT_TERMINAL_PROMPT"] == "0"
config = Path(os.environ["SKILLSHARE_CONFIG"])
assert "targets: {}" in config.read_text()
source = next(line for line in config.read_text().splitlines() if line.startswith("source: "))
directory = Path(json.loads(source.removeprefix("source: "))) / args[4]
with Path(os.environ["AUDIT"]).open("a") as output:
    output.write(json.dumps({"args": args, "directory": str(directory)}) + "\n")
if os.environ.get("FAIL_INSTALL"):
    raise SystemExit("Synthetic download failure " + os.environ.get("GH_TOKEN", ""))
if os.environ.get("EXPECTED_TOKEN"):
    assert os.environ["GH_TOKEN"] == os.environ["EXPECTED_TOKEN"]
directory.mkdir()
(directory / "SKILL.md").write_text(args[2])
"""
    )
    # pylint: enable=duplicate-code
    skillshare.chmod(0o700)
    mise = binaries / "mise"
    mise.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "assert sys.argv[1:] == ['which', 'skillshare', '--tool', 'github:runkids/skillshare@1.2.3']\n"
        f"print({str(skillshare)!r})\n"
    )
    mise.chmod(0o700)
    return home


def apply_skills(home, skills, **overrides):
    """Provision sources and reconcile provider links through the production role and module."""
    declaration = {
        "mise": {"tools": {"github:runkids/skillshare": "1.2.3"}},
        "ai_tools": {"orca": {"version": "1.2.3"}, "skills": skills},
    }
    variables = {
        "workstation_manager_use_become": False,
        "workstation_manager_resolved": {
            "user": managed_user(home),
            "development": declaration,
        },
        "workstation_ai_config": AiToolsNormalizer().normalize(declaration),
        "workstation_ai_root": str(home / ".local/share/workstation-manager/ai-tools"),
    }
    tasks = [
        {"ansible.builtin.import_role": {"name": "neilime.workstation_setup.ai_tools", "tasks_from": "skills/main"}},
        {
            "neilime.workstation_setup.ai_skill_links": {
                "directory": str(home / ".agents/skills"),
                "state_path": str(home / ".local/state/fixture-skills.json"),
                "skills": "{{ workstation_ai_skills }}",
            }
        },
    ]
    environment = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "AUDIT": str(home / "calls.jsonl")}
    playbook = write_local_playbook(home.parent / "skills.json", tasks, variables, environment=environment)
    return run_playbook(
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        ansible_environment(home.parent, **overrides),
        cwd=home.parent,
    )


def test_global_skills_are_idempotent_and_follow_source_pin_changes(skill_home):
    """Local content is preserved and a changed remote source updates the managed link."""
    local = {"name": "local", "source": "~/.agents/skills/local"}
    remote = {"name": "review", "source": f"example/skills/tree/{'a' * 40}/skills/review"}
    skills = [local, remote]
    result = apply_skills(skill_home, skills)
    assert result.returncode == 0, result.stdout + result.stderr
    target = skill_home / ".agents/skills/review"
    initial = target.resolve()
    assert target.is_symlink()
    assert (target / "SKILL.md").read_text() == remote["source"]
    repeated = apply_skills(skill_home, skills)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert len((skill_home / "calls.jsonl").read_text().splitlines()) == 1
    remote["source"] = remote["source"].replace("a" * 40, "b" * 40)
    updated = apply_skills(skill_home, skills)
    assert updated.returncode == 0, updated.stdout + updated.stderr
    assert target.resolve() != initial
    assert initial.is_dir()
    assert (target / "SKILL.md").read_text() == remote["source"]
    assert (skill_home / ".agents/skills/local/SKILL.md").read_text() == "User-authored skill\n"
    assert not (skill_home / ".agents/skills/local").is_symlink()
    assert (skill_home / ".config/skillshare/config.yaml").read_text() == "Personal Skillshare configuration\n"


def test_local_skills_need_no_installed_skillshare(skill_home):
    """Custom skill directories remain usable without any remote installer."""
    (skill_home / ".local/bin/mise").unlink()
    result = apply_skills(skill_home, [{"name": "local", "source": "~/.agents/skills/local"}])
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (skill_home / "calls.jsonl").exists()


def test_private_download_failure_stops_setup_without_exposing_credentials(skill_home):
    """The managed token reaches the downloader, while failures keep provider links unchanged."""
    token = "synthetic-global-skill-token"
    skills = [{"name": "private", "source": f"example/skills/tree/{'a' * 40}/private"}]
    failed = apply_skills(skill_home, skills, WORKSTATION_MANAGER_GITHUB_TOKEN=token, FAIL_INSTALL="1")
    assert failed.returncode != 0
    assert token not in failed.stdout + failed.stderr
    assert "censored" in failed.stdout
    assert not (skill_home / ".agents/skills/private").exists()
    result = apply_skills(skill_home, skills, WORKSTATION_MANAGER_GITHUB_TOKEN=token, EXPECTED_TOKEN=token)
    assert result.returncode == 0, result.stdout + result.stderr
    assert token not in result.stdout + result.stderr
