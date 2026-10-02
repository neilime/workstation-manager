# Cleanup

Cleanup upgrades installed APT packages, removes orphaned dependencies, and prunes
unused Docker data, **including unused anonymous volumes**. Review containers and
their storage before running it.

## Run cleanup

Preview the drift report first:

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

| Area            | Action                                                                                                                                               |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| APT             | Refresh package lists, run a distribution upgrade, remove orphaned dependencies with their configuration, and clean obsolete cached packages.        |
| Docker          | Run `docker system prune --all --force --volumes`: remove stopped containers, unused networks and images, build cache, and unused anonymous volumes. |
| System journal  | Vacuum archived logs older than two weeks.                                                                                                           |
| Installer cache | Remove the cached mise installer from workstation-manager's user state directory.                                                                    |

APT upgrades can install or remove packages to resolve dependencies. Docker
cleanup runs whenever Docker is available, without a second confirmation.

## Drift report

An applied cleanup writes this report by default:

```text
~/.local/state/workstation-manager/cleanup-report.json
```

It lists manually installed APT packages and Flatpak apps added since the last
setup baseline, additional native browser profiles, and unexpected files in the
managed configuration and state directories. These findings are reported for
review; cleanup does not remove them. Browser profiles and their internal data
are preserved.

If the package baseline is missing, run setup before relying on package drift
results. Docker prune and journal vacuum failures are recorded in the report and
do not stop cleanup; check their exit codes when an action appears incomplete.

## Preview limits

`--dry-run` reports drift but skips package upgrades, package removal, Docker
pruning, log deletion, and installer removal. It does not calculate the exact
package transaction or the amount of Docker data that would be removed, and it
does not save a new cleanup report.

The entrypoint can still install bootstrap dependencies, download configuration,
authenticate to Bitwarden, and refresh its local cache during a preview.
