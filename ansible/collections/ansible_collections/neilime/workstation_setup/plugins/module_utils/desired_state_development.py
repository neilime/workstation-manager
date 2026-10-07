"""Development section normalization for the desired state schema."""

from __future__ import annotations

import re

from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    desired_state_support,
)


# pylint: disable=too-few-public-methods
class DevelopmentSectionNormalizer(desired_state_support.DesiredStateDefaultsSectionNormalizer):
    """Normalize the development section of the desired-state schema."""

    def normalize(self, config: dict[str, object], defaults: dict[str, object]) -> dict[str, object]:
        """Return the normalized development section."""

        development = self._resolver.mapping(config.get("development"), "workstation_manager.development")
        settings = self._resolver.mapping(development.get("settings"), "workstation_manager.development.settings")
        default_settings = self._resolver.mapping(
            defaults.get("settings"),
            "workstation_manager.development.defaults.settings",
        )

        return {
            **self._tools(development, defaults),
            "orca": self._orca(development),
            "npm_packages": self._npm_packages(development),
            "packages": self._packages(development, defaults),
            "editor_packages": self._packages(development, defaults, "editor_packages"),
            "settings": self._resolver.sysctl_settings(
                settings,
                default_settings,
                "workstation_manager.development.settings",
            ),
        }

    def _tools(self, development: dict[str, object], defaults: dict[str, object]) -> dict[str, object]:
        """Validate native runtime versions and the remaining user-tool ownership."""
        mise = self._resolver.mapping(
            development.get("mise"), "workstation_manager.development.mise", allowed_keys={"version", "tools"}
        )
        default_mise = self._resolver.mapping(defaults.get("mise"), "workstation_manager.development.defaults.mise")
        node = self._resolver.mapping(development.get("node"), "workstation_manager.development.node")
        github = self._resolver.mapping(development.get("github"), "workstation_manager.development.github")
        default_github = self._resolver.mapping(
            defaults.get("github"), "workstation_manager.development.defaults.github"
        )
        node_version = self._resolver.release_version(
            node.get("version"), "workstation_manager.development.node.version"
        )
        mise_version = self._resolver.release_version(
            mise.get("version"), "workstation_manager.development.mise.version"
        )
        tools = self._resolver.mapping(
            self._resolver.value_or_default(mise.get("tools"), default_mise.get("tools")),
            "workstation_manager.development.mise.tools",
        )
        reserved = {
            "node",
            "nodejs",
            "aqua:cli/cli",
            "gh",
            "aqua:docker/cli",
            "docker",
            "aqua:docker/compose",
            "aqua:docker/buildx",
        }
        if reserved.intersection(tools):
            raise ValueError(
                "Default Node, GitHub CLI, and Docker are system-owned; remove their global mise entries. "
                "Project Node overrides remain supported."
            )
        if {
            "php",
            "asdf:mise-plugins/asdf-php",
            "vfox:mise-plugins/vfox-php",
            "vfox:version-fox/vfox-php",
        }.intersection(tools):
            raise ValueError("Use only vfox:jdx/vfox-php for the managed PHP runtime")
        if "composer" in tools:
            raise ValueError("Use only github:composer/composer for managed Composer")
        for tool in ("vfox:jdx/vfox-php", "github:composer/composer"):
            self._resolver.release_version(tools.get(tool), f"development.mise.tools.{tool}")
        for tool, version in tools.items():
            self._resolver.release_version(version, f"development.mise.tools.{tool}")
        account = github.get("account")
        if not isinstance(account, str) or not account.strip():
            raise ValueError("Set development.github.account to your GitHub username in ansible/private.override.yml")
        return {
            "node": {"version": node_version},
            "github": {
                "host": self._resolver.first_non_empty_string(github.get("host"), "github.com"),
                "account": account.strip(),
                "extensions": self._extensions(github, default_github),
            },
            "mise": {"version": mise_version, "tools": tools},
        }

    def _extensions(self, github: dict[str, object], defaults: dict[str, object]) -> dict[str, str]:
        """Convert reviewed release versions or commit revisions to gh install pins."""
        extensions = self._resolver.mapping(
            self._resolver.value_or_default(github.get("extensions"), defaults.get("extensions")),
            "development.github.extensions (repository: version or commit)",
        )
        result = {}
        for repository, revision in extensions.items():
            if re.fullmatch(r"[\w.-]+/gh-[\w.-]+", repository) is None or not isinstance(revision, str):
                raise ValueError("GitHub extensions require OWNER/gh-NAME and an exact version or commit")
            if re.fullmatch(r"[0-9a-f]{40}", revision):
                result[repository] = revision
            else:
                result[repository] = "v" + self._resolver.release_version(revision, f"GitHub extension {repository}")
        return result

    def _orca(self, development: dict[str, object]) -> dict[str, object]:
        """Require the configured release for the managed Orca installation."""
        orca = self._resolver.mapping(development.get("orca"), "development.orca")
        return {
            "version": self._resolver.release_version(orca.get("version"), "development.orca.version"),
            "settings": self._resolver.mapping(orca.get("settings"), "development.orca.settings"),
        }

    def _packages(
        self, development: dict[str, object], defaults: dict[str, object], key: str = "packages"
    ) -> list[object]:
        """Validate and deduplicate the declared development APT packages."""
        packages = self._resolver.list_value(
            self._resolver.value_or_default(development.get(key), defaults.get(key)),
            f"workstation_manager.development.{key}",
        )
        if any(not isinstance(package, str) or not package.strip() for package in packages):
            raise ValueError("Development packages must be nonempty APT package names")
        return list(dict.fromkeys(packages))

    def _npm_packages(self, development: dict[str, object]) -> dict[str, object]:
        """Require a pinned npm package and an explicit executable verification command."""
        packages = self._resolver.mapping(development.get("npm_packages"), "development.npm_packages")
        missing = {"@openai/codex", "@github/copilot"} - packages.keys()
        if missing:
            raise ValueError(
                f"development.npm_packages requires standard workstation tools: {', '.join(sorted(missing))}"
            )
        for name, value in packages.items():
            package = self._resolver.mapping(value, f"development.npm_packages.{name}")
            self._resolver.release_version(package.get("version"), f"npm package {name}.version")
            command = package.get("command")
            if not isinstance(command, str) or re.fullmatch(r"[a-zA-Z0-9][\w-]*", command) is None:
                raise ValueError(f"npm package {name} requires an executable command name")
            if re.fullmatch(r"(?:@[\w.-]+/)?[\w.-]+", name) is None:
                raise ValueError(f"Invalid npm package name: {name}")
        return packages
