"""Pilot-remediation guards for the production-shaped Apple mechanism target."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "native" / "apple-source-host"
PLATFORM = HOST / "Sources" / "AppleSourceHostPlatform"


def _source(name: str) -> str:
    return (PLATFORM / name).read_text(encoding="utf-8")


def test_platform_mechanisms_are_a_shipping_product_and_core_stays_separate() -> None:
    manifest = (HOST / "Package.swift").read_text(encoding="utf-8")
    assert '.library(name: "AppleSourceHostPlatform"' in manifest
    assert 'name: "AppleSourceHostPlatform"' in manifest
    assert 'dependencies: ["AppleSourceHost"]' in manifest
    assert '.target(name: "AppleSourceHost"),' in manifest


def test_calendar_platform_mechanism_uses_only_bounded_read_shapes() -> None:
    source = _source("EventKitCalendarMechanism.swift")
    for required in (
        "EventKitCalendarMechanism: CalendarMechanism",
        "authorizationStatus(for: .event)",
        "calendars(for: .event)",
        "predicateForEvents",
        "events(matching:",
        "occurrenceDate",
        "lastModifiedDate",
        "query.limit",
    ):
        assert required in source
    for forbidden in (
        "EKEventStore()",
        "EKEventStore.init",
        "requestFullAccess",
        "requestWriteOnly",
        ".save(",
        ".remove(",
        ".commit(",
    ):
        assert forbidden not in source


def test_contacts_platform_mechanism_uses_minimum_keys_and_no_save_surface() -> None:
    source = _source("ContactsStoreMechanism.swift")
    assert "ContactsStoreMechanism: ContactsMechanism" in source
    assert "CNContactIdentifierKey" in source and "CNContactTypeKey" in source
    assert "predicateForContactsInContainer" in source
    assert "predicateForContactsInGroup" in source
    assert "query.limit" in source
    for forbidden in (
        "CNContactStore()",
        "CNContactStore.init",
        "CNSaveRequest",
        "requestAccess",
        ".execute(",
        "CNContactGivenNameKey",
        "CNContactEmailAddressesKey",
        "CNContactPhoneNumbersKey",
    ):
        assert forbidden not in source


def test_platform_composition_is_injected_inert_and_mail_limitation_is_explicit() -> None:
    source = _source("PlatformAppleSourceComposition.swift")
    assert "eventStore: EKEventStore" in source
    assert "contactStore: CNContactStore" in source
    assert "unavailableNoPublicReadAPI" in source
    assert "EKEventStoreChangedNotification" in source
    assert "CNContactStoreDidChangeNotification" in source
    assert "addObserver" not in source
    assert "import ScriptingBridge" not in source
