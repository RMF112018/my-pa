# WP-17 — Apple Calendar Live Adapter

> **Current-head correction (2026-08-12 pilot remediation).** This historical
> record accurately describes WP-17's original proof, but its statements that no
> EventKit mechanism exists in the repository are no longer current. The
> separately bounded `AppleSourceHostPlatform` product now contains an injected,
> read-only EventKit mechanism and inert composition. It creates no store,
> requests no TCC grant, names no mutation, and repository validation reads no
> live calendar. The framework-free core and all original adapter refusals remain.
> Current candidate scope and external gates are recorded in
> `PILOT-BLOCKER-REMEDIATION-20260812.md`.

Branch: `bf/wp-17-apple-calendar-adapter`. Base: `fd333da46a20447d67b99c115023a7a9bdc41464`.

This record states what WP-17 proved, **at what level it proved it**, and what it
could not prove without an operator. It follows WP-15's and WP-16's shape because
that shape is the point: a compiled guarantee, a link-time guarantee, a runtime
observation and a document are four different things, and a package that blurs
them is worth nothing.

**The headline is not a feasibility finding, and that is the difference from
WP-16.**

> EventKit **is** a real, documented, public read API. It enumerates sources,
> calendars and events; it expands recurrence for you; it publishes an
> occurrence's originally scheduled start, an all-day flag, a per-event time
> zone, a detached flag and a cancellation *status*. WP-16's headline was a
> negative — no mechanism existed. WP-17's is not: the mechanism exists, and
> `Compatibility/AppleCalendarEventKitProbe` makes the compiler re-prove it on
> every build.
>
> What is missing is **consent**. Reaching a calendar needs a TCC grant only a
> human can give, and this package must not obtain one, ask for one, or read a
> calendar. So the adapter is built and proved against a **mechanism seam**
> driven by a store this harness seeded itself, in one process, with no event
> store ever constructed.
>
> **No calendar belonging to anyone was read to produce any line of this record,
> and nothing here may be read as if one had been.**

---

## A. The six controls, and the level each is proved at

**Read the "Proved at" column as the claim.** Nothing in this document upgrades a
level in a later restatement.

| # | Control | Verdict | Proved at | Where |
|---|---|---|---|---|
| 1 | **Stable account / calendar / series / occurrence identity** | **Proven, four levels, injective, anchored to the original scheduled start** | **Swift runtime, in-process** for behaviour; **Python-structural** for the alphabet and the key shape | `AppleSourceHostContractChecks::checkCalendarIdentityIsFourLevelInjectiveAndAnchoredToTheOriginal`; `test_the_calendar_identity_alphabet_excludes_the_composition_separator` |
| 2 | **Permissions fail closed** | **Proven, including the empty-vs-unavailable distinction** | **Swift runtime, in-process** for the refusal and the zero-read measurement; **Python-structural** for the exhaustive `switch` with no `default` | `::checkCalendarAuthorizationFailsClosedAndIsNotAnEmptyPage`; `test_calendar_authorization_fails_closed_and_cannot_degrade_to_an_empty_page` |
| 3 | **Recurrence semantics** | **Proven against a wall-clock rule: expansion, exceptions, detached instances, and an exception that names no scheduled start refused** | **Swift runtime, in-process** | `::checkCalendarRecurrenceExpandsAndCancellationIsNotAnAbsence` |
| 4 | **Cancellation is represented, not absent** | **Proven, and a defect at the base was found and fixed — see §C** | **Swift runtime, in-process**, in both expanders and through the adapter; **Python-structural** against re-introducing the drop | `::checkCalendarRecurrenceExpandsAndCancellationIsNotAnAbsence`, `::checkCalendarCancellationSurvivesTheAdapterAndIsNotFilterable`, `::checkRecurrenceIdentityAndBounds`; `test_a_cancelled_occurrence_is_representable_and_is_never_dropped` |
| 5 | **All-day and timezone semantics** | **Proven: DST gap, repeated hour, foreign zone, whole-day-for-every-reader, and a wall-clock-stable series whose instants shift** | **Swift runtime, in-process**, against the platform's own zone database; **Python-structural** for the "no instant field" invariant | `::checkCalendarAllDayAndForeignZoneSemantics`, `::checkCalendarDaylightSavingGapRepeatedHourAndStableWallClock`; `test_an_all_day_span_has_nowhere_to_put_an_instant` |
| 6 | **Read-only API surface** | **Proven at Swift link time, unchanged from WP-15** | **Swift link-time** (the shipping target links no Apple framework — `otool -L` below), plus **Swift compile-time** for the probe, plus static guards over every Swift file under `native/` | `test_no_swift_outside_the_probes_can_reach_an_event_store`, `test_the_calendar_mechanism_seam_declares_only_read_operations`, `test_the_three_probes_are_compile_only_and_never_linked_into_the_host`; WP-15's `test_the_shipping_host_holds_no_write_path_into_an_apple_source` still passes |
| — | **A live read of a real calendar** | **NOT PROVED, and nothing in this package attempts it.** No `EKEventStore` is constructed anywhere in this repository, no authorization is requested, and no calendar was enumerated. Every behavioural claim above is over a seeded in-process fixture | **Nowhere.** Needs an operator TCC grant on real hardware — see §F | — |
| — | **Performance** | **NOT PROVED.** The fixture's timings are the fixture's, not a calendar store's, and they are not reported here for that reason | **Nowhere** | — |

---

## B. What the shipping target links after this change

`swift build` from clean, then `otool -L` on the two products SwiftPM actually
links. This is WP-15's control 1, re-derived at this head rather than cited.

```
.build/debug/AppleSourceHostContractChecks:
	/usr/lib/libSystem.B.dylib
	/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation
	/usr/lib/libobjc.A.dylib
	/usr/lib/swift/libswiftCore.dylib
	/usr/lib/swift/libswiftCoreFoundation.dylib (weak)
	/usr/lib/swift/libswiftDarwin.dylib
	/usr/lib/swift/libswiftDispatch.dylib
	/usr/lib/swift/libswiftIOKit.dylib (weak)
	/usr/lib/swift/libswiftObjectiveC.dylib (weak)
	/usr/lib/swift/libswiftXPC.dylib (weak)
```

