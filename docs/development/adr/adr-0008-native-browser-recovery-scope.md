# ADR 0008 Keep browser recovery native

- Status: Accepted
- Date: 2026-11-25
- Supersedes: The shared-pin management decision in [ADR 0007](adr-0007-browser-recovery-checkpoints.md)

## Context

The user withdrew the requirement to manage shared pinned tabs because the custom
extension and its synchronization logic add too much maintenance cost.

## Decision

Remove the managed extension, pin reconciliation, launcher overrides, native
shared-pin flag configuration, and their dedicated tests and tooling. Pinned
tabs are outside the managed recovery guarantee. Setup and backup do not manage
their configuration or synchronization.

Keep native Brave recovery: selected Sync categories, fresh download and
application checkpoints, upload acknowledgements, installation readback, and
Bitwarden profile metadata. The requirement to verify restored data before
setup succeeds still applies to this scope.

## Consequences

Browser recovery needs no custom extension or JavaScript model test runtime.
The earlier pin implementation and qualification results in ADR 0007 are
historical evidence, not supported behavior. Existing browser data and
user-managed pinned tabs remain outside this change.
