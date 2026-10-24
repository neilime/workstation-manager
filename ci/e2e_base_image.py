#!/usr/bin/env python3
"""Build a reusable desktop prerequisite image without booting an authenticated VM."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ("e2e-tests/base-image/install-desktop.sh", "e2e-tests/base-image/clean-image.sh")


def file_digest(path: Path) -> str:
    """Hash a potentially large image without keeping it in memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class DesktopBaseImage:
    """Identify, prepare, and verify a public prerequisite image."""

    def __init__(self, root: Path = ROOT) -> None:
        self.root = root

    def identify(self, checksums: str, today: datetime.date) -> dict[str, str]:
        """Key the recipe by upstream content and a weekly package refresh."""
        url = self.source_url()
        filename = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
        matches = re.findall(rf"^([0-9a-f]{{64}}) [ *]{re.escape(filename)}$", checksums, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError("Expected one SHA-256 for the configured Ubuntu cloud image")
        refresh = (today - datetime.timedelta(days=today.weekday())).isoformat()
        digest = hashlib.sha256(f"{url}\n{matches[0]}\n{refresh}\n".encode())
        for relative in (*RECIPES, "ci/e2e_base_image.py"):
            digest.update(relative.encode() + b"\0" + (self.root / relative).read_bytes())
        return {"source_url": url, "source_sha256": matches[0], "key": "e2e-desktop-" + digest.hexdigest()}

    def source_url(self) -> str:
        """Read the sole maintained Ubuntu image URL from the Lima template."""
        template = (self.root / "e2e-tests/lima-ubuntu.yml").read_text(encoding="utf-8")
        urls = re.findall(r'^  - location: "(https://cloud-images\.ubuntu\.com/[^"\s]+)"$', template, re.MULTILINE)
        if len(urls) != 1:
            raise ValueError("Expected one HTTPS Ubuntu cloud image in the Lima template")
        return urls[0]

    @staticmethod
    def verify(image: Path, metadata: dict[str, str]) -> str:
        """Reject mismatched or damaged cached output before Lima consumes it."""
        recorded = json.loads(image.with_suffix(".json").read_text(encoding="utf-8"))
        digest = file_digest(image)
        if recorded.get("key") != metadata["key"] or recorded.get("sha256") != digest:
            raise ValueError("Desktop base image does not match its inputs or checksum")
        return digest

    def build(self, image: Path, metadata: dict[str, str]) -> None:
        """Customize only a fresh verified cloud image, then publish atomically."""
        if os.geteuid() == 0:
            raise PermissionError("Build the desktop image as an unprivileged user; run make e2e-base without sudo")
        image.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="e2e-base-", dir=image.parent) as temporary:
            directory = Path(temporary)
            source = directory / "source.qcow2"
            with urllib.request.urlopen(metadata["source_url"], timeout=60) as response, source.open("wb") as output:
                shutil.copyfileobj(response, output)
            if file_digest(source) != metadata["source_sha256"]:
                raise ValueError("Ubuntu cloud image checksum mismatch; resolve its identity again")
            expanded = directory / "expanded.qcow2"
            environment = {**os.environ, "LIBGUESTFS_BACKEND": "direct"}
            # Use /tmp for appliance sockets, as allowed by Ubuntu's network-helper profile.
            environment.pop("XDG_RUNTIME_DIR", None)
            commands = [
                ["qemu-img", "create", "-f", "qcow2", str(expanded), "16G"],
                [
                    "virt-resize",
                    "--format",
                    "qcow2",
                    "--output-format",
                    "qcow2",
                    "--expand",
                    "/dev/sda1",
                    str(source),
                    str(expanded),
                ],
                [
                    "virt-customize",
                    "--verbose",
                    "--format",
                    "qcow2",
                    "-a",
                    str(expanded),
                    "--memsize",
                    "2048",
                    "--smp",
                    "2",
                    "--no-logfile",
                    "--upload",
                    f"{self.root / RECIPES[0]}:/tmp/workstation-e2e-install-desktop.sh",
                    "--run-command",
                    "bash /tmp/workstation-e2e-install-desktop.sh",
                    "--upload",
                    f"{self.root / RECIPES[1]}:/tmp/workstation-e2e-clean-image.sh",
                    "--run-command",
                    "bash /tmp/workstation-e2e-clean-image.sh",
                ],
            ]
            for command in commands:
                subprocess.run(command, check=True, env=environment)
            prepared = directory / "desktop.qcow2"
            subprocess.run(["qemu-img", "convert", "-O", "qcow2", "-c", str(expanded), str(prepared)], check=True)
            manifest = directory / "desktop.json"
            manifest.write_text(
                json.dumps({"key": metadata["key"], "sha256": file_digest(prepared)}) + "\n", encoding="utf-8"
            )
            prepared.replace(image)
            manifest.replace(image.with_suffix(".json"))


def main() -> None:
    """Resolve the cache key or build/verify its image using one manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("identify", "build", "verify"))
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--image", type=Path, default=Path(".cache/e2e-base/desktop.qcow2"))
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    base = DesktopBaseImage()
    if args.action == "identify":
        url = urllib.parse.urljoin(base.source_url(), "SHA256SUMS")
        with urllib.request.urlopen(url, timeout=30) as response:
            checksums = response.read().decode("utf-8")
        metadata = base.identify(checksums, datetime.datetime.now(datetime.UTC).date())
        args.metadata.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"key={metadata['key']}\n")
                output.write(f"source-digest={metadata['source_sha256']}\n")
    else:
        metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
        if args.action == "build":
            base.build(args.image, metadata)
        digest = base.verify(args.image, metadata)
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"digest=sha256:{digest}\n")


if __name__ == "__main__":
    main()
