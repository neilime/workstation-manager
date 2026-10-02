# Backup and restore

Recovery uses Bitwarden for keys and browser profiles, Git for Chezmoi files, a
browser sidecar for bookmarks plus sanitized non-secret preferences, and an archive
for project files and workstation-manager user configuration. Keep access to all
four; the archive alone is not a complete recovery source.

## Create a backup

Run from an interactive terminal:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  sh -s -- backup
```

Enter the destination when prompted. Choose a directory outside the files being
backed up. You can provide it directly:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_BACKUP_OUTPUT_DIR=/media/backup/workstation sh -s -- backup
```

Backup authenticates with sudo before launching Ansible. Your local sudo password
is separate from your Bitwarden vault password. Recovery checks, user caches, and
archive creation run as the managed user; dependency installation runs as root.
Non-interactive runs must allow sudo to launch Ansible without prompting.

Backup checks recovery sources before creating the archive:

- Chezmoi managed files: Choose `save` to capture workstation files, or `restore` to apply source state locally.
- Chezmoi Git checkout: Choose how to reconcile local and remote source changes, then approve `publish` separately if keeping local changes.
- Local SSH/GPG keys: Choose `save` to update Bitwarden with the local key. Each save is verified. Keys stored only in Bitwarden are left untouched.
- Browser profiles: Choose `save` to update Bitwarden with local names, colors and logos; use `retry` after manual pairing or record creation. See [browser recovery](browser.md).
- Browser Sync: Check every profile has finished syncing and its stable 24 recovery words match its Bitwarden note. Brave supplies the current rotating 25th pairing word when joining. Never paste the words into the prompt.

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

Recovery prompts use the same direction names, chosen separately at each step:

- `save` keeps this computer's version in recovery storage.
- `restore` replaces this computer's version with the stored version.

Backup only offers `save` for keys, copying the local key to Bitwarden without
deleting unrelated keys or remote records. A key present only in Bitwarden is left
untouched, because backup never overwrites local keys to match the vault. GPG `save`
includes the key's ownertrust record when one exists.

Backup verifies each applied change. When Sync everything is disabled, enable it in
the browser and choose `retry`. Browser `sync` runs synchronization and verifies recovery
codes against Bitwarden; code mismatches offer `save`.
Each prompt also offers `skip` and `abort`; an earlier approval never selects a later action.
`skip` leaves that recovery source unchanged at this step and continues the other
backup work:

- In a Chezmoi prompt, `skip` skips all remaining Chezmoi checks for this run.
- In an SSH/GPG prompt, `skip` skips only the current key; other keys still prompt.
- In browser drift, `skip` skips browser recovery and automatic live Sync verification.
  At the live Sync prompt, it skips live verification alone.

Skipping does not undo actions you already approved. It does not add dotfiles or
keys to the archive automatically, and setup still does not restore browser data
from local files. Backup can still write a separate browser sidecar with local
bookmarks and sanitized non-secret preferences when native profiles exist, but
Bitwarden and Sync remain the recovery path for profile recreation. An archive can
still be created, and the final output reports **incomplete recovery coverage**,
with its manifest containing `recovery_status` set to `incomplete` plus
`recovery_skipped` records for the affected categories. Key records identify only
SSH/GPG categories, not key contents or vault records.

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

- `save` preserves local source changes. When the branch is behind or
  diverged, it commits all
  uncommitted source changes, then fast-forwards or merges the
  upstream branch while preserving local commits. It does not push. A conflict
  stops backup; inspect `git status` in the displayed source directory, resolve
  and complete the merge or run `git merge --abort`, then retry backup. Any commit
  made to save local edits remains available after aborting the merge.
  When there are no incoming commits, it keeps local changes for the separate
  publication approval.
- `skip` leaves this step unchanged and skips the remaining Chezmoi recovery
  checks. It does not publish local changes or add dotfiles to the archive.
- `abort` stops backup without changing source files or publishing anything.

Backup never discards local source changes to match the remote, because that
would drop the very changes a backup exists to preserve. Reconcile manually in
another terminal if you need to replace local work, then retry backup.

After Git reconciliation, backup checks managed workstation files against the
updated source and offers `save`, `restore`, `skip`, or `abort` if they differ. Remaining
local Git changes require a separate `publish` approval or an explicit `skip`
before backup can continue. A remote update during these checks stops backup so you can review it
on the next run.

Files no longer managed by the remote source are not automatically deleted from
your home.

Publish changes to your private overrides too; see
[configuration](configuration.md). A separately supplied local override is not
checked for publication.

## Included files and recovery limits

The default archive includes:

- `~/Documents/dev-projects`: project files, including local modifications and
  untracked files outside the exclusions below.
- `~/.config/workstation-manager`: workstation-manager user configuration.

Missing source paths are listed in the manifest. Backup fails if no source path
exists. The archive excludes nested `.git` metadata and the contents of
`node_modules`, `.venv`, `.pytest_cache`, `__pycache__`, `dist`, `build`, `.next`,
`coverage`, and `target` directories.

