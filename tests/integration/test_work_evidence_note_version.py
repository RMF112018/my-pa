"""AT-003: exact Meeting note and Capture version evidence for Work records (S1, WP-02A).

S1 contract sections 3.1, 3.2, 5.1, 5.2 and 7.1 against PostgreSQL through
`ApplicationService.invoke`. An exact note or Capture version passage is
admitted as origin evidence; a wrong parent, a foreign Principal, a spoofed
source or passage digest, a passage outside the body or hashed after
normalization, an archived or restricted Capture are refused with nothing
written; a legacy Capture root only corroborates, is refused when any version
of it is restricted, never satisfies an origin rule, and reads
`legacy_unversioned`; anchor availability follows the Capture's archive state
at read time without writing a lineage row. The legacy Work
`origin_evidence_ref` rule is unchanged. Every body is synthetic.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterator
from typing import Any

import pytest

from my_pa.application.commands import (
    ArchiveCapture,
    CreateCommitment,
    ReadIssue,
    RestoreCapture,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.situation.continuity import CommitmentDirection
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL, LineageRuntime
from tests.database.lineage_record_harness import (
    GATEWAY,
    NOTE_BODY,
    all_lineage_counts,
    capture,
    capture_anchor,
    commitment,
    legacy_anchor,
    meeting,
    membership,
    note_anchor,
    originated_from,
    restricted_capture_version,
)
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[LineageRuntime]:
    composed = LineageRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _refused_cleanly(runtime: LineageRuntime, command: Any) -> dict[str, Any]:  # noqa: ANN401
    before = all_lineage_counts(runtime.engine)
    error = runtime.refused(command, surface=GATEWAY)
    assert all_lineage_counts(runtime.engine) == before
    return error


def _note_origin(
    runtime: LineageRuntime, key: str, anchor: dict[str, object], to_note: str, c1: str
) -> Any:  # noqa: ANN401
    return originated_from("commitment", c1, "meeting_note_version", to_note, key, (anchor,))


# --- Meeting note versions ---------------------------------------------------


def test_an_exact_note_passage_is_admitted_as_origin_evidence(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "note-ok")
    c1 = commitment(runtime, "note-ok")
    written = runtime.ok(
        _note_origin(runtime, "note-ok", note_anchor(m1, n1, NOTE_BODY), n1, c1), surface=GATEWAY
    )
    assert written["created"] is True and written["replayed"] is False
    (anchor,) = written["association"]["evidence"]
    assert anchor["family"] == "meeting_note_version" and anchor["root_id"] == m1


def test_a_note_version_under_another_meeting_is_not_found(runtime: LineageRuntime) -> None:
    _m1, n1 = meeting(runtime, "wrong-parent-1")
    m2, _n2 = meeting(runtime, "wrong-parent-2")
    c1 = commitment(runtime, "wrong-parent")
    error = _refused_cleanly(
        runtime, _note_origin(runtime, "wrong-parent", note_anchor(m2, n1, NOTE_BODY), n1, c1)
    )
    assert error["code"] == "not_found" and error["safe_details"] == ["evidence_anchors"]


def test_a_spoofed_source_digest_is_refused(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "spoof-source")
    c1 = commitment(runtime, "spoof-source")
    error = _refused_cleanly(
        runtime,
        _note_origin(
            runtime, "spoof-source", note_anchor(m1, n1, NOTE_BODY, source_sha256="0" * 64), n1, c1
        ),
    )
    assert error["code"] == "invalid_request" and error["safe_details"] == ["evidence_anchors"]


def test_a_spoofed_passage_digest_is_refused(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "spoof-passage")
    c1 = commitment(runtime, "spoof-passage")
    anchor = {**note_anchor(m1, n1, NOTE_BODY), "passage_sha256": "1" * 64}
    error = _refused_cleanly(runtime, _note_origin(runtime, "spoof-passage", anchor, n1, c1))
    assert error["code"] == "invalid_request" and error["safe_details"] == ["evidence_anchors"]


def test_a_passage_outside_the_body_is_refused(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "outside")
    c1 = commitment(runtime, "outside")
    beyond = len(NOTE_BODY) + 5
    anchor = {
        **note_anchor(m1, n1, NOTE_BODY),
        "passage_start_cp": len(NOTE_BODY) - 2,
        "passage_end_cp": beyond,
        "passage_sha256": hashlib.sha256(NOTE_BODY[-2:].encode("utf-8")).hexdigest(),
    }
    error = _refused_cleanly(runtime, _note_origin(runtime, "outside", anchor, n1, c1))
    assert error["code"] == "invalid_request" and error["safe_details"] == ["evidence_anchors"]


def test_a_hash_of_the_normalized_passage_is_refused(runtime: LineageRuntime) -> None:
    decomposed = unicodedata.normalize("NFD", "Review the café plan today.")
    m1, n1 = meeting(runtime, "normalized", body=decomposed)
    c1 = commitment(runtime, "normalized")
    exact = note_anchor(m1, n1, decomposed, passage=unicodedata.normalize("NFD", "café"))
    start, end = exact["passage_start_cp"], exact["passage_end_cp"]
    assert isinstance(start, int) and isinstance(end, int)
    normalized = unicodedata.normalize("NFC", decomposed[start:end])
    assert normalized != decomposed[start:end]
    spoofed = {**exact, "passage_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest()}
    error = _refused_cleanly(runtime, _note_origin(runtime, "normalized", spoofed, n1, c1))
    assert error["code"] == "invalid_request" and error["safe_details"] == ["evidence_anchors"]
    runtime.ok(_note_origin(runtime, "normalized-exact", exact, n1, c1), surface=GATEWAY)


def test_a_foreign_principal_note_is_not_found(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "foreign-note", principal_id=OTHER_PRINCIPAL)
    c1 = commitment(runtime, "foreign-note")
    error = _refused_cleanly(
        runtime, _note_origin(runtime, "foreign-note", note_anchor(m1, n1, NOTE_BODY), n1, c1)
    )
    assert error["code"] == "not_found"


def test_a_refused_evidence_write_leaves_no_row_or_request(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "no-row")
    c1 = commitment(runtime, "no-row")
    command = _note_origin(
        runtime, "no-row", note_anchor(m1, n1, NOTE_BODY, source_sha256="2" * 64), n1, c1
    )
    before = all_lineage_counts(runtime.engine)
    runtime.refused(command, surface=GATEWAY)
    after = all_lineage_counts(runtime.engine)
    assert after == before
    assert after["lineage_write_requests"] == before["lineage_write_requests"]
    # The same key with a correct anchor is a fresh request, not a replay.
    fixed = _note_origin(runtime, "no-row", note_anchor(m1, n1, NOTE_BODY), n1, c1)
    assert runtime.ok(fixed, surface=GATEWAY)["replayed"] is False


def test_legacy_work_origin_evidence_ref_is_unchanged(runtime: LineageRuntime) -> None:
    root, _version, _digest = capture(runtime, "legacy-work")
    _m1, n1 = meeting(runtime, "legacy-work")
    counterparty = seed_counterparty_entity(runtime.engine, PRINCIPAL)

    def create(ref: str, key: str) -> CreateCommitment:
        return CreateCommitment(
            counterparty_entity_id=counterparty,
            direction=CommitmentDirection.OWED_BY_PRINCIPAL,
            summary=f"Synthetic legacy commitment {key}",
            origin_evidence_ref=ref,
            idempotency_key=f"lineage-legacy-work-{key}",
        )

    accepted = runtime.ok(create(root, "cap"))
    assert accepted["commitment"]["origin_evidence_ref"] == root
    refused = runtime.refused(create(n1, "mnote"))
    assert refused["code"] == "invalid_request"
    assert refused["safe_details"] == ["invalid_evidence_reference"]


# --- Capture versions -----------------------------------------------------------


def test_an_exact_capture_version_passage_is_admitted_as_origin_evidence(
    runtime: LineageRuntime,
) -> None:
    root, version, _ = capture(runtime, "cap-ok")
    c1 = commitment(runtime, "cap-ok")
    written = runtime.ok(
        originated_from(
            "commitment",
            c1,
            "capture_version",
            version,
            "cap-ok",
            (capture_anchor(root, version, NOTE_BODY),),
        ),
        surface=GATEWAY,
    )
    (anchor,) = written["association"]["evidence"]
    assert anchor["family"] == "capture_version" and anchor["availability"] == "available"


def test_a_capture_version_under_another_capture_is_not_found(runtime: LineageRuntime) -> None:
    _root, version, _ = capture(runtime, "cap-parent-1")
    other, _other_version, _ = capture(runtime, "cap-parent-2", body=NOTE_BODY + " other")
    c1 = commitment(runtime, "cap-parent")
    error = _refused_cleanly(
        runtime,
        originated_from(
            "commitment",
            c1,
            "capture_version",
            version,
            "cap-parent",
            (capture_anchor(other, version, NOTE_BODY),),
        ),
    )
    assert error["code"] == "not_found"


def test_a_spoofed_capture_digest_is_refused(runtime: LineageRuntime) -> None:
    root, version, _ = capture(runtime, "cap-spoof")
    c1 = commitment(runtime, "cap-spoof")
    anchor = {**capture_anchor(root, version, NOTE_BODY), "source_sha256": "3" * 64}
    error = _refused_cleanly(
        runtime,
        originated_from("commitment", c1, "capture_version", version, "cap-spoof", (anchor,)),
    )
    assert error["code"] == "invalid_request" and error["safe_details"] == ["evidence_anchors"]


def _archive(runtime: LineageRuntime, root: str, key: str, revision: int = 0) -> None:
    runtime.ok(
        ArchiveCapture(
            capture_id=root,
            expected_lifecycle_revision=revision,
            idempotency_key=f"lineage-archive-{key}",
            reason="synthetic archive",
        )
    )


def _restore(runtime: LineageRuntime, root: str, key: str, revision: int = 1) -> None:
    runtime.ok(
        RestoreCapture(
            capture_id=root,
            expected_lifecycle_revision=revision,
            idempotency_key=f"lineage-restore-{key}",
            reason="synthetic restore",
        )
    )


def test_an_archived_capture_root_is_capture_withdrawn(runtime: LineageRuntime) -> None:
    root, version, _ = capture(runtime, "cap-archived")
    c1 = commitment(runtime, "cap-archived")
    issue = runtime.issue("cap-archived")
    _archive(runtime, root, "cap-archived")
    withdrawn = {"code": "denied", "safe_details": ["capture_withdrawn"]}
    # As an endpoint only (a membership of the Capture version, no evidence).
    endpoint = _refused_cleanly(runtime, membership(issue, "capture_version", version, "cap-ep"))
    assert {key: endpoint[key] for key in withdrawn} == withdrawn
    # As evidence only (a membership of a Commitment citing the version).
    anchored = _refused_cleanly(
        runtime,
        membership(
            issue,
            "commitment",
            c1,
            "cap-anchor",
            anchors=(capture_anchor(root, version, NOTE_BODY, role="corroborates"),),
        ),
    )
    assert {key: anchored[key] for key in withdrawn} == withdrawn
    # As both: an origin on the archived version.
    error = _refused_cleanly(
        runtime,
        originated_from(
            "commitment",
            c1,
            "capture_version",
            version,
            "cap-archived",
            (capture_anchor(root, version, NOTE_BODY),),
        ),
    )
    assert error["code"] == "denied" and error["safe_details"] == ["capture_withdrawn"]


def test_a_restricted_capture_version_is_refused(runtime: LineageRuntime) -> None:
    root, version, _ = capture(runtime, "cap-restricted")
    restricted = restricted_capture_version(runtime.engine, version)
    issue = runtime.issue("cap-restricted")
    error = _refused_cleanly(
        runtime,
        membership(
            issue,
            "commitment",
            commitment(runtime, "cap-restricted"),
            "cap-restricted",
            anchors=(capture_anchor(root, restricted, NOTE_BODY, role="corroborates"),),
        ),
    )
    assert error["code"] == "invalid_request" and error["safe_details"] == ["evidence_anchors"]
    endpoint = _refused_cleanly(
        runtime, membership(issue, "capture_version", restricted, "cap-restricted-member")
    )
    assert endpoint["code"] == "invalid_request" and endpoint["safe_details"] == ["endpoint"]


def test_a_legacy_capture_root_is_admitted_only_as_corroboration(runtime: LineageRuntime) -> None:
    root, _version, _ = capture(runtime, "legacy-role")
    issue = runtime.issue("legacy-role")
    c1 = commitment(runtime, "legacy-role")
    written = runtime.ok(
        membership(issue, "commitment", c1, "legacy-role", anchors=(legacy_anchor(root),)),
        surface=GATEWAY,
    )
    (anchor,) = written["membership"]["evidence"]
    assert anchor["family"] == "capture" and anchor["version_id"] is None
    assert anchor["source_version_no"] is None and anchor["passage_start_cp"] is None
    for role in ("origin", "discussion"):
        # Refused by the request parse itself: no transport can carry it further.
        with pytest.raises(InvalidRequestError) as refused:
            membership(
                issue,
                "commitment",
                c1,
                f"legacy-role-{role}",
                role="reference",
                anchors=(legacy_anchor(root, role=role),),
            )
        assert refused.value.safe_details == (SafeDetail.EVIDENCE_ANCHORS,)


def test_a_legacy_root_with_a_restricted_version_is_refused(runtime: LineageRuntime) -> None:
    root, version, _ = capture(runtime, "legacy-restricted")
    restricted_capture_version(runtime.engine, version)
    issue = runtime.issue("legacy-restricted")
    error = _refused_cleanly(
        runtime,
        membership(
            issue,
            "commitment",
            commitment(runtime, "legacy-restricted"),
            "legacy-restricted",
            anchors=(legacy_anchor(root),),
        ),
    )
    assert error["code"] == "invalid_request" and error["safe_details"] == ["evidence_anchors"]


def _availability_fixture(runtime: LineageRuntime, key: str) -> tuple[str, str, str]:
    root, version, _ = capture(runtime, key)
    issue = runtime.issue(key)
    c1 = commitment(runtime, key)
    runtime.ok(
        membership(
            issue,
            "commitment",
            c1,
            key,
            anchors=(
                capture_anchor(root, version, NOTE_BODY, role="corroborates"),
                legacy_anchor(root, role="contradicts"),
            ),
        ),
        surface=GATEWAY,
    )
    return issue, root, version


def _availabilities(runtime: LineageRuntime, issue: str) -> dict[str, str]:
    read = runtime.ok(ReadIssue(issue_id=issue, include_members=True))
    (member,) = read["memberships"]
    return {anchor["family"]: anchor["availability"] for anchor in member["evidence"]}


def test_an_anchor_reads_archived_after_its_capture_is_archived(runtime: LineageRuntime) -> None:
    issue, root, _ = _availability_fixture(runtime, "avail-archived")
    assert _availabilities(runtime, issue) == {
        "capture_version": "available",
        "capture": "legacy_unversioned",
    }
    _archive(runtime, root, "avail-archived")
    assert _availabilities(runtime, issue) == {"capture_version": "archived", "capture": "archived"}


def test_an_anchor_reads_available_again_after_restore(runtime: LineageRuntime) -> None:
    issue, root, _ = _availability_fixture(runtime, "avail-restored")
    _archive(runtime, root, "avail-restored")
    _restore(runtime, root, "avail-restored")
    assert _availabilities(runtime, issue) == {
        "capture_version": "available",
        "capture": "legacy_unversioned",
    }


def test_archive_and_restore_write_no_lineage_row(runtime: LineageRuntime) -> None:
    issue, root, _ = _availability_fixture(runtime, "avail-rows")
    before = all_lineage_counts(runtime.engine)
    digest = runtime.ok(ReadIssue(issue_id=issue, include_members=True))["memberships"][0][
        "evidence_set_digest"
    ]
    _archive(runtime, root, "avail-rows")
    _restore(runtime, root, "avail-rows")
    assert all_lineage_counts(runtime.engine) == before
    member = runtime.ok(ReadIssue(issue_id=issue, include_members=True))["memberships"][0]
    assert member["evidence_set_digest"] == digest and member["revision_no"] == 1


def test_a_legacy_capture_root_never_satisfies_an_origin_rule(runtime: LineageRuntime) -> None:
    root, version, _ = capture(runtime, "legacy-origin")
    c1 = commitment(runtime, "legacy-origin")
    error = _refused_cleanly(
        runtime,
        originated_from(
            "commitment", c1, "capture_version", version, "legacy-origin", (legacy_anchor(root),)
        ),
    )
    assert error["code"] == "invalid_request" and error["safe_details"] == ["evidence_anchors"]


def test_a_legacy_anchor_reads_as_legacy_unversioned(runtime: LineageRuntime) -> None:
    issue, _root, _ = _availability_fixture(runtime, "legacy-reads")
    assert _availabilities(runtime, issue)["capture"] == "legacy_unversioned"
