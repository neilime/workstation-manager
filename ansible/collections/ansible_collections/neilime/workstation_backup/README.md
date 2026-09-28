# neilime.workstation_backup

Owns key and browser recovery checks, Chezmoi synchronization, archive creation,
Git repository inventory, and backup manifests. The entrypoint launches Ansible
with sudo; backup tasks run as the resolved managed user, while dependency
installation explicitly runs as root. Chezmoi branch reconciliation and
publication require explicit decisions before backup can continue. Replacing
local source changes with the remote version also requires a discard confirmation.
Every drift and recovery confirmation prompt allows an explicit skip. Skipped
categories appear in the manifest and final report as incomplete recovery coverage;
failed operations and verification of approved changes still stop backup.

See [backup and restore](../../../../../docs/usage/backup-and-restore.md) for the
user workflow and recovery limits, and the
[development guide](../../../../../docs/development/README.md) for structure and
checks.
