# Browser adapters

`desktop.browser` selects `neilime.workstation_setup.browser_<name>`; Brave is the
implemented adapter. Names must match `[a-z][a-z0-9_]*`.
[Configuration resolution](../../ansible/tasks/resolve_workstation_config.yml)
checks the required task files before setup, backup, or cleanup. Keep vendor
packages, policies and native formats inside the adapter. Changing the selector
does not migrate profiles or uninstall another browser.

See [browser profiles](../usage/browser.md) for user configuration and recovery.

## Role contract

Add `browser_<name>` under the setup collection's `roles/` directory with these
entrypoints:

| Task file              | Responsibility                                                                                                                                                  |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `main.yml`             | Install the browser, select it as default, permit Sync, and create declared profiles while preserving data. Publish `workstation_manager_browser_desktop_file`. |
| `backup.yml`           | Inspect metadata and policy drift without mutation. Publish the inspection and recovery instructions listed below.                                              |
| `reconcile.yml`        | Apply the explicit `save` or `restore` choice in `workstation_backup_recovery_choices['browser-recovery']` and verify the result.                               |
| `sync.yml`             | Apply the explicit `sync`, `save`, or `restore` choice in `workstation_backup_recovery_choices['browser-sync']` and verify live recovery.                       |
| `inspect_profiles.yml` | Publish undeclared paths in `workstation_manager_cleanup_unmanaged_browser_profile_directories`, or `[]`. Never delete profiles.                                |

`backup.yml` publishes:

- `workstation_backup_browser_inspection`: `profiles`, `drift`, and `sync_issues`
  for metadata and policy checks. Live enrollment diagnostics belong to `sync.yml`.
- `workstation_backup_browser_recovery_report`: issues grouped by action, with
  affected profile names and directories.
- `workstation_backup_browser_sync_instructions`: inspected profiles and the
  automatic live verification to follow.
- `workstation_backup_browser_sync_actions`: supported reconciliation directions.
- `workstation_backup_browser_user_data_dir`: source for the browser export sidecar.

