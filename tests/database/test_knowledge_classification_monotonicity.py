"""KLP-WP-03: Knowledge classification is server-derived, floored and monotonic (DB).

KLP-AC-059 (closing), the cross-profile case of KLP-AC-138 and (KLP-WP-04
slice B1) the KLP-R6V-201 / KLP-R6V-202 cases of KLP-AC-152. Marked
`database` (auto `database_clone`), routed to `database-current-head`.

* `Classification.is_cloud_eligible` is unchanged: only `synthetic_test`.
* `synthetic_test` is refused by plain CHECKs on assertions, proposals and
  evidence unless the carried `origin_is_synthetic` / `source_is_synthetic` --
  copied through composite FKs from the source profile -- is true; and an
  explicit create can never carry a synthetic origin.
* An evidence-less explicit create stores `private_local`; a create citing a
  version stores the rank-max of every version of what it cites.
* Stored classes never decrease (assertion and evidence control triggers).
* KLP-AC-138: a restriction through one source profile withholds an assertion
  linked through *another* profile of the same `origin_system`, with no
  mutation fan-out; a new external version cannot launder it either.

KLP-WP-04 slice B2 adds the submit / successor cases (KLP-AC-095, 116, 138):

* a successor supersedes a restricted predecessor and is stored no less
  restrictive (rank-max with the predecessor floor); a raw successor insert
  below its predecessor is refused by the BEFORE INSERT trigger (23514);
* a submit through a synthetic profile carries `origin_is_synthetic` to the
  submission, evidence and assertion, while the predicate floor keeps the
  stored class at `private_local` (never `synthetic_test` above the floor);
* a submit-linked assertion is withheld remotely once a sibling of its object
  is restricted under another profile of the same origin system, with no
  mutation fan-out;
* KLP-R6V-201 at submit: re-citing an existing private external row whose
  object became restricted raises it and nulls its excerpt in the same UPDATE.

Direct SQL is used only for rows WP-03 has no writer for (source profiles,
external evidence, proposals) and for the refused writes themselves.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from my_pa.application.commands import ReadKnowledgeAssertion
from my_pa.domain.common.classification import Classification, is_cloud_eligible
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import knowledge_assertions, knowledge_evidence_refs
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction
from tests.database.test_knowledge_assertion_repository import (
    WHEN,
    KnowledgeRuntime,
    capture_evidence,
    new_principal,
)
from tests.database.test_knowledge_assertion_submissions import (
    PAYMENT,
    SubmitRuntime,
    add_direct_payment_head,
    external,
)
from tests.database.test_knowledge_evidence_availability import EXCERPT as _EXCERPT_B1
from tests.database.test_knowledge_evidence_availability import seed_external_excerpt
from tests.database.test_knowledge_source_profiles import provision, run_cli
from tests.security.test_knowledge_assertion_disclosure import (
    REMOTE,
    link,
    restricted_capture_version,
    seed_external,
    seed_profile,
)

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[KnowledgeRuntime]:
    composed = KnowledgeRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _class_of(runtime: KnowledgeRuntime, assertion_id: str) -> str:
    with runtime.engine.connect() as connection:
        return str(
            connection.execute(
                select(knowledge_assertions.c.classification).where(
                    knowledge_assertions.c.assertion_id == assertion_id
                )
            ).scalar_one()
        )


def test_cloud_eligibility_is_unchanged() -> None:
    assert [member for member in Classification if is_cloud_eligible(member)] == [
        Classification.SYNTHETIC_TEST
    ]


def test_an_evidence_less_create_is_private_local(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    created = runtime.create(principal, "klp03-floor")
    assert _class_of(runtime, created["assertion_id"]) == "private_local"


def test_a_create_takes_the_rank_max_of_every_cited_version(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    capture_id, digest = runtime.capture(principal, "rankmax")
    restricted_capture_version(runtime.engine, principal, capture_id)
    # Citing the *first* (private) version still stores the restricted rank-max.
    created = runtime.create(
        principal, "klp03-rankmax", evidence=(capture_evidence(capture_id, digest),)
    )
    assert _class_of(runtime, created["assertion_id"]) == "restricted_local"
    with runtime.engine.connect() as connection:
        stored, excerpt = connection.execute(
            select(
                knowledge_evidence_refs.c.source_classification,
                knowledge_evidence_refs.c.excerpt,
            ).where(knowledge_evidence_refs.c.principal_id == principal)
        ).one()
    assert (stored, excerpt) == ("restricted_local", None)


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "UPDATE knowledge.knowledge_assertions SET classification = 'synthetic_test', "
            "version = version + 1, updated_at = now() WHERE assertion_id = :a",
            "",
        ),
        (
            "UPDATE knowledge.knowledge_assertion_submissions SET origin_is_synthetic = true "
            "WHERE submission_id = :s",
            "",
        ),
    ],
    ids=["assertion-class-cannot-fall", "explicit-origin-is-never-synthetic"],
)
def test_a_lower_class_or_a_synthetic_explicit_origin_is_refused(
    runtime: KnowledgeRuntime, statement: str, constraint: str
) -> None:
    principal = new_principal()
    created = runtime.create(principal, "klp03-refuse")
    with pytest.raises(IntegrityError), runtime.engine.begin() as connection:
        connection.execute(
            text(statement), {"a": created["assertion_id"], "s": created["submission_id"]}
        )
    assert _class_of(runtime, created["assertion_id"]) == "private_local"


def test_synthetic_test_needs_a_synthetic_origin_on_every_table(
    runtime: KnowledgeRuntime,
) -> None:
    """Plain CHECKs, with the synthetic flag carried from the profile."""
    principal = new_principal()
    engine = runtime.engine
    profile = seed_profile(engine, principal, origin_system="outlook_mail", key="synthetic-1")
    with pytest.raises(IntegrityError, match="synthetic"):
        seed_external(engine, principal, profile, object_id="o-1", classification="synthetic_test")
    created = runtime.create(principal, "klp03-synthetic")
    with pytest.raises(IntegrityError, match="synthetic"), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertions (principal_id, assertion_id, "
                "subject_kind, subject_id, predicate_code, predicate_version, value_type, "
                "cardinality, temporal_semantics, qualifier_rule, value_text, "
                "normalized_value_sha256, fingerprint_version, assertion_fingerprint, "
                "epistemic_status, classification, origin_is_synthetic, lifecycle, "
                "origin_submission_id, created_at, updated_at) VALUES (:p, :a, 'principal', :p, "
                "'policy.requirement', 1, 'text', 'multi_value', 'observed_state', 'none', "
                "'Synthetic', :h, 1, :f, 'principal_asserted', 'synthetic_test', false, "
                "'archived', :s, now(), now())"
            ),
            {
                "p": principal,
                "a": issue_identifier(IdKind.KNOWLEDGE_ASSERTION),
                "h": "b" * 64,
                "f": "c" * 64,
                "s": created["submission_id"],
            },
        )
    with pytest.raises(IntegrityError, match="synthetic"), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertion_proposals (principal_id, proposal_id, "
                "review_case_id, origin_submission_id, origin_is_synthetic, subject_kind, "
                "subject_id, predicate_code, predicate_version, value_type, cardinality, "
                "temporal_semantics, qualifier_rule, value_text, normalized_value_sha256, "
                "fingerprint_version, proposal_fingerprint, classification, risk_class, "
                "review_requirement, state, created_at, updated_at) VALUES (:p, :x, :r, :s, "
                "false, 'principal', :p, 'policy.requirement', 1, 'text', 'multi_value', "
                "'observed_state', 'none', 'Synthetic', :h, 1, :f, 'synthetic_test', 'low', "
                "'requires_review', 'needs_review', now(), now())"
            ),
            {
                "p": principal,
                "x": issue_identifier(IdKind.KNOWLEDGE_ASSERTION_PROPOSAL),
                "r": issue_identifier(IdKind.REVIEW_CASE),
                "s": created["submission_id"],
                "h": "b" * 64,
                "f": "d" * 64,
            },
        )


def test_evidence_class_never_decreases(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    engine = runtime.engine
    profile = seed_profile(engine, principal, origin_system="outlook_mail", key="monotone")
    evidence = seed_external(
        engine, principal, profile, object_id="o-2", classification="restricted_local"
    )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_evidence_refs SET "
                "source_classification = 'private_local' WHERE evidence_ref_id = :e"
            ),
            {"e": evidence},
        )


def test_a_restriction_through_another_profile_withholds_without_fan_out(
    runtime: KnowledgeRuntime,
) -> None:
    """KLP-AC-138 cross-profile: no assertion row changes, yet the read is withheld."""
    principal = new_principal()
    engine = runtime.engine
    created = runtime.create(principal, "klp03-cross", value="Requirement cross profile")
    first = seed_profile(engine, principal, origin_system="sharepoint_documents", key="cross-1")
    link(engine, principal, created, seed_external(engine, principal, first, object_id="doc-9"))
    assert (
        runtime.invoke(
            ReadKnowledgeAssertion(assertion_id=created["assertion_id"]),
            principal_id=principal,
            **REMOTE,
        ).error
        is None
    )
    with engine.connect() as connection:
        before = connection.execute(
            text("SELECT version, classification FROM knowledge.knowledge_assertions")
        ).all()
    second = seed_profile(engine, principal, origin_system="sharepoint_documents", key="cross-2")
    seed_external(
        engine,
        principal,
        second,
        object_id="doc-9",
        version="v7",
        classification="restricted_local",
    )
    withheld = runtime.invoke(
        ReadKnowledgeAssertion(assertion_id=created["assertion_id"]),
        principal_id=principal,
        **REMOTE,
    )
    assert withheld.error is not None and withheld.error.code.value == "not_found"
    with engine.connect() as connection:
        after = connection.execute(
            text("SELECT version, classification FROM knowledge.knowledge_assertions")
        ).all()
    assert after == before, "remote safety must not depend on a mutation fan-out"
    local = runtime.invoke(
        ReadKnowledgeAssertion(assertion_id=created["assertion_id"]), principal_id=principal
    )
    assert local.error is None


# ---- KLP-WP-04 slice B1: KLP-R6V-201 / KLP-R6V-202 (KLP-AC-152 slice) ----------------
#
# R6V-201 (ii) -- a capture-kind row for an already restricted capture is born
# `restricted_local` with excerpt NULL -- is `test_a_create_takes_the_rank_max_of_
# every_cited_version` above. The external re-citation case of (i) needs the
# autonomous submit writer (slice B2); here its explicit-create analogue proves
# the same statement: a re-observation that raises an existing row redacts it in
# the same UPDATE instead of failing the CHECK.

_EXCERPT = "Synthetic excerpt held by a private row."


def _row(engine: Any, evidence_ref_id: str) -> dict[str, Any]:  # noqa: ANN401
    with engine.connect() as connection:
        return dict(
            connection.execute(
                select(knowledge_evidence_refs).where(
                    knowledge_evidence_refs.c.evidence_ref_id == evidence_ref_id
                )
            )
            .one()
            ._mapping
        )


def test_a_re_citation_after_restriction_raises_and_redacts_without_error(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    engine = runtime.engine
    capture_id, digest = runtime.capture(principal, "recite")
    evidence = issue_identifier(IdKind.KNOWLEDGE_EVIDENCE_REF)
    excerpt_sha256 = hashlib.sha256(_EXCERPT.encode()).hexdigest()
    # Setup only: an existing private canonical row for the cited version that
    # still holds an excerpt (no slice-B1 writer stores one for a capture).
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_evidence_refs (principal_id, evidence_ref_id, "
                "identity_kind, capture_id, content_hash, excerpt, excerpt_sha256, "
                "content_origin, source_classification, created_at, updated_at) VALUES "
                "(:p, :e, 'capture', :c, :h, :x, :xh, 'capture', 'private_local', now(), now())"
            ),
            {
                "p": principal,
                "e": evidence,
                "c": capture_id,
                "h": digest,
                "x": _EXCERPT,
                "xh": excerpt_sha256,
            },
        )
    restricted_capture_version(engine, principal, capture_id)
    created = runtime.create(
        principal, "klp04-recite", evidence=(capture_evidence(capture_id, digest),)
    )
    assert created["outcome"] == "direct_created"
    row = _row(engine, evidence)
    assert (row["source_classification"], row["excerpt"]) == ("restricted_local", None)
    assert (row["excerpt_sha256"], row["content_hash"]) == (excerpt_sha256, digest)
    assert _class_of(runtime, created["assertion_id"]) == "restricted_local"
    with engine.connect() as connection:
        rows = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).scalars()
        assert list(rows) == [evidence], "a re-citation creates no second evidence row"


def test_classify_evidence_raises_and_redacts_every_existing_sibling_in_one_run(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    """KLP-R6V-202 option A: siblings share the run and the sorted C4b set.

    Siblings are the same Principal's rows of the same `external_object_id`
    under any profile of the same `origin_system`, any version. Another origin
    system's row of the same id, and another object, are untouched.
    """
    principal = new_principal()
    engine = runtime.engine
    profile_a = provision(engine, principal, tmp_path, scope="synthetic-mailbox:a")
    profile_b = provision(engine, principal, tmp_path, scope="synthetic-mailbox:b")
    profile_c = provision(
        engine, principal, tmp_path, origin_system="teams_messages", scope="synthetic-team:c"
    )
    named = seed_external_excerpt(engine, principal, profile_a, object_id="synthetic-x")
    sibling = seed_external_excerpt(
        engine, principal, profile_b, object_id="synthetic-x", version="v2"
    )
    other_origin = seed_external_excerpt(engine, principal, profile_c, object_id="synthetic-x")
    other_object = seed_external_excerpt(engine, principal, profile_a, object_id="synthetic-y")
    via_sibling = runtime.create(principal, "klp04-via-sibling", value="Linked via sibling")
    link(engine, principal, via_sibling, sibling)

    code, lines = run_cli(
        engine,
        principal,
        "classify-evidence",
        "--evidence-ref",
        named,
        "--classification",
        "restricted_local",
    )
    assert code == 0, lines
    assert lines[0] == f"evidence_refs     {','.join(sorted([named, sibling]))}"
    for raised in (named, sibling):
        row = _row(engine, raised)
        assert (row["source_classification"], row["excerpt"]) == ("restricted_local", None)
        assert row["excerpt_sha256"] is not None
    for untouched in (other_origin, other_object):
        row = _row(engine, untouched)
        assert (row["source_classification"], row["excerpt"]) == ("private_local", _EXCERPT_B1)
    assert _class_of(runtime, via_sibling["assertion_id"]) == "restricted_local"


# ---- KLP-WP-04 slice B2: submit / successor cases ---------------------------------------


@pytest.fixture
def submitter(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def test_a_successor_of_a_restricted_predecessor_is_never_less_restrictive(
    submitter: SubmitRuntime,
) -> None:
    principal = new_principal()
    add_direct_payment_head(submitter.engine)
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "floor")
    first = submitter.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value="Net 30",
        candidate="f1",
        effective_from=WHEN - timedelta(days=9),
        evidence=(external("inv-f1"),),
    )
    with submitter.engine.connect() as connection:
        evidence = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).scalar_one()
    with knowledge_maintenance_transaction(submitter.engine) as repository:
        repository.classify_evidence_restricted(principal, evidence, at=WHEN)
    second = submitter.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value="Net 45",
        candidate="f2",
        effective_from=WHEN - timedelta(days=1),
        evidence=(external("inv-f2"),),
    )
    assert second["outcome"] == "direct_superseded", second
    assert _class_of(submitter, second["assertion_id"]) == "restricted_local"
    # The trigger refuses a raw successor below its (superseded) predecessor.
    with pytest.raises(IntegrityError), submitter.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertions (principal_id, assertion_id, "
                "subject_kind, subject_id, predicate_code, predicate_version, value_type, "
                "cardinality, temporal_semantics, qualifier_rule, value_text, "
                "normalized_value_sha256, fingerprint_version, assertion_fingerprint, "
                "epistemic_status, classification, origin_is_synthetic, lifecycle, version, "
                "origin_submission_id, supersedes_assertion_id, created_at, updated_at) "
                "SELECT principal_id, :n, subject_kind, subject_id, predicate_code, "
                "predicate_version, value_type, cardinality, temporal_semantics, "
                "qualifier_rule, 'Net 99', normalized_value_sha256, 1, :f, epistemic_status, "
                "'private_local', origin_is_synthetic, 'active', 1, origin_submission_id, "
                "assertion_id, now(), now() FROM knowledge.knowledge_assertions "
                "WHERE assertion_id = :a"
            ),
            {
                "n": issue_identifier(IdKind.KNOWLEDGE_ASSERTION),
                "f": "c" * 64,
                "a": first["assertion_id"],
            },
        )


def test_a_synthetic_profile_carries_the_synthetic_origin_above_the_floor(
    submitter: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = submitter.profile(principal, origin="synthetic")
    org = submitter.entity(principal, "synthetic")
    created = submitter.submit(principal, profile, subject_id=org)
    assert created["outcome"] == "direct_created", created
    with submitter.engine.connect() as connection:
        assertion = connection.execute(
            select(
                knowledge_assertions.c.origin_is_synthetic, knowledge_assertions.c.classification
            ).where(knowledge_assertions.c.assertion_id == created["assertion_id"])
        ).one()
        evidence = connection.execute(
            select(
                knowledge_evidence_refs.c.source_is_synthetic,
                knowledge_evidence_refs.c.content_origin,
                knowledge_evidence_refs.c.source_classification,
            ).where(knowledge_evidence_refs.c.principal_id == principal)
        ).one()
    assert tuple(assertion) == (True, "private_local")
    assert tuple(evidence) == (True, "synthetic_source", "synthetic_test")


def test_a_submit_linked_assertion_is_withheld_by_another_profiles_restriction(
    submitter: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "cross-submit")
    created = submitter.submit(principal, profile, subject_id=org, evidence=(external("doc-7"),))
    read = ReadKnowledgeAssertion(assertion_id=created["assertion_id"])
    assert submitter.invoke(read, principal_id=principal, **REMOTE).error is None
    other = submitter.profile(principal, scope="scope-b")
    seed_external(
        submitter.engine,
        principal,
        other,
        object_id="doc-7",
        version="v9",
        classification="restricted_local",
    )
    before = _class_of(submitter, created["assertion_id"])
    withheld = submitter.invoke(read, principal_id=principal, **REMOTE)
    assert withheld.error is not None and withheld.error.code.value == "not_found"
    assert _class_of(submitter, created["assertion_id"]) == before == "private_local"
    assert submitter.invoke(read, principal_id=principal).error is None


def test_a_submit_re_citing_a_now_restricted_object_raises_and_redacts(
    submitter: SubmitRuntime,
) -> None:
    """KLP-R6V-201 (i) at submit: one UPDATE raises the row and nulls its excerpt."""
    principal = new_principal()
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "recite")
    first = submitter.submit(
        principal, profile, subject_id=org, evidence=(external("doc-r", excerpt="Kept excerpt."),)
    )
    other = submitter.profile(principal, scope="scope-b")
    seed_external(
        submitter.engine,
        principal,
        other,
        object_id="doc-r",
        version="v2",
        classification="restricted_local",
    )
    again = submitter.submit(
        principal,
        profile,
        subject_id=org,
        candidate="cand-again",
        evidence=(external("doc-r", excerpt="Kept excerpt."),),
    )
    assert again["outcome"] == "duplicate_existing"
    with submitter.engine.connect() as connection:
        row = connection.execute(
            select(
                knowledge_evidence_refs.c.source_classification,
                knowledge_evidence_refs.c.excerpt,
                knowledge_evidence_refs.c.excerpt_sha256,
            ).where(
                knowledge_evidence_refs.c.principal_id == principal,
                knowledge_evidence_refs.c.source_profile_id == profile,
            )
        ).one()
    assert row.source_classification == "restricted_local"
    assert row.excerpt is None
    assert row.excerpt_sha256 == hashlib.sha256(b"Kept excerpt.").hexdigest()
    del first
