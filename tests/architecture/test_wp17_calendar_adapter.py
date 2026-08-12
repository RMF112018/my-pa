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
#: WP-18's Contacts shape probe, on the same footing as the other three. Its own
#: constraints live in `test_wp18_contacts_adapter.py`; it appears here because
#: the probe *set* is what this module's exemption and count guards are about,
#: and a probe missing from the set is a directory nothing holds to anything.
CONTACTS_PROBE: Final = HOST / "Compatibility" / "AppleContactsShapeProbe"
TASKS_PROBE: Final = HOST / "Compatibility" / "AppleTasksEventKitProbe"

#: The four compile-only probe targets. Each is declared in `Package.swift` on
#: the same footing, each is a dependency of nothing, and each is the only place
#: its framework may be named.
PROBES: Final = (FRAMEWORK_PROBE, MAIL_PROBE, EVENT_KIT_PROBE, CONTACTS_PROBE, TASKS_PROBE)
PROBE_TARGETS: Final = (
    "AppleFrameworkCompatibilityProbe",
    "AppleMailAutomationShapeProbe",
    "AppleCalendarEventKitProbe",
    "AppleContactsShapeProbe",
    "AppleTasksEventKitProbe",
)

MECHANISM: Final = SHIPPING / "CalendarMechanism.swift"
ADAPTER: Final = SHIPPING / "BoundedCalendarReadAdapter.swift"
IDENTITY: Final = SHIPPING / "CalendarIdentity.swift"
TIME: Final = SHIPPING / "CalendarTime.swift"
RECURRENCE: Final = SHIPPING / "CalendarRecurrence.swift"
FIXTURE: Final = SHIPPING / "FixtureCalendarMechanism.swift"
LEGACY_RECURRENCE: Final = SHIPPING / "Recurrence.swift"
PROTOCOL: Final = SHIPPING / "NativeSourceProtocolV1.swift"


#: A closed `/* … */` span, non-greedy so nested openers do not swallow code.
BLOCK_COMMENT: Final = re.compile(r"/\*[\s\S]*?\*/")


def _without_comments(source: str) -> str:
    """Drop comment text, keeping every line that also carries code.

    Whole-line `//` prose stays invisible on purpose: a guard that reddens on
    the paragraph explaining it is a guard somebody deletes.

    Closed `/* … */` **spans** are blanked before that line filter rather than
    their lines being dropped whole. Dropping the line was fail-open: a comment
    that ends mid-line leaves code after it, so `/* shape */ <forbidden code>`
    compiled and was invisible to every text guard here. WP-18's reviewer proved
    it against this helper's copy in `test_wp18_contacts_adapter.py`, and the
    helper is shared by WP-15 through WP-18, so all four are corrected together.
    Blanking preserves newlines, and an opener with no closer still starts its
    line with `/*` and is dropped as before.
    """
    blanked = BLOCK_COMMENT.sub(
        lambda match: "".join("\n" if character == "\n" else " " for character in match.group(0)),
        source,
    )
    return "\n".join(
        line for line in blanked.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )


def _swift_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in root.rglob("*.swift") if ".build" not in path.parts))


def _probe_files() -> set[Path]:
    return {path for probe in PROBES for path in _swift_files(probe)}


def _swift_outside_the_probes() -> tuple[Path, ...]:
    """Every Swift file under `native/` except the four compile-only probes.

    Wider than the shipping directory on purpose, and for the reason WP-15's
    correction established: the directory an EventKit import would actually
    arrive in is the one nobody named — a new tool target, a new test executable.
    """
    return tuple(path for path in _swift_files(HOST) if path not in _probe_files())


def _source(path: Path) -> str:
    return _without_comments(path.read_text(encoding="utf-8"))


#: `\b` rather than a bare prefix: `CalendarMechanismKind` and
#: `CalendarMechanismDescriptor` both start with the seam's name, and an
#: `extension CalendarMechanismDescriptor` is not an extension of the seam.
SEAM_DECLARATION: Final = re.compile(r"public protocol CalendarMechanism\b")
SEAM_EXTENSION: Final = re.compile(r"\bextension\s+CalendarMechanism\b")


#: Multiline first, then raw, then plain — a `"""` block matched as three plain
#: literals would blank the wrong spans.
STRING_LITERAL: Final = re.compile(r'"""[\s\S]*?"""' + r'|#+"[\s\S]*?"#+' + r'|"(?:[^"\\\n]|\\.)*"')


