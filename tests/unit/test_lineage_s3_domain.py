"""The record lineage S3 pure domain (S3 contract sections 3.4, 4.2, 5 and 10).

FAST: no database, no clock beyond the instants each test states. Worker L1's
part of the crosswalk row: the knowledge cut rules (`domain.lineage.asof`), the
completeness precedence, and the backfill source document against the shared
golden vectors (`tests/fixtures/lineage_backfill_source_vectors.json`, which
`tests/database/test_lineage_backfill_digest_parity.py` holds the SQL functions
to). Worker L2's part (sections 3.1 to 3.3): the link transition table, the
`related_context` canonical order, the one "in the Issue's context" predicate
and the handoff chain that skips voided events. Every value is synthetic.
"""

from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.domain.lineage.asof import (
    COMPLETENESS_PRECEDENCE,
    CutAfterNowError,
    completeness,
    effective_known_at,
    is_known,
    knowledge_cut,
    native_cut,
)
from my_pa.domain.lineage.backfill import (
    PLAN_DOMAIN,
    SOURCE_DOMAIN,
    origin_reference,
    plan_digest,
    reference_token,
    source_digest,
    source_document,
)
from my_pa.domain.lineage.canonical import normalized_identity, related_context_order
from my_pa.domain.lineage.closure import (
    LINK_TRANSITIONS,
    in_issue_context,
    is_contest_evidence,
    link_transition,
)
from my_pa.domain.lineage.cursor import (
    CursorMalformedError,
    LineageCursor,
    cursor_binding,
    decode_cursor,
    encode_cursor,
    grant_digest,
    instant_token,
    parse_instant_token,
    scope_digest,
)
from my_pa.domain.lineage.handoff import (
    HandoffCorrectionFact,
    can_void,
    chain_state,
    last_live,
    retime_in_order,
)
from my_pa.domain.lineage.model import EvidenceAnchor, InvalidLineageValueError, RecordRef
from my_pa.domain.lineage.vocabulary import (
    LINEAGE_READ_GENERATION,
    LIVE_LINK_STATES,
    EvidenceRole,
    EvidenceSourceFamily,
    HandoffCorrectionAction,
    LineageCompleteness,
    LinkLifecycleState,
    LinkRevisionAction,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SourceVersionKind,
)
from my_pa.domain.lineage_backfill.vocabulary import BackfillSourceKind

VECTORS: Final = (
    Path(__file__).resolve().parents[1] / "fixtures" / ("lineage_backfill_source_vectors.json")
)
NOW: Final = datetime(2026, 10, 19, 12, tzinfo=UTC)
HORIZON: Final = NOW - timedelta(hours=1)


def _vectors() -> dict[str, Any]:
    loaded = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _inputs(vector: dict[str, Any]) -> dict[str, Any]:
    stated = vector["input"]
    return {**stated, "source_kind": BackfillSourceKind(stated["source_kind"])}


# ---- section 3.4: the knowledge cut -------------------------------------------------


