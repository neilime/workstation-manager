# ADR 0005 Verified and resumable browser Sync teardown

- Status: Accepted
- Date: 2026-10-23
- Scope: End-to-end fixture lifecycle and shared native deletion observer

## Context

End-to-end setup creates devices on live recovery chains. VM deletion must require
server evidence that those exact captured devices were removed.

Brave's [device bridge][device-bridge] checks for an outstanding deletion once
per second, then invokes its callback after five checks even if upload remains
unconfirmed. Its [reset handler][reset-handler] proceeds with local Sync reset.
A callback therefore cannot certify server deletion. On retry, downloading the
device's tombstone can [reset Sync immediately][self-deletion], before an
observer attached after startup sees it. Waiting longer for active Sync does not
resolve that observation race.

These upstream sources were inspected on 2026-10-23. They explain the design;
they are not evidence of a successful current VM test.

## Decision

Run native leave in a private copy of only the captured profile and its root
encryption state. Keep the original closed and unchanged as the retry source.
Do not rejoin a chain or manufacture a replacement identity.

Hold browser HTTPS connections through a loopback CONNECT proxy until deletion
observers are ready. Forward opaque TLS traffic without inspecting payloads or
changing certificate verification, following [Chromium's proxy contract][proxy].

Accept either the existing matched commit acknowledgement or, explicitly for
teardown, a fresh successful GetUpdates response containing the captured
device's deleted entity, client tag, server ID, and positive version. The
[Sync server retains the client tag on tombstones][server]. Local inactivity,
empty device lists, and reset callbacks remain insufficient.

Atomically persist each confirmed removal before closing its browser. Retain
copies with live writers and refuse overlapping attempts. A shutdown failure
still fails teardown without undoing recorded server proof. Normal workstation
duplicate cleanup retains its commit and device-list verification contract.

Current operation and limits belong in the [end-to-end guide](../e2e-tests.md#teardown-and-reuse)
and [browser adapter guide](../browser-adapters.md#verification-and-device-removal).

## Alternatives

- Longer timeouts or additional blind retries do not recover a missed tombstone.
- Resetting and restoring the original profile creates interruption windows that
  can destroy the identity and tracker needed for another attempt.
- Treating an inactive client as removed could discard unverified remote devices.
- Creating observer devices adds registrations and credentials to the cleanup
  problem instead of observing the captured identity directly.

## Consequences

Teardown uses extra local disk space and a loopback proxy restricted to the test
fixture. Browser protocol changes still fail closed. Unit and isolated
integration tests cover proof validation, connection ordering, failed writes,
and interruption safety. Live server behavior still requires the complete VM flow.

[device-bridge]: https://github.com/brave/brave-core/blob/master/chromium_src/components/sync_device_info/device_info_sync_bridge.cc
[reset-handler]: https://github.com/brave/brave-core/blob/master/components/brave_sync/sync_service_impl_helper.cc
[self-deletion]: https://github.com/brave/brave-core/blob/master/browser/sync/brave_sync_service_impl_delegate.cc
[proxy]: https://github.com/chromium/chromium/blob/main/net/docs/proxy.md#http-proxy-scheme
[server]: https://github.com/brave/go-sync/blob/master/datastore/sync_entity.go
