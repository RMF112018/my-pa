"""KLP-WP-03: the Knowledge Assertion repository on a real database (KLP-AC-148).

Marked `database` (auto `database_clone`) and routed to `database-current-head`.
Every write goes through `ApplicationService.invoke` on the production SQL unit
of work, so what is checked is the committed Knowledge rows next to the committed
feed.

* **KLP-AC-148** -- an explicit create of an exact live duplicate returns
  `duplicate_existing` naming the existing assertion and writes *only* its own
  completed submission row: zero evidence, link, mutation, classification or
  Record Event rows.
* A first create writes one submission, one assertion (`principal_asserted`,
  `active`, version 1, never `synthetic_test`), one `create` mutation, the
  cited evidence/link rows and exactly one Record Event.
* The explicit-create admissibility rulings (DEV-02..DEV-06): consequential or
  operator-review predicates and external/counterevidence citations are refused
  with no row; a domain-owned predicate completes `domain_owned_no_intake`; a
  non-canonical subject is a born-completed `refused/subject_not_canonical` row
  that satisfies every R6 section 11 CHECK and replays.

This module also holds the small harness every KLP-WP-03 database module
imports. Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, func, select, text

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    Command,
    CreateCapture,
    CreateEntity,
    CreateKnowledgeAssertion,
    CreateProject,
    CreateRelationshipMemory,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.domain.relationship.entity import EntityType
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.tables import (
    capture_versions,
    knowledge_assertion_evidence_links,
    knowledge_assertion_mutations,
    knowledge_assertion_submissions,
    knowledge_assertions,
    knowledge_evidence_refs,
    knowledge_submission_evidence,
    record_events,
    relationship_memory_versions,
)
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

WHEN: Final = datetime(2026, 10, 4, 12, tzinfo=UTC)
LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)
#: Seed S3 (`policy.requirement`): Knowledge-owned, multi_value, requires_review,
#: consequential none, subjects {principal, project} -- admissible to explicit create.
POLICY: Final = "policy.requirement"
#: Seed S2: Knowledge-owned, organization entities only.
OPERATING: Final = "organization.operating_requirement"
#: Seed S4: Knowledge-owned, historical.
LESSON: Final = "process.lesson_learned"
#: Seed S7: consequential, requires_operator -- refused for explicit create.
FINANCIAL: Final = "project.financial_fact"
#: Seed S5: canonical owner continuity_decision -- domain-owned.
DECISION: Final = "project.decision"
#: The tables an explicit create may write.
KNOWLEDGE_TABLES: Final = (
    knowledge_assertion_submissions,
    knowledge_assertions,
    knowledge_assertion_mutations,
    knowledge_assertion_evidence_links,
    knowledge_evidence_refs,
    knowledge_submission_evidence,
)


def new_principal() -> str:
    return issue_identifier(IdKind.PRINCIPAL)


class KnowledgeRuntime:
    """`ApplicationService` over the production SQL unit of work, Knowledge plane on."""

    def __init__(
        self,
        url: str,
        *,
        knowledge_enabled: bool = True,
        discovery_client_ids: frozenset[str] = frozenset(),
        relationship_intelligence: bool = True,
    ) -> None:
        self.engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(
                self.engine,
                audit=audit,
                relationship_memory_enabled=True,
                relationship_intelligence_enabled=True,
            )

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            clock=lambda: WHEN,
            relationship_intelligence_enabled=relationship_intelligence,
            relationship_intelligence_writes_enabled=True,
            relationship_memory_enabled=True,
            knowledge_assertions_enabled=knowledge_enabled,
            # KLP-WP-04 slice B2: the autonomous-submit tests bind a discovery client.
            knowledge_discovery_client_ids=discovery_client_ids,
            # KLP-WP-04 slice B2: a task to route a critical date to.
            task_management_unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(self.engine),
        )

    def close(self) -> None:
        self.engine.dispose()
        self.audit_engine.dispose()

    def invoke(
        self,
        command: Command,
        *,
        principal_id: str,
        transport: CaptureTransport = CaptureTransport.LOCAL,
        grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
        client_id: str | None = None,
    ) -> ResponseEnvelope:
        capability = command.capability
        purpose = sorted(permitted_purposes(capability))[0]
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=purpose,
                principal_id=principal_id,
                requested_at=WHEN,
            ),
            command,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            transport=transport,
            capability_grants=grants,
            authenticated_client_id=client_id,
        )

    def ok(self, command: Command, *, principal_id: str, **remote: object) -> dict[str, Any]:
        response = self.invoke(command, principal_id=principal_id, **remote)
        assert response.error is None, response.error
        assert response.result is not None
        return dict(response.result)

    def error(self, command: Command, *, principal_id: str, **remote: object) -> dict[str, Any]:
        response = self.invoke(command, principal_id=principal_id, **remote)
        assert response.error is not None, response.result
        return response.error.model_dump(mode="json")

    # -- seeding through the owning planes' own writers --------------------

    def project(self, principal_id: str, key: str) -> str:
        created = self.ok(
            CreateProject(name=f"Synthetic project {key}", idempotency_key=f"prj-{key}"),
            principal_id=principal_id,
        )
        return str(_find_id(created, "prj_"))

    def entity(
        self, principal_id: str, key: str, entity_type: EntityType = EntityType.ORGANIZATION
    ) -> str:
        created = self.ok(
            CreateEntity(
                entity_type=entity_type,
                display_name=f"Synthetic org {key}",
                idempotency_key=f"ent-{key}",
            ),
            principal_id=principal_id,
        )
        return str(_find_id(created, "ent_"))

    def capture(self, principal_id: str, key: str) -> tuple[str, str]:
        """A capture and the `content_sha256` of its first version."""
        created = self.ok(
            CreateCapture(text=f"Synthetic knowledge evidence {key}", idempotency_key=f"cap-{key}"),
            principal_id=principal_id,
        )
        capture_id = str(created["capture_id"])
        with self.engine.connect() as connection:
            digest = connection.execute(
                select(capture_versions.c.content_sha256).where(
                    capture_versions.c.capture_id == capture_id
                )
            ).scalar_one()
        return capture_id, str(digest)

    def memory(self, principal_id: str, entity_id: str, key: str) -> tuple[str, str]:
        """A Relationship Memory and the `statement_sha256` of its version."""
        created = self.ok(
            CreateRelationshipMemory(
                entity_id=entity_id,
                statement=f"Synthetic memory statement {key}",
                idempotency_key=f"mem-{key}",
            ),
            principal_id=principal_id,
        )
        memory_id = str(_find_id(created, "mem_"))
        with self.engine.connect() as connection:
            digest = connection.execute(
                select(relationship_memory_versions.c.statement_sha256).where(
                    relationship_memory_versions.c.memory_id == memory_id
                )
            ).scalar_one()
        return memory_id, str(digest)

    def create(
        self,
        principal_id: str,
        key: str,
        *,
        subject_id: str | None = None,
        subject_kind: KnowledgeSubjectKind = KnowledgeSubjectKind.PRINCIPAL,
        predicate: str = POLICY,
        value: str = "Synthetic requirement value",
        evidence: tuple[dict[str, object], ...] = (),
        **remote: object,
    ) -> dict[str, Any]:
        return self.ok(
            create_command(
                key,
                subject_id=principal_id if subject_id is None else subject_id,
                subject_kind=subject_kind,
                predicate=predicate,
                value=value,
                evidence=evidence,
            ),
            principal_id=principal_id,
            **remote,
        )


def create_command(
    key: str,
    *,
    subject_id: str,
    subject_kind: KnowledgeSubjectKind = KnowledgeSubjectKind.PRINCIPAL,
    predicate: str = POLICY,
    value: str = "Synthetic requirement value",
    evidence: tuple[dict[str, object], ...] = (),
) -> CreateKnowledgeAssertion:
    return CreateKnowledgeAssertion(
        subject_kind=subject_kind,
        subject_id=subject_id,
        predicate_code=predicate,
        value=value,
        idempotency_key=key,
        evidence=evidence,
    )


def capture_evidence(capture_id: str, digest: str, role: str = "direct") -> dict[str, object]:
    return {
        "identity_kind": "capture",
        "capture_id": capture_id,
        "content_hash": digest,
        "role": role,
    }


def memory_evidence(memory_id: str, digest: str, role: str = "supporting") -> dict[str, object]:
    return {
        "identity_kind": "relationship_memory",
        "relationship_memory_id": memory_id,
        "content_hash": digest,
        "role": role,
    }


def _find_id(document: object, prefix: str) -> str | None:
    if isinstance(document, str) and document.startswith(prefix):
        return document
    if isinstance(document, dict):
        for value in document.values():
            found = _find_id(value, prefix)
            if found is not None:
                return found
    if isinstance(document, list):
        for value in document:
            found = _find_id(value, prefix)
            if found is not None:
                return found
    return None


def counts(engine: Engine, principal_id: str) -> dict[str, int]:
    """Row counts of every table an explicit create may write, plus the feed."""
    with engine.connect() as connection:
        found = {
            table.name: int(
                connection.execute(
                    select(func.count()).where(table.c.principal_id == principal_id)
                ).scalar_one()
            )
            for table in KNOWLEDGE_TABLES
        }
        found["record_events"] = int(
            connection.execute(
                select(func.count()).where(
                    record_events.c.principal_id == principal_id,
                    record_events.c.record_family == "knowledge_assertion",
                )
            ).scalar_one()
        )
    return found


def knowledge_events(engine: Engine, principal_id: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(record_events)
                .where(
                    record_events.c.principal_id == principal_id,
                    record_events.c.record_family == "knowledge_assertion",
                )
                .order_by(record_events.c.sequence_number)
            ).mappings()
        ]


def submission_row(engine: Engine, submission_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(
            connection.execute(
                select(knowledge_assertion_submissions).where(
                    knowledge_assertion_submissions.c.submission_id == submission_id
                )
            )
            .mappings()
            .one()
        )


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[KnowledgeRuntime]:
    composed = KnowledgeRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


# ---- a first create -------------------------------------------------------------


def test_a_first_create_writes_one_assertion_mutation_links_and_event(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    capture_id, digest = runtime.capture(principal, "first")
    result = runtime.create(
        principal, "klp03-first", evidence=(capture_evidence(capture_id, digest),)
    )
    assert result["outcome"] == "direct_created"
    assert result["reason"] == "created"
    assert result["canonical_owner"] == "knowledge_assertion"
    assert result["assertion_version"] == 1
    assert result["current_lifecycle"] == "active"
    assert counts(runtime.engine, principal) == {
        "knowledge_assertion_submissions": 1,
        "knowledge_assertions": 1,
        "knowledge_assertion_mutations": 1,
        "knowledge_assertion_evidence_links": 1,
        "knowledge_evidence_refs": 1,
        "knowledge_submission_evidence": 1,
        "record_events": 1,
    }
    with runtime.engine.connect() as connection:
        row = (
            connection.execute(
                select(knowledge_assertions).where(
                    knowledge_assertions.c.assertion_id == result["assertion_id"]
                )
            )
            .mappings()
            .one()
        )
    assert row["epistemic_status"] == "principal_asserted"
    assert row["lifecycle"] == "active"
    assert row["version"] == 1
    assert row["classification"] == "private_local"
    assert row["origin_is_synthetic"] is False
    submission = submission_row(runtime.engine, result["submission_id"])
    assert submission["causal_depth"] == 0
    assert submission["causal_root_submission_id"] == result["submission_id"]
    assert submission["submission_state"] == "completed"


def test_an_evidence_less_create_stores_private_local_and_never_synthetic(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    result = runtime.create(principal, "klp03-bare")
    with runtime.engine.connect() as connection:
        classification = connection.execute(
            select(knowledge_assertions.c.classification).where(
                knowledge_assertions.c.assertion_id == result["assertion_id"]
            )
        ).scalar_one()
    assert classification == "private_local"


# ---- KLP-AC-148 ----------------------------------------------------------------


def test_an_exact_live_duplicate_writes_only_its_own_submission_row(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    capture_id, digest = runtime.capture(principal, "dup")
    first = runtime.create(principal, "klp03-dup-1")
    before = counts(runtime.engine, principal)
    # Same fact, a new key, and *new* evidence: still no enrichment.
    second = runtime.create(
        principal, "klp03-dup-2", evidence=(capture_evidence(capture_id, digest),)
    )
    after = counts(runtime.engine, principal)
    assert second["outcome"] == "duplicate_existing"
    assert second["reason"] == "exact_duplicate"
    assert second["assertion_id"] == first["assertion_id"]
    assert second["assertion_version"] == 1
    assert second["mutation_id"] is None
    assert second["current_lifecycle"] == "active"
    delta = {name: after[name] - before[name] for name in after}
    assert delta == {
        "knowledge_assertion_submissions": 1,
        "knowledge_assertions": 0,
        "knowledge_assertion_mutations": 0,
        "knowledge_assertion_evidence_links": 0,
        "knowledge_evidence_refs": 0,
        "knowledge_submission_evidence": 0,
        "record_events": 0,
    }
    with runtime.engine.connect() as connection:
        version, classification = connection.execute(
            select(knowledge_assertions.c.version, knowledge_assertions.c.classification).where(
                knowledge_assertions.c.assertion_id == first["assertion_id"]
            )
        ).one()
    assert (version, classification) == (1, "private_local")


def test_a_normalized_equal_value_is_the_same_duplicate(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    first = runtime.create(principal, "klp03-norm-1", value="Keep  the   gate\tlocked")
    second = runtime.create(principal, "klp03-norm-2", value=" Keep the gate locked ")
    assert second["outcome"] == "duplicate_existing"
    assert second["assertion_id"] == first["assertion_id"]


# ---- admissibility (DEV-02 .. DEV-06) --------------------------------------------


def test_a_consequential_operator_predicate_is_refused_with_no_row(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    project = runtime.project(principal, "fin")
    error = runtime.error(
        create_command(
            "klp03-fin",
            subject_id=project,
            subject_kind=KnowledgeSubjectKind.PROJECT,
            predicate=FINANCIAL,
        ),
        principal_id=principal,
    )
    assert error["code"] == "invalid_request"
    assert "review_required" in error["safe_details"]
    assert counts(runtime.engine, principal) == dict.fromkeys(
        (*(table.name for table in KNOWLEDGE_TABLES), "record_events"), 0
    )


def test_the_operator_refusal_is_identical_for_absent_and_foreign_subjects(
    runtime: KnowledgeRuntime,
) -> None:
    owner, intruder = new_principal(), new_principal()
    foreign = runtime.project(owner, "fin-foreign")
    absent = issue_identifier(IdKind.PROJECT)
    answers = [
        runtime.error(
            create_command(
                f"klp03-fin-{index}",
                subject_id=subject,
                subject_kind=KnowledgeSubjectKind.PROJECT,
                predicate=FINANCIAL,
            ),
            principal_id=intruder,
        )
        for index, subject in enumerate((foreign, absent))
    ]
    for answer in answers:
        answer.pop("correlation_id", None)
    assert answers[0] == answers[1]


def test_an_unknown_predicate_is_refused_with_no_row(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    error = runtime.error(
        create_command("klp03-unknown", subject_id=principal, predicate="unknown.predicate"),
        principal_id=principal,
    )
    assert error["code"] == "invalid_request"
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 0


@pytest.mark.parametrize(
    "evidence",
    [
        {
            "identity_kind": "external_object",
            "source_profile_id": "kdsp_synthetic0001",
            "external_object_id": "message-1",
            "content_hash": "a" * 64,
            "role": "direct",
        },
        {
            "identity_kind": "capture",
            "capture_id": "cap_synthetic00000001",
            "content_hash": "a" * 64,
            "role": "counterevidence",
        },
    ],
    ids=["external_object", "counterevidence"],
)
def test_external_and_counterevidence_citations_are_refused_with_no_row(
    runtime: KnowledgeRuntime, evidence: dict[str, object]
) -> None:
    """DEV-06: refused at the command boundary, before any read or write."""
    principal = new_principal()
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.KNOWLEDGE_ASSERTIONS_CREATE.value,
            {
                "contract_version": "v1",
                "request_id": issue_identifier(IdKind.CORRELATION),
                "requested_at": WHEN.isoformat(),
                "principal_id": principal,
                "purpose": Purpose.KNOWLEDGE_ASSERTION_AUTHORING.value,
                "payload": {
                    "subject_kind": "principal",
                    "subject_id": principal,
                    "predicate_code": POLICY,
                    "value": "Synthetic value",
                    "idempotency_key": "klp03-evidence",
                    "evidence": [evidence],
                },
            },
        )
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 0


def test_a_domain_owned_predicate_completes_no_intake_without_an_assertion(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    project = runtime.project(principal, "decision")
    result = runtime.create(
        principal,
        "klp03-decision",
        subject_id=project,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        predicate=DECISION,
    )
    assert result["outcome"] == "domain_owned_no_intake"
    assert result["reason"] == "canonical_owner_no_intake"
    assert result["canonical_owner"] == "continuity_decision"
    assert result["assertion_id"] is None
    found = counts(runtime.engine, principal)
    assert found["knowledge_assertion_submissions"] == 1
    assert found["knowledge_assertions"] == 0
    assert found["record_events"] == 0


def test_a_non_canonical_subject_is_a_born_completed_refusal_that_replays(
    runtime: KnowledgeRuntime,
) -> None:
    """DEV-07 (ruling (f)): every section 11 CHECK holds on the refused row."""
    owner, caller = new_principal(), new_principal()
    foreign = runtime.project(owner, "foreign")
    command = create_command(
        "klp03-foreign",
        subject_id=foreign,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        predicate=LESSON,
    )
    first = runtime.ok(command, principal_id=caller)
    assert first["outcome"] == "refused"
    assert first["reason"] == "subject_not_canonical"
    row = submission_row(runtime.engine, first["submission_id"])
    assert row["submission_state"] == "completed"
    assert row["origin"] == "explicit_create"
    assert row["causal_depth"] == 0
    assert row["causal_root_submission_id"] == first["submission_id"]
    assert row["source_profile_id"] is None and row["external_run_id"] is None
    assert row["result_assertion_id"] is None
    # The four CHECKs, re-evaluated on the stored row by the database itself.
    with runtime.engine.connect() as connection:
        violated = connection.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conrelid = "
                "'knowledge.knowledge_assertion_submissions'::regclass AND contype = 'c' "
                "AND conname IN ('knowledge_submission_origin_shape', "
                "'knowledge_submission_causal_shape', "
                "'knowledge_submission_reason_matches_outcome', "
                "'knowledge_submission_explicit_create_is_a_root')"
            )
        ).scalars()
        names = sorted(violated)
        assert names == sorted(
            [
                "knowledge_submission_origin_shape",
                "knowledge_submission_causal_shape",
                "knowledge_submission_reason_matches_outcome",
                "knowledge_submission_explicit_create_is_a_root",
            ]
        )
        for name in names:
            definition = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name "
                    "AND conrelid = 'knowledge.knowledge_assertion_submissions'::regclass"
                ),
                {"name": name},
            ).scalar_one()
            check = definition.removeprefix("CHECK ")
            holds = connection.execute(
                text(
                    f"SELECT {check} FROM knowledge.knowledge_assertion_submissions "  # noqa: S608
                    "WHERE submission_id = :id"
                ),
                {"id": first["submission_id"]},
            ).scalar_one()
            assert holds is True, name
    # Same key and digest replays the refusal; a different digest conflicts.
    assert runtime.ok(command, principal_id=caller) == first
    conflict = runtime.error(
        create_command(
            "klp03-foreign",
            subject_id=foreign,
            subject_kind=KnowledgeSubjectKind.PROJECT,
            predicate=LESSON,
            value="A different value",
        ),
        principal_id=caller,
    )
    assert conflict["code"] == "conflict"
    assert "idempotency_conflict" in conflict["safe_details"]
    assert counts(runtime.engine, caller)["knowledge_assertion_submissions"] == 1


def test_absent_and_foreign_subjects_answer_byte_identically(runtime: KnowledgeRuntime) -> None:
    owner, caller = new_principal(), new_principal()
    foreign = runtime.project(owner, "foreign-bytes")
    absent = issue_identifier(IdKind.PROJECT)
    answers = []
    for subject in (foreign, absent):
        result = runtime.ok(
            create_command(
                f"klp03-bytes-{subject}",
                subject_id=subject,
                subject_kind=KnowledgeSubjectKind.PROJECT,
                predicate=LESSON,
            ),
            principal_id=caller,
        )
        result.pop("submission_id")
        answers.append(result)
    assert answers[0] == answers[1]


def test_a_foreign_citation_and_an_absent_one_are_the_same_not_found(
    runtime: KnowledgeRuntime,
) -> None:
    owner, caller = new_principal(), new_principal()
    capture_id, digest = runtime.capture(owner, "foreign-cite")
    answers = []
    for index, cited in enumerate(
        (
            capture_evidence(capture_id, digest),
            capture_evidence(issue_identifier(IdKind.CAPTURE), digest),
        )
    ):
        error = runtime.error(
            create_command(f"klp03-cite-{index}", subject_id=caller, evidence=(cited,)),
            principal_id=caller,
        )
        error.pop("correlation_id", None)
        answers.append(error)
    assert answers[0] == answers[1]
    assert answers[0]["code"] == "not_found"
    assert counts(runtime.engine, caller)["knowledge_assertion_submissions"] == 0


def test_an_entity_subject_must_be_an_allowed_active_entity_type(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    organization = runtime.entity(principal, "org")
    person = runtime.entity(principal, "person", EntityType.PERSON)
    admitted = runtime.create(
        principal,
        "klp03-org",
        subject_id=organization,
        subject_kind=KnowledgeSubjectKind.ENTITY,
        predicate=OPERATING,
    )
    assert admitted["outcome"] == "direct_created"
    refused = runtime.create(
        principal,
        "klp03-person",
        subject_id=person,
        subject_kind=KnowledgeSubjectKind.ENTITY,
        predicate=OPERATING,
    )
    assert (refused["outcome"], refused["reason"]) == ("refused", "subject_not_canonical")


def test_memory_evidence_takes_the_rank_max_class_of_the_memory(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    organization = runtime.entity(principal, "memory-org")
    memory_id, digest = runtime.memory(principal, organization, "cited")
    result = runtime.create(
        principal,
        "klp03-memory",
        subject_id=organization,
        subject_kind=KnowledgeSubjectKind.ENTITY,
        predicate=OPERATING,
        evidence=(memory_evidence(memory_id, digest),),
    )
    assert result["outcome"] == "direct_created"
    with runtime.engine.connect() as connection:
        evidence = connection.execute(
            select(
                knowledge_evidence_refs.c.identity_kind,
                knowledge_evidence_refs.c.content_origin,
                knowledge_evidence_refs.c.source_classification,
                knowledge_evidence_refs.c.excerpt,
            ).where(knowledge_evidence_refs.c.principal_id == principal)
        ).one()
    assert tuple(evidence) == ("relationship_memory", "relationship_memory", "private_local", None)


def test_the_plane_off_refuses_create_as_unsupported_and_writes_nothing(
    disposable_database: str,
) -> None:
    runtime = KnowledgeRuntime(disposable_database, knowledge_enabled=False)
    try:
        principal = new_principal()
        error = runtime.error(
            create_command("klp03-off", subject_id=principal), principal_id=principal
        )
        assert error["code"] == "unsupported"
        assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 0
    finally:
        runtime.close()
