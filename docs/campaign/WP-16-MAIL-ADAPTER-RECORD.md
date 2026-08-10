# WP-16 — Apple Mail Live Adapter Feasibility and Implementation

Branch: `bf/wp-16-apple-mail-adapter`. Base: `f121816fd7752165c28e36fcddf1d7700dfe2eb6`.

This record states what WP-16 proved, **at what level it proved it**, and what it
could not prove without an operator. It follows WP-15's shape because WP-15's
shape is the point: a compiled guarantee, a runtime observation and a document
are three different things, and a feasibility package that blurs them is worth
nothing.

**The headline is a split, and it is a negative on the half that matters most.**

> There is **no supported mechanism on this macOS version by which an unsigned,
> unentitled, headless process can enumerate Apple Mail accounts, list mailboxes
> or query messages.** MailKit cannot do it — that is re-proved below over the
> framework's entire public surface, not asserted. `Message.framework` cannot do
> it: it ships no header and exports two version symbols. The on-disk store has
> no public contract and is TCC-protected. The one mechanism that *does* expose
> accounts, mailboxes and messages is Apple Mail's scripting terminology, and
> reaching it requires a TCC Automation grant only a human can give — a grant
> which, as measured below, **cannot be scoped to reading**.
>
> Traversal, identity, bounding and refusal are a different question, and those
> are implemented and proved here at runtime against a fixture-driven mechanism
> seam. The adapter is real; the live mechanism behind it is operator-gated.

---

## A. Mechanism feasibility — the candidate matrix

Every negative below is measured against the SDK, the framework headers or
Apple's own scripting dictionary on this machine. Toolchain of record: Apple
Swift 6.2 (`swiftlang-6.2.0.19.9`), target `arm64-apple-macosx28.0`, SDK
`/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk` version 26.0, macOS 27.0
(build 26A5378n). **There is no full Xcode on this machine**, only Command Line
Tools, which matters once below.

| Mechanism | What it exposes | What it cannot do | Evidence | Verdict | What would change it |
|---|---|---|---|---|---|
| **MailKit** | 16 classes and 7 protocols across 23 headers, all extension-point: `MEExtension`, `MEMessageDecoder`, `MEMessageSecurityHandler`, `MEMessageActionHandler`, `MEContentBlocker`, `MEComposeSessionHandler`, `MEMessage`, `MEExtensionManager` | **No store. No account enumeration. No mailbox listing. No message query.** Messages arrive *as parameters to delegate callbacks Mail invokes*; nothing in the framework pulls | Full public surface enumerated from `MailKit.framework/Headers` in the installed SDK. Across all 23 headers the words `mailbox` and `account` occur only inside doc comments for `moveToTrashAction`, `moveToArchiveAction` and `moveToJunkAction`; `fetch` occurs only where Mail fetches headers *for* the extension. `MEExtensionManager` declares exactly two class methods, `reloadContentBlockerWithIdentifier:` and `reloadVisibleMessagesWithCompletionHandler:` | **NEGATIVE — confirmed** | Apple shipping a read API. Nothing an implementer can do |
| **MailKit, read as a mutation surface** | `MEMessageActionDecision` applying `markAsRead`, `markAsUnread`, `moveToArchive`, `moveToJunk`, **`moveToTrash`**, flag and background-colour actions | — | Same headers | **Adverse finding.** MailKit is a *mutation* surface with no read surface. Adopting it would import the authority to move a message to trash while providing none of the authority to read one | — |
| **`Message.framework`** | Nothing | Cannot be imported: the SDK ships `Message.tbd` and **no headers and no modulemap** | `Message.framework/Versions/B/Message.tbd` is 347 bytes and its `exports` list is exactly `_MessageVersionNumber, _MessageVersionString` | **NEGATIVE — a version-stamp husk** | Apple restoring headers. It has been header-less for many releases |
| **ScriptingBridge / OSAKit / AppleScript over Mail.app** | Accounts (`id`, `account type`, `email addresses`, `enabled`), mailboxes (nested, with `account` and `container`), messages (`id`, `message id`, `date received`, `date sent`, `subject`, `sender`, `source`, `message size`, `all headers`), attachments (`id`, `MIME type`, `file size`, `downloaded`) | Cannot be reached without a **TCC Automation grant**, which is operator-gated (EXT-04). Cannot be scoped to reading — see the access-group finding below. Publishes no generation token, so no stable identity — see control 2 | `ScriptingBridge.framework` and `OSAKit.framework` are both present in the SDK with modulemaps and link. `Compatibility/AppleMailAutomationShapeProbe` compiles against ScriptingBridge on every build. The terminology is Apple's own `Mail.sdef`, SHA-256 `111b9291c502354106a320f6ba0a7e38ed29f09e443404679fb57778708b0722`, and the probe's table is checked against it by `tests/architecture/test_wp16_mail_adapter.py` | **PRESENT, OPERATOR-GATED, and not read-only** | A TCC Automation grant on a pilot Mac (EXT-04) plus a signed, notarized helper (EXT-03). Neither makes it read-only |
| **Direct read of the on-disk Mail store** | — | Documented grounds only. **Not read, not listed, not stat-ed** | `~/Library/Mail` is inside the TCC-protected user-data set that requires Full Disk Access. **Apple publishes no format contract for the store**, which is the load-bearing half and is a claim about an absence rather than about a layout — so nothing about its bundle structure, its version directory or its index may be relied on across releases. This row is documentation-level by construction: settling it any other way would mean reading the operator's mailbox | **NEGATIVE on documented grounds** | Nothing short of Apple publishing a format contract. A Full Disk Access grant would make it *readable*, not *supported* |
| **IMAP against a loopback or fixture server** | The traversal contract in full: `UIDVALIDITY` as a generation, `UID` as a provider key, `SEARCH SINCE/BEFORE` as a server-side date bound, `FETCH BODY.PEEK[]` as a non-mutating read | **Cannot live in this host at all.** WP-15's control 2 forbids every networking primitive anywhere under `native/`, down to the raw Darwin calls. It also solves no part of *discovery*: accounts and credentials would have to come from somewhere else | `tests/architecture/test_wp15_native_host_admission.py::test_the_host_cannot_reach_a_database_or_read_a_credential` scans the whole `native/` tree | **Viable as a shape, structurally excluded as an implementation** | Moving IMAP to the application plane, where a credential and a socket are already permitted, and pairing it with a separate discovery mechanism |
| **`sdp` / `sdef` header generation** | Would have produced a compile-checked ObjC interface for the whole Mail dictionary | Not available: `sdp` requires full Xcode | `xcode-select: error: tool 'sdp' requires Xcode, but active developer directory '/Library/Developer/CommandLineTools' is a command line tools instance` | **UNAVAILABLE here** | Installing Xcode. It would raise the automation probe from a checked data table to a compiled interface |

