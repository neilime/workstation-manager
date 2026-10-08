# AI provider adapters

The setup collection owns the implementation of
[ADR 0002](adr/adr-0002-ai-tools-setup-and-management.md).
[AI tool configuration](../usage/ai-tools.md) is the canonical user contract.

## Adapter contract

AI defaults live in `ansible/group_vars/all.yml`.
`desired_state_ai_tools.py` validates configuration metadata without inspecting the host
or retrieving secrets. The secrets normalizer validates Bitwarden item selectors
before the AI normalizer binds `bitwarden_secret` references to item UUIDs.
Required GitHub and Context7 item selectors and declared MCP credential references
reject empty values; actual vault reads remain in setup's private credential phase. `resolve_workstation_config.yml` requires `main.yml`,
`preflight.yml` and `authenticate.yml` for every key in the `providers` mapping. Each entry's `npm`,
`version`, and `command` fields provision its CLI, and its key selects the
`ai_tool_<provider>` role. New providers need no shared registry or caller changes.

The shared `ai_tools` role runs after restoration, Chezmoi, development tooling
and persistent GitHub authentication. It installs the declared provider CLIs and Orca
before checking selected clients, establishing native provider logins, provisioning
extension resources, resolving credentials and probing stdio servers. An empty provider mapping skips CLI and
extension provisioning while keeping Orca managed. Extension tasks run as the resolved user
with explicit `HOME`, `XDG_CONFIG_HOME` and `PATH`. System application installation
and Playwright's Ubuntu dependency installation use root.

An adapter consumes:

- `workstation_ai_servers`: native common `command`, `args`, and string-valued
  `env` mappings keyed by name. These contain secrets: use `no_log: true` on
  every task that consumes or copies them and clear temporary maps.
- `workstation_ai_skills`: verified source roots, relative directories and names.
- `workstation_ai_state`: private directory for adapter ownership files.

Keep shared resources in Agent Skills and MCP formats. Do not make common
workflows depend on a provider's plugin runtime or connector-specific tool names.
A skill's frontmatter and instructions must also be portable; support for the
`SKILL.md` container alone does not guarantee support for provider extensions.

Keep native schema translation in the adapter. Use `ai_provider_config` to merge
JSONC entries or the owned TOML block; use `ai_skill_links` for owned symlinks.
Both modules plan without writing in check mode and reject user conflicts before
mutating their file or link set. The shared role defers the provisioning/configuring
phase in check mode because its source paths and credentials can depend on pending
installations. Preflight must tolerate those pending installations in previews.

`authenticate.yml` establishes the provider's native account session. The Codex
and Copilot adapters use `ai_provider_auth`, whose helper strips ambient provider
tokens, selects the managed home and checks native login status. Codex requires
`login status` to report a ChatGPT session; Copilot uses the SDK's `auth.getStatus` JSON-RPC request over the
CLI's stdio transport. It checks Copilot's returned account and host against the
GitHub declaration. Interactive login uses the bootstrap terminal directly so
codes and credentials bypass Ansible's captured output. Check mode starts no
clients; unattended missing login fails. No model request or OAuth cache editing
is involved. `development.ai_tools.authenticate` defaults to true. An explicit
false defers only provider authentication; installation, configuration and MCP
verification still run, and the final report identifies unverified provider logins.
Recheck these native contracts when upgrading provider pins:
[Codex login](https://learn.chatgpt.com/docs/cli/reference) and
[Copilot SDK authentication](https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/authenticate).

`mcp_stdio.py` implements the bounded initialize/discover/call subset used by setup.
It starts a separate process group, discards stderr, bounds
response size and time, and closes the group on completion or failure. It never
logs protocol payloads. The setup probe checks discovery and each declared
`auth_check` tool call. Bitwarden credentials enter only the private server
environment. Select read-only checks; use `expect_text` when a server reports
upstream failures as text without MCP's `isError` flag, as Context7 can.

## Updating resources

Orca's release lives in `development.ai_tools.orca.version`; each CLI package,
version and command lives in `development.ai_tools.providers.<name>`. Each entry
in `development.ai_tools.mcp_servers` owns its package, version, binary and launch
settings. The annotated Renovate manager in
`.github/renovate/renovate-config.json5` extracts these pins;
`e2e-tests/unit/test_ai_tools_pins.py` checks the actual expression against every
public AI package and GitHub-backed mise tool. Global skills use Skillshare's
`name` and `source` fields. GitHub skill URLs contain immutable full commit SHAs;
the separate `git-refs` manager follows the `depName` and `branch` annotation on
each `source` and proposes updated digests. The extraction tests cover these pins.

Local skill paths resolve in the managed home. For remote skills, the shared role
runs the pinned Skillshare CLI against an isolated configuration and a source-hashed
download directory. Existing installations are reused; changing a source creates a
new installation before provider links are reconciled. Native installation audit
failures propagate. Provider adapters retain ownership of links and preserve
user-authored skill directories. Repository-scoped skills use their native
Skillshare configuration and lockfile through the development tooling role.

Review Node requirements, exported binaries, credential handling and browser
selection when updating MCP versions. Setup uses the Playwright CLI from the
installed MCP dependency tree, including upstream's exactly pinned prerelease
Playwright dependency when a stable MCP release uses one. Do not replace that
dependency independently or run an unrelated global Playwright installer.

Upstream contracts: [Copilot configuration](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers),
[Visual Studio Code MCP](https://code.visualstudio.com/docs/agents/reference/mcp-configuration),
[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli),
[Skillshare installation](https://skillshare.runkids.cc/docs/reference/commands/install/),
[Context7](https://github.com/upstash/context7), and
[Playwright MCP](https://github.com/microsoft/playwright-mcp).

## Testing

AI coverage uses unit and isolated integration tests. Run them through the normal
[development checks](README.md):

```sh
make test-unit
make test-integration
```

Collection unit tests cover normalization, native configuration merging, skill
ownership, authentication status handling and MCP protocol failures using synthetic
inputs and disposable processes. Pin tests verify the active Renovate expressions.

Integration tests under `e2e-tests/unit/` run real Ansible against isolated homes,
synthetic client executables and local HTTP/MCP fixtures. They cover provider
installation orchestration, Orca release authentication, adapter idempotence,
permissions, skill reconciliation, check mode and credential redaction.

These tests require no provider accounts or live AI services. Live OAuth sessions,
desktop client startup and browser operations are outside their scope. The shared
Lima setup fixture defers provider sign-in with
`development.ai_tools.authenticate: false`; it has no dedicated AI assertions.
