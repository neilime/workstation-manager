"""Protect existing VS Code JSONC settings while configuring the host terminal."""

from __future__ import annotations

import json

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.editor_terminal import (
    EditorTerminalKeybindings,
    EditorTerminalSettings,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.jsonc_document import (
    JsoncDocument,
)


def test_new_settings_select_native_zsh() -> None:
    """A native terminal uses the configured host executable."""
    settings = json.loads(EditorTerminalSettings().configure("{}\n"))
    assert settings["terminal.integrated.defaultProfile.linux"] == "zsh"
    assert settings["terminal.integrated.profiles.linux"]["zsh"] == {"path": "/usr/bin/zsh", "args": ["-l"]}
    assert "settingsSync.ignoredSettings" not in settings


def test_existing_sync_exclusions_retain_jsonc_comments_when_already_configured() -> None:
    """An unchanged exclusion list must not lose its comments or trailing comma."""

    exclusions = (
        '"settingsSync.ignoredSettings": [\n'
        "    // machine-specific shells\n"
        '    "terminal.integrated.profiles.linux",\n'
        '    "terminal.integrated.defaultProfile.linux",\n'
        "  ]"
    )
    result = EditorTerminalSettings().configure("{" + exclusions + "}")
    assert exclusions in result


@pytest.mark.parametrize("trailing_comma", ["", ","])
def test_comments_other_profiles_and_unrelated_settings_are_preserved(trailing_comma: str) -> None:
    """Only the managed profile and default selection should change, including in JSONC."""

    existing = (
        '{\n  // personal editor settings\n  "editor.fontSize": 17,\n'
        '  "fixture.url": "https://example.invalid/*keep*/",\n'
        '  "fixture.text": "comma,} and quote \\"",\n'
        '  "terminal.integrated.profiles.linux": {\n'
        "    /* keep this profile comment */\n"
        '    "custom": {"path": "/bin/bash", "args": ["-l",],},\n'
        '    "disabled": null,\n'
        '  },\n  "terminal.integrated.defaultProfile.linux": "custom"'
        f"{trailing_comma}\n}}\n// trailing note\n"
    )
    result = EditorTerminalSettings().configure(existing)
    for fragment in (
        "// personal editor settings",
        '"editor.fontSize": 17',
        '"fixture.url": "https://example.invalid/*keep*/"',
        '"fixture.text": "comma,} and quote \\""',
        "/* keep this profile comment */",
        '"custom": {"path": "/bin/bash", "args": ["-l",],}',
        '"disabled": null',
        "// trailing note",
    ):
        assert fragment in result
    assert EditorTerminalSettings().configure(result) == result


@pytest.mark.parametrize("content", ["", "  \n", "// settings not configured yet\n", "{}", '{"editor.fontSize":12}'])
def test_empty_and_compact_settings_are_supported(content: str) -> None:
    """VS Code settings do not need pre-existing multiline objects or terminal profiles."""

    result = EditorTerminalSettings().configure(content)
    assert '"/usr/bin/zsh"' in result
    assert EditorTerminalSettings().configure(result) == result


def test_existing_managed_profile_is_repaired_without_changing_other_profiles() -> None:
    """The managed profile is repaired while personal profiles remain unchanged."""

    existing = json.dumps(
        {
            "terminal.integrated.defaultProfile.linux": "personal",
            "terminal.integrated.profiles.linux": {
                "zsh": {"path": "/bin/sh"},
                "personal": {"path": "/bin/bash"},
            },
        }
    )
    result = json.loads(EditorTerminalSettings().configure(existing))
    assert result["terminal.integrated.profiles.linux"]["zsh"] == {"path": "/usr/bin/zsh", "args": ["-l"]}
    assert result["terminal.integrated.profiles.linux"]["personal"] == {"path": "/bin/bash"}


def test_bom_crlf_and_unicode_settings_are_preserved() -> None:
    """Settings synchronized from another editor retain their original encoding and line endings."""

    original = '\ufeff{\r\n  // personal comment\r\n  "fixture.text": "café",\r\n}\r\n'
    result = EditorTerminalSettings().configure(original)
    assert result.startswith("\ufeff{")
    assert '// personal comment\r\n  "fixture.text": "café",\r\n' in result
    assert "\n" not in result.replace("\r\n", "")
    assert EditorTerminalSettings().configure(result) == result


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '{"broken":',
        "{/* unterminated",
        '{"terminal.integrated.profiles.linux": []}',
    ],
)
def test_invalid_settings_fail_without_exposing_their_contents(content: str) -> None:
    """Malformed or incompatible settings must not be discarded to configure the terminal."""

    with pytest.raises(ValueError) as failure:
        EditorTerminalSettings().configure(content)
    assert content not in str(failure.value)


@pytest.mark.parametrize("content", ["", "// personal shortcuts\n", "[]", "[\n]\n"])
def test_terminal_paste_shortcuts_use_the_regular_clipboard(content: str) -> None:
    """Terminal paste uses the same action as the context menu and converges once."""
    result = EditorTerminalKeybindings().configure(content)
    bindings = JsoncDocument().loads('{"bindings":' + result + "\n}")["bindings"]
    assert {binding["key"] for binding in bindings} == {"ctrl+v", "shift+insert"}
    assert all(binding["command"] == "workbench.action.terminal.paste" for binding in bindings)
    assert all(binding["when"] == "terminalFocus" for binding in bindings)
    assert EditorTerminalKeybindings().configure(result) == result


@pytest.mark.parametrize("trailing_comma", ["", ","])
def test_paste_overrides_preserve_personal_bindings_and_jsonc(trailing_comma: str) -> None:
    """Clipboard overrides follow conflicting bindings without reformatting personal entries."""
    personal = (
        '  {"key":"ctrl+k ctrl+v", "command":"personal.command", "args":{"text":"café,]"}},\r\n'
        '  {"key":"shift+insert", "command":"workbench.action.terminal.pasteSelection",'
        ' "when":"terminalFocus"}'
    )
    content = "\ufeff[\r\n  // keep this\r\n" + personal + trailing_comma + " // closing comment\r\n]\r\n"
    result = EditorTerminalKeybindings().configure(content)
    assert personal in result
    assert "// closing comment\r\n" in result
    assert result.startswith("\ufeff[\r\n")
    assert "\n" not in result.replace("\r\n", "")
    bindings = JsoncDocument().loads('{"bindings":' + result.lstrip("\ufeff") + "\n}")["bindings"]
    assert bindings[-1]["command"] == "workbench.action.terminal.paste"
    assert EditorTerminalKeybindings().configure(result) == result


@pytest.mark.parametrize(
    "content",
    ['{"private":"synthetic"}', '["synthetic"]', '[{"key":null}]', '[{"broken":', '[], "extra": "synthetic"'],
)
def test_invalid_keybindings_fail_privately(content: str) -> None:
    """Malformed shortcut documents must never be replaced or exposed in diagnostics."""
    with pytest.raises(ValueError) as failure:
        EditorTerminalKeybindings().configure(content)
    assert "synthetic" not in str(failure.value)
