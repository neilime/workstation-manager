"""Configure a host Zsh terminal without rewriting personal VS Code JSONC settings."""

from __future__ import annotations

import json
import re
from typing import Any

_JSONC_TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')
_TRAILING_COMMAS = re.compile(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])')


# The editor exposes the single configuration operation used by its module.
# pylint: disable-next=too-few-public-methods
class EditorTerminalSettings:
    """Edit only the managed terminal profile and its default selection."""

    def configure(self, content: str) -> str:
        """Preserve comments, unrelated settings and profiles, accepting JSONC trailing commas."""

        if not self._without_comments(content).strip():
            content += ("" if content.endswith("\n") else "\n") + "{}\n"
        content = self._set(
            content,
            ("terminal.integrated.profiles.linux", "zsh (host)"),
            {"path": "/app/bin/host-spawn", "args": ["/usr/bin/zsh", "-l"], "overrideName": True},
        )
        return self._set(content, ("terminal.integrated.defaultProfile.linux",), "zsh (host)")

    @staticmethod
    def _without_comments(content: str) -> str:
        """Mask comments with whitespace so parsed value offsets retain their original positions."""

        def mask(match: re.Match[str]) -> str:
            token = match.group()
            return token if token.startswith('"') else re.sub(r"[^\r\n]", " ", token)

        masked = _JSONC_TOKENS.sub(mask, content)
        return " " + masked[1:] if masked.startswith("\ufeff") else masked

    def _parse(self, content: str) -> str:
        """Validate settings privately and return a same-length JSON representation."""

        masked = _TRAILING_COMMAS.sub(
            lambda match: match.group() if match.group().startswith('"') else " ",
            self._without_comments(content),
        )
        try:
            settings = json.loads(masked)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"VS Code settings contain invalid JSONC at line {error.lineno}, column {error.colno}."
            ) from error
        if not isinstance(settings, dict):
            raise ValueError("VS Code settings must be a JSONC object.")
        return masked

    @staticmethod
    def _skip_space(content: str, position: int) -> int:
        """Advance within an already validated object."""

        while content[position].isspace():
            position += 1
        return position

    def _properties(self, masked: str, start: int) -> tuple[dict[str, tuple[int, int]], int]:
        """Locate an object's property values and closing brace in the original text."""

        if masked[start] != "{":
            raise ValueError("VS Code terminal profiles must be a JSONC object.")
        decoder = json.JSONDecoder()
        properties: dict[str, tuple[int, int]] = {}
        position = self._skip_space(masked, start + 1)
        while masked[position] != "}":
            key, key_end = decoder.raw_decode(masked, position)
            value_start = self._skip_space(masked, self._skip_space(masked, key_end) + 1)
            _value, value_end = decoder.raw_decode(masked, value_start)
            properties[key] = (value_start, value_end)
            position = self._skip_space(masked, value_end)
            if masked[position] == ",":
                position = self._skip_space(masked, position + 1)
        return properties, position

    def _set(self, content: str, keys: tuple[str, ...], value: Any) -> str:
        """Replace one value or add its missing parent object without rewriting siblings."""

        masked = self._parse(content)
        start = self._skip_space(masked, 0)
        for depth, key in enumerate(keys[:-1]):
            properties, _closing = self._properties(masked, start)
            if key not in properties:
                for remaining in reversed(keys[depth + 1 :]):
                    value = {remaining: value}
                return self._edit(content, start, key, value)
            start = properties[key][0]
        return self._edit(content, start, keys[-1], value)

    def _edit(self, content: str, start: int, key: str, value: Any) -> str:
        """Keep all unedited text and insert separators outside existing comments."""

        masked = self._parse(content)
        properties, closing = self._properties(masked, start)
        parent_indent = re.match(r"[ \t]*", content[content.rfind("\n", 0, start) + 1 :]).group()
        child_indent = parent_indent + "  "
        newline = "\r\n" if "\r\n" in content else "\n"
        formatted = json.dumps(value, ensure_ascii=False, indent=2).replace("\n", newline + child_indent)
        if key in properties:
            bounds = properties[key]
            if json.loads(masked[bounds[0] : bounds[1]]) == value:
                return content
            return content[: bounds[0]] + formatted + content[bounds[1] :]
        if properties:
            last_value_end = max(end for _begin, end in properties.values())
            if "," not in self._without_comments(content)[last_value_end:closing]:
                content = content[:last_value_end] + "," + content[last_value_end:]
                closing += 1
        entry = newline + child_indent + json.dumps(key) + ": " + formatted + newline + parent_indent
        return content[:closing] + entry + content[closing:]