`.build/debug/AppleSourceHostFixtureExport` is the same list. **No EventKit, no
Contacts, no MailKit, no ScriptingBridge, no ServiceManagement.** Byte-identical
to the base head's list; adding a calendar adapter changed nothing about it.

`swift package describe --type json` reports all three probes as `library`
targets with `product_memberships: null`, while the only two executables depend
on `AppleSourceHost` alone. So nothing links them, and the probes' claim stops at
**compilation**, which is the level stated everywhere in this document.

**This property is defended, and the defence is measured.** §G's plant R-P6 gives
the shipping target `dependencies: ["AppleCalendarEventKitProbe"]`; the build
still succeeds and `otool -L` then shows
`/System/Library/Frameworks/EventKit.framework/Versions/A/EventKit` linked into
the product. The guard reddens on it. That is the whole point of the guard, and
it is the first time in this campaign the *consequence* of that plant has been
shown at link level rather than argued.

---

## C. The three leads, verified

### Lead A — confirmed, and it was a real defect

`NativeRecurrenceExpander.expand` computed

```swift
let cancelled = exception != nil && exception?.replacementStartUnixMilliseconds == nil
...
if !cancelled && overlaps { result.append(...) }
```

so a cancelled occurrence was **omitted from the expansion entirely**. Downstream
that is indistinguishable from an occurrence the series never had. "The 10:00
stand-up was cancelled" and "there was never a 10:00 stand-up" lead to different
actions, and the consumer could not recover the first from the second.

**Fixed additively.** `NativeCalendarOccurrence` gained
`lifecycle: CalendarOccurrenceLifecycle` — `confirmed`, `cancelled`, `detached` —
and the expander now emits the cancelled occurrence carrying the slot it was
cancelled from. The stored `isException` flag became a computed property derived
from the lifecycle, which removes the state in which the two could disagree.

**Three existing assertions in `Tests/AppleSourceHostContractChecks/main.swift`
changed, and they are named here rather than quietly edited.** All three are in
`checkRecurrenceIdentityAndBounds`, over a four-occurrence series with one moved
and one cancelled instance:

| Assertion | Old expectation | New expectation | Why |
|---|---|---|---|
| the expansion bound passed to `expand` | `maximumOccurrences: 3` | `maximumOccurrences: 4` | the series has four occurrences and four are now emitted; three would now hit the ceiling |
| `occurrences.count == 3` | `3` | `4` | the cancelled occurrence is present |
| the scheduled-start list | `[first, first + day, first + (3 * day)]` | `[first, first + day, first + (2 * day), first + (3 * day)]` | `first + 2*day` is the cancelled slot, which used to be missing from the result |

Nothing was deleted or loosened. Two assertions were **added** in the same block:
the lifecycle sequence is `[.confirmed, .detached, .cancelled, .confirmed]`, and
the cancelled occurrence still carries its original start and end. The old
expectations are written into the source as a comment so the next reader sees the
correction rather than inferring it.

`test_a_cancelled_occurrence_is_representable_and_is_never_dropped` now fails if
the drop is re-introduced, in either expander or by a `filter` in the adapter
(plants R-P14 and R-P15).

### Lead B — confirmed

`NativeCalendarOccurrence` was the only type in `Recurrence.swift` with a
**synthesized** `Codable`; its two siblings had hand-written validating decoders.
Its invariants were therefore bypassable off the wire, which is the exact defect
WP-15 fixed for the page and cursor ceilings and WP-16 fixed for the mail content
bounds. It now has a throwing initialiser and an `init(from:)` that routes through
it, and the invariant it carries is the one that keeps identity honest: a
`confirmed` occurrence must start where its identity says the series scheduled it.

`tests/architecture/test_wp12_slice_d_native_host.py` counts the validating
decoders in that file. Its own comment says *"Raising this number is the only
direction it may ever move without deleting a decoder"* — so the count moved from
two to three, in the sanctioned direction, with the reason recorded in the test.

### Lead C — confirmed

There was no account level. `NativeRecurrenceSeries` carried `bucketID` and
`seriesID` and nothing above them. WP-17 adds four levels in
`CalendarIdentity.swift`:

| Level | Type | Composed form | Separators |
|---|---|---|---|
| account | `CalendarAccountIdentity` | `account` | 0 |
| calendar (bucket) | `CalendarBucketIdentity` | `account:calendar` | 1 |
| series | `CalendarSeriesIdentity` | `account:calendar:series` | 2 |
| occurrence | `CalendarOccurrenceIdentity` | `account:calendar:series:<key>` | 3 |

Injectivity comes from two facts together: the component alphabet **excludes
`:`**, so a composed identifier splits back into its fields unambiguously; and the
separator count alone says which level an identifier is, so a series and one of
its occurrences cannot collide however the components are chosen. Each level is a
strict prefix of the one below it, which is asserted rather than assumed.

Composition **refuses** rather than trimming: four maximum-length components
genuinely exceed `NativeSourceOpaqueID`'s 200-byte ceiling, so
`calendarIdentityTooLong` is a reachable path and not decoration.

---

## D. The three things a calendar adapter usually gets wrong

### 1. The occurrence key, and why it is the original start

An occurrence is keyed by **the start the series originally scheduled it for**,
never by the start it currently has. A detached instance moved from Tuesday to
Thursday keeps its Tuesday key: it is the same occurrence, moved. Keying by the
actual start would make the move read as a *deletion and a creation* — the
Tuesday occurrence vanishes, an unrelated Thursday one appears — and every
downstream reconciler would believe it. Both directions are asserted: the moved
occurrence keeps its identifier, and a genuinely different occurrence scheduled
at the moved time does not share it.

