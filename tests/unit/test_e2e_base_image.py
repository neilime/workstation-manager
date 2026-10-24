"""Validate desktop fixture identity, offline construction, and fail-closed reuse."""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

WORKSPACE = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("e2e_base_image", WORKSPACE / "ci/e2e_base_image.py")
assert SPEC is not None and SPEC.loader is not None
base_image = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base_image)
SOURCE = b"synthetic public Ubuntu cloud image"
TODAY = datetime.date(2026, 1, 7)


@pytest.fixture(name="builder")
def fixture_builder(tmp_path):
    """Identify synthetic upstream content using the maintained recipe inputs."""
    root = tmp_path / "repository"
    for relative in (*base_image.RECIPES, "ci/e2e_base_image.py"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((WORKSPACE / relative).read_bytes())
    (root / "e2e-tests/lima-ubuntu.yml").write_text(
        'images:\n  - location: "https://cloud-images.ubuntu.com/releases/99.01/release/fixture-amd64.img"\n'
        '    arch: "x86_64"\n',
        encoding="utf-8",
    )
    return base_image.DesktopBaseImage(root)


def source_checksums(content: bytes = SOURCE) -> str:
    """Publish the same checksum format as the upstream SHA256SUMS file."""
    return hashlib.sha256(content).hexdigest() + " *fixture-amd64.img\n"


def test_base_image_identity_reuses_unchanged_inputs_within_a_week(builder):
    """Application edits do not rebuild desktop prerequisites, while package refreshes remain bounded."""
    original = builder.identify(source_checksums(), TODAY)
    (builder.root / "workstation.sh").write_text("changed workstation implementation\n", encoding="utf-8")
    assert builder.identify(source_checksums(), TODAY + datetime.timedelta(days=4)) == original
    assert builder.identify(source_checksums(), TODAY + datetime.timedelta(days=5))["key"] != original["key"]


@pytest.mark.parametrize("relative", [*base_image.RECIPES, "ci/e2e_base_image.py"])
def test_base_image_identity_invalidates_each_recipe_input(builder, relative):
    """Any package, cleanup, or image-building change invalidates the cached prerequisite image."""
    original = builder.identify(source_checksums(), TODAY)
    path = builder.root / relative
    path.write_text(path.read_text(encoding="utf-8") + "\n# changed recipe\n", encoding="utf-8")
    assert builder.identify(source_checksums(), TODAY)["key"] != original["key"]


def test_base_image_identity_invalidates_changed_upstream_content(builder):
    """A mutable upstream release URL cannot reuse an image built from different source bytes."""
    original = builder.identify(source_checksums(), TODAY)
    changed = builder.identify(source_checksums(b"updated public source"), TODAY)
    assert changed["key"] != original["key"]
    assert changed["source_sha256"] == hashlib.sha256(b"updated public source").hexdigest()


@pytest.mark.parametrize("checksums", ["", source_checksums() * 2, "invalid *fixture-amd64.img\n"])
def test_base_image_identity_requires_an_unambiguous_upstream_checksum(builder, checksums):
    """Missing, duplicate, and malformed checksum records cannot produce a cache key."""
    with pytest.raises(ValueError, match="one SHA-256"):
        builder.identify(checksums, TODAY)


@pytest.mark.parametrize("damage", ["image", "key", "manifest"])
def test_base_image_verification_rejects_corrupt_or_unrelated_cached_output(tmp_path, damage):
    """Consumers must validate both the output bytes and the expected build identity."""
    image = tmp_path / "desktop.qcow2"
    image.write_bytes(b"prepared desktop")
    metadata = {"key": "synthetic-inputs"}
    manifest = image.with_suffix(".json")
    manifest.write_text(
        json.dumps({**metadata, "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}), encoding="utf-8"
    )
    assert base_image.DesktopBaseImage.verify(image, metadata) == hashlib.sha256(image.read_bytes()).hexdigest()
    if damage == "image":
        image.write_bytes(b"truncated")
    elif damage == "key":
        metadata["key"] = "different-inputs"
    else:
        manifest.write_text("truncated JSON {", encoding="utf-8")
    with pytest.raises(ValueError):
        base_image.DesktopBaseImage.verify(image, metadata)


@pytest.fixture(name="image_commands")
def fixture_image_commands(monkeypatch):
    """Simulate disk tools at their process boundary without opening a VM or host disk."""
    calls = []
    execute_shell = subprocess.run

    def run(command, **options):
        assert options["check"] is True
        calls.append(command)
        if command[:2] == ["qemu-img", "create"]:
            Path(command[-2]).write_bytes(b"empty disk")
        elif command[0] == "virt-resize":
            assert Path(command[-2]).read_bytes() == SOURCE
            Path(command[-1]).write_bytes(SOURCE)
        elif command[0] == "virt-customize":
            disk = Path(command[command.index("-a") + 1])
            assert disk.read_bytes() == SOURCE
            disk.write_bytes(b"prepared desktop")
            assert options["env"]["LIBGUESTFS_BACKEND"] == "direct"
            assert "XDG_RUNTIME_DIR" not in options["env"]
        elif command[:2] == ["qemu-img", "convert"]:
            Path(command[-1]).write_bytes(Path(command[-2]).read_bytes())
        else:
            pytest.fail(f"Unexpected disk or VM operation: {command[0]}")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        base_image.urllib.request, "urlopen", Mock(side_effect=lambda *args, **kwargs: io.BytesIO(SOURCE))
    )
    monkeypatch.setattr(base_image.subprocess, "run", run)
    return calls, run, execute_shell


def test_base_image_build_rejects_root_before_creating_or_downloading_image(
    builder, image_commands, tmp_path, monkeypatch
):
    """Image construction requires one unprivileged owner for libguestfs and its network helper."""
    monkeypatch.setattr(base_image.os, "geteuid", lambda: 0)
    image = tmp_path / "cache/desktop.qcow2"

    with pytest.raises(PermissionError, match="without sudo"):
        builder.build(image, builder.identify(source_checksums(), TODAY))

    base_image.urllib.request.urlopen.assert_not_called()
    assert image_commands[0] == []
    assert not image.parent.exists()


def test_base_image_build_customizes_only_a_fresh_download(builder, image_commands, tmp_path, monkeypatch):
    """Building prerequisites never reads or modifies an existing authenticated Lima instance."""
    live_vm = tmp_path / "lima/fixture/diffdisk"
    live_vm.parent.mkdir(parents=True)
    live_vm.write_bytes(b"existing workstation and credentials")
    monkeypatch.setenv("LIMA_HOME", str(live_vm.parent.parent))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "user-session"))
    image = tmp_path / "cache/desktop.qcow2"
    metadata = builder.identify(source_checksums(), TODAY)

    builder.build(image, metadata)

    assert live_vm.read_bytes() == b"existing workstation and credentials"
    assert image.read_bytes() == b"prepared desktop"
    assert builder.verify(image, metadata) == hashlib.sha256(image.read_bytes()).hexdigest()
    base_image.urllib.request.urlopen.assert_called_once_with(metadata["source_url"], timeout=60)
    calls, _, _ = image_commands
    customize = next(command for command in calls if command[0] == "virt-customize")
    assert "-d" not in customize
    assert str(live_vm) not in json.dumps(calls)
    assert Path(customize[customize.index("-a") + 1]).parent.parent == image.parent
    assert not list(image.parent.glob("e2e-base-*"))


