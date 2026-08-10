"""WP-15's six controls, as guards rather than as claims.

The native Apple host is the one component of this system that will eventually
run next to a human being's real mail, calendar and contacts. What keeps that
safe is not that today's host is synthetic — it is that the host is *structurally*
incapable of the things it must never do, and that a change which made it capable
would fail the build rather than pass review unnoticed.

So each control here is written as the narrowest executable statement that would
break if the property broke:

1. **source-read-only** — no Apple personal-data framework, no mutating symbol,
   and no write-capable entitlement anywhere in the shipping target;
2. **no database credential** — no DSN, no driver, no environment read, no
   network or database client, and no package dependency at all;
3. **bounded spool** — the bounds exist and the over-bound path *throws*; the
   runtime proof of owner-only modes and atomic rename lives in the Swift
   contract checks, which this module deliberately does not duplicate;
4. **bridge/version** — the frozen identifier is the only version the host
   agrees to, and a lifecycle cannot reach handoff without agreeing;
5. **replay** — proved at the application and database boundary, not here;
6. **content-free telemetry** — the operational types have nowhere to put
   content, checked field by field rather than by grepping for known-bad words.

Comment text is stripped before scanning. A guard that a code comment can trip is
a guard someone eventually weakens to get their comment back.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"
HOST: Final = ROOT / "native" / "apple-source-host"
SHIPPING: Final = HOST / "Sources" / "AppleSourceHost"
PROBE: Final = HOST / "Compatibility" / "AppleFrameworkCompatibilityProbe"
MANIFEST: Final = HOST / "Package.swift"

#: The frameworks the compile-only probe is allowed — and required — to name.
PROBED_FRAMEWORKS: Final = ("EventKit", "Contacts", "MailKit", "ServiceManagement")


def _without_comments(source: str) -> str:
    """Drop whole-line comments, keeping string literals intact.

    Only whole-line comments are removed, so a DSN inside a string literal is
    still visible to the credential scan below — which is the one place a literal
    genuinely matters.
    """
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )


def _swift_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in root.rglob("*.swift") if ".build" not in path.parts))


def _native_tree() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in (ROOT / "native").rglob("*")
            if path.is_file() and ".build" not in path.parts
        )
    )


def _shipping_source() -> str:
    return _without_comments(
        "\n".join(path.read_text(encoding="utf-8") for path in _swift_files(SHIPPING))
    )


def _probe_source() -> str:
    return _without_comments(
        "\n".join(path.read_text(encoding="utf-8") for path in _swift_files(PROBE))
    )


def test_the_scan_is_reading_the_host_at_all() -> None:
    """Guards every assertion below against an empty read."""
    shipping = _swift_files(SHIPPING)
    assert len(shipping) >= 7, f"the shipping target scan found {len(shipping)} files"
    assert len(_swift_files(PROBE)) == 1
    assert "ProtectedSpool" in _shipping_source()
    assert len(_native_tree()) >= 10


# --- control 1: the host cannot write to an Apple source ---------------------

#: Every symbol by which a macOS process mutates Mail, Calendar or Contacts, plus
#: the frameworks that expose them. The shipping target may name none of these.
#:
#: This is a *structural* claim, not a review note: with no import of the
#: framework there is no type to call a mutating method on, so the absence of the
#: import is the stronger half and the symbol list is the belt to its braces.
MUTATING_APPLE_SURFACE: Final = (
    "import EventKit",
    "import EventKitUI",
    "import Contacts",
    "import ContactsUI",
    "import MailKit",
    "import AddressBook",
    "import Photos",
    "import Messages",
    "EKEventStore",
    "EKReminder",
    "CNContactStore",
    "CNSaveRequest",
    "CNMutableContact",
    "MEMessageActionHandler",
    "saveEvent",
    "removeEvent",
    "saveCalendar",
    "removeCalendar",
    "executeSave",
    "requestAccess",
    "requestFullAccess",
    "requestWriteOnly",
)


def test_the_shipping_host_holds_no_write_path_into_an_apple_source() -> None:
    source = _shipping_source()
    named = sorted(symbol for symbol in MUTATING_APPLE_SURFACE if symbol in source)
    assert named == [], (
        f"the shipping native host names {named}. WP-15's first control is that "
        "the host can read an Apple source and cannot mutate one; a mutating "
        "symbol or a personal-data framework import in the shipping target ends "
        "that property whether or not the call site is reached today"
    )


def test_the_read_only_boundary_declares_no_mutating_operation() -> None:
    """The protocol the application talks to offers reads and nothing else."""
    boundary = _without_comments(
        (SHIPPING / "NativeHostEnvelopes.swift").read_text(encoding="utf-8")
    )
    declared = re.findall(r"func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", boundary)
    protocol_body = boundary.split("public protocol NativeHostApplicationBoundary", 1)[1]
    operations = sorted(set(re.findall(r"func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", protocol_body)))
    assert operations == ["discover", "negotiate", "preflight", "read"], (
        f"the application boundary now offers {operations}; every operation on it "
        "must be a read or the version handshake"
    )
    assert declared, "the boundary scan parsed no function at all"


def test_no_write_capable_entitlement_or_usage_declaration_exists() -> None:
    """The tripwire for EXT-03, which is operator-gated and not this package's.

    There is no entitlement file here today. There is also no legitimate reason
    for one to appear without the signing work that owns it, so its appearance
    should stop the build and be looked at rather than ride along in a diff.
    """
    declarations = sorted(
        str(path.relative_to(ROOT))
        for path in _native_tree()
        if path.suffix in {".entitlements", ".plist", ".provisionprofile"}
        or path.name == "Info.plist"
    )
    assert declarations == [], (
        f"{declarations} declare entitlements, usage descriptions or a signing "
        "profile. Signing, notarization and TCC are EXT-03/EXT-04 and are "
        "operator-gated; WP-15 proves compatibility without activating any of them"
    )


# --- control 2: the host holds no database credential ------------------------

#: A connection string, a driver, or a way to read one out of the environment.
CREDENTIAL_SURFACE: Final = (
    "postgres://",
    "postgresql://",
    "postgresql+psycopg",
    "psycopg",
    "PostgresNIO",
    "PostgresClient",
    "libpq",
    "SQLite",
    "GRDB",
    "NSPersistentContainer",
    "CoreData",
    "DATABASE_URL",
    "MY_PA_",
    "databaseURL",
    "connectionString",
    "ProcessInfo.processInfo.environment",
    "getenv(",
    "URLSession",
    "NWConnection",
    "NWListener",
    "NSXPCConnection",
    "Security.framework",
    "SecItemCopyMatching",
)


def test_the_host_cannot_reach_a_database_or_read_a_credential() -> None:
    """Admission goes through the authenticated application, never around it.

    The host's only outward move is to write bytes into its own owner-only spool.
    It has no DSN, no driver, no environment read from which a DSN could arrive,
    and no socket. That is what makes "application-mediated admission" a property
    of the build rather than a convention.
    """
    offenders: dict[str, list[str]] = {}
    for path in _native_tree():
        try:
            text = _without_comments(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:  # pragma: no cover - no binary files today
            continue
        found = sorted(symbol for symbol in CREDENTIAL_SURFACE if symbol in text)
        if found:
            offenders[str(path.relative_to(ROOT))] = found
    assert offenders == {}, (
        f"{offenders} put a database credential, driver, environment read or "
        "network client inside the native host. The host must reach PostgreSQL "
        "through the authenticated application and by no other route"
    )


def test_the_host_package_declares_no_dependency_and_links_no_library() -> None:
    manifest = _without_comments(MANIFEST.read_text(encoding="utf-8"))
    for forbidden in (".package(", "linkedLibrary", "unsafeFlags", "linkerSettings"):
        assert forbidden not in manifest, (
            f"Package.swift now declares {forbidden}; the host's dependency "
            "surface is empty on purpose and a database client is exactly what a "
            "first dependency would smuggle in"
        )


# --- control 3: the spool refuses at its bound, and never drops ---------------


def test_the_spool_bounds_exist_and_refuse_rather_than_evict() -> None:
    """Behaviour *at* the limit, which is where silent data loss lives.

    The runtime proof — 0700 directories, 0600 items, write/fsync/rename, and an
    inventory unchanged by a refused enqueue — is in the Swift contract checks.
    What is checked here is that the over-bound paths still `throw`: an enqueue
    that returned a value at the bound could drop, and one that unlinks to make
    room does drop.
    """
    spool = _without_comments((SHIPPING / "ProtectedSpool.swift").read_text(encoding="utf-8"))
    for bound, error in (
        ("maximumItems", "itemCapacityExceeded"),
        ("maximumBytes", "byteCapacityExceeded"),
        ("maximumPayloadBytes", "payloadTooLarge"),
    ):
        assert bound in spool and f"throw ProtectedSpoolError.{error}" in spool, (
            f"the spool no longer refuses at {bound} by throwing {error}; a bound "
            "that is reached without an error is a bound that drops data"
        )
    # `acknowledge` is the only unlink, and it names one item the application has
    # already durably admitted. Nothing evicts, purges, or truncates.
    assert spool.count("unlinkat(") == 1, (
        f"the spool now unlinks in {spool.count('unlinkat(')} places; the single "
        "permitted removal is acknowledgement of an item the application admitted"
    )
    for eviction in ("func purge", "func evict", "func trim", "removeItem", "func drop"):
        assert eviction not in spool


# --- control 6: operational telemetry has nowhere to put content -------------

#: The only field types an emitted operational value may declare. `String` is
#: allowed for exactly one field name, below; every other textual value must be a
#: closed enumeration or an opaque identifier whose own validator rejects locator
#: punctuation.
TELEMETRY_FIELD_TYPES: Final = frozenset(
    {
        "Bool",
        "Int",
        "Int64",
        "NativeHostDistributionModel",
        "NativeHostErrorClass",
        "NativeHostErrorClass?",
        "NativeHostLifecycleState",
        "NativeHostSpoolHealth",
        "NativeHostTelemetryEventClass",
        "NativeSourceKind",
        "NativeSourceKind?",
        "NativeSourceOpaqueID",
    }
)

#: The single field permitted to be a bare `String`, and it is a frozen constant
#: that every initialiser and decoder checks against `NativeSourceProtocolV1`.
TELEMETRY_STRING_FIELD: Final = "protocolVersion"

TELEMETRY_TYPES: Final = (
    "NativeHostTelemetryEvent",
    "NativeHostSpoolHealth",
    "NativeHostHealthReport",
)


def _stored_properties(source: str, type_name: str) -> tuple[tuple[str, str], ...]:
    body = source.split(f"public struct {type_name}", 1)[1]
    body = body.split("\n    public init", 1)[0]
    return tuple(
        (name, annotation.strip())
        for name, annotation in re.findall(r"public let ([A-Za-z_][A-Za-z0-9_]*): ([^\n=]+)", body)
    )


def test_operational_telemetry_has_nowhere_to_put_personal_content() -> None:
    """The WP-15 redaction guard, stated as a type property.

    A redaction filter is a promise that every call site remembers to call it.
    This asserts something stronger and cheaper to keep: the values a health
    endpoint, metric or log line may carry declare no free-form text field, so
    there is no field into which a subject line, a message body, a contact value
    or a calendar note could be written in the first place.
    """
    source = _without_comments((SHIPPING / "HostTelemetry.swift").read_text(encoding="utf-8"))
    seen = 0
    for type_name in TELEMETRY_TYPES:
        properties = _stored_properties(source, type_name)
        assert properties, f"{type_name} parsed with no stored property"
        seen += len(properties)
        for name, annotation in properties:
            if annotation == "String":
                assert name == TELEMETRY_STRING_FIELD, (
                    f"{type_name}.{name} is a free-form String. Operational "
                    "telemetry carries counts, identifiers, types and error "
                    "classes only; a String field is where a message body ends up"
                )
                continue
            assert annotation in TELEMETRY_FIELD_TYPES, (
                f"{type_name}.{name} is declared `{annotation}`, which is not in "
                "the closed set of content-free telemetry field types. Adding a "
                "type here is a decision about what an operator's logs may "
                "contain, and it should be made deliberately"
            )
    assert seen >= 15, f"the telemetry scan read {seen} fields; it is not reading the file"


def test_no_telemetry_type_names_a_content_bearing_concept() -> None:
    """The second lock: field *names* drawn from source content, not just types.

    Weaker than the type check above and deliberately kept anyway — a future
    `payload: Int` would pass the type check while telling a reader that content
    belongs here.
    """
    source = _without_comments((SHIPPING / "HostTelemetry.swift").read_text(encoding="utf-8"))
    declarations = re.findall(r"let ([A-Za-z_][A-Za-z0-9_]*): ([^\n=]+)", source)
    declared = {name.lower() for name, _ in declarations}
    forbidden = {
        "payload",
        "body",
        "subject",
        "snippet",
        "text",
        "note",
        "notes",
        "title",
        "summary",
        "location",
        "attendees",
        "recipients",
        "emailaddress",
        "phonenumber",
        "displayname",
        "displaylabel",
        "path",
        "message",
        "description",
    }
    named = sorted(declared & forbidden)
    assert named == [], (
        f"telemetry declares {named}. Those names describe source content, and a "
        "field named for content will eventually hold some"
    )


def test_the_error_class_vocabulary_is_closed_and_discards_its_error() -> None:
    """An error class must not be able to become an error message."""
    source = _without_comments((SHIPPING / "HostTelemetry.swift").read_text(encoding="utf-8"))
    body = source.split("public enum NativeHostErrorClass", 1)[1].split("\n}", 1)[0]
    assert "String" in body.split("\n", 1)[0], "the error class is no longer a string enum"
    assert "localizedDescription" not in source
    assert "\\(error" not in source, (
        "telemetry now interpolates an error value; a class that renders its "
        "error is a message, and a message can carry anything the error saw"
    )


# --- the quarantine: unreachable, and measured to be ------------------------


def test_the_native_source_plane_is_reachable_from_no_transport() -> None:
    """Why the WP-04 quarantine is safe to leave standing, stated as a measurement.

    The twenty-two unpartitioned `native_*`/`source_*` tables carry no Principal
    column. WP-15 does not change that, and the reason it is not a release
    blocker is that no transport reaches the controller that writes them: the
    controller has zero production call sites and every transport refuses a
    `native_sources.*` capability name outright.

    If either half of that stops being true, the quarantine entry in
    `tests/architecture/test_user_owned_tables_are_partitioned.py` stops
    describing a vacuous residual and becomes a live isolation failure. This test
    is what turns that sentence into something that fails.
    """
    owning = {
        PACKAGE / "application" / "native_sources.py",
        PACKAGE / "infrastructure" / "persistence" / "native_sources.py",
    }
    reaching = sorted(
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if path not in owning and "NativeSourceController" in path.read_text(encoding="utf-8")
    )
    assert reaching == [], (
        f"{reaching} construct or reference NativeSourceController. The native "
        "plane is unpartitioned and quarantined; a production call site makes "
        "twenty-two unscoped tables reachable and is release-blocking under §18"
    )

    normalization = (PACKAGE / "adapters" / "normalization.py").read_text(encoding="utf-8")
    assert "NativeSourceCapability(capability)" in normalization
    assert "raise UnsupportedError() from None" in normalization, (
        "the transport no longer refuses native-source capability names; the "
        "quarantine's unreachability rests on that refusal"
    )


# --- OD-COMP-009: the compatibility probe is a compile check, not a host ------


def test_the_compatibility_probe_is_compile_only_and_never_linked_into_the_host() -> None:
    """What the probe proves, and the two things it must not become.

    It must not become a runtime path — nothing instantiates a store, requests a
    permission, or registers a service — and it must not become a dependency of
    the shipping target, which would put EventKit and Contacts inside the module
    that talks to the application.
    """
    manifest = _without_comments(MANIFEST.read_text(encoding="utf-8"))
    assert 'name: "AppleFrameworkCompatibilityProbe"' in manifest
    shipping_target = manifest.split('.target(name: "AppleSourceHost"', 1)[1].split(",", 1)[0]
    assert "AppleFrameworkCompatibilityProbe" not in shipping_target, (
        "the shipping target now depends on the compatibility probe, which links "
        "EventKit, Contacts and MailKit into the module that speaks to the "
        "application"
    )
    for target in ("AppleSourceHostContractChecks", "AppleSourceHostFixtureExport"):
        section = manifest.split(f'name: "{target}"', 1)[1].split("),", 1)[0]
        assert "AppleFrameworkCompatibilityProbe" not in section

    probe = _probe_source()
    for framework in PROBED_FRAMEWORKS:
        assert f"import {framework}" in probe, (
            f"the probe no longer imports {framework}; OD-COMP-009's compatibility "
            "claim is only worth what the compiler re-proves on every build"
        )
    for activation in (
        "EKEventStore(",
        "CNContactStore(",
        "CNSaveRequest(",
        "requestAccess",
        "requestFullAccess",
        ".register()",
        ".unregister()",
        "try await",
        "MEExtensionManager",
    ):
        assert activation not in probe, (
            f"the compatibility probe calls {activation}. It exists to answer a "
            "compile-and-link question; instantiating a store or registering a "
            "service is activation, and activation is operator-gated (EXT-03/04)"
        )
    # Metatypes only: every framework reference resolves at compile time.
    assert probe.count(".self") >= 15, "the probe stopped referencing metatypes"


def test_the_declared_platform_supports_the_target_distribution_model() -> None:
    """`SMAppService` is macOS 13+; a lower floor would make the probe vacuous."""
    manifest = _without_comments(MANIFEST.read_text(encoding="utf-8"))
    assert "platforms: [.macOS(.v13)]" in manifest, (
        "the package no longer declares its macOS floor. Without it the probe "
        "compiles against a deployment target on which ServiceManagement and "
        "MailKit are unavailable, and the compatibility proof inverts"
    )
