"""Reuse a tooling image only when its complete build inputs and base match."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys

DOCKERFILE = pathlib.Path("docker/tooling/Dockerfile")
PLATFORM = "linux/amd64"
DIGEST_PATTERN = r"sha256:[0-9a-f]{64}"


class ToolingImage:
    """Resolve immutable references using Docker's existing registry authentication."""

    def __init__(self, workspace: pathlib.Path, repository: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", repository):
            raise ValueError("A GitHub owner/repository is required")
        self.workspace = workspace
        self.image = f"ghcr.io/{repository.lower()}/tooling"

    @staticmethod
    def inspect(reference: str, *, allow_missing: bool = False) -> str:
        """Return a digest; only Docker's exact missing-manifest result is a miss."""
        result = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", reference, "--format", "{{json .Manifest}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode:
            # Authentication, throttling, networking and malformed responses must fail.
            if allow_missing and result.stderr.strip() == f"ERROR: {reference}: not found":
                return ""
            raise RuntimeError(f"Cannot inspect {reference}: {result.stderr.strip()}")
        manifest = json.loads(result.stdout)
        digest = manifest.get("digest", "") if isinstance(manifest, dict) else ""
        if not isinstance(digest, str) or not re.fullmatch(DIGEST_PATTERN, digest):
            raise ValueError(f"Registry returned no valid digest for {reference}")
        return digest

    def build_inputs(self) -> tuple[str, dict[str, str]]:
        """Hash every literal COPY input, rejecting unsupported recipes instead of guessing."""
        recipe = (self.workspace / DOCKERFILE).read_text(encoding="utf-8")
        bases = re.findall(r"^FROM (ubuntu:[0-9]{2}\.[0-9]{2})\$\{TOOLING_BASE_DIGEST\}$", recipe, re.MULTILINE)
        if len(bases) != 1 or len(re.findall(r"^\s*FROM\s", recipe, re.MULTILINE | re.IGNORECASE)) != 1:
            raise ValueError("Tooling Dockerfile must have one digest-selectable Ubuntu base")
        paths = {DOCKERFILE}
        for line in recipe.splitlines():
            if not re.match(r"^\s*(COPY|ADD)\s", line, re.IGNORECASE):
                continue
            words = shlex.split(line)
            if words[0].upper() != "COPY" or len(words) < 3:
                raise ValueError("Tooling image reuse requires literal COPY file inputs")
            for source in words[1:-1]:
                path = pathlib.Path(source)
                if source.startswith(("-", "[")) or any(character in source for character in "*?$\\"):
                    raise ValueError(f"Unsupported tooling COPY input: {source}")
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError(f"Tooling COPY input must stay in the workspace: {source}")
                paths.add(path)
        for ignore in (pathlib.Path(".dockerignore"), DOCKERFILE.with_name("Dockerfile.dockerignore")):
            if (self.workspace / ignore).exists():
                paths.add(ignore)
        inputs = {}
        for path in sorted(paths):
            source_path = self.workspace / path
            if source_path.is_symlink() or not source_path.is_file():
                raise ValueError(f"Tooling build input must be a regular file: {path}")
            inputs[str(path)] = hashlib.sha256(source_path.read_bytes()).hexdigest()
        return bases[0], inputs

    def resolve(self, today: datetime.date) -> dict[str, str]:
        """Refresh mutable package resolutions weekly and the Ubuntu base on every run."""
        base, inputs = self.build_inputs()
        base_digest = self.inspect(base)
        refresh = today.strftime("%G-W%V")
        fingerprint = hashlib.sha256(
            json.dumps(
                {"schema": 1, "files": inputs, "base": base_digest, "platform": PLATFORM, "refresh": refresh},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        tag = f"inputs-{fingerprint}"
        digest = self.inspect(f"{self.image}:{tag}", allow_missing=True)
        return {
            "tag": tag,
            "base-digest": f"@{base_digest}",
            "refresh": refresh,
            "image": f"{self.image}@{digest}" if digest else "",
        }

    def select(self, cached: str, built: str) -> dict[str, str]:
        """Preserve the CI consumers' output contract using an immutable image reference."""
        result = json.loads(built or "{}") if not cached else {}
        image = cached or (result.get("image", "") if isinstance(result, dict) else "")
        if not isinstance(image, str) or not re.fullmatch(rf"{re.escape(self.image)}@{DIGEST_PATTERN}", image):
            raise ValueError("Tooling build or cache must return this repository's immutable image digest")
        return {"built-images": json.dumps({"tooling": {"images": [image]}})}


def main() -> int:
    """Write non-sensitive action outputs without shell interpolation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("resolve", "select"))
    args = parser.parse_args()
    try:
        resolver = ToolingImage(pathlib.Path.cwd(), os.environ["GITHUB_REPOSITORY"])
        if args.action == "resolve":
            outputs = resolver.resolve(datetime.datetime.now(datetime.UTC).date())
            print("Reusing tooling image" if outputs["image"] else "Tooling build inputs require a new image")
        else:
            outputs = resolver.select(
                os.environ.get("TOOLING_CACHED_IMAGE", ""), os.environ.get("TOOLING_BUILT_IMAGE", "")
            )
        with pathlib.Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.writelines(f"{name}={value}\n" for name, value in outputs.items())
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Tooling image resolution failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
