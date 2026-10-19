# Browser profiles

Setup installs Brave Stable, makes it the default browser, and recreates profiles
from Bitwarden. Setup enables **Sync everything**, joins each configured profile
to its stored Brave Sync chain, and waits for verified synchronization.
Browser recovery during backup can connect profiles to their stored chains and
verify synchronization automatically. Setup sets HTTP, HTTPS, and HTML defaults
for the managed user, including Ubuntu and GNOME desktop-specific associations.

Setup and approved backup synchronization keep **This Device** and remove other
Sync entries with exactly the same device name. Differently named devices are
preserved by default. You can explicitly remove additional device names through
`desktop.browser_sync_disposable_device_names` in your private override; its
[public default](../../ansible/group_vars/all.yml) is an empty list.
Cleanup requires a successful Sync cycle, server acknowledgement for every
deletion, and a checked device list. Dry runs never remove devices.

Use unique computer names within a Sync chain: same-name entries are treated as
duplicates. List an additional name as disposable only when all remote devices
with that exact name can be removed.

For each managed profile, setup also keeps Brave's built-in "Offer to save
passwords" and "Auto Sign-in" prompts off so the Bitwarden extension stays the
effective password manager. Brave's own default-password-manager toggle does not
persist per profile, so setup enforces this on every run.

## Configure recovery

Set the browser and collection in your private
`workstation-config/ansible/private.override.yml`:

```yaml
desktop:
  browser: brave
secrets:
  bitwarden:
    browser_profiles_collection_id: "<your-browser-profiles-collection-uuid>"
```

See [configuration](configuration.md) for the private override workflow. An empty
collection selector creates no managed profiles. A selected collection must be
accessible, nonempty, and contain valid profile records.

Create one Bitwarden secure note per profile in that collection:

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

Identifiers use lowercase letters, numbers, and dashes. Keep both identifiers
and directories unique. For an existing profile, open `brave://version` and use
the last directory in **Profile Path**. Do not store recovery words or individual
profile definitions in Git. Brave also shows a 25th pairing word when joining a
device; that word rotates and is not stored in Bitwarden.

To add a profile, create it in Brave, start its own Sync chain, enable **Sync
everything**, then create its secure note. Keep the note's name equal to the
profile name. Setup preserves existing profile names; change a name in both Brave
and Bitwarden when renaming a profile.

## Restore on another computer

