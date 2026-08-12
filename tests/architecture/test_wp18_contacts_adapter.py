"""WP-18's Contacts controls, as guards rather than as claims.

WP-15 proved the shipping host links no Apple framework, WP-16 preserved it and
WP-17 preserved it again. WP-18 adds a contacts adapter, and the risk of *this*
addition is different in kind from WP-17's rather than merely sharper.

A calendar read is bounded by a horizon: the thing that can go wrong is that it
reads too much *time*. A contacts read is bounded by a **key set**: the thing
that can go wrong is that it reads too much *about a person*. One line —
`keysToFetch` gaining a name key — turns a structural adapter into an address
book in a public repository, and no horizon, page ceiling or cursor catches it.
So the first guard below is the key set, and it is a privacy control rather than
an optimisation.

The rest are the semantics a contacts adapter loses quietly: an identifier
treated as stable when the source will not vouch for it, a group membership
discarded and delivered as "in no group", a grant revoked in System Settings
while the process is still reading, and a refusal that arrives downstream looking
like an empty address book.

Comment text is stripped before scanning, for WP-15's reason: a guard a code
comment can trip is a guard someone eventually weakens to get their comment back.

**What these guards are not.** They do not prove that contacts can be read.
Nothing in this repository proves that, because proving it needs a TCC grant only
the operator can give and this package must not obtain — and **no contact
belonging to anyone was read to write any of it**. What the probe guard proves is
narrower and is the part that can be settled without consent: that the symbols a
minimum-key read-only contacts adapter would need exist in this SDK and typecheck
on this toolchain.
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
PLATFORM_SHIPPING: Final = HOST / "Sources" / "AppleSourceHostPlatform"
PLATFORM_HOST: Final = HOST / "Sources" / "AppleSourceHostPlatformHost"
MANIFEST: Final = HOST / "Package.swift"

FRAMEWORK_PROBE: Final = HOST / "Compatibility" / "AppleFrameworkCompatibilityProbe"
MAIL_PROBE: Final = HOST / "Compatibility" / "AppleMailAutomationShapeProbe"
EVENT_KIT_PROBE: Final = HOST / "Compatibility" / "AppleCalendarEventKitProbe"
CONTACTS_PROBE: Final = HOST / "Compatibility" / "AppleContactsShapeProbe"

#: The four compile-only probe targets. Each is declared in `Package.swift` on
#: the same footing, each is a dependency of nothing, and each is the only place
#: its framework may be named. It was three before this package; the widening is
#: recorded in `docs/campaign/WP-18-CONTACTS-ADAPTER-RECORD.md` §H rather than
#: absorbed silently.
PROBES: Final = (FRAMEWORK_PROBE, MAIL_PROBE, EVENT_KIT_PROBE, CONTACTS_PROBE)
PROBE_TARGETS: Final = (
    "AppleFrameworkCompatibilityProbe",
    "AppleMailAutomationShapeProbe",
    "AppleCalendarEventKitProbe",
    "AppleContactsShapeProbe",
)

MECHANISM: Final = SHIPPING / "ContactsMechanism.swift"
ADAPTER: Final = SHIPPING / "BoundedContactsReadAdapter.swift"
IDENTITY: Final = SHIPPING / "ContactsIdentity.swift"
FIXTURE: Final = SHIPPING / "FixtureContactsMechanism.swift"
PROTOCOL: Final = SHIPPING / "NativeSourceProtocolV1.swift"
CHECKS: Final = HOST / "Tests" / "AppleSourceHostContractChecks" / "main.swift"

#: Every Swift file this package owns, plus its probe. Scanned by the guards that
#: would redden on legitimate code elsewhere — `score` is an ordinary word in a
#: search ranker and is not an ordinary word here.
CONTACTS_FILES: Final = (MECHANISM, ADAPTER, IDENTITY, FIXTURE)


#: A closed `/* … */` span, non-greedy so nested openers do not swallow code.
BLOCK_COMMENT: Final = re.compile(r"/\*[\s\S]*?\*/")


def _without_comments(source: str) -> str:
    """Drop comment text, keeping every line that also carries code.

    Whole-line `//` prose is dropped deliberately: a forbidden symbol named in
    the paragraph that explains why it is forbidden must stay invisible, because
    a guard that reddens on its own rationale is a guard somebody deletes.

    Closed `/* … */` **spans** are blanked before that line filter rather than
    their lines being dropped whole. Dropping the line was fail-open: a comment
    that ends mid-line leaves code after it, so
    `/* shape */ public static func plantedSave() -> CNSaveRequest.Type { … }`
    compiled, named a forbidden symbol, and was invisible to every text guard
    below. Blanking preserves newlines, so a multi-line span still leaves the
    code around it on the lines it was written on, and an opener with no closer
    still starts its line with `/*` and is dropped as before.
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
    """Every Swift file under `native/` except the four compile-only probes."""
    return tuple(path for path in _swift_files(HOST) if path not in _probe_files())


def _source(path: Path) -> str:
    return _without_comments(path.read_text(encoding="utf-8"))


def _probe_source() -> str:
    return "\n".join(_source(path) for path in _swift_files(CONTACTS_PROBE))


#: `\b` rather than a bare prefix: `ContactsMechanismKind` and
#: `ContactsMechanismDescriptor` both start with the seam's name, and an
#: `extension ContactsMechanismDescriptor` is not an extension of the seam.
SEAM_DECLARATION: Final = re.compile(r"public protocol ContactsMechanism\b")
SEAM_EXTENSION: Final = re.compile(r"\bextension\s+ContactsMechanism\b")

#: Multiline first, then raw, then plain — a `"""` block matched as three plain
#: literals would blank the wrong spans.
STRING_LITERAL: Final = re.compile(r'"""[\s\S]*?"""' + r'|#+"[\s\S]*?"#+' + r'|"(?:[^"\\\n]|\\.)*"')


def _without_string_literals(source: str) -> str:
    """Blank the *contents* of Swift string literals, preserving every offset.

    WP-17's correction found this the hard way: a `}` inside a string literal
    closes a brace Swift never opened, so
    `extension ContactsMechanism { static let closer = "}" … }` would truncate the
    body and hide whatever is declared underneath it. Blanking is
    length-preserving because the match offsets are used to slice the source.
    """

    def blank(match: re.Match[str]) -> str:
        return "".join(character if character == "\n" else " " for character in match.group(0))

    return STRING_LITERAL.sub(blank, source)


def _balanced_body(source: str, start: int) -> str:
    """The brace-balanced block beginning at the first `{` after `start`."""
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


PUBLIC_FUNCTION: Final = re.compile(r"\bpublic func\s+([A-Za-z_][A-Za-z0-9_]*)")


def _public_functions(source: str) -> tuple[tuple[str, str], ...]:
    """Every `public func` in `source`, paired with its first statement.

    Quantifying over the entry points beats naming them. A guard that inspects
    the operations it already knows about is green the moment a third one is
    added, which is exactly the moment it needed to speak.
    """
    blanked = _without_string_literals(source)
    functions: list[tuple[str, str]] = []
    for match in PUBLIC_FUNCTION.finditer(blanked):
        body = _balanced_body(blanked, match.start())
        opening = next((line.strip() for line in body.splitlines() if line.strip()), "")
        functions.append((match.group(1), opening))
    return tuple(functions)


