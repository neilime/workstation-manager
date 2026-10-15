"""Keep E2E timing and temporary profiling transparent to action failures."""

from __future__ import annotations

import configparser
import importlib.util
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock

import pytest
from ansible.parsing.dataloader import DataLoader

E2E_PATH = pathlib.Path(__file__).parents[1]


def load_guest_module(name: str) -> types.ModuleType:
    """Load the guest helper without making e2e-tests a Python package."""
    module_path = E2E_PATH / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


task_profiling = load_guest_module("task_profiling")


def test_browser_metrics_expose_only_selected_numeric_buckets(capsys: pytest.CaptureFixture[str]) -> None:
    """Browser response fields outside the fixed numeric metrics never enter logs."""
    diagnostics = load_guest_module("browser_sync_diagnostics")
    pipe = mock.Mock()
    pipe.call.return_value = {
        "histograms": [
            {"name": "private-value", "buckets": ["private-value"]},
            {
                "name": "Sync.URLFetchResponse",
                "buckets": [{"low": 200, "high": 201, "count": 1}],
                "extra": "private-value",
            },
        ]
    }
    diagnostics.network_metrics(pipe)
    assert capsys.readouterr().out == 'Sync.URLFetchResponse: [{"low": 200, "high": 201, "count": 1}]\n'


@pytest.mark.parametrize(
    "bucket", [{"low": "private-value", "high": 201, "count": 1}, {"low": True, "high": 201, "count": 1}]
)
def test_browser_metrics_reject_non_numeric_buckets(bucket: dict, capsys: pytest.CaptureFixture[str]) -> None:
    """Malformed metric values fail with a fixed error and no browser payload."""
    diagnostics = load_guest_module("browser_sync_diagnostics")
    pipe = mock.Mock()
    pipe.call.return_value = {"histograms": [{"name": "Sync.URLFetchResponse", "buckets": [bucket]}]}
    with pytest.raises(ValueError, match="^Unexpected numeric Sync metrics$"):
        diagnostics.network_metrics(pipe)
    assert not capsys.readouterr().out


