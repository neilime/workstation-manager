"""Keep parallel avatar recovery bounded, complete, and private."""

from __future__ import annotations

import base64
import copy
import subprocess
import threading
from unittest import mock

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils import (
    browser_profile_avatars,
)


def profile(index: int, *, avatar: bool = True) -> dict:
    """Return normalized metadata with distinct synthetic item and attachment identities."""

    result = {"id": f"profile-{index}", "item_id": f"11111111-1111-4111-8111-{index:012d}", "label": f"Profile {index}"}
    if avatar:
        result["avatar_attachment_id"] = f"avatar-{index}"
    return result


def recovery() -> browser_profile_avatars.BrowserAvatarRecovery:
    """Use an explicit synthetic cache and session without invoking the real CLI."""

    return browser_profile_avatars.BrowserAvatarRecovery("private-session", "/fixture/Bitwarden CLI", "/fixture/bw")


def test_avatar_downloads_overlap_with_at_most_two_workers(monkeypatch):
    """Concurrent completions retain their profile association and leave input metadata unchanged."""

    mutex = threading.Lock()
    paired = threading.Barrier(2)
    second_completed = threading.Event()
    activity = {"current": 0, "peak": 0}
    completed = []

    def download(argv, **kwargs):
        assert kwargs["timeout"] == 120 and kwargs["check"] is True
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["capture_output"] is True
        assert kwargs["env"]["BW_SESSION"] == "private-session"
        assert kwargs["env"]["BITWARDENCLI_APPDATA_DIR"] == "/fixture/Bitwarden CLI"
        assert kwargs["env"]["BW_NOINTERACTION"] == "true"
        assert "private-session" not in argv
        index = int(argv[3].split("-")[-1])
        assert argv == [
            "/fixture/bw",
            "get",
            "attachment",
            f"avatar-{index}",
            "--itemid",
            profile(index)["item_id"],
            "--raw",
        ]
        with mutex:
            activity["current"] += 1
            activity["peak"] = max(activity["peak"], activity["current"])
        paired.wait(timeout=5)
        if index == 0:
            assert second_completed.wait(timeout=5)
        with mutex:
            activity["current"] -= 1
            completed.append(index)
        if index == 1:
            second_completed.set()
        return subprocess.CompletedProcess(argv, 0, f"image-{index}".encode(), b"")

    monkeypatch.setattr(browser_profile_avatars.subprocess, "run", download)
    profiles = [profile(index) for index in range(4)] + [profile(4, avatar=False)]
    original = copy.deepcopy(profiles)

    result = recovery().read(profiles)

    assert activity == {"current": 0, "peak": 2}
    assert completed.index(1) < completed.index(0)
    assert profiles == original
    assert result[-1] == profiles[-1]
    assert [base64.b64decode(item["avatar_png"]) for item in result[:-1]] == [
        f"image-{index}".encode() for index in range(4)
    ]


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing-cli"])
def test_avatar_download_retries_remain_bounded_and_private(monkeypatch, failure):
    """All four failed attempts remain fatal without exposing CLI output or credentials."""

    errors = {
        "exit": subprocess.CalledProcessError(7, ["private-command"], output=b"private-image", stderr=b"private-error"),
        "timeout": subprocess.TimeoutExpired(
            ["private-command"], 120, output=b"private-image", stderr=b"private-error"
        ),
        "missing-cli": OSError("private-path"),
    }
    download = mock.Mock(side_effect=errors[failure])
    delay = mock.Mock()
    monkeypatch.setattr(browser_profile_avatars.subprocess, "run", download)
    monkeypatch.setattr(browser_profile_avatars.time, "sleep", delay)

    with pytest.raises(ValueError, match="failed after retrying") as error:
        recovery().read([profile(0)])

    assert download.call_count == 4
    assert delay.call_args_list == [mock.call(5)] * 3
    assert "private" not in str(error.value)
    assert error.value.__context__ is None