def _without_string_literals(source: str) -> str:
    """Blank the *contents* of Swift string literals, preserving every offset.

    Found by attacking this file's own new brace matcher, which is the failure
    WP-16's correction Worker hit four times: a `}` inside a string literal
    closes a brace Swift never opened, so
    `extension CalendarMechanism { static let closer = "}" … }` truncated the
    body and hid the `removeOccurrence` declared underneath it. Blanking is
    length-preserving because the match offsets are used to slice the source.
    """

    def blank(match: re.Match[str]) -> str:
        return "".join(character if character == "\n" else " " for character in match.group(0))

    return STRING_LITERAL.sub(blank, source)


def _balanced_body(source: str, start: int) -> str:
    """The brace-balanced block beginning at the first `{` after `start`.

    Used for extensions rather than the declaration's scan-to-end-of-file,
    because an extension is not the last declaration in an arbitrary file and a
    scan to the end of one would redden on every unrelated type below it. An
    unbalanced source falls back to the rest of the file — over-reading fails
    safe, reading nothing does not.
    """
    opened = source.find("{", start)
    if opened < 0:
        return source[start:]
    depth = 0
    for index in range(opened, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opened + 1 : index]
    return source[opened + 1 :]


def _seam_segments() -> tuple[tuple[str, str, str], ...]:
    """Every place a member can be added to `CalendarMechanism`, tree-wide.

    Scoped to `CalendarMechanism.swift`, this scan was vacuous against the shape
    that actually arrives: a protocol extension in a **different** file adds
    `removeOccurrence` to every conformer of the seam without touching the file
    holding the protocol at all, and WP-17's reviewer proved it by planting one
    and watching the suite stay green. So the scan is the whole native tree —
    wider than `Sources/AppleSourceHost` on purpose, for WP-15's reason that the
    file a violation arrives in is the one nobody named.

    Returns `(kind, file, body)` triples so the declaration keeps its own
    assertions — inheritance is a property of the declaration and of nothing
    else — while every member assertion reads the union.
    """
    segments: list[tuple[str, str, str]] = []
    for path in _swift_files(HOST):
        source = _without_string_literals(_source(path))
        name = str(path.relative_to(ROOT))
        for match in SEAM_DECLARATION.finditer(source):
            segments.append(("declaration", name, source[match.end() :]))
        for match in SEAM_EXTENSION.finditer(source):
            segments.append(("extension", name, _balanced_body(source, match.end())))
    return tuple(segments)


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
    # The exemption set is exactly four directories. Widening it again should be
    # a decision somebody makes here, not a side effect of adding a target. It was
    # three until WP-18 added the Contacts shape probe, and the widening is
    # recorded in that package's record rather than absorbed silently.
    assert len(_probe_files()) == 5, (
        f"the compile-only probe set holds {len(_probe_files())} files. Each probe "
        "is one file and there are five of them; another is another place an "
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

#: The symbols the table above may never lose. A count floor alone is defeated by
#: swapping eighteen real spellings for eighteen that never occur; these are the
#: ones whose absence would let a genuine EventKit client through unnamed.
EVENT_KIT_SURFACE_FLOOR: Final = (
    "import EventKit",
    "EKEventStore",
    "EKEvent",
    "EKCalendar",
    "EKAuthorizationStatus",
)


def test_no_swift_outside_the_probes_can_reach_an_event_store() -> None:
    # **The table is the whole content of the assertion below, so it gets the
    # floor `PROBE_TARGETS` and the decode-path `subjects` already have.** WP-16's
    # reviewer found this exact shape in three separate guards and WP-17's found
    # it here: emptied to one never-occurring token, the loop finds nothing to
    # name and a shipping file with a real `import EventKit` and a real
    # `EKEventStore` passes. A count is not enough on its own — eighteen junk
    # tokens count the same as eighteen real ones — so the load-bearing spellings
    # are named as well.
    assert len(EVENT_KIT_SURFACE) >= 18, (
        f"the EventKit surface table names {len(EVENT_KIT_SURFACE)} symbols and the "
        "floor is 18. Shrinking it does not narrow this guard, it empties it: the "
        "assertion below can only report what this table told it to look for"
    )
    assert len(set(EVENT_KIT_SURFACE)) == len(EVENT_KIT_SURFACE), (
        "the EventKit surface table repeats a symbol, which meets the floor above "
        "without covering another way to reach a store"
    )
    missing = [symbol for symbol in EVENT_KIT_SURFACE_FLOOR if symbol not in EVENT_KIT_SURFACE]
    assert missing == [], (
        f"the EventKit surface table no longer names {missing}. The count floor is "
        "met by any eighteen strings; these five are the ones a real EventKit "
        "client cannot be written without"
    )

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

    And closed against every *file*, which is WP-17's own correction. Reading
    only `CalendarMechanism.swift` left the cheapest opening of all: a protocol
    extension elsewhere in the tree puts `removeOccurrence` on every conformer
    without editing the protocol. `_seam_segments` finds the declaration and each
    extension wherever they are; the member assertions below read the union.
    """
    segments = _seam_segments()
    declarations = [name for kind, name, _ in segments if kind == "declaration"]
    assert declarations == [str(MECHANISM.relative_to(ROOT))], (
        f"the calendar mechanism seam is declared in {declarations}. It must be "
        "declared exactly once and in CalendarMechanism.swift; a second "
        "declaration is a second seam and this guard would hold neither of them "
        "to the closed sets below"
    )
    body = next(text for kind, _, text in segments if kind == "declaration")
    assert len(body) > 100, "the seam scan read an empty protocol body"

    inherited = sorted(
        part.strip() for part in body.split("{", 1)[0].lstrip(": ").split(",") if part.strip()
    )
    assert inherited == ["Sendable"], (
        f"the calendar mechanism seam now inherits {inherited}. A parent "
        "protocol's requirements are this seam's requirements, and they arrive "
        "without appearing between the braces the rest of this test reads"
    )

    # Every member assertion from here reads the declaration *and* every
    # extension of the seam, joined. A default implementation in an extension is
    # a member of this seam on every conformer, so it belongs to the same closed
    # sets as the requirements between the protocol's own braces.
    where = sorted({name for _, name, _ in segments})
    members = "\n".join(text for _, _, text in segments)

    operations = sorted(set(re.findall(r"func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", members)))
    assert operations == sorted(MECHANISM_OPERATIONS), (
        f"the calendar mechanism seam now offers {operations}, declared across "
        f"{where}. Every operation on it must be a read: this seam is the only "
        "thing a live calendar mechanism would be asked for, so an operation that "
        "is not a read is a mutation path into somebody's calendar"
    )

    # `[^{}]+` rather than `[^\n{]+` for the type: Swift admits the accessor
    # block on the following line, and a regex anchored to one line would not see
    # `var isAllDay: Bool\n{ get set }` at all.
    properties = re.findall(r"var\s+([A-Za-z_][A-Za-z0-9_]*)\s*:[^{}]+\{([^}]*)\}", members)
    settable = sorted(name for name, accessors in properties if "set" in accessors.split())
    assert settable == [], (
        f"the calendar mechanism seam declares the settable properties {settable} "
        f"across {where}. A `{{ get }}` property is a read and is legal here; "
        "`{ get set }` is an assignment into somebody's calendar, and it is not a "
        "`func`, so the operation set above never sees it"
    )
    assert sorted(name for name, _ in properties) == sorted(MECHANISM_PROPERTIES), (
        f"the calendar mechanism seam now declares the properties "
        f"{sorted(name for name, _ in properties)} across {where}. The property "
        "set is closed for the same reason the operation set is"
    )
    assert "subscript" not in members, (
        f"the calendar mechanism seam declares a subscript, across {where}. A "
        "subscript is an operation with no name for the closed set above to hold, "
        "and a `{ get set }` subscript is a write into a calendar keyed by a string"
    )


#: The **closed set** of `EKEventStore` members the probe may name, rather than a
#: list of forbidden ones.
#:
#: A forbidden list forbids exactly the spellings whoever wrote it thought of,
#: and WP-17's reviewer proved that against the first draft: it rejected
#: `EKEventStore.save(` and `EKEventStore.remove(` and admitted `EKEventStore.save`
#: and `EKEventStore.remove` — valid *unapplied* method references, because the
#: parentheses are optional once a type annotation disambiguates the overload —
#: and both compiled and passed every guard in this repository. A closed set has
#: no such gap: a member that is not one of these six is a member that has to be
#: argued for here.
#:
#: The equality is deliberate in both directions. Padding this tuple with `save`
#: does not admit `save` — it demands the probe name it, and the probe naming it
#: is what the assertion is about.
EVENT_STORE_MEMBERS: Final = (
    "Type",
    "authorizationStatus",
    "calendars",
    "events",
    "predicateForEvents",
    "self",
)

#: EventKit's mutating half by name. None of it belongs in a read-only probe, and
#: `EKEventEditViewController` is on the list because a view controller that saves
#: an event is a save whatever it is spelled.
EVENT_KIT_MUTATION_SURFACE: Final = (
    "EKCalendarChooser",
    "EKEventEditViewController",
    "EKEventStoreChanged",
    "refreshSourcesIfNecessary",
    "removeCalendar",
    "removeEvent",
    "removeReminder",
    "saveCalendar",
    "saveEvent",
    "saveReminder",
)

#: The closed set of modules the probe may import. `"import EventKit" in probe` is
#: not this assertion and never was: `import EventKitUI` contains it as a
#: substring, so the substring test admits the framework whose whole purpose is
#: an editing view controller. Found by attacking this file's own first draft.
PROBE_IMPORTS: Final = ("EventKit",)

#: Every spelling that would put a live `EKEventStore` **instance** in scope, with
#: what each one is. `(EKEventStore) -> …` and `EKEventStore.Type` are excluded by
#: construction: the first is the parameter of the curried function type an
#: unapplied reference already has, and the second is a metatype. Neither is a
#: store.
#:
#: The parameter row was added after attacking the first draft of this list,
#: which caught construction and missed the shorter route:
#: `func leak(_ handed: EKEventStore) { _ = handed.save }` names no member *of the
#: type*, constructs nothing, and is an unapplied reference to the save the whole
#: package exists to be without.
#:
#: Every row here names `EKEventStore`, which is what makes them safe to scan the
#: **whole** native tree with rather than only the calendar probe — and the
#: probe's docstring needed exactly that, because it claims no event store is
#: constructed *anywhere in this repository* and the string turns out to be named
#: in two Swift files, not one: WP-15's multi-framework probe holds
#: `EKEventStore.self` too, and nothing held *it* to any of this.
EVENT_STORE_CONSTRUCTION: Final = (
    (r"EKEventStore\s*\(", "constructs an event store"),
    (r"EKEventStore\s*\.\s*init\b", "names the event store's initialiser"),
    (
        r"\b(?:let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*EKEventStore\b(?!\s*\.\s*Type)",
        "declares a variable whose type is an event store",
    ),
    (r"->\s*EKEventStore\b(?!\s*\.\s*Type)", "declares a function returning an event store"),
    (
        r"[(,]\s*(?:_|[A-Za-z_][A-Za-z0-9_]*)(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*"
        r":\s*EKEventStore\b(?!\s*\.\s*Type)",
        "declares a parameter whose type is an event store, which hands it an "
        "instance without constructing one",
    ),
)

#: The rows the **calendar probe alone** is held to. Each is ordinary Swift that
#: the shipping module and the contract checks use correctly — `try self.init(…)`
#: is the decode-path routing every other guard in this file *requires*, and
#: `FileManager.removeItem` is how a temporary directory is cleaned up — so
#: scanning the tree with them would redden on correct code. Inside a probe whose
#: entire body is metatypes, key paths and unapplied references, none of them has
#: a legitimate use.
PROBE_LOCAL_ACTIVATION: Final = (
    (r"\.\s*init\s*\(", "calls an initialiser, which is a construction under another name"),
    (
        r"\.\s*(?:save|remove|commit|reset|delete)[A-Za-z]*\b",
        "names a mutating member on something, and an instance member reference "
        "needs no event-store spelling in front of it to be a write",
    ),
    (
        r"\btypealias\b",
        "introduces an alias, and an alias is a spelling of a forbidden symbol that "
        "no scan above this line can see",
    ),
)


def test_the_event_kit_probe_reaches_no_store_in_any_spelling() -> None:
    """The constraints the probe's own docstring claims, actually enforced.

    Split out from the resolution floors below because it is the half that was
    *trusted* rather than enforced until WP-17's correction, and it is the half
    that matters: the resolution floors say the probe still proves something, and
    these say the probe still costs nothing.

    Note what is deliberately **not** enforced. Comment lines are stripped before
    scanning, so the probe's own docstring may keep discussing `save`, `remove`
    and `EKEventStore` in prose. That is WP-15's rule and it is a choice: a guard
    that reddens on the paragraph explaining it is a guard somebody deletes to
    get their paragraph back. The cost is that a trailing comment on a line of
    code is not stripped, which is a wider hole in the other direction and is
    accepted for the same reason.
    """
    # The whole directory rather than the one file it holds today: a second file
    # beside it is caught by the exemption-set floor in the first test above, and
    # this guard should not depend on that one to be reading everything.
    probe = "\n".join(_source(path) for path in _swift_files(EVENT_KIT_PROBE))
    assert "EKEventStore" in probe, "the probe scan is reading no event-store reference at all"

    imports = sorted(
        set(re.findall(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_.]*)", probe, re.MULTILINE))
    )
    assert imports == sorted(PROBE_IMPORTS), (
        f"the EventKit probe imports {imports} and the closed set is "
        f"{sorted(PROBE_IMPORTS)}. EventKitUI is the editing half of this framework "
        "and every other Apple module is WP-15's control 1; the probe's exemption "
        "is from one framework, not from the rule"
    )

    named = sorted(set(re.findall(r"EKEventStore\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)", probe)))
    assert named == sorted(EVENT_STORE_MEMBERS), (
        f"the EventKit probe names the event-store members {named} and the closed "
        f"set is {sorted(EVENT_STORE_MEMBERS)}. Every member here is read-only or a "
        "metatype; `save`, `remove`, `commit`, `reset` and `init` are not, and the "
        "unapplied spelling of each — no parentheses, disambiguated by the return "
        "type — is as real a reference as the applied one"
    )

    for pattern, what in EVENT_STORE_CONSTRUCTION + PROBE_LOCAL_ACTIVATION:
        found = re.search(pattern, probe)
        assert found is None, (
            f"the EventKit probe {what} (`{found.group(0) if found else ''}`). It "
            "exists to answer a compile-and-typecheck question without consent, and "
            "an event store that exists is one line from a TCC dialogue EXT-04 "
            "reserves to the operator and one more from an enumeration of somebody's "
            "calendar"
        )

    mutating = sorted(symbol for symbol in EVENT_KIT_MUTATION_SURFACE if symbol in probe)
    assert mutating == [], (
        f"the EventKit probe names {mutating}. A save or a remove would end the "
        "read-only claim outright, and it would do so even here, in a target "
        "nothing links: the claim WP-17 makes is about what this repository names, "
        "not only about what it runs"
    )


def test_no_swift_in_the_native_tree_constructs_an_event_store() -> None:
    """The probe docstring's widest claim, scanned as widely as it is stated.

    `test_no_swift_outside_the_probes_can_reach_an_event_store` exempts all three
    compile-only probes, and the guard above holds only the calendar one. That
    left the other two exempt from everything: `EKEventStore` is named in **two**
    Swift files, not the one §J of the record claimed, because WP-15's
    multi-framework probe holds `EKEventStore.self` as well — and WP-15's own
    activation list forbids `EKEventStore(` and not `EKEventStore.save`, which is
    the paren-suffixed gap WP-17's reviewer found here.

    So this scans **every** Swift file under `native/`, probes included, in the
    shape `test_the_calendar_seam_cannot_ask_for_an_authorization_it_does_not_have`
    already uses for the same reason: a store constructed in a
    compiled-but-never-called function is one edit away from being read from.
    """
    scanned = _swift_files(HOST)
    assert len(scanned) >= 24, f"the native scan found {len(scanned)} Swift files"

    naming = {}
    for path in scanned:
        source = _source(path)
        if "EKEventStore" not in source:
            continue
        name = str(path.relative_to(ROOT))
        for pattern, what in EVENT_STORE_CONSTRUCTION:
            found = re.search(pattern, source)
            assert found is None, (
                f"{name} {what} (`{found.group(0) if found else ''}`). No Swift file "
                "in this repository may hold a live event store: an instance is one "
                "line from the TCC dialogue EXT-04 reserves to the operator, and the "
                "target it sits in being linked by nothing is a property of today's "
                "Package.swift rather than of the code"
            )
        named = set(re.findall(r"EKEventStore\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)", source))
        unexpected = sorted(named - set(EVENT_STORE_MEMBERS))
        assert unexpected == [], (
            f"{name} names the event-store members {unexpected}, which are not in "
            f"the read-only closed set {sorted(EVENT_STORE_MEMBERS)}. The unapplied "
            "spelling — `EKEventStore.save`, no parentheses — is as real a reference "
            "as the applied one, and this scan sees both"
        )
        naming[name] = sorted(named)

    # Non-vacuity: the loop above skips files that never name the type, so it is
    # worth nothing unless some file does. Two do, and both are compile-only
    # probes — which is the fact §J of the record now states.
    assert sorted(naming) == [
        "native/apple-source-host/Compatibility/AppleCalendarEventKitProbe/CalendarEventKitShape.swift",
        "native/apple-source-host/Compatibility/AppleFrameworkCompatibilityProbe/FrameworkCompatibility.swift",
    ], f"the Swift files naming an event store are now {sorted(naming)}"


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
    """WP-16's count guard, extended to the third probe and then the fourth.

    The name is left alone deliberately: renaming a test changes an identifier
    other records cite, and the count it enforces is `PROBE_TARGETS`, which is
    asserted below rather than spelled in the name.

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
    assert len(PROBE_TARGETS) == 5, "the probe target set stopped naming all five probes"

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