@pytest.mark.parametrize("failed_stage", ["create", "virt-resize", "virt-customize", "convert"])
def test_base_image_failed_disk_operations_publish_nothing(
    builder, image_commands, tmp_path, monkeypatch, failed_stage
):
    """Any failed download preparation, customization, or compression leaves no reusable output."""
    calls, successful_run, _ = image_commands

    def failing_run(command, **options):
        stage = command[1] if command[0] == "qemu-img" else command[0]
        if stage == failed_stage:
            raise subprocess.CalledProcessError(37, command)
        return successful_run(command, **options)

    monkeypatch.setattr(base_image.subprocess, "run", failing_run)
    image = tmp_path / "cache/desktop.qcow2"
    with pytest.raises(subprocess.CalledProcessError):
        builder.build(image, builder.identify(source_checksums(), TODAY))
    assert not image.exists()
    assert not image.with_suffix(".json").exists()
    assert not list(image.parent.glob("e2e-base-*"))
    assert all("limactl" not in command for command in calls)


def test_base_image_bad_source_checksum_prevents_disk_commands(builder, image_commands, tmp_path):
    """Unverified upstream bytes never reach any disk customization command."""
    calls, _, _ = image_commands
    image = tmp_path / "cache/desktop.qcow2"
    with pytest.raises(ValueError, match="checksum mismatch"):
        builder.build(image, builder.identify(source_checksums(b"different download"), TODAY))
    assert calls == []
    assert not image.exists()