def test_a_transient_download_failure_retries_only_the_failed_attachment(monkeypatch):
    """Successful reads are not replayed while another attachment exhausts its own retry policy."""

    attempts = {"avatar-0": 0, "avatar-1": 0}

    def download(argv, **_kwargs):
        attachment = argv[3]
        attempts[attachment] += 1
        if attachment == "avatar-1" and attempts[attachment] == 1:
            raise subprocess.TimeoutExpired(argv, 120)
        return subprocess.CompletedProcess(argv, 0, attachment.encode(), b"")

    monkeypatch.setattr(browser_profile_avatars.subprocess, "run", download)
    monkeypatch.setattr(browser_profile_avatars.time, "sleep", lambda _seconds: None)

    result = recovery().read([profile(0), profile(1)])

    assert attempts == {"avatar-0": 1, "avatar-1": 2}
    assert [base64.b64decode(item["avatar_png"]) for item in result] == [b"avatar-0", b"avatar-1"]


def test_one_failed_download_never_publishes_partial_profile_updates(monkeypatch):
    """A successful sibling attachment cannot turn incomplete recovery into a usable result."""

    def download(argv, **_kwargs):
        if argv[3] == "avatar-1":
            raise subprocess.CalledProcessError(1, argv, stderr=b"private-error")
        return subprocess.CompletedProcess(argv, 0, b"private-image", b"")

    monkeypatch.setattr(browser_profile_avatars.subprocess, "run", download)
    monkeypatch.setattr(browser_profile_avatars.time, "sleep", lambda _seconds: None)
    profiles = [profile(0), profile(1)]
    original = copy.deepcopy(profiles)

    with pytest.raises(ValueError, match="failed after retrying"):
        recovery().read(profiles)

    assert profiles == original


@pytest.mark.parametrize(
    "invalid",
    [
        {"id": "--private"},
        {"id": " profile-0"},
        {"item_id": "private-item"},
        {"avatar_attachment_id": "--private"},
        {"avatar_attachment_id": "../private"},
        {"avatar_attachment_id": ""},
        {"avatar_attachment_id": None},
    ],
)
def test_invalid_attachment_requests_stop_before_any_download(monkeypatch, invalid):
    """Validate all external identifiers before starting a valid sibling's download."""

    download = mock.Mock()
    monkeypatch.setattr(browser_profile_avatars.subprocess, "run", download)

    with pytest.raises(ValueError) as error:
        recovery().read([profile(1), {**profile(0), **invalid}])

    download.assert_not_called()
    assert "private" not in str(error.value)


@pytest.mark.parametrize("profiles", [[profile(0), profile(0)], [None], "private-value"])
def test_invalid_profile_inventory_is_rejected_before_download(monkeypatch, profiles):
    """Ambiguous ownership or malformed records cannot be silently omitted from recovery."""

    download = mock.Mock()
    monkeypatch.setattr(browser_profile_avatars.subprocess, "run", download)
    with pytest.raises(ValueError) as error:
        recovery().read(profiles)
    download.assert_not_called()
    assert "private" not in str(error.value)


@pytest.mark.parametrize("profiles", [[], [profile(0, avatar=False)]])
def test_unmanaged_avatars_require_no_download(monkeypatch, profiles):
    """Profiles without configured attachments preserve their existing metadata without CLI reads."""

    download = mock.Mock()
    monkeypatch.setattr(browser_profile_avatars.subprocess, "run", download)
    assert recovery().read(profiles) == profiles
    download.assert_not_called()


@pytest.mark.parametrize("session,cache", [("", "/cache"), ("private", "relative-private"), ("private\0", "/cache")])
def test_invalid_session_or_cache_path_is_rejected_without_disclosure(session, cache):
    """Recovery requires a usable private session and an explicit absolute account cache."""

    with pytest.raises(ValueError) as error:
        browser_profile_avatars.BrowserAvatarRecovery(session, cache, "/fixture/bw")
    assert "private" not in str(error.value)
