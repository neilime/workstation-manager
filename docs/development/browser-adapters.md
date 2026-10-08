# Browser adapters

`desktop.browser` selects a role named
`neilime.workstation_setup.browser_<name>`. Brave is the implemented adapter.
Keep package sources, signing keys, desktop entries, policies, and native profile
formats inside the adapter. User configuration contains the scalar selector:

```yaml
desktop:
  browser: brave
```

Names must match `[a-z][a-z0-9_]*`. Configuration resolution checks the required
task files before running setup, backup, or cleanup; there is no adapter registry.
Changing the selector does not migrate data or uninstall the previous browser.

## Role contract

Add the role under
`ansible/collections/ansible_collections/neilime/workstation_setup/roles/browser_<name>/`:

- `tasks/main.yml`: install the browser, make it the default, keep Sync
  available, and create declared profiles while preserving existing data.
  Publish `workstation_manager_browser_desktop_file`.
- `tasks/backup.yml`: inspect profiles without mutation. Publish
  `workstation_backup_browser_inspection` with `profiles`, `drift`, and
  `sync_issues` for metadata and policy checks. The live entrypoint owns chain
  enrollment diagnostics. Publish `workstation_backup_browser_recovery_report` as a short
  text report grouping detected issues by action, with affected profile names and
  directories. Keep vendor-specific instructions in the adapter. Publish
  `workstation_backup_browser_sync_instructions` for the later live verification,
  naming the inspected profiles and explaining the automatic operation. Publish
  `workstation_backup_browser_user_data_dir` so backup can emit its browser-only
  sidecar export without changing setup restore.
- `tasks/reconcile.yml`: apply the explicitly selected `save` or
  `restore` choice in `workstation_backup_recovery_choices['browser-recovery']`,
  guard previews, and verify the changed metadata. Publish supported direction
  descriptions in `workstation_backup_browser_sync_actions` during inspection.
  New recovery-note creation requires a declared profile record. A closed-browser
  precondition detected before any mutation can use the shared recovery decision
  role for retry/skip/abort under `browser-recovery`. Retry returns to inspection
  and a fresh direction choice; never reuse an earlier approval. Actual operation
  and verification failures must still fail.
- `tasks/sync.yml`: execute the explicit `sync`, `save`, or `restore` action in
  `workstation_backup_recovery_choices['browser-sync']`. Publish
  `workstation_backup_browser_live_verified` only after fresh native Sync and
  matching recovery codes are verified. Publish a sanitized shared decision
  request in `workstation_backup_browser_live_request` for remaining problems.
  Never use a user's assertion as verification or launch the browser in previews.
- `tasks/inspect_profiles.yml`: report undeclared profile paths in
  `workstation_manager_cleanup_unmanaged_browser_profile_directories`, or `[]`.
  Never delete profiles.

Setup invokes `main.yml` after archive restoration and before GNOME preferences
and editor sign-in. The special `browser` favorite resolves to the published
desktop entry. Backup uses the shared recovery decision role for
direction choices, retry/skip/abort, and automatic live Sync verification. It reloads and
inspects profiles after an approved action or retry. Cleanup invokes only the inspection entrypoint.

Use `workstation_manager_resolved.user` for the target account and
`workstation_manager_use_become` for privilege escalation. Namespace internal
variables to the adapter role. Put reusable Python logic in `plugins/module_utils/`
and expose it through thin modules or filters.

## Profile input

Use `neilime.workstation_setup.browser_profile_collection` to load
`workstation_manager_browser_profiles`. The loader authenticates Bitwarden as the
resolved user with `HOME` and `XDG_CONFIG_HOME` pointing to that account. Use the
same user and environment for avatar downloads and browser synchronization so
session tokens refer to the same CLI account cache. Setup adapters and backup orchestration
use its default entrypoint, which also downloads avatar attachments into memory.
Failed avatar downloads are retried up to three times with a five-second delay.
If recovery remains incomplete, the loader stops with an error that excludes
attachment contents and CLI output.
Cleanup loads `tasks_from: metadata` before calling the inspection entrypoint;
profile-directory drift does not require avatar images.

