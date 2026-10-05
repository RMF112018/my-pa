"""KLP-WP-04 slice C: Knowledge Review on a real database (R6 sections 3.2, 8, 10).

KLP-AC-035, KLP-AC-038 (fresh/replay keys), KLP-AC-115, plus the promotion
behaviour behind KLP-AC-036/041/095/116. Marked `database` (auto
`database_clone`), routed to `database-current-head`.

Every proposal is filed by the production autonomous submit (a bound discovery
client) and every decision goes through `ApplicationService.invoke` as
`review.decide`, from the surface the test names (CLI / HTTP gateway operator
surface, an unstamped local caller, a remote ChatLLM client, an operator-review
client). Direct SQL only reads rows back and seeds the next predicate head
version the frozen seeds lack (the registry has no runtime writer).

* **KLP-AC-035** -- a `review_queued` proposal is no assertion: not in
  `knowledge.assertions.list`, no assertion/mutation/link/Record Event row;
  only acceptance promotes it.
* **KLP-AC-038 (keys)** -- the result is exactly the seven existing keys,
  `decision_id` = `kadec_`, `assertion_id` = `kasr_` / null, `receipt_id` =
  `kamut_` / null, completed into `relationship_write_requests` as
  `review_decision`.
* **KLP-AC-115** -- each decision row carries the derived channel/authority
  pair and `authenticated_client_id` for remote channels only.
* Promotion: `review_accepted` assertion at the active head, citing the
  proposal's case, a `review_accept` / `review_correct` mutation citing the
  decision, links equal to the origin submission's evidence, a single-current
  holder superseded, an equal live fact refused `conflict(duplicate_fact)`, an
  archived Capture refused `denied(capture_withdrawn)`, an archived subject
  Entity refused `denied(subject)`.
* State machine: reject/defer/mark_unresolved/invalidate move the proposal and
  write nothing canonical; a terminal proposal and a stale version conflict.
* KLP-AC-114 (database half): CHECK `knowledge_decision_operator_rule_holds`
  refuses an `ordinary_reviewer` accept / correct_and_accept of a
  `requires_operator` case, and `knowledge_decision_channel_matches_authority`
  refuses a channel, class and client that do not travel together.

This module also holds the Review harness the other slice C modules import.
Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError

from my_pa.application.commands import (
    ArchiveEntity,
    Command,
    DecideReviewCase,
    ListKnowledgeAssertions,
    ListReviewCases,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.review import CorrectionPatch, Disposition
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    knowledge_assertion_evidence_links,
    knowledge_assertion_mutations,
    knowledge_assertion_proposals,
    knowledge_assertion_review_decisions,
    knowledge_assertions,
    knowledge_submission_evidence,
    relationship_write_requests,
)
from tests.database.test_knowledge_assertion_repository import (
    POLICY,
    WHEN,
    capture_evidence,
    counts,
    knowledge_events,
    new_principal,
)
from tests.database.test_knowledge_assertion_submissions import (
    PAYMENT,
    SubmitRuntime,
    add_direct_payment_head,
    archive_capture,
    external,
)

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

OPERATOR_CLIENT: Final = "klp04-synthetic-operator-review-client"
CHATLLM_CLIENT: Final = "klp04-synthetic-chatllm-client"
#: A remote reviewer's grants: both Review names plus the Knowledge read grant.
READ_GRANTS: Final = frozenset(
    {
        (Capability.REVIEW_LIST, None),
        (Capability.REVIEW_DECIDE, None),
        (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ),
    }
)
#: The same remote reviewer without the Knowledge read grant.
NO_READ_GRANTS: Final = frozenset(
    {(Capability.REVIEW_LIST, None), (Capability.REVIEW_DECIDE, None)}
)
#: The frozen R6 section 10.1 Knowledge `review.list` row keys.
KNOWLEDGE_ROW_KEYS: Final = frozenset(
    {
        "review_case_id",
        "proposal_id",
        "proposal_state",
        "risk_class",
        "opened_at",
        "review_version",
        "latest_disposition",
        "subject_kind",
        "subject_kind_of_fact",
        "subject_id",
        "predicate_code",
        "review_requirement",
    }
)
#: The existing seven `review.decide` result keys (R6 section 10.1).
DECIDE_KEYS: Final = frozenset(
    {
        "review_case_id",
        "decision_id",
        "review_version",
        "disposition",
        "proposal_state",
        "assertion_id",
        "receipt_id",
    }
)


def remote(client: str, grants: frozenset[Any] = READ_GRANTS) -> dict[str, object]:
    """The keyword set of one remote MCP caller."""
    return {"transport": CaptureTransport.REMOTE_CLIENT, "grants": grants, "client_id": client}


CLI: Final[dict[str, object]] = {"operator_surface": OperatorSurface.CLI}
WEB: Final[dict[str, object]] = {"operator_surface": OperatorSurface.HTTP_GATEWAY}
#: An unstamped local caller (stdio MCP): no surface, no client, no grants.
STDIO: Final[dict[str, object]] = {}


class ReviewRuntime(SubmitRuntime):
    """`SubmitRuntime` with the operator-review allowlist bound and Review helpers."""

    def __init__(self, url: str, *, identity_correction: bool = False) -> None:
        super().__init__(
            url,
            operator_review_client_ids=frozenset({OPERATOR_CLIENT}),
            identity_correction=identity_correction,
        )

    def org(self, principal_id: str, key: str) -> str:
        return self.entity(principal_id, key)

    def queue(
        self,
        principal_id: str,
        profile: str,
        subject_id: str,
        *,
        candidate: str = "cand-1",
        predicate: str = PAYMENT,
        subject_kind: KnowledgeSubjectKind = KnowledgeSubjectKind.ENTITY,
        value: str = "Synthetic net 30 terms",
        evidence: tuple[dict[str, object], ...] | None = None,
    ) -> dict[str, Any]:
        """File one proposal through the production submit; asserts `review_queued`."""
        result = self.submit(
            principal_id,
            profile,
            subject_id=subject_id,
            subject_kind=subject_kind,
            candidate=candidate,
            predicate=predicate,
            value=value,
            evidence=evidence,
        )
        assert result["outcome"] == "review_queued", result
        return result

    def decide_command(
        self,
        case: str,
        disposition: Disposition,
        *,
        version: int = 0,
        patch: dict[str, object] | None = None,
        reason: str | None = None,
        corrected_value: str | None = None,
    ) -> DecideReviewCase:
        if reason is None and disposition is Disposition.INVALIDATE:
            reason = "Synthetic basis went away"
        return DecideReviewCase(
            review_case_id=case,
            expected_review_version=version,
            disposition=disposition,
            correction_patch=None if patch is None else CorrectionPatch.of(patch),
            corrected_value=corrected_value,
            reason=reason,
        )

    def decide(
        self,
        principal_id: str,
        case: str,
        disposition: Disposition = Disposition.ACCEPT,
        *,
        version: int = 0,
        patch: dict[str, object] | None = None,
        reason: str | None = None,
        via: dict[str, object] = CLI,
    ) -> dict[str, Any]:
        return self.ok(
            self.decide_command(case, disposition, version=version, patch=patch, reason=reason),
            principal_id=principal_id,
            **via,
        )

    def decide_error(
        self,
        principal_id: str,
        case: str,
        disposition: Disposition = Disposition.ACCEPT,
        *,
        version: int = 0,
        patch: dict[str, object] | None = None,
        reason: str | None = None,
        corrected_value: str | None = None,
        via: dict[str, object] = CLI,
    ) -> dict[str, Any]:
        return self.error(
            self.decide_command(
                case,
                disposition,
                version=version,
                patch=patch,
                reason=reason,
                corrected_value=corrected_value,
            ),
            principal_id=principal_id,
            **via,
        )

    def cases(
        self,
        principal_id: str,
        *,
        via: dict[str, object] = CLI,
        **filters: Any,  # noqa: ANN401 - ListReviewCases keywords
    ) -> list[dict[str, Any]]:
        listed = self.ok(ListReviewCases(**filters), principal_id=principal_id, **via)
        return list(listed["review_cases"])

    def knowledge_cases(
        self,
        principal_id: str,
        *,
        via: dict[str, object] = CLI,
        **filters: Any,  # noqa: ANN401 - ListReviewCases keywords
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in self.cases(principal_id, via=via, **filters)
            if row["subject_kind"] == "knowledge_assertion"
        ]

    def invoke_with_request_id(
        self,
        command: Command,
        *,
        principal_id: str,
        request_id: str,
        **via: Any,  # noqa: ANN401
    ) -> ResponseEnvelope:
        """One invoke under a caller-fixed request id (the C1 replay identity)."""
        capability = command.capability
        return self.service.invoke(
            RequestMetadata(
                request_id=request_id,
                capability=capability,
                purpose=sorted(permitted_purposes(capability))[0],
                principal_id=principal_id,
                requested_at=WHEN,
            ),
            command,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            transport=via.get("transport", CaptureTransport.LOCAL),
            capability_grants=via.get("grants"),
            authenticated_client_id=via.get("client_id"),
            operator_surface=via.get("operator_surface"),
        )

    def archive_entity(self, principal_id: str, entity_id: str) -> None:
        self.ok(
            ArchiveEntity(
                entity_id=entity_id,
                expected_version=1,
                reason="Synthetic archive",
                idempotency_key=f"klp04-archive-{entity_id}",
            ),
            principal_id=principal_id,
        )


def without_correlation(error: dict[str, Any]) -> dict[str, Any]:
    """An error body minus its per-request correlation id (the only varying field)."""
    return {key: value for key, value in error.items() if key != "correlation_id"}


def decisions_of(engine: Engine, case: str) -> list[dict[str, Any]]:
    d = knowledge_assertion_review_decisions
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(d).where(d.c.review_case_id == case).order_by(d.c.decision_sequence)
            ).mappings()
        ]


def proposal_of(engine: Engine, case: str) -> dict[str, Any]:
    p = knowledge_assertion_proposals
    with engine.connect() as connection:
        return dict(
            connection.execute(select(p).where(p.c.review_case_id == case)).mappings().one()
        )


def assertion_of(engine: Engine, assertion_id: str) -> dict[str, Any]:
    a = knowledge_assertions
    with engine.connect() as connection:
        return dict(
            connection.execute(select(a).where(a.c.assertion_id == assertion_id)).mappings().one()
        )


def mutation_of(engine: Engine, mutation_id: str) -> dict[str, Any]:
    m = knowledge_assertion_mutations
    with engine.connect() as connection:
        return dict(
            connection.execute(select(m).where(m.c.mutation_id == mutation_id)).mappings().one()
        )


def write_request_of(engine: Engine, decision_id: str) -> dict[str, Any]:
    w = relationship_write_requests
    with engine.connect() as connection:
        return dict(
            connection.execute(select(w).where(w.c.result_id == decision_id)).mappings().one()
        )


def assertion_count(engine: Engine, principal_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).where(knowledge_assertions.c.principal_id == principal_id)
            ).scalar_one()
        )


@pytest.fixture
def review(disposable_database: str) -> Iterator[ReviewRuntime]:
    composed = ReviewRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _queued(review: ReviewRuntime, *, candidate: str = "cand-1") -> tuple[str, str, str]:
    """(principal, subject entity, review_case_id) of one requires_operator proposal."""
    principal = new_principal()
    profile = review.profile(principal)
    entity = review.org(principal, "acme")
    result = review.queue(principal, profile, entity, candidate=candidate)
    return principal, entity, str(result["review_case_id"])


# ---- KLP-AC-035: a proposal is not an assertion ------------------------------------


def test_a_queued_proposal_is_no_assertion_until_acceptance_promotes_it(
    review: ReviewRuntime,
) -> None:
    principal, entity, case = _queued(review)
    before = counts(review.engine, principal)
    assert before["knowledge_assertions"] == 0
    assert before["knowledge_assertion_mutations"] == 0
    assert before["knowledge_assertion_evidence_links"] == 0
    assert before["record_events"] == 0
    listed = review.ok(ListKnowledgeAssertions(), principal_id=principal)
    assert listed["assertions"] == []
    (row,) = review.knowledge_cases(principal)
    assert set(row) == KNOWLEDGE_ROW_KEYS
    assert row["review_case_id"] == case
    assert row["subject_kind_of_fact"] == "entity"
    assert row["subject_id"] == entity
    assert row["predicate_code"] == PAYMENT
    assert row["review_requirement"] == "requires_operator"
    assert row["proposal_state"] == "needs_review"
    assert row["risk_class"] == "high"
    assert row["review_version"] == 0
    assert row["latest_disposition"] is None

    decided = review.decide(principal, case)
    assert set(decided) == DECIDE_KEYS
    assert decided["decision_id"].startswith("kadec_")
    assert decided["assertion_id"].startswith("kasr_")
    assert decided["receipt_id"].startswith("kamut_")
    assert decided["proposal_state"] == "accepted"
    assert decided["review_version"] == 1
    assert decided["disposition"] == "accept"

    fact = assertion_of(review.engine, decided["assertion_id"])
    proposal = proposal_of(review.engine, case)
    assert fact["epistemic_status"] == "review_accepted"
    assert fact["accepted_review_case_id"] == case
    assert fact["origin_submission_id"] == proposal["origin_submission_id"]
    assert fact["assertion_fingerprint"] == proposal["proposal_fingerprint"]
    assert fact["lifecycle"] == "active"
    assert fact["version"] == 1
    receipt = mutation_of(review.engine, decided["receipt_id"])
    assert receipt["mutation_kind"] == "review_accept"
    assert receipt["review_decision_id"] == decided["decision_id"]
    assert receipt["proposal_id"] == proposal["proposal_id"]
    assert receipt["review_case_id"] == case
    assert receipt["submission_id"] == proposal["origin_submission_id"]
    links = knowledge_assertion_evidence_links
    se = knowledge_submission_evidence
    with review.engine.connect() as connection:
        linked = set(
            connection.execute(
                select(links.c.evidence_ref_id, links.c.evidence_role).where(
                    links.c.assertion_id == decided["assertion_id"]
                )
            ).all()
        )
        cited = set(
            connection.execute(
                select(se.c.evidence_ref_id, se.c.evidence_role).where(
                    se.c.submission_id == proposal["origin_submission_id"]
                )
            ).all()
        )
    assert linked == cited and linked
    (event,) = knowledge_events(review.engine, principal)
    assert event["event_kind"] == "created"
    assert event["record_id"] == decided["assertion_id"]
    assert event["actor_class"] == "review_promotion"
    assert event["authority"] == "review_accepted"
    assert event["source_capability"] == "review.decide"
    assert event["source_receipt_id"] == decided["receipt_id"]
    listed = review.ok(ListKnowledgeAssertions(), principal_id=principal)
    assert [item["assertion_id"] for item in listed["assertions"]] == [decided["assertion_id"]]


def test_the_result_is_completed_into_the_review_decision_replay_row(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    decided = review.decide(principal, case)
    stored = write_request_of(review.engine, decided["decision_id"])
    assert stored["capability"] == "review.decide"
    assert stored["result_family"] == "review_decision"
    assert stored["result_secondary_id"] == case
    assert stored["result_assertion_id"] == decided["assertion_id"]
    assert stored["receipt_id"] == decided["receipt_id"]
    assert stored["result_state"] == "accepted"
    assert stored["result_disposition"] == "accept"
    assert stored["result_version"] == 1


# ---- KLP-AC-115: channel, authority and client on every decision -------------------


@pytest.mark.parametrize(
    ("via", "channel", "authority", "client"),
    [
        (CLI, "local_cli", "local_operator", None),
        (WEB, "local_web", "local_operator", None),
        (remote(OPERATOR_CLIENT), "remote_operator_review", "remote_operator_attested", True),
    ],
    ids=["cli", "http_gateway", "operator_review_client"],
)
def test_an_operator_decision_records_its_derived_channel(
    review: ReviewRuntime,
    via: dict[str, object],
    channel: str,
    authority: str,
    client: bool | None,
) -> None:
    principal, _entity, case = _queued(review)
    review.decide(principal, case, via=via)
    (decision,) = decisions_of(review.engine, case)
    assert decision["decision_channel"] == channel
    assert decision["operator_authority_class"] == authority
    assert decision["authenticated_client_id"] == (OPERATOR_CLIENT if client else None)
    assert decision["review_requirement"] == "requires_operator"
    assert decision["disposition"] == "accept"
    assert decision["external_feedback_ref_hash"] is None


@pytest.mark.parametrize(
    ("via", "channel", "client"),
    [
        (STDIO, "local_unattested", None),
        ({"operator_surface": None, "grants": READ_GRANTS}, "local_unattested", None),
        (remote(CHATLLM_CLIENT), "remote_interactive", CHATLLM_CLIENT),
    ],
    ids=["stdio", "local_with_grants", "chatllm_client"],
)
def test_an_ordinary_reviewer_decision_records_its_channel_and_may_accept_review_only(
    review: ReviewRuntime, via: dict[str, object], channel: str, client: str | None
) -> None:
    principal = new_principal()
    profile = review.profile(principal, direct=False)
    entity = review.org(principal, "acme")
    queued = review.queue(
        principal,
        profile,
        entity,
        predicate="organization.operating_requirement",
        value="Synthetic badge required on site",
    )
    case = str(queued["review_case_id"])
    proposal = proposal_of(review.engine, case)
    assert proposal["review_requirement"] == "requires_review"
    decided = review.decide(principal, case, via=via)
    assert decided["proposal_state"] == "accepted"
    (decision,) = decisions_of(review.engine, case)
    assert decision["decision_channel"] == channel
    assert decision["operator_authority_class"] == "ordinary_reviewer"
    assert decision["authenticated_client_id"] == client


def test_an_ordinary_reviewer_is_denied_an_operator_case_and_writes_nothing(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    before = counts(review.engine, principal)
    for via in (STDIO, remote(CHATLLM_CLIENT)):
        for disposition, patch in (
            (Disposition.ACCEPT, None),
            (Disposition.CORRECT_AND_ACCEPT, {"value": "Synthetic net 45 terms"}),
        ):
            error = review.decide_error(principal, case, disposition, patch=patch, via=via)
            assert error["code"] == "denied"
            assert error["safe_details"] == ["disposition"]
    assert decisions_of(review.engine, case) == []
    assert counts(review.engine, principal) == before
    # Non-promoting dispositions are open to an ordinary reviewer (no CHECK applies).
    deferred = review.decide(principal, case, Disposition.DEFER, via=remote(CHATLLM_CLIENT))
    assert deferred["proposal_state"] == "deferred"
    assert deferred["assertion_id"] is None and deferred["receipt_id"] is None


# ---- the state machine on storage -----------------------------------------------------


@pytest.mark.parametrize(
    ("disposition", "state"),
    [
        (Disposition.REJECT, "rejected"),
        (Disposition.DEFER, "deferred"),
        (Disposition.MARK_UNRESOLVED, "unresolved"),
        (Disposition.INVALIDATE, "invalidated"),
    ],
)
def test_a_non_promoting_disposition_moves_the_proposal_and_writes_nothing_canonical(
    review: ReviewRuntime, disposition: Disposition, state: str
) -> None:
    principal, _entity, case = _queued(review)
    before = counts(review.engine, principal)
    decided = review.decide(principal, case, disposition)
    assert decided["proposal_state"] == state
    assert decided["assertion_id"] is None
    assert decided["receipt_id"] is None
    assert proposal_of(review.engine, case)["state"] == state
    # KLP-AC-043: a decision alone emits no canonical Record Event.
    assert counts(review.engine, principal) == before
    (decision,) = decisions_of(review.engine, case)
    assert decision["disposition"] == disposition.value
    assert decision["decision_sequence"] == 1


def test_open_states_take_further_decisions_and_terminal_states_conflict(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    review.decide(principal, case, Disposition.DEFER)
    review.decide(principal, case, Disposition.MARK_UNRESOLVED, version=1)
    review.decide(principal, case, Disposition.DEFER, version=2)
    (row,) = review.knowledge_cases(principal)
    assert row["review_version"] == 3
    assert row["latest_disposition"] == "defer"
    assert row["proposal_state"] == "deferred"
    accepted = review.decide(principal, case, version=3)
    assert accepted["review_version"] == 4
    error = review.decide_error(principal, case, Disposition.REJECT, version=4)
    assert error["code"] == "conflict"
    assert error["safe_details"] == ["expected_review_version"]
    assert [row["decision_sequence"] for row in decisions_of(review.engine, case)] == [1, 2, 3, 4]


def test_a_stale_expected_version_conflicts_and_writes_no_decision(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    error = review.decide_error(principal, case, version=1)
    assert error["code"] == "conflict"
    assert error["safe_details"] == ["expected_review_version"]
    assert decisions_of(review.engine, case) == []
    assert assertion_count(review.engine, principal) == 0


# ---- correction --------------------------------------------------------------------


def test_correct_and_accept_writes_the_corrected_fact_and_keeps_the_patch(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    proposal = proposal_of(review.engine, case)
    decided = review.decide(
        principal,
        case,
        Disposition.CORRECT_AND_ACCEPT,
        patch={"value": "  Synthetic   net 45 terms ", "effective_from": "2026-09-01T00:00:00Z"},
    )
    assert decided["proposal_state"] == "corrected_accepted"
    fact = assertion_of(review.engine, decided["assertion_id"])
    assert fact["value_text"] == "Synthetic net 45 terms"
    assert fact["effective_from"] is not None
    assert fact["assertion_fingerprint"] != proposal["proposal_fingerprint"]
    assert fact["subject_id"] == proposal["subject_id"]
    assert fact["predicate_code"] == proposal["predicate_code"]
    assert fact["classification"] == proposal["classification"]
    assert mutation_of(review.engine, decided["receipt_id"])["mutation_kind"] == "review_correct"
    (decision,) = decisions_of(review.engine, case)
    assert decision["correction_patch"] == {
        "effective_from": "2026-09-01T00:00:00Z",
        "value": "  Synthetic   net 45 terms ",
    }
    (event,) = knowledge_events(review.engine, principal)
    assert event["event_kind"] == "created"


@pytest.mark.parametrize(
    "patch",
    [
        {"subject_id": "ent_synthetic00000001"},
        {"predicate_code": "policy.requirement"},
        {"owner_ref": {"kind": "task", "id": "tsk_synthetic00000001"}},
        {"principal_id": "prn_synthetic00000001"},
        {"source_profile_id": "kdsp_synthetic000001"},
        {"date_kind": "deadline"},
        {"value": 45},
        {"effective_from": "2026-09-01"},
        {"effective_from": "2026-09-02T00:00:00Z", "effective_to": "2026-09-01T00:00:00Z"},
    ],
    ids=[
        "subject",
        "predicate",
        "owner",
        "principal",
        "source_profile",
        "undeclared_qualifier",
        "non_text_value",
        "naive_instant",
        "unordered_interval",
    ],
)
def test_an_uncorrectable_patch_is_invalid_and_writes_nothing(
    review: ReviewRuntime, patch: dict[str, object]
) -> None:
    principal, _entity, case = _queued(review)
    before = counts(review.engine, principal)
    error = review.decide_error(principal, case, Disposition.CORRECT_AND_ACCEPT, patch=patch)
    assert error["code"] == "invalid_request"
    assert error["safe_details"] == ["corrected_value"]
    assert decisions_of(review.engine, case) == []
    assert counts(review.engine, principal) == before


def test_a_free_text_corrected_value_is_invalid_for_a_knowledge_case(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    error = review.decide_error(
        principal, case, Disposition.CORRECT_AND_ACCEPT, corrected_value="Synthetic net 60"
    )
    assert error["code"] == "invalid_request"
    assert error["safe_details"] == ["corrected_value"]
    assert decisions_of(review.engine, case) == []


def test_a_date_kind_qualifier_and_instant_value_are_correctable_on_a_dated_predicate(
    review: ReviewRuntime,
) -> None:
    principal = new_principal()
    profile = review.profile(principal)
    project = review.project(principal, "dated")
    queued = review.submit(
        principal,
        profile,
        subject_id=project,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        predicate="project.critical_date",
        value="2026-12-01T00:00:00+00:00",
        qualifier={"date_kind": "milestone"},
    )
    assert queued["outcome"] == "review_queued", queued
    case = str(queued["review_case_id"])
    decided = review.decide(
        principal,
        case,
        Disposition.CORRECT_AND_ACCEPT,
        patch={"date_kind": "deadline", "value": "2026-12-15T09:30:00+01:00"},
    )
    fact = assertion_of(review.engine, decided["assertion_id"])
    assert fact["qualifier_json"] == {"date_kind": "deadline"}
    assert fact["value_datetime"] == datetime(2026, 12, 15, 8, 30, tzinfo=UTC)


# ---- promotion under the C3-C6 locks ---------------------------------------------------


def test_acceptance_supersedes_a_different_single_current_holder(review: ReviewRuntime) -> None:
    add_direct_payment_head(review.engine)
    principal = new_principal()
    direct = review.profile(principal)
    entity = review.org(principal, "acme")
    created = review.submit(
        principal, direct, subject_id=entity, predicate=PAYMENT, value="Synthetic net 30"
    )
    assert created["outcome"] == "direct_created", created
    queued = review.submit(
        principal,
        direct,
        subject_id=entity,
        predicate=PAYMENT,
        candidate="cand-2",
        value="Synthetic net 60",
        evidence=(external("obj-2"),),
    )
    assert queued["outcome"] == "review_queued", queued
    decided = review.decide(principal, str(queued["review_case_id"]))
    successor = assertion_of(review.engine, decided["assertion_id"])
    predecessor = assertion_of(review.engine, str(created["assertion_id"]))
    assert successor["supersedes_assertion_id"] == created["assertion_id"]
    assert predecessor["lifecycle"] == "superseded"
    assert predecessor["version"] == 2
    kinds = [event["event_kind"] for event in knowledge_events(review.engine, principal)]
    # create (direct), then the predecessor's state change and the successor's creation.
    assert kinds == ["created", "state_changed", "created"]


def test_an_equal_live_fact_under_the_subject_lock_refuses_acceptance(
    review: ReviewRuntime,
) -> None:
    add_direct_payment_head(review.engine)
    principal = new_principal()
    profile = review.profile(principal, direct=False)
    entity = review.org(principal, "acme")
    queued = review.queue(principal, profile, entity, value="Synthetic net 30")
    case = str(queued["review_case_id"])
    # The same fact goes live by explicit create meanwhile (no proposal check there).
    review.create(
        principal,
        "klp04-equal-live",
        subject_id=entity,
        subject_kind=KnowledgeSubjectKind.ENTITY,
        predicate=PAYMENT,
        value="Synthetic net 30",
    )
    before = counts(review.engine, principal)
    error = review.decide_error(principal, case)
    assert error["code"] == "conflict"
    assert error["safe_details"] == ["duplicate_fact"]
    assert decisions_of(review.engine, case) == []
    assert counts(review.engine, principal) == before
    assert proposal_of(review.engine, case)["state"] == "needs_review"


def test_an_archived_cited_capture_refuses_acceptance(review: ReviewRuntime) -> None:
    principal = new_principal()
    profile = review.profile(principal)
    capture_id, digest = review.capture(principal, "cited")
    queued = review.queue(
        principal,
        profile,
        principal,
        predicate=POLICY,
        subject_kind=KnowledgeSubjectKind.PRINCIPAL,
        value="Synthetic badge policy",
        evidence=(external("obj-1"), capture_evidence(capture_id, digest, "supporting")),
    )
    case = str(queued["review_case_id"])
    archive_capture(review, principal, capture_id)
    error = review.decide_error(principal, case)
    assert error["code"] == "denied"
    assert error["safe_details"] == ["capture_withdrawn"]
    assert decisions_of(review.engine, case) == []
    assert assertion_count(review.engine, principal) == 0
    # A non-promoting disposition needs no Capture fence (R6 8.2).
    assert review.decide(principal, case, Disposition.REJECT)["proposal_state"] == "rejected"


def test_a_subject_entity_no_longer_canonical_refuses_acceptance(review: ReviewRuntime) -> None:
    principal, entity, case = _queued(review)
    review.archive_entity(principal, entity)
    error = review.decide_error(principal, case)
    assert error["code"] == "denied"
    assert error["safe_details"] == ["subject"]
    assert decisions_of(review.engine, case) == []
    assert assertion_count(review.engine, principal) == 0
    invalidated = review.decide(principal, case, Disposition.INVALIDATE)
    assert invalidated["proposal_state"] == "invalidated"


def test_a_retired_predicate_head_refuses_promotion_but_not_rejection(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    with review.engine.begin() as connection:
        head = connection.execute(
            text(
                "SELECT max(predicate_version) FROM knowledge.knowledge_assertion_predicates "
                "WHERE predicate_code = :c"
            ),
            {"c": PAYMENT},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertion_predicates SELECT predicate_code, "
                ":v, 'retired', value_type, cardinality, temporal_semantics, qualifier_rule, "
                "allowed_subject_kinds, allowed_entity_types, canonical_owner, "
                "autonomous_admission_policy, review_requirement, consequential_class, "
                "normalization_rule, classification_floor, conflict_rule, "
                "minimum_evidence_authority, fingerprint_version, now() "
                "FROM knowledge.knowledge_assertion_predicates "
                "WHERE predicate_code = :c AND predicate_version = :h"
            ),
            {"c": PAYMENT, "v": int(head) + 1, "h": int(head)},
        )
    error = review.decide_error(principal, case)
    assert error["code"] == "invalid_request"
    assert error["safe_details"] == ["kinds"]
    assert decisions_of(review.engine, case) == []
    assert review.decide(principal, case, Disposition.REJECT)["proposal_state"] == "rejected"


def test_a_foreign_case_is_not_found_exactly_as_an_unknown_one(review: ReviewRuntime) -> None:
    _owner, _entity, case = _queued(review)
    stranger = new_principal()
    foreign = without_correlation(review.decide_error(stranger, case))
    unknown = without_correlation(
        review.decide_error(stranger, issue_identifier(IdKind.REVIEW_CASE))
    )
    assert foreign == unknown
    assert foreign["code"] == "not_found"
    assert foreign["safe_details"] == ["review_case_id"]
    assert decisions_of(review.engine, case) == []
    assert review.knowledge_cases(stranger) == []


# ---- KLP-AC-114 (database half): the CHECKs behind the service rule -------------------


@pytest.mark.parametrize(
    ("authority", "channel", "client", "disposition", "refused"),
    [
        ("ordinary_reviewer", "local_unattested", None, "accept", True),
        ("ordinary_reviewer", "remote_interactive", CHATLLM_CLIENT, "correct_and_accept", True),
        ("ordinary_reviewer", "remote_interactive", CHATLLM_CLIENT, "reject", False),
        ("local_operator", "remote_interactive", None, "reject", True),
        ("remote_operator_attested", "remote_operator_review", None, "reject", True),
        ("ordinary_reviewer", "local_unattested", CHATLLM_CLIENT, "defer", True),
        ("local_operator", "local_cli", None, "accept", False),
    ],
    ids=[
        "ordinary-accept",
        "ordinary-correct",
        "ordinary-reject-control",
        "operator-remote-channel",
        "attested-without-client",
        "unattested-with-client",
        "operator-accept-control",
    ],
)
def test_the_decision_checks_refuse_an_ordinary_acceptance_and_a_mismatched_channel(
    review: ReviewRuntime,
    authority: str,
    channel: str,
    client: str | None,
    disposition: str,
    refused: bool,
) -> None:
    _principal, _entity, case = _queued(review)
    insert = text(
        "INSERT INTO knowledge.knowledge_assertion_review_decisions (principal_id, "
        "decision_id, review_case_id, proposal_id, review_requirement, decision_sequence, "
        "disposition, correction_patch, authenticated_client_id, decision_channel, "
        "operator_authority_class, correlation_id, audit_id, created_at) SELECT principal_id, "
        ":d, review_case_id, proposal_id, review_requirement, 1, :disposition, "
        "CAST(:patch AS jsonb), :client, :channel, :authority, :corr, :audit, now() "
        "FROM knowledge.knowledge_assertion_proposals WHERE review_case_id = :c"
    )
    values = {
        "d": issue_identifier(IdKind.KNOWLEDGE_ASSERTION_REVIEW_DECISION),
        "disposition": disposition,
        "patch": '{"value": "x"}' if disposition == "correct_and_accept" else None,
        "client": client,
        "channel": channel,
        "authority": authority,
        "corr": issue_identifier(IdKind.CORRELATION),
        "audit": issue_identifier(IdKind.AUDIT),
        "c": case,
    }
    if refused:
        with pytest.raises(IntegrityError), review.engine.begin() as connection:
            connection.execute(insert, values)
        assert decisions_of(review.engine, case) == []
    else:
        with review.engine.begin() as connection:
            connection.execute(insert, values)
        assert len(decisions_of(review.engine, case)) == 1
