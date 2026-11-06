"""Supply Renovate with GNOME extension releases and their archive checksums."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile


class GnomeExtensionReleases:
    """Resolve official archives before allowing Renovate to propose their pins."""

    EXTENSIONS: ClassVar[dict[str, str]] = {
        "gnome-clipboard": "clipboard-indicator@tudmotu.com",
        "gnome-vitals": "Vitals@CoreCoding.com",
    }
    REGISTRY = "https://extensions.gnome.org"

    @staticmethod
    def _download(url: str) -> bytes:
        with urlopen(url, timeout=30) as response:
            return response.read()

    def datasource(self, uuid: str) -> dict:
        """Bind the newest numeric release to the bytes actually served by GNOME."""
        registry_url = f"{self.REGISTRY}/extension-info/?uuid={quote(uuid)}"
        info = json.loads(self._download(registry_url))
        if not isinstance(info, dict) or info.get("uuid") != uuid:
            raise ValueError(f"Unexpected GNOME extension identity for {uuid}")
        shell_versions = info.get("shell_version_map")
        if not isinstance(shell_versions, dict) or not shell_versions:
            raise ValueError(f"Missing GNOME extension releases for {uuid}")
        versions: list[int] = []
        for entry in shell_versions.values():
            candidate = entry.get("version") if isinstance(entry, dict) else None
            if not isinstance(candidate, int) or isinstance(candidate, bool) or candidate < 1:
                raise ValueError(f"Invalid GNOME extension release version for {uuid}")
            versions.append(candidate)
        version = max(versions)
        archive_url = f"{self.REGISTRY}/extension-data/{uuid.replace('@', '')}.v{version}.shell-extension.zip"
        archive = self._download(archive_url)
        with ZipFile(io.BytesIO(archive)) as extension:
            if extension.namelist().count("metadata.json") != 1:
                raise ValueError(f"Expected one archive metadata.json for {uuid}")
            metadata = json.loads(extension.read("metadata.json"))
        if (
            not isinstance(metadata, dict)
            or metadata.get("uuid") != uuid
            or not isinstance(metadata.get("version"), int)
            or isinstance(metadata.get("version"), bool)
            or metadata["version"] != version
        ):
            raise ValueError(f"Archive identity or version differs from GNOME release {uuid} v{version}")
        release = {"version": str(version), "digest": hashlib.sha256(archive).hexdigest()}
        return {
            "defaultRegistryUrlTemplate": registry_url,
            "format": "json",
            # A JSON literal is a JSONata expression. Freeze the verified release so a
            # later API response cannot pair a newly published version with this hash.
            "transformTemplates": [json.dumps({"releases": [release]})],
        }

    def write_environment(self, destination: Path) -> None:
        """Publish the complete datasource configuration only after both checks pass."""
        datasources = {name: self.datasource(uuid) for name, uuid in self.EXTENSIONS.items()}
        with destination.open("a", encoding="utf-8") as environment:
            environment.write(f"RENOVATE_CUSTOM_DATASOURCES={json.dumps(datasources)}\n")


def main() -> None:
    """Prepare the next GitHub Actions step, failing before Renovate on bad input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-env", required=True, type=Path)
    args = parser.parse_args()
    try:
        GnomeExtensionReleases().write_environment(args.github_env)
    except (OSError, ValueError, BadZipFile) as error:
        raise SystemExit(f"Cannot prepare GNOME extension updates: {error}") from error


if __name__ == "__main__":
    main()
