# Backup and restore

Recovery uses Bitwarden for keys and browser profiles, Git for Chezmoi files,
Brave Sync for browser data, and an archive for project files and workstation
configuration. Keep access to each source; the archive alone is incomplete.

## Create a backup

Run from an interactive terminal:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  sh -s -- backup
```

Choose a destination outside the files being backed up, or supply it directly:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR=/media/backup/workstation sh -s -- backup
```

Backup requests sudo authentication before launching Ansible. Use your local sudo
password, which is separate from your Bitwarden password. Recovery and archive
creation run as the managed user; dependency installation runs as root.
Unattended runs need sudo access without prompting.

### Recovery decisions

Before archiving, backup checks recovery sources and asks how to reconcile drift:

| Source             | Available reconciliation                                                      |
| ------------------ | ----------------------------------------------------------------------------- |
| Chezmoi files      | `save` captures local files; `restore` applies the source versions locally.   |
| Chezmoi Git source | `save` preserves local work; `publish` separately approves pushing it.        |
| SSH/GPG keys       | `save` updates Bitwarden from a local key and verifies the result.            |
| Browser settings   | `save` updates existing notes; `retry` rechecks manual fixes.                 |
| Browser Sync       | `sync` verifies recovery; mismatches can offer `save`, `restore`, or `retry`. |

