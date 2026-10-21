"""Protect source freshness, previews, private failures, and verified change reporting."""

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.chezmoi_source import (
    ChezmoiSourceError,
    ChezmoiSourceUpdater,
)


@pytest.fixture(name="source_update")
def source_update_fixture(tmp_path):
    """Model Git at its command boundary without credentials entering arguments or error text."""
    state = {"head": "a" * 40, "remote": "a" * 40, "calls": [], "fail": "", "verify": True}

    def run(command, *, environ_update):
        assert environ_update["GIT_TERMINAL_PROMPT"] == "0"
        assert environ_update["GIT_OPTIONAL_LOCKS"] == "0"
        assert environ_update["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
        assert "private-source-token" not in " ".join(command)
        arguments = command[3:]
        state["calls"].append(arguments)
        output = ""
        if arguments[0] == state["fail"]:
            return 1, "private-source-token", "private-source-token"
        if arguments == ["rev-parse", "--show-toplevel"]:
            output = str(tmp_path)
        elif arguments == ["rev-parse", "HEAD"]:
            output = state["head"]
        elif arguments == ["rev-parse", "FETCH_HEAD"]:
            output = state["remote"]
        elif arguments[:2] == ["rev-parse", "--git-path"]:
            output = str(tmp_path / ".git" / arguments[2])
        elif arguments[0] == "symbolic-ref":
            output = "fixture"
        elif arguments[0] == "config":
            output = "origin" if arguments[-1].endswith(".remote") else "refs/heads/fixture"
        elif arguments[0] == "merge" and state["verify"]:
            state["head"] = state["remote"]
        return 0, output, ""

    return ChezmoiSourceUpdater(tmp_path, run, "private-source-token"), state


@pytest.mark.parametrize("update,preview", [(False, False), (True, False), (True, True)])
def test_fresh_source_and_changes_are_verified_without_mutating_previews(source_update, update, preview):
    """Report changes only for accepted commits; a preview cannot claim remote freshness."""
    updater, state = source_update
    if update:
        state["remote"] = "b" * 40
    result = updater.ensure(check_mode=preview)
    assert result["changed"] == (update and not preview)
    assert result["remote_verified"] != preview
    assert result["revision"] == state["head"]
    assert any(command[0] == "fetch" for command in state["calls"]) != preview
    assert any(command[0] == "merge" for command in state["calls"]) == (update and not preview)


@pytest.mark.parametrize("operation", ["fetch", "merge-base", "merge"])
def test_git_failure_cannot_report_success_or_expose_credentials(source_update, operation):
    """Fetch, ancestry, and update failures stop with safe diagnostics and preserve the prior revision."""
    updater, state = source_update
    state.update(remote="b" * 40, fail=operation)
    with pytest.raises(ChezmoiSourceError) as error:
        updater.ensure()
    assert "private-source-token" not in str(error.value)
    assert state["head"] == "a" * 40


def test_unverified_update_fails_even_when_git_reports_success(source_update):
    """A successful command cannot substitute for checking the actual source revision."""
    updater, state = source_update
    state.update(remote="b" * 40, verify=False)
    with pytest.raises(ChezmoiSourceError, match="not verified") as error:
        updater.ensure()
    assert error.value.changed


def test_unfinished_git_operation_stops_before_fetching(source_update, tmp_path):
    """An unfinished operation must remain available for manual completion or cancellation."""
    updater, state = source_update
    pending = tmp_path / ".git/MERGE_HEAD"
    pending.parent.mkdir()
    pending.write_text("b" * 40)
    with pytest.raises(ChezmoiSourceError, match="unfinished Git operation"):
        updater.ensure()
    assert pending.read_text() == "b" * 40
    assert not any(command[0] == "fetch" for command in state["calls"])
