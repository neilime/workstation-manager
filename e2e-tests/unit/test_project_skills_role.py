"""Exercise automatic project skill provisioning without network or workstation changes."""

import json
import os
import sys
from pathlib import Path

import pytest
from ansible_test_helpers import (
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)

pytestmark = pytest.mark.integration


@pytest.fixture(name="skill_projects")
def prepare_skill_projects(tmp_path):
    """Create nested projects and isolated mise/Skillshare stand-ins."""
    home = tmp_path / "home"
    projects = home / "projects"
    binary_dir = home / ".local/bin"
    binary_dir.mkdir(parents=True)
    project = projects / "team/project with spaces"
    for parent in [
        project,
        projects / "plain",
        project / "node_modules/dependency",
        project / ".skillshare/skills/example",
    ]:
        manifest = parent / ".skillshare/config.yaml"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("targets: [codex]\nskills: []\n")
    (projects / "plain/.skillshare/config.yaml").unlink()
    outside = tmp_path / "outside"
    (outside / ".skillshare").mkdir(parents=True)
    (outside / ".skillshare/config.yaml").write_text("targets: [codex]\n")
    (projects / "external").symlink_to(outside, target_is_directory=True)
    audit = tmp_path / "calls.jsonl"
    skillshare = binary_dir / "skillshare"
    skillshare.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
root = Path.cwd()
assert os.environ["HOME"] == os.environ["EXPECTED_HOME"]
assert os.environ["XDG_CONFIG_HOME"] == os.environ["EXPECTED_HOME"] + "/.config"
assert os.environ["GIT_TERMINAL_PROMPT"] == "0"
with open(os.environ["AUDIT"], "a", encoding="utf-8") as output:
    output.write(json.dumps([str(root), args]) + "\n")
if args[0] == os.environ.get("FAIL_ACTION"):
    print("synthetic failure " + os.environ.get("GH_TOKEN", ""), file=sys.stderr)
    sys.exit(1)
source = root / ".skillshare/skills/fixture"
target = root / ".agents/skills/fixture"
if args == ["install", "-p"]:
    if os.environ.get("EXPECTED_TOKEN"):
        assert os.environ["GH_TOKEN"] == os.environ["EXPECTED_TOKEN"]
    installed = int(not source.exists())
    source.mkdir(parents=True, exist_ok=True)
    (source / "SKILL.md").write_text("Fixture skill\n")
    print(f"Installed {installed} skills")
elif args == ["status", "-p", "--json"]:
    print(json.dumps({"targets": [{"mode": "merge", "synced_count": int(target.is_symlink()),
                                  "skills_enabled": True, "status": "merged"}]}))
elif args == ["sync", "-p", "--json"]:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_symlink():
        target.symlink_to(source)
    print(json.dumps({"updated": 0, "pruned": 0, "details": [{"mode": "merge", "linked": 1}]}))
else:
    raise AssertionError(args)
"""
    )
    skillshare.chmod(0o755)
    mise = binary_dir / "mise"
    mise.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "assert sys.argv[1:] == ['which', 'skillshare', '--tool', 'github:runkids/skillshare@1.2.3']\n"
        f"print({str(skillshare)!r})\n"
    )
    mise.chmod(0o755)
    variables = {
        "workstation_manager_use_become": False,
        "workstation_manager_resolved": {
            "user": managed_user(home, projects_directory=str(projects)),
            "development": {"mise": {"tools": {"github:runkids/skillshare": "1.2.3"}}},
        },
    }
    tasks = [
        {
            "ansible.builtin.import_role": {
                "name": "neilime.workstation_setup.development_tooling",
                "tasks_from": "project_skills",
            }
        }
    ]
    playbook = write_local_playbook(tmp_path / "playbook.json", tasks, variables)
    environment = ansible_environment(tmp_path, EXPECTED_HOME=str(home), AUDIT=str(audit))
    # Preserve the isolated Python dependencies used by native test runs.
    if "PYTHONPATH" in os.environ:
        environment["PYTHONPATH"] = os.environ["PYTHONPATH"]
    return project, audit, playbook, environment


def apply_project_skills(fixture, *, check=False, **environment):
    """Apply the production task file using an isolated local playbook."""
    _, _, playbook, configured = fixture
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    return run_playbook(command + (["--check"] if check else []), {**configured, **environment}, cwd=playbook.parent)


def test_setup_discovers_projects_syncs_skills_and_repairs_missing_links(skill_projects):
    """Nested manifests opt in; dependencies and symlinked directories stay untouched."""
    project, audit, _, _ = skill_projects
    result = apply_project_skills(skill_projects)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=2" in result.stdout
    calls = [json.loads(line) for line in audit.read_text().splitlines()]
    assert {call[0] for call in calls} == {str(project)}
    target = project / ".agents/skills/fixture"
    assert (target / "SKILL.md").is_file()
    repeated = apply_project_skills(skill_projects)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    target.unlink()
    repaired = apply_project_skills(skill_projects)
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert "changed=1" in repaired.stdout
    assert target.is_symlink()


def test_project_skill_preview_needs_no_installed_tools_and_writes_nothing(skill_projects):
    """Dry runs discover opted-in projects without executing mise or Skillshare."""
    project, audit, _, environment = skill_projects
    Path(environment["EXPECTED_HOME"], ".local/bin/mise").unlink()
    result = apply_project_skills(skill_projects, check=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0" in result.stdout
    assert str(project) in result.stdout
    assert not audit.exists()
    assert not (project / ".agents").exists()


@pytest.mark.parametrize("action", ["install", "sync"])
def test_project_skill_failures_fail_setup(skill_projects, action):
    """Install and sync failures propagate instead of reporting a completed setup."""
    _, audit, _, _ = skill_projects
    result = apply_project_skills(skill_projects, FAIL_ACTION=action)
    assert result.returncode != 0
    assert "synthetic failure" in result.stdout + result.stderr
    calls = [json.loads(line)[1][0] for line in audit.read_text().splitlines()]
    assert calls[-1] == action


def test_private_skill_installation_uses_managed_authentication_and_redacts_failures(skill_projects):
    """Private Git downloads receive the optional token without exposing it on failure."""
    token = "synthetic-project-skill-token"
    result = apply_project_skills(skill_projects, WORKSTATION_MANAGER_GITHUB_TOKEN=token, EXPECTED_TOKEN=token)
    assert result.returncode == 0, result.stdout + result.stderr
    failed = apply_project_skills(skill_projects, WORKSTATION_MANAGER_GITHUB_TOKEN=token, FAIL_ACTION="install")
    assert failed.returncode != 0
    assert token not in result.stdout + result.stderr + failed.stdout + failed.stderr
    assert "censored" in failed.stdout


def test_absent_projects_directory_does_not_require_skillshare(skill_projects):
    """Fresh workstations with no projects have no project provisioning work."""
    _, audit, _, environment = skill_projects
    home = Path(environment["EXPECTED_HOME"])
    (home / "projects").rename(home / "saved-projects")
    (home / ".local/bin/mise").unlink()
    result = apply_project_skills(skill_projects)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0" in result.stdout
    assert not audit.exists()
