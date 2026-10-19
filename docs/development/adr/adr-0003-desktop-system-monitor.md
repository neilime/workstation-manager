# ADR 0003 Desktop system monitor indicator

- Status: Accepted
- Date: 2026-10-19
- Deciders: workstation-manager maintainers

## Context

The workstation runs Ubuntu with GNOME
([ADR 0001](adr-0001-workstation-toolchain.md)). GNOME's default top bar shows no
live machine telemetry, so the user cannot see CPU load, memory pressure,
temperature, or network throughput at a glance while running containerized builds
and AI tooling — the resource-heavy workloads ADR 0001 calls out as needing
bounded, observable background use.

The project already manages one top-bar GNOME Shell extension, **Clipboard
Indicator** (`clipboard-indicator@tudmotu.com`), through a reviewed, reproducible
contract in the `gnome_preferences` role:

- A pinned `version` and `sha256` live under `desktop.clipboard_indicator` in
  [public configuration](../../../ansible/group_vars/all.yml) and are validated by
  the setup collection's `desired_state_desktop` normalizer. An explicit, valid
  pin is required; there is no `latest` fallback.
- The archive is downloaded from `extensions.gnome.org` with its checksum,
  validated for identity, version, GNOME compatibility, and extraction safety
  before use, extracted into a versioned directory, registered through a stable
  symlink, and enabled through `dconf` without replacing other extensions.
- Extension preferences come from a Chezmoi-owned settings file applied with
  `community.general.dconf`, and extension version validation stays enabled.
- A Renovate custom manager and custom datasource propose new releases; the
  digest is refreshed during review.

A system monitor indicator is the same class of component and should reuse this
contract rather than add a parallel mechanism.

## Decision

Add **Vitals** (`Vitals@CoreCoding.com`,
[extension 1460](https://extensions.gnome.org/extension/1460/vitals/),
[source](https://github.com/corecoding/Vitals)) as a managed GNOME Shell top-bar
indicator installed during `setup`, using the same reviewed-extension contract as
Clipboard Indicator. Vitals surfaces CPU, memory, temperature, network, and
storage in the panel with a detailed dropdown, uses asynchronous polling to keep
background overhead bounded, and tracks current GNOME Shell releases, satisfying
ADR 0001's current-software and performance drivers.

### 1. One declarative, pinned source

`desktop.system_monitor` in [public configuration](../../../ansible/group_vars/all.yml)
carries an explicit `version` and `sha256`. Both resolve into
`workstation_manager_resolved` and are validated by the `desired_state_desktop`
normalizer with the same "explicit valid pin required" rule as the clipboard
extension. No release selector is hardcoded in roles or Python.

### 2. Reuse the extension install contract

The feature lives in its own `gnome_preferences` task file
(`tasks/system_monitor.yml`) included from the role's `main.yml`, mirroring the
clipboard task file: prepare a versioned directory, download the pinned archive
from `extensions.gnome.org` with its checksum, validate the archive (identity,
version, GNOME compatibility, extraction safety) before extraction through the
shared `GnomeExtensionArchive` validator, extract, register through a stable
symlink, and enable it in `/org/gnome/shell/enabled-extensions` while removing it
from the disabled list. Tasks are idempotent, support check mode, run as the
resolved user with the existing privilege-escalation facts, and perform no
mutation during `--dry-run`. Extension version validation stays enabled.

### 3. Chezmoi-owned preferences

Which sensors appear in the bar, their units, and the polling interval are user
preferences. They live in the companion `workstation-config` repository as
`~/.config/vitals/settings.ini` and are applied under
`/org/gnome/shell/extensions/vitals/` with `dconf`, matching how clipboard
preferences are delivered. The profile is optional: setup applies it only when the
file is present, so the indicator installs with upstream defaults until a profile
is authored.

### 4. Keep the pin current

A Renovate custom manager and custom datasource for `Vitals@CoreCoding.com` read
the GNOME Extensions info endpoint, propose reviewed releases, and leave the digest
to be refreshed during review, exactly as for Clipboard Indicator. The old digest
deliberately blocks installation of an unreviewed version. Dependabot has no
native fit and is not used.

### 5. Verify with unit and integration tests

Unit tests cover pin normalization and archive validation (identity, digest, GNOME
compatibility, and extraction safety). An isolated integration test runs the real
role tasks with a synthetic archive and temporary home to verify installation,
enablement, preference application, idempotence, check-mode safety, and that an
invalid digest stops activation without enabling the extension. Live panel
rendering and sensor accuracy remain manual Wayland acceptance checks, as ADR 0001
already scopes for Clipboard Indicator.

## Consequences

- The user gets live CPU, memory, temperature, and network status in the top bar,
  reproducibly and pinned, with the same safety guarantees as the existing managed
  extension.
- A second reviewed GNOME extension now rides the same contract. The shared
  `GnomeExtensionArchive` validator removes duplicated archive-safety logic; the
  role install flow is deliberately duplicated per feature and would only warrant a
  shared helper if a third extension is added.
- One more pin to keep current: an additional Renovate handler and a digest refresh
  on each bump.
- Live panel rendering and sensor accuracy remain manual Wayland acceptance checks,
  consistent with ADR 0001.

## Alternatives considered

- **System Monitor / System Monitor Next / Resources extensions.** Rejected as the
  default: narrower adoption and, for some, heavier or less consistently maintained
  across current GNOME releases than Vitals.
- **A standalone application (`gnome-system-monitor`, `btop`).** Rejected: it does
  not meet the always-visible top-bar status requirement. These remain available
  for deep inspection.
- **A dedicated role outside `gnome_preferences`.** Rejected: it would duplicate the
  download, validate, enable, and configure logic that already exists for Clipboard
  Indicator in `gnome_preferences`.