def test_known_and_valid_cut_rules() -> None:
    # T_k = min(requested known_at, or now; H): capped at the committed horizon.
    assert effective_known_at(None, now=NOW, horizon=HORIZON) == HORIZON
    earlier = HORIZON - timedelta(minutes=5)
    assert effective_known_at(earlier, now=NOW, horizon=HORIZON) == earlier
    assert effective_known_at(HORIZON + timedelta(minutes=5), now=NOW, horizon=HORIZON) == HORIZON
    # A Principal with no allocator row has no lineage fact.
    assert effective_known_at(None, now=NOW, horizon=None) is None
    # After now is refused, naming the field, before any horizon is consulted.
    with pytest.raises(CutAfterNowError) as late:
        effective_known_at(NOW + timedelta(seconds=1), now=NOW, horizon=None)
    assert late.value.field == "known_at"
    with pytest.raises(CutAfterNowError) as late_valid:
        knowledge_cut(known_at=None, valid_at=NOW + timedelta(seconds=1), now=NOW, horizon=HORIZON)
    assert late_valid.value.field == "valid_at"
    with pytest.raises(CutAfterNowError) as both:
        knowledge_cut(
            known_at=NOW + timedelta(seconds=1),
            valid_at=NOW + timedelta(seconds=1),
            now=NOW,
            horizon=HORIZON,
        )
    assert both.value.field == "known_at"

    # T_v = min(valid_at, T_k), defaulting to T_k; valid_at reported as requested.
    default = knowledge_cut(known_at=None, valid_at=None, now=NOW, horizon=HORIZON)
    assert (default.known_at, default.valid_at, default.lineage_valid_at) == (
        HORIZON,
        HORIZON,
        HORIZON,
    )
    past = HORIZON - timedelta(days=1)
    bounded = knowledge_cut(known_at=None, valid_at=past, now=NOW, horizon=HORIZON)
    assert (bounded.known_at, bounded.valid_at, bounded.lineage_valid_at) == (HORIZON, past, past)
    # A valid_at after the horizon is reported, but the lineage plane is clamped.
    after_horizon = HORIZON + timedelta(minutes=30)
    clamped = knowledge_cut(known_at=None, valid_at=after_horizon, now=NOW, horizon=HORIZON)
    assert clamped.valid_at == after_horizon
    assert clamped.lineage_valid_at == HORIZON
    empty = knowledge_cut(known_at=None, valid_at=past, now=NOW, horizon=None)
    assert (empty.known_at, empty.valid_at, empty.lineage_valid_at) == (None, past, None)

    # N = min(valid_at?, known_at?, read time): never the lineage horizon.
    assert native_cut(known_at=None, valid_at=None, read_time=NOW) == NOW
    assert native_cut(known_at=past, valid_at=None, read_time=NOW) == past
    assert native_cut(known_at=earlier, valid_at=past, read_time=NOW) == past

    # Knowledge of one fact: by its mark against W(T), or by recorded_at pre-S3.
    assert is_known(commit_seq=3, recorded_at=NOW, watermark=3, cut=HORIZON)
    assert not is_known(commit_seq=4, recorded_at=past, watermark=3, cut=HORIZON)
    assert not is_known(commit_seq=1, recorded_at=past, watermark=None, cut=HORIZON)
    assert is_known(commit_seq=None, recorded_at=past, watermark=None, cut=HORIZON)
    assert not is_known(commit_seq=None, recorded_at=NOW, watermark=9, cut=HORIZON)
    assert not is_known(commit_seq=1, recorded_at=past, watermark=1, cut=None)


def test_completeness_precedence() -> None:
    assert COMPLETENESS_PRECEDENCE == (
        LineageCompleteness.SCOPE_CHANGED_RESTART_REQUIRED,
        LineageCompleteness.UNRESOLVED_AMBIGUITY,
        LineageCompleteness.TRUNCATED_BUDGET,
        LineageCompleteness.RESTRICTED_EVIDENCE,
        LineageCompleteness.PARTIAL_NATIVE_HISTORY,
        LineageCompleteness.COMPLETE,
    )
    assert set(COMPLETENESS_PRECEDENCE) == set(LineageCompleteness)
    assert completeness(()) == (LineageCompleteness.COMPLETE, (LineageCompleteness.COMPLETE,))
    assert completeness([LineageCompleteness.COMPLETE]) == (
        LineageCompleteness.COMPLETE,
        (LineageCompleteness.COMPLETE,),
    )
    state, qualifiers = completeness(
        [
            LineageCompleteness.PARTIAL_NATIVE_HISTORY,
            LineageCompleteness.COMPLETE,
            LineageCompleteness.RESTRICTED_EVIDENCE,
            LineageCompleteness.TRUNCATED_BUDGET,
            LineageCompleteness.RESTRICTED_EVIDENCE,
        ]
    )
    assert state is LineageCompleteness.TRUNCATED_BUDGET
    assert qualifiers == (
        LineageCompleteness.TRUNCATED_BUDGET,
        LineageCompleteness.RESTRICTED_EVIDENCE,
        LineageCompleteness.PARTIAL_NATIVE_HISTORY,
    )
    # A restart outranks everything, and `complete` never rides along.
    every = completeness(list(LineageCompleteness))
    assert every[0] is LineageCompleteness.SCOPE_CHANGED_RESTART_REQUIRED
    assert LineageCompleteness.COMPLETE not in every[1]
    assert every[1] == COMPLETENESS_PRECEDENCE[:-1]