The key is rendered as a **biased, fixed-width, order-preserving decimal**:
`UInt64(bitPattern:) ^ 0x8000_0000_0000_0000`, zero-padded to twenty digits. Both
halves are needed. Without the bias, instants before 1970 sort after instants
after it; without the padding, `String(-1)` sorts before `String(-2)` and after
`String(10)`. Either way a cursor resumes in the wrong place, which is silent
loss that looks like an empty page.

### 2. All-day, which is not an instant

`CalendarAllDaySpan` holds two `CalendarDate`s and **has no instant field at
all**. That is the enforcement mechanism, not a convention: "midnight local" is
not a value the type can take, in any zone, for any reader. It is the same shape
WP-15 used for content-free telemetry — the bound is that there is nowhere to
write the wrong value — and `test_an_all_day_span_has_nowhere_to_put_an_instant`
asserts every stored property of it is a date.

A UTC-windowed read still has to decide overlap, so the span publishes the widest
instant range any zone on Earth could place it in: UTC+14 on the leading edge,
UTC−12 on the trailing one. **Outward only**, exactly as `MailDayWindow.widening`
is. Narrowing would drop an all-day event for a reader in the wrong hemisphere;
widening at worst admits a record the caller can see. The contract check runs the
overlap for readers at UTC−12, −5, 0, +1, +9 and +14 and requires the day to be
visible from all of them.

An identity anchor is still needed, and it is `epochDay × 86 400 000` — a pure
function of the date, identical for every reader. It is called
`identityAnchorUnixMilliseconds` and not `startUnixMilliseconds` because it is
not a time the event happens, and an all-day occurrence anchored to anything
other than a whole day is refused at `init` and on the decode path.

### 3. DST, which has three answers and not one

`CalendarTimedInterval` holds **the instant as the authority** and the wall clock
as a *derived, verified* companion: the initialiser recomputes the wall clock from
the instant in the event's own zone and refuses the value if the two disagree. So
a foreign-zone event keeps its own zone rather than the reader's, and this is
asserted against hard-coded Paris values that a leaked host zone could not
produce.

`CalendarZone.resolve(_ wallClock:in:)` returns one of three answers, because a
DST transition genuinely produces three:

| Case | When | What this package does |
|---|---|---|
| `skipped` | 02:30 on 2026-03-08 in `America/New_York` — the spring-forward gap | The series is **refused** (`calendarScheduleInconsistent`). Every way of continuing invents an instant, and an invented instant is indistinguishable from a real one once it is in a record |
| `unique` | Every ordinary day | The instant |
| `ambiguous` | 01:30 on 2026-11-01 in `America/New_York` — the fall-back repeated hour | Two instants, an hour apart, at two different UTC offsets. The **earlier** is taken, and the choice is a named constant rather than whichever comparison ran first |

Each candidate offset is confirmed by round-tripping it — an offset is accepted
only if the instant it produces is genuinely at that offset — which is what makes
the gap answer `skipped` rather than a plausible instant an hour away.

**The load-bearing case is the series.** A 09:00 daily series in
`America/New_York` is stable in *local* time across a transition, so its UTC
instants are **not** evenly spaced: the check requires a step of 82 800 000 ms
across the March transition and 90 000 000 ms across the November one, 86 400 000
either side of both, with every occurrence still at 09:00 local. A
fixed-millisecond expander — which is what the WP-14 `NativeRecurrenceExpander`
is, correctly, for a series *defined* in UTC — walks such a series an hour off for
half the year. That is why `CalendarSeriesExpander` is defined on wall clocks and
why the two expanders both exist; see §H.

---

## E. The bounded horizon, and honest truncation

| Bound | Value | Behaviour | Why |
|---|---|---|---|
| `maximumCalendarHorizonDays` | 366 | Request **refused** (`calendarHorizonExceeded`) | A horizon quietly clipped from ten years to one returns a page indistinguishable from "nothing is scheduled after next spring" |
| an absent time range | — | **Refused** (`calendarHorizonExceeded`) | A calendar has no natural end, so "no bound" is not a wider read; it is the unbounded enumeration the horizon exists to prevent. `CalendarTraversalQuery` has nowhere to put "no window" |
| `maximumCalendarSeriesOccurrences` | 512 | Expansion **refused** (`recurrenceLimitExceeded`) | A series cut mid-expansion loses occurrences no cursor describes |
| `maximumPageSize` / `maximumCursorBytes` | 100 / 512 | Refused, unchanged from WP-15 | Reused rather than re-minted, so the host and the admitting application cannot drift. Asserted against the Python contract's own constants |
| `maximumCalendarIdentityComponentBytes` | 64 | Composition **refused** (`calendarIdentityTooLong`) | A trimmed identity aliases two occurrences onto one record |

Every one of these is enforced on the initialiser **and** on the decode path. A
bound that only exists on an initialiser holds for values built in Swift and not
for the same values arriving as JSON, which is the shape a host is actually handed.

**Truncation is declared and the declaration is cross-checked.**
`CalendarTraversalResult.moreAvailable` is the explicit signal, and the adapter
refuses a result whose signal and page disagree: a mechanism claiming more must
have filled the page (a short page with more behind it is incoherent) and must
have left an occurrence to resume from. Paging the fixture calendar in twos is
asserted to reproduce the single-page read exactly, with no duplicate and nothing
missing.

**What this does not prove, stated plainly.** A mechanism that truncates and
reports `moreAvailable == false` is **undetectable from the adapter** — nothing
downstream of a source can tell a suppressed record from one that never existed.
The adapter enforces the half that is detectable and the seam documents the half
that is a contract. The same is true of the suppressed-cancellation fault: the
harness catches it by *comparing two reads*, not by the adapter noticing, and the
check says so in as many words.

Six mechanism faults are injected so the adapter's re-checks are exercised rather
than merely written: ignoring the window (`calendarHorizonViolated`), enumerating
the whole store (`calendarUnboundedEnumeration`), returning keys out of order
(`nonCanonicalOrder`), claiming more without filling the page
(`calendarTruncationUndeclared`), answering with another calendar's occurrences
(`unknownBucket`), and suppressing cancellations (measured by comparison).