### The access-group finding, which is the sharpest thing in this package

macOS offers exactly one mechanism for *scoping* Apple-event access to part of an
application's dictionary: scripting access groups, declared in the target's
`sdef` and requested by a sandboxed client through
`com.apple.security.scripting-targets`. If Apple Mail declared a read-only access
group, a sandboxed client could be granted reading and denied deletion.

It does not. Read out of `Mail.sdef` at the hash above:

* the **only** named access group Mail declares is `com.apple.mail.compose`, and
  it covers the Text Suite, `outgoing message`, `signature` and `recipient` — the
  *compose* surface;
* the `message`, `mailbox` and `account` classes of the Mail Framework suite —
  the entire read surface — carry **no access-group declaration at all**;
* `delete` (`coredelo`), `duplicate` (`coreclon`) and `move` (`coremove`) are
  each declared `<access-group identifier="*"/>`;
* `Mail.app`'s `Info.plist` declares no `NSApplicationScriptingAccessGroups`.

So the scoping mechanism, applied to Mail, would grant a sandboxed client the
compose surface and the three destructive commands and **not** the read surface —
the exact inverse of what this system wants. And an unscoped client holding a
full TCC Automation grant gets the whole dictionary, reads and deletions
together, because TCC Automation is granted per *(client, target application)*
pair and never per command.

**This is a reading of the dictionary, not a tested behaviour**, and it is marked
as such deliberately: testing it means sending an Apple event to Mail, which
raises the consent dialogue this package refuses to cause. It is nonetheless the
reason control 6 is enforced by *not linking the framework* rather than by
promising not to call the mutating half.

### What was deliberately not done to obtain any of this

No Apple event was sent. No `osascript`, no `NSAppleScript`, no
`OSAScript.executeAndReturnError`, no ScriptingBridge message send, no
`SBApplication` constructed. **`~/Library/Mail` was not read, not listed, not
enumerated and not stat-ed** — its directory names carry real account
identifiers, and a package about a public repository does not go there to learn
something a document already says. No TCC state was touched, so this package
consumed none of the operator's EXT-04 budget.

