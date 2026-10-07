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
        "desktop": {"clipboard_indicator": {"version": "123", "sha256": "a" * 64}},
        "development": {
            "github": {"account": "fixture"},
            "node": {"version": "1.2.3"},
            "mise": {
                "version": "1.2.3",
                "tools": {"vfox:jdx/vfox-php": "1.2.3", "github:composer/composer": "1.2.3"},
            },
            "orca": {"version": "1.2.3"},
            "npm_packages": {
                "@openai/codex": {"version": "1.2.3", "command": "codex"},
                "@github/copilot": {"version": "1.2.3", "command": "copilot"},
            },
        },
        "home_environment": {"chezmoi": {"version": "1.2.3"}},
    }

    def merge(config: dict[str, Any]) -> dict[str, Any]:
        return merge_hash(versions, config)

    return merge
