# neilime.workstation_backup

Owns key and browser recovery checks, Chezmoi synchronization, archive creation,
Git repository inventory, and backup manifests. Git inventory omits nested
checkouts ignored by their enclosing project's Git ignore rules. SSH key discovery uses file
contents; a private key with a `.pub` filename is not skipped. The entrypoint launches Ansible
with sudo; backup tasks run as the resolved managed user, while dependency
installation explicitly runs as root. Chezmoi branch reconciliation and
publication require explicit decisions before backup can continue.
The shared [recovery_decision role](roles/recovery_decision) handles all drift and
recovery confirmation prompts: explicit choices, input retries, previews,
noninteractive failures, aborts, and recorded skips. Each source offers `save` to update
recovery storage from this computer; Chezmoi managed files can also `restore` stored source
locally. Source roles own inspection, approved actions, and verification. Skipped categories appear in the manifest and
final report as incomplete recovery coverage; failed operations and verification
of approved changes still stop backup.
GPG ownertrust is exported from the managed user's trust database and matched to
each key by fingerprint; see the recovery guide for missing-record behavior.
Deferred SSH/GPG writes use the current unlocked Bitwarden session after both
collections have been read, and check session status before saving. Item reads and
post-write verification use `community.general.bitwarden` with exactly one expected
record. See the [integration guide](../../../../../docs/development/README.md#bitwarden-integration)
for the remaining CLI operations.
Browser actions reconcile metadata, run live Sync, and compare recovery codes
with Bitwarden automatically. Code mismatches offer an explicit `save` direction.
Approved operations close Brave gracefully and preserve its previous
session. Pending synchronization stays unverified; failed operations stop backup.
When native browser profiles exist, backup also writes a standalone sidecar with
their bookmarks and sanitized non-secret preferences. Setup restore does not
replay that sidecar; Bitwarden and Sync remain the browser recovery source.
The state role initializes manifest records before browser export; filesystem
planning preserves those records, so the manifest lists each generated sidecar.
Archive creation streams files once with fast gzip compression, prunes excluded
directories, and applies standard Git ignore rules. It reports compressed archive
size and elapsed time and runs under the managed user's permissions.
Archive paths use the common parent of all requested sources, so a missing default
source does not shorten the home-relative project paths.

See [backup and restore](../../../../../docs/usage/backup-and-restore.md) for the
user workflow and recovery limits, and the
[development guide](../../../../../docs/development/README.md) for structure and
checks.