`sync.yml` publishes `workstation_backup_browser_live_verified` only after fresh
native Sync and matching recovery codes pass verification. Remaining problems go
in a sanitized `workstation_backup_browser_live_request` for the shared
[recovery decision role](automation.md#recovery-decisions). Never accept a user's
assertion as verification or launch the browser in previews.

Reconciliation requires a declared profile before creating a recovery note.
A closed-browser precondition detected before mutation may offer retry/skip/abort.
Retry reloads state and asks for a fresh direction; operation and verification
failures still fail. Setup prompts to close a running browser and retries in an
interactive session; unattended runs stop with that instruction.

Setup runs the adapter after archive restoration and before GNOME preferences
and editor sign-in. The `browser` favorite uses its published desktop entry.
Backup reloads and inspects profiles after approved actions or retries. Cleanup
calls only `inspect_profiles.yml`.

Use `workstation_manager_resolved.user` and `workstation_manager_use_become` for
the managed account. Namespace adapter variables, keep reusable Python in
`plugins/module_utils/`, and expose thin modules or filters.

## Profile input

Use `neilime.workstation_setup.browser_profile_collection` to populate
`workstation_manager_browser_profiles`. It reads
`secrets.bitwarden.browser_profiles_collection_id`; an empty selector produces
`[]`, while a configured collection must be accessible and nonempty.
See the [vault record schema](../usage/browser.md#configure-recovery).

The default entrypoint loads metadata and avatar attachments into memory.
Cleanup uses `tasks_from: metadata` because drift inspection needs no images.
Run collection loading, avatar downloads, and live recovery as the same resolved
user with its `HOME` and `XDG_CONFIG_HOME`, so they share the CLI account cache.

| Metadata key           | Meaning                                             |
| ---------------------- | --------------------------------------------------- |
| `id`                   | Stable profile identifier                           |
| `label`                | Bitwarden note name                                 |
| `directory`            | Native profile directory basename                   |
| `item_id`              | Bitwarden note UUID                                 |
| `theme_colors`         | Optional list of one to three normalized hex colors |
| `avatar_attachment_id` | Optional attachment identifier                      |
| `avatar_png`           | Optional base64 PNG held in memory                  |
| `bookmark_bar`         | Optional `always`, `new_tab`, or `never` visibility |
| `confirm_close_tabs`   | Optional boolean close-all-tabs confirmation        |

Recovery words are required but excluded from this inventory. The vault stores
24 stable words; a supplied rotating 25th pairing word is excluded from private
chain comparisons. Mark full records and image arguments `no_log`. Reports may
contain selected metadata and drift, never notes, image data or CLI output.

Live recovery refreshes the vault before reading records and before accepting
code verification. Download failures have bounded retries; exhausted retries
stop recovery. Cached records cannot certify recovery, and vault writes are not
retried. Errors identify the operation and status without record contents.

## Brave implementation

The [Brave role][brave-role] manages
`~/.config/BraveSoftware/Brave-Browser` under the resolved home. Its policy permits
Sync; enrollment requires native browser operations.

Profile seeding preserves existing names and unspecified preferences. `restore`
replaces declared metadata, enables Sync everything, joins stored chains, and
requires live verification. Metadata `save` updates vault fields and avatars
without changing recovery words; the separate live Sync action can save a code
into an existing note and verify its readback. Backup's browser export sidecar
contains local bookmarks and sanitized preferences; setup does not replay it.

Preserve these implementation contracts:

- Close only the managed user's matching browser through graceful shutdown,
  preserve tabs, and reopen it if previously running. Preserve active and remote
  profile locks; remove a stale local lock only after its recorded process exits.
  Never force-kill processes.
- Apply only declared profile preferences. Inspect explicit unsaved choices as
  drift without inventing restore values. Verify bookmark-bar settings through
  native readback after Sync; setup may reapply them and verify another cycle,
  while backup does not repair local choices. Verify the local
  `brave.enable_window_closing_confirm` preference independently of Sync.
- Use native WebUI APIs over inherited anonymous DevTools pipes. Preserve the
  browser sandbox, policy and password backend; open no debugging port. Keep
  recovery words in memory and vault credentials out of browser environments.
- Await the internal page, its native profile-path response, and an exact profile
  match before accessing Sync. Use the settings page's existing callbacks and
  canonical `chrome://` module URLs. Await OS encryption readiness and stop on
  decryption failure without replacing the chain.
- Read allowed desktop variables from the managed user's live systemd session.
  Keep raw session output and arbitrary browser errors out of task results.

The [native Sync helper][native-sync] owns enrollment and recovery;
[profile synchronization][profile-sync] owns metadata reconciliation.

### Verification and device removal

Verification requires a fresh successful GetUpdates response, healthy native
Sync diagnostics, required data types running, and two observations without
unacknowledged entity sequences or pending tombstones. Stale success, partial
responses, errors, and timeouts remain unverified. An existing matching seed must
not be rejoined even when saved transport flags indicate incomplete setup.

After verification, duplicate cleanup targets exact matches of the current device
name or `desktop.browser_sync_disposable_device_names`. Protect the unambiguous
current device GUID, recheck identities before mutation, and preserve unrelated
devices. Each deletion requires a fresh successful server commit for its client
tag and a device-list readback; a native callback alone is insufficient.

The observer is shared with [VM teardown](e2e-tests.md#teardown-and-reuse).
Keep it installed across diagnostic navigation and delayed acknowledgement events.
Each observation must obtain fresh status and counts for every running data type
within one deadline. Replaced status or lost page state invalidates the
observation; late replies cannot complete it. Explicit native rejections and
broken automation connections fail recovery.

Reduce diagnostics inside the browser to booleans, numeric metrics and
allowlisted error categories. Never return entity contents, scripts, recovery
words or arbitrary native error messages. Upstream API changes fail closed;
saved preferences alone cannot prove server upload. Throttled enrollment points
to the [device-limit recovery procedure](../usage/browser.md#restore-on-another-computer).

## Validation

Follow the [development checks](README.md). Cover selection, idempotence,
existing-data preservation, check mode, invalid input, redaction, and read-only
drift inspection. Native profile writes need running-browser and symlink checks.
Exercise installation and restore behavior in the test VM.

The setup assertions run this native smoke test through SSH. To run it directly
after installing Brave in the VM:

```sh
limactl shell --workdir /workspace workstation-manager-v1 -- \
  python3 /workspace/e2e-tests/browser_sync_smoke.py
```

Replace the VM name if using a custom `VM_NAME`. The test uses a disposable
profile and disabled Sync endpoint. It exercises native code access, private IPC,
profile identity, tab preservation, callbacks, and production diagnostic
JavaScript with synthetic success, failure, stale, upload, deletion and delayed
response states. It does not certify public Sync connectivity; the
[full VM flow](e2e-tests.md#run-the-flow) checks live recovery.

[brave-role]: ../../ansible/collections/ansible_collections/neilime/workstation_setup/roles/browser_brave
[native-sync]: ../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/module_utils/browser_native_sync.py
[profile-sync]: ../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/module_utils/browser_profile_sync.py
