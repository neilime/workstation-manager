"""Keep GNOME extension updates bound to the official archive bytes."""

import ast
import hashlib
import io
import json
import re
from pathlib import Path
from urllib.error import URLError
from zipfile import BadZipFile, ZipFile

import pytest

from ci.renovate_gnome import GnomeExtensionReleases

ROOT = Path(__file__).resolve().parents[2]


def archive_bytes(metadata):
    """Build a synthetic upstream archive without installing an extension."""
    archive = io.BytesIO()
    with ZipFile(archive, "w") as extension:
        extension.writestr("metadata.json", json.dumps(metadata))
    return archive.getvalue()


@pytest.fixture(name="upstream")
def fixture_upstream(monkeypatch):
    """Serve deterministic GNOME API and archive responses through the HTTP boundary."""
    responses = {}
    for uuid in GnomeExtensionReleases.EXTENSIONS.values():
        info_url = f"{GnomeExtensionReleases.REGISTRY}/extension-info/?uuid={uuid.replace('@', '%40')}"
        archive_url = (
            f"{GnomeExtensionReleases.REGISTRY}/extension-data/{uuid.replace('@', '')}.v10.shell-extension.zip"
        )
        responses[info_url] = json.dumps(
            {"uuid": uuid, "shell_version_map": {"47": {"version": 9}, "48": {"version": 10}, "49": {"version": 10}}}
        ).encode()
        responses[archive_url] = archive_bytes({"uuid": uuid, "version": 10})

    def download(url, *, timeout):
        assert timeout > 0
        result = responses[url]
        if isinstance(result, Exception):
            raise result
        return io.BytesIO(result)

    monkeypatch.setattr("ci.renovate_gnome.urlopen", download)
    return responses


def test_environment_contains_only_releases_with_verified_archive_digests(tmp_path, upstream):
    """Select numeric releases and hand Renovate the hash of each matching archive."""
    destination = tmp_path / "environment"
    destination.write_text("EXISTING=value\n")

    GnomeExtensionReleases().write_environment(destination)

    existing, exported = destination.read_text().splitlines()
    assert existing == "EXISTING=value"
    name, value = exported.split("=", 1)
    assert name == "RENOVATE_CUSTOM_DATASOURCES"
    datasources = json.loads(value)
    assert datasources.keys() == GnomeExtensionReleases.EXTENSIONS.keys()
    for name, uuid in GnomeExtensionReleases.EXTENSIONS.items():
        datasource = datasources[name]
        assert datasource["defaultRegistryUrlTemplate"] in upstream
        assert datasource["format"] == "json"
        archive_url = (
            f"{GnomeExtensionReleases.REGISTRY}/extension-data/{uuid.replace('@', '')}.v10.shell-extension.zip"
        )
        assert json.loads(datasource["transformTemplates"][0]) == {
            "releases": [{"version": "10", "digest": hashlib.sha256(upstream[archive_url]).hexdigest()}]
        }


@pytest.mark.parametrize(
    "invalid_info",
    [
        {"uuid": "wrong@example.com"},
        {"shell_version_map": {}},
        {"shell_version_map": {"50": {"version": "10"}}},
        {"shell_version_map": {"50": {"version": True}}},
        {"shell_version_map": {"50": {"version": 0}}},
    ],
)
def test_invalid_release_information_prevents_export(tmp_path, upstream, invalid_info):
    """Untrusted release identities and malformed versions cannot become update pins."""
    uuid = GnomeExtensionReleases.EXTENSIONS["gnome-vitals"]
    url = next(url for url in upstream if "extension-info" in url and "Vitals" in url)
    upstream[url] = json.dumps({"uuid": uuid, **invalid_info}).encode()
    destination = tmp_path / "environment"
    with pytest.raises(ValueError):
        GnomeExtensionReleases().write_environment(destination)
    assert not destination.exists()


@pytest.mark.parametrize("metadata", [{"uuid": "wrong@example.com", "version": 10}, {"version": 9}, {"version": "10"}])
def test_archive_must_match_selected_identity_and_version(tmp_path, upstream, metadata):
    """A valid ZIP for a different release cannot supply the selected release's hash."""
    uuid = GnomeExtensionReleases.EXTENSIONS["gnome-vitals"]
    url = next(url for url in upstream if "extension-data" in url and "Vitals" in url)
    upstream[url] = archive_bytes({"uuid": uuid, **metadata})
    with pytest.raises(ValueError, match="identity or version"):
        GnomeExtensionReleases().write_environment(tmp_path / "environment")


def test_download_failure_does_not_export_a_partial_configuration(tmp_path, upstream):
    """If the second archive is unavailable, leave GitHub's environment file intact."""
    url = next(url for url in upstream if "extension-data" in url and "Vitals" in url)
    upstream[url] = URLError("archive unavailable")
    destination = tmp_path / "environment"
    destination.write_text("EXISTING=value\n")
    with pytest.raises(URLError, match="archive unavailable"):
        GnomeExtensionReleases().write_environment(destination)
    assert destination.read_text() == "EXISTING=value\n"


@pytest.mark.parametrize("payload", [b"not a ZIP", b"PK\x05\x06" + b"\x00" * 18])
def test_unusable_archive_prevents_export(tmp_path, upstream, payload):
    """A broken ZIP or missing metadata cannot be published as an installable pin."""
    url = next(url for url in upstream if "extension-data" in url and "Vitals" in url)
    upstream[url] = payload
    destination = tmp_path / "environment"
    with pytest.raises((BadZipFile, ValueError)):
        GnomeExtensionReleases().write_environment(destination)
    assert not destination.exists()


def test_managers_extract_version_and_digest_from_public_configuration(public_defaults):
    """Every GNOME handler must capture its checksum before proposing an update."""
    configuration = (ROOT / ".github/renovate/renovate-config.json5").read_text()
    public_content = (ROOT / "ansible/group_vars/all.yml").read_text()
    for key in ("clipboard_indicator", "system_monitor"):
        expression = next(line.strip().rstrip(",") for line in configuration.splitlines() if f"'{key}:" in line)
        pattern = ast.literal_eval(expression).replace("(?<", "(?P<")
        pin = public_defaults["desktop"][key]
        assert re.search(pattern, public_content).groupdict() == {
            "currentValue": pin["version"],
            "currentDigest": pin["sha256"],
        }
        assert re.search(pattern, f'{key}:\n  version: "10"\n') is None