# ---- sections 4.2 and 5: the backfill source document ------------------------------


def test_backfill_source_document_golden_vectors() -> None:
    loaded = _vectors()
    vectors = loaded["vectors"]
    names = [vector["name"] for vector in vectors]
    assert len(names) == len(set(names)) >= 11
    # Every source kind is exercised.
    assert {vector["input"]["source_kind"] for vector in vectors} == {
        kind.value for kind in BackfillSourceKind
    }
    for vector in vectors:
        document = source_document(**_inputs(vector))
        assert document == vector["document"], vector["name"]
        assert document.isascii(), vector["name"]
        assert json.loads(document)["schema_version"] == 1
        expected = hashlib.sha256(SOURCE_DOMAIN + document.encode("utf-8")).hexdigest()
        assert source_digest(**_inputs(vector)) == expected == vector["digest"], vector["name"]
        reference = vector.get("reference")
        if reference is not None:
            # The stored token, and the digest the document carries, are of the
            # exact stored bytes; the text itself appears nowhere.
            kind, token = origin_reference(reference)
            assert kind.value == vector["input"]["source_kind"], vector["name"]
            assert token == vector["input"]["source_ref"], vector["name"]
            if not reference.isascii() or kind is BackfillSourceKind.WORK_ORIGIN_OTHER:
                assert reference not in document, vector["name"]
            digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
            assert vector["input"]["facts"]["origin_ref_sha256"] == digest

    by_name = {vector["name"]: vector for vector in vectors}
    # R3-F22: a non-ASCII, non-NFC free-text reference is digested as stored --
    # never normalized -- and its NFC form is a different token.
    free = by_name["work_origin_other_non_ascii_non_nfc"]["reference"]
    assert not free.isascii()
    assert unicodedata.normalize("NFC", free) != free
    assert reference_token(free) == "free_text:" + hashlib.sha256(free.encode()).hexdigest()
    assert reference_token(unicodedata.normalize("NFC", free)) != reference_token(free)
    # R3-F27: population by identifier shape, not by prefix.
    assert origin_reference("asrt_not-an-identifier")[0] is BackfillSourceKind.WORK_ORIGIN_OTHER
    assert origin_reference("cap_lineages3vec0001")[0] is (
        BackfillSourceKind.WORK_ORIGIN_CAPTURE_ROOT
    )
    assert reference_token("mnote_lineages3vec0001").startswith("prefix:mnote:")
    assert all(
        len(vector["input"]["source_ref"]) <= 256 and vector["input"]["source_ref"].isascii()
        for vector in vectors
    )

    # The document refuses what the SQL function could not emit.
    task = _inputs(by_name["task_follow_up"])
    for broken in (
        {**task, "source_family": "commitment"},
        {**task, "facts": {}},
        {**task, "facts": {"commitment_id": "cmt_lineages3vec0001", "extra": 1}},
        {**task, "facts": {"commitment_id": "cmt_lineages3vecé0001"}},
        {**task, "source_ref": ""},
        {**task, "source_ref": "x" * 257},
        {**task, "source_version": 0},
    ):
        with pytest.raises(InvalidLineageValueError):
            source_document(**broken)
    assertion = _inputs(by_name["work_origin_assertion"])
    spans = list(assertion["facts"]["spans"])
    with pytest.raises(InvalidLineageValueError):
        source_document(**{**assertion, "facts": {**assertion["facts"], "spans": spans[::-1]}})

    # The plan digest: domain-separated canonical JSON over the items in order.
    items = [(1, "a" * 64, "native_virtual_proven", "native_follow_up", None)]
    expected_plan = hashlib.sha256(
        PLAN_DOMAIN
        + (
            '{"items":[[1,"' + "a" * 64 + '","native_virtual_proven","native_follow_up",null]],'
            '"run_id":"lbfr_lineages3vec0001","schema_version":1,"validator_version":1}'
        ).encode()
    ).hexdigest()
    assert plan_digest(run_id="lbfr_lineages3vec0001", validator_version=1, items=items) == (
        expected_plan
    )
    with pytest.raises(InvalidLineageValueError):
        plan_digest(run_id="lbfr_lineages3vec0001", validator_version=1, items=items * 2)


