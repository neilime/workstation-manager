#!/usr/bin/env python3
"""Export only non-secret expectations for the Goss suites inside the guest."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import init_plugin_loader
from ansible.utils.vars import merge_hash


# A probe exposes one cohesive operation, rather than a general testing API.
# pylint: disable=too-few-public-methods
class GossVariables:
    """Select public assertions from the same normalized configuration as setup."""

    def collect(self) -> dict:
        """Never serialize vault IDs, credentials, browser profiles or MCP environments."""
        workspace = Path(__file__).resolve().parents[1]
        init_plugin_loader(prefix_collections_path=[str(workspace / "ansible/collections")])
        # pylint: disable=import-outside-toplevel
        from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state import (
            DesiredStateConfigNormalizer,
        )

        loader = DataLoader()
        public = loader.load_from_file(str(workspace / "ansible/group_vars/all.yml"))["workstation_manager"]
        private = Path.home() / ".local/state/workstation-manager/e2e/private.override.yml"
        overrides = loader.load_from_file(str(private)) if private.exists() else {}
        config = DesiredStateConfigNormalizer().normalize(
            merge_hash(public, overrides or {}, list_merge="replace"),
            {"WORKSTATION_MANAGER_USER": os.environ["USER"], "WORKSTATION_MANAGER_USER_HOME": str(Path.home())},
        )
        development = config["development"]
        desktop = config["desktop"]
        return {
            "user": {key: config["user"][key] for key in ("name", "home", "projects_directory")},
            "uid": os.getuid(),
            "system": {key: config["system"][key] for key in ("locale", "timezone", "settings")},
            "ubuntu": (workspace / "ansible/ubuntu-version").read_text(encoding="utf-8").strip(),
            "ansible": (workspace / "ansible/requirements.txt").read_text(encoding="utf-8").strip().split("==")[1],
            "tools": development["mise"]["tools"],
            "node": development["node"]["version"],
            "github": {key: development["github"][key] for key in ("host", "account", "extensions")},
            "packages": sorted(
                set(
                    config["system"]["packages"]["prerequisites"]
                    + config["system"]["packages"]["apt"]
                    + development["packages"]
                    + development["editor_packages"]
                )
            ),
            "editor_packages": development["editor_packages"],
            "providers": [
                {key: provider[key] for key in ("command", "npm")}
                for provider in development["ai_tools"]["providers"].values()
            ],
            "development_sysctl": development["settings"]["sysctl"],
            "desktop": {key: desktop[key] for key in ("clipboard_indicator", "system_monitor", "flatpak", "gnome")},
        }


if __name__ == "__main__":
    print(json.dumps(GossVariables().collect()))
