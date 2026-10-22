"""Edit individual JSONC properties while preserving unrelated text and comments."""

from __future__ import annotations

import json
import re
from typing import Any

_JSONC_TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')
_TRAILING_COMMAS = re.compile(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])')


class JsoncDocument:
    """Read and modify JSON objects without reformatting neighboring properties."""

    def prepare(self, content: str) -> str:
        """Supply an object after an empty or comments-only document."""
        if not self._without_comments(content).strip():
            content += ("" if content.endswith("\n") else "\n") + "{}\n"
        return content

    def loads(self, content: str) -> dict:
        """Validate JSONC without returning source text in errors."""
        return json.loads(self._parse(self.prepare(content)))

    def set(self, content: str, keys: tuple[str, ...], value: Any) -> str:
        """Update one property without altering sibling text."""
        return self._set(self.prepare(content), keys, value)

    def remove(self, content: str, keys: tuple[str, ...]) -> str:
        """Remove one property and its separator, preserving sibling comments."""
        masked = self._parse(content)
        start = self._skip_space(masked, 0)
        for key in keys[:-1]:
            properties, _closing = self._properties(masked, start)
            if key not in properties:
                return content
            start = properties[key][0]
        previous_end = None
        for key, key_start, value_end, next_position in self._members(masked, start):
            if key == keys[-1]:
                if masked[next_position] == ",":
                    return content[:key_start] + content[next_position + 1 :]
                # A trailing comma is masked during parsing but must also be removed.
                tail = self._without_comments(content)[value_end:next_position]
                removal_end = value_end + tail.index(",") + 1 if "," in tail else value_end
                if previous_end is not None:
                    separator = masked.index(",", previous_end, key_start)
                    return content[:separator] + content[separator + 1 : key_start] + content[removal_end:]
                return content[:key_start] + content[removal_end:]
            previous_end = value_end
        return content

    def append_keybindings(self, content: str, bindings: list[dict[str, str]]) -> str:
        """Append effective shortcut overrides while preserving existing JSONC array text."""
        if not self._without_comments(content).strip():
            content += ("" if content.endswith("\n") else "\n") + "[]\n"
        masked = self._parse(content, container_type=list)
        existing = json.loads(masked)
        if any(not isinstance(item, dict) for item in existing):
            raise ValueError("VS Code keybindings must be a JSONC array of objects.")
        if any(not isinstance(item.get("key", ""), str) for item in existing):
            raise ValueError("VS Code keybinding keys must be strings.")
        keys = {binding["key"] for binding in bindings}
        relevant = [item for item in existing if item.get("key", "").lower() in keys]
        if relevant[-len(bindings) :] == bindings:
            return content
        return self._append_array_items(content, masked, bindings, len(existing))

    def _append_array_items(self, content: str, masked: str, items: list[dict], count: int) -> str:
        """Insert after existing array entries without moving their comments or separators."""
        closing = masked.rfind("]")
        if count:
            # Find the last value's end so a separator never lands inside a comment.
            position = self._skip_space(masked, self._skip_space(masked, 0) + 1)
            for _item in range(count):
                _value, value_end = json.JSONDecoder().raw_decode(masked, position)
                position = self._skip_space(masked, value_end)
                if masked[position] == ",":
                    position = self._skip_space(masked, position + 1)
            if "," not in self._without_comments(content)[value_end:closing]:
                content = content[:value_end] + "," + content[value_end:]
                closing += 1
        newline = "\r\n" if "\r\n" in content else "\n"
        additions = json.dumps(items, ensure_ascii=False, indent=2)[2:-2].replace("\n", newline)
        return content[:closing] + newline + additions + newline + content[closing:]

    def _members(self, masked: str, start: int):
        """Locate keys, values and separators in a validated object."""
        decoder = json.JSONDecoder()
        position = self._skip_space(masked, start + 1)
        while masked[position] != "}":
            key, end = decoder.raw_decode(masked, position)
            value_start = self._skip_space(masked, self._skip_space(masked, end) + 1)
            _value, value_end = decoder.raw_decode(masked, value_start)
            next_position = self._skip_space(masked, value_end)
            yield key, position, value_end, next_position
            position = self._skip_space(masked, next_position + 1) if masked[next_position] == "," else next_position

    @staticmethod
    def _without_comments(content: str) -> str:
        """Mask comments with whitespace so parsed value offsets retain their original positions."""

        def mask(match: re.Match[str]) -> str:
            token = match.group()
            return token if token.startswith('"') else re.sub(r"[^\r\n]", " ", token)

        masked = _JSONC_TOKENS.sub(mask, content)
        return " " + masked[1:] if masked.startswith("\ufeff") else masked

    def _parse(self, content: str, container_type: type = dict) -> str:
        """Validate settings privately and return a same-length JSON representation."""

        masked = _TRAILING_COMMAS.sub(
            lambda match: match.group() if match.group().startswith('"') else " ",
            self._without_comments(content),
        )
        try:
            settings = json.loads(masked, object_pairs_hook=self._unique_properties)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Configuration contains invalid JSONC at line {error.lineno}, column {error.colno}."
            ) from error
        if not isinstance(settings, container_type):
            expected = "array" if container_type is list else "object"
            raise ValueError(  # noqa: TRY004 - Schema validation reports ValueError.
                f"Configuration must be a JSONC {expected}."
            )
        return masked

    @staticmethod
    def _unique_properties(pairs: list[tuple[str, Any]]) -> dict:
        """Reject ambiguous ownership without including property names or values in errors."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Configuration contains duplicate JSONC properties.")
            result[key] = value
        return result

    @staticmethod
    def _skip_space(content: str, position: int) -> int:
        """Advance within an already validated object."""

        while content[position].isspace():
            position += 1
        return position

    def _properties(self, masked: str, start: int) -> tuple[dict[str, tuple[int, int]], int]:
        """Locate an object's property values and closing brace in the original text."""

        if masked[start] != "{":
            raise ValueError("Configuration properties must be a JSONC object.")
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
        parent_indent = content[content.rfind("\n", 0, start) + 1 :]
        parent_indent = parent_indent[: len(parent_indent) - len(parent_indent.lstrip(" \t"))]
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
