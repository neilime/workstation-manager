# Browser profiles

Setup installs Brave Stable, makes it the default browser, and recreates profiles
from Bitwarden. Each profile uses its own Brave Sync chain for browsing data.
Joining that chain is a manual step on each computer.

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
profile definitions in Git.

To add a profile, create it in Brave, start its own Sync chain, enable **Sync
everything**, then create its secure note. Keep the note's name equal to the
profile name. Setup preserves existing profile names; change a name in both Brave
and Bitwarden when renaming a profile.

## Restore on another computer

1. Configure the collection, close Brave completely, and run
   [setup](../../README.md#set-up-or-update-the-workstation). Setup creates the
   profiles and applies any stored colors and logos.
2. Open each profile and go to `brave://settings/braveSync`.
3. Join that profile's existing chain using its Bitwarden recovery words. Append
   the current rotating 25th word as described in
   [Brave's Sync setup guide](https://support.brave.app/hc/en-us/articles/360021218111-How-do-I-set-up-Sync).
   Another connected computer can also display a fresh pairing code.
4. Enable **Sync everything** and wait for synchronization. Check bookmarks,
   extensions, and important tabs before relying on the restored profile.
5. Open `brave://sync-internals` and verify successful synchronization without
   pending changes or errors.

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
The prompt groups detected problems and names the affected profiles. Close Brave,
then choose the source for supported metadata changes:

- `restore` restores stored names, colors, and logos locally and recreates
  missing profiles. Other preferences, browsing data, and existing Sync chains
  are preserved.
- `save` updates existing Bitwarden records from local names, colors, and
  logos. It preserves recovery words, unrelated fields, and secondary palette
  colors. An absent or disabled managed logo is removed from its note; a local
  default or extension theme removes the managed `theme_colors` field.

Each direction verifies the changes it makes. The available choices depend on
which side has usable data. Neither direction deletes profiles or vault records.
A new local profile still needs a secure note containing its recovery words;
create that note in Bitwarden. Pairing a restored profile and enabling Sync still
happen in Brave. Choose `retry` after those manual steps to reload both sides.
Cleanup preserves all browser profiles.

After these checks, backup asks you to confirm that every profile has completed
live Sync and its first 24 recovery words match its Bitwarden note. Verify this
in Brave before answering `synced`; the tool cannot prove a server upload or
compare the words automatically. Noninteractive backups with browser profiles
stop at this requirement. In an interactive backup, `skip` leaves browser recovery
unverified and records incomplete coverage; see [backup skips](backup-and-restore.md#create-a-backup).
A dry run reports checks without certifying recovery.