# ---- sections 3.1 to 3.3 (worker L2): transitions, order, context, chain -------------

_ISSUE: Final = "sit_lineages3domain0001"
_OTHER_ISSUE: Final = "sit_lineages3domain0002"


def _ref(family: RecordFamily, suffix: str) -> RecordRef:
    prefix = {
        RecordFamily.SITUATION: "sit",
        RecordFamily.MEETING: "mtg",
        RecordFamily.MEETING_NOTE_VERSION: "mnote",
        RecordFamily.TASK: "tsk",
        RecordFamily.COMMITMENT: "cmt",
        RecordFamily.CONSTRAINT: "cst",
        RecordFamily.CAPTURE_VERSION: "capver",
    }[family]
    return RecordRef(family=family, record_id=f"{prefix}_{suffix}")


def _anchor(role: EvidenceRole, kind: SourceVersionKind) -> EvidenceAnchor:
    exact = kind is SourceVersionKind.IMMUTABLE_VERSION
    return EvidenceAnchor(
        source_family=(
            EvidenceSourceFamily.MEETING_NOTE_VERSION if exact else EvidenceSourceFamily.CAPTURE
        ),
        source_root_id="mtg_lineages3domain0001" if exact else "cap_lineages3domain0001",
        source_version_kind=kind,
        source_version_id="mnote_lineages3domain0001" if exact else None,
        source_version_no=1 if exact else None,
        source_sha256="0" * 64 if exact else None,
        passage_start_cp=None,
        passage_end_cp=None,
        passage_sha256=None,
        role=role,
    )


def test_link_transition_table() -> None:
    active, contested, ended = (
        LinkLifecycleState.ACTIVE,
        LinkLifecycleState.CONTESTED,
        LinkLifecycleState.ENDED,
    )
    # Section 3.1's table, exactly.
    assert {
        (action, state): link_transition(action, state)
        for action in LINK_TRANSITIONS
        for state in LinkLifecycleState
    } == {
        (LinkRevisionAction.CORRECT_EVIDENCE, active): active,
        (LinkRevisionAction.CORRECT_EVIDENCE, contested): None,
        (LinkRevisionAction.CORRECT_EVIDENCE, ended): None,
        (LinkRevisionAction.END, active): ended,
        (LinkRevisionAction.END, contested): ended,
        (LinkRevisionAction.END, ended): None,
        (LinkRevisionAction.CONTEST, active): contested,
        (LinkRevisionAction.CONTEST, contested): None,
        (LinkRevisionAction.CONTEST, ended): None,
        (LinkRevisionAction.REINSTATE, active): None,
        (LinkRevisionAction.REINSTATE, contested): active,
        (LinkRevisionAction.REINSTATE, ended): None,
    }
    # `assert` writes revision 1 and is no transition; `ended` admits nothing.
    assert link_transition(LinkRevisionAction.ASSERT, active) is None
    assert set(LINK_TRANSITIONS) == set(LinkRevisionAction) - {LinkRevisionAction.ASSERT}
    assert {active, contested} == LIVE_LINK_STATES
    # The contest rule: an exact `contradicts` anchor, beside any other role.
    exact = SourceVersionKind.IMMUTABLE_VERSION
    legacy = SourceVersionKind.LEGACY_UNVERSIONED
    assert is_contest_evidence([_anchor(EvidenceRole.CONTRADICTS, exact)])
    assert is_contest_evidence(
        [_anchor(EvidenceRole.CORROBORATES, exact), _anchor(EvidenceRole.CONTRADICTS, exact)]
    )
    assert not is_contest_evidence([_anchor(EvidenceRole.CONTRADICTS, legacy)])
    assert not is_contest_evidence([_anchor(EvidenceRole.CORROBORATES, exact)])
    assert not is_contest_evidence([])