@pytest.fixture(name="desktop_recipe")
def fixture_desktop_recipe(tmp_path):
    """Execute the actual guest recipe with host-changing commands replaced and paths isolated."""
    marker = tmp_path / "recipe-marker"
    script = tmp_path / "install-desktop.sh"
    script.write_text(
        (WORKSPACE / "e2e-tests/base-image/install-desktop.sh")
        .read_text(encoding="utf-8")
        .replace("marker=/var/lib/workstation-manager-e2e-base", "marker=" + shlex.quote(str(marker)))
        .replace("/etc/netplan", shlex.quote(str(tmp_path / "netplan"))),
        encoding="utf-8",
    )
    commands = tmp_path / "bin"
    commands.mkdir()
    dispatcher = commands / "fixture-command"
    dispatcher.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "name = pathlib.Path(sys.argv[0]).name\n"
        "with open(os.environ['TEST_TRACE'], 'a') as trace: trace.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
        "if name == 'debconf-set-selections': sys.stdin.read()\n"
        "if name == 'apt-get':\n"
        "    netplan = pathlib.Path(os.environ['TEST_NETPLAN'])\n"
        "    assert netplan.read_text(encoding='utf-8') == 'network:\\n  version: 2\\n  renderer: networkd\\n'\n"
        "    assert netplan.stat().st_mode & 0o777 == 0o600\n"
        "if name == 'apt-get' and os.environ.get('TEST_APT_FAILURE') in sys.argv[1:]: sys.exit(37)\n"
        "if name == 'dpkg-query': print(os.environ.get('TEST_PACKAGE_STATE', 'installed'), end='')\n",
        encoding="utf-8",
    )
    dispatcher.chmod(0o700)
    for command in ("apt-get", "sed", "debconf-set-selections", "dpkg-query"):
        (commands / command).symlink_to(dispatcher)
    environment = {
        **os.environ,
        "PATH": f"{commands}:/usr/bin:/bin",
        "TEST_TRACE": str(tmp_path / "trace"),
        "TEST_NETPLAN": str(tmp_path / "netplan/99-lima-networkd.yaml"),
    }
    return script, marker, environment


def run_recipe(recipe, **variables):
    """Bound the isolated shell execution and expose its failure to the test."""
    script, _, environment = recipe
    return subprocess.run(
        ["bash", str(script)], env={**environment, **variables}, capture_output=True, text=True, check=False, timeout=10
    )


