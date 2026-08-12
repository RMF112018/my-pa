"""WP-16's Mail controls, as guards rather than as claims.

WP-15 proved the shipping host links no Apple framework, so no mutating type
exists in it to call. WP-16 adds a Mail adapter, and the whole risk of that
addition is that a Mail adapter is the one component with an obvious reason to
reach for the frameworks WP-15 kept out. So these guards are written against the
two ways that could happen — by importing an automation framework into something
that ships, and by making the shipping target depend on the probe that already
imports one.

The remaining guards are about the bounds, and they are all one idea: **a bound
that only exists on an initialiser is not a bound**, because the same value can
arrive as JSON. WP-15 learned that on the page ceiling; the mail content bounds
are written the same way and checked here the same way.

Comment text is stripped before scanning, for WP-15's reason: a guard a code
comment can trip is a guard someone eventually weakens to get their comment back.

**What these guards are not.** They do not prove that Apple Mail can be read.
Nothing in this repository proves that, because proving it needs a TCC Automation
grant that only the operator can give, and asking for one is itself the thing
this package refuses to do. What the last two tests prove is narrower and is the
part that *can* be settled without consent: that the terminology the record
describes is the terminology Apple ships, read out of Apple's own dictionary file
rather than out of memory.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
HOST: Final = ROOT / "native" / "apple-source-host"
SHIPPING: Final = HOST / "Sources" / "AppleSourceHost"
MANIFEST: Final = HOST / "Package.swift"
AUTOMATION_PROBE: Final = HOST / "Compatibility" / "AppleMailAutomationShapeProbe"
PLATFORM_MAIL: Final = (
    HOST / "Sources" / "AppleSourceHostPlatform" / "AppleMailAutomationMechanism.swift"
)

MECHANISM: Final = SHIPPING / "MailMechanism.swift"
ADAPTER: Final = SHIPPING / "BoundedMailReadAdapter.swift"
FIXTURE: Final = SHIPPING / "FixtureMailMechanism.swift"
PROTOCOL: Final = SHIPPING / "NativeSourceProtocolV1.swift"

#: Apple's Mail scripting dictionary, on a machine that has Mail installed. It is
#: application *terminology* — a list of the words Mail answers to — and contains
#: no mailbox content of any kind. Reading it is how the automation probe's table
#: is verified instead of asserted.
MAIL_SDEF: Final = Path("/System/Applications/Mail.app/Contents/Resources/Mail.sdef")


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


def _swift_outside_the_automation_mechanisms() -> tuple[Path, ...]:
    """Every Swift file except the compile probe and admitted production reader.

    Wider than the shipping directory on purpose, and for the reason WP-15's
    correction established: the directory an automation import would actually
    arrive in is the one nobody named — a new tool target, a new test executable.
    The probe is the single place `ScriptingBridge` is permitted, and it is not
    excused; `test_the_mail_automation_probe_sends_no_event_and_is_never_linked`
    holds it to metatypes, a data table, and no event.
    """
    return tuple(
        path
        for path in _swift_files(HOST)
        if AUTOMATION_PROBE not in path.parents and path != PLATFORM_MAIL
    )


def _source(path: Path) -> str:
    return _without_comments(path.read_text(encoding="utf-8"))


# --- non-vacuity --------------------------------------------------------------


def test_the_mail_scan_is_reading_the_adapter_at_all() -> None:
    """Every assertion below is worthless if the scan reads nothing."""
    for path in (MECHANISM, ADAPTER, FIXTURE, PROTOCOL, PLATFORM_MAIL):
        assert path.is_file(), f"{path} is missing; the WP-16 scan reads nothing"
    assert "public protocol MailMechanism" in _source(MECHANISM)
    assert "public struct BoundedMailReadAdapter" in _source(ADAPTER)
    assert len(_swift_files(AUTOMATION_PROBE)) == 1

    scanned = set(_swift_outside_the_automation_mechanisms())
    assert set(_swift_files(SHIPPING)) < scanned, (
        "the Apple-event scan is no wider than Sources/AppleSourceHost"
    )
    assert scanned.isdisjoint(_swift_files(AUTOMATION_PROBE))
    assert scanned | set(_swift_files(AUTOMATION_PROBE)) | {PLATFORM_MAIL} == set(
        _swift_files(HOST)
    ), "a Swift file under native/ is in neither the Apple-event scan nor the probe"


# --- control 6: the seam is a read surface and nothing else -------------------

#: The closed set of operations `MailMechanism` may offer. Adding a sixth is a
#: decision about whether this host can act on a mailbox, and it should be made
#: on purpose rather than in a diff.
MECHANISM_OPERATIONS: Final = (
    "accounts",
    "consentState",
    "mailboxes",
    "messageContent",
    "messageSummaries",
)

#: The closed set of *properties* the seam may offer, every one of them
#: `{ get }`-only. A `{ get }` property is a read and stays legal; a `{ get set }`
#: property is an assignment into somebody's mailbox that the operation set above
#: cannot see, because it is not a `func`.
MECHANISM_PROPERTIES: Final = ("descriptor",)


def test_the_mail_mechanism_seam_declares_only_read_operations() -> None:
    """The seam is closed, and closed against every way Swift declares a member.

    **A `func` is not the only kind of operation a protocol can carry, and the
    first version of this guard only looked at `func`.** Both of

        var readStatus: Bool { get set }
        subscript(deleteMessage key: String) -> Bool { get set }

    compile as members of `MailMechanism`, are mutation paths into a mailbox in
    exactly the sense the failure message below describes, and were invisible to
    the operation regex. So the settable half of a property and the subscript
    form are checked here too.
    """
    body = _source(MECHANISM).split("public protocol MailMechanism", 1)[1]

    # The seam inherits `Sendable` and nothing else. A protocol inherits its
    # parents' requirements, so `MailMechanism: Sendable, SomeMutatingSeam` puts
    # every operation of that parent on this seam while every assertion below —
    # which reads only the text between `public protocol MailMechanism` and the
    # end of the file — sees an unchanged five-operation protocol.
    inherited = sorted(
        part.strip() for part in body.split("{", 1)[0].lstrip(": ").split(",") if part.strip()
    )
    assert inherited == ["Sendable"], (
        f"the mail mechanism seam now inherits {inherited}. A parent protocol's "
        "requirements are this seam's requirements, and they arrive without "
        "appearing between the braces the rest of this test reads"
    )

    operations = sorted(set(re.findall(r"func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", body)))
    assert operations == sorted(MECHANISM_OPERATIONS), (
        f"the mail mechanism seam now offers {operations}. Every operation on it "
        "must be a read: this seam is the only thing a live mail mechanism would "
        "be asked for, so an operation that is not a read is a mutation path into "
        "somebody's mailbox"
    )

    # `[^{}]+` rather than `[^\n{]+` for the type: Swift admits the accessor
    # block on the following line, and a regex anchored to one line would not
    # see `var readStatus: Bool\n{ get set }` at all.
    properties = re.findall(r"var\s+([A-Za-z_][A-Za-z0-9_]*)\s*:[^{}]+\{([^}]*)\}", body)
    settable = sorted(name for name, accessors in properties if "set" in accessors.split())
    assert settable == [], (
        f"the mail mechanism seam declares the settable properties {settable}. A "
        "`{ get }` property is a read and is legal here; `{ get set }` is an "
        "assignment into somebody's mailbox — `readStatus`, `deletedStatus`, "
        "`junkMailStatus` are all one-line properties in Apple Mail's own "
        "dictionary — and it is not a `func`, so the operation set above never "
        "sees it"
    )
    assert sorted(name for name, _ in properties) == sorted(MECHANISM_PROPERTIES), (
        f"the mail mechanism seam now declares the properties "
        f"{sorted(name for name, _ in properties)}. The property set is closed for "
        "the same reason the operation set is: every member of this seam is "
        "something a live mail mechanism will be asked for, and adding one is a "
        "decision rather than a line in a diff"
    )
    assert "subscript" not in body, (
        "the mail mechanism seam declares a subscript. A subscript is an "
        "operation with no name for the closed set above to hold, and a "
        "`{ get set }` subscript is a write into a mailbox keyed by a string. "
        "There is no read this seam needs that one of its five named operations "
        "cannot express"
    )


def test_the_mail_seam_cannot_ask_for_a_permission_it_does_not_have() -> None:
    """Observing consent is a read. *Requesting* it raises a TCC dialogue.

    EXT-04 is operator-gated, and a consent dialogue is not something a headless
    host may cause. The seam is therefore shaped so the adapter can learn that
    consent is absent and stop, and has no way at all to ask for it.
    """
    for path in _swift_outside_the_automation_mechanisms():
        source = _without_comments(path.read_text(encoding="utf-8"))
        for asking in (
            "requestConsent",
            "requestAuthorization",
            "requestAccess",
        ):
            assert asking not in source, (
                f"{path.relative_to(ROOT)} names {asking}. Consent is the "
                "operator's to give (EXT-04); this host may observe that it is "
                "absent and refuse, and may not raise the dialogue that asks"
            )
    platform = _source(PLATFORM_MAIL)
    assert "AEDeterminePermissionToAutomateTarget(" in platform
    assert re.search(r"AEDeterminePermissionToAutomateTarget\([\s\S]*?false\s*\)", platform), (
        "the production Mail consent check must pass askUserIfNeeded: false"
    )
    assert not any(
        asking in platform for asking in ("requestConsent", "requestAuthorization", "requestAccess")
    )


# --- control 6 and control 1: no Apple event leaves the shipping host ---------

#: Every way a macOS process drives another application by Apple event, plus the
#: frameworks that expose them. Nothing outside the automation shape probe may
#: name any of these.
#:
#: This matters more than the equivalent WP-15 list, because Apple Mail's
#: scripting dictionary is a read-**write** vocabulary and a TCC Automation grant
#: is per-application rather than per-command. There is no consent that permits
#: `date received` and withholds `delete`, so the only enforceable read-only
#: boundary is the client not linking this at all.
APPLE_EVENT_SURFACE: Final = (
    "import ScriptingBridge",
    "import OSAKit",
    "import AppleScriptKit",
    "import AppleScriptObjC",
    "import Carbon",
    "SBApplication",
    "SBElementArray",
    "SBObject",
    "NSAppleScript",
    "NSAppleEventDescriptor",
    "OSAScript",
    "OSALanguage",
    "executeAndReturnError",
    "executeAppleEvent",
    "AESendMessage",
    "AEDeterminePermission",
    "osascript",
)


def test_only_the_bounded_platform_mail_reader_can_send_read_apple_events() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _swift_outside_the_automation_mechanisms():
        source = _without_comments(path.read_text(encoding="utf-8"))
        named = sorted(symbol for symbol in APPLE_EVENT_SURFACE if symbol in source)
        if named:
            offenders[str(path.relative_to(ROOT))] = named
    assert offenders == {}, (
        f"{offenders} name an Apple-event or automation symbol. Apple Mail's "
        "scripting dictionary carries `delete`, `move`, `duplicate` and `send` "
        "alongside `date received`, and TCC grants Automation per application "
        "rather than per command — so a target that can send an event to Mail is "
        "a target that can empty a mailbox, whether or not it does today"
    )
    platform = _source(PLATFORM_MAIL)
    assert "import ScriptingBridge" in platform and "SBApplication(" in platform
    assert "dateReceived >= %@ AND dateReceived <= %@" in platform
    assert "maximumMatchingMessages" in platform and "maximumMailboxes" in platform
    for mutation in (
        "sendEvent(",
        ".setTo(",
        ".delete()",
        ".move(",
        ".duplicate(",
        ".send(",
        "executeAndReturnError",
    ):
        assert mutation not in platform, (
            f"the production Mail reader names mutating automation surface {mutation}"
        )


def test_the_mail_automation_probe_sends_no_event_and_is_never_linked() -> None:
    """What the probe proves, and the two things it must not become.

    It must not become a runtime path — nothing constructs an `SBApplication`,
    compiles a script, or sends an event — and it must not become a dependency of
    anything that ships, which would put the one framework that can mutate Apple
    Mail inside the module that talks to the application.
    """
    manifest = _without_comments(MANIFEST.read_text(encoding="utf-8"))
    assert "let package = Package(" in manifest and manifest.count('"AppleSourceHost"') >= 3, (
        "the manifest scan is not reading Package.swift"
    )

    # Counted, not walked. **The section-walking form of this guard does not
    # work, and finding that out is why it is written this way.** Planting
    # `dependencies: [...]` on the shipping target left both this test and
    # WP-15's `test_the_compatibility_probe_is_compile_only_and_never_linked_into_the_host`
    # green, because splitting on `name: "AppleSourceHost"` lands on the
    # *product* declaration a few lines above the target, whose section ends
    # before the plant. A count is immune to that: a probe named anywhere other
    # than its own `name:` is a probe something depends on, whatever the
    # manifest's formatting.
    #
    # `AppleFrameworkCompatibilityProbe` is covered here too. It is WP-15's
    # probe and WP-15's guard is not weakened or edited — but the same plant
    # slips past it, and a guard that could not see EventKit arriving in the
    # shipping module was measuring the wrong thing.
    for probe_target in ("AppleFrameworkCompatibilityProbe", "AppleMailAutomationShapeProbe"):
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

    probe = _source(AUTOMATION_PROBE / "MailAutomationShape.swift")
    assert "import ScriptingBridge" in probe, (
        "the probe no longer imports ScriptingBridge. Its whole value is that the "
        "compiler re-proves on every build that the mechanism is *present* — which "
        "is a different finding from 'the mechanism does not exist'"
    )
    for activation in (
        "SBApplication(",
        "applicationWithBundleIdentifier",
        "applicationWithURL",
        "applicationWithProcessIdentifier",
        "initWithBundleIdentifier",
        "sendEvent",
        "NSAppleScript",
        "OSAScript",
        "executeAndReturnError",
        ".activate()",
        ".get()",
        "try await",
    ):
        assert activation not in probe, (
            f"the Mail automation probe calls {activation}. It exists to answer a "
            "compile-and-link question without consent; constructing a scripting "
            "application or sending an event raises the TCC dialogue that EXT-04 "
            "reserves to the operator"
        )
    assert probe.count(".self") >= 3, "the probe stopped referencing metatypes"


# --- control 4: bodies are carried whole or omitted whole --------------------


def test_the_mail_content_bounds_exist_and_are_frozen_in_the_protocol() -> None:
    """The bounds belong to the protocol, not to whichever adapter builds a page."""
    protocol = _source(PROTOCOL)
    for name, value in (
        ("maximumMailBodyBytes", "262_144"),
        ("maximumMailHeaderBytes", "65_536"),
        ("maximumMailAttachmentDescriptors", "32"),
        ("maximumMailAttachmentBytes", "26_214_400"),
        ("maximumMailIdentityComponentBytes", "64"),
    ):
        assert f"public static let {name} = {value}" in protocol, (
            f"the frozen mail bound {name} = {value} is no longer declared in the "
            "protocol. A bound an adapter owns is a bound the next adapter does "
            "not have"
        )


def test_a_mail_body_is_carried_whole_or_omitted_whole_and_never_trimmed() -> None:
    """The one invariant that makes truncation unrepresentable.

    `body != nil` implies `body!.count == completeness.bodyByteSize`. A truncated
    body has fewer bytes than the size it claims, so it cannot be built and it
    cannot be decoded. Every other phrasing of this bound — a `prefix`, a
    `clamp`, a `min` over the ceiling — produces a value that reads as complete
    and is not, which is §28's silent loss.
    """
    adapter = _source(ADAPTER)
    assert "body.count == completeness.bodyByteSize" in adapter, (
        "the invariant tying a carried body to its declared size is gone. Without "
        "it a trimmed body is a valid value, and a trimmed body is indistinguishable "
        "from a short one"
    )
    assert "throw NativeSourceContractError.mailHeaderTooLarge" in adapter, (
        "an over-long header block no longer refuses the record; headers have no "
        "honest partial form, so the only alternatives are refusal and silent loss"
    )
    for trimming in (
        "bodyBytes.prefix",
        "body.prefix",
        "headerBytes.prefix",
        "headers.prefix",
        "truncat",
    ):
        assert trimming not in adapter, (
            f"the mail adapter now trims with {trimming}. A body or header cut at "
            "a byte boundary is loss the consumer cannot detect; the permitted "
            "partial forms are whole omissions, and each records what it omitted"
        )


def test_mail_refuses_the_total_message_bound_before_materializing_headers_or_attachments() -> None:
    source = _source(PLATFORM_MAIL)
    size_check = source.index("messageSize")
    headers = source.index("let headers:")
    attachments = source.index("let attachments =")
    body = source.index("let body:")
    assert size_check < headers < attachments < body
    assert "maximumMailHeaderBytes" in source[size_check:headers]
    assert "maximumMailBodyBytes" in source[size_check:headers]


def test_every_mail_content_bound_is_enforced_on_the_decode_path_too() -> None:
    """WP-15's lesson, applied to the content bounds.

    A bound enforced only on the memberwise initialiser holds for values built in
    Swift and not for the same values arriving as JSON, which is the shape the
    host would actually be handed.

    **A decoder that exists is not a decoder that validates**, and the first
    version of this guard asserted only the first of those. A decoder rewritten
    to assign its stored properties directly compiles, keeps the literal string
    this test looked for, and skips every `guard` in the throwing initialiser —
    so an over-ceiling attachment mislabelled `metadata_only` would decode off
    the wire. The routing is therefore asserted as well: the decoder must reach
    the validating initialiser (`try self.init(…)`, or `Self(rawValue:)` for the
    failable one) and must assign no stored property of its own.

    This remains a *static* check, and the runtime one is the one that matters:
    `AppleSourceHostContractChecks::checkMailAttachmentDescriptorBoundsHoldOffTheWire`
    decodes the malformed JSON and requires the failure.
    """
    for path, types in (
        (ADAPTER, ("MailContentCompleteness", "MailRecordContent")),
        (
            MECHANISM,
            ("MailIdentityComponent", "MailDayWindow", "MailAttachmentDescriptor"),
        ),
    ):
        source = _source(path)
        for type_name in types:
            body = source.split(f"public struct {type_name}", 1)[1].split("\npublic ", 1)[0]
            assert "public init(from decoder: Decoder)" in body, (
                f"{type_name} carries an invariant and decodes off the wire with no "
                "validating decoder of its own; the bound would hold only for "
                "values built in Swift"
            )
            decoder = body.split("public init(from decoder: Decoder)", 1)[1].split("\n    }", 1)[0]
            assert "try self.init(" in decoder or "Self(rawValue:" in decoder, (
                f"{type_name}'s decoder no longer routes through its validating "
                "initialiser. A decoder that builds the value some other way is a "
                "decoder that skips every guard the initialiser holds, and the "
                "bound then applies only to values built in Swift — which is the "
                "defect this test was written to catch, in the one shape it could "
                "not see"
            )
            assigned = sorted(set(re.findall(r"self\.([A-Za-z_][A-Za-z0-9_]*)\s*=[^=]", decoder)))
            assert assigned == [], (
                f"{type_name}'s decoder assigns {assigned} directly. Direct "
                "assignment is exactly how a decoder keeps its shape and loses its "
                "validation: the fields arrive off the wire unchecked"
            )


def test_the_mail_identity_alphabet_excludes_the_composition_separator() -> None:
    """Injectivity, which is what stops two messages becoming one record.

    `MailMessageIdentity.recordIdentifier()` joins the mailbox, the generation and
    the provider key with `:`. `NativeSourceOpaqueID` admits `:`, so the
    restriction has to live on the component alphabet or the join is ambiguous.
    """
    mechanism = _source(MECHANISM)
    body = mechanism.split("public struct MailIdentityComponent", 1)[1].split(
        "public struct MailMessageIdentity", 1
    )[0]
    alphabet = re.search(r'charactersIn: "([^"]+)"', body)
    assert alphabet is not None, "the identity component alphabet is no longer declared"
    assert ":" not in alphabet.group(1), (
        "the mail identity component alphabet now admits ':', which is the "
        "separator recordIdentifier() joins with. Two distinct identities would "
        "compose to one record identifier and silently become one message"
    )
    assert "throw NativeSourceContractError.mailIdentityTooLong" in mechanism, (
        "an over-long identity is no longer refused. A trimmed identity is the "
        "one truncation with no honest partial form: it aliases two messages"
    )


def test_a_mechanism_that_publishes_no_generation_cannot_be_read_from() -> None:
    """Control 2's structural half.

    A provider key means nothing outside the generation that issued it — IMAP
    says a UID is meaningful only within a `UIDVALIDITY`. Apple Mail's scripting
    terminology publishes no equivalent, so a future automation mechanism has to
    solve that before it can traverse rather than discovering it downstream.
    """
    adapter = _source(ADAPTER)
    assert "guard mechanism.descriptor.publishesGeneration else {" in adapter
    assert "throw NativeSourceContractError.mailGenerationUnavailable" in adapter, (
        "the adapter will now read from a mechanism that cannot name its "
        "generation, which is how an identifier that silently re-points gets minted"
    )
    assert "throw NativeSourceContractError.mailDateBoundNotSourceSide" in adapter, (
        "the adapter no longer refuses a date-bounded read against a mechanism "
        "that can only filter after a full scan; 'bounded without enumerating the "
        "store' is the acceptance and a full scan is not it"
    )


# --- the mechanism evidence, checked against Apple's own dictionary -----------


def _sdef_root() -> ElementTree.Element:
    if not MAIL_SDEF.is_file():
        pytest.skip(f"{MAIL_SDEF} is not present on this machine")
    # The input is Apple's own signed system resource at a fixed absolute path
    # under `/System`, on a sealed volume, read only to compare its declarations
    # against a table in this repository. It is not untrusted input, and adding a
    # parsing dependency to read one system file would be the larger change.
    return ElementTree.parse(MAIL_SDEF).getroot()  # noqa: S314


def _probe_terms(table: str) -> tuple[tuple[str, str, str], ...]:
    """The automation probe's terminology table, parsed out of the Swift source.

    Read from the probe rather than restated here, so that the probe and this
    guard cannot drift apart into two lists that agree with nothing.
    """
    probe = _source(AUTOMATION_PROBE / "MailAutomationShape.swift")
    body = probe.split(f"{table}: [Term] = [", 1)[1].split("\n    ]", 1)[0]
    return tuple(
        (scripting_class, member, code)
        for scripting_class, member, code in re.findall(
            r'Term\(scriptingClass: "([^"]*)", member: "([^"]*)", code: "([^"]*)"\)',
            body,
        )
    )


def test_the_probe_read_shape_is_read_only_in_apples_own_dictionary() -> None:
    """The evidence for "discovery and traversal exist", read out of the source.

    Every term the probe lists as read-shaped must actually be declared by Mail,
    on the class the probe says, with the code the probe says, and with
    `access="r"`. A table nobody checks is a table that becomes wrong quietly.
    """
    root = _sdef_root()
    terms = _probe_terms("readShapeTerms")
    assert len(terms) >= 12, f"the probe's read-shape table parsed to {len(terms)} terms"

    declared: dict[tuple[str, str], tuple[str, str]] = {}
    for suite in root.iter("suite"):
        for element in suite.iter("class"):
            class_name = element.get("name", "")
            for member in element.iter("property"):
                declared[(class_name, member.get("name", ""))] = (
                    member.get("code", ""),
                    member.get("access", "rw"),
                )

    missing = [term for term in terms if (term[0], term[1]) not in declared]
    assert missing == [], (
        f"{missing} are listed by the Mail automation probe as read-shaped "
        f"terminology and are not declared by {MAIL_SDEF}. The probe's table is "
        "the record's evidence that discovery and traversal exist at all"
    )
    wrong = [
        (term, declared[(term[0], term[1])])
        for term in terms
        if declared[(term[0], term[1])] != (term[2], "r")
    ]
    assert wrong == [], (
        f"{wrong} disagree with Apple's dictionary on the four-character code or "
        "on read-only access"
    )


def test_apple_mail_consent_cannot_withhold_the_mutation_surface() -> None:
    """The control-6 finding, stated as a measurement rather than a caution.

    TCC Automation is granted per *(client, target application)* pair, not per
    command. So a grant that permits reading `date received` is the same grant
    that permits `coredelo` at a mailbox. This asserts the mutation half of the
    dictionary really is there — because if it were not, the record's central
    reason for keeping the automation framework out of everything that ships
    would be wrong.
    """
    root = _sdef_root()
    terms = _probe_terms("mutationTermsConsentCannotWithhold")

    # **A floor, because without one this test measures nothing.** The body of
    # this check is a loop over the probe's table, and an empty table is a loop
    # that runs zero times and passes: emptying
    # `mutationTermsConsentCannotWithhold` to `[Term] = [\n    ]` leaves this
    # module at 13 passed while the record still calls this "the control-6
    # finding, stated as a measurement".
    #
    # **Ten, and not fewer.** Ten is the whole table, not a sample of it, and
    # the two halves carry different halves of the finding: the five commands
    # are the mutation a grant carries in its own right — `delete` (`coredelo`),
    # `move` (`coremove`) and `duplicate` (`coreclon`) are the three §A names as
    # destructive — and the five settable properties are the mutation the same
    # grant carries *at a message*, which is the half a reader is least likely
    # to believe without seeing it measured. Any floor below ten would let one
    # of those halves be deleted with this guard still green. The sibling
    # read-shape floor is `>= 12` over sixteen terms because that table's job is
    # to establish a *shape* and a shape survives losing an entry; this table's
    # job is to establish a *finding*, and a finding measured from a shrinking
    # table is a different finding.
    assert len(terms) >= 10, (
        f"the probe's mutation table parsed to {len(terms)} terms. This test is "
        "a loop over that table, so a short table is a quiet way to stop "
        "measuring the finding that control 6 rests on: that a TCC Automation "
        "grant which permits reading `date received` is the same grant that "
        "permits `coredelo` at a mailbox"
    )
    assert len(set(terms)) == len(terms), (
        f"the probe's mutation table holds {len(terms)} entries and only "
        f"{len(set(terms))} distinct ones. A repeated term satisfies the floor "
        "above without adding a measurement, which is the obvious way past it"
    )
    commands_listed = {member for scripting_class, member, _ in terms if scripting_class == ""}
    properties_listed = {(cls, member) for cls, member, _ in terms if cls != ""}
    assert {"delete", "move", "duplicate"} <= commands_listed, (
        f"the probe's mutation table lists the commands {sorted(commands_listed)} "
        "and no longer names all three of `delete`, `move` and `duplicate`. Those "
        "are the three commands §A reads out of Mail's dictionary as "
        '`<access-group identifier="*"/>`, and they are the reason the automation '
        "framework is kept out of everything that ships"
    )
    assert properties_listed, (
        "the probe's mutation table now lists commands only. The settable "
        "properties are the half that shows the grant mutates *a message* — "
        "`read status`, `deleted status`, `junk mail status` — and dropping them "
        "leaves the finding resting on the half nobody doubts"
    )

    commands = {
        element.get("name", ""): element.get("code", "")
        for suite in root.iter("suite")
        for element in suite.iter("command")
    }
    settable: dict[tuple[str, str], str] = {}
    for suite in root.iter("suite"):
        for element in suite.iter("class"):
            for member in element.iter("property"):
                if member.get("access", "rw") != "r":
                    settable[(element.get("name", ""), member.get("name", ""))] = member.get(
                        "code", ""
                    )

    for scripting_class, member, code in _probe_terms("mutationTermsConsentCannotWithhold"):
        if scripting_class == "":
            assert commands.get(member) == code, (
                f"the probe lists the command `{member}` ({code}) as mutation the "
                f"consent cannot withhold, and {MAIL_SDEF} does not declare it "
                "that way. Either the finding or the table is wrong, and the "
                "record rests on the finding"
            )
        else:
            assert settable.get((scripting_class, member)) == code, (
                f"the probe lists {scripting_class}.{member} ({code}) as settable "
                f"and {MAIL_SDEF} does not declare it settable"
            )


def test_no_entitlement_or_usage_declaration_was_added_for_the_mail_mechanism() -> None:
    """The tripwire, restated for the key this package would have needed.

    A live automation mechanism needs `NSAppleEventsUsageDescription` in an
    Info.plist and, under the App Sandbox,
    `com.apple.security.automation.apple-events` plus a temporary-exception entry
    naming `com.apple.mail`. None of that exists here and none of it may arrive
    without the signing work that owns it (EXT-03). WP-15 already fails the build
    if such a file appears; this reads the same tree for the *contents* that would
    make one meaningful, so a key smuggled into some other file type is caught too.
    """
    forbidden = (
        "NSAppleEventsUsageDescription",
        "com.apple.security.automation.apple-events",
        "com.apple.security.temporary-exception.apple-events",
        "com.apple.security.network.client",
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
        f"{offenders} declare a usage description or an entitlement for Apple "
        "events or the network. Both are EXT-03/EXT-04 and operator-gated; WP-16 "
        "proves the mechanism's shape without activating any of it"
    )
