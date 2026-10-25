"""Recover browser avatar attachments concurrently without persisting private image data."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_profile_paths import (
    BrowserProfilePathsPlanner,
)


class BrowserAvatarRecovery:  # pylint: disable=too-few-public-methods
    """Download at most two attachments using the managed user's synchronized CLI cache."""

    def __init__(self, session: str, appdata_dir: str, executable: str) -> None:
        if not isinstance(session, str) or not session.strip() or "\0" in session:
            raise ValueError("Browser avatar recovery requires an unlocked Bitwarden session")
        if not isinstance(appdata_dir, str) or not Path(appdata_dir).is_absolute() or "\0" in appdata_dir:
            raise ValueError("Browser avatar recovery requires an absolute Bitwarden cache directory")
        self.executable = executable
        self.environment = {
            **os.environ,
            "BITWARDENCLI_APPDATA_DIR": appdata_dir,
            "BW_SESSION": session,
            "BW_NOINTERACTION": "true",
        }

    def read(self, profiles: list[dict]) -> list[dict]:
        """Return all profiles with their recovered images only after every request succeeds."""

        if not isinstance(profiles, list):
            raise ValueError(  # noqa: TRY004 - Invalid external records use the module's validation error contract.
                "Browser avatar recovery requires a list of profile records"
            )
        requests = []
        seen = set()
        for profile in profiles:
            if not isinstance(profile, dict):
                raise ValueError(  # noqa: TRY004 - Invalid external records use the module's validation error contract.
                    "Browser avatar recovery requires profile records"
                )
            profile_id = profile.get("id")
            if (
                not isinstance(profile_id, str)
                or not BrowserProfilePathsPlanner().has_valid_profile_id(profile_id)
                or profile_id != profile_id.strip()
                or profile_id in seen
            ):
                raise ValueError("Browser avatar recovery requires unique canonical profile IDs")
            seen.add(profile_id)
            if "avatar_attachment_id" in profile:
                requests.append(self._request(profile))
        if not requests:
            return [dict(profile) for profile in profiles]

        with ThreadPoolExecutor(max_workers=2) as workers:
            images = dict(workers.map(self._download, requests))
        return [
            {**profile, "avatar_png": images[profile["id"]]} if profile["id"] in images else dict(profile)
            for profile in profiles
        ]

    @staticmethod
    def _request(profile: dict) -> tuple[str, str, str]:
        """Reject ambiguous identifiers before any subprocess or download starts."""

        item_id = profile.get("item_id")
        try:
            if not isinstance(item_id, str) or str(UUID(item_id)) != item_id:
                raise ValueError
        except ValueError:
            raise ValueError("Browser avatar recovery requires canonical Bitwarden item IDs") from None
        attachment_id = profile["avatar_attachment_id"]
        if not isinstance(attachment_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", attachment_id):
            raise ValueError("Browser avatar recovery requires safe nonempty attachment IDs")
        return profile["id"], item_id, attachment_id

    def _download(self, request: tuple[str, str, str]) -> tuple[str, str]:
        """Keep each attempt bounded and hide CLI output from all failure diagnostics."""

        profile_id, item_id, attachment_id = request
        for attempt in range(4):
            try:
                # Ansible's run_command has shared module state and no execution
                # timeout. Each worker owns a bounded subprocess and private pipes.
                # pylint: disable-next=ansible-bad-function
                result = subprocess.run(
                    [self.executable, "get", "attachment", attachment_id, "--itemid", item_id, "--raw"],
                    env=self.environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=120,
                    check=True,
                )
                return profile_id, base64.b64encode(result.stdout).decode("ascii")
            except OSError, subprocess.SubprocessError:
                if attempt < 3:
                    time.sleep(5)
        raise ValueError(
            "Browser avatar recovery failed after retrying the Bitwarden attachment download; "
            "check network access and the configured avatar attachments, then retry"
        )