Inside Git repositories, backup also excludes untracked files and directories
ignored by `.gitignore` files, `.git/info/exclude`, or your global Git ignore file.
Nested projects, worktrees, and submodules use their own ignore rules; ignored
nested checkouts are omitted entirely. Tracked files remain eligible even when
they match a Git ignore pattern, because Git does not treat tracked files as
ignored. Files outside Git repositories use the directory exclusions above.

Backup skips excluded directory trees before reading their contents and streams
each included entry once through native `tar` and `gzip`. It uses fast gzip
compression; archives can be larger than with maximum compression. A private
`.partial` file holds the archive until creation succeeds, then replaces the
destination. A failed backup leaves any
previous completed archive intact. If an interrupted process leaves a `.partial`
file, check that no backup is running and move it aside before retrying.
If a source file changes while `tar` reads it, backup fails; stop writes to your
projects and retry.

During archive creation, backup displays the compressed archive size and elapsed
time every five seconds. Updates start with `preparing files` until the archive
begins growing. A final size update appears when archive creation finishes.

SSH/GPG keys, browser data, and other home directories are not archive sources by
default. Setup restores keys from Bitwarden, applies Chezmoi, and recreates browser
profiles with [automatic Sync recovery](browser.md). Backup writes browser bookmarks and
sanitized non-secret preferences to a separate sidecar when profiles exist, but
setup does not import that sidecar automatically.

To include additional directories, set a colon-separated list:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_BACKUP_EXTRA_PATHS="$HOME/Documents/notes:$HOME/Pictures" \
  sh -s -- backup
```

The same exclusions apply to extra paths. Explicitly selected browser stores are
included without browser-specific filtering. Archive paths are relative to the
common parent of all requested sources, including missing default sources. Default
backups therefore keep paths relative to your home. Keep extra paths under your
home and check the archive layout before restoring.

Backup also writes `<archive>.restore-command.txt` beside the archive with the
full `setup` command for replaying that specific backup on another computer.

Keep the archive and generated sidecars together. Backup always writes the
manifest, Git inventory, and restore-command sidecars; the browser sidecar is
created when local profiles exist:

- `.tar.gz`: Archived user files.
- `.restore-command.txt`: Copy-pasteable `setup` command for replaying the
  paired archive.
- `.browser-profiles.json`: Browser bookmarks plus sanitized non-secret
  preferences for local inspection or manual recovery.
- `.git-repositories.json`: Git remotes, branch, commit, and working-tree
  status for discovered dev projects.
- `.manifest.txt`: Timestamp, archive path, source paths, sidecars, and skipped
  recovery categories.

These files are **not encrypted**. Project files can contain secrets, the
inventory contains paths and remote URLs, and bookmarks can reveal private
services even when preferences are sanitized. Store them in a private destination;
copying them off the computer is your responsibility.

The Git inventory supports repositories with a physical `.git` directory.
It omits nested checkouts ignored by the enclosing project's Git rules, such as
repositories under `tools/vendor/` when that directory is ignored. Non-ignored
nested projects remain in the inventory. It does not
preserve Git history that exists only locally, stashes, reflogs, or the staging
index. Push commits you need to recover before relying on this backup.

## Restore during setup

Place the archive and its matching sidecars together, then run:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  WORKSTATION_MANAGER_RESTORE_ARCHIVE=/media/backup/workstation/workstation-manager-backup-20260927T120000Z.tar.gz \
  sh -s -- setup
```

If the archive was created by workstation-manager, you can copy the command from
the matching `.restore-command.txt` sidecar instead of rebuilding it manually.

Setup installs the managed baseline and applies Chezmoi before extracting files
into your home. Existing files at archived paths can be overwritten. The browser
sidecar is backup-only and is not consumed by setup; browser recovery still comes
from Bitwarden and Sync. Check the archive layout first:

```sh
tar -tzf /path/to/workstation-manager-backup.tar.gz
```

For the default sources, expect paths such as `Documents/dev-projects/...` and
`.config/workstation-manager/...`, even when one source was missing at backup time.
Setup also restores single-source archives containing `dev-projects/...` into
`~/Documents`, or `workstation-manager/...` into `~/.config`. The matching manifest
lets setup resolve a shortened archive root when extra source paths are present.
Setup reports the extraction directory; inspect it when extra paths changed the
archive root.

Setup validates the archive before extraction. It rejects absolute paths, path
traversal, relative link paths that leave your home, absolute hard links, entries beneath
archived symlinks, duplicate entries at symlink paths, and special files. Absolute
symbolic links and relative aliases to them are preserved, including virtual
environment interpreter links;
their targets must exist on the restored workstation before you use them. This
checks extraction safety, not whether the files are trustworthy.

When the Git inventory is present, setup clones each project's primary remote,
fetches all its branches, checks out the recorded branch, restores its additional
remotes, then copies the archived files over the clone. Other remote branches
remain available for commands such as `git switch main`. A recorded detached
commit is restored only when available from the clone. This overlay does not
replay file deletions; inspect `git status` after recovery.

SSH remotes use the target user's restored keys and SSH configuration. Setup
automatically records a host's key on first connection and rejects changes to
known keys. A host-key verification error occurs before repository permissions
are checked; verify the server's fingerprint and review the target user's
`~/.ssh/known_hosts` before retrying.

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
