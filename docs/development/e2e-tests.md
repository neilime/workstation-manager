# End-to-end tests

Run workstation-changing tests in the Lima VM. They use credentials and live
recovery services; keep them isolated from the development host.

## Prerequisites

Install cURL, Python 3, Lima, `qemu-img`, and `qemu-system-x86_64`.
The [VM template](../../e2e-tests/lima-ubuntu.yml) selects the Ubuntu release,
architecture, disk, and memory. Override CPU and memory with positive
`E2E_VM_CPUS` and `E2E_VM_MEMORY_GIB` values before creating a VM.
Existing VMs retain their resources.

CI prepares an offline desktop prerequisite image from the configured Ubuntu
cloud image. Its cache key includes the upstream SHA-256, build recipes, and UTC
calendar week; the weekly rebuild refreshes desktop packages. Cached image bytes
are checked before use. A cache miss installs `libguestfs-tools` and `dhcpcd-base`
on the runner and builds the image before authenticated actions begin.
CI uses QEMU's built-in user networking for the build appliance.

The image contains only the desktop prerequisites normally installed by Lima.
Every test VM still creates its own identity, user session, and fixture keyring,
then runs the complete workstation bootstrap. Live VM disks, restored keys,
Bitwarden state, and browser profiles are never used to build the image.

For a local prepared base, install `libguestfs-tools` and `dhcpcd-base` alongside
the VM tools, ensure your user can access `/dev/kvm`, then run:

```sh
printf '%s\n' dhcpcd-base |
  sudo tee "$(guestfish get-path)/supermin.d/workstation-manager-dhcp" >/dev/null
sudo chmod a+r /boot/vmlinuz-*
make e2e-base-inputs
make e2e-base
E2E_BASE_IMAGE="$PWD/.cache/e2e-base/desktop.qcow2" make e2e-up
```