---

## B. The six controls

| # | Control | Verdict | Proved at | Where |
|---|---|---|---|---|
| 1 | Mechanism feasibility | **Split: proven negative for headless discovery; the automation mechanism is present and operator-gated; traversal proven against the seam** | Header/SDK enumeration (documentation-level for the negatives), **Swift compile-time** for ScriptingBridge's presence, **Python + Apple's `Mail.sdef`** for the terminology table | This document; `AppleMailAutomationShapeProbe`; `test_the_probe_read_shape_is_read_only_in_apples_own_dictionary` |
| 2 | Stable identity | **Proven, including the negative** | **Swift runtime, in-process** | `AppleSourceHostContractChecks::checkMailIdentityIsStableAcrossReadsAndChangesWithTheGeneration`, `::checkMailIdentityCompositionIsInjectiveAndRefusesToTrim`, `::checkMailReadRefusesAMechanismThatPublishesNoGeneration` |
| 3 | Date-bounded reads | **Proven against the seam; source-side-ness is enforced rather than assumed. Unmeasured for the live automation mechanism** | **Swift runtime, in-process** | `::checkMailDateBoundIsSourceSideOrRefused` |
| 4 | Body / attachment limits | **Proven, on the initialiser and on the decode path** | **Swift runtime, in-process**, plus static guards | `::checkMailBodyAndAttachmentBoundsOmitMarkAndRefuse`, `::checkMailPageCursorAndOrderingBounds`; `test_a_mail_body_is_carried_whole_or_omitted_whole_and_never_trimmed` |
| 5 | Permissions / packaging / sandbox | **Shape proven; nothing granted, signed or notarized** | **Swift runtime** for the refusal path; **documentation** for the entitlement and packaging shape | `::checkMailDiscoveryIsConsentGatedBeforeAnyRead`; `test_no_entitlement_or_usage_declaration_was_added_for_the_mail_mechanism`; §D below |
| 6 | Read-only surface | **Proven at Swift link time, unchanged from WP-15** | **Swift link-time** (the shipping target links no Apple framework) plus static guards over every Swift file under `native/` | `test_no_swift_outside_the_automation_probe_can_send_an_apple_event`, `test_the_mail_mechanism_seam_declares_only_read_operations`, `test_the_mail_automation_probe_sends_no_event_and_is_never_linked`; WP-15's `test_the_shipping_host_holds_no_write_path_into_an_apple_source` still passes unchanged |

### Control 1 — what "proven" means for each half

Two different claims, and conflating them would be the dishonest part:

* **"MailKit cannot enumerate"** and **"`Message.framework` is a husk"** are
  proven the way WP-15 proved the first of them: by enumerating the actual public
  surface of the installed SDK. That is documentation-level evidence about an
  artefact on this disk, and it is as strong as this kind of claim gets.
* **"The scripting mechanism exists"** is proven at **compile time**:
  `Compatibility/AppleMailAutomationShapeProbe` imports `ScriptingBridge` and
  resolves `SBApplication`, `SBObject`, `SBElementArray` and
  `SBApplicationDelegate` as metatypes, on every `swift build`. This is the
  difference between "the mechanism does not exist" and "the mechanism exists and
  we do not have permission", and only the second is true.
* **"The terminology is what this record says it is"** is proven by reading
  Apple's `Mail.sdef` in a test and comparing it to the probe's table, term by
  term, including the four-character Apple Event code and the `access="r"`
  attribute. The table is verified, not asserted.
* **Nothing here proves a live read works.** A grant, a real account and an
  operator are needed for that, and this package does not have them.

### Control 2 — identity, and why the generation is inside it

A provider key is stable only relative to a *generation* of the mailbox. IMAP
states this in as many words: a UID is unique and ascending within a
`UIDVALIDITY` value, and when the server changes `UIDVALIDITY` every UID a client
holds becomes meaningless. An identity that stored only the key would be a
correct-looking identifier that silently starts pointing at a different message,
and every downstream reconciliation would inherit that.

So `MailMessageIdentity` is `(mailboxID, generation, providerKey)` and the record
identifier is the three joined with `:`. Three consequences, each asserted:

* **The join is injective.** `MailIdentityComponent`'s alphabet excludes `:`, so
  the last two colon-separated fields of a composed identifier are always the
  generation and the key, and distinct triples cannot collide. The contract check
  demonstrates this on the pair that would otherwise alias.
