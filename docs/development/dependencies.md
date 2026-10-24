# Dependency updates

Declare versions and commit pins in maintained configuration or dependency
manifests. Workstation tool pins belong in
[`ansible/group_vars/all.yml`](../../ansible/group_vars/all.yml).
Normalizers, scripts, roles, and templates consume configured values and reject
missing or invalid required pins. Private examples inherit public pins.

Setup applies configured pins and updates managed unpinned APT packages to their
repository candidates. It refreshes APT metadata at the start of system setup and
after vendor repository changes. Upgrade tasks use `state: latest`, `force_apt_get`
and `fail_on_autoremove`; the task-local lint exceptions express this update
policy. Held packages are not overridden. Declared Flatpak apps use `state: latest`;
check mode reports a potential change even when they are current. See the
[software update contract](../usage/configuration.md#software-updates).

Verify stable releases, support status and migration requirements against official
upstream sources. Use the latest stable release compatible with the supported
environment; document a concrete blocker if an upgrade cannot proceed. Remove
unused adapters, aliases, transitions, tests and docs while preserving supported
recovery and data-safety behavior.

## Update ownership

| Owner                                                    | Dependencies                                                                                                       |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| [Dependabot](../../.github/dependabot.yml)               | GitHub Actions, Docker images, and Python packages.                                                                |
| [Renovate](../../.github/renovate/renovate-config.json5) | Ansible collections, public workstation tool pins, reviewed GNOME extensions, and the coordinated Ubuntu baseline. |
| Skillshare                                               | Project skill commits and lockfile hashes through its own commands.                                                |

The [Renovate workflow](../../.github/workflows/renovate.yml) runs weekly and
supports manual dispatch. Every added or moved pin needs an update handler in the
same change. Prefer Dependabot when it supports the complete update; use Renovate
for custom extraction, release filtering, and coordinated updates. Remove obsolete
handlers and verify extraction at the actual file path.

Inline Renovate annotations cover release-based tools, AI packages, MCP servers,
and GitHub-backed mise tools. Git skill sources pin full commit SHAs; `git-refs`
annotations select the upstream branch for digest proposals. The
[pin extraction tests](../../tests/unit/test_ai_tools_pins.py) verify coverage.
Project skills use their [own update commands](project-skills.md).

## Coordinated and reviewed updates

Ubuntu updates coordinate the [baseline guard](../../ansible/ubuntu-version),
[tooling image](../../docker/tooling/Dockerfile), and
[Lima template](../../e2e-tests/lima-ubuntu.yml).
Renovate selects stable releases from Canonical's feed; Dependabot ignores that
image to avoid competing proposals. Align Python across the tooling image,
requirements, collection metadata, Make commands and CI. The test interpreter
must match the tooling image.

Clipboard Indicator and Vitals use custom GNOME Extensions datasources.
Reviewers must download the proposed archive, refresh its SHA-256, verify GNOME
compatibility, and requalify clipboard behavior or panel sensors on Wayland.
An unchanged digest blocks installation of a different archive; zero placeholders
are rejected. These updates require review.

PHP follows stable upstream tags through its maintained mise backend. Ubuntu owns
build prerequisites. The Docker Secret Service helper and Chezmoi use verified
release checksums. Keep tests independent of current release literals by using
synthetic versions or maintained configuration.

Run the affected [development checks](README.md) after changing pins, including
extraction tests for moved or added handlers. Renovate branch-update errors fail
the workflow; inspect its logs for the dependency and file. Keep guides focused
on the supported configuration. Record decisions and dated upgrade evidence in
[ADRs](adr/README.md).
