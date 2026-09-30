"""Regression tests for the Git project report task wiring."""

from __future__ import annotations

import pathlib
import unittest

from ansible.parsing.dataloader import DataLoader

TASK_FILE = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup/roles/"
    / "development_tooling/tasks/git_project_report.yml"
)


class GitProjectReportRoleTests(unittest.TestCase):
    """Keep Git project report task paths stable and free of folded whitespace."""

    def test_report_assets_use_exact_destination_paths(self) -> None:
        """Managed asset destinations must not gain spaces from folded YAML strings."""

        tasks = DataLoader().load_from_file(str(TASK_FILE))
        destinations = {
            task["name"]: (
                task.get("ansible.builtin.template", {}).get("dest") or task.get("ansible.builtin.file", {}).get("dest")
            )
            for task in tasks
            if task.get("ansible.builtin.template", {}).get("dest") or task.get("ansible.builtin.file", {}).get("dest")
        }

        self.assertEqual(
            destinations,
            {
                "Install Git project report command wrapper": (
                    "{{ workstation_manager_resolved.user.home }}/.local/bin/workstation-manager-git-project-report"
                ),
                "Install Git project report timer activator": (
                    "{{ workstation_manager_resolved.user.home }}"
                    "/.local/bin/workstation-manager-git-project-report-activate-timer"
                ),
                "Install Git project report user service unit": (
                    "{{ workstation_manager_resolved.user.home }}"
                    "/.config/systemd/user/workstation-manager-git-project-report.service"
                ),
                "Install Git project report user timer unit": (
                    "{{ workstation_manager_resolved.user.home }}"
                    "/.config/systemd/user/workstation-manager-git-project-report.timer"
                ),
                "Enable Git project report timer for future sessions": (
                    "{{ workstation_manager_resolved.user.home }}"
                    "/.config/systemd/user/timers.target.wants/workstation-manager-git-project-report.timer"
                ),
                "Install Git project report desktop autostart entry": (
                    "{{ workstation_manager_resolved.user.home }}"
                    "/.config/autostart/workstation-manager-git-project-report.desktop"
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