* **An over-long composition is refused, never trimmed.** A trimmed identity is
  the one truncation with no honest partial form: it silently merges two
  messages into one record. `recordIdentifier()` throws `mailIdentityTooLong`.
* **A mechanism that publishes no generation cannot be read from at all.**
  `MailMechanismDescriptor.publishesGeneration` gates `readMail` before the
  mechanism is asked anything. This is not defensive coding; it is the honest
  finding turned into a structural constraint, because **Apple Mail's scripting
  terminology publishes nothing that plays the `UIDVALIDITY` role.** Mail's
  `message id` is the RFC 5322 `Message-ID` header, which is not unique across
  mailboxes and is not guaranteed present; Mail's `message` `id` is an integer
  `libraryID` with no published stability contract at all. A future automation
  mechanism must solve that before it can traverse, and it will find out here
  rather than three layers downstream.

The negative is asserted as loudly as the positive: after
`regenerate(as: "gen-0002")` the identity set must be **disjoint** from the
previous one. A stable identity across a generation change would be the failure.

### Control 3 — the bound reaches the source, and that is checked twice

`MailDateBoundEnforcement` is the mechanism's declaration of how far a date bound
actually reaches, and the adapter enforces the acceptance criterion against it:

* `sourceSideExact` — the source applies the interval;
* `sourceSideDayGranular` — the source applies whole days, because IMAP's
  `SEARCH SINCE`/`BEFORE` carry a date and no time. The adapter **widens outward**
  to whole UTC days and refines back to the exact interval itself. `MailDayWindow`
  refuses to exist unless it is day-aligned, on the initialiser and on the decode
  path, so an un-widened request cannot reach a day-granular source and silently
  drop the boundary days. The floor is a floor division, so a pre-epoch instant
  rounds down rather than toward zero;
* `clientSideAfterFullScan` — a date-bounded read is **refused**, before the
  mechanism is enumerated. "Bounded by date without enumerating the whole store"
  is the acceptance; a client-side filter after a full scan is precisely not it.

And the descriptor's claim is not taken on its own: `MailTraversalResult`
carries `scannedWholeMailbox`, and a date-bounded read whose result says `true`
is refused. Two independent locks, because the descriptor is the half an
optimistic implementer gets wrong. A third check catches a mechanism that ignores
the window it was handed: every returned instant is re-tested against the widened
window and `mailDateBoundViolated` is thrown if any falls outside.

**What is not proved:** whether Apple Mail's `whose date received > …` filter is
index-backed or a walk inside Mail. Apple publishes no contract either way, and
measuring it means sending an event. If an automation mechanism is ever built it
must declare its own enforcement level honestly, and `clientSideAfterFullScan` is
the answer that will be refused.

### Control 4 — three bounds that do three different things

A single behaviour at every bound would be wrong somewhere, so each bound does
what is honest for the thing it bounds. All are frozen in
`NativeSourceProtocolV1` alongside WP-15's page and cursor ceilings, and every
one is enforced **on the decode path as well as the initialiser** — WP-15's
lesson, because a bound that holds only for values built in Swift is a bound that
JSON walks around.

| Bound | Value | Behaviour | Why |
|---|---|---|---|
| `maximumMailBodyBytes` | 262 144 | Body **omitted whole and marked**, true size recorded | A body cut at a byte boundary reads as complete. An omission with the real size attached is loss the consumer can measure and re-fetch |
| `maximumMailHeaderBytes` | 65 536 | **Record refused** (`mailHeaderTooLarge`) | Headers are the record's identity and provenance. There is no honest partial header block |
| `maximumMailAttachmentDescriptors` | 32 | Descriptors carried to the ceiling, **true count recorded**, record marked partial | Losing metadata for the thirty-third attachment is recoverable if it is recorded, and undetectable if it is not |
| `maximumMailAttachmentBytes` | 26 214 400 | Descriptor must be labelled `omittedOversize` | It gates a *label*, never bytes — see below |

**Attachment bytes are bounded structurally rather than numerically.**
`MailAttachmentDescriptor` has no field for bytes and is not going to acquire one
by accident, so a two-gigabyte attachment costs a record a few dozen bytes. This
is the same shape WP-15 used for content-free telemetry: a struct with nowhere to
put the thing keeps the promise that a filter only makes.

**The invariant that makes truncation unrepresentable** is one line:
`body != nil` implies `body!.count == completeness.bodyByteSize`. A truncated
body has fewer bytes than the size it claims, so it cannot be constructed and it
cannot be decoded. The runtime check plants a marker at the **front** of an
oversize body and then searches the emitted record for it — the same
planted-marker technique WP-15 used for telemetry, applied to content.

