# ADR 0006 Microsoft APM evaluation for AI tool extensions

- Status: Proposed
- Date: 2026-11-05
- Deciders: workstation-manager maintainers
- Revisits: [ADR 0002](adr-0002-ai-tools-setup-and-management.md)

## Context

[ADR 0002](adr-0002-ai-tools-setup-and-management.md) set how setup installs and
manages AI assistant extensions. The maintainer asked to re-open that decision and
weigh [Microsoft APM](https://microsoft.github.io/apm/) (Agent Package Manager)
against four goals — maintainability, staying current, continuous improvement, and
reduced complexity — explicitly accepting breaking changes. This record captures
the evaluation and a clear decision so the choice is not re-litigated later.

### What ADR 0002 implements today

The current design has four layers, each with a distinct owner:

1. **One provider-agnostic declaration.** `development.ai_tools` in
   [public configuration](../../../ansible/group_vars/all.yml) lists providers,
   skills, and MCP servers. The
   [AI normalizer](../../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/module_utils/desired_state_ai_tools.py)
   validates it without host inspection or vault reads.
2. **Per-provider adapters.** `ai_tool_copilot` and `ai_tool_codex` render the
   declaration into each client's native MCP and skill configuration and own
   reconciliation: reject conflicting names, preserve user content, plan in check
   mode, and never log secrets.
3. **Skill delivery.** Remote and project skills install through pinned
   [Skillshare](https://github.com/runkids/skillshare) — a Go single binary pinned
   in `development.mise.tools` with a Renovate annotation; custom skills are
   Chezmoi-owned. See [project skills](../project-skills.md) and
   [AI tools usage](../../usage/ai-tools.md#skills).
4. **MCP provisioning and secrets.** The
   [shared role](../../../ansible/collections/ansible_collections/neilime/workstation_setup/roles/ai_tools)
   installs each MCP server's npm package into a versioned directory behind a
   stable `current` symlink so a client never fetches it at chat startup, reusing
   the pinned system Node.js; installs Playwright's browser and Ubuntu libraries
   matched to the pinned server; resolves MCP secrets from Bitwarden as the
   resolved user with `no_log`; and runs read-only stdio
   [`auth_check` probes](../../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/module_utils/mcp_stdio.py).
   Every task is idempotent, check-mode aware, and headless under `workstation.sh`.

### What APM is (inspected 2026-11-05)

APM (`microsoft/apm`, latest `0.35.0` on 2026-10-22; pre-1.0) is a dependency
manager for agent context. An `apm.yml` manifest plus an `apm.lock.yaml` lockfile
(per-file SHA-256, pinned 40-character commit SHAs) declare seven first-class
primitives, including MCP servers. `apm install` and `apm compile` render them into
12+ assistants (Copilot, Codex, Claude, Cursor, Gemini, and more). It adds an
`apm-policy.yml` governance engine, a hidden-Unicode content scan, SBOM export, a
headless `apm install --frozen` mode, and a `microsoft/apm-action`. It installs
non-interactively with a pinned, checksum-verified standalone binary
(`curl -sSL https://aka.ms/apm-unix | VERSION=v0.35.0 sh`) or `pip install apm-cli`.

Three properties are decisive for this project:

- **It configures MCP servers; it does not provision them.** APM writes the native
  MCP client config pointing at a command (for example `npx -y <server>`). It does
  not install the server package, its Node.js or Python runtime, system packages,
  or Playwright browsers, and does not verify that the launcher is present. That
  provisioning is explicitly left to other tooling.
- **No external secret-manager integration.** Secrets flow as host-environment
  references in each target's native syntax — resolved by the harness at runtime,
  or from the environment at install time for harnesses without native
  interpolation. APM auto-generates interactive prompts for required MCP registry
  variables (optional ones never prompt), adding friction to unattended runs.
  There is no Bitwarden, Vault, or credential-helper integration.
- **Pre-1.0 with frequent breaking changes.** Minor releases ship roughly weekly
  and document `BREAKING` changes; there is no package signing (hash integrity
  only), and the project is Microsoft-hosted open source, not a product with a
  stability guarantee.

## Decision

Keep ADR 0002. Do not adopt APM as the managing layer now. Treat APM as a future
candidate only for the portable skills, prompts, and instructions delivery layer —
replacing Skillshare and the skill-link rendering — and adopt it there only when
the gates below hold. Do not route MCP servers, secrets, Playwright provisioning,
or provider orchestration through APM.

The rationale maps to the maintainer's four goals.

### Reduced complexity — not met now

APM can absorb only the thinnest, already-simple slices of ADR 0002: Skillshare
(one pinned Go binary) and the skill-link rendering
([`ai_skill_links.py`](../../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/module_utils/ai_skill_links.py),
about 90 lines). It cannot own the bulk — MCP package provisioning and the
`current` symlink, Playwright browser and dependency installation, Bitwarden
secret resolution, `auth_check` probes, and headless resolved-user orchestration —
because it only configures MCP servers and has no provisioning or secret-manager
role. Adopting it therefore keeps all the hard code and adds a second declaration
(`apm.yml` plus `apm.lock.yaml`) beside `development.ai_tools`, splitting skill and
MCP ownership across two systems. Net complexity rises rather than falls.

### Maintainability — net negative now

Replacing a stable Go single binary with a pre-1.0 tool that ships breaking changes
in weekly minor releases raises upkeep for a component on the `workstation.sh | sh`
bootstrap path. A tight `VERSION=` pin with checksum verification makes this
controllable, and any pin needs a Renovate or Dependabot handler under the
repository's [update-ownership rule](../dependencies.md#update-ownership), but the
review cadence would exceed today's. The absence of package signing adds a
supply-chain caveat for content pulled into the agent context.

### Staying current and improvement — real but narrow and future-dated

APM's genuine edge is a compiler that tracks many assistants and their format
changes for the portable skills, prompts, and instructions layer, plus lockfile
rigor (per-file SHA-256, drift audit, transitive dependencies) and optional
org-wide policy. That value lands exactly where the repository hand-maintains
adapters for skills. It is low-value today — the workstation targets Copilot and
Codex — and does not extend to MCP native rendering, which stays coupled to the
Bitwarden-aware adapters APM cannot own.

For the skills layer specifically, APM already installs deterministically and
unattended: a dependency pins to an immutable tag or commit SHA, the committed
`apm.lock.yaml` records the resolved commit and per-file SHA-256 digests, and
`apm install --frozen` replays those pins without rewriting the lockfile or
prompting — a documented CI recipe. Interactive prompts are confined to
`apm update` confirmations and to self-defined MCP servers that need environment
variables, neither of which touches a skills-only (`--only apm`) install.
Pinnable, checksum-verified, unattended skill installation is therefore not a
barrier; the remaining blockers are APM's pre-1.0 stability and the MCP/secret
split below.

### Re-evaluation gates

Adopt APM for the skills layer when all of the following hold, and record the
adoption in a superseding ADR:

1. APM reaches a stable manifest contract (1.0 or a frozen `apm.yml` and
   `apm.lock.yaml` schema) so breaking changes no longer land on the bootstrap
   path.
2. Either a documented path keeps MCP and Bitwarden secrets out of `apm.yml` and
   compatible with resolved-user Bitwarden resolution, or the skills layer is
   adopted without routing MCP through APM.
3. The workstation targets more assistants than the adapters cover cheaply, so
   multi-target compilation reduces net adapter maintenance.
4. The change deletes more than it adds: Skillshare and the skill-link rendering
   are retired while the MCP, secrets, browser, and orchestration contracts stay
   unchanged.

## Alternatives

- **Replace ADR 0002 wholesale with APM.** Rejected: APM cannot own MCP
  provisioning, Bitwarden secrets, Playwright, or headless orchestration, so the
  hard layers remain while a pre-1.0 dependency and a second manifest are added —
  more complexity and upkeep, against every stated goal.
- **Adopt APM now for skills only, keep MCP and secrets custom.** Deferred, not
  rejected: plausible, but it trades the simpler, more stable Skillshare binary for
  near-term pre-1.0 churn to gain lockfile rigor. It becomes the first adoption
  step once the gates hold.
- **Keep ADR 0002 and record nothing.** Rejected: the alternative is strong enough
  that a contributor would re-open it; the evaluation and gates belong in decision
  history.

## Consequences

- The ADR 0002 contracts stand unchanged: the provider-agnostic declaration,
  per-provider adapters, Skillshare skill install and sync, MCP provisioning with
  the `current` symlink, Playwright provisioning, Bitwarden secret resolution, and
  `auth_check` probes.
- No pre-1.0 tool enters the bootstrap path; update ownership and review cadence
  are unchanged.
- The APM evaluation and its gates are preserved here, so a revisit starts from the
  gates rather than from fresh research.
- If a gate later triggers, a superseding ADR adopts APM for the skills layer,
  retires Skillshare and the skill-link rendering, adds an APM version pin with a
  Renovate or Dependabot handler and a headless install step, and leaves the MCP,
  secrets, browser, and orchestration contracts in place.

Sources inspected 2026-11-05: APM documentation at <https://microsoft.github.io/apm/>
and the [`microsoft/apm`](https://github.com/microsoft/apm) repository (v0.35.0) — the
installation, MCP installation, manifest schema, lockfile, and security guides, plus
the README and changelog; Skillshare at <https://github.com/runkids/skillshare>.
