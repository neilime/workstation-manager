# neilime.workstation_restore

Owns archive validation, extraction into the target user's home, and Git
repository reattachment during setup at each saved commit, with all primary-remote
branches available. Recorded local branches are recreated even when their remote
branch has been deleted, provided the saved commit is still retrievable.
SSH clones record new host keys without prompting and reject changed known keys.
Failed Git recovery stops setup while preserving restored project files and
existing recovery overlays.
Extraction resolves shortened single-source archives to their original home
subdirectory and validates the selected destination before writing files.

See [backup and restore](../../../../../docs/usage/backup-and-restore.md) for the
user workflow and recovery limits, and the
[development guide](../../../../../docs/development/README.md) for structure and
checks.