**The first version of that search could not have failed**, and §F records the
plant that proved it: the check decoded the payload as UTF-8 and looked for the
marker as text, while every byte-bearing field encodes to a JSON array of decimal
numbers. It now searches **bytes**, in the record's headers and in the raw
payload.

### Control 5 — permissions and packaging, proved as a shape

Nothing was granted, signed, notarized or registered. What a live automation
mechanism would need, stated so the operator knows the size of the ask:

| Requirement | Value | Owner |
|---|---|---|
| TCC Automation consent | `kTCCServiceAppleEvents`, per *(this client, `com.apple.mail`)*. Prompted on the first event; cannot be scoped to reading (§A) | Operator, EXT-04 |
| Usage description | `NSAppleEventsUsageDescription` in the helper's `Info.plist`. Its absence is a hard failure on modern macOS, not a silent one | EXT-03 |
| Sandbox entitlements, if sandboxed | `com.apple.security.automation.apple-events`, plus `com.apple.security.temporary-exception.apple-events` naming `com.apple.mail` | EXT-03 |
| Signing and notarization | Required for the helper and for `SMAppService` registration | Operator, EXT-03 |
| Mail must be running | ScriptingBridge will launch it otherwise, which is itself a user-visible act | Operator |
| Network client entitlement | `com.apple.security.network.client` — **not needed and not wanted**, because the IMAP route is structurally excluded from this host | — |

**None of these keys exists anywhere in this tree, and two guards now say so.**
WP-15's `test_no_write_capable_entitlement_or_usage_declaration_exists` fails the
build if an `.entitlements`, `.plist` or `.provisionprofile` file appears;
WP-16's `test_no_entitlement_or_usage_declaration_was_added_for_the_mail_mechanism`
reads the same tree for the key *strings*, so one smuggled into a file of some
other type is caught too.

The runtime half of control 5 is the refusal path, and it is measured rather than
read: the fixture counts every call the adapter makes to it, so after a refused
consent "nothing was read" is the number `0` and not a claim about the source.
`notDetermined` is treated exactly like `denied`, because on macOS the trying is
what raises the dialogue. **The seam has no `requestConsent` and no equivalent**,
by construction and by guard — this host can learn that consent is absent and
stop, and has no way at all to ask for it.

### Control 6 — read-only, and WP-15's control 1 re-proved rather than weakened

**The shipping `AppleSourceHost` target still links no Apple framework.** WP-15's
structural proof is untouched: `test_the_shipping_host_holds_no_write_path_into_an_apple_source`
passes unchanged, over a scan that now includes WP-16's three new shipping files
and the new probe's Swift file.

The Mail adapter is defined over the `MailMechanism` seam and imports nothing but
`Foundation`. `ScriptingBridge` appears in exactly one place — the
non-shipping `AppleMailAutomationShapeProbe` — on precisely the footing WP-15
established for `AppleFrameworkCompatibilityProbe`: a separate target, resolving
metatypes, instantiating nothing, and **deliberately not a dependency** of
anything else in the package. The guard for that is a **count** — a probe
target's name may appear as a quoted token in `Package.swift` exactly once, in
its own `name:` — because the obvious section-walking form of it does not work,
and §F records how that was discovered. A second guard asserts the probe
constructs no `SBApplication`, compiles no script and sends no event.

The seam itself is a closed set of five read operations, held closed by a guard
rather than by review. There is no move, no delete, no flag, no mark-as-read.

---

## C. The harness, and the level of proof it reaches

**In-process, over a mechanism seam. Not over a socket. This is stated plainly
because the alternative would be worth more.**

A loopback IMAP responder on `127.0.0.1` would prove the wire contract, and it
was not skipped as disproportionate — it is **forbidden by a standing control**.
WP-15's control 2 scans every file under `native/` for the raw Darwin networking
primitives and the framework-level clients above them, test targets included, so
a listening or connecting harness anywhere in this package turns that guard red.
Weakening the guard to get a nicer proof would have been the wrong trade, and
adding a socket outside `native/` would have proved a wire this host is forbidden
to speak.

So: the traversal, identity, bounding and refusal claims are proved at **runtime,
in one process**, and nothing in this record implies socket-level or live-source
coverage. What the seam does buy is that the same claims will hold for any
mechanism that satisfies it, because every refusal lives in the adapter rather
than in the mechanism.

