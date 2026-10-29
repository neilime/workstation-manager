"""Prepare the workstation scenario for an isolated shared VM action."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from ci.e2e_base_image import DesktopBaseImage

ROOT = Path(__file__).resolve().parents[1]


# Rendering is the only operation; image verification belongs to DesktopBaseImage.
# pylint: disable-next=too-few-public-methods
class WorkstationVMConfig:
    """Keep CI resource settings and verified public image data in the consumer."""

    def __init__(self, root: Path = ROOT) -> None:
        self.root = root

    def render(self, repository: str, revision: str, image: Path, cpus: int, memory_gib: int) -> dict:
        """Inherit desktop provisioning and stage the exact public checkout in the guest."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository):
            raise ValueError("Expected a GitHub owner/repository without credentials")
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Expected the full checked-out commit SHA")
        if cpus < 1 or memory_gib < 1:
            raise ValueError("VM CPU and memory settings must be positive integers")
        image = image.resolve(strict=True)
        metadata = json.loads((self.root / ".cache/e2e-base-inputs.json").read_text(encoding="utf-8"))
        digest = DesktopBaseImage.verify(image, metadata)
        return {
            "base": str(self.root / "e2e-tests/lima-ubuntu.yml"),
            "images": [{"location": str(image), "arch": "x86_64", "digest": f"sha256:{digest}"}],
            "cpus": cpus,
            "memory": f"{memory_gib}GiB",
            "plain": True,
            "param": {"repository": repository, "revision": revision},
        }


def main() -> None:
    """Write a Lima configuration only after validating the scenario and cached image."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--cpus", type=int, required=True)
    parser.add_argument("--memory-gib", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = WorkstationVMConfig().render(args.repository, args.revision, args.image, args.cpus, args.memory_gib)
    args.output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
