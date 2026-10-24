"""Keep tooling image reuse tied to build inputs without hiding registry failures."""

from __future__ import annotations

import datetime
import importlib.util
import json
import pathlib
import subprocess
from unittest.mock import Mock

import pytest

WORKSPACE = pathlib.Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("tooling_image", WORKSPACE / "ci/tooling_image.py")
assert SPEC is not None and SPEC.loader is not None
tooling_image = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tooling_image)
BASE_DIGEST = "sha256:" + "a" * 64
IMAGE_DIGEST = "sha256:" + "b" * 64
TODAY = datetime.date(2026, 1, 7)


@pytest.fixture(name="resolver")
def tooling_resolver(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Use synthetic dependencies with the current recipe's supported COPY contract."""
    dockerfile = tmp_path / tooling_image.DOCKERFILE
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(
        "ARG TOOLING_BASE_DIGEST\n"
        "FROM ubuntu:99.01${TOOLING_BASE_DIGEST}\n"
        "ARG TOOLING_REFRESH=local\n"
        "COPY requirements.txt /requirements.txt\n"
        "COPY collections.yml /collections.yml\n"
    )
    (tmp_path / "requirements.txt").write_text("synthetic-package>=1,<2\n")
    (tmp_path / "collections.yml").write_text("collections: []\n")
    image = tooling_image.ToolingImage(tmp_path, "Fixture/Workstation")
    monkeypatch.setattr(image, "inspect", Mock(side_effect=[BASE_DIGEST, IMAGE_DIGEST]))
    return image


def test_tooling_image_reuses_immutable_digest_for_unchanged_build_inputs(resolver):
    """Application edits do not invalidate a dependency-only image or change its immutable output."""
    first = resolver.resolve(TODAY)
    (resolver.workspace / "workstation.sh").write_text("changed application\n")
    resolver.inspect.side_effect = [BASE_DIGEST, IMAGE_DIGEST]
    second = resolver.resolve(TODAY + datetime.timedelta(days=1))
    assert second == first
    assert second["image"] == f"ghcr.io/fixture/workstation/tooling@{IMAGE_DIGEST}"


@pytest.mark.parametrize(
    "path", [tooling_image.DOCKERFILE, pathlib.Path("requirements.txt"), pathlib.Path("collections.yml")]
)
def test_tooling_image_invalidates_changed_recipe_and_each_dependency(resolver, path):
    """Every copied input and the Dockerfile contribute to the registry lookup key."""
    first = resolver.resolve(TODAY)
    source = resolver.workspace / path
    source.write_text(source.read_text() + "# changed\n")
    resolver.inspect.side_effect = [BASE_DIGEST, ""]
    second = resolver.resolve(TODAY)
    assert second["tag"] != first["tag"]
    assert second["image"] == ""


@pytest.mark.parametrize("change", ["base", "week", "ignore"])
def test_tooling_image_refreshes_base_packages_and_build_context(resolver, change):
    """Base updates, weekly package refreshes and context exclusion changes cannot reuse old images."""
    first = resolver.resolve(TODAY)
    digest = "sha256:" + "c" * 64 if change == "base" else BASE_DIGEST
    today = TODAY + datetime.timedelta(days=7) if change == "week" else TODAY
    if change == "ignore":
        (resolver.workspace / ".dockerignore").write_text("ignored\n")
    resolver.inspect.side_effect = [digest, ""]
    second = resolver.resolve(today)
    assert second["tag"] != first["tag"]
    assert second["base-digest"] == f"@{digest}"
    assert (second["refresh"] != first["refresh"]) == (change == "week")


@pytest.mark.parametrize("source", ["missing.txt", "*.txt", "../outside.txt", "--from=other /file"])
def test_tooling_image_rejects_unaccounted_build_inputs(resolver, source):
    """Unresolvable dependencies fail before consulting an image that may be stale."""
    with (resolver.workspace / tooling_image.DOCKERFILE).open("a") as dockerfile:
        dockerfile.write(f"COPY {source} /destination\n")
    with pytest.raises(ValueError, match="(input|COPY)"):
        resolver.resolve(TODAY)
    resolver.inspect.assert_not_called()


def test_tooling_image_current_recipe_accounts_for_all_dependencies():
    """The maintained Docker recipe remains resolvable without duplicating its dependency list."""
    image = tooling_image.ToolingImage(WORKSPACE, "fixture/workstation")
    base, inputs = image.build_inputs()
    assert base == "ubuntu:" + (WORKSPACE / "ansible/ubuntu-version").read_text().strip()
    assert "ansible/requirements.txt" in inputs
    assert "e2e-tests/requirements.txt" in inputs


@pytest.mark.parametrize("allow_missing", [False, True])
def test_tooling_image_distinguishes_missing_optional_tag_from_missing_base(monkeypatch, allow_missing):
    """Only the optional cached image may be absent; the selected base must resolve."""
    reference = "ghcr.io/fixture/workstation/tooling:synthetic-inputs"
    result = subprocess.CompletedProcess([], 1, "", f"ERROR: {reference}: not found\n")
    monkeypatch.setattr(tooling_image.subprocess, "run", Mock(return_value=result))
    if allow_missing:
        assert tooling_image.ToolingImage.inspect(reference, allow_missing=True) == ""
    else:
        with pytest.raises(RuntimeError, match="Cannot inspect"):
            tooling_image.ToolingImage.inspect(reference)


@pytest.mark.parametrize(
    "error",
    [
        "failed to authorize: failed to fetch oauth token: 403 Forbidden",
        "unexpected status 429 Too Many Requests",
        "dial tcp: lookup ghcr.io: no such host",
        "failed to authorize: credential not found",
    ],
)
def test_tooling_image_registry_failure_does_not_trigger_build(monkeypatch, error):
    """Authentication, throttling and transport failures remain actionable failures."""
    result = subprocess.CompletedProcess([], 1, "", f"ERROR: {error}\n")
    monkeypatch.setattr(tooling_image.subprocess, "run", Mock(return_value=result))
    with pytest.raises(RuntimeError, match="Cannot inspect"):
        tooling_image.ToolingImage.inspect("ghcr.io/fixture/workstation/tooling:inputs", allow_missing=True)


@pytest.mark.parametrize("payload", [{"digest": IMAGE_DIGEST}, {}, {"digest": "latest"}])
def test_tooling_image_registry_response_requires_sha256_digest(monkeypatch, payload):
    """Successful registry commands must still identify immutable content."""
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    monkeypatch.setattr(tooling_image.subprocess, "run", Mock(return_value=result))
    if payload.get("digest") == IMAGE_DIGEST:
        assert tooling_image.ToolingImage.inspect("fixture") == IMAGE_DIGEST
    else:
        with pytest.raises(ValueError, match="valid digest"):
            tooling_image.ToolingImage.inspect("fixture")


@pytest.mark.parametrize("cached", [False, True])
def test_tooling_image_selection_preserves_consumer_contract(resolver, cached):
    """Cache hits and builds expose the same immutable image to all current-checkout test jobs."""
    image = f"{resolver.image}@{IMAGE_DIGEST}"
    outputs = resolver.select(image if cached else "", "" if cached else json.dumps({"image": image}))
    assert json.loads(outputs["built-images"])["tooling"]["images"] == [image]


@pytest.mark.parametrize(
    "image", ["", "ghcr.io/fixture/workstation/tooling:mutable", f"ghcr.io/other/tooling@{IMAGE_DIGEST}"]
)
def test_tooling_image_selection_rejects_missing_or_wrong_image(resolver, image):
    """A skipped or malformed build cannot silently hand consumers an unrelated or mutable image."""
    with pytest.raises(ValueError, match="immutable image"):
        resolver.select("", json.dumps({"image": image}))


def test_tooling_image_command_writes_consumer_output_and_fails_without_valid_build(tmp_path, monkeypatch):
    """The workflow entrypoint produces its output only after successful immutable-image selection."""
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_REPOSITORY", "fixture/workstation")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("TOOLING_CACHED_IMAGE", "")
    monkeypatch.setenv("TOOLING_BUILT_IMAGE", "[]")
    monkeypatch.setattr(tooling_image.sys, "argv", ["tooling_image.py", "select"])
    assert tooling_image.main() == 1
    assert not output.exists()
    image = f"ghcr.io/fixture/workstation/tooling@{IMAGE_DIGEST}"
    monkeypatch.setenv("TOOLING_BUILT_IMAGE", json.dumps({"image": image}))
    assert tooling_image.main() == 0
    name, value = output.read_text().strip().split("=", 1)
    assert name == "built-images"
    assert json.loads(value)["tooling"]["images"] == [image]
