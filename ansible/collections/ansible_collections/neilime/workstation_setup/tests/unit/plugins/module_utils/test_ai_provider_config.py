"""Protect provider configuration through previews, updates, removals and conflicts."""

import json
import tomllib

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.ai_provider_config import (
    AiProviderConfiguration,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.jsonc_document import (
    JsoncDocument,
)


@pytest.fixture(name="servers")
def fixture_servers():
    """Servers."""
    return {"example": {"command": "/installed/server", "args": ["--stdio"], "env": {"KEY": "synthetic-secret"}}}


@pytest.mark.parametrize(
    "format_name,key,original",
    [
        (
            "json",
            "servers",
            '{/* keep personal comment */ "servers": {"personal": {"command": "/personal"},}, "other": 42}',
        ),
        (
            "toml",
            "mcp_servers",
            '# keep personal comment\nmodel = "personal"\n[mcp_servers.personal]\ncommand = "/personal"\n',
        ),
    ],
)
def test_preview_install_update_and_removal_preserve_personal_settings(tmp_path, servers, format_name, key, original):
    """Preview install update and removal preserve personal settings."""
    path, state = tmp_path / "config", tmp_path / "state"
    path.write_text(original)
    manager = AiProviderConfiguration()
    assert manager.reconcile(path, state, format_name, key, servers, check=True)
    assert path.read_text() == original
    assert not state.exists()
    assert manager.reconcile(path, state, format_name, key, servers)
    assert not manager.reconcile(path, state, format_name, key, servers)
    servers["example"]["command"] = "/updated/server"
    assert manager.reconcile(path, state, format_name, key, servers)
    loader = tomllib.loads if format_name == "toml" else JsoncDocument().loads
    content = loader(path.read_text())
    assert content[key]["personal"]["command"] == "/personal"
    assert content[key]["example"] == servers["example"]
    assert "keep personal comment" in path.read_text()
    assert "synthetic-secret" not in state.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert manager.reconcile(path, state, format_name, key, {})
    assert set(loader(path.read_text())[key]) == {"personal"}
    assert not manager.reconcile(path, state, format_name, key, {})


@pytest.mark.parametrize(
    "format_name,key,original",
    [
        ("json", "servers", '{"servers":{"example":{"command":"/personal"}}}'),
        ("toml", "mcp_servers", '[mcp_servers.example]\ncommand = "/personal"\n'),
    ],
)
def test_conflicting_user_entry_is_not_taken_over(tmp_path, servers, format_name, key, original):
    """Conflicting user entry is not taken over."""
    path, state = tmp_path / "config", tmp_path / "state"
    path.write_text(original)
    with pytest.raises(ValueError, match="conflict"):
        AiProviderConfiguration().reconcile(path, state, format_name, key, servers)
    assert path.read_text() == original
    assert not state.exists()


@pytest.mark.parametrize("format_name,key", [("json", "servers"), ("toml", "mcp_servers")])
def test_user_edits_to_owned_entries_stop_reconciliation(tmp_path, servers, format_name, key):
    """User edits to owned entries stop reconciliation."""
    path, state = tmp_path / "config", tmp_path / "state"
    manager = AiProviderConfiguration()
    manager.reconcile(path, state, format_name, key, servers)
    path.write_text(path.read_text().replace("/installed/server", "/personal/change"))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="conflict"):
        manager.reconcile(path, state, format_name, key, {})
    assert path.read_bytes() == before


def test_private_config_refuses_symlinks_and_invalid_json_without_overwrite(tmp_path, servers):
    """Private config refuses symlinks and invalid json without overwrite."""
    path, state, target = tmp_path / "config", tmp_path / "state", tmp_path / "dotfile-source"
    target.write_text("{}")
    path.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        AiProviderConfiguration().reconcile(path, state, "json", "servers", servers)
    assert target.read_text() == "{}"
    path.unlink()
    path.write_text('{"synthetic-secret":')
    with pytest.raises(ValueError) as error:
        AiProviderConfiguration().reconcile(path, state, "json", "servers", servers)
    assert "synthetic-secret" not in str(error.value)


def test_identical_personal_entry_is_not_silently_adopted(tmp_path, servers):
    """Matching content does not grant setup ownership of a personal entry."""
    path, state = tmp_path / "config", tmp_path / "state"
    original = json.dumps({"servers": servers})
    path.write_text(original)
    with pytest.raises(ValueError, match="conflict"):
        AiProviderConfiguration().reconcile(path, state, "json", "servers", servers)
    assert path.read_text() == original
    assert not state.exists()


@pytest.mark.parametrize(
    "personal",
    [
        '[projects."/home/test/projects/example"]\ntrust_level = "trusted"\n',
        '[profiles.personal]\nmodel = "personal-model"\n',
        '[mcp_servers.personal]\ncommand = "/personal"\n',
    ],
)
def test_toml_user_tables_inside_managed_block_are_never_deleted(tmp_path, servers, personal):
    """Client-inserted personal tables must stop a destructive MCP update or removal."""
    path, state = tmp_path / "config", tmp_path / "state"
    manager = AiProviderConfiguration()
    manager.reconcile(path, state, "toml", "mcp_servers", servers)
    path.write_text(path.read_text().replace(manager.END, personal + manager.END))
    before, ownership = path.read_bytes(), state.read_bytes()

    for desired, check in [(servers, True), (servers, False), ({}, False)]:
        with pytest.raises(ValueError, match="user entries"):
            manager.reconcile(path, state, "toml", "mcp_servers", desired, check=check)
        assert path.read_bytes() == before
        assert state.read_bytes() == ownership

    # Moving the same personal table outside the marker permits safe reconciliation.
    path.write_text(path.read_text().replace(personal + manager.END, manager.END + personal))
    manager.reconcile(path, state, "toml", "mcp_servers", {})
    assert personal in path.read_text()


def test_duplicate_jsonc_properties_are_rejected_without_exposing_values():
    """Ambiguous properties must not bypass ownership or leak source data."""
    with pytest.raises(ValueError, match="duplicate") as error:
        JsoncDocument().loads('{"servers":{},"servers":{"token":"synthetic-secret"}}')
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("content", ['{"a":1,"b":2,"c":3}', '{/*before*/ "a":1,/*keep*/ "b":2, "c":3,}', '{"a":1,}'])
def test_jsonc_removal_preserves_valid_separators_and_unrelated_members(content):
    """Jsonc removal preserves valid separators and unrelated members."""
    editor = JsoncDocument()
    original = editor.loads(content)
    for key in original:
        result = editor.remove(content, (key,))
        assert editor.loads(result) == {name: value for name, value in original.items() if name != key}
        if "/*keep*/" in content:
            assert "/*keep*/" in result
