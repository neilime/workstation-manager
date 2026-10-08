"""Keep custom skills safe while reconciling links to reviewed remote content."""

import json

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.ai_skill_links import (
    AiSkillLinks,
)


def source(path):
    """Source."""
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("---\nname: example\ndescription: fixture\n---\nFixture skill")
    return {"name": "example", "root": str(path), "subdirectory": "."}


def test_preview_update_and_removal_touch_only_owned_links(tmp_path):
    """Preview update and removal touch only owned links."""
    first, second = source(tmp_path / "first"), source(tmp_path / "second")
    directory, state = tmp_path / "skills", tmp_path / "state"
    manager = AiSkillLinks()
    assert manager.reconcile(directory, state, [first], check=True)["changed"]
    assert not directory.exists()
    assert manager.reconcile(directory, state, [first])["changed"]
    assert not manager.reconcile(directory, state, [first])["changed"]
    assert manager.reconcile(directory, state, [second])["changed"]
    assert (directory / "example").resolve() == tmp_path / "second"
    assert manager.reconcile(directory, state, [])["changed"]
    assert not (directory / "example").exists()
    assert (tmp_path / "first/SKILL.md").exists()
    assert json.loads(state.read_text()) == {}


def test_custom_skill_directory_is_verified_without_becoming_owned(tmp_path):
    """Custom skill directory is verified without becoming owned."""
    directory, state = tmp_path / "skills", tmp_path / "state"
    skill = source(directory / "example")
    assert not AiSkillLinks().reconcile(directory, state, [skill])["changed"]
    assert not AiSkillLinks().reconcile(directory, state, [])["changed"]
    assert (directory / "example/SKILL.md").exists()


def test_conflicting_user_directory_and_escaping_source_fail_before_changes(tmp_path):
    """Conflicting user directory and escaping source fail before changes."""
    skill = source(tmp_path / "source")
    directory, state = tmp_path / "skills", tmp_path / "state"
    (directory / "example").mkdir(parents=True)
    with pytest.raises(ValueError, match="conflicts"):
        AiSkillLinks().reconcile(directory, state, [skill])
    assert not state.exists()
    skill["subdirectory"] = "../outside"
    with pytest.raises(ValueError, match="escapes"):
        AiSkillLinks().reconcile(directory, state, [skill])


def test_missing_source_is_deferred_only_in_check_mode(tmp_path):
    """Missing source is deferred only in check mode."""
    skill = {"name": "example", "root": str(tmp_path / "missing"), "subdirectory": "."}
    directory, state = tmp_path / "skills", tmp_path / "state"
    assert AiSkillLinks().reconcile(directory, state, [skill], check=True)["deferred"] == ["example"]
    assert not directory.exists()
    with pytest.raises(ValueError, match="missing SKILL.md"):
        AiSkillLinks().reconcile(directory, state, [skill])
