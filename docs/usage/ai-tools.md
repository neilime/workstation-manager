# AI tools

Setup installs Orca, Codex CLI, and Copilot CLI and configures shared skills and
MCP servers. [Public defaults](../../ansible/group_vars/all.yml) live under
`workstation_manager.development.ai_tools`. Use `development.ai_tools` in your
[private override](configuration.md#edit-your-private-override), and rerun setup
after publishing changes. Inherit maintained release pins from public defaults.

## Applications

`providers` defines the selected CLIs. The provider name selects `codex` or
`copilot`; `npm`, `version`, and `command` define its package, exact release, and
executable. Setup installs the configured release for the managed user. Client
updates can change the running version between setup runs.

`orca.version` selects Orca's release. `orca.settings` seeds missing settings while
preserving existing preferences and workspaces. An empty `providers` mapping skips
CLI provisioning and extension configuration; Orca remains managed separately.

## Authentication

Setup requires a ChatGPT account session for Codex and native OAuth sign-in for
Copilot. It reuses saved sessions or opens the client's sign-in flow in your
terminal. Complete the browser or device-code prompt. Copilot must match
`development.github.account` and `development.github.host`.

For unattended setup, sign in beforehand as the managed user with `codex login`
and `copilot login`. On a headless machine, use `codex login --device-auth` and
`copilot login --device-code`, then approve the displayed links in your browser.
A Codex API-key login or inherited automation token does not satisfy the saved
account-session requirement. Credentials remain in each client's native store.

To defer provider sign-in, explicitly set `development.ai_tools.authenticate: false`.
Setup still installs and configures providers, skills, and MCP servers and verifies
MCP startup and declared access checks. It reports sign-in as deferred and
unverified; complete native logins before using the clients.

Login checks make no model requests and do not prove subscription entitlement,
quota, or model access. Desktop applications may require separate sign-in.

## MCP servers

The default configuration provides Context7 and Playwright. Each entry in
`mcp_servers` defines a local stdio server with a unique lowercase `name`, `args`
list, and optional `env` mapping. For an npm package, supply `npm`, an exact stable
`version`, and its exported `binary`. For an already installed program, supply an
absolute `command` instead. Setup installs packages in advance; client startup
does not download them. Remote HTTP servers and their OAuth flows are unmanaged.

Set the required Context7 item UUID in your private override:

```yaml
secrets:
  bitwarden:
    context7-api-key: "<item-uuid>"
```

Store the API key in the item's password field. Setup supplies it as
`CONTEXT7_API_KEY`. Missing, blank, or invalid UUIDs fail validation, including
dry runs. An empty or inaccessible password fails normal setup.

Other MCP `env` credentials can use `bitwarden_item_id` directly or
`bitwarden_secret` to reference `secrets.bitwarden`. Credential fields support
`login.password` (the default), `login.username`, `notes`, and `fields.NAME`.
Optional `bitwarden_collection_id` restricts the item to a collection. Unknown
selectors and missing, empty, ambiguous, or inaccessible credentials fail setup.
Use literal `env` strings only for non-secret values. See
[Bitwarden authentication](configuration.md#prepare-bitwarden-collections).

Optional `auth_check` declares a read-only MCP tool call after startup. Supply its
`tool`, optional `arguments` mapping, and optional `expect_text` substring. Use a
harmless operation with no secret arguments. Failed access or a missing expected
response stops setup without logging the server response. Without `auth_check`,
setup checks startup and tool discovery only.

The default Context7 check resolves a public library; invalid credentials, quota
limits, and network errors stop setup. Local Playwright needs no server login.
For `@playwright/mcp`, set `playwright.browser` to `chromium`, `firefox`, or `webkit`.
Setup installs the matching browser and Ubuntu libraries. The default launch uses
a headless, isolated profile. Omit `playwright` only if you provision prerequisites
yourself; browser flags and external connections cannot override a managed selection.

## Skills

Skills contain `SKILL.md` and optional scripts or references. Select content that
works with your providers; a skill may require a provider-specific connector or
tool. Skillshare installs sources and exposes them to the selected clients.

Defaults select `review-loop` and `migrate-lib` from the companion repository's
`home/dot_agents/skills/`, applied through Chezmoi. For additional skills, declare
`name` and `source`. Local sources begin with `~/`, relative to the managed user's
home. Remote sources use a GitHub skill URL pinned to a full commit SHA:

```yaml
development:
  ai_tools:
    skills:
      - name: commit-messages
        source: ~/.agents/skills/commit-messages
      - name: review-checklist
        source: "<owner>/<repository>/tree/<full-commit-sha>/skills/review-checklist"
```

Replace the placeholders with a reviewed source containing `SKILL.md`. Local
sources must exist after Chezmoi applies. Remote URLs also accept the
`https://github.com/` prefix. Reruns reuse sources; changing a pin installs the
selected revision and updates managed links. Personal global Skillshare
configuration is preserved.

Public remote pins need update coverage; see
[dependency updates](../development/dependencies.md). For repository-scoped skills,
use [project skills](../development/project-skills.md).

## Configuration ownership and reruns

| Client             | MCP configuration                          |
| ------------------ | ------------------------------------------ |
| Codex              | `~/.codex/config.toml`, `mcp_servers`      |
| Copilot            | `~/.copilot/mcp-config.json`, `mcpServers` |
| Visual Studio Code | `~/.config/Code/User/mcp.json`, `servers`  |

Copilot's file serves CLI and Agent Host. Visual Studio Code is configured when
`code` is selected in `development.editor_packages`. Codex reads skills from
`~/.agents/skills`; Copilot reads `~/.copilot/skills`.

Setup preserves unrelated configuration and comments. Codex entries use a marked
TOML block; JSON entries merge individually. Native files use mode `0600` and can
contain credentials. Exclude generated MCP settings from Chezmoi and application
settings synchronization. Never capture them with `chezmoi add`.

For personal Codex settings, a Chezmoi modify template must preserve existing MCP
tables and ownership markers and leave matching files unchanged. Keep personal
tables outside the managed block, including any project tables Codex inserted
before its closing marker. Setup refuses symlinked configuration paths to keep
credentials out of dotfile sources.

Reruns update or remove only unchanged, setup-owned entries and links. Personal
files, custom skill directories, and edits to managed entries are preserved;
conflicting names stop setup. Move or rename conflicting entries before managing
them through declarations.

To remove a server or skill, remove its declaration and rerun setup while its
provider remains enabled. Disabling a provider preserves its CLI and files. Cached
packages, browser binaries, and source checkouts are retained.

## Verification and troubleshooting

Normal setup starts each server as the managed user, checks protocol initialization
and tool discovery, and runs declared access checks. Failures stop setup and server
output stays private. These checks do not prove that a desktop client starts the
server successfully or that its browser can launch.

`workstation.sh setup --dry-run` validates declarations and provider availability
where possible. Downloads, sign-in, credential reads, MCP execution, and configuration
changes are deferred; a preview does not prove startup readiness.

Restart clients after setup. Inspect servers with `/mcp` in Copilot CLI, `/mcp` or
`codex mcp list` in Codex, or **MCP: List Servers** in Visual Studio Code. Resolve
workspace or profile entries that override the same names. Keep diagnostic logs
private; they may contain credentials.