`FixtureMailMechanism` is IMAP-shaped on purpose: it publishes a generation, keys
messages by an ordered provider key, and bounds by whole days. It also injects
three faults a real mechanism can have — ignoring the window, satisfying the
window by scanning everything, and returning keys out of order — so the adapter's
re-checks are exercised rather than merely written.

Every fixture value is obviously synthetic: `person-a@example.invalid`,
`person-b@example.invalid`, `Fixture Subject 001`. `.invalid` is the reserved
TLD. The harness needs no credential and there is none to mistake for one.

**Provider keys are compared lexicographically**, which is a real constraint on
any future mechanism: an IMAP mechanism must zero-pad its UIDs or the cursor
resumes in the wrong place, because `10` sorts before `9`. The fixture pads, and
this sentence is the contract.

---

## D. What requires an operator, and what each would unlock

| Gate | What is missing | Would unlock |
|---|---|---|
| EXT-04 | A TCC Automation grant for *(helper, `com.apple.mail`)* on a pilot Mac | Whether the scripting mechanism actually enumerates accounts and mailboxes at usable speed; whether `whose date received` is index-backed; whether `message` `id` is stable across a Mail restart and across an account re-sync — the generation question this package refuses to guess at |
| EXT-03 | Apple signing identity, notarization profile, and an `Info.plist` carrying `NSAppleEventsUsageDescription` | Any of the above at all, since an unsigned helper cannot hold a durable TCC grant |
| EXT-05 | An eligible pilot Mac and `SMAppService` registration | Lifecycle evidence for the helper that would host the mechanism |
| EXT-06 | An approved non-personal Apple test account with seeded synthetic mail | The only honest way to measure performance and date-bound behaviour. **No live personal mailbox may be used for this, and none was** |
| — | A decision, not a grant: whether IMAP moves to the application plane | The full traversal contract over a real wire, with `UIDVALIDITY` as a real generation. It cannot live in this host |
| — | Full Xcode | `sdp`-generated terminology headers, raising the automation probe from a checked data table to a compiled interface |

**What an operator cannot unlock**, and it should be said before anyone spends a
grant on it: a TCC Automation grant to Mail is not scopeable to reading, and no
amount of operator cooperation makes it so. If read-only-at-the-permission-layer
is a requirement, Apple Mail automation fails it permanently, and the honest
options are a per-account IMAP client on the application plane or Microsoft Graph
— which is explicitly out of scope here.

---

## E. What WP-16 deliberately did not do

* **No migration and no capability seat.** The Alembic chain is unchanged:
  26 revision files, single head `8f2b6c4d1a37`, both re-derived at this head.
  The seat and frozen-`CHECK` counts are not restated here because this package
  did not measure them; it added nothing that could move them, and the suites
  that do measure them pass.
* **No un-quarantining.** Nothing added here is reachable from any transport.
  `test_the_native_source_plane_is_reachable_from_no_transport` passes unchanged,
  and `BoundedMailReadAdapter` has zero references outside the host package.
* **No WP-20 baseline plane.** No `SqlNativeBaselineStore`, no
  `read_and_admit_page`, no `adapter_identity`, no run/checkpoint fields, no
  `NativeRunState.RUNNING`.
* **No Python source change at all.** `src/`, `apps/`, `scripts/`, `migrations/`
  and `ops/` are untouched; the only Python added is one architecture test
  module. The mail content bounds live entirely inside the host's payload
  construction, and the application's existing envelope bounds still apply to the
  page and cursor unchanged, so there is no second literal to hold equal.
* **Two documentation edits that are corrections, not claims.** The native
  package's README said "Thirteen checks" and had said so since before WP-15
  raised the count to fourteen; it now says twenty-one and describes the Mail
  targets. And `docs/plans/mcv-completion-plan.md` spelled a test-module count
  that adding one module made stale — the same guard caught the same class of
  defect for WP-15, which is the guard working.
* **No Apple event, no TCC prompt, no signing, no notarization, no service
  registration.**
* **No live personal data.** `~/Library/Mail` was not touched in any way.
* **No Graph anything.**

---

## F. Non-vacuity — controlled reversions

Every guard authored by this package was planted against, observed red for the
intended reason, and reverted; each file was then verified byte-identical to its
pre-plant SHA-256. **The campaign's own lesson applies to this table: a guard you
author is not a guard you are subject to.** Where a plant revealed that a guard
would *not* have fired, the guard was widened and re-planted, and that is
recorded here rather than quietly fixed.

**Two of them did**, and both are in the table. Neither was found by review.

