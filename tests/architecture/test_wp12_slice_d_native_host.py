"""WP-12D's source-built synthetic host remains inside its authority boundary."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "native" / "apple-source-host"
SOURCES = HOST / "Sources" / "AppleSourceHost"


def _source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(SOURCES.glob("*.swift")))


def test_native_host_has_no_dependency_database_network_or_live_apple_surface() -> None:
    package = (HOST / "Package.swift").read_text(encoding="utf-8")
    source = _source()

    assert ".package(" not in package
    for fragment in (
        "import EventKit",
        "import Contacts",
        "import MailKit",
        "EKEventStore",
        "CNContactStore",
        "requestAccess",
        "NSXPC",
        "LaunchAgent",
        "URLSession",
        "NWListener",
        "postgres",
        "Postgres",
        "SQLite",
        "DATABASE_URL",
        "databaseURL",
        "connectionString",
    ):
        assert fragment not in source


def test_application_boundary_is_versioned_read_only_and_has_no_admission_result() -> None:
    source = _source()
    boundary = (SOURCES / "NativeHostEnvelopes.swift").read_text(encoding="utf-8")

    assert 'identifier = "my-pa.native-source.v1"' in source
    assert "public protocol NativeHostApplicationBoundary" in boundary
    assert "func discover(" in boundary
    assert "func preflight(" in boundary
    assert "func read(" in boundary
    for fragment in (
        "func create",
        "func update",
        "func delete",
        "func write",
        "func mutate",
        "func activate",
        "AdmissionReceipt",
        "AdmissionResult",
    ):
        assert fragment not in boundary


def test_spool_surface_is_bounded_atomic_owner_only_and_acknowledgement_gated() -> None:
    spool = (SOURCES / "ProtectedSpool.swift").read_text(encoding="utf-8")

    for required in (
        "maximumItems",
        "maximumBytes",
        "maximumPayloadBytes",
        "O_CREAT | O_EXCL | O_NOFOLLOW",
        "S_IRUSR | S_IWUSR",
        "Darwin.fsync",
        "Darwin.openat",
        "fstatat",
        "Darwin.unlinkat",
        "renameatx_np",
        "Darwin.lockf",
        "sharedProcessLocks",
        "referenceCount",
        "releaseSharedProcessLock",
        "AT_SYMLINK_NOFOLLOW",
        "RENAME_EXCL",
        "func acknowledge(",
        "func quarantine(",
        "func recoverResidues(",
        'case crashResidue = "crash_residue"',
    ):
        assert required in spool
    assert "removeItem" not in spool
    assert "Data(contentsOf:" not in spool
    assert "func purge" not in spool


def test_every_invariant_bearing_wire_value_has_explicit_validating_decode() -> None:
    protocol = (SOURCES / "NativeSourceProtocolV1.swift").read_text(encoding="utf-8")
    envelopes = (SOURCES / "NativeHostEnvelopes.swift").read_text(encoding="utf-8")
    recurrence = (SOURCES / "Recurrence.swift").read_text(encoding="utf-8")
    spool = (SOURCES / "ProtectedSpool.swift").read_text(encoding="utf-8")

    assert protocol.count("public init(from decoder: Decoder)") == 5
    assert envelopes.count("public init(from decoder: Decoder)") == 8
    assert recurrence.count("public init(from decoder: Decoder)") == 2
    assert spool.count("public init(from decoder: Decoder)") == 1


def test_public_identifiers_reject_locator_punctuation() -> None:
    protocol = (SOURCES / "NativeSourceProtocolV1.swift").read_text(encoding="utf-8")

    assert "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._:" in protocol
    assert (
        "@"
        not in protocol.split("public struct NativeSourceOpaqueID", 1)[1].split(
            "public struct NativeSourceAccount", 1
        )[0]
    )
    assert (
        "/"
        not in protocol.split("public struct NativeSourceOpaqueID", 1)[1].split(
            "public struct NativeSourceAccount", 1
        )[0]
    )
