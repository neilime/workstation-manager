"""Protect source freshness, previews, private failures, and verified change reporting."""

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.chezmoi_source import (
    ChezmoiSourceError,
    ChezmoiSourceUpdater,
)


@pytest.fixture(name="source_update")
def source_update_fixture(tmp_path):
    """Model Git at its command boundary without credentials entering arguments or error text."""
    state = {"head": "a" * 40, "remote": "a" * 40, "calls": [], "fail": "", "verify": True, "dirty": False, "stash": ""}

    def run(command, *, environ_update):
        assert environ_update["GIT_TERMINAL_PROMPT"] == "0"
        assert environ_update["GIT_OPTIONAL_LOCKS"] == "0"
        assert environ_update["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
        assert "private-source-token" not in " ".join(command)
        arguments = command[3:]
        state["calls"].append(arguments)
        output = ""
        if arguments[0] == state["fail"] and (arguments[0] != "stash" or arguments[1] == "push"):
            return 1, "private-source-token", "private-source-token"
        if arguments == ["rev-parse", "--show-toplevel"]:
            output = str(tmp_path)
        elif arguments == ["rev-parse", "HEAD"]:
            output = state["head"]
        elif arguments == ["rev-parse", "FETCH_HEAD"]:
            output = state["remote"]
        elif arguments == ["rev-parse", "--verify", "refs/stash"]:
            output = state["stash"]
        elif arguments[0] == "status" and state["dirty"]:
            output = " M dot_zshrc"
        elif arguments[:2] == ["stash", "push"]:
            state["dirty"] = False
            state["stash"] = "c" * 40
        elif arguments[:2] == ["stash", "list"]:
            output = state["stash"]
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


def test_dirty_source_reports_a_reconcilable_failure_without_mutation(source_update):
    """Only an initial local-edit failure can offer the source reconciliation prompt."""
    updater, state = source_update
    state["dirty"] = True
    with pytest.raises(ChezmoiSourceError) as error:
        updater.ensure()
    assert error.value.local_changes
    assert not error.value.changed
    assert not any(command[0] in {"fetch", "stash", "merge"} for command in state["calls"])


def test_approved_stash_is_not_created_in_check_mode(source_update):
    """Previewing an approved action cannot move local edits or claim remote freshness."""
    updater, state = source_update
    state["dirty"] = True
    result = updater.ensure(check_mode=True, stash_local_changes=True)
    assert not result["remote_verified"]
    assert state["dirty"]
    assert not any(command[0] in {"fetch", "stash", "merge"} for command in state["calls"])


@pytest.mark.parametrize("operation", ["fetch", "merge-base", "stash", "merge"])
def test_stash_or_update_failure_preserves_recovery_and_stops_reconciliation(source_update, operation):
    """Check remote ancestry before stashing and report saved work even when the update fails."""
    updater, state = source_update
    state.update(dirty=True, remote="b" * 40, fail=operation)
    with pytest.raises(ChezmoiSourceError) as error:
        updater.ensure(stash_local_changes=True)
    assert not error.value.local_changes
    assert "private-source-token" not in str(error.value)
    assert state["head"] == "a" * 40
    assert error.value.changed == (operation in {"stash", "merge"})
    if operation == "merge":
        assert "c" * 40 in str(error.value)
        assert "stash apply --index" in str(error.value)
    else:
        assert state["dirty"]


def test_incomplete_stash_cannot_allow_source_application(source_update):
    """Remaining worktree changes after an approved stash still fail with recovery instructions."""
    updater, state = source_update
    state.update(dirty=True, remote="b" * 40)
    original_run = updater.run_command

    def leave_dirty(command, **kwargs):
        result = original_run(command, **kwargs)
        state["dirty"] = True
        return result

    updater.run_command = leave_dirty
    with pytest.raises(ChezmoiSourceError) as error:
        updater.ensure(stash_local_changes=True)
    assert error.value.changed
    assert not error.value.local_changes
    assert "c" * 40 in str(error.value)
    assert not any(command[0] == "merge" for command in state["calls"])


def test_stash_must_create_a_new_entry_before_claiming_edits_were_saved(source_update):
    """Unstashable edits must not be reported as saved in an unrelated existing stash."""
    updater, state = source_update
    state.update(dirty=True, stash="d" * 40)
    original_run = updater.run_command

    def skip_stash(command, **kwargs):
        if command[3:5] == ["stash", "push"]:
            return 0, "No local changes to save", ""
        return original_run(command, **kwargs)

    updater.run_command = skip_stash
    with pytest.raises(ChezmoiSourceError, match="No new Chezmoi source stash") as error:
        updater.ensure(stash_local_changes=True)
    assert not error.value.local_changes
    assert "d" * 40 not in str(error.value)
    assert state["dirty"]
    assert not any(command[0] == "merge" for command in state["calls"])
