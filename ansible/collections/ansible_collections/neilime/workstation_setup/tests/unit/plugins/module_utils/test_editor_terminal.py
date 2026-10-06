"""Protect existing VS Code JSONC settings while configuring the host terminal."""

from __future__ import annotations

import json

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.editor_terminal import (
    EditorTerminalSettings,
)


def test_new_settings_select_the_host_zsh_profile() -> None:
    """The profile must execute the host's installed Zsh through the Flatpak bridge."""

    settings = json.loads(EditorTerminalSettings().configure("{}\n"))
    assert settings["terminal.integrated.defaultProfile.linux"] == "zsh (host)"
    assert settings["terminal.integrated.profiles.linux"]["zsh (host)"] == {
        "path": "/app/bin/host-spawn",
        "args": ["/usr/bin/zsh", "-l"],
        "overrideName": True,
    }
    assert settings["settingsSync.ignoredSettings"] == [
        "terminal.integrated.profiles.linux",
        "terminal.integrated.defaultProfile.linux",
    ]


def test_sync_exclusions_preserve_personal_choices_and_remove_terminal_opt_ins() -> None:
    """Host-specific terminal settings must stay local even after explicitly opting into sync."""

    existing = json.dumps(
        {
            "settingsSync.ignoredSettings": [
                "editor.fontSize",
                "-window.zoomLevel",
                "-terminal.integrated.profiles.linux",
                "terminal.integrated.defaultProfile.linux",
                "-terminal.integrated.defaultProfile.linux",
            ],
            "settingsSync.ignoredExtensions": ["fixture.personal"],
        }
    )
    result = EditorTerminalSettings().configure(existing)
    settings = json.loads(result)
    assert settings["settingsSync.ignoredSettings"] == [
        "editor.fontSize",
        "-window.zoomLevel",
        "terminal.integrated.defaultProfile.linux",
        "terminal.integrated.profiles.linux",
    ]
    assert settings["settingsSync.ignoredExtensions"] == ["fixture.personal"]
    assert EditorTerminalSettings().configure(result) == result


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
    assert '"/app/bin/host-spawn"' in result
    assert EditorTerminalSettings().configure(result) == result


def test_existing_managed_profile_is_repaired_without_changing_other_profiles() -> None:
    """A restored profile pointing at the sandbox's missing Zsh must use the host bridge."""

    existing = json.dumps(
        {
            "terminal.integrated.defaultProfile.linux": "zsh (host)",
            "terminal.integrated.profiles.linux": {
                "zsh (host)": {"path": "/usr/bin/zsh"},
                "personal": {"path": "/bin/bash"},
            },
        }
    )
    result = json.loads(EditorTerminalSettings().configure(existing))
    assert result["terminal.integrated.profiles.linux"]["zsh (host)"]["path"] == "/app/bin/host-spawn"
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
        '{"settingsSync.ignoredSettings": "synthetic-private-marker"}',
        '{"settingsSync.ignoredSettings": ["synthetic-private-marker", 42]}',
        '{"settingsSync.ignoredSettings": null}',
    ],
)
def test_invalid_settings_fail_without_exposing_their_contents(content: str) -> None:
    """Malformed or incompatible settings must not be discarded to configure the terminal."""

    with pytest.raises(ValueError) as failure:
        EditorTerminalSettings().configure(content)
    assert content not in str(failure.value)
