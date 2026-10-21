# neilime.workstation_backup

Owns recovery checks, approved synchronization, archive creation, Git inventory,
and backup manifests. Skipped sources are recorded as incomplete coverage.
Failed operations or verification of approved changes stop backup.

The shared [recovery decision role](roles/recovery_decision/README.md) handles
explicit choices; source roles own inspection, approved actions, and verification.
Backup uses the resolved managed user and preserves credential privacy.

- [Backup and restore](../../../../../docs/usage/backup-and-restore.md): workflow, archive contract, and recovery limits.
- [Bitwarden integration](../../../../../docs/development/automation.md#bitwarden-integration): fresh reads and credential boundaries.
- [Browser adapters](../../../../../docs/development/browser-adapters.md): native recovery verification.
- [Development](../../../../../docs/development/README.md): collection boundaries and validation.