def test_base_image_runs_uploaded_recipe_bytes_with_bash(
    builder, image_commands, desktop_recipe, tmp_path, monkeypatch
):
    """Offline customization preserves Bash semantics and the recipe's own file checksum."""
    script, marker, environment = desktop_recipe
    install = builder.root / base_image.RECIPES[0]
    install.write_bytes(script.read_bytes())
    # Cleanup has its own isolated test; this test executes only package provisioning.
    (builder.root / base_image.RECIPES[1]).write_text("#!/usr/bin/env bash\nset -euo pipefail\n", encoding="utf-8")
    guest = tmp_path / "guest"
    guest.mkdir()
    uploads = {}
    _, disk_command, execute_shell = image_commands

    def run(command, **options):
        if command[0] == "virt-customize":
            for index, option in enumerate(command):
                if option == "--upload":
                    source, destination = command[index + 1].split(":", 1)
                    path = guest / destination.lstrip("/")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(Path(source).read_bytes())
                    uploads[destination] = path
                elif option == "--run-command":
                    arguments = shlex.split(command[index + 1])
                    shell_command = shlex.join([str(uploads.get(value, value)) for value in arguments])
                    execute_shell(["sh", "-c", shell_command], env=environment, check=True, timeout=10)
                elif option == "--run":
                    # libguestfs prepends a shell wrapper to script text; a Bash shebang cannot select Bash here.
                    shell_command = ":\n" + Path(command[index + 1]).read_text(encoding="utf-8")
                    execute_shell(["sh", "-c", shell_command], env=environment, check=True, timeout=10)
        return disk_command(command, **options)

    monkeypatch.setattr(base_image.subprocess, "run", run)
    image = tmp_path / "cache/desktop.qcow2"
    builder.build(image, builder.identify(source_checksums(), TODAY))
    assert marker.read_text(encoding="utf-8").strip() == hashlib.sha256(install.read_bytes()).hexdigest()
    assert install.read_bytes() in [path.read_bytes() for path in uploads.values()]
    assert builder.verify(image, builder.identify(source_checksums(), TODAY))


@pytest.mark.parametrize("failure", ["update", "install"])
def test_desktop_recipe_package_failures_never_mark_the_image_complete(desktop_recipe, failure):
    """A failed package index or installation prevents future provisioning from trusting the image."""
    result = run_recipe(desktop_recipe, TEST_APT_FAILURE=failure)
    assert result.returncode == 37, result.stderr
    assert not desktop_recipe[1].exists()


def test_desktop_recipe_validates_cached_packages_without_running_apt(desktop_recipe):
    """An unchanged prerequisite recipe avoids APT only while every declared package remains installed."""
    script, marker, environment = desktop_recipe
    result = run_recipe(desktop_recipe)
    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8").strip() == hashlib.sha256(script.read_bytes()).hexdigest()
    trace = Path(environment["TEST_TRACE"])
    calls = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    install = next(command for command in calls if command[0] == "apt-get" and "install" in command)
    packages = install[install.index("--no-install-recommends") + 1 :]
    trace.write_text("", encoding="utf-8")
    assert run_recipe(desktop_recipe).returncode == 0
    calls = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert [command[-1] for command in calls if command[0] == "dpkg-query"] == packages
    assert not any(command[0] == "apt-get" for command in calls)
    assert run_recipe(desktop_recipe, TEST_PACKAGE_STATE="config-files").returncode != 0


@pytest.mark.parametrize("cached", [False, True])
def test_desktop_recipe_preserves_networkd_for_fresh_and_prepared_images(desktop_recipe, cached):
    """Desktop prerequisites configure Lima's network renderer before package installation or cached reuse."""
    if cached:
        assert run_recipe(desktop_recipe).returncode == 0
    netplan = Path(desktop_recipe[2]["TEST_NETPLAN"])
    netplan.parent.mkdir(exist_ok=True)
    netplan.write_text("network:\n  version: 2\n  renderer: NetworkManager\n", encoding="utf-8")
    netplan.chmod(0o644)

    result = run_recipe(desktop_recipe)

    assert result.returncode == 0, result.stderr
    assert netplan.read_text(encoding="utf-8") == "network:\n  version: 2\n  renderer: networkd\n"
    assert netplan.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("identity_layout", ["regular", "etc-link", "dbus-link", "missing"])
