# ADR 0006 Coupled GNOME extension updates

- Status: Accepted
- Date: 2026-11-06
- Supersedes: Update process in [ADR 0003, decision 4](adr-0003-desktop-system-monitor.md#4-keep-the-pin-current)
- Also supersedes: Manual GNOME digest refresh in [ADR 0001](adr-0001-workstation-toolchain.md).

## Context

[PR 315's end-to-end run](https://github.com/neilime/workstation-manager/actions/runs/42160869594/job/127744073156?pr=315)
failed because Renovate updated Clipboard Indicator's version while retaining the
previous archive's SHA-256. Manual checksum refresh made every extension update
uninstallable until a reviewer supplied the matching digest. GNOME's extension
info endpoint lists versions but does not supply archive checksums.

## Decision

Resolve the newest release for Clipboard Indicator and Vitals before launching
Renovate. Download the official archive, validate its identity and version, and
compute its SHA-256. Supply both values as a fixed
[custom datasource](https://docs.renovatebot.com/modules/datasource/custom/)
release and capture `currentDigest` alongside `currentValue` in each regular expression manager.
Renovate then updates both fields together, including digest-only corrections.

Any preparation failure stops the workflow before Renovate runs. Keep automerge
disabled and retain GNOME compatibility and Wayland acceptance review. The
[dependency guide](../dependencies.md) owns the current procedure.

## Consequences

Extension PRs contain installable version/checksum pairs. A checksum records the
archive served by the official registry; it is not independent proof of safety
or desktop compatibility. Setup retains its archive and GNOME validation.
An unavailable GNOME registry delays the whole scheduled Renovate run.

## Alternatives considered

- Manual checksum updates: rejected because they routinely produce failing PRs.
- A post-upgrade command: rejected because command failures become artifact errors
  and can leave Renovate with an incomplete update. Preparing complete releases
  before Renovate starts gives a clear failure boundary.
