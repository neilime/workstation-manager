"""Verify exact extension updates without resolving or upgrading to latest."""

import json

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.github_extensions import (
    GitHubExtensions,
)


@pytest.fixture(name="extensions")
def extensions_fixture(tmp_path):
    """Emulate installed binary/script extensions while recording CLI mutations."""
    state = {"installed": {"example/gh-tool": "v1.0.0"}, "calls": [], "dirty": False}

    def run(command):
        state["calls"].append(command)
        if command[1:3] == ["extension", "list"]:
            return (
                0,
                "\n".join(
                    f"gh tool\t{repo}\t{version[:8] if len(version) == 40 else version}"
                    for repo, version in state["installed"].items()
                ),
                "",
            )
        if command[1:3] == ["extension", "remove"]:
            state["installed"].pop("example/" + command[3])
        if command[1:3] == ["extension", "install"]:
            state["installed"][command[3]] = command[5]
        if command[-1] == "HEAD":
            return 0, state["installed"]["example/gh-tool"], ""
        if command[-1] == "--porcelain":
            return 0, " M user-change" if state["dirty"] else "", ""
        return 0, "", ""

    record = tmp_path / "state/pins.json"
    record.parent.mkdir()
    record.write_text(json.dumps(state["installed"]))
    return GitHubExtensions(tmp_path, record, run), state


@pytest.mark.parametrize("revision", ["v2.0.0", "a" * 40])
def test_upgrade_verifies_the_requested_pin_and_is_idempotent(extensions, revision):
    """Updates replace old pins explicitly; gh --force must not select latest instead."""
    manager, state = extensions
    assert manager.ensure({"example/gh-tool": revision})
    assert state["installed"] == {"example/gh-tool": revision}
    assert ["gh", "extension", "install", "example/gh-tool", "--pin", revision] in state["calls"]
    assert not manager.ensure({"example/gh-tool": revision})
    assert all("--force" not in command for command in state["calls"])


def test_preview_and_modified_script_checkout_preserve_the_existing_extension(extensions, tmp_path):
    """A preview may inspect but never remove; local script changes block replacement."""
    manager, state = extensions
    assert manager.ensure({"example/gh-tool": "v2.0.0"}, check_mode=True)
    assert state["installed"] == {"example/gh-tool": "v1.0.0"}
    (tmp_path / ".local/share/gh/extensions/gh-tool/.git").mkdir(parents=True)
    state["dirty"] = True
    with pytest.raises(ValueError, match="Preserve local changes"):
        manager.ensure({"example/gh-tool": "v2.0.0"})
    assert not any(command[1:3] == ["extension", "remove"] for command in state["calls"])