---

## F. What requires an operator, and what each would unlock

| Gate | What is missing | Would unlock |
|---|---|---|
| **EXT-04** | A TCC calendar grant for the helper on a pilot Mac | Everything this package refuses to guess at: whether `EKSource`/`EKCalendar`/`EKEvent` identifiers are stable across a restart and across an account re-sync; whether `occurrenceDate` is populated for every provider's detached instances; whether a CalDAV-backed calendar reports cancellation as `EKEventStatus.canceled` or by deletion; whether `predicateForEvents(withStart:end:calendars:)` is index-backed at usable speed |
| **EXT-03** | Apple signing identity, notarization profile, and an `Info.plist` carrying `NSCalendarsFullAccessUsageDescription` | Any of the above at all, since an unsigned helper cannot hold a durable TCC grant |
| **EXT-05** | An eligible pilot Mac and `SMAppService` registration | Lifecycle evidence for the helper that would host the mechanism |
| **EXT-06** | An approved non-personal Apple test account with seeded synthetic events | The only honest way to measure performance and horizon behaviour. **No live personal calendar may be used for this, and none was** |
| — | A decision, not a grant: whether an EventKit mechanism is written at all | The seam is implemented by a fixture and by nothing else in this repository. Writing a live one means linking EventKit somewhere, and *where* is an architectural decision this package deliberately does not take |

**macOS 14 splits calendar consent into `fullAccess` and `writeOnly`, so a
read-only *grant* is possible.** A read-only *framework* is not: one event store
answers both `events(matching:)` and `save(_:span:commit:)`. So the enforceable
read-only boundary is still the client not linking EventKit, which is what §B
measures. The package floor is macOS 13 (`SMAppService`, OD-COMP-009), where the
older single `authorized` status is all there is; `CalendarAuthorizationState`
names the four states both versions agree on, so the adapter does not depend on
which one a host runs.

---

## G. Non-vacuity — controlled reversions

Every guard authored by this package was planted against, observed red **for the
intended reason**, and reverted; each file was then verified byte-identical to its
pre-plant SHA-256. **The campaign's own lesson applies to this table: a guard you
author is not a guard you are subject to**, and WP-16's reviewer proved three of
that package's guards vacuous after it had said the same thing. So the plants
below include the shapes that defeated WP-16's first drafts — a two-line property
declaration, an inherited mutation surface, a decoder that keeps its signature and
loses its validation — and a **control** plant that must stay green.

A red Swift check exits **133** because an uncaught error at top level traps. A
healthy architecture plant was **1 failed, 13 passed** in
`tests/architecture/test_wp17_calendar_adapter.py` when this table was produced;
the module holds sixteen tests after the correction in §K, so the same shape now
reads **1 failed, 15 passed**.

**This table did not save the package from the review.** It is left exactly as it
was written, because the honest reading of it is the point: every plant in it
reddened, and four of the guards it vouched for were still incomplete. §K is what
that cost.

### The Swift contract checks — eleven plants

| # | Plant | What went red | Exit |
|---|---|---|---|
| R-S1 | `requireAuthorization` treats `.notDetermined` as authorized — the "try it and see" change | `…failed("Expected provider failure permissionDenied")` | 133 |
| R-S2 | A detached occurrence keyed by its **moved** start rather than its original | `…failed("The detached occurrence did not move")` | 133 |
| R-S3 | The WP-14 expander drops cancelled occurrences again (`if !cancelled && overlaps`) | `…failed("Cancellation did not preserve bounded expansion")` | 133 |
| R-S4 | `CalendarSeriesExpander` drops cancelled occurrences | `…failed("The expansion produced 4 occurrences; a cancelled one was dropped")` | 133 |
| R-S5 | The spring-forward gap resolves to an instant instead of refusing | `…failed("A wall clock inside the spring-forward gap resolved to an instant")` | 133 |
| R-S6 | The horizon clamps with `min(...)` instead of refusing | `…failed("Expected error calendarHorizonExceeded")` | 133 |
| R-S7 | An undeclared truncation returns `nil` instead of throwing | `…failed("Expected error calendarTruncationUndeclared")` | 133 |
| R-S8 | `CalendarOccurrence` drops the confirmed-anchor invariant | `…failed("Expected error calendarLifecycleInconsistent")` | 133 |
| R-S9 | An all-day span bounded as if it were midnight UTC | `…failed("The all-day span narrowed its eastward bound")` | 133 |
| R-S10 | `CalendarTimedInterval` stops re-deriving its wall clock from its instant | `…failed("Expected error calendarScheduleInconsistent")` | 133 |
| R-S11 | **WP-16's C3 shape**: `CalendarOccurrence.init(from:)` rewritten to assign its four fields directly, keeping the literal a naive guard looks for | `…failed("Malformed CalendarOccurrence decoded successfully")` | 133 |

### The architecture guards — nineteen plants, one file each

