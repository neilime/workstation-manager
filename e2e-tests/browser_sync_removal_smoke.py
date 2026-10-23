"""Exercise exact-identity deletion evidence in the disposable native browser smoke test."""

from __future__ import annotations

import json
from collections.abc import Callable

from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_cdp import (
    BrowserPipe,
)
from ansible_collections.neilime.workstation_setup.plugins.module_utils.browser_sync_devices import (
    _REMOVAL_BINDING,
    _REMOVAL_CHECKS,
    _WATCH_REMOVAL,
)


def device_removal_acknowledgement(pipe: BrowserPipe, page: str) -> Callable[[], bool]:
    """Only a fresh successful commit for the captured device proves server removal."""

    acknowledged = pipe.watch_acknowledgement(page, _REMOVAL_BINDING)
    assert acknowledged() is False
    pipe.evaluate(
        page,
        """(() => {
          const send = chrome.send;
          chrome.send = (method, args) => {
            if (method === 'getAllNodes') throw new Error('Teardown must not query browser data');
            send(method, args);
          };
          window.fixtureRefreshes = 0;
          return true;
        })()""",
    )
    assert pipe.evaluate(page, f"{_WATCH_REMOVAL}([])") is False
    assert pipe.evaluate(page, f"{_WATCH_REMOVAL}(['captured-device', 'second-device'])") is True
    assert pipe.evaluate(page, "window.workstationDeviceRemoval.checks") == dict.fromkeys(_REMOVAL_CHECKS, False)
    # Exercise the refresh interval used by remote-device pruning.
    assert (
        pipe.evaluate(
            page,
            "new Promise(resolve => setTimeout(() => resolve(window.fixtureRefreshes > 0), 200))",
        )
        is True
    )
    # Native ClientTagHash for the synthetic DeviceInfo_captured-device tag.
    tag = "vDaa7bHEfGrVKfQexaIbA4HNnqE="
    cases = [
        # Stale responses, updates, other devices, and failed commits do not prove deletion.
        (tag, "captured-server-id", True, "captured-server-id", "SUCCESS", -10000, False),
        (tag, "captured-server-id", False, "captured-server-id", "SUCCESS", 0, False),
        ("another-tag", "captured-server-id", True, "captured-server-id", "SUCCESS", 0, False),
        (None, "captured-server-id", True, "captured-server-id", "SUCCESS", 0, False),
        (tag, "", True, "", "SUCCESS", 0, False),
        (tag, "captured-server-id", True, "captured-server-id", "TRANSIENT_ERROR", 0, False),
        # Response IDs may be reassigned or omitted: the protocol uses request order.
        (tag, "captured-server-id", True, "another-server-id", "SUCCESS", 0, False),
        # Every selected device needs its own successful commit, including retries.
        ("dCXwbGioGJWMGC5alsHTmMfUlAQ=", "second-id", True, "second-id", "TRANSIENT_ERROR", 0, False),
        ("dCXwbGioGJWMGC5alsHTmMfUlAQ=", "second-id", True, None, "SUCCESS", 0, True),
    ]
    for request_tag, request_id, deleted, response_id, response_type, offset, expected in cases:
        event: dict = {
            "request": {
                "commit": {"entries": [{"id_string": request_id, "client_tag_hash": request_tag, "deleted": deleted}]}
            },
            "response": {"commit": {"entryresponse": [{"id_string": response_id, "response_type": response_type}]}},
        }
        if response_id is None:
            del event["response"]["commit"]["entryresponse"][0]["id_string"]
        # A successful unrelated entry must not acknowledge the selected device.
        event["request"]["commit"]["entries"].insert(
            0, {"id_string": "unrelated-id", "client_tag_hash": "unrelated-tag", "deleted": True}
        )
        event["response"]["commit"]["entryresponse"].insert(0, {"response_type": "SUCCESS"})
        result = pipe.evaluate(
            page,
            """(() => {
              const {webUIListenerCallback} = window.cr;
              const fixture = FIXTURE;
              const time = Date.now() + OFFSET;
              webUIListenerCallback('onProtocolEvent', {time, type: 'Commit Request', proto: fixture.request});
              const respond = () => webUIListenerCallback(
                'onProtocolEvent', {time, type: 'Commit Response', proto: fixture.response});
              if (DELAYED) setTimeout(respond, 100);
              else respond();
              return window.workstationDeviceRemoval.acknowledged;
            })()""".replace("FIXTURE", json.dumps(event))
            .replace("OFFSET", str(offset))
            .replace("DELAYED", json.dumps(expected)),
        )
        assert result is False
        if expected:
            assert pipe.wait_for_acknowledgement(page, _REMOVAL_BINDING, timeout=5) is True
        assert acknowledged() is expected
    assert pipe.evaluate(page, "window.workstationDeviceRemoval.checks") == dict.fromkeys(_REMOVAL_CHECKS, True)
    pipe.evaluate(page, "clearInterval(window.workstationDeviceRemoval.timer); true")
    print("Device removal requires a fresh successful server commit for its captured identity.", flush=True)
    return acknowledged


