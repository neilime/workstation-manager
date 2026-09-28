# neilime.workstation_backup

Owns key and browser recovery checks, Chezmoi synchronization, archive creation,
Git repository inventory, and backup manifests. The entrypoint launches Ansible
with sudo; backup tasks run as the resolved managed user, while dependency
installation explicitly runs as root.

See [backup and restore](../../../../../docs/usage/backup-and-restore.md) for the
user workflow and recovery limits, and the
[development guide](../../../../../docs/development/README.md) for structure and
checks.