| # | Plant | Guard that went red |
|---|---|---|
| R-P1 | `func removeOccurrence(...)` added to the seam | `test_the_calendar_mechanism_seam_declares_only_read_operations` |
| R-P2 | `var isCancelled: Bool { get set }` added to the seam | same guard, on the settable-property assertion |
| R-P2b | The same property with its accessor block **on the next line** — the shape WP-16's first draft could not see | same guard, same assertion |
| R-P3 | `subscript(cancel key: String) -> Bool { get set }` added to the seam | same guard, on the subscript assertion |
| R-P4 | `public protocol CalendarMechanism: Sendable, CalendarMutating` — a mutating **parent**, whose requirements arrive without appearing between the braces | same guard, on the inheritance assertion |
| R-P5 | `import EventKit` added to `Tests/AppleSourceHostContractChecks` — **outside** `Sources/`, which is the WP-15 blind-spot shape | `test_no_swift_outside_the_probes_can_reach_an_event_store` |
| R-P6 | The shipping target given `dependencies: ["AppleCalendarEventKitProbe"]` | `test_the_three_probes_are_compile_only_and_never_linked_into_the_host`. **And the consequence was measured**: with the plant in place the build succeeds and `otool -L` shows `EventKit.framework` linked into the product. Reverted, it is gone |
| R-P6b | The same plant naming `AppleFrameworkCompatibilityProbe` — WP-15's probe | same guard |
| R-P6c | **CONTROL**: the manifest reformatted to multi-line with **no** dependency added | Correctly **green — 14 passed**. A reformat is not a violation and the count guard does not pretend it is |
| R-P7 | The EventKit probe emptied of its first member | `test_the_event_kit_probe_resolves_symbols_and_reaches_no_store`, on the metatype floor |
| R-P7b | The probe's `\EKEvent.occurrenceDate` key path removed | same guard, on the named-member assertion |
| R-P8 | `maximumCalendarHorizonDays` drifted to `367` | `test_the_calendar_bounds_are_frozen_in_the_protocol_and_agree_with_python` |
| R-P9 | `public let startUnixMilliseconds: Int64` added to `CalendarAllDaySpan` | `test_an_all_day_span_has_nowhere_to_put_an_instant` |
| R-P10 | The `.restricted` arm returns instead of throwing | `test_calendar_authorization_fails_closed_and_cannot_degrade_to_an_empty_page` |
| R-P11 | `CalendarOccurrence.init(from:)` assigns its fields directly | `test_every_invariant_bearing_calendar_value_validates_on_the_decode_path` — and R-S11 above, which is the claim; the static guard is the addition |
| R-P12 | `:` added to the calendar identity alphabet | `test_the_calendar_identity_alphabet_excludes_the_composition_separator` |
| R-P13 | `NSCalendarsFullAccessUsageDescription` added to a string literal in the native tree | `test_no_entitlement_or_usage_declaration_was_added_for_the_calendar_mechanism` |
| R-P14 | The WP-14 expander's cancelled-drop restored | `test_a_cancelled_occurrence_is_representable_and_is_never_dropped` |
| R-P15 | The adapter filters cancelled occurrences out of the page it returns | same guard, on the `filter` assertion |
| R-P16 | A fourth Swift file added to a probe directory | `test_the_wp17_scan_is_reading_the_calendar_adapter_at_all`, on the exemption-set floor |

Every plant was reverted with `git checkout --` (or `rm` for R-P16) and every
restored file verified byte-identical by SHA-256. **No plant remains in the tree**;
`git status` is clean at the head below and the full suite is green at the numbers
in §I.

---

## H. What WP-17 deliberately did not do, and what it leaves standing

* **No live mechanism.** The seam has one implementation, `FixtureCalendarMechanism`,
  and it is seeded by hand. Writing an EventKit one requires the consent this
  package refuses to obtain and a decision about which target may link the
  framework.
* **No occurrence content.** There is no title, location, attendee, organiser or
  note field anywhere in the calendar types. WP-17's acceptance names none, and a
  content field nothing needs is a content field that eventually holds somebody's
  calendar in a public repository. A future package that needs one owns bounding
  it, in WP-16's shape.
* **No baseline plane, no migration, no schema change, no capability seat.** The
  single Alembic head remains `8f2b6c4d1a37` over 26 revisions and the capability
  set remains nineteen. `git diff fd333da..HEAD -- src/ apps/ scripts/ migrations/ ops/`
  is empty.
* **The native plane stays quarantined.** Nothing here is reachable from a
  transport and no production module references any of it.
* **Two recurrence expanders now exist, and that is a known duplication.**
  `NativeRecurrenceExpander` expands a series defined by a fixed UTC interval;
  `CalendarSeriesExpander` expands a series defined by a local wall clock in a
  named zone. They answer different questions — the second is the only one that
  can represent a series whose local time is stable across a DST transition — and
  the first could not be extended to the second without changing a validated type
  that existing contract checks assert on. The WP-14 pair is used by nothing but
  the contract checks today. **Whoever next owns `Recurrence.swift` should decide
  whether the UTC-interval expander still earns its place**; this package fixed
  its two defects rather than deleting assertions to remove it.
* **WP-15's control-1 exemption set was widened by one directory**, from one
  compile-only probe to two, so that the EventKit probe can import EventKit. The
  *assertion* is unchanged — every Swift file under `native/` outside the
  compile-only probes may still name no mutating Apple symbol — and the new probe
  is held to the same standard by `test_the_event_kit_probe_resolves_symbols_and_reaches_no_store`.
  The widening is measured: `test_the_wp17_scan_is_reading_the_calendar_adapter_at_all`
  requires the exemption set to be exactly three files, so a fourth is a decision
  somebody has to make here (plant R-P16).
* **`CalendarMechanismKind.eventKitStore` is declared and never constructed.** It
  names the mechanism a live implementation would declare, in the shape
  `MailMechanismKind.appleMailAutomation` already established. If the next owner
  judges that dead under §2, it is one line.
* **The seam guard scans from `public protocol CalendarMechanism` to the end of
  the file**, which is safe only because that protocol is the last declaration in
  `CalendarMechanism.swift`. A declaration added below it would be scanned as if
  it were part of the seam. That direction fails safe — it reddens on something
  legal rather than passing something illegal — and it is deliberately not
  bounded to the protocol's closing brace, for WP-16's reason: bounding it would
  stop a second protocol carrying `func delete()` from being seen at all.

  **What this bullet did not disclose, and what the correction changed.** The
  scan read *one file*. A Swift protocol is not confined to the file that
  declares it: `extension CalendarMechanism { func removeOccurrence(…) }` in any
  other file puts that operation on every conformer of the seam without touching
  `CalendarMechanism.swift`, and WP-17's reviewer planted exactly that and
  watched the suite stay green. The guard now finds the declaration and every
  protocol extension of it across the whole native tree, and holds the union to
  the same closed operation and property sets. The declaration keeps its
  scan-to-end-of-file behaviour, above; an extension is read to its own balanced
  closing brace instead, because an extension is not the last declaration in an
  arbitrary file and scanning to the end of one would redden on unrelated code.

  **What is still trusted here.** The scan covers `native/apple-source-host`,
  which is every Swift file in this repository. A protocol extension declared in
  some future Swift package outside that directory would not be seen. Nothing
  today can be in that position, and no guard asserts that nothing ever will be.

