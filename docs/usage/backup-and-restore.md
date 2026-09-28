# Backup and restore

Recovery uses Bitwarden for keys and browser profiles, Git for Chezmoi files, and
an archive for project files and workstation-manager user configuration. Keep
access to all three; the archive alone is not a complete recovery source.

## Create a backup

Run from an interactive terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  sh -s -- backup
```

Enter the destination when prompted. Choose a directory outside the files being
backed up. You can provide it directly:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR=/media/backup/workstation sh -s -- backup
```

Backup authenticates with sudo before launching Ansible. Your local sudo password
is separate from your Bitwarden vault password. Recovery checks, user caches, and
archive creation run as the managed user; dependency installation runs as root.
Non-interactive runs must allow sudo to launch Ansible without prompting.

Backup checks recovery sources before creating the archive:

| Check                 | Required action when out of sync                                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Chezmoi managed files | Choose `re-add` to capture local changes, `apply` to overwrite local changes with source state, or `abort`.                                            |
| Chezmoi Git checkout  | Approve `publish` to commit all source changes and push them. Resolve a behind or diverged branch manually, then rerun backup.                         |
| Local SSH/GPG keys    | Approve each missing or changed key being added to or updated in Bitwarden. Saved values are read back and verified. Extra vault keys are retained.    |
| Browser profiles      | Reconcile the local profiles with their Bitwarden records, then choose `retry`. See [browser recovery](browser.md).                                    |
| Browser Sync          | Check every profile has finished syncing and its recovery words match its Bitwarden note; then choose `synced`. Never paste the words into the prompt. |

Unresolved checks stop backup. A non-interactive run cannot make these decisions
and cannot confirm live browser Sync. Saved browser settings do not prove that an
upload has completed.

Chezmoi must already be initialized. Its Git branch must have an upstream, and a
successful backup requires a clean checkout synchronized with that remote.
Publish changes to your private overrides too; see
[configuration](configuration.md). A separately supplied local override is not
checked for publication.

## Included files and recovery limits

The default archive includes:

- `~/Documents/dev-projects`: project files, including local modifications and
  untracked files.
- `~/.config/workstation-manager`: workstation-manager user configuration.

Missing source paths are listed in the manifest. Backup fails if no source path
exists. The archive excludes nested `.git` metadata and the contents of
`node_modules`, `.venv`, `.pytest_cache`, `__pycache__`, `dist`, `build`, `.next`,
`coverage`, and `target` directories.

SSH/GPG keys, browser data, and other home directories are not archive sources by
default. Setup restores keys from Bitwarden, applies Chezmoi, and recreates browser
profiles for [manual Sync pairing](browser.md).

To include additional directories, set a colon-separated list:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS="$HOME/Documents/notes:$HOME/Pictures" \
  sh -s -- backup
```

The same exclusions apply to extra paths. Explicitly selected browser stores are
included without browser-specific filtering. Archive paths are relative to the
common parent of the included sources; keep extra paths under your home and check
the archive layout before restoring.

Keep these three files together:

| File suffix              | Contents                                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `.tar.gz`                | Archived user files.                                                                                           |
| `.git-repositories.json` | Git remotes, branch, commit, and working-tree status for projects discovered under `~/Documents/dev-projects`. |
| `.manifest.txt`          | Timestamp, archive path, included or missing sources, and Git inventory location.                              |

These files are **not encrypted**. Project files can contain secrets, and the
inventory contains paths and remote URLs. Store them in a private destination;
copying them off the computer is your responsibility.

The Git inventory supports repositories with a `.git` directory. It does not
preserve Git history that exists only locally, stashes, reflogs, or the staging
index. Push commits you need to recover before relying on this backup.

## Restore during setup

Place the archive and its matching sidecars together, then run:

```sh
curl -fsSL https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_RESTORE_ARCHIVE=/media/backup/workstation/workstation-manager-backup-20260927T120000Z.tar.gz \
  sh -s -- setup
```

Setup installs the managed baseline and applies Chezmoi before extracting files
into your home. Existing files at archived paths can be overwritten. Check the
archive layout first:

```sh
tar -tzf /path/to/workstation-manager-backup.tar.gz
```

For the default sources, expect paths such as `Documents/dev-projects/...` and
`.config/workstation-manager/...`. If a default source was missing or extra paths
changed the archive root, inspect where those relative paths will land.

Setup validates the archive before extraction. It rejects absolute paths, path
traversal, links outside your home, entries beneath archived symlinks, and special
files. This checks extraction safety, not whether the files are trustworthy.

When the Git inventory is present, setup clones each project's primary remote and
recorded branch, restores its additional remotes, then copies the archived files
over the clone. A recorded detached commit is restored only when available from
the clone. This overlay does not replay file deletions; inspect `git status` after
recovery.

A project without a recorded remote remains a plain directory. If reattachment
fails, its restored files are kept as a plain directory and the result is reported
as `failed`; setup can continue. Read the reattachment results before treating
project recovery as complete. Without the inventory, only files are restored.

## Preview

Add `--dry-run` to either command. Backup reports pending synchronization and
archive work without creating an archive, changing vault records, or committing
and pushing Git changes. Restore validates the archive without extracting it or
cloning projects.

A preview still bootstraps dependencies, downloads configuration, and can
authenticate to Bitwarden and refresh its local cache. It does not certify remote
Git freshness or live browser Sync completion.
