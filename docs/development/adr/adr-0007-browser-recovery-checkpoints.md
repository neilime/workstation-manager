# ADR 0007 Explicit browser recovery checkpoints

- Status: Accepted; shared-pin management superseded by [ADR 0008](adr-0008-native-browser-recovery-scope.md)
- Date: 2026-11-25
- Scope: Browser recovery and continuous shared-pin synchronization

## Context

Setup must restore all expected browser data before succeeding. A reported
failure had only `Sync Cycle Ongoing` incomplete. That message identifies the
failed predicate; it does not establish whether data was missing, a request was
stuck, or unrelated work kept the engine busy.

The verifier at the start of this investigation required two healthy snapshots with a fresh
successful download, idle Sync, and entity coverage. Its fresh-download flag
does not associate the response with requested data types. Two synthetic replays
of the production JavaScript on 2026-11-25 demonstrated independent gaps:

- A fresh response with only a Bookmarks progress marker could satisfy the
  download flag for an otherwise complete diagnostic fixture.
- Marking the engine busy prevented entity inspection even when that same
  fixture contained the expected data.

These are verifier observations, not a reproduction of the user's failure.

Chromium exposes a [per-type download status][download-status] internally, but
the [Sync diagnostics handler][diagnostics] does not expose it to WebUI.
The [download processor][processor] validates response markers and emits the
protocol response before the [syncer applies updates][syncer]. A successful
response therefore cannot prove restoration. A controller's `Running` state
alone is also insufficient during initial configuration.

## Confirmed recovery requirements

The user selected these required categories on 2026-11-25. Setup must verify
their restoration before succeeding:

| Required data             | Boundary                                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------- |
| Bookmarks and folders     | URLs, names, hierarchy, and ordering.                                                                   |
| Browser preferences       | Supported browser settings.                                                                             |
| Search engines            | Default provider and custom search definitions.                                                         |
| Shields and site settings | Supported protection settings and exceptions.                                                           |
| Themes and appearance     | Supported synced appearance plus managed profile choices.                                               |
| Extensions                | Installed extensions and their synced settings. Local-only extension data is excluded.                  |
| Browsing history          | History available through Sync, with its documented limitations; not a complete historical archive.     |
| Browser and web apps      | Supported registrations and synced settings.                                                            |
| Profile metadata          | Names, colors, and custom avatars managed through Bitwarden.                                            |
| Shared pinned tabs        | Continuously propagate pin, unpin, and reorder operations between computers; restore the list at setup. |

Browser-saved passwords, autofill, ordinary open tabs, saved tab groups, reading
lists, exact window/session layouts, site sessions and storage, local-only
extension data, payment methods, passkeys, downloads, Wallet/Rewards data, and
Leo history are outside the requested recovery guarantee. Existing data must
remain preserved.

### Confirmed behavior

The user confirmed all five rules on 2026-11-25. These are accepted requirements;
implementation must satisfy the qualification checks below.

1. Recovery uses the latest data uploaded to Brave Sync, with profile metadata
   from Bitwarden. Preserve later deletions and edits instead of replacing them
   with an older backup snapshot. Data never uploaded by another computer cannot
   be recovered from the chain.
2. Disable synchronization for excluded categories wherever Brave provides
   suitable controls, while preserving existing data. Merely omitting these
   categories from verification does not satisfy this rule. If a control couples
   required and excluded categories, report that limitation before adoption.
3. Merge compatible offline pin edits. An unpin wins over a concurrent reorder
   of the same pin. A stale device must not resurrect that pin; an explicit later
   re-pin remains a new user action.
4. Preserve the address saved when a tab was pinned. Navigation inside that tab
   stays local and must not change the shared pin address or navigate tabs on
   other computers.
5. A remote unpin removes the pin on other computers while leaving the page open.

The previous implementation enabled `Sync everything`. Setup and backup now
share the selected-category contract, including disabled excluded categories.
Upload verification, approved-change verification, and device-removal safety
requirements remain in force.

### Shared pinned tabs

The requested flag is `brave://flags/#brave-shared-pinned-tabs`. In the inspected
Brave release it controls `BraveSharedPinnedTabs`, which is
[disabled by default][pinned-feature]. The separate profile setting
`brave.tabs.shared_pinned_tab` is [registered locally with a false default][pinned-pref].
The [shared pinned-tab service][pinned-service] shares live tab contents among
windows belonging to one local profile. It does not implement a cross-computer
pin-list synchronization channel. Enabling the flag alone does not satisfy the
requested recovery guarantee.