---

## I. Verification at this head

Every number below was produced here, at this head. The base figures were
re-derived at `fd333da` before any edit rather than copied from WP-16's record.

| Command | Exit | Observed |
|---|---|---|
| `swift build --package-path native/apple-source-host` (after `rm -rf .build`) | 0 | `Build complete!` — **0 warnings, 0 errors**, all three probes compiled. The run ends at **`[44/44]`**, and the figure needs the caveat below rather than a bare number |
| `otool -L` on both linked products | 0 | libSystem, Foundation, libobjc and the Swift runtime. **No Apple framework** — see §B |
| `.build/debug/AppleSourceHostContractChecks` | 0 | `AppleSourceHostContractChecks: PASS (30 checks)` — was **22** at the base |
| `.build/debug/AppleSourceHostFixtureExport` | 0 | unchanged export |
| `pytest tests/architecture -q` | 1 | **2061 passed, 1 failed.** Base measured at `fd333da`: **2045 passed, 1 failed**. 2045 + 16 = 2061 |
| `pytest tests/schema tests/database -q` | 0 | **286 passed** — identical to the base; this package adds no test there |
| `pytest -q` (full) | 1 | **4665 passed, 1 failed, 0 errors.** Base at `fd333da`: **4649 passed, 1 failed**. 4649 + 16 = 4665, and the 16 are the new architecture module in full |
| `ruff check .` | 0 | All checks passed |
| `ruff format --check .` | 0 | **588 files** already formatted — 587 at the base plus the one module added. Measured over a clean `git archive` of each commit the figures are **586 → 587**; the extra file in the working tree is the single Python file under the gitignored `web/node_modules`, which is the same unowned root the one failing test below is about |
| `mypy` per repo config | 0 | no issues in **177 source files** — unchanged, because no Python source was added |
| Alembic revisions | — | single head `8f2b6c4d1a37` over **26** revision files — unchanged |
| Capability seats | — | **19** — unchanged |

**On the build-step figure.** This record said "39 build steps" at the first head
and that was a misreading, which is worth stating rather than silently editing:
SwiftPM revises the denominator *during* a single run as it discovers work, and
one clean build here prints `[13/40]`, `[25/40]`, `[33/44]` and finally `[44/44]`
— the numbers 15, 39, 40 and 44 all appear as denominators in one run. Reading a
mid-build line gives 39. Two clean builds at this head both end at `[44/44]`,
which is the total and the only figure worth quoting. It is still a
toolchain- and machine-dependent number: **treat it as evidence the build
completed with three probes compiled and no warnings, not as a constant.** The
stable facts are the exit code, the zero warnings, the zero errors, and the three
`Compiling …Probe` lines.

**The one failure is the pre-existing, unowned one**,
`test_ci_invokes_mypy_over_the_declared_tree.py::test_every_python_root_is_type_checked_or_named`,
which is red at the base head for `web/node_modules` and is not this package's.
**No test was weakened, skipped, xfailed or deleted to reach any of these
numbers.** Three existing assertions changed and all three are named — the three
rows in §C's table — and each changed because the semantics improved, not because
the assertion was inconvenient. One documentation count moved with the tree it
counts: `docs/plans/mcv-completion-plan.md` §3 now says one hundred and sixty-one
test modules rather than one hundred and sixty, which is what
`test_spelled_counts_match_the_sets_they_name.py` requires.

---

## J. The privacy boundary, stated as a fact rather than an intention

* No `EKEventStore` was constructed, anywhere, at any point. **This bullet was
  wrong in two ways at the first head and is corrected here.** The string appears
  in **two** Swift files, not one — this package's EventKit probe and WP-15's
  multi-framework probe, which holds `EKEventStore.self` as well — and in the
  calendar probe it appears in three positions, not two: as a metatype
  (`EKEventStore.self`, `EKEventStore.Type`), as the receiver of unapplied method
  references (`EKEventStore.events(matching:)` and its three siblings), **and as
  the parameter of the curried function types those unapplied references
  necessarily have** (`(EKEventStore) -> (NSPredicate) -> [EKEvent]`). The third
  is a type annotation and not a store, but it is a position and the earlier
  wording did not name it. What is true without qualification: no event store is
  constructed, no variable anywhere holds one, and
  `test_no_swift_in_the_native_tree_constructs_an_event_store` now scans every
  Swift file under `native/` — probes included — to keep all three facts true.
  The set of members of that type named anywhere in the tree is closed at six,
  every one of them a read or a metatype.
* No authorization was requested. `requestFullAccessToEvents` and every sibling
  are named nowhere in the tree, and a guard scans the **whole** native tree,
  probes included, to keep it that way.
* `~/Library/Calendars` was not read, listed, `stat`-ed or searched.
* No Apple event was sent.
* Every fixture value is obviously synthetic: `account-alpha`, `calendar-beta`,
  `Calendar Beta`, `series-alpha`. There is no title, attendee or location field
  in any calendar type, so there is nothing for a real one to be mistaken for.

---

## K. Correction after independent review

An independent review of the first head returned **0 BLOCKERs and 4 NOTEs**. All
four were guard-coverage or accuracy findings: no production code, migration,
schema or capability seat changed, and `git diff fd333da..HEAD -- src/ apps/
scripts/ migrations/ ops/ web/` is still empty. Two files changed —
`tests/architecture/test_wp17_calendar_adapter.py` and the probe's own docstring —
plus this record.

The common shape of all four is the one the campaign keeps re-learning: **a guard
that lists what is forbidden only forbids the spellings its author thought of.**
Three of the four corrections replace a forbidden list with a closed set.

### NOTE 1 — the probe's constraints were trusted, not enforced

