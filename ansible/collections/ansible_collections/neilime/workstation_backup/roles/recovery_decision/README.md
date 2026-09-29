# recovery_decision

Owns backup recovery prompts, input validation and retries, noninteractive and
preview handling, aborts, and recording explicit skips for the manifest.
Source roles inspect state, supply safe instructions and allowed actions, execute
only the selected action, and verify its result.

Call this role at each decision point with:

- `workstation_backup_recovery_id`: stable lowercase decision identifier.
- `workstation_backup_recovery_needed`: whether this step needs a decision
  (defaults to `true`).
- `workstation_backup_recovery_request`: a mapping containing `scope`, `summary`,
  `actions` (action names mapped to descriptions), `skip` (what this step skips),
  and `abort_message`. Pass display metadata only, never complete secret records.

Use `save` for copying workstation values into recovery storage and
`restore` for restoring recovery values locally. Offer only directions with
usable source data; preserve separate destructive and publication approvals.

The role supplies `skip` and `abort`; callers declare only their own actions.
Results appear in `workstation_backup_recovery_choices[id]`. Every invocation
resets that entry to an empty string, including previews and unnecessary checks,
so previous approval cannot authorize a later action. A preview reports pending
work without choosing or recording a skip. Noninteractive required decisions fail.
Requests for unnecessary checks are not evaluated.

Decision IDs distinguish stages (`chezmoi-git`, `chezmoi-discard`,
`chezmoi-files`, `chezmoi-publish`, `browser-recovery`, `browser-sync`). The `key`
ID is reset for each SSH/GPG item. Recovery scopes group manifest coverage:
`chezmoi`, `ssh-keys`, `gpg-keys`, `browser-recovery`, and `browser-sync`.
A recorded scope does not automatically skip another decision: source roles
control continuation, so skipping one key still permits subsequent key decisions.

A `retry` action must reload and inspect source state; it never means verified.
A mutating action must verify its result before continuing. Destructive Git
replacement and publication require separate decisions. See
[backup and restore](../../../../../../../docs/usage/backup-and-restore.md)
for the user workflow and recovery limits.
