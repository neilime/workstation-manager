# End-to-end tests

Run workstation-changing tests in the Lima VM. They use credentials and live
recovery services; keep them isolated from the development host.

## Prerequisites

Install cURL, Python 3, Lima, `qemu-img`, and `qemu-system-x86_64`.
The [VM template](../../e2e-tests/lima-ubuntu.yml) selects the Ubuntu release,
architecture, disk, and memory. Override CPU and memory with positive
`E2E_VM_CPUS` and `E2E_VM_MEMORY_GIB` values before creating a VM.
Existing VMs retain their resources.

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

The suite runs three phases:

1. **Backup:** create isolated project fixtures and a published Chezmoi source,
   restore keys, and require recovery checks without prompts or skips.
2. **Setup:** remove the recovery fixture, restore its archive, and verify installed
   behavior. The override defers provider sign-in explicitly.
3. **Cleanup:** verify the report and preservation of user data.

The backup fixture requires a fresh VM without Chezmoi or Brave profile state.
Setup uses configured Bitwarden collections and requires live Brave Sync recovery.
The [native browser smoke test](browser-adapters.md#validation) uses separate
disposable profiles with a disabled Sync endpoint. AI coverage uses
[unit and isolated integration tests](ai-tools.md#testing); provider sign-in remains
part of normal setup.

Use `make e2e-prepare` to build tooling and start the VM concurrently.
`make e2e-backup`, `make e2e-setup`, and `make e2e-cleanup` run individual actions
without assertions; setup expects the backup fixture archive.

## Teardown and reuse

Run `make e2e-down` after failures too. It resumes a stopped VM, asks only the
captured test devices to leave their Sync chains, verifies deletion, then removes
the VM. Failed browser teardown retains the VM and its recorded identities for
diagnosis; hosted CI runners still expire after the job.

Teardown requires fresh Sync download/readiness evidence, native leave
acknowledgement, and a successful server commit for the captured device's deletion.
A local leave callback alone cannot authorize VM deletion. Preexisting profiles
and profiles introduced after identity capture are excluded. Recovery words,
device identities, and raw protocol data stay out of diagnostics.
The shared [browser observer contract](browser-adapters.md#brave-implementation)
defines callback, navigation, and server-acknowledgement handling.

Use separate Sync chains for concurrent runs. Setup removes duplicate devices
matching its own name, so shared names and chains can interfere with another run.
VM names are not workstation cleanup defaults. Use `VM_NAME` to select an instance
and `make e2e-reset` before reusing it.

## Reports and diagnostics

Set `REPORTS_DIR=.reports` for syntax and test reports.
The setup screenshot defaults to `.reports/screenshots/e2e-setup-desktop.png`;
`SCREENSHOTS_DIR` changes its directory. CI publishes reports and the screenshot.

The suite records phase duration and exit status. `E2E_PROFILE_TASKS=1` adds
Ansible task timing; CI enables it and records failures as well as success.
Temporary profiling changes are restored afterward. Assertion output includes
the slowest tests.

Startup and setup failures produce bounded VM, memory, session, display-manager,
and OOM diagnostics. They exclude action journals and process environments.
After failed setup, browser diagnostics use numeric metrics and redacted checks;
a separate disposable chain is verified and removed without replacing the
original failure or saved recovery chains.

CI caches public Lima downloads before authenticated phases. Guest disks and
authenticated state are never cached. Each assertion phase uses its own SSH
control socket and a read-only Lima configuration. The read-only workspace mount
uses QEMU 9p without caching and leaves AppArmor enabled.
