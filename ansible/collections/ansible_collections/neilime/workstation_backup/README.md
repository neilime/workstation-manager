# neilime.workstation_backup

Owns key and browser recovery checks, Chezmoi synchronization, archive creation,
Git repository inventory, and backup manifests. SSH key discovery uses file
contents; a private key with a `.pub` filename is not skipped. The entrypoint launches Ansible
with sudo; backup tasks run as the resolved managed user, while dependency
installation explicitly runs as root. Chezmoi branch reconciliation and
publication require explicit decisions before backup can continue. Replacing
local source changes with the remote version also requires a discard confirmation.
The shared [recovery_decision role](roles/recovery_decision) handles all drift and
recovery confirmation prompts: explicit choices, input retries, previews,
noninteractive failures, aborts, and recorded skips. Each source offers `save` and `restore` when usable data exists on that
side. Source roles own inspection, approved actions, and verification. Skipped categories appear in the manifest and
final report as incomplete recovery coverage; failed operations and verification
of approved changes still stop backup.
GPG ownertrust is exported from the managed user's trust database and matched to
each key by fingerprint; see the recovery guide for missing-record behavior.
Deferred SSH/GPG writes use the current unlocked Bitwarden session after both
collections have been read, and check session status before saving.
Browser prompts offer verified metadata synchronization in both directions.
`restore` also enables Sync everything for managed profiles with Brave closed.
Pairing and other unresolved Sync checks remain visible before the separate live
Sync confirmation.

See [backup and restore](../../../../../docs/usage/backup-and-restore.md) for the
user workflow and recovery limits, and the
[development guide](../../../../../docs/development/README.md) for structure and
checks.
