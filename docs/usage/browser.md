# Browser profiles

Setup installs Brave Stable, makes it the default browser, and recreates profiles
from Bitwarden. It enables **Sync everything**, joins the stored Sync chains, and
verifies synchronization. Backup checks local profiles and offers approved
synchronization; see [before backup](#before-backup).

## Configure recovery

Set the browser and collection in your private override:

```yaml
desktop:
  browser: brave
secrets:
  bitwarden:
    browser_profiles_collection_id: "<your-browser-profiles-collection-uuid>"
```

Follow [configuration](configuration.md) to publish the override. An empty
collection selector creates no managed profiles. A selected collection must be
accessible, nonempty, and contain valid records.

Create one Bitwarden secure note per profile:

| Field                            | Content                                                                   |
| -------------------------------- | ------------------------------------------------------------------------- |
| Name                             | Profile label, such as `Personal`                                         |
| Custom field `id`                | Stable identifier, such as `personal`                                     |
| Custom field `directory`         | Native directory: `Default`, `Profile 1`, etc.                            |
| Notes                            | The profile's stable first 24 Sync recovery words                         |
| Optional `theme_colors`          | One to three comma-separated `#RRGGBB` colors                             |
| Optional `bookmark_bar`          | `always`, `new_tab`, or `never`                                           |
| Optional `confirm_close_tabs`    | `true` to ask before closing multiple tabs; `false` to disable the prompt |
| Optional attachment `avatar.png` | PNG, up to 256 KiB and 1024 × 1024 pixels                                 |

Identifiers use lowercase letters, numbers, and dashes. Keep identifiers and
directories unique. Find an existing profile's directory in `brave://version`, at
the end of **Profile Path**. Keep recovery words and profile definitions out of
Git. Brave supplies a rotating 25th pairing word; do not store it in Bitwarden.

To add a profile, create it in Brave, start a Sync chain, enable **Sync everything**,
and create its note. Keep its name equal to the name shown in Brave's profile
picker. Setup restores the name saved in Bitwarden. To keep a local rename,
update its note or save the change during backup before running setup.

## Restore on another computer

1. Configure the collection, close Brave, and run
   [setup](../../README.md#set-up-or-update-the-workstation) from the managed user's
   desktop session with its system keyring unlocked.
2. Setup restores saved profile settings, joins the stored chains, and waits for
   fresh successful synchronization and matching recovery codes. Resolve any
   reported desktop, vault, policy, or server error and rerun setup.
3. Check bookmarks, extensions, settings, and important tabs in each profile.
   Successful Sync cannot prove that another device saved everything you expected.

Setup reuses an existing matching chain or switches a configured profile to its
stored chain. It preserves unrelated browser data and does not update Bitwarden
recovery words. Recovery closes Brave safely and reopens it if it was running;
private windows cannot be restored. Dry runs do not launch Brave or join chains.

Recovery needs an active desktop and unlocked keyring. Setup over SSH can discover
the managed user's existing GNOME session; log in to the desktop first. Failed
vault downloads are retried; persistent failures stop recovery without marking it
verified. Resolve policies that block Sync with your administrator.

If enrollment reports server throttling, open **Settings → Sync → Manage your
synced devices** on a connected device. Remove only devices you no longer use,
then rerun setup. Discarded VMs can still occupy device slots.

Setup and approved backup synchronization keep **This Device** and remove other
entries with exactly the same device name. Other names are preserved unless
listed in `desktop.browser_sync_disposable_device_names`. Use unique computer
names, and list an extra name only when every remote device with that exact name
can be removed. Deletions require a successful Sync cycle and server acknowledgement;
dry runs never remove devices.

Brave Sync recovery depends on the chain's data remaining available; see the
[Brave Sync FAQ](https://support.brave.app/hc/en-us/articles/360047642371-Sync-FAQ).
Open Tabs Sync does not guarantee a pinned-tab layout. Re-pin important tabs after
recovery; extensions may also need their own settings or sign-in restored.

Setup disables Brave's password-saving and automatic sign-in prompts for managed
profiles. It does not import browser passwords into Bitwarden. Import and verify
them separately before deleting browser copies. Recovery still requires **Sync
everything** when Bitwarden is your password manager.

Browser profiles are outside the default archive. The
[browser backup sidecar](backup-and-restore.md#included-files-and-recovery-limits)
contains bookmarks and sanitized non-secret preferences for manual recovery;
setup does not import it.

## Colors and company logos

For `theme_colors: "#1C3144, #ECB807"`, setup uses the first color as Brave's native
theme seed. Brave derives the interface shades; other colors remain metadata in
Bitwarden. The light/dark choice is preserved. Reset an active theme extension
before applying a native color. If setup reports unfinished theme migration,
open and close the profile once, then retry.

Attach a company logo as `avatar.png` to its note. Setup restores it locally on
each computer. The toolbar uses the logo; the avatar selector still offers stock
icons. Brave updates may affect this feature, and Sync does not carry the image.

Close Brave before applying appearance changes. Interactive setup waits for you
to close it; unattended setup stops. To keep a new appearance, update the note or
save it during backup. Removing an optional color or avatar stops managing it and
preserves the current local appearance.

## Bookmark-bar visibility

Set `bookmark_bar` to `always`, `new_tab`, or `never`, or save the local choice
during backup. Setup applies the choice and verifies it after Sync, reapplying it
if Sync changed it. A policy conflict or failed verification stops recovery.
Omitting the field leaves the choice unmanaged.

## Close-all-tabs confirmation

Set `confirm_close_tabs` to `true` or `false`, or save the local **Warn me before
closing window with multiple tabs** choice during backup. Setup restores and
verifies it. Brave does not carry this preference through native Sync. Omitting
the field leaves it unmanaged.

## Before backup

[Backup](backup-and-restore.md) compares local profile names, directories, main
colors, bookmark-bar and close-tabs choices, logos, and saved Sync configuration
with Bitwarden.

For profile-setting differences, choose `save` to update existing notes from this
computer. This preserves recovery words, unrelated fields, and secondary colors;
it removes disabled logos and managed colors that no longer exist locally.
Backup does not recreate missing profiles or enable **Sync everything**. Run
setup to apply stored profile settings, or fix the reported issue and use `retry`.
A new local profile needs a valid secure note before its recovery can be managed.

After profile settings match, choose `sync`. Backup starts a fresh Sync cycle,
waits for completion without pending changes, and privately checks each stable
recovery code against Bitwarden. If a code differs, it offers:

- `save`: store the local recovery code in its existing note, then verify Sync.
- `restore`: connect the affected profile to the chain stored in Bitwarden, then
  verify Sync. This is also offered for a disconnected profile.
- `retry`: recheck after manual reconciliation.

Each prompt also offers `skip` and `abort`; see
[backup skips](backup-and-restore.md#create-a-backup). Skipped browser recovery is
unverified. Failed operations or verification after an approved change stop backup.
Unsupported native browser interfaces also stop verification.

Brave closes gracefully during approved operations and reopens its saved session
if it was running. Backup does not force it to exit and preserves active or remote
profile locks. It can clear a same-host lock after the recorded process has exited.
If Brave cannot close, resolve the problem and retry, skip browser recovery, or abort.

Non-interactive backup cannot approve live browser verification and does not start
browser automation. Dry runs inspect saved settings without launching Brave or
certifying live recovery.