The loader reads `secrets.bitwarden.browser_profiles_collection_id`. An empty
selector produces `[]`; a configured collection must be accessible and nonempty.
See the [user record schema](../usage/browser.md#configure-recovery).

| Metadata key           | Meaning                                             |
| ---------------------- | --------------------------------------------------- |
| `id`                   | Stable profile identifier                           |
| `label`                | Bitwarden note name                                 |
| `directory`            | Native profile directory basename                   |
| `item_id`              | Bitwarden note UUID                                 |
| `theme_colors`         | Optional list of one to three normalized hex colors |
| `avatar_attachment_id` | Optional attachment identifier                      |
| `avatar_png`           | Optional base64 PNG, loaded into memory             |

Recovery words are validated as present but are not exposed in this inventory.
The canonical vault record stores only the stable first 24 words. If a copied
25-word pairing code is present, the native adapter ignores the rotating 25th
word and compares only the stable recovery code privately against the active
Sync chain.
Mark image module arguments and tasks handling full records `no_log`. Reports
must contain only selected metadata and drift details, never notes or image data.

## Brave implementation

The [Brave role](../../ansible/collections/ansible_collections/neilime/workstation_setup/roles/browser_brave)
uses `~/.config/BraveSoftware/Brave-Browser` under the resolved user's home. Its
managed policy permits Sync; it cannot enroll profiles. Seeding creates missing
profiles and applies declared colors and avatars while preserving existing
names and other preferences. Explicit `restore` reconciliation also replaces
profile names and enables Sync everything for managed profiles; `save` updates
existing vault metadata and avatars without changing recovery words. Approved
operations close the managed user's matching Brave instance with a graceful
exit request, preserve session tabs, and reopen it afterward if it was running.
Locks are never removed and processes are never force-killed. Setup restores
profile metadata, enables Sync everything, joins the stored chains, and requires
verified live synchronization. Preview runs do not launch Brave.

Live verification uses Brave's native WebUI APIs through inherited anonymous
DevTools pipes. It opens no debugging port and does not copy profiles, bypass
browser policies, disable the sandbox, or change password-storage backends.
Only the selected profile's native code reaches the vault helper, in memory.
Settings requests use the page's existing native callbacks, preserving its own
responses and listeners. Importing a separate `cr.js` into the bundled settings
page would initialize Chromium's WebUI callbacks twice and fail.
Diagnostic node contents are reduced inside Brave to boolean status; browsing
data never reaches an Ansible result. Child environments exclude vault credentials.
Native automation errors identify the failed operation without including scripts,
arguments, recovery words, or raw browser errors.
Browser automation uses a desktop-session query that reads the managed user's live
systemd environment. GNOME's initial `/proc` environment lacks the display variables
created later by Wayland. Only allowed desktop variables reach application children;
raw session-manager output is never returned in task results.
The backup-only browser export sidecar is separate: it carries local bookmarks
and sanitized non-secret preferences, and setup does not replay it automatically.

Verification requires a new successful GetUpdates response after requesting a
refresh, healthy Sync diagnostics, and two observations without unacknowledged
entity sequences or pending tombstones. Required browser data types must be
running. Stale success, errors, incomplete diagnostics, and timeouts cannot
certify recovery. `save` updates only an existing note's code and verifies the
readback. `restore` uses Brave's native leave/join handlers and current pairing
suffix, enables Sync everything, and verifies the resulting chain.

The native interfaces follow
[Brave's Sync handler](https://github.com/brave/brave-core/blob/master/browser/ui/webui/settings/brave_sync_handler.cc)
and [Chromium's Sync diagnostics](https://github.com/chromium/chromium/blob/main/components/sync/service/sync_internals_util.cc).
API changes fail closed. Saved preferences alone never prove server upload.
Call-site Ansible Pylint exceptions allow the retained CDP process and detached
desktop restart, which outlive a synchronous command, and the session query's
sanitized child environment.

## Validation

Follow the [development checks](README.md). Cover configuration selection,
idempotent profile creation, preservation of existing data, check mode, invalid
input, sensitive-data redaction, and read-only drift inspection. For native
profile writes, test running-browser and symlink protections. Exercise actual
installation and restore behavior in the test VM, not on the developer's host.

The end-to-end setup assertions run the isolated native smoke test through SSH. To run it
directly in the Lima VM after installing Brave:

```sh
limactl shell --workdir /workspace workstation-manager-v1 -- \
  python3 /workspace/e2e-tests/browser_sync_smoke.py
```

It uses a disposable profile and a disabled Sync endpoint. It exercises real
native code access, private IPC, profile identity, tab preservation, callback
routing, and production diagnostic JavaScript with synthetic success, error,
stale, upload, and deletion states. It does not certify connectivity to the public
Sync service.
