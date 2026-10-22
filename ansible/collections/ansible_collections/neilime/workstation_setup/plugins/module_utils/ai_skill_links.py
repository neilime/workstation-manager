"""Expose selected skills without overwriting user-authored directories or links."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ansible_collections.neilime.workstation_setup.plugins.module_utils.ai_provider_config import (
    AiProviderConfiguration,
)


# One operation plans and applies the complete set to validate conflicts before mutation.
# pylint: disable-next=too-few-public-methods
class AiSkillLinks:
    """Own only links created by setup, leaving skill content with its source manager."""

    def reconcile(self, directory: Path, state_path: Path, skills: list[dict], check: bool = False) -> dict:
        """Validate sources and collisions before reconciling links; previews never create files."""
        if not directory.is_absolute() or any(p.is_symlink() for p in (directory, *directory.parents)):
            raise ValueError("The provider skills directory must be absolute and must not traverse symlinks")
        AiProviderConfiguration.private_path(state_path)
        previous = json.loads(state_path.read_text()) if state_path.exists() else {}
        if not isinstance(previous, dict) or any(not isinstance(v, str) for v in previous.values()):
            raise ValueError("Invalid AI skill ownership state")
        names = [skill["name"] for skill in skills]
        if any(re.fullmatch(r"[a-z][a-z0-9_-]*", name) is None for name in [*names, *previous]):
            raise ValueError("AI skill names must be safe directory identifiers")
        if len(set(names)) != len(names):
            raise ValueError("AI skill names must be unique")
        desired, deferred = self._sources(skills, check)
        operations, ownership = self._plan(directory, previous, desired, deferred)
        changed = bool(operations) or ownership != previous
        if changed and not check:
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            for path, target in operations:
                if path.is_symlink():
                    path.unlink()
                if target is not None:
                    path.symlink_to(target, target_is_directory=True)
            AiProviderConfiguration.write_private(state_path, json.dumps(ownership, indent=2) + "\n")
        return {"changed": changed, "deferred": deferred}

    @staticmethod
    def _sources(skills: list[dict], check: bool) -> tuple[dict, list]:
        """Resolve and validate source boundaries before touching provider links."""
        desired, deferred = {}, []
        for skill in skills:
            root = Path(skill["root"])
            if not root.is_absolute() or root.is_symlink():
                raise ValueError("AI skill sources require absolute, non-symlink roots")
            source = (root / skill["subdirectory"]).resolve()
            if not source.is_relative_to(root.resolve()) or not (source / "SKILL.md").resolve().is_relative_to(
                root.resolve()
            ):
                raise ValueError(f"AI skill {skill['name']} escapes its selected source")
            if not (source / "SKILL.md").is_file():
                if check:
                    deferred.append(skill["name"])
                    continue
                raise ValueError(f"AI skill {skill['name']} is missing SKILL.md; provision its declared source")
            desired[skill["name"]] = str(source)
        return desired, deferred

    @staticmethod
    def _plan(directory: Path, previous: dict, desired: dict, deferred: list) -> tuple[list, dict]:
        """Reject all collisions before returning the owned link operations."""
        operations, ownership = [], dict(previous)
        for name in previous.keys() | desired.keys():
            if name in deferred:
                continue
            path = directory / name
            existing = os.readlink(path) if path.is_symlink() else None
            if name in desired and path.exists() and path.resolve() == Path(desired[name]):
                if name in previous and existing == previous[name]:
                    ownership[name] = existing
                continue
            if (path.exists() or path.is_symlink()) and (existing is None or existing != previous.get(name)):
                raise ValueError(f"AI skill {name} conflicts with a user file; preserve or rename it before setup")
            target = desired.get(name)
            operations.append((path, target))
            if target is None:
                ownership.pop(name, None)
            else:
                ownership[name] = target
        return operations, ownership
