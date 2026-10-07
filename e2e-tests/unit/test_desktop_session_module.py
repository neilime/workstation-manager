"""The desktop adapter exposes usable session access without credentials or changes."""

import pytest
from ansible_test_helpers import ansible_environment, run_playbook, write_local_playbook

pytestmark = pytest.mark.integration


def test_desktop_session_module_is_read_only_and_filters_credentials(tmp_path) -> None:
    """Run the real module with explicit desktop access in an isolated check-mode play."""
    playbook = write_local_playbook(
        tmp_path / "playbook.json",
        [
            {
                "name": "Discover desktop session",
                "neilime.workstation_setup.desktop_session_info": {},
                "environment": {
                    "DISPLAY": ":fixture",
                    "BW_SESSION": "private-vault-session",
                },
                "register": "desktop",
            },
            {
                "name": "Verify sanitized read-only result",
                "ansible.builtin.assert": {
                    "that": [
                        "desktop.available",
                        "not desktop.changed",
                        "desktop.environment.DISPLAY == ':fixture'",
                        "'BW_SESSION' not in desktop.environment",
                    ]
                },
            },
        ],
        {},
    )
    result = run_playbook(
        ["ansible-playbook", "-i", "localhost,", str(playbook), "--check"],
        ansible_environment(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "private-vault-session" not in result.stdout + result.stderr
