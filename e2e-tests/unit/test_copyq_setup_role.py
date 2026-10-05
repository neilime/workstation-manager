"""Exercise CopyQ clipboard configuration and startup without desktop applications."""

from __future__ import annotations

import configparser
import json
import os
import pathlib
import pwd
import subprocess
import sys

import pytest
from ansible.parsing.dataloader import DataLoader

TASK_DIRECTORY = (
    pathlib.Path(__file__).parents[2]
    / "ansible/collections/ansible_collections/neilime/workstation_setup/roles/gnome_preferences/tasks"
)


@pytest.fixture(name="copyq_setup")
def fixture_copyq_setup(tmp_path: pathlib.Path) -> tuple[pathlib.Path, dict[str, str]]:
    """Provide an isolated user home, process probe, and Flatpak command."""

    home = tmp_path / "home"
    home.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    probe = binaries / "pgrep"
    probe.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "root = pathlib.Path(os.environ['FIXTURE_ROOT'])\n"
        "if (root / 'fail-probe').exists():\n"
        "    sys.exit(2)\n"
        "if sys.argv[-1] == 'gnome-shell':\n"
        "    if (root / 'fail-session').exists():\n"
        "        sys.exit(3)\n"
        "    if (root / 'headless').exists():\n"
        "        sys.exit(1)\n"
        "    print(os.getppid())\n"
        "elif sys.argv[-1] == 'copyq':\n"
        "    if not (root / 'running').exists():\n"
        "        sys.exit(1)\n"
        "    print(1234)\n"
        "else:\n"
        "    sys.exit(2)\n"
    )
    probe.chmod(0o755)
    flatpak = binaries / "flatpak"
    flatpak.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "root = pathlib.Path(os.environ['FIXTURE_ROOT'])\n"
        "if (root / 'fail-start').exists():\n"
        "    sys.exit(4)\n"
        "keys = ('HOME', 'DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS',\n"
        "        'XDG_CONFIG_HOME', 'XDG_DATA_HOME')\n"
        "environment = {key: os.environ.get(key) for key in keys}\n"
        "with (root / 'calls.jsonl').open('a') as calls:\n"
        "    calls.write(json.dumps({'args': sys.argv[1:], 'env': environment}) + '\\n')\n"
        "(root / 'running').touch()\n"
    )
    flatpak.chmod(0o755)
    loader = DataLoader()
    startup_tasks = loader.load_from_file(str(TASK_DIRECTORY / "copyq.yml"))
    for task in startup_tasks:
        if task["name"] == "Start CopyQ hidden in the active desktop session":
            task["ansible.builtin.command"]["argv"][0] = str(flatpak)
    startup_file = tmp_path / "copyq.json"
    startup_file.write_text(json.dumps(startup_tasks))
    tasks = loader.load_from_file(str(TASK_DIRECTORY / "autostart.yml"))
    for task in tasks:
        if "ansible.builtin.include_tasks" in task:
            task["ansible.builtin.include_tasks"] = str(startup_file)
    flatpak_tasks = TASK_DIRECTORY.parent.parent / "flatpak_apps/tasks"
    clipboard_task = next(
        task
        for task in loader.load_from_file(str(flatpak_tasks / "main.yml"))
        if task.get("ansible.builtin.import_tasks") == "copyq.yml"
    )
    clipboard_task["ansible.builtin.import_tasks"] = str(flatpak_tasks / "copyq.yml")
    tasks.insert(0, clipboard_task)
    account = pwd.getpwuid(os.getuid())
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
                        "workstation_manager_gnome_use_become_user": False,
                        "workstation_manager_resolved": {
                            "user": {"name": account.pw_name, "home": str(home)},
                            "desktop": {
                                "flatpak": {"packages": "{{ fixture_packages | default(['com.github.hluk.copyq']) }}"},
                                "gnome": {
                                    "autostart": "{{ fixture_autostart | default(copyq_autostart) }}",
                                },
                            },
                        },
                        "copyq_autostart": [
                            {
                                "desktop_file": "com.github.hluk.copyq.desktop",
                                "name": "CopyQ",
                                "command": "/usr/bin/flatpak run com.github.hluk.copyq --start-server hide",
                            }
                        ],
                    },
                    "tasks": tasks,
                }
            ]
        )
    )
    config = tmp_path / "ansible.cfg"
    config.write_text("[defaults]\n")
    environment = {
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "HOME": str(home),
        "LC_ALL": "C.UTF-8",
        "ANSIBLE_CONFIG": str(config),
        "ANSIBLE_HOME": str(tmp_path / ".ansible"),
        "FIXTURE_ROOT": str(tmp_path),
        "DISPLAY": ":42",
        "WAYLAND_DISPLAY": "wayland-fixture",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/fixture/bus",
        "XDG_DATA_HOME": str(tmp_path / "ide-data"),
    }
    if "ANSIBLE_COLLECTIONS_PATH" in os.environ:
        environment["ANSIBLE_COLLECTIONS_PATH"] = os.environ["ANSIBLE_COLLECTIONS_PATH"]
    return tmp_path, environment