Qualification must enable the feature and profile setting, restore the intended
pin list and order, and verify the pinned tabs after a browser restart and in a
new normal window of that profile. Ordinary tabs, cookies, and site sign-in
sessions remain outside the selected scope.

The user confirmed continuous synchronization between computers. A setup-only
snapshot does not meet this requirement. Each profile needs its own shared list
of pinned URLs and their order, plus local shared-window behavior. This does not
require sharing page memory, cookies, or site sign-in sessions between computers.

Use a managed MV3 extension with the documented [tabs API][tabs-api] and
[extension sync storage][extension-storage]. It uses the existing Brave chain;
there is no additional synchronization service. Pin identities and saved URLs are
immutable. Positions are separate records. Permanent, compact per-device removal
records make an unpin win over a concurrent reorder or stale replay. A later
explicit re-pin receives a new identity. Compatible changes to different pins
merge; conflicting moves of the same pin use the Sync storage result.

Persist pending writes locally before calling Sync storage. Preserve deletions
when collecting obsolete live records. Quota or write failures retain the outbox
and fail setup/backup verification. A minute alarm retries pending work; verify
that the alarm exists whenever the worker starts. Observe native tab events
serially and distinguish actual reorders from tab creation and navigation.

Install the stable extension identity under the browser data root and load it
through the managed desktop and command launchers, including automation restarts.
The DevTools unpacked-extension probe did not persist across ordinary launches.
An empty extension cache does not prove an empty chain. Setup alone authorizes
initial publication after fresh download/application evidence. On a chain change,
pause publication and preserve the old local state before disconnecting. Verify
disabled native transport before clearing extension Sync storage. Keep the old
pages open.

Two existing extensions were inspected on 2026-11-25. [TruePin][truepin]
documents manually saved sets across computers and local automatic snapshots.
[Persistent Pinned Tabs for Brave][persistent-pins] documents persistence across
sessions and windows within a profile. Neither inspected description establishes
automatic cross-computer pin, unpin, and reorder propagation compatible with
Brave's native shared-pins feature. Neither has been installed or qualified here.

Native qualification must establish:

- Pin, unpin, and reorder changes propagate both ways between independent profiles
  on the same test chain, with unrelated profiles unaffected.
- A fresh installation receives the saved list before publishing local defaults.
  Restarting, closing windows, and transferring a shared tab between windows must
  not publish accidental removals or multiply pins.
- Offline changes survive restart and converge after reconnecting. Compatible
  edits merge, and unpinning wins over a concurrent reorder without stale devices
  resurrecting removed pins.
- Navigation within a pinned tab preserves its original shared address and leaves
  navigation on other computers unchanged, including after browser restart.
- Applying remote changes preserves ordinary tabs and local page state where
  possible. A remote unpin must leave that tab open.
- Setup reads back the actual pinned URLs and order after synchronization and
  fails if required recovery is incomplete.

These are acceptance requirements. The earlier API probe explicitly writes and
applies lists. Production qualification must exercise automatic worker behavior
through real browser actions.

## Decision

Use a finite recovery boundary in setup and backup:

1. Observe fresh requests and successful final responses covering every required
   data type. Reject missing markers, remaining pages, failures, and ambiguous
   request ordering. Do not export entity contents or recovery words.
2. Require a later request carrying the final response's progress markers, then
   query native models after the engine dispatches their updates. Require healthy
   transport/encryption, complete required-model coverage, and acknowledged
   metadata with no pending tombstones. Separately verify installed extensions
   and web-app registrations; their Sync nodes can include pending installation
   requests. Verify actual shared pins and their uploaded changes.
3. Permit unrelated ongoing work only after those conditions hold. An idle flag
   by itself must neither certify restored data nor invalidate proven data.
4. Preserve device identity and continue an interrupted attempt without resetting
   or rejoining the chain. A blocked or stale attempt must fail.

The [checkpoint parser](../../../ansible/collections/ansible_collections/neilime/workstation_setup/plugins/module_utils/browser/sync/checkpoint.py)
is shared by production and the earlier narrow live experiment. Unknown native
schemas and data types fail closed. Observer replacement discards prior evidence.
Commit-only models have no download requirement but retain upload checks.

