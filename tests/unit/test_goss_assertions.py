"""Validate native Goss suites and recovery probes using synthetic data only."""

# Keep subprocess capture/timeout boilerplate local to these boundary tests.
# pylint: disable=duplicate-code

from __future__ import annotations

import importlib.util
import io
import json
import os
import pathlib
import subprocess
import tarfile

import pytest
import yaml

ROOT = pathlib.Path(__file__).parents[2]


def load_module(name: str, relative: str):
    """Load a consumer probe without executing its guest entrypoint."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="variables")
def variables_fixture(tmp_path, monkeypatch, private_overrides):
    """Normalize maintained defaults with a synthetic private configuration."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USER", "fixture")
    private = tmp_path / ".local/state/workstation-manager/e2e/private.override.yml"
    private.parent.mkdir(parents=True)
    private.write_text(
        yaml.safe_dump({**private_overrides, "user": {"name": "controller", "home": "/home/controller"}})
    )
    module = load_module("goss_variables", "e2e-tests/goss_vars.py")
    values = module.GossVariables().collect()
    path = tmp_path / "vars.json"
    path.write_text(json.dumps(values))
    return path, values


def test_setup_suite_renders_configured_resources_without_private_fields(variables):
    """The real verifier expands includes and consumes current expectations without leaking vault IDs."""
    # Arrange
    path, values = variables
    # Act
    result = subprocess.run(
        ["goss", "-g", str(ROOT / "e2e-tests/goss/setup.yaml"), "--vars", str(path), "render"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    suite = yaml.safe_load(result.stdout)
    # Assert
    expected = {**values["system"]["settings"]["sysctl"], **values["development_sysctl"]}
    assert {resource["name"]: resource["value"] for resource in suite["kernel-param"].values()} == expected
    assert values["user"]["name"] == "fixture"
    assert values["user"]["home"] == str(path.parent)
    assert values["user"]["projects_directory"] == str(path.parent / "Documents/dev-projects")
    assert values["user"]["name"] in suite["user"]
    assert suite["service"]["docker"]["running"]
    assert "browser-sync-automation" in suite["command"]
    assert "22222222-2222-2222-2222-222222222222" not in path.read_text() + result.stdout
    assert not {"secrets", "mcp_servers", "browser_profiles"}.intersection(values)
    for resource in suite["command"].values():
        subprocess.run(["sh", "-n"], input=resource["exec"], text=True, check=True, timeout=5)
        if "<<'PYTHON'" in resource["exec"]:
            python = resource["exec"].split("<<'PYTHON'\n", 1)[1].rsplit("\nPYTHON", 1)[0]
            compile(python, "goss-probe", "exec")


@pytest.mark.parametrize("relative", [True, False])
def test_project_skill_accepts_resolved_links_but_rejects_wrong_targets(variables, relative):
    """A relative link is valid; identical content at the wrong destination is not."""
    # Arrange
    path, values = variables
    project = pathlib.Path(values["user"]["projects_directory"]) / "client-restore"
    source = project / ".skillshare/skills/e2e-project-skill"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("fixture\n")
    target = project / ".agents/skills/e2e-project-skill"
    target.parent.mkdir(parents=True)
    target.symlink_to(os.path.relpath(source, target.parent) if relative else source)
    rendered = subprocess.run(
        ["goss", "-g", str(ROOT / "e2e-tests/goss/setup.yaml"), "--vars", str(path), "render"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    suite = path.parent / "skill.yaml"
    suite.write_text(
        yaml.safe_dump({"command": {"project-skill": yaml.safe_load(rendered.stdout)["command"]["project-skill"]}})
    )
    command = ["goss", "-g", str(suite), "validate"]
    # Act
    passed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    target.unlink()
    target.symlink_to(source.parent)
    (source.parent / "SKILL.md").write_text("fixture\n")
    failed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    # Assert
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert failed.returncode != 0


def test_cleanup_suite_detects_changed_preservation_markers(variables):
    """Native Goss must reject altered user data, including extra lines."""
    # Arrange
    path, values = variables
    home = pathlib.Path(values["user"]["home"])
    root = home / ".config/BraveSoftware/Brave-Browser"
    for profile in ("managed-e2e-stale", "Profile 9999", "e2e-component-cache"):
        directory = root / profile
        directory.mkdir(parents=True)
        (directory / "Preferences").write_text("{}")
        (directory / "e2e-preserve-marker").write_text("preserve\n")
    command = [
        "goss",
        "-g",
        str(ROOT / "e2e-tests/goss/cleanup.yaml"),
        "--vars",
        str(path),
        "validate",
        "--format",
        "junit",
    ]
    # Act
    passed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    (root / "Profile 9999/e2e-preserve-marker").write_text("preserve\nchanged\n")
    failed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    # Assert
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert failed.returncode != 0
    assert "<failure" in failed.stdout


@pytest.mark.parametrize("damage", [None, "recovery-skip", "inventory", "permissions", "local-edit", "private-file"])
def test_backup_probe_preserves_recovery_and_data_safety(tmp_path, damage):
    """Manifest completeness, private artifacts and archived local edits remain required."""
    # Arrange
    module = load_module("backup_probe", "e2e-tests/probes/backup.py")
    base = tmp_path / "workstation-manager-backup-fixture"
    archive = base.with_suffix(".tar.gz")
    manifest = base.with_suffix(".manifest.txt")
    inventory = base.with_suffix(".git-repositories.json")
    restore = base.with_suffix(".restore-command.txt")
    records = [
        f"archive\t{archive}",
        "dry_run\t0",
        f"export\tgit-repositories\t{inventory}",
        f"export\trestore-command\t{restore}",
    ]
    if damage == "recovery-skip":
        records.append("recovery_skipped\tkeys")
    manifest.write_text("\n".join(records))
    inventory.write_text(
        json.dumps(
            [
                {
                    "relative_path": "wrong" if damage == "inventory" else "client-restore",
                    "primary_remote_name": "origin",
                    "primary_remote_url": "/tmp/workstation-manager-e2e-origin-client-restore.git",
                    "branch": "main",
                }
            ]
        )
    )
    restore.write_text(
        "wget -qO- https://raw.githubusercontent.com/fixture/main/workstation.sh | "
        f"WORKSTATION_MANAGER_RESTORE_ARCHIVE={archive} sh -s -- setup\n"
    )
    restore.chmod(0o600)
    entries = {"local-note.txt": b"local-untracked\n", "tracked.txt": b"remote-base\nlocal-change\n"}
    if damage == "local-edit":
        entries["tracked.txt"] = b"remote-base\n"
    if damage == "private-file":
        entries["secret.private"] = b"synthetic"
    with tarfile.open(archive, "w:gz") as content:
        for name, value in entries.items():
            member = tarfile.TarInfo("Documents/dev-projects/client-restore/" + name)
            member.size = len(value)
            content.addfile(member, io.BytesIO(value))
    archive.chmod(0o644 if damage == "permissions" else 0o600)
    failed = False
    # Act
    try:
        module.BackupProbe(tmp_path).verify()
    except AssertionError:
        failed = True
    # Assert
    assert failed is (damage is not None)


@pytest.mark.parametrize("deadline,status", [("1", 124), ("invalid", 2)])
def test_expired_assertion_preparation_never_connects_to_vm(tmp_path, deadline, status):
    """No configuration can be exported after the shared suite deadline."""
    # Arrange
    limactl = tmp_path / "limactl"
    limactl.write_text('#!/bin/sh\ntouch "$HOME/connected"\n')
    limactl.chmod(0o700)
    # Act
    result = subprocess.run(
        ["bash", str(ROOT / "e2e-tests/prepare-assertions.sh"), "fixture", "setup"],
        cwd=tmp_path,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "E2E_SUITE_DEADLINE": deadline,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    # Assert
    assert result.returncode == status
    assert not (tmp_path / "connected").exists()


def test_local_goss_rejects_unowned_guest_directory_without_removing_it(tmp_path):
    """Malformed VM output must never become a cleanup target."""
    # Arrange
    scripts = tmp_path / "e2e-tests"
    scripts.mkdir()
    runner = scripts / "run-assertions.sh"
    runner.write_bytes((ROOT / "e2e-tests/run-assertions.sh").read_bytes())
    (scripts / "prepare-assertions.sh").write_text('mkdir -p "$REPORTS_DIR/goss"\n')
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nprintf '{}'\n")
    docker.chmod(0o700)
    limactl = tmp_path / "limactl"
    limactl.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        "  *mktemp*) printf /home/fixture/important-data;;\n"
        '  *"rm -rf"*) touch "$HOME/removed";;\n'
        "  *) exit 99;;\nesac\n"
    )
    limactl.chmod(0o700)
    # Act
    result = subprocess.run(
        ["bash", str(runner), "fixture", "backup"],
        cwd=tmp_path,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "REPORTS_DIR": str(tmp_path / "reports"),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    # Assert
    assert result.returncode == 1
    assert not (tmp_path / "removed").exists()