@pytest.mark.parametrize(
    "existing_instance,start_status,resources",
    [
        (False, 0, {}),
        (True, 0, {"E2E_VM_CPUS": "4"}),
        (False, 37, {}),
        (False, 0, {"E2E_VM_CPUS": "4", "E2E_VM_MEMORY_GIB": "8"}),
    ],
)
def test_vm_start_preserves_failures_and_collects_diagnostics(
    tmp_path: pathlib.Path, existing_instance: bool, start_status: int, resources: dict[str, str]
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
            "E2E_VM_CPUS": "",
            "E2E_VM_MEMORY_GIB": "",
            **resources,
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
        assert not any(argument.startswith(("--cpus=", "--memory=")) for argument in start_arguments)
    else:
        assert "--containerd=none" in start_arguments
        assert "--name=fixture" in start_arguments
        assert DataLoader().load_from_file(str(rendered_config))["mounts"][0]["location"] == str(E2E_PATH.parent)
        for variable, flag in (("E2E_VM_CPUS", "--cpus="), ("E2E_VM_MEMORY_GIB", "--memory=")):
            assert [argument for argument in start_arguments if argument.startswith(flag)] == (
                [flag + resources[variable]] if variable in resources else []
            )
    for diagnostic in ("serial boot diagnostic", "hostagent boot diagnostic", "guest boot diagnostic"):
        assert (diagnostic in result.stderr) == bool(start_status)
    assert re.search(rf"phase=vm-start elapsed=\d+s status={start_status}", result.stderr)
    assert not list(tmp_path.glob("workstation-manager-lima-*"))


@pytest.mark.parametrize("variable,value", [("E2E_VM_CPUS", "0"), ("E2E_VM_MEMORY_GIB", "1.5")])
def test_vm_creation_rejects_invalid_resources(tmp_path: pathlib.Path, variable: str, value: str) -> None:
    """Invalid resource overrides fail before starting a VM and remove temporary configuration."""
    limactl = tmp_path / "limactl"
    limactl.write_text('#!/bin/bash\n[[ "$1" == list ]] || touch "$TEST_STARTED"\n')
    limactl.chmod(0o700)
    started = tmp_path / "started"
    result = subprocess.run(
        ["bash", str(E2E_PATH / "e2e-up.sh"), "fixture"],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "TMPDIR": str(tmp_path),
            "TEST_STARTED": str(started),
            "E2E_VM_CPUS": "",
            "E2E_VM_MEMORY_GIB": "",
            variable: value,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    assert f"{variable} must be a positive integer" in result.stderr
    assert not started.exists()
    assert not list(tmp_path.glob("workstation-manager-lima-*"))


@pytest.mark.parametrize("tooling_status,vm_status", [(0, 0), (37, 0), (0, 42)])
def test_e2e_preparation_overlaps_work_and_propagates_failures(
    tmp_path: pathlib.Path, tooling_status: int, vm_status: int
) -> None:
    """Both prerequisites must start before either finishes, and either failure fails preparation."""
    shutil.copyfile(E2E_PATH.parent / "Makefile", tmp_path / "Makefile")
    scripts = tmp_path / "e2e-tests"
    scripts.mkdir()
    commands = tmp_path / "bin"
    commands.mkdir()
    rendezvous = (
        'touch "$TEST_PREPARE_TRACE/$own"\n'
        "for attempt in {1..100}; do\n"
        '  if [[ -e "$TEST_PREPARE_TRACE/$other" ]]; then exit "$status"; fi\n'
        "  sleep 0.02\n"
        "done\nexit 99\n"
    )
    for script, body in (
        (commands / "limactl", "exit 0\n"),
        (
            commands / "docker",
            '[[ "$1" == image ]] && exit 1\nown=tooling; other=vm; status="$TEST_TOOLING_STATUS"\n' + rendezvous,
        ),
        (scripts / "e2e-up.sh", 'own=vm; other=tooling; status="$TEST_VM_STATUS"\n' + rendezvous),
    ):
        script.write_text("#!/bin/bash\n" + body)
        script.chmod(0o700)
    for executable in ("qemu-img", "qemu-system-x86_64"):
        (commands / executable).symlink_to(commands / "limactl")
    result = subprocess.run(
        ["make", "e2e-prepare", "TOOLING_IMAGE_PULL=1"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{commands}:/usr/bin:/bin",
            "TEST_PREPARE_TRACE": str(tmp_path),
            "TEST_TOOLING_STATUS": str(tooling_status),
            "TEST_VM_STATUS": str(vm_status),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert (result.returncode == 0) == (tooling_status == vm_status == 0), result.stdout + result.stderr
    assert "Error 99" not in result.stderr, "Preparation serialized work instead of overlapping it"
    assert (tmp_path / "tooling").exists()
    assert (tmp_path / "vm").exists()


@pytest.mark.parametrize(
    "initially_active,format_status,probe_status", [(False, 0, 0), (True, 0, 0), (False, 37, 0), (True, 0, 42)]
)
def test_vm_swap_preserves_active_pages_and_requires_successful_formatting(
    tmp_path: pathlib.Path, initially_active: bool, format_status: int, probe_status: int
) -> None:
    """Provisioning skips active swap, fails closed on probe errors, and requires successful formatting."""
    config = DataLoader().load_from_file(str(E2E_PATH / "lima-ubuntu.yml"))
    provision = next(entry["script"] for entry in config["provision"] if "swapon --show" in entry["script"])
    swapfile = tmp_path / "fixture.swap"
    swapfile.write_text("existing pages")
    active = tmp_path / "active"
    if initially_active:
        active.write_text(str(swapfile) + "\n")
    commands = tmp_path / "bin"
    commands.mkdir()
    trace = tmp_path / "trace"
    for name, body in (
        (
            "swapon",
            'if [[ "$1" == --show=NAME ]]; then\n'
            '  if [[ "$TEST_PROBE_STATUS" != 0 ]]; then exit "$TEST_PROBE_STATUS"; fi\n'
            '  if [[ -f "$TEST_ACTIVE" ]]; then cat "$TEST_ACTIVE"; fi\n'
            "else\n"
            '  printf "%s\\n" "$1" >"$TEST_ACTIVE"\n'
            '  printf "activate\\n" >>"$TEST_TRACE"\n'
            "fi\n",
        ),
        ("fallocate", '[[ "$1" == --length && "$2" == 4GiB ]] || exit 99\nprintf "pages" >"$3"\n'),
        (
            "mkswap",
            'printf "format\\n" >>"$TEST_TRACE"\nexit "$TEST_FORMAT_STATUS"\n',
        ),
    ):
        command = commands / name
        command.write_text("#!/bin/bash\nset -eu\n" + body)
        command.chmod(0o700)
    for _ in range(2):
        result = subprocess.run(
            ["bash", "-c", provision.replace("/var/lib/workstation-manager-e2e.swap", shlex.quote(str(swapfile)))],
            env={
                **os.environ,
                "PATH": f"{commands}:/usr/bin:/bin",
                "TEST_ACTIVE": str(active),
                "TEST_TRACE": str(trace),
                "TEST_FORMAT_STATUS": str(format_status),
                "TEST_PROBE_STATUS": str(probe_status),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == (probe_status or format_status), result.stderr
    if initially_active:
        assert swapfile.read_text() == "existing pages"
        assert not trace.exists()
    else:
        assert swapfile.stat().st_mode & 0o777 == 0o600
        assert active.exists() == (format_status == 0)
        assert trace.read_text().splitlines() == (["format", "format"] if format_status else ["format", "activate"])


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
            with self.subTest(exit_status=exit_status), tempfile.TemporaryDirectory() as temporary_dir:
                summary = pathlib.Path(temporary_dir) / "summary.md"
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
                    env={**os.environ, "GITHUB_STEP_SUMMARY": str(summary)},
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, exit_status, result.stderr)
                self.assertRegex(result.stderr, rf"phase=fixture elapsed=\d+s status={exit_status}")
                self.assertRegex(summary.read_text(), rf"- E2E fixture: \d+s \(exit {exit_status}\)")
                self.assertNotIn("synthetic-vault-password", result.stdout + result.stderr + summary.read_text())

    def test_summary_failure_preserves_the_action_status(self) -> None:
        """An unavailable summary destination must not replace the original action failure."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'set -euo pipefail; source "$1"; run_e2e_timed_command fixture bash -c "exit 37"',
                    "timing-test",
                    str(E2E_PATH / "e2e-common.sh"),
                ],
                env={**os.environ, "GITHUB_STEP_SUMMARY": temporary_dir},
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertIn("Could not append E2E timing", result.stderr)


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


@pytest.mark.parametrize(
    "scenario,expected_status,expected_trace",
    [
        ("ready", 0, ["logout", "wait", "logged-out", "restart", "unlock"]),
        ("locked-keyring", 37, ["logout", "wait", "logged-out", "restart", "unlock"]),
        ("logout-failed", 31, ["logout"]),
        ("logout-stuck", 1, ["logout", "wait", "wait"]),
        ("sessions-unavailable", 29, ["logout"]),
        ("missing-session", 1, []),
        ("restart-failed", 38, ["logout", "wait", "logged-out", "restart"]),
    ],
)
def test_desktop_restart_waits_for_logout_and_keyring(
    tmp_path: pathlib.Path, scenario: str, expected_status: int, expected_trace: list[str]
) -> None:
    """Relogin waits for the old session to close, and recovery requires an unlocked keyring."""

    trace = tmp_path / "trace"
    trace.touch()
    script = r"""
source "$1/e2e-common.sh"
loginctl() {
    case "$1" in
        show-user)
            if [[ "$TEST_SCENARIO" != missing-session ]]; then printf 'graphical-42\n'; fi
            ;;
        list-sessions)
            [[ "$TEST_SCENARIO" != sessions-unavailable ]] || return 29
            printf 'ssh-7 1234 fixture -\n'
            if [[ "$TEST_SCENARIO" != logout-stuck ]] && grep -Fxq wait "$TEST_TRACE"; then
                printf 'logged-out\n' >>"$TEST_TRACE"
            else
                printf 'graphical-42 1234 fixture seat0\n'
            fi
            ;;
        *) return 99 ;;
    esac
}
gnome-session-quit() {
    printf 'logout\n' >>"$TEST_TRACE"
    [[ "$TEST_SCENARIO" != logout-failed ]] || return 31
}
sleep() { printf 'wait\n' >>"$TEST_TRACE"; }
seq() { printf '1\n2\n'; }
export -f loginctl gnome-session-quit sleep seq
run_e2e_lima_control_command() {
    case "$2" in
        id) printf '1234\n' ;;
        pgrep) if grep -Fxq restart "$TEST_TRACE"; then printf '200\n'; else printf '100\n'; fi ;;
        env) shift; "$@" ;;
        sudo)
            printf 'restart\n' >>"$TEST_TRACE"
            [[ "$TEST_SCENARIO" != restart-failed ]] || return 38
            ;;
        bash)
            printf 'unlock\n' >>"$TEST_TRACE"
            [[ "$TEST_SCENARIO" != locked-keyring ]] || return 37
            ;;
        *) return 99 ;;
    esac
}
restart_e2e_desktop_session
"""
    result = subprocess.run(
        ["bash", "-c", script, "--", str(E2E_PATH)],
        env={**os.environ, "TEST_TRACE": str(trace), "TEST_SCENARIO": scenario},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == expected_status, result.stdout + result.stderr
    assert trace.read_text().splitlines() == expected_trace


def test_assertions_keep_ssh_sockets_outside_read_only_lima_state(tmp_path: pathlib.Path) -> None:
    """Pytest's real SSH backend overrides the socket while retaining Lima's connection options."""

    config = tmp_path / "lima.config"
    original = "Host *\n  User fixture-user\n  ControlMaster auto\n  ControlPath /read-only-lima/ssh.sock\n"
    config.write_text(original)
    config.chmod(0o400)
    effective_config = tmp_path / "effective-config"
    ssh_executable = shutil.which("ssh")
    assert ssh_executable is not None
    ssh = tmp_path / "ssh"
    ssh.write_text(
        f'#!/bin/sh\nset -eu\n{shlex.quote(ssh_executable)} -G "$@" >"$TEST_SSH_CONFIG"\nprintf \'fixture\\n\'\n'
    )
    ssh.chmod(0o700)
    test = tmp_path / "test_connection.py"
    test.write_text('def test_connection(host):\n    assert host.check_output("true") == "fixture"\n')
    subprocess.run(
        ["bash", str(E2E_PATH / "run-assertions.sh"), str(config), "-q", "--hosts=ssh://fixture", str(test)],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "TEST_SSH_CONFIG": str(effective_config)},
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    settings = dict(line.split(" ", 1) for line in effective_config.read_text().splitlines())
    assert pathlib.Path(settings["controlpath"]).parent == pathlib.Path("/tmp")
    assert settings["controlmaster"] == "auto"
    assert settings["user"] == "fixture-user"
    assert config.read_text() == original


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
                        + 'print_e2e_desktop_diagnostics() { printf "desktop-diagnostics\\n" >>"$TEST_TRACE"; '
                        + "return 43; }\n"
                        + 'run_e2e_lima_shell() { printf "browser-diagnostics\\n" >>"$TEST_TRACE"; return 44; }\n'
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
                    self.assertEqual("desktop-diagnostics" in phases, setup_status != 0)
                    if setup_status:
                        self.assertLess(phases.index("desktop-diagnostics"), phases.index("browser-diagnostics"))
                    started_phases = re.findall(r"^E2E phase: (\S+)$", result.stderr, re.MULTILINE)
                    completed_phases = re.findall(r"^E2E timing: phase=(\S+) ", result.stderr, re.MULTILINE)
                    self.assertEqual(completed_phases, started_phases)