On the inspected Ubuntu/Brave build, the apps selection includes Web Apps;
retired packaged Apps/App settings models do not run. Nigori encryption readiness
is checked independently. Do not require absent platform models or silently
omit active models from download coverage. Web-app debug installation states are
numeric strings; accept completed registrations, including native suggestions
without OS integration, and reject pending installation or removal.

## Alternatives

- Increasing the timeout can accommodate slow requests but cannot establish
  missing data coverage or repair an observation race.
- Ignoring `Sync Cycle Ongoing` without replacement evidence weakens the user's
  completion requirement.
- Reporting success immediately after enrollment does not restore the required
  data before setup succeeds.
- Restoring a complete profile snapshot could provide an explicit inventory,
  but requires a separate encrypted backup contract, coherent closed-profile
  capture, and device identity handling. Brave documents that copying profiles
  between systems can lose [access to encrypted data][encryption] without the
  corresponding operating-system key storage.
- Hosting another Sync server does not fix client-side completion evidence.

## Consequences and qualification

The expected state is the latest data available from the selected chain, not a
stale backup inventory. Data never uploaded elsewhere is unavailable. Native Sync
limits still apply to history, supported preferences, extension-local data, and
web-app OS integration. The helper's transport inherits extension storage limits.
Removed pins retain compact tombstones; deleting those records would weaken stale
device protection.

The native shared-window feature exposes placeholder tab URLs that can lag behind
the live shared tab after navigation. Verify per-window pin identities and order,
and retain their current addresses only on the current device for restart adoption.
When Brave restores the original shared address, briefly activate the tab to
attach its real contents and restore this computer's saved navigation, then
restore the previous active tab. Do not publish navigation to other computers.

Do not reuse download checkpoints as upload or deletion acknowledgements.
Backup reconciliation and approved changes must keep their existing failure
semantics. Device removal retains [ADR 0005](adr-0005-browser-sync-teardown.md).

Live qualification must report exact browser/runtime versions, elapsed time,
actual data readback, interruption rejection, recovery continuation, identity
preservation, and server-confirmed fixture removal. Report whether a busy cycle
was actually observed; do not infer it merely from generated activity. Full
workstation qualification remains required in addition to isolated native checks.

## Initial research evidence, 2026-11-25

A new Lima VM ran Ubuntu 26.04, Python 3.14.4, and Brave 1.100.59
(browser version output `158.1.100.59`). Three consecutive experiments passed
after correcting the observer's assumptions about native serialization:
protobuf integers are strings, and the diagnostic visitor omits
`message_contents`. Request progress markers identify the download requests.

The recovery/interruption/identity phases took 44.8, 44.4, and 44.5 seconds.
Each run restored the exact synthetic bookmark and Home button preference,
rejected the disconnected receiver for ten seconds, recovered the next bookmark
after reconnecting, and preserved the device identity. Both runs that recorded
the completion sample passed while `Sync Cycle Ongoing` was true. All runs
observed a busy cycle during polling. Each run separately required server
confirmation of both test-device removals before deleting the profiles.

These results validate the experiment's narrow contract. They do not reproduce
the original private chain, demonstrate large-profile recovery, or establish
coverage for the other browser data types. Unit coverage separately rejects
orphan, partial, paginated, failed, and ambiguously ordered evidence, and
preserves unowned files and incomplete fixture recovery state during cleanup.

### Shared pins API and transport evidence

A separate new Lima VM used the same Ubuntu, Python, and Brave versions above.
Two independent profiles loaded the same synthetic extension identity and joined
a fresh test chain. The API and transport phases passed in 47.6 seconds. An
expanded run also verified native reordering and preservation of the unpinned
page, passing those phases in 49.6 seconds and finishing with server-confirmed
removal of both devices in 91.0 seconds total. All devices created by the trials
were removed with server confirmation before their profiles were deleted.

The probe confirmed fresh extension storage download, transfer in the reverse
direction, cached storage and encrypted chain identity after restart, and receipt
of a changed list after reconnecting. Explicit application of that list produced
the exact pinned URLs and order in every normal window, including a newly opened
window. Native unpinning left the underlying page open. These assertions require
the real browser and Sync transport; mocked extension APIs cannot qualify them.

The runner uses a test-only unpacked extension with a public manifest key and
private debugging pipes. It deliberately writes and applies the known test lists
through its driver. It does not qualify automatic tab event tracking, extension
service-worker suspension, concurrent offline edits, production distribution, or
empty-chain initialization. That probe enabled the native feature only for its test launches; it did not
qualify persistence for normal launches.

