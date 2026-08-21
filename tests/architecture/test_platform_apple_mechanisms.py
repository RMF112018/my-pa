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
        "enumerateEvents(matching:",
        "maximumEventsScanned",
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
    assert "read-only Calendar, Contacts, Tasks, and Mail" in readme
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


def test_platform_executable_preserves_application_issued_authority_identity() -> None:
    main = (HOST / "Sources" / "AppleSourceHostPlatformHost" / "main.swift").read_text(
        encoding="utf-8"
    )
    admission = _source("PlatformHostAdmission.swift")
    for required in (
        "maximumAggregateInputBytes",
        "O_NOFOLLOW",
        "fstat(descriptor",
        "PlatformAppleSourceComposition(",
        "ProtectedSpool(",
        "protectedNonLiveHandoff(",
        "authorizedSinglePassHandoff(",
        'arguments[2] == "--dry-run"',
        'arguments[2] == "--authorized-single-pass"',
        'case "--authorization-grant"',
        'arguments[1] == "spool"',
        "spool.acknowledge(envelopeID)",
    ):
        assert required in main
    assert "spool.enqueue" in admission
    assert 'handoffState: "production_composition_spooled"' in admission
    for required in (
        "PlatformAuthorizedReadGrant",
        "validateAuthorizedRead(",
        "grant.bridgeID",
        "grant.requestID",
        "grant.envelopeID",
        "selection.accountID == grant.accountID",
        "selection.bucketID == grant.bucketID",
        "composition.read(",
    ):
        assert required in admission
    for forbidden in (
        "authorizationState()",
        "consentState()",
        "discoverMail()",
    ):
        assert forbidden not in admission

    process_adapter = (
        ROOT / "src" / "my_pa" / "infrastructure" / "apple_source_host.py"
    ).read_text(encoding="utf-8")
    controller = (ROOT / "src" / "my_pa" / "application" / "native_sources.py").read_text(
        encoding="utf-8"
    )
    assert 'wire_grant = grant.model_dump(by_alias=True, mode="json")' in process_adapter
    assert "never synthesize authority identity here" in process_adapter
    assert 'f"{envelope_id}.pending"' in process_adapter
    assert "os.O_NOFOLLOW" in process_adapter
    assert "if pending.exists():" in process_adapter
    assert "return self._decode_pending" in process_adapter
    assert "def pending(" in process_adapter
    assert '"--quarantine"' in process_adapter
    assert "bridge_id=authority.bridge_id" in controller
    assert "envelopeID=authority.envelope_id" in controller
    assert "requestID=authority.request_id" in controller
    assert "self._host.acknowledge(authority.envelope_id)" in controller
    assert "self._host.quarantine(authority.envelope_id)" in controller


def test_current_docs_name_the_inert_handoff_and_deferred_goodnotes_model_route() -> None:
    readme = (HOST / "README.md").read_text(encoding="utf-8")
    source_index = (ROOT / "docs" / "00_REPOSITORY_SOURCE_INDEX.md").read_text(encoding="utf-8")
    context = (ROOT / "docs" / "architecture" / "system-context.md").read_text(encoding="utf-8")
    goodnotes = (ROOT / "docs" / "operations" / "goodnotes-local-source.md").read_text(
        encoding="utf-8"
    )
    assert "content-free protected receipt" in readme
    assert "closed ScriptingBridge Mail reads" in source_index
    assert "authenticated application-to-host single-page handoff" in context
    assert "GoodNotes invokes no model" in goodnotes
    assert "accepts no content or\nprovider" in goodnotes
    assert "has no executable router" in goodnotes
    assert "status: CURRENT_REPOSITORY_ARCHITECTURE" in context
    assert "authenticated_head_sha:" not in context
    assert "NEW_CANDIDATE_NOT_IN_REPOSITORY" not in context
    assert "current tree SHA, local worktree status" not in context

    campaign = (ROOT / "docs" / "campaign" / "CAMPAIGN-BRIEF.md").read_text(encoding="utf-8")
    assert "SUPERSEDED — NOT CURRENT CAMPAIGN AUTHORITY" in campaign
    assert "status: SUPERSEDED_HISTORICAL_SNAPSHOT" in campaign
    assert "PILOT-BLOCKER-REMEDIATION-20260812.md" in campaign
    assert "current candidate authority record" in source_index
    assert "not authority for present campaign state" in source_index

    runbook = (ROOT / "ops" / "runbooks" / "goodnotes-and-model-operations.md").read_text(
        encoding="utf-8"
    )
    assert "production-shaped, local GoodNotes" in runbook
    assert "ManifestGoodNotesSource" in runbook
    assert "BoundedLocalOCRTranscriber" in runbook
    assert "temporary synthetic files" in runbook
    assert "remains unconfigured and\ndisabled" in runbook
    assert "implements a synthetic-only GoodNotes" not in runbook

    cli_source = (ROOT / "apps" / "cli" / "sources.py").read_text(encoding="utf-8")
    module_boundaries = (ROOT / "docs" / "architecture" / "module-boundaries.md").read_text(
        encoding="utf-8"
    )
    assert "set is thirty" in cli_source and "twelve since WP-6" not in cli_source
    assert "fifty-four capabilities" in module_boundaries