def device_removal_readback(pipe: BrowserPipe) -> None:
    """Opted-in readback reports only fresh server tombstones for every captured identity."""

    captured = {
        "id_string": "captured-server-id",
        "client_tag_hash": "vDaa7bHEfGrVKfQexaIbA4HNnqE=",
        "deleted": True,
        # Native protobuf int64 values are decimal strings, not JS numbers.
        "version": "9223372036854775807",
    }
    for read_back in (False, True):
        page = pipe.page("brave://sync-internals")
        acknowledged = pipe.watch_acknowledgement(page, _REMOVAL_BINDING)
        pipe.evaluate(
            page,
            """(async () => {
              const {addWebUiListener, removeWebUiListener, webUIListenerCallback}
                = await import('chrome://resources/js/cr.js');
              window.workstationSyncSettings = {addWebUiListener, removeWebUiListener};
              window.fixtureProtocolEvent = event => webUIListenerCallback('onProtocolEvent', event);
              window.fixtureRefreshes = 0;
              chrome.send = method => {
                if (method === 'getAllNodes') throw Error('Teardown must not query browser data');
                if (method === 'triggerRefresh') window.fixtureRefreshes++;
              };
              return true;
            })()""",
        )
        arguments = "['captured-device', 'second-device'], true" if read_back else "['captured-device']"
        assert pipe.evaluate(page, f"{_WATCH_REMOVAL}({arguments})") is True

        def publish(
            entry: dict,
            *,
            details: str = "Received 1 update(s).",
            error: str | None = "SUCCESS",
            offset: int = 0,
            session: str = page,
        ) -> bool:
            event = {
                "type": "GetUpdates Response",
                "details": details,
                "proto": {
                    "error_code": error,
                    "get_updates": {
                        "entries": [entry],
                        "changes_remaining": "1" if details.endswith(" Some updates remain.") else "0",
                    },
                },
            }
            result = pipe.evaluate(
                session,
                "(() => { const event = "
                + json.dumps(event)
                + f"; event.time = Date.now() + {offset}; window.fixtureProtocolEvent(event); "
                "return window.workstationDeviceRemoval.acknowledged; })()",
            )
            assert isinstance(result, bool)
            return result

        if not read_back:
            assert publish(captured) is False
            assert acknowledged() is False
            assert pipe.evaluate(page, "window.workstationDeviceRemoval.checks") == dict.fromkeys(
                _REMOVAL_CHECKS, False
            )
        else:
            assert publish(captured, offset=-10000) is False
            assert publish(captured, details="Received error: transient failure") is False
            assert publish(captured, error="TRANSIENT_ERROR") is False
            assert publish(captured, error=None) is False
            assert publish(captured, details="Received 2 update(s).") is False
            for invalid in (
                {"client_tag_hash": "another-device-tag"},
                {"client_tag_hash": None},
                {"deleted": False},
                {"id_string": ""},
                {"version": None},
                {"version": "0"},
                {"version": "-1"},
            ):
                assert publish({**captured, **invalid}) is False
            assert pipe.evaluate(page, "window.workstationDeviceRemoval.checks") == dict.fromkeys(
                _REMOVAL_CHECKS, False
            )
            # An owned tombstone proves its deletion even when later pages remain;
            # the second captured identity still requires independent evidence.
            assert publish(captured, details="Received 1 update(s). Some updates remain.") is False
            assert acknowledged() is False
            assert (
                publish(
                    {**captured, "client_tag_hash": "dCXwbGioGJWMGC5alsHTmMfUlAQ=", "id_string": "second-server-id"}
                )
                is True
            )
            assert pipe.wait_for_acknowledgement(page, _REMOVAL_BINDING, timeout=5) is True
            assert acknowledged() is True
            assert pipe.evaluate(page, "window.workstationDeviceRemoval.checks") == {
                name: name in {"Device Tombstone", "Server Acknowledgement"} for name in _REMOVAL_CHECKS
            }
        replace_removal_observer(pipe, page)
        assert acknowledged() is read_back
    print("Removal readback and fresh commit observers retain independent server evidence.", flush=True)