### The Swift contract checks — nine plants

Each was applied to one file, observed, and restored with `git checkout --`;
every restored file was verified byte-identical to its pre-plant SHA-256. A red
Swift check exits **133** because an uncaught error at top level traps.

| # | Plant | What went red | Exit |
|---|---|---|---|
| R1 | `requireConsent` treats `.notDetermined` as granted — the "try it and see" change | `ContractCheckError.failed("Expected provider failure permissionDenied")` | 133 |
| R2 | `:` added to `MailIdentityComponent`'s alphabet | `…failed("A colon in an identity component would make composition ambiguous")` | 133 |
| R3 | `recordIdentifier()` composes mailbox and key without the generation | `…failed("A generation change left identities unchanged; a stale key would now resolve to a different message")` | 133 |
| R4 | The `publishesGeneration` guard deleted | `…failed("Expected error mailGenerationUnavailable")` | 133 |
| R5 | `clientSideAfterFullScan` returns `nil` instead of throwing — "just filter it here" | `…failed("A client-side-only mechanism was enumerated before being refused")` | 133 |
| R6 | `bodyFits` forced true, so an oversize body is carried | `NativeSourceContractError.mailBodyTooLarge` | 133 |
| R7 | The wire invariant weakened from `==` to `<=`, admitting a short body | `…failed("Malformed MailRecordContent decoded successfully")` | 133 |
| R8 | The strict-ascending re-check deleted | `…failed("Expected error nonCanonicalOrder")` | 133 |
| R9 | An omitted body's first 64 bytes appended to the record's headers "as a preview" | **first attempt: nothing.** `PASS (21 checks)`, exit 0. After correction: `…failed("The oversize body's first bytes reached the record's headers; an omitted body must be omitted, not previewed somewhere else")` | 0, then 133 |

**R9 is the blind spot, and it is worth stating exactly.** The oversize-body check
decoded the record payload as UTF-8 and searched the resulting string for the
planted marker. Every byte-bearing field on this wire encodes to a **JSON array
of decimal numbers**, so the marker's characters are never present as characters
no matter what leaks — the assertion could not have failed for any input. It now
searches **bytes**, in the record's headers and in the raw payload, and R9
reddens. R6 is a weaker plant than it looks for the same reason: it is caught one
layer earlier, by `MailRecordContent`'s own invariant, so it never reaches the
marker search. R9 is what proves the marker search.

### The architecture guards — thirteen plants, one file each

Observed as `pytest tests/architecture/test_wp16_mail_adapter.py -q`; the module
holds thirteen tests, so a healthy plant reads **1 failed, 12 passed**.

| # | Plant | Guard that went red |
|---|---|---|
| P1 | `MailMechanism.swift` moved out of the tree | `test_the_mail_scan_is_reading_the_adapter_at_all`, plus three others — **4 failed, 9 passed**. SHA-256 `6be4242d…f726` matched on restore |
| P2 | `func markAsRead` added to the seam | `test_the_mail_mechanism_seam_declares_only_read_operations` — `At index 3 diff: 'markAsRead' != 'messageContent'` |
| P3 | `requestAuthorization()` added to the fixture mechanism | `test_the_mail_seam_cannot_ask_for_a_permission_it_does_not_have` |
| P4 | `import ScriptingBridge` added to `Tests/AppleSourceHostContractChecks` — **outside** `Sources/AppleSourceHost`, which is the WP-15 blind-spot shape | `test_no_swift_outside_the_automation_probe_can_send_an_apple_event` |
| P5 | The shipping target given `dependencies: ["AppleMailAutomationShapeProbe"]` | **first attempt: nothing. 13 passed.** See below |
| P5a | Same plant, corrected guard | `AppleMailAutomationShapeProbe is named 2 times in Package.swift as a quoted token…` |
| P5b | The shipping target given `dependencies: ["AppleFrameworkCompatibilityProbe"]` — **WP-15's probe** | Same guard, naming `AppleFrameworkCompatibilityProbe` |
| P5c | The contract-check executable given the automation probe as a dependency | Same guard |
| P5d | The manifest reformatted to multi-line with **no** dependency added | Correctly **green**. A reformat is not a violation and the corrected guard does not pretend it is |
| P6 | `maximumMailBodyBytes` drifted to `262_145` | `test_the_mail_content_bounds_exist_and_are_frozen_in_the_protocol` |
| P7 | `MailDayWindow`'s `init(from:)` deleted | `test_every_mail_content_bound_is_enforced_on_the_decode_path_too` |
| P8 | `date received`'s code changed to `rdrx` in the probe's table | `test_the_probe_read_shape_is_read_only_in_apples_own_dictionary` — `[(('message', 'date received', 'rdrx'), ('rdrc', 'r'))] disagree with Apple's dictionary…` |
| P9 | `account.password` swapped for the read-only `account type` in the mutation table | `test_apple_mail_consent_cannot_withhold_the_mutation_surface` — `…does not declare it settable` |
| P10 | `NSAppleEventsUsageDescription` added to a string literal in the native tree | `test_no_entitlement_or_usage_declaration_was_added_for_the_mail_mechanism` |
| P11 | The wire invariant weakened from `==` to `<=` | `test_a_mail_body_is_carried_whole_or_omitted_whole_and_never_trimmed` |
| P12 | `:` added to the identity alphabet | `test_the_mail_identity_alphabet_excludes_the_composition_separator` |
| P13 | The `publishesGeneration` guard deleted | `test_a_mechanism_that_publishes_no_generation_cannot_be_read_from` |

