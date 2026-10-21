"""Configuration fixtures for desired-state normalization tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from ansible.utils.vars import merge_hash


@pytest.fixture
def with_tool_versions() -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Supply synthetic required configuration without tracking production pins."""

    versions = {
        "secrets": {
            "bitwarden": {
                "server": "https://vault.example.test",
                "context7-api-key": "22222222-2222-2222-2222-222222222222",
            }
        },
        "desktop": {
            "clipboard_indicator": {"version": "123", "sha256": "a" * 64},
            "system_monitor": {"version": "456", "sha256": "b" * 64},
        },
        "development": {
            "docker": {"credential_helper_version": "1.2.3"},
            "github": {"account": "fixture"},
            "node": {"version": "1.2.3"},
            "mise": {
                "version": "1.2.3",
                "tools": {"vfox:jdx/vfox-php": "1.2.3", "github:composer/composer": "1.2.3"},
            },
            "ai_tools": {
                "orca": {"version": "1.2.3"},
                "providers": {
                    "codex": {"npm": "@openai/codex", "version": "1.2.3", "command": "codex"},
                    "copilot": {"npm": "@github/copilot", "version": "1.2.3", "command": "copilot"},
                },
            },
        },
        "home_environment": {"chezmoi": {"version": "1.2.3"}},
    }

    def merge(config: dict[str, Any]) -> dict[str, Any]:
        return merge_hash(versions, config)

    return merge
