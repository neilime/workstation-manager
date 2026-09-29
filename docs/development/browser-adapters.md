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
  `sync_issues`. Publish `workstation_backup_browser_recovery_report` as a short
  text report grouping detected issues by action, with affected profile names and
  directories. Keep vendor-specific instructions in the adapter. Publish
  `workstation_backup_browser_sync_instructions` for the later live verification.
- `tasks/inspect_profiles.yml`: report undeclared profile paths in
  `workstation_manager_cleanup_unmanaged_browser_profile_directories`, or `[]`.
  Never delete profiles.

Setup invokes `main.yml` after archive restoration and before GNOME preferences
and editor sign-in. The special `browser` favorite resolves to the published
desktop entry. Backup owns retry/skip/abort prompts and the final live Sync
confirmation. Cleanup invokes only the inspection entrypoint.

Use `workstation_manager_resolved.user` for the target account and
`workstation_manager_use_become` for privilege escalation. Namespace internal
variables to the adapter role. Put reusable Python logic in `plugins/module_utils/`
and expose it through thin modules or filters.

## Profile input

Use `neilime.workstation_setup.browser_profile_collection` to load
`workstation_manager_browser_profiles`. Setup adapters and backup orchestration
use its default entrypoint, which also downloads avatar attachments into memory.
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
Their correspondence with the active Sync chain requires user verification.
Mark image module arguments and tasks handling full records `no_log`. Reports
must contain only selected metadata and drift details, never notes or image data.

## Brave implementation

The [Brave role](../../ansible/collections/ansible_collections/neilime/workstation_setup/roles/browser_brave)
uses `~/.config/BraveSoftware/Brave-Browser` under the resolved user's home. Its
managed policy permits Sync; it cannot enroll profiles. Seeding creates missing
profiles and applies declared colors and avatars while preserving existing
names and other preferences. It refuses changes while Brave is running.

Backup checks local inventory and Sync settings, including **Sync everything**.
Saved preferences are insufficient evidence of a completed server upload. Custom
logos use internal local profile-picture fields and are restored from Bitwarden.
Keep these limitations explicit in [user instructions](../usage/browser.md).

## Validation

Follow the [development checks](README.md). Cover configuration selection,
idempotent profile creation, preservation of existing data, check mode, invalid
input, sensitive-data redaction, and read-only drift inspection. For native
profile writes, test running-browser and symlink protections. Exercise actual
installation and restore behavior in the test VM, not on the developer's host.