def run_setup(fixture: tuple[pathlib.Path, dict[str, str]], *options: str) -> subprocess.CompletedProcess[str]:
    """Run the production autostart tasks with isolated process boundaries."""

    root, environment = fixture
    return subprocess.run(
        ["ansible-playbook", "--inventory", "localhost,", str(root / "playbook.json"), *options],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_setup_starts_copyq_hidden_and_is_idempotent(copyq_setup) -> None:
    """An existing desktop session should not require logout after setup."""

    root, _ = copyq_setup
    initial = run_setup(copyq_setup)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    repeated = run_setup(copyq_setup)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    assert len(calls) == 1
    assert calls[0]["args"] == ["run", "com.github.hluk.copyq", "--start-server", "hide"]
    assert calls[0]["env"] == {
        "HOME": str(root / "home"),
        "DISPLAY": ":42",
        "WAYLAND_DISPLAY": "wayland-fixture",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/fixture/bus",
        "XDG_CONFIG_HOME": str(root / "home/.config"),
        "XDG_DATA_HOME": str(root / "home/.local/share"),
    }
    autostart = root / "home/.config/autostart/com.github.hluk.copyq.desktop"
    assert "Exec=/usr/bin/flatpak run com.github.hluk.copyq --start-server hide" in autostart.read_text()
    assert "X-GNOME-Autostart-enabled=true" in autostart.read_text()
    override = root / "home/.local/share/flatpak/overrides/com.github.hluk.copyq"
    assert "QT_QPA_PLATFORM=xcb" in override.read_text()
    assert not (root / "ide-data/flatpak/overrides/com.github.hluk.copyq").exists()


def test_setup_preserves_an_already_running_copyq(copyq_setup) -> None:
    """Do not launch another server or hide the user's existing CopyQ window."""

    root, _ = copyq_setup
    (root / "running").touch()
    (root / "fail-session").touch()
    result = run_setup(copyq_setup)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / "calls.jsonl").exists()


@pytest.mark.parametrize("options", [(), ("--extra-vars", '{"fixture_autostart":[]}')])
def test_copyq_clipboard_override_preserves_other_settings(copyq_setup, options: tuple[str, ...]) -> None:
    """Every launch should use XWayland, without replacing unrelated permissions."""

    root, _ = copyq_setup
    override = root / "home/.local/share/flatpak/overrides/com.github.hluk.copyq"
    override.parent.mkdir(parents=True)
    override.write_text(
        "[Context]\nsockets=x11;wayland;\nfilesystems=xdg-download;\n"
        "[Environment]\nQT_QPA_PLATFORM=wayland\nCOPYQ_LOG_LEVEL=WARNING\n"
    )

    result = run_setup(copyq_setup, *options)

    assert result.returncode == 0, result.stdout + result.stderr
    settings = configparser.ConfigParser()
    settings.read(override)
    assert dict(settings["Environment"]) == {"qt_qpa_platform": "xcb", "copyq_log_level": "WARNING"}
    assert dict(settings["Context"]) == {"sockets": "x11;wayland;", "filesystems": "xdg-download;"}
    repeated = run_setup(copyq_setup, *options)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "changed=0" in repeated.stdout
    assert "quit it from its menu and reopen it" not in repeated.stdout


@pytest.mark.parametrize("options", [("--check",), ("--extra-vars", '{"fixture_packages":[]}')])
def test_copyq_override_is_not_written_in_preview_or_when_unmanaged(copyq_setup, options: tuple[str, ...]) -> None:
    """Dry runs and an unmanaged CopyQ must preserve an existing override file."""

    root, _ = copyq_setup
    override = root / "home/.local/share/flatpak/overrides/com.github.hluk.copyq"
    override.parent.mkdir(parents=True)
    original = "[Environment]\nQT_QPA_PLATFORM=wayland\n"
    override.write_text(original)

    result = run_setup(copyq_setup, *options)

    assert result.returncode == 0, result.stdout + result.stderr
    assert override.read_text() == original


@pytest.mark.parametrize("session", ["headless", "without-display"])
def test_setup_without_a_graphical_display_defers_startup(copyq_setup, session: str) -> None:
    """Headless setup should install future startup without launching CopyQ."""

    root, environment = copyq_setup
    if session == "headless":
        (root / "headless").touch()
    else:
        environment.pop("DISPLAY")
        environment.pop("WAYLAND_DISPLAY")
    result = run_setup(copyq_setup)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CopyQ will start at the next graphical login" in result.stdout
    assert not (root / "calls.jsonl").exists()
    assert (root / "home/.config/autostart/com.github.hluk.copyq.desktop").is_file()


@pytest.mark.parametrize(
    "options",
    [
        ("--check",),
        ("--extra-vars", '{"fixture_autostart":[]}'),
        ("--extra-vars", '{"fixture_packages":[]}'),
    ],
)
def test_preview_or_disabled_copyq_cannot_launch_an_application(copyq_setup, options: tuple[str, ...]) -> None:
    """Previews and disabled configuration must not inspect or start CopyQ."""

    root, _ = copyq_setup
    (root / "fail-probe").touch()
    result = run_setup(copyq_setup, *options)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / "calls.jsonl").exists()


@pytest.mark.parametrize("operation", ["probe", "session", "start"])
def test_copyq_startup_errors_fail_setup(copyq_setup, operation: str) -> None:
    """Unexpected process inspection errors and failed starts must be reported."""

    root, _ = copyq_setup
    (root / f"fail-{operation}").touch()
    result = run_setup(copyq_setup)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (root / "running").exists()
