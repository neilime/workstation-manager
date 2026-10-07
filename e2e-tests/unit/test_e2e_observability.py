"""Keep E2E timing and temporary profiling transparent to action failures."""

from __future__ import annotations

import configparser
import importlib.util
import os
import pathlib
import re
import subprocess
import tempfile
import types
import unittest
from unittest import mock

import pytest
from ansible.parsing.dataloader import DataLoader

E2E_PATH = pathlib.Path(__file__).parents[1]


def load_profiling_module() -> types.ModuleType:
    """Load the guest helper without making e2e-tests a Python package."""
    module_path = E2E_PATH / "task_profiling.py"
    spec = importlib.util.spec_from_file_location("task_profiling", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


task_profiling = load_profiling_module()


@pytest.mark.parametrize("existing_instance,start_status", [(False, 0), (True, 0), (False, 37)])
def test_vm_start_preserves_failures_and_collects_diagnostics(
    tmp_path: pathlib.Path, existing_instance: bool, start_status: int
) -> None:
    """Both startup paths retain status; failed diagnostics cannot hide a boot failure."""
    commands = tmp_path / "bin"
    commands.mkdir()
    limactl = commands / "limactl"
    limactl.write_text(
        "#!/bin/bash\n"
        'case "$1" in\n'
        '  list) if [ "$TEST_EXISTING_VM" = 1 ]; then printf "fixture\\n"; fi ;;\n'
        '  start) printf "%s\\0" "$@" >"$TEST_START_ARGS"\n'
        '    if [ "$TEST_EXISTING_VM" = 0 ]; then cp "${@: -1}" "$TEST_RENDERED_CONFIG"; fi\n'
        '    exit "$TEST_START_STATUS" ;;\n'
        '  shell) cat >/dev/null; printf "guest boot diagnostic\\n"; exit 42 ;;\n'
        "esac\n"
    )
    limactl.chmod(0o700)
    instance = tmp_path / "lima/fixture"
    instance.mkdir(parents=True)
    (instance / "serial.log").write_text("serial boot diagnostic\n")
    (instance / "ha.stderr.log").write_text("hostagent boot diagnostic\n")
    arguments = tmp_path / "arguments"
    rendered_config = tmp_path / "rendered.yml"
    result = subprocess.run(
        ["bash", str(E2E_PATH / "e2e-up.sh"), "fixture"],
        env={
            **os.environ,
            "PATH": f"{commands}:/usr/bin:/bin",
            "LIMA_HOME": str(instance.parent),
            "TMPDIR": str(tmp_path),
            "TEST_EXISTING_VM": str(int(existing_instance)),
            "TEST_START_STATUS": str(start_status),
            "TEST_START_ARGS": str(arguments),
            "TEST_RENDERED_CONFIG": str(rendered_config),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == start_status, result.stderr
    start_arguments = arguments.read_text().split("\0")[:-1]
    if existing_instance:
        assert start_arguments[-1] == "fixture"
    else:
        assert "--containerd=none" in start_arguments
        assert "--name=fixture" in start_arguments
        assert DataLoader().load_from_file(str(rendered_config))["mounts"][0]["location"] == str(E2E_PATH.parent)
    for diagnostic in ("serial boot diagnostic", "hostagent boot diagnostic", "guest boot diagnostic"):
        assert (diagnostic in result.stderr) == bool(start_status)
    assert re.search(rf"phase=vm-start elapsed=\d+s status={start_status}", result.stderr)
    assert not list(tmp_path.glob("workstation-manager-lima-*"))


class ProfilingConfigurationTests(unittest.TestCase):
    """Preserve guest configuration and recover from failed profiling preparation."""

    def test_restores_existing_configuration_and_permissions(self) -> None:
        """Existing settings and callbacks survive profiling, then restore byte-for-byte."""
        original = b"# Keep this comment\n[defaults]\nforks = 3\ncallbacks_enabled = timer\n"
        with tempfile.TemporaryDirectory() as temporary_dir:
            config = pathlib.Path(temporary_dir) / "ansible.cfg"
            config.write_bytes(original)
            config.chmod(0o640)
            backup = task_profiling.prepare(config)
            self.assertEqual(config.stat().st_mode & 0o777, 0o640)
            parser = configparser.ConfigParser()
            parser.read(config)
            self.assertEqual(parser.getint("defaults", "forks"), 3)
            self.assertEqual(
                parser.get("defaults", "callbacks_enabled"),
                "timer, ansible.posix.profile_tasks",
            )
            self.assertTrue(parser.getboolean("defaults", "bin_ansible_callbacks"))
            task_profiling.restore(config, backup)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(config.stat().st_mode & 0o777, 0o640)
            self.assertFalse(backup.exists())

    def test_removes_configuration_when_guest_had_none(self) -> None:
        """A newly created Ansible configuration must not persist after the suite."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            config = pathlib.Path(temporary_dir) / "ansible" / "ansible.cfg"
            backup = task_profiling.prepare(config)
            self.assertTrue(config.is_file())
            self.assertEqual(config.stat().st_mode & 0o777, 0o644)
            task_profiling.restore(config, backup)
            self.assertFalse(config.exists())
            self.assertFalse(backup.exists())

    def test_failed_install_restores_original_configuration(self) -> None:
        """A failure between saving and replacing the config must restore the original."""
        replace = pathlib.Path.replace

        def fail_replacement(source: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
            if source.name == "profile.cfg":
                raise OSError("synthetic install failure")
            return replace(source, target)

        with tempfile.TemporaryDirectory() as temporary_dir:
            config = pathlib.Path(temporary_dir) / "ansible.cfg"
            config.write_text("[defaults]\nforks = 7\n")
            with mock.patch.object(pathlib.Path, "replace", fail_replacement):
                with self.assertRaisesRegex(OSError, "synthetic install failure"):
                    task_profiling.prepare(config)
            self.assertEqual(config.read_text(), "[defaults]\nforks = 7\n")
            self.assertEqual(list(config.parent.iterdir()), [config])


class PhaseTimingTests(unittest.TestCase):
    """Time commands without leaking their arguments or changing failure semantics."""

    def test_preserves_status_and_hides_command_arguments(self) -> None:
        """Timing records must retain failures while never printing credential arguments."""
        for exit_status in (0, 37):
            with self.subTest(exit_status=exit_status):
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'set -euo pipefail; source "$1"; '
                        "run_e2e_timed_command fixture bash -c 'exit \"$1\"' "
                        'fixture "$2" synthetic-vault-password',
                        "timing-test",
                        str(E2E_PATH / "e2e-common.sh"),
                        str(exit_status),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, exit_status, result.stderr)
                self.assertRegex(result.stderr, rf"phase=fixture elapsed=\d+s status={exit_status}")
                self.assertNotIn("synthetic-vault-password", result.stdout + result.stderr)


@pytest.mark.parametrize("state,expected", [("ACTIVE", 0), ("ERROR", 1)])
def test_clipboard_readiness_requires_an_active_extension(state, expected):
    """GNOME readiness checks distinguish a loaded extension from an installed failure."""
    script = r"""
source "$1/e2e-common.sh"
run_e2e_lima_control_command() {
    if [[ "$2" == id ]]; then
        printf '1234\n'
    else
        printf 'State: %s\n' "$TEST_EXTENSION_STATE"
    fi
}
seq() { printf '1\n'; }
sleep() { :; }
wait_for_e2e_clipboard_extension
"""
    result = subprocess.run(
        ["bash", "-c", script, "--", str(E2E_PATH)],
        env={**os.environ, "TEST_EXTENSION_STATE": state},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == expected, result.stdout + result.stderr


class SuiteFailureTests(unittest.TestCase):
    """Exercise suite orchestration with fake actions and no VM or external services."""

    def test_profile_cleanup_preserves_action_and_screenshot_failures(self) -> None:
        """Cleanup always runs, while setup failures still permit the diagnostic screenshot."""
        for setup_status, screenshot_status, restore_status in (
            (0, 0, 0),
            (31, 0, 42),
            (0, 1, 0),
            (0, 0, 42),
        ):
            with self.subTest(setup=setup_status, screenshot=screenshot_status, restore=restore_status):
                with tempfile.TemporaryDirectory() as temporary_dir:
                    fixture = pathlib.Path(temporary_dir)
                    scripts = fixture / "e2e-tests"
                    scripts.mkdir()
                    (scripts / "e2e-test.sh").write_text((E2E_PATH / "e2e-test.sh").read_text())
                    (scripts / "test_setup.py").touch()
                    (scripts / "e2e-common.sh").write_text(
                        (E2E_PATH / "e2e-common.sh").read_text()
                        + '\nprepare_e2e_task_profiling() { printf "prepare\\n" >>"$TEST_TRACE"; }\n'
                        + 'restore_e2e_task_profiling() { printf "restore\\n" >>"$TEST_TRACE"; '
                        + 'return "$TEST_RESTORE_STATUS"; }\n'
                        + "restart_e2e_desktop_session() { :; }\n"
                        + "wait_for_e2e_clipboard_extension() { :; }\n"
                        + 'capture_e2e_vm_desktop() { printf "screenshot\\n" >>"$TEST_TRACE"; '
                        + 'printf "image" >"$2/$1.png"; return "$TEST_SCREENSHOT_STATUS"; }\n'
                    )
                    for phase in ("backup", "setup", "cleanup"):
                        (scripts / f"e2e-{phase}.sh").write_text(
                            f'printf "{phase}\\n" >>"$TEST_TRACE"\n'
                            + ('exit "$TEST_SETUP_STATUS"\n' if phase == "setup" else "exit 0\n")
                        )
                    docker = fixture / "docker"
                    docker.write_text('#!/bin/sh\nprintf "assertions\\n" >>"$TEST_TRACE"\n')
                    docker.chmod(0o700)
                    trace = fixture / "trace"
                    result = subprocess.run(
                        ["bash", str(scripts / "e2e-test.sh"), "fixture"],
                        cwd=fixture,
                        env={
                            **os.environ,
                            "PATH": f"{fixture}:/usr/bin:/bin",
                            "TEST_TRACE": str(trace),
                            "TEST_SETUP_STATUS": str(setup_status),
                            "TEST_SCREENSHOT_STATUS": str(screenshot_status),
                            "TEST_RESTORE_STATUS": str(restore_status),
                        },
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=10,
                    )
                    self.assertEqual(
                        result.returncode,
                        setup_status or screenshot_status or restore_status,
                        result.stderr,
                    )
                    phases = trace.read_text().splitlines()
                    self.assertEqual(phases[0], "prepare")
                    self.assertIn("screenshot", phases)
                    self.assertEqual(phases[-1], "restore")
                    self.assertEqual("cleanup" in phases, setup_status == 0)
                    started_phases = re.findall(r"^E2E phase: (\S+)$", result.stderr, re.MULTILINE)
                    completed_phases = re.findall(r"^E2E timing: phase=(\S+) ", result.stderr, re.MULTILINE)
                    self.assertEqual(completed_phases, started_phases)
