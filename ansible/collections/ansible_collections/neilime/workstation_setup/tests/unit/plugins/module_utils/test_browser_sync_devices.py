"""Sync cleanup preserves the active device and requires acknowledged remote deletions."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserProtocolError,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_native_sync import (
    NativeSync,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_sync_devices import (
    SyncDeviceList,
)


def device(guid: str, name: str = "fixture-laptop", *, current: bool = False) -> dict:
    """Native identity fields suffice; browsing data never belongs in this fixture."""

    return {"guid": guid, "name": name, "isCurrentDevice": current}


CURRENT = device("current", current=True)
OLD = device("old")
OTHER = device("other", "another-computer")


def test_only_exact_name_duplicates_and_disposable_names_are_removed() -> None:
    """This Device survives even if its own name is configured as disposable."""

    devices = SyncDeviceList([CURRENT, OLD, OTHER, device("vm", "fixture-vm"), device("similar", "fixture-vm-extra")])
    assert devices.removal_ids(["fixture-vm", "fixture-laptop"]) == ["old", "vm"]
    assert devices.removal_ids([]) == ["old"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        [OLD],
        [CURRENT, CURRENT],
        [CURRENT, device("other", current=True)],
        [CURRENT, {**OLD, "isCurrentDevice": "false"}],
        [CURRENT, {**OLD, "guid": ""}],
        [CURRENT, {**OLD, "name": None}],
        [CURRENT, "private-invalid-data"],
    ],
)
def test_ambiguous_or_malformed_device_lists_cannot_authorize_cleanup(value: object) -> None:
    """A partial or unsupported native response must never select a removal target."""

    with pytest.raises(BrowserProtocolError) as error:
        SyncDeviceList(value)
    assert "private-invalid-data" not in str(error.value)


@pytest.fixture(name="native")
def native_fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[NativeSync, Mock, Mock, Mock]:
    """Exercise cleanup with native callbacks and server observations isolated."""

    encryption = {"available": True, "decryptionFailed": False}
    pipe = Mock()
    pipe.evaluate.side_effect = [True, {"issued": True, "value": True}, {"issued": True, "value": encryption}]
    instance = NativeSync(pipe, "/fixture/Default", disposable_names=["fixture-vm"])
    pipe.evaluate.side_effect = None
    pipe.evaluate.return_value = True
    pipe.wait_for_acknowledgement.return_value = True
    request = Mock()
    wait = Mock(return_value=True)
    monkeypatch.setattr(instance, "_request", request)
    monkeypatch.setattr(instance, "wait", wait)
    return instance, request, wait, pipe


def test_cleanup_verifies_every_deletion_and_is_idempotent(native: tuple) -> None:
    """Reruns retain the same device and send no deletes once the list is clean."""

    instance, request, wait, pipe = native
    before = [CURRENT, OLD, OTHER, device("vm", "fixture-vm")]
    after = [CURRENT, OTHER]
    request.side_effect = [before, before, True, True, after, after]
    assert instance.prune_devices() == 2
    assert instance.prune_devices() == 0
    deletes = [call.args for call in request.call_args_list if call.args[0] == "SyncDeleteDevice"]
    assert deletes == [("SyncDeleteDevice", "old"), ("SyncDeleteDevice", "vm")]
    wait.assert_called_once()
    pipe.watch_acknowledgement.assert_called_once()


@pytest.mark.parametrize("failure", ["observer", "changed", "rejected", "pending", "unacknowledged", "readback"])
def test_device_cleanup_cannot_claim_unverified_deletions(native: tuple, failure: str) -> None:
    """Reject failures before mutation and require server evidence plus unchanged current identity afterward."""

    instance, request, wait, pipe = native
    before = [CURRENT, OLD]
    rechecked = [device("replacement", current=True), OLD] if failure == "changed" else before
    after = before if failure == "readback" else [CURRENT]
    request.side_effect = [before, rechecked, failure != "rejected", after]
    pipe.evaluate.return_value = failure != "observer"
    wait.return_value = failure != "pending"
    pipe.wait_for_acknowledgement.return_value = failure != "unacknowledged"
    with pytest.raises(BrowserProtocolError):
        instance.prune_devices()
    if failure in {"observer", "changed"}:
        assert all(call.args[0] != "SyncDeleteDevice" for call in request.call_args_list)
