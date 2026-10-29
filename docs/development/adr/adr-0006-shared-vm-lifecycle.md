# ADR 0006 Shared VM lifecycle with workstation-owned tests and recovery

- Status: Proposed
- Date: 2026-10-29
- Scope: CI VM creation, host assertions, and verified teardown

## Context

The infrastructure CI project provides focused Lima create, test, and destroy
actions. Workstation tests have a different execution boundary from its guest
command action: Docker runs pytest and testinfra on the host, while nine staged
operations exercise backup, setup, and cleanup through SSH. Reports, desktop
screenshots, credential scopes, and browser recovery all belong to this scenario.

[ADR 0005](adr-0005-browser-sync-teardown.md) requires verified removal of captured
browser devices before VM deletion. A generic destroy action cannot establish
that evidence, and an unconditional cleanup step would violate this contract.

## Decision

Use the shared create and destroy actions in CI. Keep host assertions, staged
workstation operations, and report publication in this repository. Do not route
host tests through an action intended to execute commands inside the guest.

The consumer prepares a Lima configuration from its maintained desktop template
and a verified cached public image. Plain mode isolates the guest from host
mounts and agents. Guest provisioning downloads the exact public checkout commit
before authenticated stages, preserves executable permissions, and makes the
source read-only. Resume reuses that source only when its recorded identity
matches the requested repository and revision.

Creation returns the VM name and private Lima runtime directory for host SSH and
QMP access. A configurable startup timeout accommodates desktop readiness. These
are generic lifecycle capabilities; no workstation callback runs in the action.

The consumer finishes fixtures and attempts browser-device removal after stage
failures too. Shared destruction requires successful browser removal for a
started guest. Failed startup cleanup is allowed directly because no authenticated
scenario stage has run. Failure to verify removal retains the VM until the
runner expires, with the same limitation documented in the existing test guide.

Local `make e2e-up`, `make e2e-test`, and `make e2e-down` remain available. Local
VMs retain their live read-only workspace mount. The separate `e2e-leave` target
allows CI to verify browser cleanup before handing deletion to the shared action.

## Alternatives

- Moving the entire scenario into a composite action would couple generic VM
  lifecycle code to workstation recovery and violate single responsibility.
- Moving all assertions into the guest would change the established test
  boundary without helping lifecycle reuse.
- Unconditionally destroying the VM would remove the identities needed to retry
  remote browser cleanup.

## Consequences and validation

The shared repository owns runner dependencies, runtime allocation, startup, and
deletion. This repository owns desktop configuration and all external resources
created by its scenario. GitHub Actions dependency updates cover the pinned shared
action references.

Focused tests cover source pinning, corrupt image rejection, resumed provisioning,
private-runtime SSH access, credential scopes, and the browser-removal gate.
Full hosted validation must still exercise all nine stages and preserve report
and screenshot publication before this proposal is accepted.