def _seam_segments() -> tuple[tuple[str, str, str], ...]:
    """Every place a member can be added to `ContactsMechanism`, tree-wide.

    Scoped to `ContactsMechanism.swift` this scan would be vacuous against the
    shape that actually arrives: a protocol extension in a **different** file adds
    `deleteContact` to every conformer of the seam without touching the file
    holding the protocol at all. WP-17's reviewer proved that by planting one and
    watching the suite stay green, so this module is written in the corrected
    shape from the start.
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


def _enum_cases(source: str, declaration: str) -> list[tuple[str, str]]:
    """`(case name, raw value)` pairs of one enum, raw value defaulting to the name."""
    body = source.split(declaration, 1)[1].split("\n}", 1)[0]
    pairs: list[tuple[str, str]] = []
    for match in re.finditer(r"case\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:=\s*\"([^\"]*)\")?", body):
        pairs.append((match[1], match[2] if match[2] is not None else match[1]))
    return pairs


# --- non-vacuity --------------------------------------------------------------


def test_the_wp18_scan_is_reading_the_contacts_adapter_at_all() -> None:
    """Every assertion below is worthless if the scan reads nothing.

    A guard that scans an empty set passes vacuously, and every module in this
    campaign that skipped this test had at least one guard that was doing exactly
    that.
    """
    for path in (MECHANISM, ADAPTER, IDENTITY, FIXTURE, PROTOCOL, CHECKS):
        assert path.is_file(), f"{path} is missing; the WP-18 scan reads nothing"
    assert "public protocol ContactsMechanism" in _source(MECHANISM)
    assert "public struct BoundedContactsReadAdapter" in _source(ADAPTER)
    assert "public struct ContactIdentity" in _source(IDENTITY)
    assert "public enum ContactIdentityAssurance" in _source(IDENTITY)
    assert "public final class FixtureContactsMechanism" in _source(FIXTURE)
    assert "CNContactStore" in _probe_source(), "the contacts probe scan is reading nothing"
    assert len(_swift_files(CONTACTS_PROBE)) == 1

    scanned = set(_swift_outside_the_probes())
    assert len(scanned) >= 18, f"the WP-18 scan found {len(scanned)} Swift files under native/"
    assert set(CONTACTS_FILES) < scanned, "a WP-18 shipping file is outside the tree scan"
    assert set(_swift_files(SHIPPING)) < scanned, (
        "the contacts scan is no wider than Sources/AppleSourceHost"
    )
    assert scanned.isdisjoint(_probe_files())
    assert scanned | _probe_files() == set(_swift_files(HOST)), (
        "a Swift file under native/ is in neither the contacts scan nor a probe"
    )
    # The exemption set is exactly four directories. Widening it again should be a
    # decision somebody makes here, not a side effect of adding a target.
    assert len(_probe_files()) == 4, (
        f"the compile-only probe set holds {len(_probe_files())} files. Each probe "
        "is one file and there are four of them; a fifth is a fifth place an Apple "
        "framework is permitted, and that is a decision rather than a diff"
    )


# --- control 1: the minimum key set, which is the privacy control -------------

#: The frozen minimum, spelled from outside Swift so it cannot grow quietly.
#:
#: Two keys. The equality below is two-way on purpose: padding this tuple does
#: not admit a third key, it demands that Swift declare one — and declaring one
#: is the decision this guard exists to make visible.
MINIMUM_KEYS: Final = (
    ("identifier", "contact_identifier"),
    ("structuralType", "contact_structural_type"),
)

#: Every vocabulary a content-bearing key would be spelled in: the framework's own
#: key constants and the property names behind them. **None of these may appear
#: anywhere under `native/`, probes included.**
#:
#: The probe is not excused here and that is the point of the table. A probe that
#: resolves a name key has written into a public repository that this package
#: knows how to ask for somebody's name, which is a fact about the package and not
#: only about what it runs.
CONTACTS_CONTENT_SURFACE: Final = (
    "CNContactGivenNameKey",
    "CNContactFamilyNameKey",
    "CNContactMiddleNameKey",
    "CNContactNicknameKey",
    "CNContactNamePrefixKey",
    "CNContactNameSuffixKey",
    "CNContactOrganizationNameKey",
    "CNContactJobTitleKey",
    "CNContactDepartmentNameKey",
    "CNContactEmailAddressesKey",
    "CNContactPhoneNumbersKey",
    "CNContactPostalAddressesKey",
    "CNContactUrlAddressesKey",
    "CNContactSocialProfilesKey",
    "CNContactInstantMessageAddressesKey",
    "CNContactBirthdayKey",
    "CNContactDatesKey",
    "CNContactRelationsKey",
    "CNContactNoteKey",
    "CNContactImageDataKey",
    "CNContactThumbnailImageDataKey",
    "CNContactImageDataAvailableKey",
    "givenName",
    "familyName",
    "emailAddresses",
    "phoneNumbers",
    "postalAddresses",
    "instantMessageAddresses",
    "socialProfiles",
    "organizationName",
    "thumbnailImageData",
    "imageData",
)

#: The spellings the table above may never lose. A count floor alone is defeated
#: by swapping thirty-two real spellings for thirty-two that never occur; these
#: are the ones whose absence would let a genuine content fetch through unnamed.
CONTACTS_CONTENT_FLOOR: Final = (
    "CNContactGivenNameKey",
    "CNContactFamilyNameKey",
    "CNContactEmailAddressesKey",
    "CNContactPhoneNumbersKey",
    "CNContactPostalAddressesKey",
    "CNContactBirthdayKey",
    "CNContactNoteKey",
    "CNContactImageDataKey",
    "givenName",
    "emailAddresses",
)


def test_the_minimum_contacts_key_set_is_frozen_and_holds_no_content_key() -> None:
    """Control 1, pinned from outside Swift.

    The strongest form of this control is not that a wider key set is rejected —
    it is that a wider key set has **no spelling**: the fetch-key vocabulary is
    the minimum, so widening the request and widening the vocabulary are one
    edit. This guard holds that edit in one place.
    """
    mechanism = _source(MECHANISM)
    declared = _enum_cases(mechanism, "public enum ContactsFetchKey")
    assert declared == list(MINIMUM_KEYS), (
        f"the contacts fetch-key vocabulary is now {declared} and the frozen "
        f"minimum is {list(MINIMUM_KEYS)}. Every key declared here is personal "
        "data pulled out of a store and into a process, so a third case is a "
        "decision about somebody's privacy rather than a line in a diff"
    )
    assert (
        "public static let keys: [ContactsFetchKey] = [.identifier, .structuralType]" in mechanism
    ), (
        "the frozen minimum key list is no longer declared in the shape this guard "
        "reads. It must be the whole vocabulary, in canonical order"
    )
    for name, raw in declared:
        for content in CONTACTS_CONTENT_SURFACE:
            assert content.lower() not in name.lower() and content.lower() not in raw.lower(), (
                f"the fetch key {name} ({raw}) names the content vocabulary "
                f"{content}. The minimum key set carries no content-bearing key: "
                "no name, no email address, no telephone number, no postal "
                "address, no birthday, no photograph, no note, no organization "
                "name, no social profile, no instant-message handle"
            )

    # The request path sets the key list from the frozen minimum rather than
    # taking one from a caller, and refuses anything else on both the query and
    # the record.
    adapter = _source(ADAPTER)
    assert "requestedKeys: ContactsMinimumKeySet.keys" in adapter, (
        "the adapter no longer sets the key list itself. A mechanism must be told "
        "what it may fetch, not asked to be careful"
    )
    assert mechanism.count("throw NativeSourceContractError.contactsKeySetWidened") == 2, (
        "the key-set refusal is no longer enforced on both the query and the "
        "observation. Either alone leaves the other free to widen"
    )
    assert "throw NativeSourceContractError.contactsKeySetWidened" in adapter, (
        "the adapter no longer re-checks the key set per record, so a mechanism "
        "that fetched more than it was asked for is believed"
    )


def test_no_content_bearing_contacts_key_is_named_anywhere_under_native() -> None:
    """The whole tree, probes included, held to the key set the record claims."""
    assert len(CONTACTS_CONTENT_SURFACE) >= 32, (
        f"the contacts content table names {len(CONTACTS_CONTENT_SURFACE)} symbols "
        "and the floor is 32. Shrinking it does not narrow this guard, it empties "
        "it: the assertion below can only report what this table told it to look for"
    )
    assert len(set(CONTACTS_CONTENT_SURFACE)) == len(CONTACTS_CONTENT_SURFACE), (
        "the contacts content table repeats a symbol, which meets the floor above "
        "without covering another way to fetch somebody's details"
    )
    missing = [key for key in CONTACTS_CONTENT_FLOOR if key not in CONTACTS_CONTENT_SURFACE]
    assert missing == [], (
        f"the contacts content table no longer names {missing}. The count floor is "
        "met by any thirty-two strings; these ten are the ones a real content fetch "
        "cannot be written without"
    )

    offenders: dict[str, list[str]] = {}
    for path in _swift_files(HOST):
        source = _source(path)
        named = sorted(key for key in CONTACTS_CONTENT_SURFACE if key in source)
        if named:
            offenders[str(path.relative_to(ROOT))] = named
    assert offenders == {}, (
        f"{offenders} name a content-bearing contacts key. WP-18 requests the "
        "minimum: an opaque identifier and a structural type discriminator. A key "
        "beyond those is somebody's name, address or photograph moving out of a "
        "store, and this repository is public"
    )


# --- control 5: no contact store, and no mutation, anywhere -------------------

#: The **closed set** of contact-store members any Swift file under `native/` may
#: name, rather than a list of forbidden ones.
#:
#: A forbidden list forbids exactly the spellings whoever wrote it thought of, and
#: WP-17's reviewer proved that against its first draft: it rejected
#: `EKEventStore.save(` and admitted `EKEventStore.save` — a valid *unapplied*
#: method reference, because the parentheses are optional once a type annotation
#: disambiguates the overload — and it compiled and passed every guard in the
#: repository. A closed set has no such gap: a member that is not one of these
#: seven is a member that has to be argued for here.
#:
#: The equality is deliberate in both directions. Padding this tuple with
#: `execute` does not admit `execute` — it demands that some file name it, and a
#: file naming it is what the assertion is about.
CONTACT_STORE_MEMBERS: Final = (
    "Type",
    "authorizationStatus",
    "containers",
    "enumerateContacts",
    "groups",
    "self",
    "unifiedContacts",
)

#: Every spelling that would put a live contact store **instance** in scope, with
#: what each one is. `(CNContactStore) -> …` and `CNContactStore.Type` are
#: excluded by construction: the first is the parameter of the curried function
#: type an unapplied reference already has, and the second is a metatype. Neither
#: is a store.
#:
#: The parameter row is not decoration. `func leak(_ handed: CNContactStore) { _ =
#: handed.execute }` names no member *of the type*, constructs nothing, and is an
#: unapplied reference to the save this whole package exists to be without.
CONTACT_STORE_CONSTRUCTION: Final = (
    (r"CNContactStore\s*\(", "constructs a contact store"),
    (r"CNContactStore\s*\.\s*init\b", "names the contact store's initialiser"),
    (
        r"\b(?:let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*CNContactStore\b(?!\s*\.\s*Type)",
        "declares a variable whose type is a contact store",
    ),
    (r"->\s*CNContactStore\b(?!\s*\.\s*Type)", "declares a function returning a contact store"),
    (
        r"[(,]\s*(?:_|[A-Za-z_][A-Za-z0-9_]*)(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*"
        r":\s*CNContactStore\b(?!\s*\.\s*Type)",
        "declares a parameter whose type is a contact store, which hands it an "
        "instance without constructing one",
    ),
)

#: The Contacts framework's mutating half by name, plus the editing UI. **None of
#: it may appear anywhere under `native/`**, in any file, including the probes.
#:
#: `CNSaveRequest` is the whole mutation surface of this framework: adding,
#: updating and deleting a contact, a group, a container, and adding or removing a
#: member of a group are all methods on it, executed by one call on the store. A
#: file that names it is a file one line from writing somebody's address book.
CONTACTS_MUTATION_SURFACE: Final = (
    "CNSaveRequest",
    "CNMutableContact",
    "CNMutableGroup",
    "CNMutablePostalAddress",
    "import ContactsUI",
    "CNContactViewController",
    "CNContactPickerViewController",
    "deleteContainer",
    "executeSave",
    "addContact",
    "updateContact",
    "deleteContact",
    "addGroup",
    "updateGroup",
    "deleteGroup",
    "addMember",
    "removeMember",
    "addSubgroup",
    "removeSubgroup",
    "updateContainer",
    "requestAccess",
)

#: The rows the table above may never lose.
CONTACTS_MUTATION_FLOOR: Final = (
    "CNSaveRequest",
    "CNMutableContact",
    "addContact",
    "deleteContact",
    "addMember",
    "requestAccess",
)


def test_no_swift_in_the_native_tree_constructs_a_contact_store() -> None:
    """Scanned as widely as the probe's docstring states its claim.

    **Every** Swift file under `native/`, probes included, from the start. WP-17
    learned that the hard way: its first guard exempted the probe directories, and
    the type turned out to be named in two of them rather than one, so the other
    was exempt from everything. `CNContactStore` is likewise named in two files
    here — this package's probe and WP-15's multi-framework probe — and both are
    held to the same closed set.
    """
    scanned = _swift_files(HOST)
    assert len(scanned) >= 28, f"the native scan found {len(scanned)} Swift files"
    assert len(CONTACT_STORE_MEMBERS) == 7, (
        "the closed contact-store member set changed size. Every member of it must "
        "be a read or a metatype, and adding one is an argument to be had here"
    )

    naming = {}
    for path in scanned:
        source = _source(path)
        if "CNContactStore" not in source:
            continue
        name = str(path.relative_to(ROOT))
        if PLATFORM_SHIPPING in path.parents:
            construction_patterns = CONTACT_STORE_CONSTRUCTION[:2]
        elif PLATFORM_HOST in path.parents:
            # The explicitly non-live executable constructs only the inert
            # production composition. Keep every other instance-bearing form,
            # permission request, enumeration, and mutation spelling forbidden.
            assert source.count("CNContactStore()") == 1
            construction_patterns = CONTACT_STORE_CONSTRUCTION[1:4]
        else:
            construction_patterns = CONTACT_STORE_CONSTRUCTION
        for pattern, what in construction_patterns:
            found = re.search(pattern, source)
            assert found is None, (
                f"{name} {what} (`{found.group(0) if found else ''}`). No Swift file "
                "in this repository may hold a live contact store: an instance is "
                "one line from the TCC dialogue EXT-04 reserves to the operator, "
                "and the target it sits in being linked by nothing is a property of "
                "today's Package.swift rather than of the code"
            )
        named = set(re.findall(r"CNContactStore\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)", source))
        unexpected = sorted(named - set(CONTACT_STORE_MEMBERS))
        assert unexpected == [], (
            f"{name} names the contact-store members {unexpected}, which are not in "
            f"the read-only closed set {sorted(CONTACT_STORE_MEMBERS)}. The "
            "unapplied spelling — `CNContactStore.execute`, no parentheses — is as "
            "real a reference as the applied one, and this scan sees both"
        )
        naming[name] = sorted(named)

    # Non-vacuity: the loop above skips files that never name the type, so it is
    # worth nothing unless some file does. Two are probes, two receive injected
    # stores, and the last is the exact inert dry-run composition root.
    assert sorted(naming) == [
        "native/apple-source-host/Compatibility/AppleContactsShapeProbe/ContactsShape.swift",
        "native/apple-source-host/Compatibility/AppleFrameworkCompatibilityProbe/FrameworkCompatibility.swift",
        "native/apple-source-host/Sources/AppleSourceHostPlatform/ContactsStoreMechanism.swift",
        "native/apple-source-host/Sources/AppleSourceHostPlatform/PlatformAppleSourceComposition.swift",
        "native/apple-source-host/Sources/AppleSourceHostPlatformHost/main.swift",
    ], f"the Swift files naming a contact store are now {sorted(naming)}"


def test_no_swift_in_the_native_tree_names_a_contacts_mutation_symbol() -> None:
    """Control 5, tree-wide and probes included.

    A read-only *grant* is not offered by this framework — there is one contacts
    authorization and it covers both directions — and a read-only *framework* is
    not on offer either: one store answers `unifiedContacts(matching:keysToFetch:)`
    and executes a save request. So the only enforceable read-only boundary is
    that the save surface is never named, and that the client never links the
    framework at all, which is WP-15's control 1 measured with `otool -L`.
    """
    assert len(CONTACTS_MUTATION_SURFACE) >= 20, (
        f"the contacts mutation table names {len(CONTACTS_MUTATION_SURFACE)} "
        "symbols and the floor is 20. Emptying it does not narrow this guard, it "
        "empties it"
    )
    assert len(set(CONTACTS_MUTATION_SURFACE)) == len(CONTACTS_MUTATION_SURFACE), (
        "the contacts mutation table repeats a symbol, which meets the floor above "
        "without covering another way to write an address book"
    )
    missing = [s for s in CONTACTS_MUTATION_FLOOR if s not in CONTACTS_MUTATION_SURFACE]
    assert missing == [], (
        f"the contacts mutation table no longer names {missing}. The count floor is "
        "met by any twenty strings; these six are the ones a real mutation cannot "
        "be written without"
    )

    offenders: dict[str, list[str]] = {}
    for path in _swift_files(HOST):
        source = _source(path)
        named = sorted(symbol for symbol in CONTACTS_MUTATION_SURFACE if symbol in source)
        if named:
            offenders[str(path.relative_to(ROOT))] = named
    assert offenders == {}, (
        f"{offenders} name a contacts mutation symbol. `CNSaveRequest` is the whole "
        "write surface of this framework — add, update and delete for contacts, "
        "groups and containers, plus group membership — and naming it ends WP-18's "
        "read-only claim whether or not the call site is reached today"
    )


def test_the_contacts_seam_cannot_ask_for_an_authorization_it_does_not_have() -> None:
    """Observing authorization is a read. *Requesting* it raises a TCC dialogue.

    Scanned over the **whole** native tree, probes included: the probe has no more
    business raising a consent dialogue than the shipping module does, and a
    request API named in a compiled-but-never-called function is one edit away
    from being called.
    """
    for path in _swift_files(HOST):
        source = _source(path)
        for asking in (
            "requestAccess",
            "requestAuthorization",
            "requestConsent",
            "requestFullAccess",
            "presentLimitedLibraryPicker",
        ):
            assert asking not in source, (
                f"{path.relative_to(ROOT)} names {asking}. A contacts grant is the "
                "operator's to give (EXT-04); this host may observe that it is "
                "absent and refuse, and may not raise the dialogue that asks"
            )


#: The closed set of operations `ContactsMechanism` may offer. Adding a sixth is a
#: decision about whether this host can act on an address book.
MECHANISM_OPERATIONS: Final = (
    "accounts",
    "authorizationState",
    "contacts",
    "containers",
    "groups",
)

#: The closed set of *properties* the seam may offer, every one `{ get }`-only.
MECHANISM_PROPERTIES: Final = ("descriptor",)


def test_the_contacts_mechanism_seam_declares_only_read_operations() -> None:
    """The seam is closed, and closed against every way Swift declares a member.

    Written in WP-16's and WP-17's *corrected* shape rather than their first ones,
    because both corrections were bought at the cost of a reviewer proving the
    first shape vacuous. A `func` regex sees neither `var isFavourite: Bool { get
    set }` nor `subscript(delete key: String) -> Bool { get set }`, and both are
    writes into somebody's address book. Inherited requirements are closed too — a
    mutating parent protocol puts its operations on this seam without appearing
    between the braces every other assertion reads. And the scan is every file
    under `native/`, because a protocol extension elsewhere puts a member on every
    conformer without touching the file that declares the protocol.
    """
    segments = _seam_segments()
    declarations = [name for kind, name, _ in segments if kind == "declaration"]
    assert declarations == [str(MECHANISM.relative_to(ROOT))], (
        f"the contacts mechanism seam is declared in {declarations}. It must be "
        "declared exactly once and in ContactsMechanism.swift; a second declaration "
        "is a second seam and this guard would hold neither of them to the closed "
        "sets below"
    )
    body = next(text for kind, _, text in segments if kind == "declaration")
    assert len(body) > 100, "the seam scan read an empty protocol body"

    inherited = sorted(
        part.strip() for part in body.split("{", 1)[0].lstrip(": ").split(",") if part.strip()
    )
    assert inherited == ["Sendable"], (
        f"the contacts mechanism seam now inherits {inherited}. A parent protocol's "
        "requirements are this seam's requirements, and they arrive without "
        "appearing between the braces the rest of this test reads"
    )

    where = sorted({name for _, name, _ in segments})
    members = "\n".join(text for _, _, text in segments)

    operations = sorted(set(re.findall(r"func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", members)))
    assert operations == sorted(MECHANISM_OPERATIONS), (
        f"the contacts mechanism seam now offers {operations}, declared across "
        f"{where}. Every operation on it must be a read: this seam is the only "
        "thing a live contacts mechanism would be asked for, so an operation that "
        "is not a read is a mutation path into somebody's address book. There is no "
        "save, add, update, delete, execute or commit here, and no request for "
        "consent either"
    )
    for forbidden in ("save", "add", "update", "delete", "remove", "execute", "commit", "request"):
        assert not any(operation.startswith(forbidden) for operation in operations), (
            f"the contacts mechanism seam offers an operation beginning `{forbidden}`"
        )

    properties = re.findall(r"var\s+([A-Za-z_][A-Za-z0-9_]*)\s*:[^{}]+\{([^}]*)\}", members)
    settable = sorted(name for name, accessors in properties if "set" in accessors.split())
    assert settable == [], (
        f"the contacts mechanism seam declares the settable properties {settable} "
        f"across {where}. A `{{ get }}` property is a read and is legal here; "
        "`{ get set }` is an assignment into somebody's address book, and it is not "
        "a `func`, so the operation set above never sees it"
    )
    assert sorted(name for name, _ in properties) == sorted(MECHANISM_PROPERTIES), (
        f"the contacts mechanism seam now declares the properties "
        f"{sorted(name for name, _ in properties)} across {where}. The property set "
        "is closed for the same reason the operation set is"
    )
    assert "subscript" not in members, (
        f"the contacts mechanism seam declares a subscript, across {where}. A "
        "subscript is an operation with no name for the closed set above to hold, "
        "and a `{ get set }` subscript is a write into an address book keyed by a "
        "string"
    )


#: The closed set of modules the contacts probe may import. `"import Contacts" in
#: probe` is not this assertion and never was: `import ContactsUI` contains it as
#: a substring, so the substring test admits the framework whose whole purpose is
#: an editing view controller.
PROBE_IMPORTS: Final = ("Contacts",)

#: The rows the **contacts probe alone** is held to. Each is ordinary Swift that
#: the shipping module and the contract checks use correctly — `try self.init(…)`
#: is the decode-path routing every other guard in this file *requires* — so
#: scanning the tree with them would redden on correct code. Inside a probe whose
#: entire body is metatypes, key paths and unapplied references, none of them has
#: a legitimate use.
PROBE_LOCAL_ACTIVATION: Final = (
    (r"\.\s*init\s*\(", "calls an initialiser, which is a construction under another name"),
    (
        r"\.\s*(?:save|add|update|delete|remove|execute|commit)[A-Za-z]*\b",
        "names a mutating member on something, and an instance member reference "
        "needs no store spelling in front of it to be a write",
    ),
    (
        r"\btypealias\b",
        "introduces an alias, and an alias is a spelling of a forbidden symbol that "
        "no scan above this line can see",
    ),
    (r"\btry\s+await\b", "awaits something, and this target runs nothing"),
)


def test_the_contacts_probe_reaches_no_store_in_any_spelling() -> None:
    """The constraints the probe's own docstring claims, actually enforced.

    Note what is deliberately **not** enforced. Comment lines are stripped before
    scanning, so the probe's own docstring may keep discussing the save request in
    prose. That is WP-15's rule and it is a choice: a guard that reddens on the
    paragraph explaining it is a guard somebody deletes to get their paragraph
    back. The cost is that a trailing comment on a line of code is not stripped
    either, which is a wider hole in the other direction and is accepted for the
    same reason.
    """
    probe = _probe_source()
    assert "CNContactStore" in probe, "the probe scan is reading no contact-store reference at all"

    imports = sorted(
        set(re.findall(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_.]*)", probe, re.MULTILINE))
    )
    assert imports == sorted(PROBE_IMPORTS), (
        f"the contacts probe imports {imports} and the closed set is "
        f"{sorted(PROBE_IMPORTS)}. ContactsUI is the editing half of this framework "
        "and every other Apple module is WP-15's control 1; the probe's exemption is "
        "from one framework, not from the rule"
    )

    named = sorted(set(re.findall(r"CNContactStore\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)", probe)))
    assert named == sorted(CONTACT_STORE_MEMBERS), (
        f"the contacts probe names the contact-store members {named} and the closed "
        f"set is {sorted(CONTACT_STORE_MEMBERS)}. Every member here is read-only or "
        "a metatype; `execute` and `init` are not, and the unapplied spelling of "
        "each — no parentheses, disambiguated by the return type — is as real a "
        "reference as the applied one"
    )

    for pattern, what in CONTACT_STORE_CONSTRUCTION + PROBE_LOCAL_ACTIVATION:
        found = re.search(pattern, probe)
        assert found is None, (
            f"the contacts probe {what} (`{found.group(0) if found else ''}`). It "
            "exists to answer a compile-and-typecheck question without consent, and "
            "a contact store that exists is one line from a TCC dialogue EXT-04 "
            "reserves to the operator and one more from an enumeration of somebody's "
            "address book"
        )


def test_the_contacts_probe_resolves_symbols_and_reaches_no_store() -> None:
    """What the probe proves, and the two things it must not become.

    It must not become a runtime path — nothing constructs a store, requests an
    authorization or enumerates anything — and it must not become a dependency of
    anything that ships, which would put the framework that can rewrite an address
    book inside the module that talks to the application.
    """
    probe = _probe_source()
    assert "import Contacts" in probe, (
        "the probe no longer imports Contacts. Its whole value is that the compiler "
        "re-proves on every build that the read mechanism is *present* — which is a "
        "different finding from 'the mechanism does not exist'"
    )

    for activation in (
        "CNContactStore(",
        "CNContact(",
        "CNContactFetchRequest(",
        "requestAccess",
        ".execute(",
        ".save(",
        "unifiedContacts(matching:keysToFetch:)(",
        "authorizationStatus(for:)(",
    ):
        assert activation not in probe, (
            f"the contacts probe calls {activation}. It exists to answer a "
            "compile-and-typecheck question without consent; constructing a store or "
            "requesting an authorization raises the TCC dialogue that EXT-04 "
            "reserves to the operator, and a save would end the read-only claim "
            "outright"
        )

    # **Floors, because without them this test measures nothing.** The probe's
    # value is entirely in how many symbols it makes the compiler resolve, and a
    # probe emptied to a bare `import Contacts` would satisfy every assertion above
    # while proving only that the framework exists.
    metatypes = probe.count(".self")
    key_paths = re.findall(r"\\CN[A-Za-z]+\.[A-Za-z]+", probe)
    unapplied = re.findall(r"CNContactStore\.[a-zA-Z]+\([a-zA-Z:]*\)\n?\s*$", probe, re.MULTILINE)
    assert metatypes >= 5, f"the probe resolves {metatypes} metatypes; it stopped proving types"
    assert len(key_paths) >= 7, (
        f"the probe resolves {len(key_paths)} member key paths. A metatype proves a "
        "*type* resolves; a key path proves a *member* resolves, and the members — "
        "the identifier, the structural type, the container's kind — are where a "
        "contacts adapter's assumptions actually live"
    )
    assert len(set(key_paths)) == len(key_paths), (
        f"the probe's key paths hold {len(key_paths)} entries and only "
        f"{len(set(key_paths))} distinct ones; a repeated key path meets the floor "
        "above without resolving another member"
    )
    for required in (
        r"\CNContact.identifier",
        r"\CNContact.contactType",
        r"\CNContainer.identifier",
        r"\CNContainer.type",
        r"\CNGroup.identifier",
    ):
        assert required in probe, (
            f"the probe no longer resolves {required}. Each of these carries one of "
            "WP-18's controls: the identifier is the whole of stable identity, the "
            "structural type is the second and last key requested, and the container "
            "and group identifiers are the tree membership has to survive in"
        )
    assert len(unapplied) >= 4, (
        f"the probe resolves {len(unapplied)} unapplied contact-store methods. The "
        "container listing, the group listing, the keyed read and the authorization "
        "observation are the four a read-only adapter would be built from"
    )
    # The two key constants, and only those two.
    constants = sorted(set(re.findall(r"\bCNContact[A-Za-z]*Key\b", probe)))
    assert constants == ["CNContactIdentifierKey", "CNContactTypeKey"], (
        f"the probe names the key constants {constants}. Exactly two are the frozen "
        "minimum, and a third is a key this package has written down as one it "
        "knows how to ask for"
    )


def test_the_four_probes_are_compile_only_and_never_linked_into_the_host() -> None:
    """WP-16's count guard, extended to the fourth probe.

    Counted, not walked, for the reason WP-16 recorded after finding out the hard
    way: splitting `Package.swift` on `name: "AppleSourceHost"` lands on the
    *product* declaration a few lines above the target, whose section closes before
    any dependency list, so a planted dependency stayed green in both this guard's
    ancestor and WP-15's. A count is immune to the manifest's formatting: a probe
    named anywhere other than its own `name:` is a probe something depends on.
    """
    manifest = _without_comments(MANIFEST.read_text(encoding="utf-8"))
    assert "let package = Package(" in manifest and manifest.count('"AppleSourceHost"') >= 3, (
        "the manifest scan is not reading Package.swift"
    )
    assert len(PROBE_TARGETS) == 4, "the probe target set stopped naming all four probes"

    for probe_target in PROBE_TARGETS:
        occurrences = manifest.count(f'"{probe_target}"')
        assert occurrences == 1, (
            f"{probe_target} is named {occurrences} times in Package.swift as a "
            "quoted token. Exactly one is legitimate — its own target's `name:`. A "
            "second is a dependency, a product membership, or a target list, and any "
            "of those links an Apple framework into something that ships. The "
            "shipping module linking none of them is WP-15's control 1, proved at "
            "link time, and it is the strongest guarantee in this package"
        )
        assert f'name: "{probe_target}"' in manifest


# --- control 2: identity that makes instability visible ----------------------


def test_the_contacts_identity_alphabet_excludes_the_composition_separator() -> None:
    """Injectivity, which is what stops a group and a contact colliding.

    Contacts branch where a calendar nests: a container holds groups *and*
    contacts, so two different things sit at the same depth and separator count
    alone cannot tell them apart. The composition carries a fixed discriminator
    field drawn from a closed set, and no component can forge it because the
    component alphabet excludes `:`.
    """
    identity = _source(IDENTITY)
    body = identity.split("public struct ContactsIdentityComponent", 1)[1].split(
        "public enum ContactsIdentityBranch", 1
    )[0]
    alphabet = re.search(r'charactersIn: "([^"]+)"', body)
    assert alphabet is not None, "the identity component alphabet is no longer declared"
    assert ":" not in alphabet.group(1), (
        "the contacts identity component alphabet now admits ':', which is the "
        "separator the levels are joined with. Two distinct identities would compose "
        "to one identifier and silently become one person"
    )
    assert 'separator = ":"' in identity, "the composition separator is no longer declared"
    assert "throw NativeSourceContractError.contactsIdentityTooLong" in identity, (
        "an over-long identity is no longer refused. A trimmed identity is the one "
        "truncation with no honest partial form: it aliases two people onto one record"
    )
    branch = _enum_cases(identity, "public enum ContactsIdentityBranch")
    assert sorted(name for name, _ in branch) == ["contact", "group"], (
        f"the identity branch discriminator now has the cases {branch}. It is what "
        "keeps a group and a contact at the same depth apart, and it is closed"
    )
    for level in (
        "public struct ContactsAccountIdentity",
        "public struct ContactsContainerIdentity",
        "public struct ContactsGroupIdentity",
        "public struct ContactIdentity",
    ):
        assert level in identity, (
            f"{level} is gone. The tree is account, container, group and contact, and "
            "a missing level is a level that gets reconstructed by guesswork downstream"
        )


def test_a_contact_identity_carries_its_epoch_and_states_its_own_assurance() -> None:
    """Control 2: a re-minted identifier is **detectable**, not silent.

    The hazard is specific and documented: a restore, a re-sync, or an account
    removed and re-added can re-mint every contact identifier in a container. An
    identity recording only the identifier would be a correct-looking key that
    quietly starts pointing at somebody else — or, worse, produces a second record
    for one person that nothing downstream can recognise as a duplicate.

    Two mechanisms together, and neither alone is enough: the epoch is a *field of
    the identity*, so a re-mint yields a disjoint key space rather than an
    overlapping one; and every observation states how far the mechanism vouches for
    its key, so `unknown` cannot be read as a guarantee.
    """
    identity = _source(IDENTITY)
    mechanism = _source(MECHANISM)
    adapter = _source(ADAPTER)

    contact = identity.split("public struct ContactIdentity", 1)[1].split("\n    public init", 1)[0]
    assert "public let identityEpoch: ContactsIdentityComponent" in contact, (
        "the contact identity no longer carries its epoch. An identifier stored "
        "without the epoch it is only stable within is an identifier that silently "
        "re-points"
    )
    composition = identity.split("public struct ContactIdentity", 1)[1].split(
        "func recordIdentifier", 1
    )[1]
    assert "identityEpoch.rawValue" in composition.split("\n    }", 1)[0], (
        "the epoch is no longer part of the composed record identifier, so a re-mint "
        "produces the same key for a different person"
    )

    assurance = _enum_cases(identity, "public enum ContactIdentityAssurance")
    assert sorted(name for name, _ in assurance) == [
        "reMintedInThisEpoch",
        "stableWithinEpoch",
        "unknown",
    ], (
        f"the identity assurance vocabulary is now {assurance}. Three answers are "
        "load-bearing: vouched for within the epoch, known to have been re-minted, "
        "and not characterised at all. Collapsing the third into the first is how an "
        "unstable identifier is read as a stable one"
    )

    stored = _stored_property_lines(mechanism, "ContactObservation")
    assert "public let identityAssurance: ContactIdentityAssurance" in stored, (
        f"the contact observation declares {stored}. Its assurance must be present "
        "and must not be optional: an observation that does not state its assurance "
        "is one a consumer will assume is stable"
    )
    assert not any("?" in line for line in stored), (
        f"a contact observation field became optional: {stored}. An absent field is "
        "read as an absent fact, and none of these is ever absent"
    )

    assert "throw NativeSourceContractError.contactsIdentityEpochUnavailable" in adapter, (
        "the adapter no longer refuses a mechanism that cannot name its identity "
        "epoch. Minting an identity anyway hands every downstream reconciler a key "
        "that silently re-points"
    )
    assert "throw NativeSourceContractError.contactsIdentityEpochMismatch" in adapter, (
        "the adapter no longer cross-checks the epoch a result declares against the "
        "epoch its records are keyed with"
    )


# --- control 3: the tree survives the read -----------------------------------


def test_container_and_group_membership_survives_in_the_existing_envelope() -> None:
    """`account → container → group → contact`, in the vocabulary already there.

    No parallel envelope is invented: a container and a group are both
    `NativeSourceBucket`s and the group's `parentID` names its container, which is
    a field the admitting application already understands. Membership rides on the
    observation, is bounded, and is re-checked against what discovery published.
    """
    adapter = _source(ADAPTER)
    mechanism = _source(MECHANISM)

    assert "parentID: try descriptor.identity.container.recordIdentifier()" in adapter, (
        "a group no longer names its container as its parent, so the tree does not "
        "survive discovery"
    )
    assert "kind: .contacts" in adapter, "the contacts adapter stopped emitting contacts records"
    for refusal in (
        "throw NativeSourceContractError.contactsMembershipInconsistent",
        "throw NativeSourceContractError.contactsUnknownGroup",
        "throw NativeSourceContractError.contactsMembershipUnavailable",
    ):
        assert refusal in adapter, (
            f"the adapter no longer raises {refusal.rsplit('.', 1)[1]}. Membership is "
            "part of the observation: a group with no container, a membership naming "
            "a group nothing published, and a mechanism that cannot report membership "
            "at all are three different failures and all three are refusals"
        )

    stored = _stored_property_lines(mechanism, "ContactObservation")
    assert "public let groupKeys: [ContactsIdentityComponent]" in stored, (
        f"the contact observation declares {stored}. Membership is carried on the "
        "record, not discarded and re-derived later"
    )
    assert "throw NativeSourceContractError.contactsGroupLimitExceeded" in mechanism, (
        "the membership ceiling no longer refuses. A shortened membership list is "
        "indistinguishable from a person who is genuinely in fewer groups"
    )
    assert "throw NativeSourceContractError.contactsMembershipInconsistent" in mechanism, (
        "a membership list with no canonical order is no longer refused, so two equal "
        "memberships can encode two ways"
    )

    # Every bound this adapter holds is a refusal of the whole page. A page
    # silently missing the records that failed a check is a page that reads as
    # complete.
    assert "filter" not in adapter, (
        "the contacts adapter now filters its page. Dropping the records that failed "
        "a check produces a page that reads as complete and is not"
    )
    for clamping in ("prefix(", "clamp", "truncat", "min(", "dropLast"):
        assert clamping not in adapter, (
            f"the contacts adapter now clamps with {clamping}. An over-bound request "
            "is refused, never narrowed: a narrowed answer reads as complete and is not"
        )


# --- control 4: fail closed, and stay closed ---------------------------------


def test_contacts_authorization_fails_closed_and_cannot_degrade_to_an_empty_page() -> None:
    """The distinction the campaign has enforced since WP-09.

    A page of zero records means "you have no contacts". Returning that when the
    real answer is "we were never allowed to look" is a lie, and it is a lie a
    consumer will act on by concluding that an address book is empty.
    """
    adapter = _source(ADAPTER)
    body = adapter.split("private func requireAuthorization() throws {", 1)[1].split("\n    }", 1)[
        0
    ]
    arms = re.findall(r"case\s+\.([A-Za-z_][A-Za-z0-9_]*):", body)
    assert sorted(arms) == ["authorized", "denied", "notDetermined", "restricted"], (
        f"the authorization switch now handles {sorted(arms)}. It must handle every "
        "state the framework distinguishes on this platform, one arm each, so that "
        "adding a state is a compile error rather than a silent admission"
    )
    assert "default" not in body, (
        "the authorization switch has a `default` arm. A state nobody has heard of is "
        "not a state to read somebody's address book on, and a `default` is how one "
        "gets admitted"
    )
    refusing = body.split("case .denied:", 1)[1]
    assert refusing.count("throw NativeProviderFailure.permissionDenied") == 3, (
        "one of the three non-authorized states no longer throws. Every one of them "
        "must refuse; the only permitted `return` in this function is the authorized "
        "arm's"
    )
    assert refusing.count("return") == 0, (
        "a non-authorized arm now returns rather than throwing, which is exactly how "
        "a refusal degrades into an empty page"
    )
    assert "NativeReadPage(records: [])" not in adapter, (
        "the contacts adapter now has a path that fabricates an empty page. Empty and "
        "unavailable are different facts and must be different values"
    )
    for entry in ("public func discoverContactCollections", "public func readContacts"):
        section = adapter.split(entry, 1)[1][:400]
        assert "try requireAuthorization()" in section, (
            f"{entry} no longer checks authorization before its first read"
        )


def test_a_revoked_contacts_grant_cannot_be_served_from_a_cache() -> None:
    """Control 4's second half, which WP-17 did not have to answer.

    A contacts grant can be withdrawn in System Settings while this process is
    still running. An adapter that consulted authorization once — at construction,
    or on the first call — would keep serving afterwards, and an adapter that kept
    the last page would serve *that*. Both are closed structurally rather than by
    a comment: authorization is consulted at the top of every operation, and the
    type has nowhere to keep a page.
    """
    adapter = _source(ADAPTER)

    # Quantified over *every* public function rather than over the operations
    # this package happens to have written. The counting form this replaced
    # asserted `== 2`, and a third public read that reached the mechanism with
    # no authorization check at all left the count at two: the guard was green
    # on precisely the change it existed to catch. A fourth operation is caught
    # by the assertion below without anyone remembering to edit it.
    entry_points = _public_functions(adapter)
    assert len(entry_points) >= 2, (
        f"the public-entry-point scan found {len(entry_points)} functions in the "
        "contacts adapter, so the check below is quantifying over nothing"
    )
    for name, opening in entry_points:
        assert opening == "try requireAuthorization()", (
            f"public func {name} opens with `{opening}` rather than "
            "`try requireAuthorization()`. Every public operation consults "
            "authorization first and on every call: an operation that skips the "
            "check is the one a mid-session revocation outlives"
        )
    assert adapter.count("try requireAuthorization()") == len(entry_points), (
        f"authorization is called {adapter.count('try requireAuthorization()')} "
        f"times across {len(entry_points)} public operations. Exactly one call "
        "per operation: a spare call is a call some other operation is not making"
    )

    stored = [
        line.strip()
        for line in adapter.splitlines()
        if re.match(r"\s*(?:private|public|internal|fileprivate)\s+(?:let|var)\s", line)
        and "{" not in line
    ]
    assert stored == ["private let mechanism: any ContactsMechanism"], (
        f"the contacts adapter now stores {stored}. Its only stored property may be "
        "the mechanism: anything else is state a revoked grant can leave behind, and "
        "a cached page served after a revocation is a read the operator withdrew "
        "consent for"
    )
    for cache in ("cache", "cached", "memo", "lazy var", "static var", "lastPage", "remember"):
        assert cache not in adapter, (
            f"the contacts adapter names {cache}. A cache is how a revoked grant keeps "
            "answering, and there is no read here that needs one"
        )

    # And the runtime proof exists rather than being promised. The fixture models
    # the revocation and the harness measures that the source is never touched
    # again; a guard that only read the adapter's source would pass on an adapter
    # that re-checks and then serves anyway.
    fixture = _source(FIXTURE)
    assert "case revokeAuthorizationAfterTheFirstCheck" in fixture, (
        "the fixture no longer models a grant withdrawn mid-session, so nothing "
        "measures what the adapter does when one is"
    )
    checks = _source(CHECKS)
    assert "checkContactsAuthorizationFailsClosedAndRevocationIsNotAStalePage" in checks, (
        "the runtime revocation check is gone from the Swift harness"
    )
    assert ".revokeAuthorizationAfterTheFirstCheck" in checks, (
        "the Swift harness no longer drives the revocation fault, so this module's "
        "structural claim has no runtime measurement behind it"
    )


# --- the bounds ---------------------------------------------------------------


def test_the_contacts_bounds_are_frozen_in_the_protocol_and_agree_with_python() -> None:
    """The bounds belong to the protocol, not to whichever adapter builds a page."""
    protocol = _source(PROTOCOL)
    for name, value in (
        ("maximumContactsIdentityComponentBytes", "64"),
        ("maximumContactGroupMemberships", "64"),
    ):
        assert f"public static let {name} = {value}" in protocol, (
            f"the frozen contacts bound {name} = {value} is no longer declared in the "
            "protocol. A bound an adapter owns is a bound the next adapter does not have"
        )

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

    adapter = _source(ADAPTER)
    assert "throw NativeSourceContractError.contactsTruncationUndeclared" in adapter, (
        "a page that stops short no longer has to declare it"
    )
    assert "throw NativeSourceContractError.contactsUnboundedEnumeration" in adapter, (
        "the adapter will now accept a mechanism that satisfied a container-scoped "
        "read by walking every container"
    )


def test_every_invariant_bearing_contacts_value_validates_on_the_decode_path() -> None:
    """WP-15's lesson, WP-16's correction and WP-17's, applied to WP-18.

    A bound enforced only on the memberwise initialiser holds for values built in
    Swift and not for the same values arriving as JSON, which is the shape the host
    would actually be handed. **A decoder that exists is not a decoder that
    validates**: a decoder rewritten to assign its stored properties directly
    compiles, keeps the literal string a naive guard looks for, and skips every
    `guard` in the throwing initialiser. So the routing is asserted too.

    This remains a *static* check, and the runtime one is the one that matters:
    `AppleSourceHostContractChecks::checkContactsValueBoundsHoldOffTheWire` decodes
    each malformed document and requires the failure.
    """
    mechanism = _source(MECHANISM)
    body = mechanism.split("public struct ContactObservation", 1)[1].split("\npublic ", 1)[0]
    assert "public init(from decoder: Decoder)" in body, (
        "ContactObservation carries invariants and decodes off the wire with no "
        "validating decoder of its own; the bounds would hold only for values built "
        "in Swift"
    )
    decoder = body.split("public init(from decoder: Decoder)", 1)[1].split("\n    }", 1)[0]
    assert "try self.init(" in decoder, (
        "ContactObservation's decoder no longer routes through its validating "
        "initialiser. A decoder that builds the value some other way is a decoder "
        "that skips every guard the initialiser holds"
    )
    assigned = sorted(set(re.findall(r"self\.([A-Za-z_][A-Za-z0-9_]*)\s*=[^=]", decoder)))
    assert assigned == [], (
        f"ContactObservation's decoder assigns {assigned} directly. Direct assignment "
        "is exactly how a decoder keeps its shape and loses its validation: the "
        "fields arrive off the wire unchecked"
    )

    # The component is `RawRepresentable`, so its decoder routes through the
    # failable initialiser rather than a throwing memberwise one — a different
    # shape with the same requirement.
    identity = _source(IDENTITY)
    component = identity.split("public struct ContactsIdentityComponent", 1)[1].split(
        "\npublic ", 1
    )[0]
    component_decoder = component.split("public init(from decoder: Decoder)", 1)[1].split(
        "\n    }", 1
    )[0]
    assert "Self(rawValue: rawValue)" in component_decoder, (
        "the contacts identity component's decoder no longer routes through its "
        "validating initialiser, so the alphabet and the byte ceiling hold in Swift "
        "and not off the wire"
    )
    assert "DecodingError" in component_decoder, (
        "the contacts identity component's decoder no longer refuses an inadmissible component"
    )


def test_no_entitlement_or_usage_declaration_was_added_for_the_contacts_mechanism() -> None:
    """The tripwire, restated for the keys a live contacts mechanism would need.

    A live mechanism needs `NSContactsUsageDescription` in an Info.plist and, under
    the App Sandbox, `com.apple.security.personal-information.addressbook`. None of
    that exists here and none of it may arrive without the signing work that owns
    it (EXT-03). WP-15 already fails the build if such a *file* appears; this reads
    the same tree for the *contents* that would make one meaningful, so a key
    smuggled into some other file type is caught too.
    """
    forbidden = (
        "NSContactsUsageDescription",
        "NSAddressBookUsageDescription",
        "com.apple.security.personal-information.addressbook",
        "com.apple.security.personal-information.contacts",
        "com.apple.security.contacts",
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
        f"{offenders} declare a usage description or an entitlement for contacts "
        "access. Both are EXT-03/EXT-04 and operator-gated; WP-18 proves the "
        "mechanism's shape without activating any of it"
    )


# --- control 6: observations, not truth --------------------------------------

#: The vocabulary of a judgement about a person. None of it belongs in a package
#: whose records are observations carrying provenance.
#:
#: Matched with word boundaries and case-insensitively, because `tier` is a
#: substring of `identifier` and a substring test would redden on the one field
#: this package cannot do without.
JUDGEMENT_VOCABULARY: Final = (
    "score",
    "scoring",
    "sentiment",
    "affinity",
    "closeness",
    "warmth",
    "strength",
    "rank",
    "ranking",
    "importance",
    "priority",
    "tier",
    "trait",
    "personality",
    "relationship",
    "engagement",
)


def test_the_contacts_adapter_judges_nobody_and_reaches_no_relationship_plane() -> None:
    """Brief §22, as a guard.

    A contact row is an **observation carrying provenance**, not an asserted fact
    about a person. So there is no scoring, no sentiment, no trait inference and no
    cross-Principal aggregation here, and there is no wiring to the relationship
    plane — which is explicitly a different package, whose capability seat activates
    a different set of notes the moment anything reaches it.

    Scanned over this package's own files rather than the tree: `score` is an
    ordinary word in a search ranker and an extraordinary one here.
    """
    assert len(JUDGEMENT_VOCABULARY) >= 16, (
        f"the judgement vocabulary names {len(JUDGEMENT_VOCABULARY)} words and the "
        "floor is 16; emptying it empties the assertion below"
    )
    for required in ("score", "sentiment", "trait", "relationship"):
        assert required in JUDGEMENT_VOCABULARY, (
            f"the judgement vocabulary no longer names {required}, which is one of "
            "the four the brief names outright"
        )

    offenders: dict[str, list[str]] = {}
    for path in (*CONTACTS_FILES, *_swift_files(CONTACTS_PROBE)):
        source = _source(path)
        named = sorted(
            word
            for word in JUDGEMENT_VOCABULARY
            if re.search(rf"\b{word}\w*\b", source, re.IGNORECASE)
        )
        if named:
            offenders[str(path.relative_to(ROOT))] = named
    assert offenders == {}, (
        f"{offenders} name the vocabulary of a judgement about a person. A contact "
        "row here is an observation carrying provenance, not an assertion: no "
        "scoring, no sentiment, no trait inference, no cross-Principal aggregation. "
        "Relationship Intelligence is a different package and wiring to it is not "
        "this one's to do"
    )

    # And identity ambiguity stays visible rather than being resolved away. The
    # `unknown` assurance is the field that carries it; a package that dropped it
    # would be asserting a stability the source never claimed.
    assert "case unknown" in _source(IDENTITY), (
        "the identity assurance vocabulary lost its `unknown` answer. Ambiguity has "
        "to be carried: rounding it up to a guarantee is precisely the observation "
        "presented as truth that §22 forbids"
    )
