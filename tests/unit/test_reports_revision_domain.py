"""Reports Modernization WP03, contract B: patch, change kind, intent digests, lifecycle.

Pure domain, FAST tier: no database, no clock, no network. Every value is synthetic.
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, date, datetime
from typing import Final

import pytest

from my_pa.domain.reports.content import canonical_json, validate_content
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.errors import ReportLifecycleRefusal, ReportValidationError
from my_pa.domain.reports.lifecycle import decide_lifecycle_transition
from my_pa.domain.reports.manifest import build_initial_manifest, build_version_manifest
from my_pa.domain.reports.publication import PublicationRequest, RequestedAssociation
from my_pa.domain.reports.revision import (
    ClearableField,
    CoveragePeriod,
    LifecycleRequest,
    ReportPatch,
    UpdateRequest,
    apply_patch,
    snapshot_of_publication,
    validate_clear_fields,
)
from my_pa.domain.reports.vocabulary import (
    AssociationTargetKind,
    ChangeKind,
    LifecycleOperation,
    LifecycleState,
    ReceiptOutcome,
)

SECRET: Final = "synthetic-sensitive-value-91c2"  # noqa: S105 - a synthetic marker
RECORDED: Final = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
AUTHOR: Final = derive_creator(CreatorKind.LOCAL_PRINCIPAL, "prn_aaaa0001aaaa0001aaaa0001")
START: Final = datetime(2026, 11, 1, tzinfo=UTC)
END: Final = datetime(2026, 11, 3, tzinfo=UTC)

_ACTIVE = LifecycleState.ACTIVE
_ARCHIVED = LifecycleState.ARCHIVED
_TRASHED = LifecycleState.TRASHED


def _publication(**overrides: object) -> PublicationRequest:
    fields: dict[str, object] = {
        "title": "Synthetic report",
        "content": validate_content({"format": "markdown", "body": "# Body\n"}),
        "report_type": "synthetic_note",
        "topics": ("alpha",),
        "tags": ("t1",),
        "summary": "Synthetic summary.",
        "report_date": date(2026, 11, 4),
        "coverage_start": START,
        "coverage_end": END,
        "metadata": {"k": 1.0, "n": 3},
        "associations": (
            RequestedAssociation(AssociationTargetKind.EXTERNAL_SOURCE, "https://x.test", "cites"),
        ),
    }
    fields.update(overrides)
    return PublicationRequest(**fields)  # type: ignore[arg-type]


HEAD = snapshot_of_publication(_publication())


def _update(patch: ReportPatch, **overrides: object) -> UpdateRequest:
    fields: dict[str, object] = {
        "report_id": "grpt_aaaaaaaa",
        "expected_version": 1,
        "patch": patch,
        "change_reason": "Synthetic reason.",
    }
    fields.update(overrides)
    return UpdateRequest(**fields)  # type: ignore[arg-type]


# ---- apply_patch -------------------------------------------------------------------


def test_new_content_is_a_content_change() -> None:
    content = validate_content({"format": "markdown", "body": "# Other\n"})
    result, kind = apply_patch(HEAD, ReportPatch(content=content))
    assert kind is ChangeKind.CONTENT
    assert result.content is content
    assert result.title == HEAD.title


def test_equal_content_is_reused_and_a_metadata_change() -> None:
    same = validate_content({"format": "markdown", "body": "# Body\n"})
    assert same is not HEAD.content
    result, kind = apply_patch(HEAD, ReportPatch(content=same, title="Renamed"))
    assert kind is ChangeKind.METADATA
    assert result.content is HEAD.content  # the head's content object is kept
    assert result.title == "Renamed"


def test_the_same_bytes_in_another_format_is_new_content() -> None:
    text = validate_content({"format": "text", "body": "# Body\n"})
    assert text.decoded_sha256 == HEAD.content.decoded_sha256
    _result, kind = apply_patch(HEAD, ReportPatch(content=text))
    assert kind is ChangeKind.CONTENT


@pytest.mark.parametrize(
    "patch",
    [
        ReportPatch(title="Synthetic report"),
        ReportPatch(content=validate_content({"format": "markdown", "body": "# Body\n"})),
        ReportPatch(metadata={"n": 3, "k": 1.0}),
        ReportPatch(topics=("alpha",), tags=("t1",)),
        ReportPatch(coverage_period=CoveragePeriod(START, END)),
        ReportPatch(
            associations=(
                RequestedAssociation(
                    AssociationTargetKind.EXTERNAL_SOURCE, "https://x.test", "cites"
                ),
            )
        ),
    ],
)
def test_a_patch_equal_to_the_head_is_a_no_op(patch: ReportPatch) -> None:
    result, kind = apply_patch(HEAD, patch)
    assert kind is None
    assert result is HEAD


def test_a_number_type_change_is_a_change() -> None:
    # 1 and 1.0 are equal in Python and different digits in canonical JSON.
    _result, kind = apply_patch(HEAD, ReportPatch(metadata={"k": 1, "n": 3}))
    assert kind is ChangeKind.METADATA


def test_a_present_field_replaces_the_whole_value() -> None:
    result, kind = apply_patch(
        HEAD, ReportPatch(metadata={"only": True}, topics=(), tags=(), associations=())
    )
    assert kind is ChangeKind.METADATA
    assert dict(result.metadata) == {"only": True}
    assert (result.topics, result.tags, result.associations) == ((), (), ())
    cleared, _ = apply_patch(HEAD, ReportPatch(metadata={}))
    assert dict(cleared.metadata) == {}


def test_clear_fields_null_each_nullable_field() -> None:
    result, kind = apply_patch(HEAD, ReportPatch(), frozenset(ClearableField))
    assert kind is ChangeKind.METADATA
    assert result.report_type is None
    assert result.summary is None
    assert result.report_date is None
    assert (result.coverage_start, result.coverage_end) == (None, None)
    # Clearing what is already null changes nothing.
    again, kind_again = apply_patch(result, ReportPatch(), frozenset(ClearableField))
    assert kind_again is None
    assert again is result


def test_a_field_both_patched_and_cleared_is_refused() -> None:
    with pytest.raises(ReportValidationError) as caught:
        apply_patch(HEAD, ReportPatch(summary="x"), frozenset({ClearableField.SUMMARY}))
    assert (caught.value.field, caught.value.code) == ("clear_fields", "conflict")
    with pytest.raises(ReportValidationError) as caught:
        _update(ReportPatch(report_type="other"), clear_fields=frozenset({ClearableField.TYPE}))
    assert (caught.value.field, caught.value.code) == ("clear_fields", "conflict")


def test_an_empty_patch_without_clear_fields_is_refused() -> None:
    with pytest.raises(ReportValidationError) as caught:
        apply_patch(HEAD, ReportPatch())
    assert (caught.value.field, caught.value.code) == ("patch", "empty")
    with pytest.raises(ReportValidationError) as caught:
        _update(ReportPatch())
    assert (caught.value.field, caught.value.code) == ("patch", "empty")


def test_validate_clear_fields() -> None:
    assert validate_clear_fields(None) == frozenset()
    assert validate_clear_fields(["summary", "type"]) == {
        ClearableField.SUMMARY,
        ClearableField.TYPE,
    }
    for value, code in (
        (["summary", "summary"], "duplicate"),
        (["title"], "unknown"),
        ([1], "type"),
        ("summary", "type"),
    ):
        with pytest.raises(ReportValidationError) as caught:
            validate_clear_fields(value)
        assert (caught.value.field, caught.value.code) == ("clear_fields", code)


@pytest.mark.parametrize(
    ("fields", "field", "code"),
    [
        ({"title": ""}, "title", "too_short"),
        ({"report_type": "my_pa_x"}, "report_type", "reserved"),
        ({"topics": ("a", "A")}, "topics", "duplicate"),
        ({"metadata": {"_x": 1}}, "metadata", "reserved_key"),
        ({"report_date": datetime(2026, 1, 1, tzinfo=UTC)}, "report_date", "type"),
        ({"content": "not content"}, "content", "type"),
        ({"associations": ("x",)}, "associations", "type"),
        ({"coverage_period": (START, END)}, "coverage_period", "type"),
    ],
)
def test_patch_fields_are_validated_as_publish_validates_them(
    fields: dict[str, object], field: str, code: str
) -> None:
    with pytest.raises(ReportValidationError) as caught:
        ReportPatch(**fields)  # type: ignore[arg-type]
    assert (caught.value.field, caught.value.code) == (field, code)


def test_coverage_period_rules() -> None:
    assert CoveragePeriod(start=START).end is None
    with pytest.raises(ReportValidationError, match="coverage_period: empty"):
        CoveragePeriod()
    with pytest.raises(ReportValidationError, match="coverage_period: order"):
        CoveragePeriod(END, START)
    with pytest.raises(ReportValidationError, match="coverage_start: naive"):
        CoveragePeriod(datetime(2026, 11, 1))


def test_change_reason_is_required_and_bounded() -> None:
    with pytest.raises(ReportValidationError, match="change_reason: required"):
        _update(ReportPatch(title="x"), change_reason=None)
    with pytest.raises(ReportValidationError, match="change_reason: too_long"):
        _update(ReportPatch(title="x"), change_reason="r" * 501)
    with pytest.raises(ReportValidationError, match="expected_version: too_small"):
        _update(ReportPatch(title="x"), expected_version=0)
    with pytest.raises(ReportValidationError, match="expected_version: type"):
        _update(ReportPatch(title="x"), expected_version=True)


def test_change_reason_alone_never_makes_a_change() -> None:
    one = _update(ReportPatch(title="Synthetic report"), change_reason="one")
    two = _update(ReportPatch(title="Synthetic report"), change_reason="two")
    assert apply_patch(HEAD, one.patch, one.clear_fields)[1] is None
    assert apply_patch(HEAD, two.patch, two.clear_fields)[1] is None
    assert one.intent_digest != two.intent_digest


# ---- intent digests ----------------------------------------------------------------


def test_update_intent_digest_is_the_canonical_normalized_payload() -> None:
    request = _update(
        ReportPatch(title="New", topics=("b", "a")),
        clear_fields=frozenset({ClearableField.SUMMARY, ClearableField.TYPE}),
    )
    expected = hashlib.sha256(
        canonical_json(
            {
                "report_id": "grpt_aaaaaaaa",
                "expected_version": 1,
                "patch": {"title": "New", "topics": ["b", "a"]},
                "clear_fields": ["summary", "type"],
                "change_reason": "Synthetic reason.",
            }
        )
    ).hexdigest()
    assert request.intent_digest == expected
    # Every caller field moves the digest; equal requests share it.
    assert _update(ReportPatch(title="New", topics=("b", "a"))).intent_digest != expected
    assert (
        _update(
            ReportPatch(title="New", topics=("b", "a")),
            clear_fields=frozenset({ClearableField.TYPE, ClearableField.SUMMARY}),
        ).intent_digest
        == expected
    )
    for changed in (
        _update(ReportPatch(title="New"), expected_version=2),
        _update(ReportPatch(title="New"), report_id="grpt_bbbbbbbb"),
        _update(ReportPatch(title="New", metadata={})),
    ):
        assert changed.intent_digest != _update(ReportPatch(title="New")).intent_digest


def test_lifecycle_intent_digest_names_operation_report_revision_and_reason() -> None:
    request = LifecycleRequest(LifecycleOperation.ARCHIVE, "grpt_aaaaaaaa", 0, "why")
    assert (
        request.intent_digest
        == hashlib.sha256(
            canonical_json(
                {
                    "operation": "archive",
                    "report_id": "grpt_aaaaaaaa",
                    "expected_lifecycle_revision": 0,
                    "reason": "why",
                }
            )
        ).hexdigest()
    )
    others = {
        LifecycleRequest(LifecycleOperation.DELETE, "grpt_aaaaaaaa", 0, "why").intent_digest,
        LifecycleRequest(LifecycleOperation.ARCHIVE, "grpt_aaaaaaaa", 1, "why").intent_digest,
        LifecycleRequest(LifecycleOperation.ARCHIVE, "grpt_aaaaaaaa", 0).intent_digest,
    }
    assert request.intent_digest not in others
    assert len(others) == 3
    with pytest.raises(ReportValidationError, match="expected_lifecycle_revision: too_small"):
        LifecycleRequest(LifecycleOperation.ARCHIVE, "grpt_aaaaaaaa", -1)
    with pytest.raises(ReportValidationError, match="reason: too_short"):
        LifecycleRequest(LifecycleOperation.ARCHIVE, "grpt_aaaaaaaa", 0, "")
    with pytest.raises(ReportValidationError, match="lifecycle_operation: type"):
        LifecycleRequest("archive", "grpt_aaaaaaaa", 0)  # type: ignore[arg-type]


# ---- manifest ----------------------------------------------------------------------


def test_the_v1_manifest_has_a_null_change_reason() -> None:
    request = _publication()
    manifest = build_initial_manifest(
        request,
        report_id="grpt_aaaaaaaa",
        version_id="grver_aaaaaaaa",
        content_id="grcnt_aaaaaaaa",
        associations=(),
        recorded_at=RECORDED,
        author=AUTHOR,
    )
    assert "change_reason" in manifest.document
    assert manifest.document["change_reason"] is None


def test_a_later_manifest_names_its_predecessor_kind_and_reason() -> None:
    manifest = build_version_manifest(
        report_id="grpt_aaaaaaaa",
        version_id="grver_bbbbbbbb",
        version_number=2,
        supersedes_version_id="grver_aaaaaaaa",
        change_kind=ChangeKind.METADATA,
        change_reason="Synthetic reason.",
        title="t",
        report_type=None,
        topics=(),
        tags=(),
        summary=None,
        report_date=None,
        coverage_start=None,
        coverage_end=None,
        metadata={},
        content=HEAD.content,
        content_id="grcnt_aaaaaaaa",
        associations=(),
        recorded_at=RECORDED,
        author=AUTHOR,
    )
    document = manifest.document
    assert (document["version_number"], document["supersedes_version_id"]) == (
        2,
        "grver_aaaaaaaa",
    )
    assert (document["change_kind"], document["change_reason"]) == (
        "metadata",
        "Synthetic reason.",
    )
    assert manifest.sha256 == hashlib.sha256(canonical_json(document)).hexdigest()


# ---- lifecycle ---------------------------------------------------------------------


def test_restore_after_archive_then_delete_returns_to_archived() -> None:
    archived = decide_lifecycle_transition(_ACTIVE, LifecycleOperation.ARCHIVE)
    trashed = decide_lifecycle_transition(archived.resulting_state, LifecycleOperation.DELETE)
    assert (trashed.prior_state, trashed.resulting_state) == (_ARCHIVED, _TRASHED)
    restored = decide_lifecycle_transition(
        _TRASHED, LifecycleOperation.RESTORE, trashed_from=trashed.prior_state
    )
    assert restored.resulting_state is _ARCHIVED
    assert restored.outcome is ReceiptOutcome.APPLIED
    from_active = decide_lifecycle_transition(
        _TRASHED, LifecycleOperation.RESTORE, trashed_from=_ACTIVE
    )
    assert from_active.resulting_state is _ACTIVE
    assert (
        decide_lifecycle_transition(_ARCHIVED, LifecycleOperation.RESTORE).resulting_state
        is _ACTIVE
    )


def test_archive_on_archived_is_a_no_op_and_illegal_moves_refuse() -> None:
    no_op = decide_lifecycle_transition(_ARCHIVED, LifecycleOperation.ARCHIVE)
    assert no_op.outcome is ReceiptOutcome.NO_OP
    assert no_op.prior_state is no_op.resulting_state is _ARCHIVED
    for state, operation, trashed_from in (
        (_ACTIVE, LifecycleOperation.RESTORE, None),
        (_TRASHED, LifecycleOperation.DELETE, _ACTIVE),
        (_TRASHED, LifecycleOperation.ARCHIVE, _ARCHIVED),
    ):
        with pytest.raises(ReportLifecycleRefusal):
            decide_lifecycle_transition(state, operation, trashed_from=trashed_from)


# ---- repr --------------------------------------------------------------------------


def test_repr_never_shows_the_body_data_or_metadata() -> None:
    content = validate_content({"format": "mixed", "body": SECRET, "data": {"s": SECRET}})
    assert SECRET not in repr(content)
    assert content.decoded_sha256 in repr(content)
    patch = ReportPatch(content=content, metadata={"s": SECRET})
    assert SECRET not in repr(patch)
    assert SECRET not in repr(_update(patch))
    snapshot = snapshot_of_publication(_publication(content=content, metadata={"s": SECRET}))
    assert SECRET not in repr(snapshot)


def test_requests_are_frozen() -> None:
    request = _update(ReportPatch(title="x"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.expected_version = 2  # type: ignore[misc]


# ---- the FAST fake mirrors the port ------------------------------------------------


def test_the_in_memory_fake_mirrors_the_port_order_and_outcomes() -> None:
    from my_pa.contracts.ports import (
        ReportIdempotencyConflictError,
        ReportNotFoundError,
        ReportStaleLifecycleRevisionError,
        ReportStaleVersionError,
        ReportWithdrawnError,
    )
    from tests.conftest import World, _GeneralReports

    reports = _GeneralReports(World())
    owner, other = "prn_aaaa0001aaaa0001aaaa0001", "prn_bbbb0002bbbb0002bbbb0002"
    ids = {"correlation_id": "corr_aaaaaaaa", "audit_id": "audit_aaaaaaaa"}
    published = reports.publish(
        _publication(),
        principal_id=owner,
        creator=AUTHOR,
        idempotency_key="p",
        recorded_at=RECORDED,
        **ids,
    )
    report_id = published.receipt.report_id

    def update(patch: ReportPatch, key: str, expected: int = 1, who: str = owner) -> object:
        return reports.update(
            _update(patch, report_id=report_id, expected_version=expected),
            principal_id=who,
            creator=AUTHOR,
            idempotency_key=key,
            recorded_at=RECORDED,
            **ids,
        )

    def transition(operation: LifecycleOperation, expected: int, key: str) -> object:
        return reports.transition(
            LifecycleRequest(operation, report_id, expected),
            principal_id=owner,
            idempotency_key=key,
            recorded_at=RECORDED,
            **ids,
        )

    same = validate_content({"format": "markdown", "body": "# Body\n"})
    first = update(ReportPatch(title="Two", content=same), "u1")
    assert first.change_kind is ChangeKind.METADATA  # type: ignore[attr-defined]
    assert first.content_id == published.content_id  # type: ignore[attr-defined]
    assert update(ReportPatch(title="Two", content=same), "u1").replayed  # type: ignore[attr-defined]
    with pytest.raises(ReportIdempotencyConflictError):
        update(ReportPatch(title="Other"), "u1")
    with pytest.raises(ReportStaleVersionError):
        update(ReportPatch(title="Three"), "u2")
    with pytest.raises(ReportNotFoundError):
        update(ReportPatch(title="Three"), "u3", who=other)
    no_op = update(ReportPatch(title="Two"), "u4", expected=2)
    assert no_op.outcome is ReceiptOutcome.NO_OP  # type: ignore[attr-defined]
    old = reports.read_version(report_id, principal_id=owner, version_number=1)
    assert old is not None and old.version.title == "Synthetic report"
    assert old.root.head_version_number == 2

    assert transition(LifecycleOperation.ARCHIVE, 0, "a").outcome is ReceiptOutcome.APPLIED  # type: ignore[attr-defined]
    with pytest.raises(ReportWithdrawnError):
        update(ReportPatch(title="Three"), "u5", expected=2)
    with pytest.raises(ReportStaleLifecycleRevisionError):
        transition(LifecycleOperation.DELETE, 0, "d")
    transition(LifecycleOperation.DELETE, 1, "d")
    restored = transition(LifecycleOperation.RESTORE, 2, "r")
    assert restored.resulting_state is LifecycleState.ARCHIVED  # type: ignore[attr-defined]
    no_event = transition(LifecycleOperation.ARCHIVE, 3, "a2")
    assert no_event.outcome is ReceiptOutcome.NO_OP and no_event.event_id is None  # type: ignore[attr-defined]
    transition(LifecycleOperation.DELETE, 3, "d2")
    with pytest.raises(ReportLifecycleRefusal):
        transition(LifecycleOperation.DELETE, 4, "d3")

    versions = reports.version_history(report_id, principal_id=owner, page_size=1)
    assert versions is not None and versions.next_cursor == versions.items[0].version_id
    rest = reports.version_history(
        report_id, principal_id=owner, after_version_id=versions.next_cursor
    )
    assert rest is not None and [i.version_number for i in rest.items] == [2]
    events = reports.lifecycle_history(report_id, principal_id=owner)
    assert events is not None
    assert [e.operation for e in events.items] == [
        LifecycleOperation.ARCHIVE,
        LifecycleOperation.DELETE,
        LifecycleOperation.RESTORE,
        LifecycleOperation.DELETE,
    ]
    assert reports.version_history(report_id, principal_id=other) is None
    with pytest.raises(ReportValidationError, match="cursor"):
        reports.version_history(report_id, principal_id=owner, after_version_id="grver_x")