The probe's docstring claimed the architecture test "enforces rather than trusts"
that nothing is instantiated and no mutating symbol appears. It did not. The
guard forbade `.save(`, `.remove(`, `EKEventStore(` and their siblings — the
**paren-suffixed** spellings only — so the reviewer planted `EKEventStore.save`
and `EKEventStore.remove` (valid *unapplied* method references; the parentheses
are optional once a type annotation disambiguates the overload) and
`EKEventStore.init()` (an actual construction). All three compiled and passed
every guard in the repository. That is a genuine enforcement failure and the
docstring's wording was the more serious half of it.

What replaced it:

* a **closed set of six members** of `EKEventStore` — `Type`, `self`, `events`,
  `calendars`, `predicateForEvents`, `authorizationStatus` — matched with
  `EKEventStore\s*\.\s*(\w+)`, so applied and unapplied spellings, whitespace
  variants and two-line forms are all one case rather than four. The equality is
  two-way: padding the allowlist with `save` does not admit `save`, it demands
  the probe name it;
* a **construction list** covering `EKEventStore(`, `EKEventStore.init`, a `let`
  or `var` of store type, a function *returning* a store, and a *parameter* of
  store type. `(EKEventStore) -> …` and `EKEventStore.Type` are excluded by
  construction: the first is the parameter of the curried function type an
  unapplied reference necessarily has, the second is a metatype;
* a **closed import set**. `"import EventKit" in source` is satisfied by
  `import EventKitUI` — the editing half of the framework — so the substring test
  was never the assertion it read as;
* `typealias`, `.init(` and any mutating member (`.save…`, `.remove…`,
  `.commit…`, `.reset…`, `.delete…`) forbidden **inside the probe only**. These
  are ordinary Swift elsewhere — `try self.init(…)` is the decode-path routing
  this very file requires, `FileManager.removeItem` is how a temporary directory
  is cleaned up — so scanning the tree with them would redden on correct code.

The docstring was rewritten to say what is now enforced, to name the failure that
made the rewrite necessary, and to state plainly what is **still trusted**: the
guard reads text, not a parsed program; whole-line comments are stripped on
purpose, so a forbidden symbol in prose is deliberately invisible, and the price
is that a trailing comment on a line of code is not stripped either.

### NOTE 2 — the seam-closure guard read one file

`test_the_calendar_mechanism_seam_declares_only_read_operations` split
`CalendarMechanism.swift` on the protocol name and read from there. A Swift
protocol is not confined to its file: the reviewer put
`extension CalendarMechanism { … removeOccurrence … saveOccurrence … }` in a
different file under `Sources/AppleSourceHost/` and the suite stayed green.

The guard now collects the declaration and **every protocol extension of the
seam** across the whole native tree, and holds the union to the same closed
operation and property sets. §H, which disclosed the scan-to-end-of-file property
and not this one, has been corrected.

### NOTE 3 — `EVENT_KIT_SURFACE` had no floor

Unlike `PROBE_TARGETS` (`== 3`) and the decode-path `subjects` (`== 8`), the
EventKit symbol table could be emptied, which made
`test_no_swift_outside_the_probes_can_reach_an_event_store` **fully vacuous** — a
real `import EventKit` plus a real `EKEventStore` in the shipping directory
passed it. This is the shape WP-16's reviewer found in three separate guards, and
finding it again one package later is the argument for the floor being a habit
rather than a fix.

The table now carries a count floor of eighteen, a no-duplicates assertion (a
repeated token meets a count floor without covering anything), and a named
membership floor — because eighteen never-occurring tokens count the same as
eighteen real ones.

### NOTE 4 — the build-step figure

Corrected in §I, with the reason it was wrong rather than a new number quietly
substituted: SwiftPM revises the denominator mid-run, and 39 is one of the values
it passes through on the way to 44.

### A fifth finding, not in the review

Enforcing NOTE 1's claim surfaced one the review did not raise. §J stated that
`EKEventStore` "appears in one file in this repository". It appears in **two**:
this package's probe and WP-15's multi-framework probe, which holds
`EKEventStore.self`. Because `_swift_outside_the_probes()` exempts all three
compile-only probes and the WP-17 guard held only the calendar one, the other two
were exempt from everything — and WP-15's own activation list has the same
paren-suffixed gap the reviewer found here, forbidding `EKEventStore(` and not
`EKEventStore.save`. `test_no_swift_in_the_native_tree_constructs_an_event_store`
now scans **every** Swift file under `native/`, probes included, for the
construction spellings and the closed member set, and asserts which two files name
the type at all so the scan cannot go quiet. §J is corrected.

### Non-vacuity of the corrections — and four blind spots in them

**A guard you author is not a guard you are subject to.** WP-16's correction
Worker found four fresh blind spots in its own new guards, one of which
reproduced the exact defect it was closing. So did this one. Every correction was
attacked with the shapes that historically defeat this kind of guard, *after* the
reviewer's three plants already reddened:

| # | Attack on the correction's own guard | First result | Closed by |
|---|---|---|---|
| B1 | `func leak(_ handed: EKEventStore) { _ = handed.save }` — an unapplied reference to `save` on a **parameter**, naming no member of the type and constructing nothing | **GREEN** | a parameter-of-store-type row in the construction list, and a mutating-member row that needs no store spelling in front of it |
| B2 | the same parameter with no use at all | **GREEN** | same |
| B3 | `import EventKitUI` added to the probe | **GREEN** — `"import EventKit" in probe` is a substring test and `EventKitUI` contains it | the closed import set |
| B4 | `extension CalendarMechanism { static let closer = "}" ; func removeOccurrence() {} }` — a brace inside a **string literal** closing a brace Swift never opened, truncating the extension body and hiding the member below it | **GREEN** | string-literal contents blanked, length-preservingly, before brace matching |

B4 is the one worth dwelling on: it is the same class of defect as the
line-anchored regex that could not see a two-line declaration, arriving in the
brace matcher written to fix a *different* incompleteness. A correction is where
these are most likely, not least.

