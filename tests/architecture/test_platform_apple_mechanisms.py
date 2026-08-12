"""Pilot-remediation guards for the production-shaped Apple mechanism target."""

from __future__ import annotations

import re
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


def test_platform_composition_is_injected_inert_and_mail_is_operator_gated() -> None:
    source = _source("PlatformAppleSourceComposition.swift")
    assert "eventStore: EKEventStore" in source
    assert "contactStore: CNContactStore" in source
    assert "AppleMailAutomationMechanism" in source
    assert "mailGeneration: String" in source
    assert "availableOperatorGatedAutomation" in source
    assert "EKEventStoreChangedNotification" in source
    assert "CNContactStoreDidChangeNotification" in source
    assert "addObserver" not in source
    assert "import ScriptingBridge" not in source


def test_tasks_platform_mechanism_is_real_bounded_and_never_requests_access() -> None:
    source = _source("EventKitTasksMechanism.swift")
    for required in (
        "EventKitTasksMechanism: TasksMechanism",
        "authorizationStatus(for: .reminder)",
        "predicateForReminders",
        "fetchReminders",
        "cancelFetchRequest",
        "maximumMaterialized",
    ):
        assert required in source
    for forbidden in ("requestFullAccess", "requestAccess", "saveReminder", "removeReminder"):
        assert forbidden not in source


def test_mail_platform_mechanism_has_a_closed_read_shape_and_no_prompt_or_mutation() -> None:
    source = _source("AppleMailAutomationMechanism.swift")
    assert "AppleMailAutomationMechanism: MailMechanism" in source
    assert "AEDeterminePermissionToAutomateTarget" in source and "false" in source
    assert "dateReceived >= %@ AND dateReceived <= %@" in source
    assert "maximumMatchingMessages" in source
    for forbidden in (
        "saveMessage",
        "removeMessage",
        "deleteMessage",
        "moveMessage",
        "sendEvent(",
        "requestConsent",
    ):
        assert forbidden not in source


def test_current_swift_check_count_and_contacts_implementation_are_documented() -> None:
    main = (HOST / "Tests" / "AppleSourceHostContractChecks" / "main.swift").read_text(
        encoding="utf-8"
    )
    check_count = len(re.findall(r"^\s*try check[A-Za-z0-9_]+\(\)\s*$", main, re.MULTILINE))
    assert check_count == 37, "update the documented-number vocabulary for a new check count"
    assert f"PASS ({check_count} checks)" in main

    readme = (HOST / "README.md").read_text(encoding="utf-8")
    assert "Thirty-seven checks" in readme
    assert "production-shaped, read-only Calendar and Contacts mechanisms" in readme
    assert "ContactsStoreMechanism.swift" in {path.name for path in PLATFORM.iterdir()}

    record = (ROOT / "docs" / "campaign" / "WP-18-CONTACTS-ADAPTER-RECORD.md").read_text(
        encoding="utf-8"
    )
    correction = record.split("Branch:", 1)[0]
    assert "Current-head correction" in correction
    assert "minimum-key Contacts mechanism" in correction
    assert f"PASS ({check_count} checks)" in correction
    assert "PASS (36 checks)" in correction and "historical" in correction
    assert "* **No live mechanism.**" not in record
    assert "platformContactStore` is declared and never" not in record
    assert "ContactsStoreMechanism" in record