def test_related_context_canonical_order() -> None:
    meeting = _ref(RecordFamily.MEETING, "lineages3order0001")
    task = _ref(RecordFamily.TASK, "lineages3order0001")
    # Family token first: "meeting" < "task".
    assert related_context_order(task, meeting) == (meeting, task)
    assert related_context_order(meeting, task) == (meeting, task)
    # Then the identifier, by code point: "B" (66) sorts before "a" (97).
    upper = RecordRef(family=RecordFamily.TASK, record_id="tsk_Blineages3order01")
    lower = RecordRef(family=RecordFamily.TASK, record_id="tsk_alineages3order01")
    assert related_context_order(lower, upper) == (upper, lower)
    assert related_context_order(upper, lower) == (upper, lower)
    # Both request orders therefore have one identity.
    identities = {
        normalized_identity(
            kind=RecordLinkKind.SEMANTIC,
            relation_type=RelationType.RELATED_CONTEXT,
            from_ref=pair[0],
            to_ref=pair[1],
            member_role=None,
            context_issue_id=_ISSUE,
        )
        for pair in (related_context_order(lower, upper), related_context_order(upper, lower))
    }
    assert len(identities) == 1
    # Equal endpoints come back as given (the application refuses them).
    assert related_context_order(task, task) == (task, task)


def test_in_issue_context_predicate() -> None:
    issue = RecordRef(family=RecordFamily.SITUATION, record_id=_ISSUE)
    member = _ref(RecordFamily.TASK, "lineages3ctx000001")
    paired = _ref(RecordFamily.MEETING_NOTE_VERSION, "lineages3ctx000001")
    outsider = _ref(RecordFamily.TASK, "lineages3ctx000002")
    inside = frozenset({issue, member, paired})

    def judged(
        kind: RecordLinkKind, source: RecordRef, target: RecordRef, context: str | None
    ) -> bool:
        return in_issue_context(
            kind=kind,
            from_ref=source,
            to_ref=target,
            context_issue_id=context,
            issue_id=_ISSUE,
            inside=inside,
        )

    semantic, membership = RecordLinkKind.SEMANTIC, RecordLinkKind.ISSUE_MEMBERSHIP
    # A membership: only from this Issue.
    assert judged(membership, issue, member, _ISSUE)
    other_issue = RecordRef(family=RecordFamily.SITUATION, record_id=_OTHER_ISSUE)
    assert not judged(membership, other_issue, member, _OTHER_ISSUE)
    # A semantic link scoped to this Issue, whatever its endpoints.
    assert judged(semantic, outsider, outsider, _ISSUE)
    # One naming this Issue as an endpoint, whatever its context.
    assert judged(semantic, paired, issue, None)
    assert judged(semantic, paired, issue, _OTHER_ISSUE)
    # A null-context link with both endpoints inside; not with one outside.
    assert judged(semantic, member, paired, None)
    assert not judged(semantic, member, outsider, None)
    # A link scoped to another Issue is never in this one's context, even inside.
    assert not judged(semantic, member, paired, _OTHER_ISSUE)


