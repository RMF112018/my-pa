"""WP-17's Calendar controls, as guards rather than as claims.

WP-15 proved the shipping host links no Apple framework and WP-16 preserved it.
WP-17 adds a calendar adapter, and the risk of that addition is sharper than
WP-16's: **EventKit is a real, public, documented read API**, so unlike Mail
there is an obvious, working, tempting framework to reach for — and the same
framework saves and removes events. Every guard below exists because the easy
version of this package is the one that imports EventKit into the module that
ships.

The remaining guards are about the semantics that a calendar adapter loses
quietly: an all-day event turned into a midnight instant, a cancelled occurrence
turned into an absence, an occurrence keyed by where it is now rather than where
it was scheduled, and a horizon narrowed instead of refused. Each of those
produces a value that reads as correct and is not.

Comment text is stripped before scanning, for WP-15's reason: a guard a code
comment can trip is a guard someone eventually weakens to get their comment back.

**What these guards are not.** They do not prove that a calendar can be read.
Nothing in this repository proves that, because proving it needs a TCC grant only
the operator can give and this package must not obtain — and no calendar
belonging to anyone was read to write any of it. What the probe guard proves is
narrower and is the part that can be settled without consent: that the symbols a
read-only EventKit adapter would need exist in this SDK and typecheck on this
toolchain.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from my_pa.contracts.v1.native_sources import (
    NATIVE_SOURCE_MAX_CURSOR_BYTES,
    NATIVE_SOURCE_MAX_PAGE_SIZE,
)

ROOT: Final = Path(__file__).resolve().parents[2]
HOST: Final = ROOT / "native" / "apple-source-host"
SHIPPING: Final = HOST / "Sources" / "AppleSourceHost"
MANIFEST: Final = HOST / "Package.swift"

FRAMEWORK_PROBE: Final = HOST / "Compatibility" / "AppleFrameworkCompatibilityProbe"
MAIL_PROBE: Final = HOST / "Compatibility" / "AppleMailAutomationShapeProbe"
EVENT_KIT_PROBE: Final = HOST / "Compatibility" / "AppleCalendarEventKitProbe"

#: The three compile-only probe targets. Each is declared in `Package.swift` on
#: the same footing, each is a dependency of nothing, and each is the only place
#: its framework may be named.
PROBES: Final = (FRAMEWORK_PROBE, MAIL_PROBE, EVENT_KIT_PROBE)
PROBE_TARGETS: Final = (
    "AppleFrameworkCompatibilityProbe",
    "AppleMailAutomationShapeProbe",
    "AppleCalendarEventKitProbe",
)

MECHANISM: Final = SHIPPING / "CalendarMechanism.swift"
ADAPTER: Final = SHIPPING / "BoundedCalendarReadAdapter.swift"
IDENTITY: Final = SHIPPING / "CalendarIdentity.swift"
TIME: Final = SHIPPING / "CalendarTime.swift"
RECURRENCE: Final = SHIPPING / "CalendarRecurrence.swift"
FIXTURE: Final = SHIPPING / "FixtureCalendarMechanism.swift"
LEGACY_RECURRENCE: Final = SHIPPING / "Recurrence.swift"
PROTOCOL: Final = SHIPPING / "NativeSourceProtocolV1.swift"


def _without_comments(source: str) -> str:
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )


def _swift_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in root.rglob("*.swift") if ".build" not in path.parts))


def _probe_files() -> set[Path]:
    return {path for probe in PROBES for path in _swift_files(probe)}


def _swift_outside_the_probes() -> tuple[Path, ...]:
    """Every Swift file under `native/` except the three compile-only probes.

    Wider than the shipping directory on purpose, and for the reason WP-15's
    correction established: the directory an EventKit import would actually
    arrive in is the one nobody named — a new tool target, a new test executable.
    """
    return tuple(path for path in _swift_files(HOST) if path not in _probe_files())


def _source(path: Path) -> str:
    return _without_comments(path.read_text(encoding="utf-8"))


def _stored_property_lines(source: str, type_name: str) -> list[str]:
    body = source.split(f"public struct {type_name}", 1)[1].split("\n    public init", 1)[0]
    return [line.strip() for line in body.splitlines() if line.strip().startswith("public let ")]


# --- non-vacuity --------------------------------------------------------------


def test_the_wp17_scan_is_reading_the_calendar_adapter_at_all() -> None:
    """Every assertion below is worthless if the scan reads nothing."""
    for path in (MECHANISM, ADAPTER, IDENTITY, TIME, RECURRENCE, FIXTURE, PROTOCOL):
        assert path.is_file(), f"{path} is missing; the WP-17 scan reads nothing"
    assert "public protocol CalendarMechanism" in _source(MECHANISM)
    assert "public struct BoundedCalendarReadAdapter" in _source(ADAPTER)
    assert "public enum CalendarOccurrenceLifecycle" in _source(IDENTITY)
    assert len(_swift_files(EVENT_KIT_PROBE)) == 1

    scanned = set(_swift_outside_the_probes())
    assert len(scanned) >= 14, f"the WP-17 scan found {len(scanned)} Swift files under native/"
    assert set(_swift_files(SHIPPING)) < scanned, (
        "the EventKit scan is no wider than Sources/AppleSourceHost"
    )
    assert scanned.isdisjoint(_probe_files())
    assert scanned | _probe_files() == set(_swift_files(HOST)), (
        "a Swift file under native/ is in neither the EventKit scan nor a probe"
    )
    # The exemption set is exactly three directories. Widening it again should be
    # a decision somebody makes here, not a side effect of adding a target.
    assert len(_probe_files()) == 3, (
        f"the compile-only probe set holds {len(_probe_files())} files. Each probe "
        "is one file and there are three of them; a fourth is a fourth place an "
        "Apple framework is permitted, and that is a decision rather than a diff"
    )


# --- control 6: no EventKit reaches anything that ships ----------------------

#: Every way a macOS process reaches a calendar through EventKit, plus the
#: mutating half of the same framework. Nothing outside the compile-only probes
#: may name any of these.
#:
#: This matters as much as WP-16's Apple-event list and for the mirror-image
#: reason. A TCC calendar grant *can* be scoped — macOS 14 splits `fullAccess`
#: from `writeOnly` — but the **framework** cannot: one `EKEventStore` answers
#: `events(matching:)` and `save(_:span:commit:)`, so a module that links EventKit
#: holds the authority to write a calendar whether or not it uses it. The only
#: enforceable read-only boundary is the client not linking it, which is what the
#: shipping target does and what these probes are kept out of.
EVENT_KIT_SURFACE: Final = (
    "import EventKit",
    "import EventKitUI",
    "EKEventStore",
    "EKEvent",
    "EKCalendar",
    "EKSource",
    "EKReminder",
    "EKParticipant",
    "EKRecurrenceRule",
    "EKAuthorizationStatus",
    "EKEntityType",
    "EKSpan",
    "saveEvent",
    "removeEvent",
    "saveCalendar",
    "removeCalendar",
    "commit(",
    "reset(",
)


def test_no_swift_outside_the_probes_can_reach_an_event_store() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _swift_outside_the_probes():
        source = _without_comments(path.read_text(encoding="utf-8"))
        named = sorted(symbol for symbol in EVENT_KIT_SURFACE if symbol in source)
        if named:
            offenders[str(path.relative_to(ROOT))] = named
    assert offenders == {}, (
        f"{offenders} name an EventKit symbol. One event store answers both "
        "`events(matching:)` and `save(_:span:commit:)`, so a target that can "
        "read a calendar through EventKit is a target that can rewrite one, "
        "whether or not it does today — and the shipping module linking no Apple "
        "framework is WP-15's control 1, proved at link time"
    )


def test_the_calendar_seam_cannot_ask_for_an_authorization_it_does_not_have() -> None:
    """Observing authorization is a read. *Requesting* it raises a TCC dialogue.

    Scanned over the **whole** native tree, probes included: the probe has no
    more business raising a consent dialogue than the shipping module does, and
    a request API named in a compiled-but-never-called function is one edit away
    from being called.
    """
    for path in _swift_files(HOST):
        source = _without_comments(path.read_text(encoding="utf-8"))
        for asking in (
            "requestFullAccessToEvents",
            "requestWriteOnlyAccessToEvents",
            "requestAccess(to",
            "requestAuthorization",
            "requestConsent",
        ):
            assert asking not in source, (
                f"{path.relative_to(ROOT)} names {asking}. A calendar grant is "
                "the operator's to give (EXT-04); this host may observe that it "
                "is absent and refuse, and may not raise the dialogue that asks"
            )


#: The closed set of operations `CalendarMechanism` may offer. Adding a fifth is
#: a decision about whether this host can act on a calendar.
MECHANISM_OPERATIONS: Final = (
    "accounts",
    "authorizationState",
    "calendars",
    "occurrences",
)

#: The closed set of *properties* the seam may offer, every one `{ get }`-only.
MECHANISM_PROPERTIES: Final = ("descriptor",)


def test_the_calendar_mechanism_seam_declares_only_read_operations() -> None:
    """The seam is closed, and closed against every way Swift declares a member.

    Written in WP-16's corrected shape rather than its first one, because that
    correction was bought at the cost of a reviewer proving the first shape
    vacuous: a `func` regex sees neither `var isAllDay: Bool { get set }` nor
    `subscript(cancel key: String) -> Bool { get set }`, and both are writes into
    somebody's calendar. Inherited requirements are closed too — a mutating
    parent protocol puts its operations on this seam without appearing between
    the braces every other assertion reads.
    """
    body = _source(MECHANISM).split("public protocol CalendarMechanism", 1)[1]
    assert len(body) > 100, "the seam scan read an empty protocol body"

    inherited = sorted(
        part.strip() for part in body.split("{", 1)[0].lstrip(": ").split(",") if part.strip()
    )
    assert inherited == ["Sendable"], (
        f"the calendar mechanism seam now inherits {inherited}. A parent "
        "protocol's requirements are this seam's requirements, and they arrive "
        "without appearing between the braces the rest of this test reads"
    )

    operations = sorted(set(re.findall(r"func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", body)))
    assert operations == sorted(MECHANISM_OPERATIONS), (
        f"the calendar mechanism seam now offers {operations}. Every operation on "
        "it must be a read: this seam is the only thing a live calendar mechanism "
        "would be asked for, so an operation that is not a read is a mutation "
        "path into somebody's calendar"
    )

    # `[^{}]+` rather than `[^\n{]+` for the type: Swift admits the accessor
    # block on the following line, and a regex anchored to one line would not see
    # `var isAllDay: Bool\n{ get set }` at all.
    properties = re.findall(r"var\s+([A-Za-z_][A-Za-z0-9_]*)\s*:[^{}]+\{([^}]*)\}", body)
    settable = sorted(name for name, accessors in properties if "set" in accessors.split())
    assert settable == [], (
        f"the calendar mechanism seam declares the settable properties {settable}. "
        "A `{ get }` property is a read and is legal here; `{ get set }` is an "
        "assignment into somebody's calendar, and it is not a `func`, so the "
        "operation set above never sees it"
    )
    assert sorted(name for name, _ in properties) == sorted(MECHANISM_PROPERTIES), (
        f"the calendar mechanism seam now declares the properties "
        f"{sorted(name for name, _ in properties)}. The property set is closed for "
        "the same reason the operation set is"
    )
    assert "subscript" not in body, (
        "the calendar mechanism seam declares a subscript. A subscript is an "
        "operation with no name for the closed set above to hold, and a "
        "`{ get set }` subscript is a write into a calendar keyed by a string"
    )


def test_the_event_kit_probe_resolves_symbols_and_reaches_no_store() -> None:
    """What the probe proves, and the two things it must not become.

    It must not become a runtime path — nothing constructs a store, requests an
    authorization or enumerates anything — and it must not become a dependency of
    anything that ships, which would put the framework that can rewrite a
    calendar inside the module that talks to the application.
    """
    probe = _source(EVENT_KIT_PROBE / "CalendarEventKitShape.swift")
    assert "import EventKit" in probe, (
        "the probe no longer imports EventKit. Its whole value is that the "
        "compiler re-proves on every build that the read mechanism is *present* — "
        "which is a different finding from 'the mechanism does not exist'"
    )

    for activation in (
        "EKEventStore(",
        "EKEvent(",
        "requestFullAccess",
        "requestWriteOnly",
        "requestAccess",
        ".save(",
        ".remove(",
        ".commit(",
        ".reset(",
        "events(matching:)(",
        "try await",
        "authorizationStatus(for:)(",
    ):
        assert activation not in probe, (
            f"the EventKit probe calls {activation}. It exists to answer a "
            "compile-and-typecheck question without consent; constructing a store "
            "or requesting an authorization raises the TCC dialogue that EXT-04 "
            "reserves to the operator, and a save or remove would end the "
            "read-only claim outright"
        )

    # **Floors, because without them this test measures nothing.** The probe's
    # value is entirely in how many symbols it makes the compiler resolve, and a
    # probe emptied to a bare `import EventKit` would satisfy every assertion
    # above while proving only that the framework exists.
    metatypes = probe.count(".self")
    key_paths = re.findall(r"\\EK[A-Za-z]+\.[A-Za-z]+", probe)
    unapplied = re.findall(r"EKEventStore\.[a-zA-Z]+\([a-zA-Z:]*\)\n?\s*$", probe, re.MULTILINE)
    assert metatypes >= 6, f"the probe resolves {metatypes} metatypes; it stopped proving types"
    assert len(key_paths) >= 10, (
        f"the probe resolves {len(key_paths)} member key paths. A metatype proves a "
        "*type* resolves; a key path proves a *member* resolves, and the members — "
        "`occurrenceDate`, `isAllDay`, `timeZone`, `status` — are where a calendar "
        "adapter's assumptions actually live"
    )
    assert len(set(key_paths)) == len(key_paths), (
        f"the probe's key paths hold {len(key_paths)} entries and only "
        f"{len(set(key_paths))} distinct ones; a repeated key path meets the floor "
        "above without resolving another member"
    )
    for required in (
        r"\EKEvent.occurrenceDate",
        r"\EKEvent.isAllDay",
        r"\EKEvent.timeZone",
        r"\EKEvent.status",
        r"\EKEvent.isDetached",
    ):
        assert required in probe, (
            f"the probe no longer resolves {required}. Each of these carries one of "
            "WP-17's controls: the original scheduled start is what occurrence "
            "identity is anchored to, all-day-ness is a flag rather than a "
            "midnight instant, an event's zone is its own rather than the "
            "reader's, and a cancelled event is a *status* on an event that is "
            "still there"
        )
    assert len(unapplied) >= 3, (
        f"the probe resolves {len(unapplied)} unapplied event-store methods. The "
        "bounded read — a start, an end, a calendar list — is the whole reason to "
        "believe a horizon-bounded calendar read is source-side rather than a "
        "filter after a full enumeration"
    )


def test_the_three_probes_are_compile_only_and_never_linked_into_the_host() -> None:
    """WP-16's count guard, extended to the third probe.

    Counted, not walked, for the reason WP-16 recorded after finding out the hard
    way: splitting `Package.swift` on `name: "AppleSourceHost"` lands on the
    *product* declaration a few lines above the target, whose section closes
    before any dependency list, so a planted dependency stayed green in both this
    guard's ancestor and WP-15's. A count is immune to the manifest's formatting:
    a probe named anywhere other than its own `name:` is a probe something depends
    on.
    """
    manifest = _without_comments(MANIFEST.read_text(encoding="utf-8"))
    assert "let package = Package(" in manifest and manifest.count('"AppleSourceHost"') >= 3, (
        "the manifest scan is not reading Package.swift"
    )
    assert len(PROBE_TARGETS) == 3, "the probe target set stopped naming all three probes"

    for probe_target in PROBE_TARGETS:
        occurrences = manifest.count(f'"{probe_target}"')
        assert occurrences == 1, (
            f"{probe_target} is named {occurrences} times in Package.swift as a "
            "quoted token. Exactly one is legitimate — its own target's `name:`. A "
            "second is a dependency, a product membership, or a target list, and "
            "any of those links an Apple framework into something that ships. The "
            "shipping module linking none of them is WP-15's control 1, proved at "
            "link time, and it is the strongest guarantee in this package"
        )
        assert f'name: "{probe_target}"' in manifest


# --- control 1: identity, four levels of it ----------------------------------


def test_the_calendar_identity_alphabet_excludes_the_composition_separator() -> None:
    """Injectivity, which is what stops a series and an occurrence colliding.

    The four levels are composed by joining components with `:`.
    `NativeSourceOpaqueID` admits `:`, so the restriction has to live on the
    component alphabet or the join is ambiguous — and an ambiguous join is how a
    detached occurrence silently becomes its own series.
    """
    identity = _source(IDENTITY)
    body = identity.split("public struct CalendarIdentityComponent", 1)[1].split(
        "public struct CalendarAccountIdentity", 1
    )[0]
    alphabet = re.search(r'charactersIn: "([^"]+)"', body)
    assert alphabet is not None, "the identity component alphabet is no longer declared"
    assert ":" not in alphabet.group(1), (
        "the calendar identity component alphabet now admits ':', which is the "
        "separator the four levels are joined with. Two distinct identities would "
        "compose to one identifier and silently become one occurrence"
    )
    assert 'separator = ":"' in identity, "the composition separator is no longer declared"
    assert "throw NativeSourceContractError.calendarIdentityTooLong" in identity, (
        "an over-long identity is no longer refused. A trimmed identity is the one "
        "truncation with no honest partial form: it aliases two occurrences"
    )
    for level in (
        "public struct CalendarAccountIdentity",
        "public struct CalendarBucketIdentity",
        "public struct CalendarSeriesIdentity",
        "public struct CalendarOccurrenceIdentity",
    ):
        assert level in identity, (
            f"{level} is gone. Control 1 is four levels of identity — account, "
            "calendar, series, occurrence — and a missing level is a level that "
            "gets reconstructed by guesswork downstream"
        )

    # The occurrence key is biased and padded, which is what makes lexicographic
    # order chronological. Either half alone leaves a cursor that resumes in the
    # wrong place: `String(-1)` sorts before `String(-2)` and after `String(10)`.
    key = identity.split("func orderPreservingKey", 1)[1].split("\n    }", 1)[0]
    assert "UInt64(bitPattern:" in key and "0x8000_0000_0000_0000" in key, (
        "the occurrence key is no longer biased into unsigned space, so instants "
        "before 1970 sort after instants after it"
    )
    assert "repeating:" in key, (
        "the occurrence key is no longer zero-padded to a fixed width, so "
        "lexicographic order is no longer numeric order"
    )

    assert "originalStartUnixMilliseconds" in identity, (
        "occurrence identity no longer names the *original* scheduled start. "
        "Keying an occurrence by where it is now makes every move read as a "
        "delete and a create"
    )


# --- control 4: a cancellation is a fact, not a gap --------------------------


def test_a_cancelled_occurrence_is_representable_and_is_never_dropped() -> None:
    """The defect this package was sent to find, closed in both expanders.

    `NativeRecurrenceExpander` computed `cancelled` and then omitted the
    occurrence from its output, which made a cancellation arrive downstream as an
    occurrence that never existed. Both expanders now emit it.
    """
    lifecycle = _source(IDENTITY).split("public enum CalendarOccurrenceLifecycle", 1)[1]
    cases = sorted(re.findall(r"case\s+([A-Za-z_][A-Za-z0-9_]*)", lifecycle))
    assert cases == ["cancelled", "confirmed", "detached"], (
        f"the occurrence lifecycle now has the cases {cases}. Three states are "
        "load-bearing: happening as scheduled, called off but still reported, and "
        "moved or edited away from the series"
    )

    legacy = _source(LEGACY_RECURRENCE)
    assert "let cancelled = exception != nil" not in legacy, (
        "the WP-14 expander computes a `cancelled` flag again. The defect was "
        "never the flag; it was that the flag gated whether the occurrence was "
        "emitted at all"
    )
    assert "if !cancelled &&" not in legacy, (
        "the WP-14 expander drops cancelled occurrences from its output again. A "
        "cancellation reported as an absence is a different fact, and the consumer "
        "cannot recover the first from the second"
    )
    assert ".cancelled" in legacy and "lifecycle: lifecycle" in legacy, (
        "the WP-14 expander no longer emits a lifecycle, so a cancelled occurrence "
        "is once again indistinguishable from one that never existed"
    )
    assert "lifecycle: .cancelled" in _source(RECURRENCE), (
        "the WP-17 expander no longer emits cancelled occurrences"
    )

    # The adapter must not quietly re-introduce the drop by filtering the page it
    # was handed. It may filter nothing at all — every re-check it makes is a
    # refusal, not a removal.
    adapter = _source(ADAPTER)
    assert "filter" not in adapter, (
        "the calendar adapter now filters its page. Every bound this adapter holds "
        "is enforced by refusing the whole page, because a page silently missing "
        "the records that failed a check is a page that reads as complete"
    )


# --- control 5: an all-day event is not an instant ---------------------------


def test_an_all_day_span_has_nowhere_to_put_an_instant() -> None:
    """The invariant enforced by the type having no field for the mistake.

    A `startUnixMilliseconds` on an all-day span is how an all-day event becomes
    "midnight local", which is a different day for a reader in a different zone
    and cannot be recovered afterwards. So the span holds dates and nothing else,
    in the shape WP-15 used for content-free telemetry: the bound is that there
    is nowhere to write the wrong value.
    """
    time_source = _source(TIME)
    properties = _stored_property_lines(time_source, "CalendarAllDaySpan")
    assert len(properties) == 2, (
        f"the all-day span declares {properties}. Two stored properties, both "
        "dates: a first day and a last day"
    )
    for line in properties:
        assert line.endswith(": CalendarDate"), (
            f"the all-day span declares `{line}`. Every stored property of it must "
            "be a date; an instant field is where 'midnight local' arrives, and "
            "midnight local is a different day for a different reader"
        )

    # The timed interval is the mirror image: the instant is the authority and
    # the wall clock is *verified against it* rather than trusted.
    interval = time_source.split("public struct CalendarTimedInterval", 1)[1].split(
        "\n    private enum CodingKeys", 1
    )[0]
    assert "guard derivedStart == startWallClock, derivedEnd == endWallClock" in interval, (
        "the timed interval no longer re-derives its wall clock from its instant "
        "and compare the two. Without that check a declared pair can disagree, and "
        "a wall clock that disagrees with its instant is how a DST bug survives"
    )
    assert "CalendarZone.wallClock(" in interval

    # The three DST answers are three, not one. Collapsing them is how an hour
    # goes missing once a year.
    resolution = time_source.split("public enum CalendarWallClockResolution", 1)[1].split("\n}", 1)[
        0
    ]
    cases = sorted(re.findall(r"case\s+([A-Za-z_][A-Za-z0-9_]*)", resolution))
    assert cases == ["ambiguous", "skipped", "unique"], (
        f"the wall-clock resolution now has the cases {cases}. A spring-forward "
        "gap names no instant and a fall-back repeated hour names two; a single "
        "answer for all three is a guess in two of them"
    )
    assert "throw NativeSourceContractError.calendarScheduleInconsistent" in _source(RECURRENCE), (
        "a series defined at a local time that does not exist is no longer "
        "refused. Every way of continuing invents an instant, and an invented "
        "instant is indistinguishable from a real one once it is in a record"
    )


# --- the bounds ---------------------------------------------------------------


def test_the_calendar_bounds_are_frozen_in_the_protocol_and_agree_with_python() -> None:
    """The bounds belong to the protocol, not to whichever adapter builds a page."""
    protocol = _source(PROTOCOL)
    for name, value in (
        ("maximumCalendarIdentityComponentBytes", "64"),
        ("maximumCalendarHorizonDays", "366"),
        ("maximumCalendarSeriesOccurrences", "512"),
    ):
        assert f"public static let {name} = {value}" in protocol, (
            f"the frozen calendar bound {name} = {value} is no longer declared in "
            "the protocol. A bound an adapter owns is a bound the next adapter does "
            "not have"
        )

    # And the two that cross the Swift/Python boundary still agree on both sides.
    # The calendar adapter reuses them rather than minting its own page ceiling,
    # so a drift here is a drift in what the admitting application will accept.
    declared = dict(
        re.findall(r"public static let (maximumPageSize|maximumCursorBytes) = (\d+)", protocol)
    )
    assert declared == {
        "maximumPageSize": str(NATIVE_SOURCE_MAX_PAGE_SIZE),
        "maximumCursorBytes": str(NATIVE_SOURCE_MAX_CURSOR_BYTES),
    }, (
        f"the Swift page and cursor ceilings are {declared} and the Python contract "
        f"declares {NATIVE_SOURCE_MAX_PAGE_SIZE} and {NATIVE_SOURCE_MAX_CURSOR_BYTES}. "
        "A page the host will build and the application will reject is a read that "
        "fails after the work"
    )


def test_the_horizon_refuses_rather_than_narrowing_and_truncation_is_declared() -> None:
    """A narrowed horizon is silent loss; a silent truncation is worse.

    A horizon quietly clipped from ten years to one returns a page that is
    indistinguishable from "nothing is scheduled after next spring". A page that
    stops short without saying so is the same failure one level down: the caller
    stops paging and never learns what it did not receive.
    """
    mechanism = _source(MECHANISM)
    adapter = _source(ADAPTER)

    assert "throw NativeSourceContractError.calendarHorizonExceeded" in mechanism, (
        "the horizon window no longer refuses a request wider than the ceiling"
    )
    assert mechanism.count("public init(from decoder: Decoder)") == 2, (
        "the horizon and occurrence types lost a validating decoder; a bound that "
        "exists only on an initialiser holds for values built in Swift and not for "
        "the same values arriving as JSON"
    )
    assert "throw NativeSourceContractError.calendarHorizonExceeded" in adapter, (
        "an unbounded calendar read is no longer refused. A calendar has no "
        "natural end, so 'no time range' is not a wider read — it is the unbounded "
        "enumeration the horizon exists to prevent"
    )
    assert "throw NativeSourceContractError.calendarTruncationUndeclared" in adapter, (
        "a page that stops short no longer has to declare it"
    )
    assert "throw NativeSourceContractError.calendarUnboundedEnumeration" in adapter, (
        "the adapter will now accept a mechanism that satisfied a bounded read by "
        "enumerating the whole store; 'bounded horizon' is the acceptance and a "
        "filter after a full enumeration is not it"
    )
    for clamping in ("prefix(", "clamp", "truncat", "min(", "dropLast"):
        assert clamping not in adapter, (
            f"the calendar adapter now clamps with {clamping}. An over-bound "
            "request is refused, never narrowed: a narrowed answer reads as "
            "complete and is not"
        )


def test_calendar_authorization_fails_closed_and_cannot_degrade_to_an_empty_page() -> None:
    """Control 2, structurally: a refusal throws and can never become a page.

    This is the distinction the campaign has enforced since WP-09, and a calendar
    is where it costs most: a page of zero records means "nothing is scheduled",
    and returning that when the real answer is "we were never allowed to look" is
    a lie a scheduler acts on.
    """
    adapter = _source(ADAPTER)
    body = adapter.split("private func requireAuthorization() throws {", 1)[1].split("\n    }", 1)[
        0
    ]
    arms = re.findall(r"case\s+\.([A-Za-z_][A-Za-z0-9_]*):", body)
    assert sorted(arms) == ["authorized", "denied", "notDetermined", "restricted"], (
        f"the authorization switch now handles {sorted(arms)}. It must handle every "
        "state EventKit distinguishes, one arm each, so that adding a state is a "
        "compile error rather than a silent admission"
    )
    assert "default" not in body, (
        "the authorization switch has a `default` arm. A state nobody has heard of "
        "is not a state to read somebody's calendar on, and a `default` is how one "
        "gets admitted"
    )
    refusing = body.split("case .denied:", 1)[1]
    assert refusing.count("throw NativeProviderFailure.permissionDenied") == 3, (
        "one of the three non-authorized states no longer throws. Every one of "
        "them must refuse; the only permitted `return` in this function is the "
        "authorized arm's"
    )
    assert refusing.count("return") == 0, (
        "a non-authorized arm now returns rather than throwing, which is exactly "
        "how a refusal degrades into an empty page"
    )
    assert "NativeReadPage(records: [])" not in adapter, (
        "the calendar adapter now has a path that fabricates an empty page. Empty "
        "and unavailable are different facts and must be different values"
    )
    # Both entry points check before they read.
    for entry in ("public func discoverCalendars", "public func readCalendar"):
        section = adapter.split(entry, 1)[1][:400]
        assert "try requireAuthorization()" in section, (
            f"{entry} no longer checks authorization before its first read"
        )


def test_every_invariant_bearing_calendar_value_validates_on_the_decode_path() -> None:
    """WP-15's lesson and WP-16's correction, applied to WP-17.

    A bound enforced only on the memberwise initialiser holds for values built in
    Swift and not for the same values arriving as JSON, which is the shape the
    host would actually be handed. **A decoder that exists is not a decoder that
    validates**: a decoder rewritten to assign its stored properties directly
    compiles, keeps the literal string a naive guard looks for, and skips every
    `guard` in the throwing initialiser. So the routing is asserted too — the
    decoder must reach the validating initialiser and must assign no stored
    property of its own.

    This remains a *static* check, and the runtime one is the one that matters:
    `AppleSourceHostContractChecks::checkCalendarValueBoundsHoldOffTheWire`
    decodes each malformed document and requires the failure.
    """
    subjects = (
        (
            TIME,
            ("CalendarDate", "CalendarWallClock", "CalendarAllDaySpan", "CalendarTimedInterval"),
        ),
        (MECHANISM, ("CalendarHorizonWindow", "CalendarOccurrence")),
        (RECURRENCE, ("CalendarRecurringSeries",)),
        (LEGACY_RECURRENCE, ("NativeCalendarOccurrence",)),
    )
    seen = 0
    for path, types in subjects:
        source = _source(path)
        for type_name in types:
            seen += 1
            body = source.split(f"public struct {type_name}", 1)[1].split("\npublic ", 1)[0]
            assert "public init(from decoder: Decoder)" in body, (
                f"{type_name} carries an invariant and decodes off the wire with no "
                "validating decoder of its own; the bound would hold only for "
                "values built in Swift"
            )
            decoder = body.split("public init(from decoder: Decoder)", 1)[1].split("\n    }", 1)[0]
            assert "try self.init(" in decoder or "self.init(" in decoder, (
                f"{type_name}'s decoder no longer routes through its validating "
                "initialiser. A decoder that builds the value some other way is a "
                "decoder that skips every guard the initialiser holds"
            )
            assigned = sorted(set(re.findall(r"self\.([A-Za-z_][A-Za-z0-9_]*)\s*=[^=]", decoder)))
            assert assigned == [], (
                f"{type_name}'s decoder assigns {assigned} directly. Direct "
                "assignment is exactly how a decoder keeps its shape and loses its "
                "validation: the fields arrive off the wire unchecked"
            )
    assert seen == 8, f"the decode-path scan checked {seen} types; it is not reading the tree"


def test_no_entitlement_or_usage_declaration_was_added_for_the_calendar_mechanism() -> None:
    """The tripwire, restated for the keys a live EventKit mechanism would need.

    A live mechanism needs `NSCalendarsFullAccessUsageDescription` in an
    Info.plist and, under the App Sandbox,
    `com.apple.security.personal-information.calendars`. None of that exists here
    and none of it may arrive without the signing work that owns it (EXT-03).
    WP-15 already fails the build if such a *file* appears; this reads the same
    tree for the *contents* that would make one meaningful, so a key smuggled
    into some other file type is caught too.
    """
    forbidden = (
        "NSCalendarsUsageDescription",
        "NSCalendarsFullAccessUsageDescription",
        "NSCalendarsWriteOnlyAccessUsageDescription",
        "NSRemindersFullAccessUsageDescription",
        "com.apple.security.personal-information.calendars",
    )
    offenders: dict[str, list[str]] = {}
    for path in (ROOT / "native").rglob("*"):
        if not path.is_file() or ".build" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - no binary files today
            continue
        named = sorted(key for key in forbidden if key in _without_comments(text))
        if named:
            offenders[str(path.relative_to(ROOT))] = named
    assert offenders == {}, (
        f"{offenders} declare a usage description or an entitlement for calendar "
        "access. Both are EXT-03/EXT-04 and operator-gated; WP-17 proves the "
        "mechanism's shape without activating any of it"
    )