### P5, and a finding about a guard this package did not author

**The plant that mattered most stayed green, and so did WP-15's.**

The first form of the manifest guard split `Package.swift` on
`name: "AppleSourceHost"` and read to the next `),`. That split does not land on
the target — it lands on the **product** declaration a few lines above it, whose
section closes before any dependency list. Giving the shipping target a
dependency on the automation probe therefore left the guard green.

Then the same plant was run against **WP-15's**
`test_the_compatibility_probe_is_compile_only_and_never_linked_into_the_host`,
with `AppleFrameworkCompatibilityProbe` in the dependency list. It stayed green
too: `28 passed`, both modules, with the shipping target depending on both
probes. That is measured, not inferred, and it means **WP-15's control 1 — the
strongest guarantee in the native host, that the shipping module links no Apple
framework — was defended by a Python guard that a one-line manifest edit walks
past.** The Swift build succeeds; the module links EventKit, Contacts, MailKit
and ScriptingBridge; nothing goes red.

The correction is a **count** rather than a walk: a probe target's name may
appear as a quoted token in `Package.swift` exactly once, in its own `name:`. A
dependency entry, a product membership or a target list is a second occurrence,
whatever the formatting. WP-16's guard now counts both probes, so WP-15's claim
is covered here.

**WP-15's test was not edited, weakened, or excused**, and its blind spot is
reported rather than silently patched over — the next owner of that file should
decide whether to fold the count into it or leave the coverage here.

---

## G. Verification at this head

Every number below was produced here, at this head. The base figures are
re-derived rather than copied from WP-15's record: the full suite was run at the
base head `f121816` before any edit, and the architecture base is measured at
this head with only the new module excluded, so the delta is an observation of
one tree rather than a comparison across two.

| Command | Exit | Observed |
|---|---|---|
| `swift build` (after `rm -rf .build`) | 0 | `Build complete!` — **0 warnings, 0 errors**, 35 build steps including both probes |
| `.build/debug/AppleSourceHostContractChecks` | 0 | `AppleSourceHostContractChecks: PASS (21 checks)` — was **14** at the base |
| `.build/debug/AppleSourceHostFixtureExport` | 0 | unchanged export |
| `pytest tests/architecture -q` | 1 | **2045 passed, 1 failed.** Base measured at this head with `--ignore` of the new module: **2032 passed, 1 failed**. 2032 + 13 = 2045 |
| `pytest tests/schema tests/database -q` | 0 | **286 passed** — identical to the base; this package adds no test there |
| `pytest -q` (full) | 1 | **4649 passed, 1 failed, 0 errors.** Base at `f121816`, run before any edit: **4636 passed, 1 failed**. 4636 + 13 = 4649, and the 13 are the new architecture module in full |
| `ruff check .` | 0 | All checks passed |
| `ruff format --check .` | 0 | **586 files** already formatted — 585 at the base plus the one module added |
| `mypy` per repo config | 0 | no issues in **177 source files** — unchanged, because no Python source was added |
| `alembic heads` | 0 | `8f2b6c4d1a37 (head)` over **26** revision files — unchanged |

**The one failure is the pre-existing, unowned one**,
`test_ci_invokes_mypy_over_the_declared_tree.py::test_every_python_root_is_type_checked_or_named`,
which is red at the base head for `web/node_modules` and is not this package's.
No test was weakened, skipped, xfailed or deleted to reach any of these numbers.
