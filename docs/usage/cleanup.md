# Cleanup

Preview cleanup, then apply it:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  sh -s -- cleanup --dry-run
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  sh -s -- cleanup
```

Both commands need the private configuration repository and Bitwarden. A selected
browser profile collection must be accessible; see [configuration](configuration.md).
Cleanup validates profile metadata without downloading avatars.

## Changes made

| Area            | Action                                                                                             |
| --------------- | -------------------------------------------------------------------------------------------------- |
| APT             | Simulate a distribution upgrade from cached metadata and remove obsolete package downloads.        |
| Docker          | Prune dangling images and build cache older than seven days, retaining a 10 GB build-cache budget. |
| System journal  | Vacuum archived logs to 14 days and 1024 MB; keep active journal files.                            |
| Installer cache | Remove the cached mise installer from workstation-manager's user state directory.                  |

These limits are fixed. Docker cleanup runs when Docker is installed and preserves
volumes, containers, networks, and tagged images. The cache budget does not promise
retention of every entry below that size. Cleanup never runs APT autoremove,
installs package upgrades, or requests restarts.

Review the APT simulation and reported reboot marker. Run `sudo apt update` and
`sudo apt upgrade` separately when appropriate; package installation can restart
services regardless of the marker. Schedule any required reboot yourself.

## Weekly BleachBit cleanup

Setup enables `workstation-manager-bleachbit-clean.timer` weekly, with up to
30 minutes of randomized delay and catch-up for missed runs. It starts in the
active user session or at the next graphical login.

Select cleaners in the BleachBit GUI. The timer runs `bleachbit --clean --preset`
only when `~/.config/bleachbit/bleachbit.ini` contains enabled cleaners. Setup
preserves those preferences. To run the same cleaner manually:

```sh
workstation-manager-bleachbit-clean
```

## Terminal results

Cleanup prints results without writing a report file. It lists manually installed
APT packages and Flatpaks added since the setup baseline, additional native browser
profiles, and unexpected files in managed configuration and state directories.
These findings are for review; cleanup does not delete them or browser profile data.

Run setup if the package baseline is missing. Docker prune and journal vacuum
failures stop cleanup; check the command output and exit status.

## Preview limits

`--dry-run` reports drift and the APT simulation while skipping package-download
cleanup, Docker pruning, log deletion, and installer removal. Cached metadata can
differ from a later refreshed APT transaction. The preview does not calculate
reclaimed Docker space.

Bootstrap dependency installation, configuration downloads, Bitwarden
authentication, and cache refreshes can still occur.
