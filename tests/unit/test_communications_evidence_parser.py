"""`communications_evidence_v2` parser: publication validation, dialects, records, diagnostics.

Every input is synthetic (`tests/fixtures/communications_evidence/synthetic.py`).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from my_pa.domain.communications.corpus import summarize_corpus
from my_pa.domain.communications.diagnostics import (
    MAX_DIAGNOSTICS,
    DiagnosticCode,
    DiagnosticCollector,
    PublicationRejection,
    ReasonCode,
)
from my_pa.domain.communications.model import (
    BodyState,
    CanonicalKey,
    CoverageState,
    Dialect,
    FolderRole,
    IdentityState,
    IntegrityOutcome,
    NormalizedMessage,
    ProviderIdFormat,
    Publication,
    RecordClassification,
    RecordOutcome,
    SourceLane,
    TimestampField,
    WindowRule,
)
from my_pa.infrastructure.communications.evidence_v2 import (
    MAX_PUBLICATION_BYTES,
    PublicationParse,
    PublicationStatus,
    parse_publication,
)
from tests.fixtures.communications_evidence import synthetic as s

C = RecordClassification
R = ReasonCode
LEAN_END = "2026-11-18T04:59:59Z"


def parse(document: object) -> PublicationParse:
    return parse_publication(s.encode(document))


def accepted(document: object) -> Publication:
    result = parse(document)
    assert result.status is PublicationStatus.ACCEPTED, result.rejection
    assert result.publication is not None
    return result.publication


def lean_with(*messages: dict[str, Any]) -> dict[str, Any]:
    return s.publication(
        list(messages),
        s.window("2026-11-17T05:00:00Z", LEAN_END, 24, "weekday_prior_24h", backfill=True),
    )


def only(document: dict[str, Any]) -> RecordOutcome:
    (record,) = accepted(document).records
    return record


def msg(record: RecordOutcome) -> NormalizedMessage:
    assert record.message is not None
    return record.message


def rejected(document: object | bytes) -> PublicationRejection | None:
    data = document if isinstance(document, bytes) else s.encode(document)
    result = parse_publication(data)
    assert result.status is PublicationStatus.REJECTED
    assert result.publication is None
    return result.rejection


# --- publication-level validation -------------------------------------------------


def test_malformed_json_is_rejected_with_position_only() -> None:
    data = b'{"schema": "communications_evidence_v2", "subject": "CANARY-SUBJECT-xyz'
    result = parse_publication(data)
    assert result.rejection is PublicationRejection.MALFORMED_JSON
    (entry,) = result.diagnostics.entries
    assert dict(entry.detail).keys() == {"line", "column", "offset"}
    assert "CANARY" not in repr(result)


def test_the_committed_malformed_fixture_is_rejected() -> None:
    data = (s.HERE / "malformed.json").read_bytes()
    assert rejected(data) is PublicationRejection.MALFORMED_JSON


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"\xff\xfe{}", PublicationRejection.INVALID_ENCODING),
        (b"[1, 2]", PublicationRejection.NOT_AN_OBJECT),
        (b'{"schema": 1, "schema": 2}', PublicationRejection.DUPLICATE_JSON_KEY),
        (b'{"x": NaN}', PublicationRejection.MALFORMED_JSON),
        (b"[" * 100_000 + b"]" * 100_000, PublicationRejection.MALFORMED_JSON),
    ],
)
def test_undecodable_documents_are_rejected(data: bytes, code: PublicationRejection) -> None:
    assert rejected(data) is code


def test_an_oversized_publication_is_rejected_before_decoding() -> None:
    assert rejected(b" " * (MAX_PUBLICATION_BYTES + 1)) is PublicationRejection.FILE_TOO_LARGE


@pytest.mark.parametrize(
    ("schema", "code"),
    [
        ("communications_evidence_v3", PublicationRejection.UNKNOWN_SCHEMA),
        ("CANARY-SCHEMA", PublicationRejection.UNKNOWN_SCHEMA),
        (None, PublicationRejection.UNKNOWN_SCHEMA),
    ],
)
def test_an_unknown_schema_name_is_rejected(schema: object, code: PublicationRejection) -> None:
    document = s.lean_publication()
    document["schema"] = schema
    assert rejected(document) is code


@pytest.mark.parametrize(
    ("version", "code"),
    [
        ("1.9.0", PublicationRejection.UNSUPPORTED_MAJOR_VERSION),
        ("3.0.0", PublicationRejection.UNSUPPORTED_MAJOR_VERSION),
        ("2.0", PublicationRejection.INVALID_SCHEMA_VERSION),
        ("02.0.0", PublicationRejection.INVALID_SCHEMA_VERSION),
        ("2.0.0-beta", PublicationRejection.INVALID_SCHEMA_VERSION),
        (2, PublicationRejection.INVALID_SCHEMA_VERSION),
    ],
)
def test_only_major_version_2_is_accepted(version: object, code: PublicationRejection) -> None:
    document = s.lean_publication()
    document["schema_version"] = version
    assert rejected(document) is code


def test_a_newer_minor_version_is_accepted_and_reported() -> None:
    document = s.lean_publication()
    document["schema_version"] = "2.3.1"
    document["future_field"] = {"anything": True}
    result = parse(document)
    assert result.status is PublicationStatus.ACCEPTED
    assert result.publication is not None
    assert str(result.publication.schema_version) == "2.3.1"
    assert result.publication.unknown_top_level_keys == 1
    assert result.diagnostics.code_counts[DiagnosticCode.SCHEMA_MINOR_NEWER] == 1
    assert result.diagnostics.code_counts[DiagnosticCode.UNKNOWN_TOP_LEVEL_KEYS] == 1


@pytest.mark.parametrize(
    "key", ["schema_version", "business_date", "window", "coverage", "mailbox_ref", "messages"]
)
def test_a_missing_required_top_level_key_is_rejected(key: str) -> None:
    document = s.lean_publication()
    del document[key]
    assert rejected(document) is PublicationRejection.MISSING_REQUIRED_KEY


def test_optional_top_level_keys_may_be_absent() -> None:
    document = s.lean_publication()
    del document["id_header"]
    del document["cycle_run_id"]
    assert accepted(document).cycle_run_id_present is False


@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("business_date", "20261117", PublicationRejection.INVALID_TOP_LEVEL_FIELD),
        ("business_date", "2026-02-30", PublicationRejection.INVALID_TOP_LEVEL_FIELD),
        ("mailbox_ref", "  ", PublicationRejection.INVALID_TOP_LEVEL_FIELD),
        ("messages", {}, PublicationRejection.INVALID_TOP_LEVEL_FIELD),
        ("coverage", [], PublicationRejection.INVALID_TOP_LEVEL_FIELD),
        ("window", "24h", PublicationRejection.INVALID_WINDOW),
    ],
)
def test_bad_top_level_values_are_rejected(
    key: str, value: object, code: PublicationRejection
) -> None:
    document = s.lean_publication()
    document[key] = value
    assert rejected(document) is code


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-11-17T05:00:00", LEAN_END),  # naive
        ("2026-11-17 05:00:00Z", LEAN_END),  # not the T form
        ("2026-11-18T05:00:00Z", "2026-11-17T05:00:00Z"),  # end before start
        ("not a time", LEAN_END),
    ],
)
def test_an_unusable_window_rejects_the_publication(start: str, end: str) -> None:
    document = s.lean_publication()
    document["window"]["start_utc"] = start
    document["window"]["end_utc"] = end
    assert rejected(document) is PublicationRejection.INVALID_WINDOW


# Out-of-range instants: `fromisoformat` accepts them, converting to UTC overflows.
YEAR_9999_WEST = "9999-12-31T23:59:59-01:00"
YEAR_0001_EAST = "0001-01-01T00:00:00+01:00"


@pytest.mark.parametrize("value", [YEAR_0001_EAST, YEAR_9999_WEST, "0001-01-01T00:00:00Z"])
def test_an_out_of_range_window_bound_is_an_invalid_window(value: str) -> None:
    for key in ("start_utc", "end_utc"):
        document = s.lean_publication()
        document["window"][key] = value
        assert rejected(document) is PublicationRejection.INVALID_WINDOW


def test_an_out_of_range_selected_time_quarantines_only_that_record() -> None:
    document = s.lean_publication()
    document["messages"][1]["timestamps"]["selected_utc"] = YEAR_9999_WEST
    records = accepted(document).records
    assert records[1].classification is C.QUARANTINED
    assert R.UNPARSEABLE_TIMESTAMP in records[1].reasons
    baseline = accepted(s.lean_publication()).records
    assert baseline[1].classification is C.ACCEPTED
    others = [r.classification for i, r in enumerate(records) if i != 1]
    assert others == [r.classification for i, r in enumerate(baseline) if i != 1]


@pytest.mark.parametrize("key", ["received_raw", "sent_raw", "selected_raw"])
def test_an_out_of_range_raw_time_only_degrades(key: str) -> None:
    record = s.message(1)
    record["timestamps"][key] = YEAR_9999_WEST
    outcome = only(lean_with(record))
    assert outcome.classification is not C.QUARANTINED
    assert R.RAW_TIMESTAMP_UNPARSEABLE in outcome.reasons


@pytest.mark.parametrize(
    "hours",
    [
        pytest.param(1e306, id="1e306"),
        pytest.param(-1, id="negative"),
        pytest.param(10_001, id="above-bound"),
        pytest.param(10**400, id="int-beyond-float"),
    ],
)
def test_an_unusable_declared_hours_is_a_window_field_diagnostic(hours: float) -> None:
    document = s.lean_publication()
    document["window"]["hours"] = hours
    result = parse(document)
    assert result.status is PublicationStatus.ACCEPTED
    assert result.publication is not None
    assert result.publication.window.declared_hours is None
    assert result.diagnostics.code_counts[DiagnosticCode.WINDOW_FIELD_INVALID] == 1
    assert DiagnosticCode.WINDOW_HOURS_MISMATCH not in result.diagnostics.code_counts


def test_a_json_literal_that_overflows_to_infinity_is_a_window_field_diagnostic() -> None:
    # `1e400` is a finite-looking literal that `json` parses to `inf`; `json.dumps`
    # would write `Infinity` (rejected outright), so the literal is spliced in.
    data = s.encode(s.lean_publication())
    assert data.count(b'"hours": 24,') == 1
    result = parse_publication(data.replace(b'"hours": 24,', b'"hours": 1e400,'))
    assert result.status is PublicationStatus.ACCEPTED
    assert result.publication is not None
    assert result.publication.window.declared_hours is None
    assert result.diagnostics.code_counts[DiagnosticCode.WINDOW_FIELD_INVALID] == 1


def test_a_window_bound_at_the_edge_of_the_range_survives_a_zone_conversion() -> None:
    # Accepted bounds keep a day clear of the `datetime` range, so the DST check's
    # conversion into a named zone cannot overflow.
    document = s.lean_publication()
    document["window"]["start_utc"] = "0001-01-02T00:00:00Z"
    document["window"]["tz"] = "America/New_York"
    result = parse(document)
    assert result.status is PublicationStatus.ACCEPTED


# --- dialects ---------------------------------------------------------------------


def test_the_lean_fixture_is_the_lean_dialect() -> None:
    publication = accepted(s.lean_publication())
    assert publication.dialect is Dialect.LEAN
    assert publication.unknown_record_keys == 0


def test_the_rich_fixture_is_the_rich_dialect() -> None:
    publication = accepted(s.rich_publication())
    assert publication.dialect is Dialect.RICH
    assert publication.unknown_record_keys == 0


def test_partial_rich_markers_are_rich_and_reported() -> None:
    document = s.lean_publication()
    document["threads"] = []
    result = parse(document)
    assert result.publication is not None
    assert result.publication.dialect is Dialect.RICH
    assert result.diagnostics.code_counts[DiagnosticCode.DIALECT_MARKERS_INCOMPLETE] == 1


def test_unknown_record_keys_are_tolerated_and_counted() -> None:
    record = s.message(1)
    record["CANARY-KEY-one"] = 1
    record["another_future_key"] = None
    outcome = only(lean_with(record))
    assert outcome.classification is C.ACCEPTED
    publication = accepted(lean_with(record))
    assert publication.unknown_record_keys == 2


# --- normalized representation ----------------------------------------------------


def test_a_lean_record_normalizes_to_neutral_types() -> None:
    record = only(lean_with(s.message(1, sender="Alpha@Example.Invalid ")))
    message = msg(record)
    assert record.classification is C.ACCEPTED
    assert message.provider_id_format is ProviderIdFormat.MUTABLE
    assert message.folder_role is FolderRole.INBOX
    assert message.identity_state is IdentityState.PROVIDER_RETURNED
    assert message.canonical_key == CanonicalKey(
        s.MAILBOX, IdentityState.PROVIDER_RETURNED, "<synthetic-0001@example.invalid>"
    )
    assert message.sender_address == "alpha@example.invalid"
    assert message.participants["to"].addresses == ("bravo@example.invalid",)
    assert message.participants["bcc"].state.value == "not_exposed"
    assert message.timestamps.selected_field is TimestampField.RECEIVED
    assert message.timestamps.selected_utc == datetime(2026, 11, 17, 12, tzinfo=UTC)
    assert message.body.state is BodyState.PRESENT
    assert message.body.integrity is IntegrityOutcome.VERIFIED


def test_participant_address_falls_back_to_the_raw_provider_shape() -> None:
    record = s.message(1)
    entry = record["from"]["value"]
    del entry["address_normalized"]
    del entry["address"]
    entry["raw"]["emailAddress"]["address"] = "RAW@example.invalid"
    assert msg(only(lean_with(record))).sender_address == "raw@example.invalid"


def test_a_missing_internet_message_id_falls_back_to_provider_id_only() -> None:
    record = only(lean_with(s.message(1, imid=None)))
    assert record.classification is C.ACCEPTED_DEGRADED
    assert R.IDENTITY_PROVIDER_ID_ONLY in record.reasons
    message = msg(record)
    assert message.canonical_key == CanonicalKey(
        s.MAILBOX, IdentityState.PROVIDER_ID_ONLY, "SYNTHETIC-PROVIDER-ID-0001"
    )


def test_the_dedup_key_is_never_the_identity() -> None:
    first, second = s.message(1), s.message(2)
    second["dedup_key"] = first["dedup_key"]
    records = accepted(lean_with(first, second)).records
    assert [r.classification for r in records] == [C.ACCEPTED, C.ACCEPTED]
    assert len({msg(r).canonical_key for r in records}) == 2


def test_an_inconsistent_identity_state_is_degraded() -> None:
    record = s.message(1, imid=None)
    record["internet_message_id_state"] = "provider_returned"
    outcome = only(lean_with(record))
    assert R.IDENTITY_STATE_INCONSISTENT in outcome.reasons


def test_an_absent_conversation_id_is_degraded() -> None:
    record = s.message(1)
    record["conversation_id"] = None
    outcome = only(lean_with(record))
    assert outcome.classification is C.ACCEPTED_DEGRADED
    assert msg(outcome).conversation_state.value == "absent"


def test_a_sent_item_selects_its_sent_time() -> None:
    record = s.message(1, folder="sent", selected_field="sentDateTime")
    message = msg(only(lean_with(record)))
    assert message.folder_role is FolderRole.SENT
    assert message.timestamps.selected_field is TimestampField.SENT


def test_a_selected_time_inconsistent_with_its_raw_field_is_degraded() -> None:
    record = s.message(1)
    record["timestamps"]["received_raw"] = "2026-11-17T12:00:01Z"
    outcome = only(lean_with(record))
    assert outcome.classification is C.ACCEPTED_DEGRADED
    assert R.SELECTED_TIMESTAMP_INCONSISTENT in outcome.reasons


def test_an_offset_timestamp_is_converted_to_utc() -> None:
    record = s.message(1)
    for key in ("received_raw", "selected_raw", "selected_utc"):
        record["timestamps"][key] = "2026-11-17T07:00:00-05:00"
    outcome = only(lean_with(record))
    assert outcome.classification is C.ACCEPTED
    assert msg(outcome).timestamps.selected_utc == datetime(2026, 11, 17, 12, tzinfo=UTC)


def test_an_unparseable_raw_timestamp_only_degrades() -> None:
    record = s.message(1)
    record["timestamps"]["sent_raw"] = "yesterday"
    outcome = only(lean_with(record))
    assert R.RAW_TIMESTAMP_UNPARSEABLE in outcome.reasons


def test_unknown_vocabulary_degrades_rather_than_passing_through() -> None:
    record = s.message(1)
    record["id_format"] = "CANARY-FORMAT"
    record["source_folder"]["role"] = "archive"
    record["cc"]["state"] = "CANARY-STATE"
    outcome = only(lean_with(record))
    assert outcome.classification is C.ACCEPTED_DEGRADED
    assert {R.UNKNOWN_ID_FORMAT, R.UNKNOWN_FOLDER_ROLE, R.UNKNOWN_PARTICIPANT_STATE} <= set(
        outcome.reasons
    )
    assert msg(outcome).folder_role is FolderRole.OTHER


# --- body state and integrity -----------------------------------------------------


def test_a_withheld_body_is_not_verifiable_and_not_a_failure() -> None:
    record = only(
        s.publication(
            [s.richen(s.message(1, selected="2026-11-14T01:00:00Z"), withheld=True)],
            s.window("2026-11-13T07:00:00Z", "2026-11-16T07:00:00Z", 72, "explicit_utc_bounds"),
            rich=True,
        )
    )
    assert record.classification is C.ACCEPTED
    message = msg(record)
    assert message.body.state is BodyState.WITHHELD
    assert message.body.content is None
    assert message.body.integrity is IntegrityOutcome.NOT_VERIFIABLE_WITHHELD
    assert message.body.utf8_bytes > 0  # describes the original
    assert message.derived_text is not None
    assert message.derived_text.text is None


def test_content_present_despite_a_privacy_screen_is_discarded() -> None:
    record = s.richen(s.message(1))
    record["privacy"]["policy_withheld"] = True
    outcome = only(lean_with(record))
    assert R.PRIVACY_WITHHELD_CONTENT_PRESENT in outcome.reasons
    message = msg(outcome)
    assert message.body.state is BodyState.WITHHELD
    assert message.body.content is None


def test_content_missing_without_a_withheld_marker_is_quarantined() -> None:
    record = s.message(1)
    record["body"]["content"] = None
    outcome = only(lean_with(record))
    assert outcome.classification is C.QUARANTINED
    assert R.BODY_CONTENT_MISSING in outcome.reasons


@pytest.mark.parametrize("mutation", ["sha", "bytes"])
def test_a_body_integrity_mismatch_is_quarantined(mutation: str) -> None:
    record = s.message(1)
    if mutation == "sha":
        record["body"]["sha256"] = s.sha("other")
    else:
        record["body"]["utf8_bytes"] += 1
    outcome = only(lean_with(record))
    assert outcome.classification is C.QUARANTINED
    assert outcome.reasons == (R.INTEGRITY_MISMATCH,)


def test_integrity_is_over_the_stored_bytes_without_normalization() -> None:
    record = s.message(1, content="<p>café</p>\r\n")
    assert only(lean_with(record)).classification is C.ACCEPTED
    record["body"]["sha256"] = s.sha("<p>café</p>\n")
    assert only(lean_with(record)).classification is C.QUARANTINED


def test_a_unique_body_integrity_mismatch_is_quarantined() -> None:
    record = s.richen(s.message(1))
    record["unique_body"]["sha256"] = s.sha("tampered")
    outcome = only(lean_with(record))
    assert outcome.classification is C.QUARANTINED
    assert R.INTEGRITY_MISMATCH in outcome.reasons


def test_a_derived_text_digest_mismatch_is_quarantined() -> None:
    record = s.message(1)
    record["body_derived_plain_text"] = {"derived": True, "sha256": s.sha("x"), "text": "y"}
    assert only(lean_with(record)).classification is C.QUARANTINED


def test_null_derived_text_and_null_derived_block_are_accepted() -> None:
    a, b = s.message(1), s.message(2)
    a["body_derived_plain_text"] = None
    b["body_derived_plain_text"] = {"derived": False, "derivation": None, "text": None}
    records = accepted(lean_with(a, b)).records
    assert [r.classification for r in records] == [C.ACCEPTED, C.ACCEPTED]
    assert msg(records[0]).derived_text is None
    derived = msg(records[1]).derived_text
    assert derived is not None
    assert derived.usable is False


def test_a_truncated_body_is_degraded_and_marked_truncated() -> None:
    record = s.message(1)
    record["body"] = s.body("<p>Partial", completeness="truncated_unknown")
    outcome = only(lean_with(record))
    assert outcome.classification is C.ACCEPTED_DEGRADED
    assert outcome.reasons == (R.BODY_TRUNCATED,)
    assert msg(outcome).body.state is BodyState.TRUNCATED


def test_an_empty_body_is_its_own_state() -> None:
    assert msg(only(lean_with(s.message(1, content="")))).body.state is BodyState.EMPTY


# --- quarantine of malformed records ----------------------------------------------


def _drop(path: tuple[str, ...]) -> Callable[[dict[str, Any]], None]:
    def mutate(record: dict[str, Any]) -> None:
        target = record
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return mutate


def _set(path: tuple[str, ...], value: object) -> Callable[[dict[str, Any]], None]:
    def mutate(record: dict[str, Any]) -> None:
        target = record
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (_drop(("id",)), R.MISSING_REQUIRED_FIELD),
        (_drop(("mailbox_ref",)), R.MISSING_REQUIRED_FIELD),
        (_drop(("source_folder",)), R.MISSING_REQUIRED_FIELD),
        (_drop(("source_folder", "role")), R.MISSING_REQUIRED_FIELD),
        (_drop(("timestamps",)), R.MISSING_REQUIRED_FIELD),
        (_drop(("timestamps", "selected_utc")), R.MISSING_REQUIRED_FIELD),
        (_drop(("timestamps", "selected_field")), R.MISSING_REQUIRED_FIELD),
        (_drop(("body",)), R.MISSING_REQUIRED_FIELD),
        (_drop(("body", "sha256")), R.MISSING_REQUIRED_FIELD),
        (_set(("id",), 17), R.INVALID_FIELD_VALUE),
        (_set(("subject",), ["CANARY-SUBJECT-xyz"]), R.INVALID_FIELD_TYPE),
        (_set(("from",), "CANARY@example.invalid"), R.INVALID_FIELD_TYPE),
        (_set(("internet_message_id",), 5), R.INVALID_FIELD_TYPE),
        (_set(("body", "utf8_bytes"), True), R.INVALID_FIELD_TYPE),
        (_set(("body", "utf8_bytes"), -1), R.INVALID_FIELD_TYPE),
        (_set(("body", "content"), 12), R.INVALID_FIELD_TYPE),
        (_set(("body", "content_type"), "rtf"), R.INVALID_FIELD_VALUE),
        (_set(("body", "sha256"), "abc"), R.INVALID_FIELD_VALUE),
        (_set(("timestamps", "selected_utc"), "2026-11-17T12:00:00"), R.UNPARSEABLE_TIMESTAMP),
        (_set(("timestamps", "selected_field"), "lastModified"), R.INVALID_FIELD_VALUE),
        (_set(("mailbox_ref",), "other_mailbox"), R.MAILBOX_REF_MISMATCH),
        (_set(("message_id",), "SYNTHETIC-OTHER"), R.PROVIDER_ID_FIELDS_DISAGREE),
    ],
)
def test_a_malformed_record_is_quarantined_alone(
    mutate: Callable[[dict[str, Any]], None], reason: ReasonCode
) -> None:
    bad = s.message(1)
    mutate(bad)
    records = accepted(lean_with(s.message(0), bad, s.message(2))).records
    assert [r.classification for r in records] == [C.ACCEPTED, C.QUARANTINED, C.ACCEPTED]
    assert reason in records[1].reasons


def test_a_non_object_record_is_quarantined() -> None:
    records = accepted(lean_with(s.message(0), "CANARY-SUBJECT-xyz", 7)).records
    assert [r.classification for r in records] == [C.ACCEPTED, C.QUARANTINED, C.QUARANTINED]
    assert records[1].reasons == (R.RECORD_NOT_AN_OBJECT,)


def test_a_missing_from_degrades() -> None:
    record = s.message(1)
    del record["from"]
    outcome = only(lean_with(record))
    assert outcome.classification is C.ACCEPTED_DEGRADED
    assert R.PARTICIPANT_FROM_ABSENT in outcome.reasons


def test_a_reported_fetch_error_degrades() -> None:
    record = s.richen(s.message(1))
    record["fetch_error"] = {"code": "CANARY-ERROR"}
    assert R.FETCH_ERROR_REPORTED in only(lean_with(record)).reasons


# --- identity rules and duplicates ------------------------------------------------


def test_inbox_and_sent_copies_are_two_observations_of_one_identity() -> None:
    records = accepted(s.lean_publication()).records
    pair = [msg(records[1]), msg(records[2])]
    assert [records[1].classification, records[2].classification] == [C.ACCEPTED, C.ACCEPTED]
    assert {m.folder_role for m in pair} == {FolderRole.INBOX, FolderRole.SENT}
    assert pair[0].canonical_key == pair[1].canonical_key
    assert pair[0].provider_id != pair[1].provider_id
    assert pair[0].timestamps.selected_utc != pair[1].timestamps.selected_utc


def test_a_within_file_repeat_is_a_duplicate_observation() -> None:
    result = parse(s.lean_publication())
    assert result.publication is not None
    records = result.publication.records
    assert records[0].classification is C.ACCEPTED
    assert records[3].classification is C.DUPLICATE_OBSERVATION
    assert result.diagnostics.code_counts[DiagnosticCode.DUPLICATE_PROVIDER_ID] == 1


def test_same_internet_message_id_with_a_different_sender_is_an_identity_conflict() -> None:
    records = accepted(s.rich_publication()).records
    assert records[4].classification is C.QUARANTINED
    assert records[5].classification is C.QUARANTINED
    assert R.IDENTITY_CONFLICT in records[4].reasons
    assert R.IDENTITY_CONFLICT in records[5].reasons


def test_same_internet_message_id_with_a_different_body_is_an_identity_conflict() -> None:
    a = s.message(1, imid="<shared@example.invalid>")
    b = s.message(2, imid="<shared@example.invalid>", content="<p>Different.</p>")
    records = accepted(lean_with(a, b)).records
    assert all(R.IDENTITY_CONFLICT in r.reasons for r in records)


def test_one_provider_id_with_different_content_is_a_provider_id_conflict() -> None:
    a = s.message(1)
    b = s.message(1, content="<p>Changed.</p>")
    records = accepted(lean_with(a, b)).records
    assert [r.classification for r in records] == [C.QUARANTINED, C.QUARANTINED]
    assert all(R.PROVIDER_ID_CONFLICT in r.reasons for r in records)


def _sent_sibling_without_imid(record: dict[str, Any]) -> dict[str, Any]:
    sibling = copy.deepcopy(record)
    sibling["source_folder"]["role"] = "sent"
    sibling["source_folder"]["key"] = "sent"
    sibling["internet_message_id"] = None
    sibling["internet_message_id_state"] = "absent"
    return sibling


def test_a_lane_missing_the_internet_message_id_is_degraded_not_conflicted() -> None:
    # R1's probe 6(a): same provider id, inbox lane with the id, sent lane without it.
    document = s.lean_publication()
    first = copy.deepcopy(document["messages"][0])
    document["messages"] = [first, _sent_sibling_without_imid(first)]
    inbox, sent = accepted(document).records
    assert sent.classification is C.ACCEPTED_DEGRADED  # the sent lane is primary
    assert inbox.classification is C.LANE_OBSERVATION_MERGED
    for record in (inbox, sent):
        assert R.LANE_IDENTITY_INCONSISTENT in record.reasons
        assert R.PROVIDER_ID_CONFLICT not in record.reasons
    assert R.IDENTITY_PROVIDER_ID_ONLY in sent.reasons


def test_a_lane_missing_the_id_still_meets_the_identity_rules_through_its_sibling() -> None:
    # The id the inbox lane supplied puts the item under the identity rules: a
    # second provider id with that id and another sender conflicts with it.
    document = s.lean_publication()
    first = copy.deepcopy(document["messages"][0])
    other = copy.deepcopy(first)
    other["id"] = other["message_id"] = "SYNTH-OTHER"
    other["from"]["value"]["address_normalized"] = "zzz@example.invalid"
    other["from"]["value"]["address"] = "zzz@example.invalid"
    document["messages"] = [first, _sent_sibling_without_imid(first), other]
    records = accepted(document).records
    assert [r.classification for r in records] == [C.QUARANTINED] * 3
    assert all(R.IDENTITY_CONFLICT in r.reasons for r in records)


def test_two_different_internet_message_ids_on_one_provider_id_still_conflict() -> None:
    a = s.message(1, imid="<one@example.invalid>")
    b = s.message(1, imid="<two@example.invalid>")
    records = accepted(lean_with(a, b)).records
    assert all(R.PROVIDER_ID_CONFLICT in r.reasons for r in records)


def test_a_repeat_of_an_identity_conflicted_record_is_quarantined_too() -> None:
    # R1's probe 6(b): the repeat used to stay `duplicate_observation` and count as usable.
    document = s.lean_publication()
    a = copy.deepcopy(document["messages"][0])
    b, c = copy.deepcopy(a), copy.deepcopy(a)
    b["id"] = b["message_id"] = "SYNTH-OTHER"
    b["from"]["value"]["address_normalized"] = "zzz@example.invalid"
    b["from"]["value"]["address"] = "zzz@example.invalid"
    document["messages"] = [a, b, c]
    publication = accepted(document)
    assert [r.classification for r in publication.records] == [C.QUARANTINED] * 3
    assert all(R.IDENTITY_CONFLICT in r.reasons for r in publication.records)
    assert publication.items == ()
    assert summarize_corpus([publication]).usable_observations == 0


# --- window -----------------------------------------------------------------------


def test_the_window_end_is_inclusive() -> None:
    records = accepted(s.lean_publication()).records
    assert msg(records[4]).timestamps.selected_utc == datetime(2026, 11, 18, 4, 59, 59, tzinfo=UTC)
    assert records[4].classification is C.ACCEPTED
    assert records[5].classification is C.OUT_OF_WINDOW


def test_the_window_start_is_inclusive_and_before_it_is_out() -> None:
    at_start = s.message(1, selected="2026-11-17T05:00:00Z")
    before = s.message(2, selected="2026-11-17T04:59:59Z")
    records = accepted(lean_with(at_start, before)).records
    assert [r.classification for r in records] == [C.ACCEPTED, C.OUT_OF_WINDOW]


def test_a_friday_window_labelled_24_hours_reports_its_real_duration() -> None:
    result = parse(s.friday_publication())
    publication = result.publication
    assert publication is not None
    window = publication.window
    assert window.rule is WindowRule.FRIDAY_PRIOR_24H
    assert window.declared_hours == 24
    assert window.actual_hours == 33.2
    assert result.diagnostics.code_counts[DiagnosticCode.WINDOW_HOURS_MISMATCH] == 1
    assert [r.classification for r in publication.records] == [C.ACCEPTED, C.ACCEPTED]


def test_an_inclusive_backfill_day_is_not_an_hours_mismatch() -> None:
    result = parse(s.lean_publication())
    assert result.publication is not None
    assert result.publication.window.actual_seconds == 86_399
    assert DiagnosticCode.WINDOW_HOURS_MISMATCH not in result.diagnostics.code_counts


def test_a_rich_in_window_flag_that_disagrees_is_degraded() -> None:
    records = accepted(s.rich_publication()).records
    assert records[3].classification is C.ACCEPTED_DEGRADED
    assert records[3].reasons == (R.IN_WINDOW_DISAGREEMENT,)


def test_a_rich_in_window_flag_on_an_out_of_window_record_agrees() -> None:
    record = s.richen(s.message(1, selected="2026-11-18T05:00:00Z"), in_window=False)
    outcome = only(lean_with(record))
    assert outcome.classification is C.OUT_OF_WINDOW
    assert outcome.reasons == ()


def test_dst_change_is_computed_and_a_wrong_declaration_is_reported() -> None:
    document = lean_with(s.message(1, selected="2026-11-01T12:00:00Z"))
    document["window"].update(
        {"start_utc": "2026-10-31T04:00:00Z", "end_utc": "2026-11-02T05:00:00Z", "hours": 49}
    )
    result = parse(document)
    assert result.publication is not None
    assert result.publication.window.dst_change_computed is True
    assert result.publication.window.dst_change_declared is False
    assert result.diagnostics.code_counts[DiagnosticCode.DST_FLAG_DISAGREEMENT] == 1


def test_an_unknown_rule_and_an_unresolvable_zone_are_tolerated() -> None:
    document = s.lean_publication()
    document["window"]["rule"] = "CANARY-RULE"
    document["window"]["tz"] = "Canary/Nowhere"
    result = parse(document)
    assert result.publication is not None
    assert result.publication.window.rule is WindowRule.UNRECOGNIZED
    assert result.diagnostics.code_counts[DiagnosticCode.WINDOW_RULE_UNRECOGNIZED] == 1
    assert result.publication.window.dst_change_computed is None
    assert result.diagnostics.code_counts[DiagnosticCode.TZ_UNRESOLVABLE] == 1


# --- coverage ---------------------------------------------------------------------


def test_coverage_sources_are_parsed() -> None:
    publication = accepted(s.lean_publication())
    assert publication.coverage_overall is CoverageState.COMPLETE
    inbox, sent, project = publication.sources
    assert (inbox.role, inbox.lane, inbox.state, inbox.raw_messages) == (
        FolderRole.INBOX,
        SourceLane.MAIL,
        CoverageState.COMPLETE,
        12,
    )
    assert sent.raw_messages == 1
    assert (project.lane, project.authorized, project.state) == (
        SourceLane.PROJECT_SYSTEM,
        False,
        CoverageState.NOT_AUTHORIZED,
    )


def test_a_coverage_count_that_disagrees_with_the_records_is_reported() -> None:
    document = s.lean_publication()
    document["coverage"]["sources"][0]["raw_messages"] = 99
    result = parse(document)
    assert result.diagnostics.code_counts[DiagnosticCode.COVERAGE_COUNT_MISMATCH] == 1


def test_partial_and_malformed_coverage_is_tolerated() -> None:
    document = s.lean_publication()
    document["coverage"]["overall"] = "partial"
    document["coverage"]["sources"].append("CANARY-SOURCE")
    result = parse(document)
    assert result.publication is not None
    assert result.publication.coverage_overall is CoverageState.PARTIAL
    assert result.diagnostics.code_counts[DiagnosticCode.COVERAGE_SOURCE_INVALID] == 1


# --- bounded, content-free diagnostics --------------------------------------------

CANARIES = (
    "CANARY-SUBJECT-xyz",
    "canary@example.invalid",
    "CANARY-PROVIDER-ID",
    "CANARY-IMID",
    "CANARY-CONVERSATION",
    "CANARY-BODY",
    "CANARY-KEY",
    "Canary Display Name",
)


def canary_publication() -> dict[str, Any]:
    good = s.message(
        1,
        provider_id="CANARY-PROVIDER-ID-1",
        imid="<CANARY-IMID-1@example.invalid>",
        sender="canary@example.invalid",
        subject="CANARY-SUBJECT-xyz",
        content="<p>CANARY-BODY</p>",
    )
    good["conversation_id"] = "CANARY-CONVERSATION"
    good["from"]["value"]["display_name"] = "Canary Display Name"
    good["CANARY-KEY"] = "CANARY-BODY"
    bad = copy.deepcopy(good)
    bad["id"] = "CANARY-PROVIDER-ID-2"
    bad["message_id"] = "CANARY-PROVIDER-ID-2"
    bad["body"]["sha256"] = s.sha("CANARY-BODY mismatch")
    bad["timestamps"]["selected_utc"] = "CANARY-SUBJECT-xyz"
    conflict = copy.deepcopy(good)
    conflict["id"] = "CANARY-PROVIDER-ID-3"
    conflict["message_id"] = "CANARY-PROVIDER-ID-3"
    conflict["from"]["value"]["address_normalized"] = "canary-other@example.invalid"
    document = lean_with(good, bad, conflict, "CANARY-SUBJECT-xyz")
    document["CANARY-KEY"] = "CANARY-BODY"
    document["window"]["rule"] = "CANARY-SUBJECT-xyz"
    document["coverage"]["sources"][0]["key"] = "CANARY-KEY"
    return document


def test_diagnostics_never_carry_input_text() -> None:
    result = parse(canary_publication())
    assert result.status is PublicationStatus.ACCEPTED
    assert len(result.diagnostics.entries) >= 5
    rendered = repr(result.diagnostics)
    for canary in CANARIES:
        assert canary.lower() not in rendered.lower(), canary


def test_diagnostic_detail_refuses_free_text() -> None:
    collector = DiagnosticCollector()
    with pytest.raises(TypeError):
        collector.add(DiagnosticCode.OUT_OF_WINDOW, "$", value="CANARY-SUBJECT-xyz")  # type: ignore[arg-type]


def test_diagnostics_are_capped_with_an_overflow_count() -> None:
    records = [s.message(n, imid=None) for n in range(MAX_DIAGNOSTICS + 50)]
    result = parse(lean_with(*records))
    assert len(result.diagnostics.entries) == MAX_DIAGNOSTICS
    assert result.diagnostics.overflow == 50
    assert result.diagnostics.code_counts[R.IDENTITY_PROVIDER_ID_ONLY] == MAX_DIAGNOSTICS + 50
    assert result.publication is not None
    assert len(result.publication.records) == MAX_DIAGNOSTICS + 50


def test_a_float_byte_count_is_not_an_integer_count() -> None:
    record = s.message(1)
    record["body"]["utf8_bytes"] = float(record["body"]["utf8_bytes"])
    outcome = only(lean_with(record))
    assert outcome.classification is C.QUARANTINED
    assert R.INVALID_FIELD_TYPE in outcome.reasons
