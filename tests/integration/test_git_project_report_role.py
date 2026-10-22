"""Exercise mandatory Git report scheduling without changing host packages or services."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible_test_helpers import (
    SETUP_ROLES,
    ansible_environment,
    managed_user,
    run_playbook,
    write_local_playbook,
)


def test_notifications_install_converge_and_open_full_report(tmp_path):
    """Setup preserves previews, converges, and makes notification clicks open the complete report."""
    role = tmp_path / "development_tooling"
    shutil.copytree(SETUP_ROLES / role.name, role)
    notifications = role / "tasks/git_project_notifications.yml"
    tasks = DataLoader().load_from_file(str(notifications))
    for task in tasks:
        if "ansible.builtin.apt" in task:
            # The VM test verifies packages; all user files use real Ansible modules here.
            task["ansible.builtin.debug"] = {"msg": task.pop("ansible.builtin.apt")}
    notifications.write_text(json.dumps(tasks))
    home = tmp_path / "home with spaces"
    (home / ".local/bin").mkdir(parents=True)
    autostart = home / ".config/autostart/workstation-manager-git-project-report.desktop"
    timer = home / ".config/systemd/user/timers.target.wants/workstation-manager-git-project-report.timer"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "id").write_text('#!/bin/sh\nprintf "%s\\n" "4294967294"\n')
    (stubs / "id").chmod(0o755)
    (stubs / "systemctl").write_text("#!/bin/sh\nexit 99\n")
    (stubs / "systemctl").chmod(0o755)
    playbook = tmp_path / "playbook.json"
    write_local_playbook(
        playbook,
        [
            {
                "ansible.builtin.import_role": {
                    "name": str(role),
                    "tasks_from": "git_project_report",
                }
            }
        ],
        {
            "workstation_manager_use_become": False,
            "workstation_manager_resolved": {
                "user": {**managed_user(home), "projects_directory": str(home / "projects")},
            },
        },
    )
    environment = ansible_environment(tmp_path, PATH=str(stubs) + ":" + os.environ["PATH"])
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    result = run_playbook([*command, "--check"], environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".config").exists()
    assert not any((home / ".local/bin").iterdir())
    assert not (home / ".local/share").exists()
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "next graphical login" in result.stdout
    assert autostart.exists()
    assert timer.is_symlink()
    assert timer.resolve().is_file()
    assert (timer.parent.parent / "workstation-manager-git-project-report.service").is_file()
    assert (home / ".local/bin/workstation-manager-git-project-report").exists()
    assert (home / ".local/bin/workstation-manager-git-project-report-activate-timer").exists()
    result = run_playbook(command, environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0" in result.stdout
    exercise_notification_actions(home, environment)


def exercise_notification_actions(home: Path, environment: dict[str, str]) -> None:
    """Use the installed launchers in a private desktop session with a synthetic viewer."""
    applications = home / ".local/share/applications"
    viewer = home / "viewer.py"
    viewer.write_text(
        "import json, sys\nfrom pathlib import Path\n"
        f"with Path({str(home / 'opened.jsonl')!r}).open('a') as log:\n"
        "    log.write(json.dumps({'path': sys.argv[1], 'report': Path(sys.argv[1]).read_text()}) + '\\n')\n"
    )
    (applications / "fixture-viewer.desktop").write_text(
        "[Desktop Entry]\nName=Fixture report viewer\nType=Application\n"
        f"Exec=/usr/bin/python3 {json.dumps(str(viewer))} %f\nMimeType=text/plain;\n"
    )
    (home / ".config/mimeapps.list").write_text("[Default Applications]\ntext/plain=fixture-viewer.desktop;\n")
    for index in range(6):
        project = home / "projects" / f"project-{index}"
        project.mkdir(parents=True)
        subprocess.run(["git", "init", "--initial-branch=main", str(project)], check=True, capture_output=True)
        (project / "uncommitted.txt").write_text("Local work\n")
    session = Path(__file__).parents[1] / "support/git_report_session_fixture.py"
    result = subprocess.run(
        ["dbus-run-session", "--", "/usr/bin/python3", str(session), str(home)],
        env={
            **environment,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_STATE_HOME": str(home / ".local/state"),
            "GNOTIFICATION_BACKEND": "gtk",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