Five further shapes were tried against the corrected seam guard and **all five
reddened**, so they are reported as attempts rather than findings: a
`static func` on the extension; a declaration split so the name and its
parenthesis sit on different lines; the `public extension` spelling; an extension
wrapped in `#if os(macOS)`; and an extension declared in the **`Tests/`** target
rather than `Sources/`. The last is the reason the scan is `native/` rather than
`Sources/AppleSourceHost`, which is what the NOTE asked for.

### The plants — twenty-four, plus the four attacks above, all reverted

`tests/architecture/test_wp17_calendar_adapter.py` holds **16** tests at this
head. A healthy plant is `1 failed, 15 passed`; a plant that trips two guards
reads `2 failed, 14 passed`.

| # | Plant | Result |
|---|---|---|
| C-P2 | **the reviewer's plant**: `EKEventStore.save`, `EKEventStore.remove` unapplied and `EKEventStore.init()` — verified to still **compile** (`swift build`, exit 0) before the guard was run | RED, closed member set: `…names the event-store members ['Type', …, 'init', …, 'remove', 'save', 'self']` |
| C-P2a | `EKEventStore.save` alone, no parentheses | RED, same assertion |
| C-P2b | `EKEventStore . save` — whitespace around the dot | RED, same assertion |
| C-P2c | `EKEventStore` and `.save` on **two lines** | RED, same assertion |
| C-P2d | `typealias Store = EKEventStore` then `Store.save` — the aliased spelling no member regex can see | RED, on the `typealias` row |
| C-P2e | `let store: EKEventStore = handed` — a store variable never constructed here | RED, on the variable row |
| C-P2f | `func pass(_ handed: EKEventStore) -> EKEventStore` — a store returned, no constructor named | RED, on the parameter row |
| C-P2g | `EKEventEditViewController` | RED, on the mutation surface |
| C-P2h | **CONTROL**: all three forbidden spellings in a **comment line only** | correctly **GREEN — 16 passed**. Deliberate: a guard that reddens on the paragraph explaining it is a guard somebody deletes |
| C-P2i | `EKEventStore.reset` unapplied | RED, closed member set |
| C-P2j | `EKEventStore.save` planted in **WP-15's** framework probe | RED, `…FrameworkCompatibility.swift names the event-store members ['save']` — the fifth finding, closed |
| C-P2k | `EKEventStore()` constructed in WP-15's framework probe | RED, `…constructs an event store` |
| C-P8 | **the reviewer's plant**: `extension CalendarMechanism` with `removeOccurrence` and `saveOccurrence` in a **new** file, `Sources/AppleSourceHost/CalendarMechanismExtras.swift` | RED: `…now offers ['accounts', 'authorizationState', 'calendars', 'occurrences', 'removeOccurrence', 'saveOccurrence'], declared across [CalendarMechanism.swift, CalendarMechanismExtras.swift]` |
| C-P8a | the same extension appended to an **existing** unrelated file, `HostTelemetry.swift` | RED, same assertion, naming that file |
| C-P8b | `var isCancelled: Bool { get {…} set {…} }` on the seam from another file | RED, on the closed property set |
| C-P8c | `subscript(cancel key: String) -> Bool { get set }` on the seam from another file | RED, on the subscript assertion |
| C-P8d | `extension CalendarMechanism where Self: Sendable` with the brace **on the next line** | RED, on the operation set |
| C-P8e | a **second** `public protocol CalendarMechanism` declared in another file | RED: `…is declared in [CalendarMechanism.swift, HostTelemetry.swift]` |
| C-P8f | **CONTROL**: `extension CalendarMechanismDescriptor` with a `removeOccurrence`, a settable `var` and a `subscript` | correctly **GREEN — 16 passed**. It is not the seam, and `\b` is why the guard knows that |
| C-P8g | **CONTROL**: `extension FixtureCalendarMechanism` — a conformer, not the protocol | correctly **GREEN — 16 passed** |
| C-P17 | **the reviewer's plant**: `EVENT_KIT_SURFACE` emptied to one never-occurring token **and** a real `import EventKit` / `EKEventStore` added under `Sources/AppleSourceHost/` | RED: `…names 1 symbols and the floor is 18` |
| C-P17a | the table padded back to **eighteen never-occurring** tokens, leak still present | RED: `…no longer names ['import EventKit', 'EKEventStore', 'EKEvent', 'EKCalendar', 'EKAuthorizationStatus']` |
| C-P17b | the table padded to eighteen by **repeating** one real token | RED: `…repeats a symbol, which meets the floor above without covering another way to reach a store` |
| C-P17c | **CONTROL**: the real EventKit leak with the table left **intact** | RED for the original reason — `{CalendarLiveMechanism.swift: ['EKEvent', 'EKEventStore', 'import EventKit']} name an EventKit symbol`. The floor is an addition to a working guard, not a replacement for one |

Every plant was reverted — `git checkout --` for modified files, `rm` for the two
created ones (`CalendarMechanismExtras.swift`, `CalendarLiveMechanism.swift`) —
and every restored file verified **byte-identical by SHA-256** before and after.
**No plant remains in the tree** and no plant file was left behind.

### What the corrected guards enforce, and what they do not

Enforced, statically, on every Swift file under `native/`: no event store is
constructed, held in a variable, returned, or taken as a parameter; the members of
`EKEventStore` named anywhere are a closed set of six reads and metatypes; the
seam's operations and properties are closed across the declaration and every
protocol extension of it, in any file; the EventKit symbol table cannot be
emptied, padded with junk, or padded by repetition.

Trusted, and named as trusted rather than dressed as enforced: these are **text**
scans, not parses. Whole-line comments are stripped by choice, which makes prose
invisible to them and trailing comments invisible too. A Swift file outside
`native/apple-source-host` would be outside every scan here; none exists. And the
strongest guarantee in the package remains the one that is not a text scan at
all — `otool -L` on both built products shows no Apple framework, which is a
link-time fact and is what WP-15's control 1 has always rested on.