def test_image_cleanup_removes_instance_identity_and_transient_files(tmp_path, identity_layout):
    """Reusable images request fresh systemd identity regardless of the source's machine-ID file layout."""
    guest = tmp_path / "guest"
    removed = (
        "etc/ssh/ssh_host_ed25519_key",
        "etc/ssh/ssh_host_ed25519_key.pub",
        "var/lib/dbus/machine-id",
        "var/lib/apt/lists/package-index",
        "tmp/builder.log",
        "var/tmp/package-state",
    )
    retained = ("var/log/package.log", "var/lib/workstation-manager-e2e-base", "etc/ssh/sshd_config")
    for relative in (*removed, *retained):
        path = guest / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic guest state", encoding="utf-8")
    machine_id = guest / "etc/machine-id"
    dbus_id = guest / "var/lib/dbus/machine-id"
    if identity_layout == "etc-link":
        machine_id.symlink_to(dbus_id)
    elif identity_layout == "missing":
        dbus_id.unlink()
    else:
        machine_id.write_text("synthetic machine identity\n", encoding="utf-8")
        if identity_layout == "dbus-link":
            dbus_id.unlink()
            dbus_id.symlink_to(machine_id)
    script = tmp_path / "clean-image.sh"
    content = (WORKSPACE / "e2e-tests/base-image/clean-image.sh").read_text(encoding="utf-8")
    content = re.sub(
        r"/etc/ssh|/etc/machine-id|/var/lib/dbus|/var/lib/apt/lists|/var/tmp|/var/log|/tmp",
        lambda match: shlex.quote(str(guest / match[0].lstrip("/"))),
        content,
    )
    script.write_text(content, encoding="utf-8")
    commands = tmp_path / "bin"
    commands.mkdir()
    for name in ("apt-get", "cloud-init"):
        stub = commands / name
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >"$TEST_TRACE/$(basename "$0")"\n', encoding="utf-8")
        stub.chmod(0o700)
    trace = tmp_path / "trace"
    trace.mkdir()

    subprocess.run(
        ["bash", str(script)],
        env={**os.environ, "PATH": f"{commands}:/usr/bin:/bin", "TEST_TRACE": str(trace)},
        check=True,
        timeout=10,
    )

    assert (trace / "cloud-init").read_text(encoding="utf-8").splitlines() == ["clean", "--logs"]
    assert not machine_id.is_symlink()
    assert machine_id.read_text(encoding="utf-8") == "uninitialized\n"
    assert machine_id.stat().st_mode & 0o777 == 0o444
    assert not any((guest / relative).exists() for relative in removed)
    assert (guest / "var/log/package.log").read_text(encoding="utf-8") == ""
    assert (guest / "var/lib/workstation-manager-e2e-base").read_text(encoding="utf-8") == "synthetic guest state"
    assert (guest / "etc/ssh/sshd_config").read_text(encoding="utf-8") == "synthetic guest state"


@pytest.mark.parametrize("existing", [False, True])
def test_vm_creation_uses_verified_local_image_only_for_new_instances(tmp_path, existing):
    """Prepared image selection pins its content for new VMs and cannot replace an existing instance."""
    image = tmp_path / "prepared image.qcow2"
    image.write_bytes(b"prepared public desktop")
    arguments = tmp_path / "start-arguments"
    commands = tmp_path / "bin"
    commands.mkdir()
    limactl = commands / "limactl"
    limactl.write_text(
        '#!/bin/bash\ncase "$1" in\n'
        '  list) if [[ "$TEST_EXISTING" == 1 ]]; then printf "fixture\\n"; fi ;;\n'
        '  start) printf "%s\\0" "$@" >"$TEST_ARGUMENTS" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    limactl.chmod(0o700)
    result = subprocess.run(
        ["bash", str(WORKSPACE / "e2e-tests/e2e-up.sh"), "fixture"],
        env={
            **os.environ,
            "PATH": f"{commands}:/usr/bin:/bin",
            "TMPDIR": str(tmp_path),
            "E2E_BASE_IMAGE": str(image),
            "E2E_VM_CPUS": "",
            "E2E_VM_MEMORY_GIB": "",
            "TEST_EXISTING": str(int(existing)),
            "TEST_ARGUMENTS": str(arguments),
            "REPORTS_DIR": "",
            "GITHUB_STEP_SUMMARY": "",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    values = arguments.read_text(encoding="utf-8").split("\0")[:-1]
    if existing:
        assert "--set" not in values
        assert values[-1] == "fixture"
    else:
        override = values[values.index("--set") + 1]
        selected = json.loads(override.removeprefix(".images = "))
        assert selected == [
            {
                "location": str(image),
                "arch": "x86_64",
                "digest": "sha256:" + hashlib.sha256(image.read_bytes()).hexdigest(),
            }
        ]
    assert image.read_bytes() == b"prepared public desktop"
    assert not list(tmp_path.glob("workstation-manager-lima-*"))