See [browser recovery](browser.md#before-backup) for profile and Sync decisions.
Never paste recovery words into prompts. Each approval applies only to its step.

Each prompt also offers `skip` and `abort`. A skip preserves that step's state and
continues other backup work:

- Chezmoi: skip all remaining Chezmoi checks for the run.
- SSH/GPG: skip only the current key.
- Browser settings: skip browser recovery and live Sync verification.
- Live browser Sync: skip live verification alone.

Skipping does not undo approved actions or add dotfiles and keys to the archive.
The final output reports **incomplete recovery coverage**, and the manifest records
`recovery_status: incomplete` and affected `recovery_skipped` categories. Key skip
records identify categories without exposing key contents or vault records.

`abort` stops backup without an archive. Ctrl+C followed by `a` at Ansible's prompt
also aborts. Unresolved checks without a skip, invalid configuration, failed
operations, and failed verification of an approved change stop backup.
Non-interactive runs never choose skips automatically or confirm live browser Sync.

### Chezmoi reconciliation

Initialize Chezmoi and configure its Git upstream before backup. Complete Chezmoi
coverage requires a clean source checkout synchronized with that remote. When
incoming changes or local work exist, backup shows source status and offers
`save`, `skip`, or `abort`.

`save` preserves local work. If the branch is behind or diverged, it commits
uncommitted source changes, then fast-forwards or merges upstream while retaining
local commits. It does not push. Merge conflicts stop backup: inspect `git status`
in the displayed source directory, resolve and finish the merge or run
`git merge --abort`, then retry. Any commit created to save edits remains after
aborting the merge. Without incoming commits, edits remain for publication approval.

After reconciliation, backup checks managed files against the updated source and
offers `save` or `restore` for differences. Remaining local Git changes need a
separate `publish` approval or explicit skip. A remote update during these checks
stops backup for review on the next run.

Backup never discards local source work to match the remote. Files no longer
managed by the source are not automatically deleted from your home. Publish
[private overrides](configuration.md) too; publication of a separately supplied
local override is not checked.

### Key recovery

Key saves update Bitwarden without replacing local keys or deleting unrelated
vault records. Keys present only in Bitwarden are left untouched. GPG saves include
ownertrust when it exists; a failed ownertrust export stops backup.

SSH keys are identified by contents. If private-key material appears in a `.pub`
file, preserve the files before correcting local names and Bitwarden fields. The
private key belongs in `~/.ssh/<name>` with mode `0600`; its public counterpart
belongs in `~/.ssh/<name>.pub`.

If a save reports a locked or expired vault session, rerun backup to unlock it.
Avoid changing the same Bitwarden CLI session from another terminal while backup
is waiting for decisions.

## Included files and recovery limits

The default archive contains:

- `~/Documents/dev-projects`: project files and eligible untracked files.
- `~/.config/workstation-manager`: workstation-manager user configuration.

Missing paths appear in the manifest; backup fails if none exists. Exclusions are
nested `.git` metadata and contents of `node_modules`, `.venv`, `.pytest_cache`,
`__pycache__`, `dist`, `build`, `.next`, `coverage`, and `target` directories.

Inside Git repositories, untracked paths ignored by `.gitignore`, `.git/info/exclude`,
or global Git rules are also excluded. Nested projects, worktrees, and submodules
use their own rules; ignored nested checkouts are omitted. Tracked files remain
eligible even if they match an ignore pattern. Outside repositories, only the
directory exclusions apply.

Include extra directories with a colon-separated list:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS="$HOME/Documents/notes:$HOME/Pictures" \
  sh -s -- backup
```

The same exclusions apply. Explicitly selected browser stores receive no
browser-specific filtering. Keep extra paths under your home and inspect the
archive layout before restoring. Paths are relative to the common parent of all
requested sources, including missing defaults; default backups are home-relative.

Archive creation reports size and elapsed time. Files changing while being read
cause failure; stop writes and retry. A private `.partial` file replaces the
destination only after success, preserving any previous completed archive on
failure. If an interrupted run leaves `.partial`, confirm no backup is running
before moving it aside and retrying.

Keep the archive and sidecars together:

| File suffix              | Contents                                                 |
| ------------------------ | -------------------------------------------------------- |
| `.tar.gz`                | Archived user files                                      |
| `.restore-command.txt`   | Setup command for this archive                           |
| `.git-repositories.json` | Project remotes, branch, commit, and working-tree status |
| `.manifest.txt`          | Sources, missing paths, sidecars, and skipped recovery   |
| `.browser-profiles.json` | Bookmarks and sanitized non-secret preferences           |

The browser sidecar is created when local profiles exist, including when browser
recovery was skipped. It supports manual inspection or recovery; setup does not
import it. Keys and other home directories are also outside the default archive.
Setup restores keys from Bitwarden, applies Chezmoi, and uses Brave Sync.

These files are **not encrypted**. Projects can contain secrets; inventories and
bookmarks can expose private paths, services, and remote URLs. Use a private
destination and copy the backup off the computer yourself.

Git inventory discovers repositories with a physical `.git` directory and skips
Git-ignored directories and checkouts. Unreadable non-ignored directories stop
inventory collection. It does not preserve locally exclusive Git history, stashes,
reflogs, or the staging index. Push commits you need to recover before relying on
this backup.

## Restore during setup

Place the archive and matching sidecars together. Copy the command from
`.restore-command.txt`, or supply the archive path:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_RESTORE_ARCHIVE=/path/to/workstation-manager-backup.tar.gz \
  sh -s -- setup
```

Replace `/path/to/workstation-manager-backup.tar.gz` with your archive. Inspect
its layout first:

```sh
tar -tzf /path/to/workstation-manager-backup.tar.gz
```

Setup installs the baseline and applies Chezmoi before extracting into your home.
**Existing files at archived paths can be overwritten.** Default archives contain
`Documents/dev-projects/...` and `.config/workstation-manager/...`, even if one
source was missing. Single-source roots `dev-projects/...` and
`workstation-manager/...` restore into `~/Documents` and `~/.config` respectively.
The matching manifest resolves shortened roots when extra sources are present;
check the reported extraction directory.

Before extraction, setup rejects absolute paths, traversal, relative links leaving
your home, absolute hard links, entries beneath archived symlinks, duplicate
symlink paths, and special files. Absolute symlinks and relative aliases to them
are preserved, including virtual-environment interpreter links. Their targets
must exist before use. This validates extraction safety, not file trustworthiness.

### Git project recovery

With a Git inventory, setup clones the primary remote, fetches its branches and
the saved commit, recreates the saved branch or detached HEAD, restores additional
remotes, and overlays archived files. Existing remote branches retain upstream
tracking. Deleted branches are recoverable only if the server still provides the
saved commit. The overlay does not replay deletions; inspect `git status` afterward.

SSH remotes use restored user keys and configuration. First connections record
host keys; changed known keys are rejected. For a host-key error, verify the
server's fingerprint and review `~/.ssh/known_hosts` before retrying.

A project without a recorded remote stays a plain directory. Failed Git recovery
preserves restored files, reports `failed`, and stops setup after reporting results.
Check access as the managed user, then retry with the same archive. An existing
`.workstation-manager-restore-overlay` directory also stops reattachment; inspect
it before moving it aside. Without an inventory, setup restores files only.

## Preview

Append `--dry-run` to either command. Backup previews synchronization and archive
work without creating an archive, changing vault records, or modifying Git source
files and history. Restore validates the archive without extracting or cloning.

Bootstrap dependencies, configuration downloads, Bitwarden authentication, and
cache refreshes can still occur. Previews do not certify remote Git freshness or
live browser Sync completion.
