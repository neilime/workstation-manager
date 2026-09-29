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
| Chezmoi Git checkout  | Choose how to reconcile local and remote source changes, then approve `publish` separately if keeping local changes.                                   |
| Local SSH/GPG keys    | Approve each missing or changed key being added to or updated in Bitwarden. Saved values are read back and verified. Extra vault keys are retained.    |
| Browser profiles      | Reconcile the local profiles with their Bitwarden records, then choose `retry`. See [browser recovery](browser.md).                                    |
| Browser Sync          | Check every profile has finished syncing and its recovery words match its Bitwarden note; then choose `synced`. Never paste the words into the prompt. |

SSH keys are identified by their contents. If backup reports private-key material
in a `.pub` file, check the local filenames and the Bitwarden `private_key` and
`public_key` fields. Preserve existing files before correcting the pair: the
private key belongs in `~/.ssh/<name>` with mode `0600`, and its matching public
key belongs in `~/.ssh/<name>.pub`. Setup rejects private-key material in a
Bitwarden `public_key` field.

GPG synchronization includes the key's ownertrust record when one exists. Keys
without an ownertrust record can still be synchronized; a failed ownertrust
export stops backup.

If a key save reports that the Bitwarden session is locked or expired, rerun
backup to unlock the vault. Avoid locking or unlocking the same Bitwarden CLI
profile in another terminal while backup is waiting for your decisions.

Recovery prompts follow the same pattern: review the reported problem, choose
one of its listed actions, then let backup recheck the result. Each prompt also
offers `skip` and `abort`; an earlier approval never selects a later action.
`skip` leaves that recovery source unchanged at this step and continues the other
backup work:

- In a Chezmoi prompt, `skip` skips all remaining Chezmoi checks for this run.
- In an SSH/GPG prompt, `skip` skips only the current key; other keys still prompt.
- In browser drift, `skip` skips browser recovery and the live Sync confirmation.
  At the live Sync prompt, it skips that confirmation alone.

Skipping does not undo actions you already approved. It does not add dotfiles,
keys, or browser data to the archive automatically. Unsynchronized local changes
may therefore be unavailable during restoration. An archive can still be created,
but the final output reports **incomplete recovery coverage**, and its manifest
contains `recovery_status` set to `incomplete` plus `recovery_skipped` records for
the affected categories. Key records identify only SSH/GPG categories, not key
contents or vault records.

Choose `abort` to stop backup. You can also press Ctrl+C, then `a` when Ansible
asks whether to abort or continue.

Unresolved checks without an explicit skip stop backup. Non-interactive runs never
choose `skip` automatically and cannot confirm live browser Sync. Invalid
configuration, failed operations, and failed verification after an approved save
still stop backup. Saved browser settings do not prove that an upload completed.

Chezmoi must already be initialized. Its Git branch must have an upstream, and a
fully checked Chezmoi recovery requires a clean checkout synchronized with that remote.
You can explicitly skip its reconciliation; the archive then records incomplete recovery coverage.
When its branch has incoming changes, local edits, or unpushed commits, backup
shows the ahead/behind counts and source file status before asking what to do:

- `merge` is available when the branch is behind or diverged. It commits all
  uncommitted source changes, then fast-forwards or merges the
  upstream branch while preserving local commits. It does not push. A conflict
  stops backup; inspect `git status` in the displayed source directory, resolve
  and complete the merge or run `git merge --abort`, then retry backup. Any commit
  made to save local edits remains available after aborting the merge.
- `keep` retains local source changes when the branch has no incoming commits;
  publication still requires separate approval later.
- `use-remote` offers to replace the source checkout with its fetched tracking
  branch. Type `discard` at the confirmation prompt to discard staged and unstaged
  source edits, delete non-ignored untracked source files, and remove local-only
  commits from the current branch. No commit or stash is created to save the
  edits, and nothing is pushed. Choose `abort` to cancel. Nested repositories,
  submodules, and ignored files that would be overwritten require manual
  reconciliation instead.
- `retry` fetches and checks again after you reconcile the source in another
  terminal, for example using your preferred rebase workflow.
- `skip` leaves this step unchanged and skips the remaining Chezmoi recovery
  checks. It does not publish local changes or add dotfiles to the archive.
- `abort` stops backup without changing source files or publishing anything.

After Git reconciliation, backup checks managed workstation files against the
updated source and offers `re-add`, `apply`, `skip`, or `abort` if they differ. Remaining
local Git changes require a separate `publish` approval or an explicit `skip`
before backup can continue. A remote update during these checks stops backup so you can review it
on the next run.

To discard local changes in both places, choose **`use-remote`, confirm `discard`,
then choose `apply`** when prompted about managed workstation files. Choosing
`re-add` would capture the workstation's current contents back into the source.
Files no longer managed by the remote source are not automatically deleted from
your home.

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
| `.manifest.txt`          | Timestamp, archive path, sources, Git inventory location, and explicitly skipped recovery categories.          |

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
archive work without creating an archive, changing vault records, or modifying
Git source files and history. Restore validates the archive without
extracting it or cloning projects.

A preview still bootstraps dependencies, downloads configuration, and can
authenticate to Bitwarden and refresh its local cache. It does not certify remote
Git freshness or live browser Sync completion.
