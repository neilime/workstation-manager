# Browser profiles

Setup installs Brave Stable, makes it the default browser, and recreates profiles
from Bitwarden. Each profile uses its own Brave Sync chain for browsing data.
Browser recovery during backup can connect profiles to their stored chains and
verify synchronization automatically.

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

| Field                            | Content                                           |
| -------------------------------- | ------------------------------------------------- |
| Name                             | Profile label, such as `Personal`                 |
| Custom field `id`                | Stable identifier, such as `personal`             |
| Custom field `directory`         | Native directory: `Default`, `Profile 1`, etc.    |
| Notes                            | The profile's stable first 24 Sync recovery words |
| Optional `theme_colors`          | One to three comma-separated `#RRGGBB` colors     |
| Optional attachment `avatar.png` | PNG, up to 256 KiB and 1024 × 1024 pixels         |

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
   [setup](../../README.md#set-up-or-update-the-workstation). Setup creates the
   profiles and applies any stored colors and logos.
2. Open each profile and go to `brave://settings/braveSync`.
3. Join that profile's existing chain using its 24 stored Bitwarden recovery
   words. Append Brave's current rotating 25th word as described in
   [Brave's Sync setup guide](https://support.brave.app/hc/en-us/articles/360021218111-How-do-I-set-up-Sync).
   Another connected computer can also display a fresh pairing code.
4. Enable **Sync everything** and wait for synchronization. Check bookmarks,
   extensions, and important tabs before relying on the restored profile.
5. Open `brave://sync-internals` and verify successful synchronization without
   pending changes or errors.

You can also run backup after setup and choose the browser `sync` action, then
`restore` when it reports profiles that need their stored chain. The script joins
those chains, enables Sync everything, and verifies recovery automatically.

Brave Sync uses a chain code independently of Google site accounts. Server
data expires after 12 months without access; recovery words cannot recover data
that has expired or been deleted. See the
[Brave Sync FAQ](https://support.brave.app/hc/en-us/articles/360047642371-Sync-FAQ).

Open Tabs Sync does not promise restoration of a pinned-tab layout. Check and
re-pin important tabs after recovery; a bookmark folder is useful for frequently
used sites. Extensions may need their own settings or sign-in restored. Browser
profiles are not included in the default workstation archive.

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

Close Brave before running setup to apply colors or logos. To keep an intentional
change, update `theme_colors` or replace `avatar.png` in Bitwarden. Removing either
optional value stops managing it and leaves the existing local appearance intact.

## Before backup

[Backup](backup-and-restore.md) compares local profiles with the collection,
including names, directories, declared main colors, logos, and saved Sync
configuration. Name checks use the names shown in Brave's profile picker.
The prompt names affected profiles and offers machine actions:

- `restore` applies saved names, colors, and logos locally, recreates missing
  profiles, and enables **Sync everything**.
- `save` updates existing Bitwarden records from local names, colors, and logos.
  It preserves recovery words, unrelated fields, and secondary palette colors.
  Disabled logos and managed colors that no longer exist locally are removed
  from the corresponding note.

Brave closes gracefully during approved operations and reopens its previous
saved session if it was running; private windows cannot be restored. Backup never
forces a process to exit or removes a profile lock. If Brave cannot close, `retry` tries again; `skip` records incomplete
browser recovery, and `abort` stops without an archive.

After profile settings match, choose `sync`. The script opens each managed
profile, starts a fresh Sync cycle, waits for successful synchronization without
pending changes, and compares its stable recovery code with Bitwarden. You do
not need to inspect diagnostic pages or compare words. Codes stay private.

If recovery codes differ, choose `save` to store the current Brave code in its
existing note, or `restore` to connect the affected profile to its stored chain.
Restoring a chain enables **Sync everything** and can merge local browsing data
with that chain. Both actions verify synchronization and matching codes afterward.
Neither direction deletes profiles or vault records.

If Sync remains pending or the server is unavailable, choose `sync` to try again,
`skip` to continue with browser recovery unverified, or `abort`. A failed operation
or failed verification after saving or restoring stops backup. Unsupported native
browser interfaces also stop verification rather than accepting a manual assertion.
See [backup skips](backup-and-restore.md#create-a-backup) for incomplete coverage.

Automatic verification requires Brave and access to the managed user's desktop
session and unlocked system keyring. A new local profile still needs a secure note
in the configured collection before its recovery can be managed. Policies that
block Sync must be resolved by the administrator. Noninteractive runs require
explicit recovery decisions and do not start browser automation. Dry runs inspect
saved settings without launching Brave or certifying live recovery.
