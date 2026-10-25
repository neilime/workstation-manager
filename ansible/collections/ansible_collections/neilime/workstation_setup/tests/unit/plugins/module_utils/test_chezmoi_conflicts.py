"""Keep replacement guards while allowing native current-input transformations."""

import json

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.chezmoi_conflicts import (
    ChezmoiConflictClassifier,
)


@pytest.mark.parametrize(
    "source,modifier",
    [
        ("exact_private_dot_codex/modify_private_config.toml", True),
        ("modify_script.txt.py", True),
        ("modify_literal_modify_named", True),
        ("literal_modify_config", False),
        ("private_modify_config", False),
        ("modify_directory/dot_config", False),
        ("dot_config.tmpl", False),
    ],
)
def test_only_the_native_modify_basename_prefix_exempts_a_file(source, modifier):
    """Attributes and parent directory names cannot turn an ordinary file into a modifier."""
    candidate = "MM .codex/config.toml"
    metadata = json.dumps({".codex/config.toml": {"sourceRelative": source}})
    assert ChezmoiConflictClassifier.replacement_conflicts([candidate], metadata, [candidate[3:]]) == (
        [] if modifier else [candidate]
    )


def test_directory_descendants_and_missing_files_remain_conflicts():
    """File-only metadata cannot exempt directory, link, deletion, or absent exact targets."""
    candidates = ["MM .config", "DA absent", "MM link", "MM modify_directory"]
    metadata = json.dumps({".config/settings": {"sourceRelative": "dot_config/modify_settings"}})
    assert (
        ChezmoiConflictClassifier.replacement_conflicts(
            candidates, metadata, [candidate[3:] for candidate in candidates]
        )
        == candidates
    )


def test_modifier_metadata_cannot_exempt_a_target_that_is_not_a_current_regular_file():
    """Desired source types cannot approve replacement of missing files, links, or directories."""
    candidates = ["DM missing", "MM link", "MM directory"]
    metadata = json.dumps({candidate[3:]: {"sourceRelative": "modify_" + candidate[3:]} for candidate in candidates})
    assert ChezmoiConflictClassifier.replacement_conflicts(candidates, metadata, []) == candidates


def test_mixed_changes_preserve_the_order_and_status_of_replacements():
    """Only exact modifier entries leave the approval list; ordinary changes stay visible."""
    candidates = ["MM .codex/config.toml", "DA settings with spaces", "MM .zshrc"]
    metadata = json.dumps(
        {
            ".codex/config.toml": {"sourceRelative": "dot_codex/modify_private_config.toml"},
            ".zshrc": {"sourceRelative": "dot_zshrc"},
        }
    )
    assert (
        ChezmoiConflictClassifier.replacement_conflicts(
            candidates, metadata, [candidate[3:] for candidate in candidates]
        )
        == candidates[1:]
    )


@pytest.mark.parametrize(
    "metadata",
    [
        "private-invalid-output",
        "null",
        "[]",
        '{".config": null}',
        '{".config": {}}',
        '{".config": {"sourceRelative": 3}}',
        '{".config": {"sourceRelative": ""}}',
    ],
)
def test_malformed_metadata_fails_without_exposing_command_output(metadata):
    """Unverified metadata stops classification instead of approving replacements."""
    with pytest.raises((TypeError, ValueError), match="invalid managed-file metadata") as error:
        ChezmoiConflictClassifier.replacement_conflicts(["MM .config"], metadata, [".config"])
    assert "private-invalid-output" not in str(error.value)
