"""Validate AI application and extension declarations without inspecting the host or vault."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from ansible_collections.neilime.workstation_setup.plugins.module_utils.desired_state_support import (
    DesiredStateValueResolver,
)


# Match the other desired-state normalizers' single normalization entrypoint.
# pylint: disable-next=too-few-public-methods
class AiToolsNormalizer:
    """Normalize AI applications, provider installations, skills and local MCP launches."""

    def __init__(self) -> None:
        self._values = DesiredStateValueResolver()

    def normalize(self, development: dict, *, bitwarden: dict | None = None) -> dict:
        """Return public metadata only; secrets are resolved by setup after provisioning."""
        config = self._values.mapping(
            development.get("ai_tools"),
            "development.ai_tools",
            allowed_keys={"authenticate", "orca", "providers", "skills", "mcp_servers"},
        )
        providers = self._providers(config)
        skills = [self._skill(value) for value in self._entries(config, "skills")]
        if any(skill["kind"] == "remote" for skill in skills):
            mise = self._values.mapping(development.get("mise"), "development.mise")
            tools = self._values.mapping(mise.get("tools"), "development.mise.tools")
            self._values.release_version(
                tools.get("github:runkids/skillshare"), "development.mise.tools.github:runkids/skillshare"
            )
        servers = [self._server(value, bitwarden or {}) for value in self._entries(config, "mcp_servers")]
        return {
            "authenticate": self._values.bool_value(config.get("authenticate"), True),
            "orca": self._orca(config),
            "providers": providers,
            "skills": skills,
            "mcp_servers": servers,
        }

    def _orca(self, config: dict[str, object]) -> dict[str, object]:
        """Require the configured release for the managed Orca installation."""
        orca = self._values.mapping(config.get("orca"), "development.ai_tools.orca")
        return {
            "version": self._values.release_version(orca.get("version"), "development.ai_tools.orca.version"),
            "settings": self._values.mapping(orca.get("settings"), "development.ai_tools.orca.settings"),
        }

    def _providers(self, config: dict[str, object]) -> dict[str, object]:
        """Use one declaration for each provider's CLI installation and adapter."""
        providers = self._values.mapping(config.get("providers"), "development.ai_tools.providers")
        for name, value in providers.items():
            self._name(name, "provider", r"[a-z][a-z0-9_]*")
            label = f"development.ai_tools.providers.{name}"
            provider = self._values.mapping(value, label, allowed_keys={"npm", "version", "command"})
            self._name(provider.get("npm"), "provider npm package", r"(?:@[a-z0-9_.-]+/)?[a-z0-9_][a-z0-9_.-]*")
            self._values.release_version(provider.get("version"), f"{label}.version")
            self._name(provider.get("command"), "provider command", r"[a-zA-Z0-9][\w-]*")
            providers[name] = provider
        return providers

    def _entries(self, config: dict, key: str) -> list[dict]:
        entries = self._values.list_value(config.get(key), f"ai_tools.{key}")
        names = set()
        mappings = []
        for value in entries:
            value = self._values.mapping(value, f"ai_tools.{key} entry")
            name = self._name(value.get("name"), key)
            if name in names:
                raise ValueError(f"ai_tools.{key} contains duplicate names")
            names.add(name)
            mappings.append(value)
        return mappings

    @staticmethod
    def _name(value: object, label: str, pattern: str = r"[a-z][a-z0-9_-]*") -> str:
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            raise ValueError(f"Invalid AI {label}: expected an identifier matching {pattern}")
        return value

    @staticmethod
    def _relative(value: object, label: str) -> str:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError(f"{label} must be a nonempty relative path")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{label} must stay within its source directory")
        return str(path)

    def _skill(self, value: dict) -> dict:
        skill = self._values.mapping(value, "AI skill", allowed_keys={"name", "source"})
        source = skill.get("source")
        if not isinstance(source, str) or not source or "\x00" in source:
            raise ValueError("AI skill source must be a local ~/ path or a pinned GitHub skill URL")
        if source.startswith("~/"):
            skill["kind"] = "local"
            skill["path"] = self._relative(source[2:], "AI skill source")
            return skill
        match = re.fullmatch(
            r"(?:https://github\.com/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/tree/"
            r"[0-9a-f]{40}/(?P<path>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)",
            source,
        )
        if match is None:
            raise ValueError("AI remote skill source must be owner/repo/tree/<full-commit-sha>/<skill-path>")
        self._relative(match["path"], "AI skill source")
        skill["kind"] = "remote"
        return skill

    def _server(self, value: dict, bitwarden: dict) -> dict:
        server = self._values.mapping(
            value,
            "AI MCP server",
            allowed_keys={"name", "command", "args", "env", "npm", "version", "binary", "playwright", "auth_check"},
        )
        args = []
        for arg in self._values.list_value(server.get("args"), "AI MCP args"):
            if not isinstance(arg, str) or "\x00" in arg:
                raise ValueError("AI MCP args must contain strings without NUL bytes")
            args.append(arg)
        server["args"] = args
        server["env"] = self._environment(server.get("env"), bitwarden)
        npm = self._server_npm(server)
        server["npm"] = npm
        browser = self._values.mapping(server.get("playwright"), "AI MCP playwright", allowed_keys={"browser"})
        if browser:
            if npm.get("package") != "@playwright/mcp" or browser.get("browser") not in (
                "chromium",
                "firefox",
                "webkit",
            ):
                raise ValueError("AI Playwright provisioning requires @playwright/mcp and a bundled browser")
            if any(
                arg in {"--browser", "--executable-path", "--config", "--cdp-endpoint", "--extension"}
                or arg.startswith(("--browser=", "--executable-path=", "--config=", "--cdp-endpoint="))
                for arg in args
            ):
                raise ValueError("Configure the managed browser only through the MCP playwright.browser field")
        server["playwright"] = browser
        server["auth_check"] = self._auth_check(server.get("auth_check"))
        return server

    def _auth_check(self, value: object) -> dict:
        """Validate an explicitly selected read-only service check without running it."""
        check = self._values.mapping(value, "AI MCP auth_check", allowed_keys={"tool", "arguments", "expect_text"})
        if not check:
            return {}
        check["tool"] = self._name(check.get("tool"), "authentication check tool", r"[A-Za-z0-9_][A-Za-z0-9_.:-]*")
        check["arguments"] = self._values.mapping(check.get("arguments"), "AI MCP auth_check arguments")
        expected = check.get("expect_text", "")
        if not isinstance(expected, str) or "\x00" in expected:
            raise ValueError("AI MCP auth_check expect_text must be a string without NUL bytes")
        check["expect_text"] = expected
        return check

    def _server_npm(self, server: dict) -> dict:
        """Resolve inline npm installation details or validate an existing executable."""
        if server.get("npm") is not None:
            if "command" in server:
                raise ValueError("AI MCP servers select either npm provisioning or an absolute command")
            return {
                "package": self._name(server["npm"], "MCP npm package", r"(?:@[a-z0-9_.-]+/)?[a-z0-9_][a-z0-9_.-]*"),
                "version": self._values.release_version(server.pop("version", None), "AI MCP npm version"),
                "binary": self._name(server.pop("binary", None), "MCP npm binary", r"[a-zA-Z0-9][\w-]*"),
            }
        if "version" in server or "binary" in server:
            raise ValueError("AI MCP version and binary require an npm package")
        command = server.get("command")
        if not isinstance(command, str) or not command.startswith("/") or "\x00" in command:
            raise ValueError("AI MCP servers require npm provisioning or an absolute installed command")
        return {}

    def _environment(self, value: object, bitwarden: dict) -> dict[str, str | dict[str, object]]:
        environment: dict[str, str | dict[str, object]] = {}
        for key, entry in self._values.mapping(value, "AI MCP env").items():
            self._name(key, "environment variable", r"[a-zA-Z_][a-zA-Z0-9_]*")
            if isinstance(entry, str) and "\x00" not in entry:
                environment[key] = entry
                continue
            reference = self._values.mapping(
                entry,
                "AI MCP credential",
                allowed_keys={"bitwarden_item_id", "bitwarden_secret", "bitwarden_collection_id", "field"},
            )
            field_name = reference.get("field", "login.password")
            if field_name not in ("login.password", "login.username", "notes") and not (
                isinstance(field_name, str) and re.fullmatch(r"fields\.[\w-]+", field_name)
            ):
                raise ValueError("AI credential field must be notes, login.password, login.username or fields.NAME")
            reference["field"] = field_name
            if "bitwarden_collection_id" in reference:
                self._name(
                    reference["bitwarden_collection_id"],
                    "Bitwarden UUID",
                    r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
                )
            identifier = self._credential_item_id(reference, bitwarden)
            reference.pop("bitwarden_secret", None)
            reference["bitwarden_item_id"] = identifier
            environment[key] = reference
        return environment

    @classmethod
    def _credential_item_id(cls, reference: dict, bitwarden: dict) -> str:
        """Resolve a declared credential to a required vault item UUID."""
        selectors = reference.keys() & {"bitwarden_item_id", "bitwarden_secret"}
        if len(selectors) != 1:
            raise ValueError("AI credentials require exactly one bitwarden_item_id or bitwarden_secret")
        if "bitwarden_item_id" in selectors:
            identifier = reference["bitwarden_item_id"]
        else:
            name = reference["bitwarden_secret"]
            if not isinstance(name, str) or name not in bitwarden:
                raise ValueError("AI credential bitwarden_secret must name an entry in secrets.bitwarden")
            identifier = bitwarden[name]
        return cls._name(identifier, "Bitwarden UUID", r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