def test_handoff_chain_skips_voided_events() -> None:
    created = datetime(2026, 10, 19, 9, tzinfo=UTC)
    minute = timedelta(minutes=1)
    retime = HandoffCorrectionFact(
        correction_no=1,
        action=HandoffCorrectionAction.RETIME,
        corrected_effective_at=created + 5 * minute,
    )
    void = HandoffCorrectionFact(
        correction_no=2, action=HandoffCorrectionAction.VOID, corrected_effective_at=None
    )
    # Folding: the latest retime moves the current time; a void makes the event voided.
    folded = chain_state(2, created + 2 * minute, (void, retime))
    assert (folded.effective_at, folded.current_effective_at, folded.voided) == (
        created + 2 * minute,
        created + 5 * minute,
        True,
    )
    plain = chain_state(1, created + minute, ())
    assert (plain.current_effective_at, plain.voided) == (created + minute, False)
    chain = (
        plain,
        chain_state(2, created + 2 * minute, (void,)),
        chain_state(3, created + 3 * minute, ()),
    )
    # The last live event is 3; with 3 gone too, it is 1 (2 is skipped).
    assert last_live(chain) == chain[2]
    assert last_live(chain[:2]) == chain[0]
    assert last_live(chain, before=3) == chain[0]
    assert last_live((chain[1],)) is None
    # Only the last live event can be voided.
    assert can_void(chain, 3)
    assert not can_void(chain, 1)
    assert can_void(chain[:2], 1)
    assert not can_void(chain[:2], 2)
    # A retime of 3 is bounded by the previous *live* event (1), not the voided 2.
    recorded = created + 10 * minute
    bounds = {"commitment_created_at": created, "recorded_at": recorded}
    assert retime_in_order(chain, 3, created + 90 * timedelta(seconds=1), **bounds)
    assert not retime_in_order(chain, 3, created + 30 * timedelta(seconds=1), **bounds)
    # And a retime of 1 by the next live event (3).
    assert retime_in_order(chain, 1, created + 170 * timedelta(seconds=1), **bounds)
    assert not retime_in_order(chain, 1, created + 190 * timedelta(seconds=1), **bounds)
    # Never before the Commitment's creation, never after its own recording.
    assert not retime_in_order(chain, 1, created - minute, **bounds)
    assert not retime_in_order((chain[2],), 3, recorded + minute, **bounds)


# ---- section 5: the lineage cursor (worker L3) ----------------------------------------

_CURSOR_K: Final = datetime(2026, 10, 19, 12, 0, 0, 123456, tzinfo=UTC)
_CURSOR_N: Final = datetime(2026, 10, 19, 12, 5, tzinfo=UTC)
_CURSOR_REQUEST: Final = {
    "origin": {"family": "task", "record_id": "tsk_cursorgolden01"},
    "issue_id": None,
    "max_depth": 4,
    "known_at": None,
    "valid_at": None,
    "page_size": 10,
}
#: Golden tokens: a `records.lineage` cursor and an `issues.timeline` one (`n`
#: null, a Record Event watermark, an array position). Recomputing them from the
#: section 5 formula below must give these exact bytes.
_GOLDEN_LINEAGE: Final = (
    "eyJiIjoiMTlhODlmOTdkMDE4YzUzZDdjZGU4Yjg1ZjlmYTNmZGFkY2Y4Yzk4YmE5YWUyYTU1MjM0OGMxZjQzODg3"
    "NmMwMiIsImsiOiIyMDI2LTEwLTE5VDEyOjAwOjAwLjEyMzQ1NloiLCJuIjoiMjAyNi0xMC0xOVQxMjowNTowMC4w"
    "MDAwMDBaIiwicCI6ImU6aXJsX2N1cnNvcmdvbGRlbjAxIiwiciI6bnVsbCwicyI6ImUwMjUyZmY4ZjRhNjg5Yzdm"
    "MWZhOTg5OGJjMDgwZTZlZTQzMDE3YTFjODFhY2YyYTdhMzNmMzc3YzM0MDRlY2UiLCJ0IjoiMjAyNi0xMC0xOVQx"
    "MjowMDowMC4xMjM0NTZaIiwidiI6MX0"
)
_GOLDEN_TIMELINE: Final = (
    "eyJiIjoiMTlhODlmOTdkMDE4YzUzZDdjZGU4Yjg1ZjlmYTNmZGFkY2Y4Yzk4YmE5YWUyYTU1MjM0OGMxZjQzODg3"
    "NmMwMiIsImsiOm51bGwsIm4iOm51bGwsInAiOlsiMjAyNi0xMC0xOVQxMjowMDowMC4wMDAwMDBaIiwxLDYsInJj"
    "ZXZfY3Vyc29yZ29sZGVuMDEiXSwiciI6InJjZXZfY3Vyc29yZ29sZGVuMDEiLCJzIjoiZTAyNTJmZjhmNGE2ODlj"
    "N2YxZmE5ODk4YmMwODBlNmVlNDMwMTdhMWM4MWFjZjJhN2EzM2YzNzdjMzQwNGVjZSIsInQiOm51bGwsInYiOjF9"
)


