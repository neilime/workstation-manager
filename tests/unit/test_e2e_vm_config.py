"""Validate the public source and image supplied to an isolated CI guest."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest
from ansible.parsing.dataloader import DataLoader

from ci.e2e_vm_config import WorkstationVMConfig

WORKSPACE = Path(__file__).parents[2]
REVISION = "a" * 40


@pytest.fixture(name="configuration")
def configuration_fixture(tmp_path):
    """Prepare an image and its matching public build manifest."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    metadata = {"key": "synthetic-desktop-inputs"}
    (cache / "e2e-base-inputs.json").write_text(json.dumps(metadata))
    image = cache / "desktop.qcow2"
    image.write_bytes(b"public desktop fixture")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    image.with_suffix(".json").write_text(json.dumps({**metadata, "sha256": digest}))
    return WorkstationVMConfig(tmp_path), image, digest


def test_vm_configuration_uses_verified_image_and_exact_public_checkout(configuration):
    """The supplied template carries resources and public inputs, with host sharing disabled."""
    renderer, image, digest = configuration
    config = renderer.render("fixture/workstation", REVISION, image, 4, 8)
    assert config["images"] == [{"location": str(image), "arch": "x86_64", "digest": f"sha256:{digest}"}]
    assert config["base"] == str(renderer.root / "e2e-tests/lima-ubuntu.yml")
    assert config["param"] == {
        "repository": "fixture/workstation",
        "revision": REVISION,
    }
    assert (config["cpus"], config["memory"], config["plain"]) == (4, "8GiB", True)


@pytest.mark.parametrize(
    "repository,revision,cpus,memory",
    [
        ("https://user:token@example.invalid/repo", REVISION, 4, 8),
        ("fixture/repo", "main", 4, 8),
        ("fixture/repo", REVISION, 0, 8),
        ("fixture/repo", REVISION, 4, 0),
    ],
)
def test_vm_configuration_rejects_unsafe_or_incomplete_inputs(configuration, repository, revision, cpus, memory):
    """Reject credentials, mutable references, and invalid resource settings before creation."""
    renderer, image, _ = configuration
    with pytest.raises(ValueError):
        renderer.render(repository, revision, image, cpus, memory)


def test_vm_configuration_rejects_modified_image(configuration):
    """A damaged cache cannot become a VM input even when a manifest exists."""
    renderer, image, _ = configuration
    image.write_bytes(b"truncated image")
    with pytest.raises(ValueError, match="checksum"):
        renderer.render("fixture/repo", REVISION, image, 4, 8)


@pytest.fixture(name="source_provision")
def source_provision_fixture(tmp_path):
    """Run the maintained guest bootstrap against a local public archive, without network or sudo."""
    source = tmp_path / "source.sh"
    source.write_text("#!/bin/sh\nexit 0\n")
    source.chmod(0o755)
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(source, arcname="checkout/workstation.sh")
    commands = tmp_path / "bin"
    commands.mkdir()
    curl = commands / "curl"
    curl.write_text(
        '#!/bin/bash\nset -eu\n[[ "$TEST_DOWNLOAD_STATUS" == 0 ]] || exit "$TEST_DOWNLOAD_STATUS"\n'
        'printf "%s\\n" "$@" >"$TEST_DOWNLOAD_ARGS"\ncp "$TEST_ARCHIVE" "${@: -1}"\n'
    )
    curl.chmod(0o755)
    config = DataLoader().load_from_file(str(WORKSPACE / "e2e-tests/lima-ubuntu.yml"))
    script = next(item["script"] for item in config["provision"] if "codeload.github.com" in item["script"])
    guest = tmp_path / "guest-workspace"

    def run(repository="fixture/workstation", revision=REVISION, download_status=0):
        rendered = script.replace("/workspace", str(guest))
        rendered = rendered.replace("{{.Param.repository}}", repository).replace("{{.Param.revision}}", revision)
        return subprocess.run(
            ["bash", "-c", rendered],
            env={
                **os.environ,
                "PATH": f"{commands}:/usr/bin:/bin",
                "TMPDIR": str(tmp_path),
                "TEST_ARCHIVE": str(archive),
                "TEST_DOWNLOAD_STATUS": str(download_status),
                "TEST_DOWNLOAD_ARGS": str(tmp_path / "download-arguments"),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    return run, guest, tmp_path


def test_public_source_survives_resume_without_download_or_revision_drift(
    source_provision,
):
    """Resuming for teardown reuses the read-only checkout and refuses another revision."""
    run, guest, fixture = source_provision
    result = run()
    assert result.returncode == 0, result.stderr
    assert (guest / "workstation.sh").read_text() == "#!/bin/sh\nexit 0\n"
    assert (guest / "workstation.sh").stat().st_mode & 0o777 == 0o555
    assert (
        f"https://codeload.github.com/fixture/workstation/tar.gz/{REVISION}"
        in (fixture / "download-arguments").read_text().splitlines()
    )
    result = run(download_status=22)
    assert result.returncode == 0, result.stderr
    assert run(revision="b" * 40).returncode != 0


def test_failed_download_leaves_no_partial_guest_workspace(source_provision):
    """A failed provisioning attempt can be retried without stale source."""
    run, guest, _ = source_provision
    assert run(download_status=22).returncode == 22
    assert not guest.exists()
    result = run()
    assert result.returncode == 0, result.stderr


def test_local_mount_mode_skips_public_source_provisioning(source_provision):
    """The local live checkout does not require a published commit or network access."""
    run, guest, _ = source_provision
    result = run(repository="", revision="", download_status=22)
    assert result.returncode == 0, result.stderr
    assert not guest.exists()
