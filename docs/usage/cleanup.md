# Cleanup

Cleanup reclaims old disposable caches and archived logs, and reports package
drift and pending updates. Routine cleanup preserves Docker containers, networks,
tagged images, and volumes. APT upgrades and service restarts are separate manual
operations.

## Run cleanup

Preview cleanup and configuration drift first:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  sh -s -- cleanup --dry-run
```

Apply cleanup:

```sh
wget -qO- https://raw.githubusercontent.com/neilime/workstation-manager/main/workstation.sh | \
  sh -s -- cleanup
```

Both commands require access to the private configuration repository and
Bitwarden. A configured browser profile collection must be accessible before
cleanup proceeds; see [configuration](configuration.md). Cleanup validates the
profile metadata without downloading avatar attachments.

## Changes made

| Area            | Action                                                                                                                 |
| --------------- | ---------------------------------------------------------------------------------------------------------------------- |
| APT             | Simulate a distribution upgrade using cached metadata, report the reboot marker, and clean obsolete package downloads. |
| Docker          | Prune dangling images and build cache older than seven days, with a 10 GB retained build-cache budget.                 |
| System journal  | Vacuum archived logs to 14 days and 1024 MB. Active journal files remain.                                              |
| Installer cache | Remove the cached mise installer from workstation-manager's user state directory.                                      |

These limits are fixed workstation behavior. Docker cleanup runs when Docker is
installed; it preserves volumes, containers, networks, and tagged images. The
10 GB budget controls retained build cache; it does not guarantee indefinite
retention of every cache entry below that size. Cleanup never runs APT autoremove.

Review the reported APT transaction, then run `sudo apt update` and
`sudo apt upgrade` separately at a suitable time. Package installation can restart
services regardless of the reboot marker. Schedule any required reboot yourself;
cleanup never upgrades packages or requests restarts.

## Weekly BleachBit cleanup

Setup enables the user timer `workstation-manager-bleachbit-clean.timer` to run
weekly, with up to 30 minutes of randomized delay. Missed runs are caught up
when the timer starts again. Setup starts it in an active user session; the
graphical login hook activates it when setup runs without a session.

The same cleaner remains available manually:

```sh
workstation-manager-bleachbit-clean
```

It runs `bleachbit --clean --preset` only when
`~/.config/bleachbit/bleachbit.ini` contains enabled cleaners. Select the cleaners
in the BleachBit GUI before running it.

Weekly scheduling is fixed behavior and requires no configuration switch.
Setup preserves saved cleaner preferences.

## Terminal results

Cleanup prints results in the terminal and does not write a report file. It lists
manually installed APT packages and Flatpak apps added since the last
setup baseline, additional native browser profiles, and unexpected files in the
managed configuration and state directories. These findings are reported for
review; cleanup does not remove them. Browser profiles and their internal data
are preserved.

If the package baseline is missing, run setup before relying on package drift
results. Docker prune and journal vacuum failures stop cleanup; check the command
output and exit status.

## Preview limits

`--dry-run` reports drift and the APT simulation while skipping download cleanup,
Docker pruning, log deletion, and installer removal. The simulation uses cached
APT metadata, so a later metadata refresh can change the transaction. The preview
does not calculate reclaimed Docker space.

The entrypoint can still install bootstrap dependencies, download configuration,
authenticate to Bitwarden, and refresh its local cache during a preview.
