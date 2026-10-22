# Project skills

Workstation setup installs Skillshare and applies each
`.skillshare/config.yaml` below `user.projects_directory` after restoring projects
and verifying GitHub authentication. It installs missing skills and syncs the
project's selected targets as the managed user. The
[project skill tasks](../../ansible/collections/ansible_collections/neilime/workstation_setup/roles/development_tooling/tasks/project_skills.yml)
skip dependency/cache trees and directory symlinks. Dry runs list projects without
running Skillshare. Install or sync failures stop setup.

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

Run normal workstation setup, or run these commands from a project's root:

```sh
skillshare install -p && skillshare sync -p
```

Use the direct command for projects outside the configured projects directory.
Private GitHub sources require `gh auth login` and `gh auth setup-git`.

## Maintain sources and generated files

Commit `.skillshare/config.yaml` and the generated `.skillshare/skills.lock.json`.
Skillshare owns downloaded sources and lockfile hashes; do not edit them by hand.
Ignore generated `.agents/skills/` and optional `.claude/skills/` links.

Setup preserves installed revisions. To update or remove a skill:

```sh
skillshare update --all -p && skillshare sync -p
skillshare uninstall NAME -p && skillshare sync -p
```

Replace `NAME` with the selected skill and review the config and lockfile diff.
See [dependency updates](dependencies.md) for CLI pin ownership and
[AI configuration](../usage/ai-tools.md#skills) for global skills.
