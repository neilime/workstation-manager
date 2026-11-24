# Project skills

Projects can declare AI agent skills in `.skillshare/config.yaml`. Workstation setup automatically installs and links them for use in your IDE and tools.

## Add or remove skills

Edit `.skillshare/config.yaml`:

```yaml
targets: [universal]  # universal = Copilot/Codex; add "claude" for Claude Code
skills:
  - name: skill-name
    source: owner/repository/path-to-skill
```

Then run:

```sh
skillshare install -p && skillshare sync -p
```

For updates and removal:

```sh
skillshare update --all -p && skillshare sync -p
skillshare uninstall SKILL_NAME -p && skillshare sync -p
```

Private GitHub sources require `gh auth login` and `gh auth setup-git`.

## What to commit

- **Commit**: `.skillshare/config.yaml` and `.skillshare/skills.lock.json`
- **Ignore**: `.agents/skills/` and `.claude/skills/` (generated links)

Do not manually edit the lockfile or generated directories; Skillshare maintains them.

Workstation setup runs Skillshare automatically for all projects under `user.projects_directory`. Setup fails if skill installation or sync fails.