New tabs can briefly expose an empty URL before navigation completes. The probe
tracks newly created tab IDs during application and waits for actual URL readback.
Browser restoration can also produce multiple normal windows; verification checks
the pin list in every window instead of imposing an exact window layout.

## Implementation evidence, 2026-11-25

A new isolated Lima VM ran Ubuntu 26.04, Python 3.14.4, and Brave 1.100.59
(Chromium 158.0.8127.92). The source tree was mounted directly into the guest;
the tests used disposable profiles, independent synthetic chains, and private
debugging pipes. No personal profile or saved recovery chain was used.

The expanded checkpoint experiment passed in 130.5 seconds. It required the
production verifier after fresh restoration and after reconnecting, rejected the
blocked receiver, read back the synthetic bookmark and preference, and retained
the receiver identity. A busy cycle was sampled, including at the narrow probe's
completion; the run did not separately record whether production verification
completed while busy. The native diagnostic regression independently verifies
that a busy flag cannot reject otherwise complete evidence.

The managed worker qualification passed in 235.9 seconds. Actual tab events
verified fresh restoration, both directions of propagation, additional windows,
browser restart, remote unpin with its page preserved, and explicit re-pin.
Local navigation survived offline browser restart. Compatible offline additions
merged with online changes, and an online unpin defeated a concurrent offline
reorder. A synthetic storage-write failure preserved the real local outbox;
stopping and restarting the actual extension worker drained it and propagated
the re-pin. Both experiments separately confirmed server removal of every test
device before deleting its profile.

Real native installation APIs rejected a missing web app, accepted its completed
installation, and rejected it after uninstall. The loaded extension also passed
native readback. These assertions exercise asynchronous browser installation,
which mocked Sync nodes cannot establish. The isolated launcher role changed
four resources initially and zero on its second run. The installed command
launcher loaded the helper in the intended native profile, and the actual desktop
entry launched Brave with that helper. Offline native checks also verified
preservation of old pin work during a disconnected chain reset and isolation
between separate browser profiles.

The expanded window-transfer assertion exposed Brave's unpin/detach/remove/attach
sequence for shared contents. The worker now retains the shared identity across
that sequence and re-pins the moved tab. A real-browser regression checks that
both transferring the tab and closing a window preserve the shared list. The
fresh-receiver fixture first verifies source upload, so its expected inventory
is data already available on the chain. The final expanded run, including the
window-transfer correction, passed all behavior assertions in 210.8 seconds.

The complete Python unit suite passed 1,405 tests in 52.19 seconds, and the five
pin-model tests passed in 0.55 seconds. The isolated integration suite passed
342 tests in 1,822.94 seconds while other VM and lint work was running. New unit
coverage targets incomplete download evidence, missing installation, extension
file safety, and pin conflict semantics. Native tests cover browser events and
the real Sync transport that unit tests cannot establish.

These checks qualify the implementation against this browser build and synthetic
data. They do not establish recovery of a large private chain or replace the full
credentialed workstation bootstrap, backup, setup, and cleanup flow. That full
flow was not run for this change.

[download-status]: https://chromium.googlesource.com/chromium/src/+/158.0.8127.92/components/sync/service/sync_service.h
[diagnostics]: https://chromium.googlesource.com/chromium/src/+/158.0.8127.92/components/browser_sync/sync_internals_message_handler.cc
[processor]: https://chromium.googlesource.com/chromium/src/+/158.0.8127.92/components/sync/engine/get_updates_processor.cc
[syncer]: https://chromium.googlesource.com/chromium/src/+/158.0.8127.92/components/sync/engine/syncer.cc
[encryption]: https://support.brave.app/hc/en-us/articles/29808985123085-Sensitive-data-storage
[pinned-feature]: https://github.com/brave/brave-core/blob/v1.100.59/chromium_src/chrome/browser/ui/tabs/features.cc
[pinned-pref]: https://github.com/brave/brave-core/blob/v1.100.59/browser/ui/tabs/brave_tab_prefs.cc
[pinned-service]: https://github.com/brave/brave-core/blob/v1.100.59/browser/ui/tabs/shared_pinned_tab_service.h
[tabs-api]: https://developer.chrome.com/docs/extensions/reference/api/tabs
[extension-storage]: https://developer.chrome.com/docs/extensions/reference/api/storage
[truepin]: https://github.com/datysho/truepin#saved-sets-and-autosaves
[persistent-pins]: https://github.com/centennial-oss/persistent-pinned-tabs-brave-ext#features