1. Configure the collection, close Brave completely, and run
   [setup](../../README.md#set-up-or-update-the-workstation) from the managed user's
   desktop session with its system keyring unlocked. Setup creates the profiles,
   restores their saved settings, enables **Sync everything**, and joins their
   stored chains using recovery words read privately from Bitwarden.
2. Setup waits for fresh successful synchronization and matching recovery codes.
   If a profile cannot synchronize, setup stops; resolve the reported desktop,
   policy, vault, or server problem and rerun setup.
3. Check bookmarks, extensions, settings, and important tabs in each profile.
   Successful synchronization cannot prove that every file or setting you expected
   was saved by another device.

Setup reuses an existing matching chain without enrolling the device again. It
can switch an existing configured profile to its stored chain. It preserves
unrelated browser data and does not update Bitwarden recovery words. Brave closes
safely for recovery and reopens if it was running. Dry runs preview recovery
without launching Brave or joining chains.

Recovery retries failed Bitwarden vault downloads automatically. If they still
fail, setup or backup stops without marking browser recovery verified. Check
network and vault access before rerunning the command.

If enrollment reports server throttling, check **Settings → Sync → Manage your
synced devices** from a profile already connected to that chain. Brave limits the
number of connected devices. Remove only devices you no longer use, then rerun
setup. Old disposable test VMs also occupy device slots until they leave the chain.

Brave Sync uses a chain code independently of Google site accounts. Server
data expires after 12 months without access; recovery words cannot recover data
that has expired or been deleted. See the
[Brave Sync FAQ](https://support.brave.app/hc/en-us/articles/360047642371-Sync-FAQ).

Open Tabs Sync does not promise restoration of a pinned-tab layout. Check and
re-pin important tabs after recovery; a bookmark folder is useful for frequently
used sites. Extensions may need their own settings or sign-in restored. Browser
profiles are not included in the default workstation archive. Backup writes a
separate `*.browser-profiles.json` sidecar with bookmarks and sanitized non-secret
preferences, but setup does not restore it automatically.

Browser passwords are not imported into Bitwarden by setup. Import and verify
them separately before deleting any browser copies. The current recovery check
requires **Sync everything**, including when Bitwarden is your password manager.

## Colors and company logos

For a palette such as `#1C3144, #ECB807`, setup applies the first color as Brave's
native theme seed. Brave derives the interface shades; additional colors remain
in Bitwarden as metadata. The light/dark choice is preserved. Reset an active
theme extension before applying a native color. If setup reports unfinished
theme migration, open and close the profile once, then retry.

Attach a company logo as `avatar.png` to its profile note. Setup restores the logo
locally on each computer. This uses internal Brave profile-picture fields: the
logo appears in the toolbar, while the avatar selector still offers stock icons.
Browser updates may affect it, and the image file is not carried by Brave Sync.

Close Brave before running setup to apply colors or logos. If Brave is still
running, interactive setup pauses and asks you to close it, then retries
automatically; a non-interactive run stops with the same instruction. To keep an
intentional change, update `theme_colors` or replace `avatar.png` in Bitwarden.
Removing either optional value stops managing it and leaves the existing local
appearance intact.

## Bookmark-bar visibility

Backup offers to save each profile's explicit bookmark-bar choice in its
Bitwarden note. Run backup on the computer with the intended setting and choose
`save` for the listed profiles. You can also set the note's `bookmark_bar` custom
field to `always`, `new_tab`, or `never`.

Setup applies that saved choice to the corresponding profile and verifies it
after Brave Sync finishes. If Sync changes it, setup reapplies the choice through
Brave, waits for synchronization, and checks it again. A policy conflict or failed
verification stops recovery. Profiles without this field retain their own choice;
setup does not force the bookmark bar on every profile. Dry runs change nothing.

## Close-all-tabs confirmation

Backup also offers to save each profile's explicit **Warn me before closing
window with multiple tabs** choice. Choose `save` on the original computer, or
set the profile note's `confirm_close_tabs` custom field to `true` or `false`.
Setup restores and verifies the saved choice on the destination profile. Both
enabled and disabled choices are preserved; omitting the field leaves it unmanaged
by setup. Dry runs leave the local preference and Bitwarden unchanged.

Brave stores this confirmation locally rather than registering it for native
Sync, so the Bitwarden field carries the choice between computers.

## Before backup

[Backup](backup-and-restore.md) compares local profiles with the collection,
including names, directories, declared main colors, bookmark-bar and close-tabs choices, logos, and saved Sync
configuration. Name checks use the names shown in Brave's profile picker.
The prompt names affected profiles and offers machine actions:

- `save` updates existing Bitwarden records from local names, colors, bookmark-bar and close-tabs choices, and logos.
  It preserves recovery words, unrelated fields, and secondary palette colors.
  Disabled logos and managed colors that no longer exist locally are removed
  from the corresponding note.

Backup does not apply saved settings locally, recreate missing profiles, or enable
**Sync everything**; run setup to restore those from Bitwarden. Use `retry` to
recheck after you fix a manual step such as enabling Sync everything.

Brave closes gracefully during approved operations and reopens its previous
saved session if it was running; private windows cannot be restored. Backup never
forces a process to exit or removes a profile lock. If Brave cannot close, `retry` tries again; `skip` records incomplete
browser recovery, and `abort` stops without an archive.

After profile settings match, choose `sync`. The script opens each managed
profile, starts a fresh Sync cycle, waits for successful synchronization without
pending changes, and compares its stable recovery code with Bitwarden. You do
not need to inspect diagnostic pages or compare words. Codes stay private.

If recovery codes differ, choose `save` to store the current Brave code in its
existing note. Backup verifies synchronization and matching codes afterward and
never deletes profiles or vault records. To connect a profile to a stored chain or
enable **Sync everything**, run setup; backup does not pull a chain onto this computer.

If Sync remains pending or the server is unavailable, choose `sync` to try again,
`skip` to continue with browser recovery unverified, or `abort`. A failed operation
or failed verification after saving stops backup. Unsupported native
browser interfaces also stop verification rather than accepting a manual assertion.
See [backup skips](backup-and-restore.md#create-a-backup) for incomplete coverage.
When profiles exist locally, backup also writes the sidecar noted above for manual
inspection or manual recovery of bookmarks and non-secret preferences.

Automatic verification requires Brave and access to the managed user's desktop
session and unlocked system keyring. Setup launched through SSH discovers that
user's existing GNOME session; log in to the desktop first. If no display is
available, recovery stops with a desktop-session error before launching Brave.
A new local profile still needs a secure note
in the configured collection before its recovery can be managed. Policies that
block Sync must be resolved by the administrator. Noninteractive setup also requires access to the managed desktop and unlocked
keyring. Noninteractive backup requires explicit recovery decisions and does not
start browser automation. Dry runs inspect
saved settings without launching Brave or certifying live recovery.
