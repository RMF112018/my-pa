"""KLP-WP-04: autonomous submit outcomes on a real database (slice B2).

KLP-AC-026, 027, 028, 029, 031, 117 and 118. Marked `database` (auto
`database_clone`), routed to `database-current-head`.

Every submit goes through `ApplicationService.invoke` as a bound discovery
client (REMOTE_CLIENT transport, the client in the discovery allowlist, the
submit grant), against a source profile provisioned by the production
maintenance writer. Direct SQL appears only to read rows back, to seed a
predicate head version the frozen seeds do not provide (a direct-admissible
single-current code: the registry has no runtime writer, KLP-AC-083), and to
inject a failure for the rollback proof.

* KLP-AC-026: a non-canonical subject (absent entity, wrong entity type,
  entity plane not composed) never yields `direct_created`: it is refused
  `subject_not_canonical`; a name is not even a well-formed subject.
* KLP-AC-027: one canonical fact submitted twice under different spellings and
  candidate keys leaves one live assertion; a non-canonical alias is refused,
  never deduplicated against the canonical subject.
* KLP-AC-028: new evidence for an exact live duplicate enriches it (links +
  one version bump, factual columns unchanged); nothing new is
  `duplicate_existing`; explicit create never enriches; a superseded
  fingerprint is never enriched.
* KLP-AC-029 / 031 / 117 / 118: the single-current slot under any predicate
  version; governed supersession only when effective_from is known, not
  regressing, not future-dated and the predecessor carries no counterevidence
  (else Review, never 23505); predecessor demoted before the successor in one
  transaction; A -> B -> A ends with one live A; an injected failure after the
  demotion rolls everything back; explicit create answers `conflict`.

Every identity here is synthetic. This module also holds the submit harness the
other KLP-WP-04 slice B2 modules import.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, func, select, text

from my_pa.application.commands import ArchiveCapture, SubmitKnowledgeAssertion
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.domain.relationship.entity import EntityType
from my_pa.infrastructure.persistence.tables import (
    knowledge_assertion_evidence_links,
    knowledge_assertion_mutations,
    knowledge_assertion_proposals,
    knowledge_assertion_subject_locks,
    knowledge_assertions,
    knowledge_evidence_refs,
)
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction
from tests.database.test_knowledge_assertion_repository import (
    OPERATING,
    WHEN,
    KnowledgeRuntime,
    capture_evidence,
    counts,
    create_command,
    knowledge_events,
    new_principal,
    submission_row,
)

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

CLIENT: Final = "klp04-synthetic-discovery-client"
OTHER_CLIENT: Final = "klp04-synthetic-discovery-client-2"
#: S1 -- single_current; the tests add a direct-admissible head version.
PAYMENT: Final = "organization.payment_terms"
SUBMIT_GRANTS: Final = frozenset(
    {(Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION)}
)
#: A synthetic 32-octet checkpoint signing key (KLP-WP-04 slice B3; never a real key).
CHECKPOINT_SIGNING_KEY: Final = b"klp04-synthetic-checkpoint-key-0"
EARLY: Final = WHEN - timedelta(days=30)
LATER: Final = WHEN - timedelta(days=10)
LATEST: Final = WHEN - timedelta(days=1)


def content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def external(
    object_id: str,
    *,
    version: str | None = "v1",
    role: str = "direct",
    excerpt: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "identity_kind": "external_object",
        "external_object_id": object_id,
        "content_hash": content_hash(object_id, version or ""),
        "role": role,
    }
    if version is not None:
        entry["external_version_id"] = version
    if excerpt is not None:
        entry["excerpt"] = excerpt
    return entry


class SubmitRuntime(KnowledgeRuntime):
    """`KnowledgeRuntime` with the discovery allowlist bound and submit helpers."""

    def __init__(
        self,
        url: str,
        *,
        relationship_intelligence: bool = True,
        seal_version: int = 1,
        signing_key: bytes = CHECKPOINT_SIGNING_KEY,
        operator_review_client_ids: frozenset[str] = frozenset(),
        identity_correction: bool = False,
        manager_client_ids: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(
            url,
            discovery_client_ids=frozenset({CLIENT, OTHER_CLIENT}),
            operator_review_client_ids=operator_review_client_ids,
            manager_client_ids=manager_client_ids,
            identity_correction=identity_correction,
            relationship_intelligence=relationship_intelligence,
            # KLP-WP-04 slice B3: a bound discovery list requires the seal.
            checkpoint_signing_key=signing_key,
            checkpoint_seal_version=seal_version,
        )

    def profile(
        self,
        principal_id: str,
        *,
        origin: str = "outlook_mail",
        scope: str = "scope-a",
        client: str = CLIENT,
        direct: bool = True,
        ceiling: str = "authoritative_source",
    ) -> str:
        """Provision one source profile through the production maintenance writer."""
        with knowledge_maintenance_transaction(self.engine) as repository:
            change = repository.apply_source_profile(
                principal_id,
                authenticated_client_id=client,
                origin_system=origin,
                scope_digest=content_hash("scope", origin, scope, client),
                authority_ceiling=ceiling,
                direct_admission_enabled=direct,
                read_only_proof_state="proven" if direct else "unproven",
                at=WHEN,
            )
        return change.profile.source_profile_id

    def disable(self, principal_id: str, profile: str) -> None:
        with knowledge_maintenance_transaction(self.engine) as repository:
            assert repository.disable_source_profile(principal_id, profile, at=WHEN) is not None

    def submit_command(
        self,
        principal_id: str,
        profile: str,
        *,
        subject_id: str,
        run: str = "run-1",
        candidate: str = "cand-1",
        subject_kind: KnowledgeSubjectKind = KnowledgeSubjectKind.ENTITY,
        predicate: str = OPERATING,
        value: str = "Synthetic operating requirement",
        evidence: tuple[dict[str, object], ...] | None = None,
        triggers: tuple[str, ...] = (),
        owner_ref: dict[str, str] | None = None,
        effective_from: datetime | None = None,
        qualifier: dict[str, object] | None = None,
    ) -> SubmitKnowledgeAssertion:
        del principal_id
        return SubmitKnowledgeAssertion(
            source_profile_id=profile,
            external_run_id=run,
            external_candidate_id=candidate,
            subject_kind=subject_kind,
            subject_id=subject_id,
            predicate_code=predicate,
            value=value,
            evidence=(external("obj-1"),) if evidence is None else evidence,
            owner_ref=owner_ref,
            qualifier=qualifier,
            effective_from=effective_from,
            trigger_event_ids=triggers,
        )

    def submit(
        self,
        principal_id: str,
        profile: str,
        *,
        client: str = CLIENT,
        **fields: Any,  # noqa: ANN401 - the submit_command keywords
    ) -> dict[str, Any]:
        return self.ok(
            self.submit_command(principal_id, profile, **fields),
            principal_id=principal_id,
            transport=CaptureTransport.REMOTE_CLIENT,
            grants=SUBMIT_GRANTS,
            client_id=client,
        )

    def submit_error(
        self,
        principal_id: str,
        profile: str,
        *,
        client: str = CLIENT,
        **fields: Any,  # noqa: ANN401 - the submit_command keywords
    ) -> dict[str, Any]:
        return self.error(
            self.submit_command(principal_id, profile, **fields),
            principal_id=principal_id,
            transport=CaptureTransport.REMOTE_CLIENT,
            grants=SUBMIT_GRANTS,
            client_id=client,
        )


def archive_capture(runtime: KnowledgeRuntime, principal_id: str, capture_id: str) -> None:
    """Archive a capture through its own production writer (`capture.archive`)."""
    runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key=f"klp04-archive-{capture_id}",
            reason="Synthetic knowledge archive",
        ),
        principal_id=principal_id,
    )


def add_direct_payment_head(engine: Engine) -> int:
    """Seed the next `organization.payment_terms` head: direct-admissible, non-consequential.

    The frozen S1 seed never direct-admits; the registry has no runtime writer,
    so the database test inserts the next version itself (structure unchanged,
    as the structure guard requires).
    """
    with engine.begin() as connection:
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
                ":v, admission_state, value_type, cardinality, temporal_semantics, "
                "qualifier_rule, allowed_subject_kinds, allowed_entity_types, canonical_owner, "
                "'authoritative_source', 'requires_review', 'none', normalization_rule, "
                "classification_floor, conflict_rule, minimum_evidence_authority, "
                "fingerprint_version, now() FROM knowledge.knowledge_assertion_predicates "
                "WHERE predicate_code = :c AND predicate_version = :h"
            ),
            {"c": PAYMENT, "v": int(head) + 1, "h": int(head)},
        )
    return int(head) + 1


def assertion(engine: Engine, assertion_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(
            connection.execute(
                select(knowledge_assertions).where(
                    knowledge_assertions.c.assertion_id == assertion_id
                )
            )
            .mappings()
            .one()
        )


def live_assertions(engine: Engine, principal_id: str, predicate: str) -> list[dict[str, Any]]:
    a = knowledge_assertions
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(a)
                .where(
                    a.c.principal_id == principal_id,
                    a.c.predicate_code == predicate,
                    a.c.lifecycle.in_(["active", "revalidation_required"]),
                )
                .order_by(a.c.created_at)
            ).mappings()
        ]


def links_of(engine: Engine, assertion_id: str) -> set[tuple[str, str]]:
    links = knowledge_assertion_evidence_links
    with engine.connect() as connection:
        return {
            (row.evidence_ref_id, row.evidence_role)
            for row in connection.execute(
                select(links.c.evidence_ref_id, links.c.evidence_role).where(
                    links.c.assertion_id == assertion_id
                )
            )
        }


def mutation_kinds(engine: Engine, assertion_id: str) -> list[str]:
    m = knowledge_assertion_mutations
    with engine.connect() as connection:
        return list(
            connection.execute(
                select(m.c.mutation_kind)
                .where(m.c.assertion_id == assertion_id)
                .order_by(m.c.new_version)
            ).scalars()
        )


def table_count(engine: Engine, table: Any, principal_id: str) -> int:  # noqa: ANN401
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).where(table.c.principal_id == principal_id)
            ).scalar_one()
        )


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


# ---- direct_created --------------------------------------------------------------


def test_a_direct_admissible_candidate_is_created_source_observed(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "direct")
    result = runtime.submit(
        principal, profile, subject_id=org, evidence=(external("obj-1", excerpt="Synthetic."),)
    )
    assert result["outcome"] == "direct_created", result
    assert result["reason"] == "created"
    assert result["current_lifecycle"] == "active"
    assert result["proposal_id"] is None
    row = assertion(runtime.engine, result["assertion_id"])
    assert row["epistemic_status"] == "source_observed"
    assert row["classification"] == "private_local"
    assert row["origin_is_synthetic"] is False
    submission = submission_row(runtime.engine, result["submission_id"])
    assert submission["origin"] == "autonomous_submit"
    assert submission["causal_depth"] == 0
    assert submission["causal_root_submission_id"] == result["submission_id"]
    assert submission["authenticated_client_id"] == CLIENT
    assert submission["source_profile_id"] == profile
    with runtime.engine.connect() as connection:
        evidence = (
            connection.execute(
                select(knowledge_evidence_refs).where(
                    knowledge_evidence_refs.c.principal_id == principal
                )
            )
            .mappings()
            .one()
        )
    assert evidence["content_origin"] == "external_source"
    assert evidence["excerpt"] == "Synthetic."
    assert evidence["excerpt_sha256"] == hashlib.sha256(b"Synthetic.").hexdigest()
    events = knowledge_events(runtime.engine, principal)
    assert [(e["event_kind"], e["actor_class"], e["authority"]) for e in events] == [
        ("created", "assistant", "source_backed_assertion")
    ]
    assert events[0]["source_capability"] == "knowledge.assertions.submit"
    assert events[0]["source_receipt_id"] == result["mutation_id"]


def test_a_never_admitting_predicate_is_queued_for_review_without_an_event(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "review")
    result = runtime.submit(principal, profile, subject_id=org, predicate=PAYMENT)
    assert result["outcome"] == "review_queued", result
    assert result["reason"] == "requires_operator"
    with runtime.engine.connect() as connection:
        proposal = (
            connection.execute(
                select(knowledge_assertion_proposals).where(
                    knowledge_assertion_proposals.c.proposal_id == result["proposal_id"]
                )
            )
            .mappings()
            .one()
        )
    assert proposal["review_case_id"] == result["review_case_id"]
    assert proposal["state"] == "needs_review"
    assert proposal["risk_class"] == "high"
    assert proposal["classification"] == "private_local"
    assert table_count(runtime.engine, knowledge_assertions, principal) == 0
    assert knowledge_events(runtime.engine, principal) == []


# ---- KLP-AC-026 ------------------------------------------------------------------


def test_an_absent_or_wrong_type_entity_is_refused_subject_not_canonical(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    person = runtime.entity(principal, "person", EntityType.PERSON)
    absent = "ent_" + "A1b2C3d4E5f6G7h8"
    for candidate, subject in (("c-absent", absent), ("c-person", person)):
        result = runtime.submit(principal, profile, subject_id=subject, candidate=candidate)
        assert result["outcome"] == "refused", result
        assert result["reason"] == "subject_not_canonical"
    assert table_count(runtime.engine, knowledge_assertions, principal) == 0
    assert table_count(runtime.engine, knowledge_assertion_proposals, principal) == 0


def test_an_entity_subject_without_the_entity_plane_never_reaches_a_write(
    disposable_database: str,
) -> None:
    """Relationship Intelligence not composed: the Knowledge plane is withheld whole.

    `_knowledge_plane` requires the entity plane, so the submit is `unsupported`
    before any read -- it can never yield `direct_created` (the persistence arm
    `SubjectResolution.PLANE_NOT_COMPOSED` is defence in depth behind it).
    """
    composed = SubmitRuntime(disposable_database, relationship_intelligence=False)
    try:
        principal = new_principal()
        profile = composed.profile(principal)
        error = composed.submit_error(principal, profile, subject_id="ent_" + "Z9y8X7w6V5u4T3s2")
        assert error["code"] == "unsupported"
        assert counts(composed.engine, principal)["knowledge_assertion_submissions"] == 0
    finally:
        composed.close()


def test_a_name_is_not_a_subject_and_writes_nothing(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    with pytest.raises(InvalidRequestError):
        runtime.submit_command(principal, profile, subject_id="Acme Synthetic Ltd")
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 0


# ---- KLP-AC-027 ------------------------------------------------------------------


def test_one_canonical_fact_under_two_spellings_leaves_one_live_assertion(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "spell")
    first = runtime.submit(
        principal, profile, subject_id=org, candidate="c1", value="Synthetic  requirement"
    )
    second = runtime.submit(
        principal, profile, subject_id=org, candidate="c2", value=" Synthetic requirement "
    )
    assert first["outcome"] == "direct_created"
    assert second["outcome"] == "duplicate_existing", second
    assert second["assertion_id"] == first["assertion_id"]
    assert len(live_assertions(runtime.engine, principal, OPERATING)) == 1
    # A non-canonical alias of the same organisation is refused, never deduplicated.
    alias = runtime.submit(
        principal,
        profile,
        subject_id="ent_" + "Q1w2E3r4T5y6U7i8",
        candidate="c3",
        value="Synthetic requirement",
    )
    assert alias["outcome"] == "refused"
    assert alias["reason"] == "subject_not_canonical"


# ---- KLP-AC-028 ------------------------------------------------------------------


def test_new_evidence_for_a_live_duplicate_enriches_without_a_factual_change(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "enrich")
    first = runtime.submit(principal, profile, subject_id=org, candidate="c1")
    before = assertion(runtime.engine, first["assertion_id"])
    enriched = runtime.submit(
        principal,
        profile,
        subject_id=org,
        candidate="c2",
        evidence=(external("obj-1"), external("obj-2", role="supporting")),
    )
    assert enriched["outcome"] == "duplicate_enriched", enriched
    assert enriched["reason"] == "evidence_enriched"
    assert enriched["assertion_id"] == first["assertion_id"]
    assert enriched["assertion_version"] == 2
    after = assertion(runtime.engine, first["assertion_id"])
    factual = (
        "value_text",
        "value_datetime",
        "qualifier_json",
        "effective_from",
        "effective_to",
        "assertion_fingerprint",
        "lifecycle",
        "epistemic_status",
        "classification",
    )
    assert {key: after[key] for key in factual} == {key: before[key] for key in factual}
    assert after["version"] == 2
    assert len(links_of(runtime.engine, first["assertion_id"])) == 2
    assert mutation_kinds(runtime.engine, first["assertion_id"]) == ["create", "evidence_enrich"]
    events = knowledge_events(runtime.engine, principal)
    assert [(e["event_kind"], e["record_version"]) for e in events] == [
        ("created", 1),
        ("updated", 2),
    ]
    # Re-citing exactly what is linked is a duplicate that writes only its row.
    before_counts = counts(runtime.engine, principal)
    again = runtime.submit(
        principal,
        profile,
        subject_id=org,
        candidate="c3",
        evidence=(external("obj-2", role="supporting"),),
    )
    assert again["outcome"] == "duplicate_existing"
    assert again["mutation_id"] is None
    after_counts = counts(runtime.engine, principal)
    assert after_counts["knowledge_assertion_submissions"] == (
        before_counts["knowledge_assertion_submissions"] + 1
    )
    assert {k: v for k, v in after_counts.items() if k != "knowledge_assertion_submissions"} == {
        k: v for k, v in before_counts.items() if k != "knowledge_assertion_submissions"
    }


def test_explicit_create_never_enriches(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    project = runtime.project(principal, "create-never-enriches")
    capture_one = runtime.capture(principal, "one")
    capture_two = runtime.capture(principal, "two")
    first = runtime.create(
        principal,
        "k1",
        subject_id=project,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        evidence=(capture_evidence(*capture_one),),
    )
    second = runtime.create(
        principal,
        "k2",
        subject_id=project,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        evidence=(capture_evidence(*capture_two),),
    )
    assert second["outcome"] == "duplicate_existing"
    assert assertion(runtime.engine, first["assertion_id"])["version"] == 1
    assert len(links_of(runtime.engine, first["assertion_id"])) == 1


# ---- KLP-AC-029 / 031 / 117 / 118 ------------------------------------------------------


def _payment(
    runtime: SubmitRuntime,
    principal: str,
    profile: str,
    org: str,
    value: str,
    candidate: str,
    effective_from: datetime | None,
    **fields: Any,  # noqa: ANN401 - the submit_command keywords
) -> dict[str, Any]:
    return runtime.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value=value,
        candidate=candidate,
        effective_from=effective_from,
        evidence=fields.pop("evidence", (external(f"inv-{candidate}"),)),
        **fields,
    )


def test_supersession_demotes_then_inserts_and_a_b_a_ends_with_one_live_a(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "abba")
    a1 = _payment(runtime, principal, profile, org, "Net 30", "a1", EARLY)
    assert a1["outcome"] == "direct_created", a1
    b = _payment(runtime, principal, profile, org, "Net 45", "b", LATER)
    assert b["outcome"] == "direct_superseded", b
    assert b["reason"] == "superseded"
    assert b["superseded_assertion_id"] == a1["assertion_id"]
    predecessor = assertion(runtime.engine, a1["assertion_id"])
    assert predecessor["lifecycle"] == "superseded"
    assert predecessor["version"] == 2
    successor = assertion(runtime.engine, b["assertion_id"])
    assert successor["supersedes_assertion_id"] == a1["assertion_id"]
    assert mutation_kinds(runtime.engine, a1["assertion_id"]) == [
        "create",
        "supersede_predecessor",
    ]
    assert mutation_kinds(runtime.engine, b["assertion_id"]) == ["supersede_successor"]
    a2 = _payment(runtime, principal, profile, org, "Net 30", "a2", LATEST)
    assert a2["outcome"] == "direct_superseded", a2
    live = live_assertions(runtime.engine, principal, PAYMENT)
    assert [row["assertion_id"] for row in live] == [a2["assertion_id"]]
    assert live[0]["value_text"] == "Net 30"
    # The superseded A (same fingerprint) was never enriched or revived.
    assert assertion(runtime.engine, a1["assertion_id"])["version"] == 2
    events = knowledge_events(runtime.engine, principal)
    assert [e["event_kind"] for e in events] == [
        "created",
        "state_changed",
        "created",
        "state_changed",
        "created",
    ]


def test_a_live_slot_under_an_older_predicate_version_still_occupies_it(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "versions")
    first = _payment(runtime, principal, profile, org, "Net 30", "v-1", EARLY)
    add_direct_payment_head(runtime.engine)
    second = _payment(runtime, principal, profile, org, "Net 60", "v-2", LATER)
    assert second["outcome"] == "direct_superseded", second
    assert second["superseded_assertion_id"] == first["assertion_id"]
    rows = live_assertions(runtime.engine, principal, PAYMENT)
    assert len(rows) == 1
    assert (
        rows[0]["predicate_version"]
        == assertion(runtime.engine, first["assertion_id"])["predicate_version"] + 1
    )


@pytest.mark.parametrize(
    ("label", "effective_from"),
    [
        ("regressing", EARLY - timedelta(days=1)),
        ("unknown", None),
        ("future", WHEN + timedelta(days=3)),
    ],
)
def test_a_blocked_supersession_is_queued_for_review_never_23505(
    runtime: SubmitRuntime, label: str, effective_from: datetime | None
) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, f"blocked-{label}")
    first = _payment(runtime, principal, profile, org, "Net 30", "p", EARLY)
    blocked = _payment(runtime, principal, profile, org, "Net 90", "q", effective_from)
    assert blocked["outcome"] == "review_queued", blocked
    assert assertion(runtime.engine, first["assertion_id"])["lifecycle"] == "active"
    assert len(live_assertions(runtime.engine, principal, PAYMENT)) == 1


def test_predecessor_counterevidence_blocks_supersession(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "counter")
    first = _payment(runtime, principal, profile, org, "Net 30", "p", EARLY)
    # Counterevidence linked to the live fact (through Review in later slices):
    # seeded as one link on the existing evidence row.
    with runtime.engine.begin() as connection:
        evidence = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertion_evidence_links (principal_id, "
                "assertion_id, evidence_ref_id, evidence_role, linked_by_mutation_id, "
                "created_at) VALUES (:p, :a, :e, 'counterevidence', :m, now())"
            ),
            {"p": principal, "a": first["assertion_id"], "e": evidence, "m": first["mutation_id"]},
        )
    blocked = _payment(runtime, principal, profile, org, "Net 90", "q", LATER)
    assert blocked["outcome"] == "review_queued", blocked
    assert assertion(runtime.engine, first["assertion_id"])["lifecycle"] == "active"


def test_a_failure_after_the_demotion_rolls_the_supersession_back(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "rollback")
    first = _payment(runtime, principal, profile, org, "Net 30", "p", EARLY)
    before = counts(runtime.engine, principal)
    with runtime.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION knowledge.klp04_test_refuse_successor() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN IF NEW.value_text = 'Net 120' THEN "
                "RAISE EXCEPTION 'synthetic successor failure'; END IF; RETURN NEW; END; $$"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER klp04_test_refuse_successor BEFORE INSERT ON "
                "knowledge.knowledge_assertions FOR EACH ROW EXECUTE FUNCTION "
                "knowledge.klp04_test_refuse_successor()"
            )
        )
    error = runtime.submit_error(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value="Net 120",
        candidate="r",
        effective_from=LATER,
        evidence=(external("inv-r"),),
    )
    assert error["code"] == "internal_error"
    row = assertion(runtime.engine, first["assertion_id"])
    assert row["lifecycle"] == "active"
    assert row["version"] == 1
    assert counts(runtime.engine, principal) == before


def test_explicit_create_against_an_occupied_slot_answers_conflict(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "create-conflict")
    _payment(runtime, principal, profile, org, "Net 30", "p", EARLY)
    capture = runtime.capture(principal, "create-conflict")
    created = runtime.ok(
        create_command(
            "k-conflict",
            subject_id=org,
            subject_kind=KnowledgeSubjectKind.ENTITY,
            predicate=PAYMENT,
            value="Net 15",
            evidence=(capture_evidence(*capture),),
        ),
        principal_id=principal,
    )
    assert created["outcome"] == "conflict", created
    assert created["reason"] == "incompatible_current_fact"
    assert len(live_assertions(runtime.engine, principal, PAYMENT)) == 1


def test_the_subject_lock_row_is_written_even_when_no_assertion_exists(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "lock-row")
    queued = runtime.submit(principal, profile, subject_id=org, predicate=PAYMENT)
    assert queued["outcome"] == "review_queued"
    assert table_count(runtime.engine, knowledge_assertion_subject_locks, principal) == 1
    assert table_count(runtime.engine, knowledge_assertions, principal) == 0