The supplemental package list includes the DHCP client inside the appliance so
it can configure networking and DNS. The builder must run without `sudo`: its
network helper needs access to the builder's temporary files. On Ubuntu, the
kernel read permission above lets libguestfs create its appliance as your user; see the
[libguestfs Ubuntu guidance](https://libguestfs.org/guestfs-faq.1.html#ubuntu).

The builder customizes a fresh download offline; it never opens an existing Lima
instance. Without `E2E_BASE_IMAGE`, local startup installs desktop prerequisites
from the cloud image. Existing instances keep their original base. The manual
main CI workflow exposes `prepared-desktop`: disable it to compare the full suite
against cold desktop provisioning at the same commit. Compare cache misses
separately from cache hits, and run comparisons sequentially when using the same
Sync chains.

Readiness requires GNOME on Wayland and an unlocked fixture keyring.
The fixture initializes its encrypted keyring privately, restarts the desktop
session after setup, and unlocks it for recovery checks.

Provide these credentials through the environment:

- `BITWARDEN_CLIENT_ID`, `BITWARDEN_CLIENT_SECRET`, and `BITWARDEN_PASSWORD`.
- `WORKSTATION_MANAGER_GITHUB_TOKEN` for the private configuration repository.
- A saved GitHub login with `write:packages`, or a separate
  `WORKSTATION_MANAGER_GHCR_TOKEN` with the required image permissions.
  CI passes its short-lived job token separately.

See [automation](automation.md#automated-runs) for credential behavior.

## Select the revision

The VM downloads the public entrypoint and exercises remote bootstrap. The default
source is the checkout's `origin` and current branch, or its commit when detached.
Set `E2E_REPOSITORY_URL` and `E2E_REPOSITORY_REF` to select another repository or ref.
Publish the intended changes first; uncommitted host edits are not deployed.

CI uses the exact checked-out workflow commit, including PR merge commits.
Bootstrap explicitly fetches pinned commits.

## Run the flow

```sh
make e2e-up
make e2e-test
make e2e-down
```

The suite runs backup, setup, and cleanup in order. Each phase separates
Arrange, Act, and Assert, with a distinct CI step and timing record:

| Phase   | Arrange                                                               | Act                                                                            | Assert                                        |
| ------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------ | --------------------------------------------- |
| Backup  | Create project fixtures and a published Chezmoi source; restore keys. | Run backup with recovery checks, then remove the temporary Chezmoi fixture.    | Verify archive contents and recovery results. |
| Setup   | Validate the archive and remove the fixture files to restore.         | Run setup, capture browser device identities, and prepare the desktop session. | Verify restored files and installed behavior. |
| Cleanup | Create browser preservation markers.                                  | Run cleanup.                                                                   | Verify the report and preserved user data.    |

The setup override explicitly defers provider sign-in. Browser ownership
preparation and capture remain together around the setup action, including when
it fails. Assertions are unchanged between the full local flow and CI stages.

The backup fixture requires a fresh VM without Chezmoi or Brave profile state.
Setup uses configured Bitwarden collections and requires live Brave Sync recovery.
The [native browser smoke test](browser-adapters.md#validation) uses separate
disposable profiles with a disabled Sync endpoint. AI coverage uses
[unit and isolated integration tests](ai-tools.md#testing); provider sign-in remains
part of normal setup.

Use `make e2e-prepare` to build tooling and start the VM concurrently.
`make e2e-backup`, `make e2e-setup`, and `make e2e-cleanup` run individual actions
without assertions; setup expects the backup fixture archive.

After `make e2e-prepare`, `make e2e-stage STAGE=backup-arrange` runs a single
stage. Use `backup`, `setup`, or `cleanup` followed by `-arrange`, `-act`, or
`-assert`, in the table's order. Stages share the same VM and require earlier
stages to succeed; they are not independent reruns. Always run
`make e2e-stage STAGE=finish` afterward to remove any remaining backup fixture
and report screenshot failures, then `make e2e-down`. The full `make e2e-test`
command handles stage sequencing and fixture finishing automatically.

## Measure setup in CI

Run the manual **Main - Continuous Integration** workflow on the revision to
measure, with `setup-benchmark=true`:

```sh
gh workflow run main-ci.yml --ref <published-branch> -f setup-benchmark=true
```

This mode adds a repeated setup and all setup assertions before cleanup in the
same disposable VM. The repeat retains installed state and
the same configuration; it does not remove restoration targets or replay the
backup archive. Browser identities must match the original captured fixture
before and after the repeat. An interrupted or unverifiable repeat retains the VM
for diagnosis instead of discarding unverified remote devices.

The benchmark adds separate `setup-repeat-act` and `setup-repeat-assert` timings
and a separate JUnit report. `setup-command` and `setup-repeat-command` measure
the entrypoint itself, excluding browser fixture bookkeeping and desktop
assertion preparation. They are contained within their Act timings; do not add
them to the stage totals. The repeat gets its own screenshot and deferred failure
status. The manual benchmark has a 50-minute suite deadline and a 75-minute job
limit; routine PR runs retain the original single setup and deadlines.

Compare baseline and candidate revisions using the same VM resources and
`prepared-desktop` setting. Run them sequentially with verified teardown because
the credentials and recovery chains are shared. Record each commit and run URL;
external downloads, package updates and Sync latency can vary between runs.
Provider sign-in is deferred and a local private override is prepared by the end-to-end
fixture, so these measurements do not include those interactive production steps.

## Teardown and reuse

Run `make e2e-down` after failures too. It resumes a stopped VM, asks only the
captured test devices to leave their Sync chains, verifies deletion, then removes
the VM. Failed browser teardown retains the VM and its recorded identities for
diagnosis; hosted CI runners still expire after the job.

Teardown follows the shared
[Sync verification and deletion contract](browser-adapters.md#verification-and-device-removal).
Only captured fixture identities can leave; preexisting and subsequently added
profiles are excluded. A local leave callback alone cannot authorize VM deletion.

The [fixture helper](../../e2e-tests/browser_sync_fixture.py) runs each attempt in
a private copy of the captured profile and root encryption state. The original
profile stays closed and unchanged, retaining its exact identity and tracker for
retries. Before allowing server contact, a loopback CONNECT proxy immediately
rejects tunnel requests locally. The fixture waits for a native protocol event
proving that backend diagnostic forwarding is active, then permits browser
retries. This prevents network waits from blocking observer registration;
browser TLS verification remains enabled.
Removal requires a matching server commit, or a fresh successful GetUpdates
response containing that device's tombstone together with native confirmation
that Sync is disabled. An active client must perform native leave and obtain a
new commit acknowledgement. Inactive Sync alone proves nothing.

Unconfirmed removals and automation connection failures allow up to three
attempts with fresh copies. Confirmed progress is written atomically before
browser shutdown, so a later shutdown failure does not repeat an acknowledged
removal. Copies still used by a browser are retained and block overlapping
attempts. Other failures stop immediately; remaining identities and original
profiles stay available in the retained VM. Keep recovery words, device
identities and raw protocol data out of diagnostics. See
[ADR 0005](adr/adr-0005-browser-sync-teardown.md) for the design rationale.

Each device's Sync waits and retries are bounded. Teardown lets these
finish for every captured profile; its total duration grows with the number of
devices and retries. The SSH wrapper detects an unresponsive connection, and CI
allows 60 minutes for the full job, including VM preparation and verified
teardown. The nine stages share a 35-minute deadline, with bounded signal
cleanup afterward; fixture finishing and verified VM teardown run outside that deadline. Connection
failures and native operation failures retain the VM.

Use separate Sync chains for concurrent runs. Setup removes duplicate devices
matching its own name, so shared names and chains can interfere with another run.
VM names are not workstation cleanup defaults. Use `VM_NAME` to select an instance
and `make e2e-reset` before reusing it.

## Reports and diagnostics

Set `REPORTS_DIR=.reports` for syntax and test reports.
The setup screenshot defaults to `.reports/screenshots/e2e-setup-desktop.png`;
`SCREENSHOTS_DIR` changes its directory. CI publishes reports and the screenshot.

The suite records each Arrange, Act, and Assert stage's duration and exit status.
Setup also records desktop readiness, screenshot, and failure diagnostic timings;
these are included in the Setup Act duration, so do not add them to stage totals.
`E2E_PROFILE_TASKS=1` adds
Ansible task timing; CI enables it and records failures as well as success.
Temporary profiling changes are restored after each stage that runs Ansible.
Assertion output includes
the slowest tests. The native browser smoke test also prints elapsed time and
status for API checks, recovery persistence, profile switching, teardown retry,
and window restoration, including successful runs. These records contain fixed
scenario labels only; browser state and recovery data stay excluded.

With `REPORTS_DIR` set, each timed phase appends one JSON record to
`e2e/phase-timings.jsonl` beneath that directory. Records contain only `phase`,
`elapsed_seconds`, and `exit_status`; command arguments and credentials are
excluded. CI uploads this report after teardown, including failed phases.
Local invocations append to the same file; use a fresh report directory when
comparing separate runs. Detailed Ansible task timings remain in the job log.

Startup and setup failures produce bounded VM, memory, session, display-manager,
and OOM diagnostics. They exclude action journals and process environments.
After failed setup, browser diagnostics use numeric metrics and redacted checks;
a separate disposable chain is verified and removed without replacing the
original failure or saved recovery chains.
Screenshot-only failures are reported after assertions and cleanup finish, so
they do not skip test coverage. Action or assertion failures stop later stages;
CI still runs fixture finishing and verified browser teardown.

CI caches public Lima downloads by upstream image checksum and saves its offline
desktop base before authenticated phases. Running guest disks and authenticated
state are never cached. Each assertion phase uses its own SSH
control socket and a read-only Lima configuration. The read-only workspace mount
uses QEMU 9p without caching and leaves AppArmor enabled.