def replace_removal_observer(pipe: BrowserPipe, page: str) -> None:
    """A new commit observer cannot inherit proof or callbacks from the previous watcher."""

    binding = "workstationDeviceRemovedCommit"
    acknowledged = pipe.watch_acknowledgement(page, binding)
    assert pipe.evaluate(page, f"{_WATCH_REMOVAL}(['second-device'], false, {json.dumps(binding)})") is True
    assert acknowledged() is False
    assert pipe.evaluate(page, "window.workstationDeviceRemoval.checks") == dict.fromkeys(_REMOVAL_CHECKS, False)
    pipe.evaluate(page, "clearInterval(window.workstationDeviceRemoval.timer); window.fixtureRefreshes = 0; true")
    assert pipe.evaluate(page, "new Promise(resolve => setTimeout(() => resolve(window.fixtureRefreshes), 200))") == 0
    pipe.evaluate(
        page,
        """(() => {
          const time = Date.now();
          const publish = window.fixtureProtocolEvent;
          // This commit belongs to the previous observer, which must be removed.
          publish({time, type: 'Commit Request', proto: {commit: {entries: [{
            id_string: 'captured-server-id', client_tag_hash: 'vDaa7bHEfGrVKfQexaIbA4HNnqE=', deleted: true
          }]}}});
          publish({time, type: 'Commit Response', proto: {commit: {entryresponse: [{response_type: 'SUCCESS'}]}}});
          // Even a current tombstone cannot satisfy the new commit-only observer.
          publish({time, type: 'GetUpdates Response', details: 'Received 1 update(s).', proto: {
            error_code: 'SUCCESS', get_updates: {entries: [{id_string: 'second-server-id',
              client_tag_hash: 'dCXwbGioGJWMGC5alsHTmMfUlAQ=', deleted: true, version: '42'}]}
          }});
          return true;
        })()""",
    )
    assert acknowledged() is False
    assert pipe.evaluate(page, "window.workstationDeviceRemoval.checks['Server Acknowledgement']") is False
    pipe.evaluate(
        page,
        """(() => {
          const time = Date.now();
          const publish = window.fixtureProtocolEvent;
          publish({time, type: 'Commit Request', proto: {commit: {entries: [{
            id_string: 'second-server-id', client_tag_hash: 'dCXwbGioGJWMGC5alsHTmMfUlAQ=', deleted: true
          }]}}});
          publish({time, type: 'Commit Response', proto: {commit: {entryresponse: [{response_type: 'SUCCESS'}]}}});
          return true;
        })()""",
    )
    assert pipe.wait_for_acknowledgement(page, binding, timeout=5) is True