def _sha(document: object) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _binding(**overrides: Any) -> str:  # noqa: ANN401
    arguments: dict[str, Any] = {
        "capability": "records.lineage",
        "principal_id": "prn_lineagecursor01",
        "request": _CURSOR_REQUEST,
        "known_at": _CURSOR_K,
        "lineage_valid_at": _CURSOR_K,
        "native_cut_at": _CURSOR_N,
        "record_event_watermark": None,
    }
    arguments.update(overrides)
    return cursor_binding(**arguments)


def _lineage_position(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("n:", "e:", "v:"))


def test_cursor_golden_vectors_and_malformed_tokens() -> None:
    binding = _binding()
    # `b` is the section 5 formula, byte for byte.
    assert binding == _sha(
        {
            "capability": "records.lineage",
            "cursor_version": 1,
            "known_at": "2026-10-19T12:00:00.123456Z",
            "native_cut_at": "2026-10-19T12:05:00.000000Z",
            "principal_id": "prn_lineagecursor01",
            "record_event_watermark": None,
            "request": _CURSOR_REQUEST,
            "valid_at": "2026-10-19T12:00:00.123456Z",
        }
    )
    scope = scope_digest(None)
    assert scope == _sha({"generation": LINEAGE_READ_GENERATION, "grant_digest": None})
    lineage = LineageCursor(
        binding=binding,
        scope=scope,
        known_at=_CURSOR_K,
        lineage_valid_at=_CURSOR_K,
        native_cut_at=_CURSOR_N,
        record_event_watermark=None,
        position="e:irl_cursorgolden01",
    )
    assert encode_cursor(lineage) == _GOLDEN_LINEAGE
    assert decode_cursor(_GOLDEN_LINEAGE, _lineage_position) == lineage
    # A timeline cursor: no native cut, a watermark, an array position.
    timeline = LineageCursor(
        binding=binding,
        scope=scope,
        known_at=None,
        lineage_valid_at=None,
        native_cut_at=None,
        record_event_watermark="rcev_cursorgolden01",
        position=["2026-10-19T12:00:00.000000Z", 1, 6, "rcev_cursorgolden01"],
    )
    assert encode_cursor(timeline) == _GOLDEN_TIMELINE
    assert decode_cursor(_GOLDEN_TIMELINE, lambda p: isinstance(p, list)) == timeline
    assert instant_token(_CURSOR_K) == "2026-10-19T12:00:00.123456Z"
    assert parse_instant_token("2026-10-19T12:00:00.123456Z") == _CURSOR_K
    # Malformed: the encoding, the length, the keys, the version, a digest, an
    # instant, the watermark and the position's shape each refuse.
    document = json.loads(base64.urlsafe_b64decode(_GOLDEN_LINEAGE + "=="))

    def token(**changes: object) -> str:
        edited = {**document, **changes}
        for key in [key for key, value in changes.items() if value is _DROP]:
            del edited[key]
        raw = json.dumps(edited, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    malformed: list[object] = [
        None,
        7,
        "",
        "not base64url!",
        "x" * 2049,
        base64.urlsafe_b64encode(b"[1,2]").decode().rstrip("="),
        base64.urlsafe_b64encode(b"\xff\xfe").decode().rstrip("="),
        token(v=2),
        token(v="1"),
        token(b="0" * 63),
        token(s="Z" * 64),
        token(k="2026-10-19T12:00:00Z"),
        token(n="yesterday"),
        token(r="rcpt_cursorgolden01"),
        token(p="x:irl_cursorgolden01"),
        token(p=["not", "a", "lineage", "key"]),
        token(extra=1),
        token(p=_DROP),
    ]
    for value in malformed:
        with pytest.raises(CursorMalformedError):
            decode_cursor(value, _lineage_position)
    with pytest.raises(ValueError, match="2048"):
        encode_cursor(replace_position(lineage, "e:" + "a" * 2100))


_DROP: Final = object()


def replace_position(cursor: LineageCursor, position: object) -> LineageCursor:
    return LineageCursor(
        binding=cursor.binding,
        scope=cursor.scope,
        known_at=cursor.known_at,
        lineage_valid_at=cursor.lineage_valid_at,
        native_cut_at=cursor.native_cut_at,
        record_event_watermark=cursor.record_event_watermark,
        position=position,
    )


def test_the_binding_changes_with_every_bound_field() -> None:
    base = _binding()
    later = _CURSOR_K + timedelta(microseconds=1)
    variants = {
        "capability": _binding(capability="issues.timeline"),
        "principal": _binding(principal_id="prn_lineagecursor02"),
        "origin": _binding(
            request={**_CURSOR_REQUEST, "origin": {"family": "task", "record_id": "tsk_other0001"}}
        ),
        "issue_id": _binding(request={**_CURSOR_REQUEST, "issue_id": "sit_cursorgolden01"}),
        "max_depth": _binding(request={**_CURSOR_REQUEST, "max_depth": 3}),
        "requested_known_at": _binding(
            request={**_CURSOR_REQUEST, "known_at": "2026-10-19T12:00:00.123456Z"}
        ),
        "requested_valid_at": _binding(
            request={**_CURSOR_REQUEST, "valid_at": "2026-10-19T12:00:00.123456Z"}
        ),
        "page_size": _binding(request={**_CURSOR_REQUEST, "page_size": 11}),
        "k": _binding(known_at=later),
        "t": _binding(lineage_valid_at=later),
        "n": _binding(native_cut_at=later),
        "r": _binding(record_event_watermark="rcev_cursorgolden01"),
    }
    assert base not in variants.values()
    assert len(set(variants.values())) == len(variants)
    # Deterministic: the same inputs bind the same token.
    assert _binding() == base


def test_the_scope_digest_changes_with_family_grants_and_generation() -> None:
    local = scope_digest(grant_digest(None, "records.lineage"))
    assert grant_digest(None, "records.lineage") is None
    called = [("records.lineage", "record_lineage_read")]
    reads = [("issues.read", "issue_read"), ("tasks.read", "task_read")]
    base = grant_digest([*called, *reads], "records.lineage")
    # Order and duplicates do not matter; the set does.
    assert base == grant_digest([*reversed(reads), *called, *called], "records.lineage")
    # A grant outside the family reads and the called capability is not bound.
    assert base == grant_digest(
        [*called, *reads, ("record_events.list", "record_event_read")], "records.lineage"
    )
    digests = {
        "base": base,
        "a family read revoked": grant_digest([*called, reads[0]], "records.lineage"),
        "a family read added": grant_digest(
            [*called, *reads, ("meetings.read", "meeting_read")], "records.lineage"
        ),
        "a purpose changed": grant_digest(
            [*called, ("issues.read", None), reads[1]], "records.lineage"
        ),
        "the called grant revoked": grant_digest(reads, "records.lineage"),
        "no grant at all": grant_digest([], "records.lineage"),
    }
    assert len(set(digests.values())) == len(digests)
    scopes = {scope_digest(value) for value in digests.values()} | {local}
    assert len(scopes) == len(digests) + 1
    # The read generation is bound too.
    assert scope_digest(base, generation=LINEAGE_READ_GENERATION + 1) != scope_digest(base)
    assert scope_digest(None, generation=2) != local
