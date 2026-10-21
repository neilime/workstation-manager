# Project skills

Workstation setup installs Skillshare and applies each
`.skillshare/config.yaml` below `user.projects_directory` after restoring projects
and verifying GitHub authentication. It installs missing skills and syncs the
project's selected targets as the managed user. Dry runs list projects without
running Skillshare; dependency/cache trees and directory symlinks are skipped.

## Declare skills

Use [this repository's config](../../.skillshare/config.yaml) as a reference:

```yaml
targets: [universal]
skills:
  - name: example
    source: <owner>/<repository>/<path-to-skill>
```

Replace the source placeholder with a reviewed skill. The `universal` target
links shared Agent Skills into `.agents/skills/` for Codex and Copilot.
For Claude Code, use `targets: [universal, claude]`; this also creates links under
`.claude/skills/`. Target selection does not install or authenticate an assistant.

Run normal workstation setup, or apply a single project directly:

```sh
skillshare install -p && skillshare sync -p
```

Use the direct command for projects outside the configured projects directory.
Private GitHub sources require `gh auth login` and `gh auth setup-git`.

## Maintain sources and generated files

Commit `.skillshare/config.yaml` and the generated `.skillshare/skills.lock.json`.
Skillshare owns downloaded sources and lockfile hashes. Ignore generated
`.agents/skills/` and optional `.claude/skills/` links.

Setup preserves installed revisions. To update or remove a skill:

```sh
skillshare update --all -p && skillshare sync -p
skillshare uninstall NAME -p && skillshare sync -p
```

Replace `NAME` with the selected skill and review the lockfile diff.
The CLI release belongs to [public defaults](../../ansible/group_vars/all.yml)
and Renovate. Global skills use the separate [AI configuration](../usage/ai-tools.md#skills).
