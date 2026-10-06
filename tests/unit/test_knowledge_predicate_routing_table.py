"""KLP-WP-07: the 8-row predicate routing table (KLP-AC-154, FAST, unmarked).

Routed to `repository-checks / validate` and `repository-checks / dependency-floor`.

R6 sections 8.5, 11.6 and 13 state what each of the eight seed predicates
becomes when a discovery client submits a candidate. This module proves that
statement through the two real pure decision functions the submit transaction
calls -- `decide_domain_route` (C2, from the immutable predicate head and the
owner-ref read) and, when no route applies, `decide_direct_admission` -- using
the frozen seed values themselves:

* the seeds are read from the committed matrix copy (`initial_predicates`) and
  are required to equal, column for column, the seed `INSERT` the Knowledge
  revision executes (parsed from the migration's `_PREDICATE_SEEDS` literal),
  so neither copy can drift from the other or from this table;
* the expected routes are the plan's own statements (`PLAN_ROUTES`), keyed by
  predicate code, and required to cover exactly the eight seed codes.

The cases: `project.critical_date` with a resolving owner ref of each of the
four kinds is `domain_owned_routed` to {tasks, commitments, constraints,
meetings} with `routed_record_id = owner_ref_id`; an unresolvable ref is
refused `owner_ref_invalid`; no ref is Knowledge Review (`review_queued`,
`requires_operator`). `project.decision` is `domain_owned_no_intake` naming
`continuity_decision` (KLP-AC-097 re-proved here). An owner ref on any other
predicate is refused. The Knowledge-owned predicates queue for Review with
their own requirement, except `organization.operating_requirement`, which is
direct-admitted only under a proven, authoritative, direct-admission-enabled
profile.

**`entity.communication_preference` (WP-04 DEV-32, Manager ruling; WP-07
DEV-01).** R6 section 13 routes it to `relationship_memory.propose` only when
(a) Relationship Memory is composed, (b) a reviewed RM intake that can
faithfully take the candidate and its evidence already exists, and (c) at
least one evidence row is `capture`/`relationship_memory` shaped. In this build
(b) does not hold, so every case -- RM composed with capture evidence, RM
composed with external-only evidence, RM not composed -- completes
`domain_owned_no_intake` naming `relationship_memory`. The repository truth
behind (b) is asserted here rather than restated: the RM proposal writer's
evidence (`ProposedEvidence`) names exactly a capture *span*, an entity
observation or an extraction knowledge record, while a Knowledge citation names
a capture *root* or a Relationship Memory -- disjoint identifier kinds -- so no
Knowledge evidence row is transferable. If either side grows a shared target,
`test_no_knowledge_citation_is_an_rm_proposal_target` fails and the routing
must be re-ruled rather than silently kept.

Every identity here is synthetic.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.application.relationship_memory import ProposedEvidence
from my_pa.domain.common.classification import Classification
from my_pa.domain.knowledge_assertion.admission import (
    OWNER_REF_ROUTES,
    AdmissionEvidence,
    AdmissionPath,
    DirectAdmissionBlocker,
    DirectAdmissionFacts,
    DomainRoute,
    SourceProfileFacts,
    SubjectResolution,
    decide_direct_admission,
    decide_domain_route,
)
from my_pa.domain.knowledge_assertion.evidence import EvidenceIdentity
from my_pa.domain.knowledge_assertion.predicate import KnowledgePredicate
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeAutonomousAdmissionPolicy,
    KnowledgeCanonicalOwner,
    KnowledgeCardinality,
    KnowledgeConflictRule,
    KnowledgeConsequentialClass,
    KnowledgeEvidenceAuthority,
    KnowledgeEvidenceIdentityKind,
    KnowledgeEvidenceRole,
    KnowledgeNormalizationRule,
    KnowledgeOriginSystem,
    KnowledgeOwnerRefKind,
    KnowledgePredicateAdmissionState,
    KnowledgeQualifierRule,
    KnowledgeReadOnlyProofState,
    KnowledgeReviewRequirement,
    KnowledgeSubjectKind,
    KnowledgeSubmissionOutcome,
    KnowledgeSubmissionReason,
    KnowledgeTemporalSemantics,
    KnowledgeValueType,
)
from my_pa.domain.relationship.entity import EntityType

ROOT: Final = Path(__file__).resolve().parents[2]
MATRIX_PATH: Final = ROOT / "tests" / "architecture" / "klp_implementation_matrix_r6.json"
MIGRATION: Final = (
    ROOT / "migrations" / "versions" / "20261004_6734f039f7a6_knowledge_assertion_layer.py"
)
NOW: Final = datetime(2026, 10, 6, 12, tzinfo=UTC)
PROFILE: Final = "kdsp_SyntheticRouting01"
HASH: Final = hashlib.sha256(b"synthetic routing evidence").hexdigest()

PAYMENT: Final = "organization.payment_terms"
OPERATING: Final = "organization.operating_requirement"
POLICY: Final = "policy.requirement"
LESSON: Final = "process.lesson_learned"
DECISION: Final = "project.decision"
CRITICAL: Final = "project.critical_date"
FINANCIAL: Final = "project.financial_fact"
PREFERENCE: Final = "entity.communication_preference"

#: The plan's statement of each seed's route when no owner ref is sent (R6 11.6
#: routing notes, 8.5, 13), under the strongest profile a discovery client can
#: hold (proven, authoritative, direct admission enabled) and one stable, direct,
#: external evidence row from that profile: (outcome, reason, canonical owner).
PLAN_ROUTES: Final[Mapping[str, tuple[str, str, str | None]]] = {
    PAYMENT: ("review_queued", "requires_operator", None),
    OPERATING: ("direct_created", "created", None),
    POLICY: ("review_queued", "requires_review", None),
    LESSON: ("review_queued", "requires_review", None),
    DECISION: ("domain_owned_no_intake", "canonical_owner_no_intake", "continuity_decision"),
    CRITICAL: ("review_queued", "requires_operator", None),
    FINANCIAL: ("review_queued", "requires_operator", None),
    PREFERENCE: ("domain_owned_no_intake", "canonical_owner_no_intake", "relationship_memory"),
}
#: The owner-ref id prefix of each kind (the identifiers the owner planes issue).
OWNER_REF_IDS: Final[Mapping[KnowledgeOwnerRefKind, str]] = {
    KnowledgeOwnerRefKind.TASK: "tsk_SyntheticRouting01",
    KnowledgeOwnerRefKind.COMMITMENT: "cmt_SyntheticRouting01",
    KnowledgeOwnerRefKind.CONSTRAINT: "cst_SyntheticRouting01",
    KnowledgeOwnerRefKind.MEETING: "mtg_SyntheticRouting01",
}
#: R6 section 13: the routed critical-date owners.
ROUTED_OWNERS: Final = frozenset({"tasks", "commitments", "constraints", "meetings"})
#: R6 section 13 (correcting R5's `team`): `entity.communication_preference` subjects.
PREFERENCE_ENTITY_TYPES: Final = frozenset(
    {"person", "organization", "team_or_group", "project", "program", "work_package", "location"}
)

_SEED_COLUMNS: Final = (
    "predicate_code",
    "predicate_version",
    "admission_state",
    "value_type",
    "cardinality",
    "temporal_semantics",
    "qualifier_rule",
    "allowed_subject_kinds",
    "allowed_entity_types",
    "canonical_owner",
    "autonomous_admission_policy",
    "review_requirement",
    "consequential_class",
    "normalization_rule",
    "classification_floor",
    "conflict_rule",
    "minimum_evidence_authority",
    "fingerprint_version",
)
EMPTY_ARRAY: Final = "'{}'::text[]"
_SQL_VALUE: Final = re.compile(r"'\{\}'::text\[\]|ARRAY\[[^\]]*\]::text\[\]|'[^']*'|\d+")


# ---- the frozen seeds, from both copies ------------------------------------------------


@cache
def matrix_seeds() -> dict[str, dict[str, Any]]:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    return {row["predicate_code"]: row for row in matrix["initial_predicates"]}


def _sql_literal(token: str) -> object:
    if token == EMPTY_ARRAY:
        return []
    if token.startswith("ARRAY["):
        return re.findall(r"'([^']*)'", token)
    if token.startswith("'"):
        return token[1:-1]
    return int(token)


@cache
def migration_seeds() -> dict[str, dict[str, object]]:
    """The seed rows the Knowledge revision INSERTs, parsed from its literal."""
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    literal = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_PREDICATE_SEEDS"
        and node.value is not None
    )
    sql = ast.literal_eval(literal)
    assert isinstance(sql, str)
    values = sql[sql.index("VALUES") + len("VALUES") :]
    rows: dict[str, dict[str, object]] = {}
    depth, start = 0, 0
    for index, char in enumerate(values):
        if char == "(":
            depth += 1
            if depth == 1:
                start = index + 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                tokens = [_sql_literal(t) for t in _SQL_VALUE.findall(values[start:index])]
                assert len(tokens) == len(_SEED_COLUMNS), tokens
                row = dict(zip(_SEED_COLUMNS, tokens, strict=True))
                rows[str(row["predicate_code"])] = row
    return rows


def predicate(code: str) -> KnowledgePredicate:
    row = matrix_seeds()[code]
    return KnowledgePredicate(
        predicate_code=row["predicate_code"],
        predicate_version=row["predicate_version"],
        admission_state=KnowledgePredicateAdmissionState(row["admission_state"]),
        value_type=KnowledgeValueType(row["value_type"]),
        cardinality=KnowledgeCardinality(row["cardinality"]),
        temporal_semantics=KnowledgeTemporalSemantics(row["temporal_semantics"]),
        qualifier_rule=KnowledgeQualifierRule(row["qualifier_rule"]),
        allowed_subject_kinds=frozenset(
            KnowledgeSubjectKind(kind) for kind in row["allowed_subject_kinds"]
        ),
        allowed_entity_types=frozenset(EntityType(kind) for kind in row["allowed_entity_types"]),
        canonical_owner=KnowledgeCanonicalOwner(row["canonical_owner"]),
        autonomous_admission_policy=KnowledgeAutonomousAdmissionPolicy(
            row["autonomous_admission_policy"]
        ),
        review_requirement=KnowledgeReviewRequirement(row["review_requirement"]),
        consequential_class=KnowledgeConsequentialClass(row["consequential_class"]),
        normalization_rule=KnowledgeNormalizationRule(row["normalization_rule"]),
        classification_floor=Classification(row["classification_floor"]),
        conflict_rule=KnowledgeConflictRule(row["conflict_rule"]),
        minimum_evidence_authority=KnowledgeEvidenceAuthority(row["minimum_evidence_authority"]),
        fingerprint_version=row["fingerprint_version"],
    )


# ---- the composed route: what the submit transaction decides ---------------------------


def profile(
    *,
    direct: bool = True,
    proof: KnowledgeReadOnlyProofState = KnowledgeReadOnlyProofState.PROVEN,
    ceiling: KnowledgeEvidenceAuthority = KnowledgeEvidenceAuthority.AUTHORITATIVE_SOURCE,
) -> SourceProfileFacts:
    return SourceProfileFacts(
        source_profile_id=PROFILE,
        origin_system=KnowledgeOriginSystem.SYNTHETIC,
        authority_ceiling=ceiling,
        direct_admission_enabled=direct,
        read_only_proof_state=proof,
        is_synthetic=True,
        disabled=False,
    )


EXTERNAL: Final = AdmissionEvidence(
    identity_kind=KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT,
    role=KnowledgeEvidenceRole.DIRECT,
    content_hash=HASH,
    source_profile_id=PROFILE,
    origin_system=KnowledgeOriginSystem.SYNTHETIC,
    external_object_id="synthetic-routing-object",
    external_version_id="v1",
)
CAPTURE: Final = AdmissionEvidence(
    identity_kind=KnowledgeEvidenceIdentityKind.CAPTURE,
    role=KnowledgeEvidenceRole.SUPPORTING,
    content_hash=HASH,
    product_record_id="cap_SyntheticRouting01",
)
MEMORY: Final = AdmissionEvidence(
    identity_kind=KnowledgeEvidenceIdentityKind.RELATIONSHIP_MEMORY,
    role=KnowledgeEvidenceRole.SUPPORTING,
    content_hash=HASH,
    product_record_id="mem_SyntheticRouting01",
)


@dataclasses.dataclass(frozen=True, slots=True)
class Routed:
    """The completed submission a candidate becomes (outcome, reason, owner, routed id)."""

    outcome: str
    reason: str
    canonical_owner: str | None
    routed_record_id: str | None = None


def route(
    code: str,
    *,
    owner_ref: tuple[KnowledgeOwnerRefKind, str] | None = None,
    resolves: bool = True,
    source: SourceProfileFacts | None = None,
    evidence: tuple[AdmissionEvidence, ...] = (EXTERNAL,),
) -> Routed:
    """C2's route first, then (Knowledge plane only) the direct-admission policy.

    The order and the hand-off are the submit transaction's own
    (`_AutonomousSubmit.run` -> `_route`, then `_knowledge`), applied to the
    seed head; the subject is canonical and nothing else is pending.
    """
    head = predicate(code)
    domain: DomainRoute | None = decide_domain_route(
        head,
        owner_ref_kind=None if owner_ref is None else owner_ref[0],
        owner_ref_id=None if owner_ref is None else owner_ref[1],
        owner_ref_resolves=resolves,
    )
    if domain is not None:
        return Routed(
            domain.outcome.value,
            domain.reason.value,
            None if domain.canonical_owner is None else domain.canonical_owner.value,
            domain.routed_record_id,
        )
    decision = decide_direct_admission(
        DirectAdmissionFacts(
            predicate=head,
            profile=profile() if source is None else source,
            subject=SubjectResolution.CANONICAL,
            evidence=evidence,
            candidate_effective_from=None,
            now=NOW,
        )
    )
    assert decision.path is not AdmissionPath.DOMAIN_OWNED, code
    assert decision.outcome is not None and decision.reason is not None
    return Routed(decision.outcome.value, decision.reason.value, None)


# ---- the seeds are one table -----------------------------------------------------------


def test_the_matrix_seeds_equal_the_revision_seed_insert_column_for_column() -> None:
    matrix = {
        code: {column: row[column] for column in _SEED_COLUMNS}
        for code, row in matrix_seeds().items()
    }
    assert len(matrix) == 8
    assert matrix == migration_seeds()


def test_the_plan_table_covers_exactly_the_eight_seed_codes() -> None:
    assert set(PLAN_ROUTES) == set(matrix_seeds())


def test_each_seed_is_a_valid_open_registry_head() -> None:
    for code in matrix_seeds():
        head = predicate(code)
        assert head.is_open_for_intake, code
        assert head.predicate_version == 1, code


# ---- the eight rows (KLP-AC-154) -------------------------------------------------------


@pytest.mark.parametrize("code", sorted(PLAN_ROUTES))
def test_each_seed_routes_as_the_plan_states(code: str) -> None:
    outcome, reason, owner = PLAN_ROUTES[code]
    assert route(code) == Routed(outcome, reason, owner)


@pytest.mark.parametrize("code", sorted(PLAN_ROUTES))
def test_the_route_follows_the_seed_columns_not_the_code(code: str) -> None:
    """Each row's route is what its frozen columns imply (no per-code special case)."""
    row = matrix_seeds()[code]
    routed = route(code)
    if row["canonical_owner"] != "knowledge_assertion":
        assert routed.outcome == "domain_owned_no_intake"
        assert routed.canonical_owner == row["canonical_owner"]
    elif row["autonomous_admission_policy"] == "never" or row["consequential_class"] != "none":
        assert routed.outcome == "review_queued"
        assert routed.reason == row["review_requirement"]
    else:
        assert routed.outcome == "direct_created"


# ---- project.critical_date: routed / invalid / absent ---------------------------------


@pytest.mark.parametrize("kind", list(KnowledgeOwnerRefKind), ids=lambda kind: kind.value)
def test_a_resolving_owner_ref_routes_a_critical_date_to_its_owner(
    kind: KnowledgeOwnerRefKind,
) -> None:
    ref = OWNER_REF_IDS[kind]
    routed = route(CRITICAL, owner_ref=(kind, ref))
    assert routed.outcome == "domain_owned_routed"
    assert routed.reason == "canonical_owner"
    assert routed.canonical_owner in ROUTED_OWNERS
    assert routed.canonical_owner == OWNER_REF_ROUTES[kind].value
    assert routed.routed_record_id == ref


def test_the_four_ref_kinds_route_to_the_four_owners() -> None:
    assert {kind.value: owner.value for kind, owner in OWNER_REF_ROUTES.items()} == {
        "task": "tasks",
        "commitment": "commitments",
        "constraint": "constraints",
        "meeting": "meetings",
    }


@pytest.mark.parametrize("kind", list(KnowledgeOwnerRefKind), ids=lambda kind: kind.value)
def test_an_unresolvable_owner_ref_refuses_a_critical_date(kind: KnowledgeOwnerRefKind) -> None:
    routed = route(CRITICAL, owner_ref=(kind, OWNER_REF_IDS[kind]), resolves=False)
    assert routed == Routed("refused", "owner_ref_invalid", None, None)


def test_a_critical_date_without_an_owner_ref_is_knowledge_review() -> None:
    assert route(CRITICAL) == Routed("review_queued", "requires_operator", None)
    # No semantic inference: even the strongest profile never direct-admits it.
    decision = decide_direct_admission(
        DirectAdmissionFacts(
            predicate=predicate(CRITICAL),
            profile=profile(),
            subject=SubjectResolution.CANONICAL,
            evidence=(EXTERNAL,),
            candidate_effective_from=None,
            now=NOW,
        )
    )
    assert DirectAdmissionBlocker.PREDICATE_NEVER_DIRECT_ADMITS in decision.blockers
    assert DirectAdmissionBlocker.CONSEQUENTIAL_PREDICATE in decision.blockers


@pytest.mark.parametrize("code", sorted(set(PLAN_ROUTES) - {CRITICAL}))
@pytest.mark.parametrize("resolves", [True, False], ids=["resolving", "unresolvable"])
def test_an_owner_ref_on_any_other_predicate_is_refused(code: str, resolves: bool) -> None:
    for kind in KnowledgeOwnerRefKind:
        routed = route(code, owner_ref=(kind, OWNER_REF_IDS[kind]), resolves=resolves)
        assert routed == Routed("refused", "owner_ref_invalid", None, None), (code, kind)


# ---- project.decision (KLP-AC-097 re-proved at the slice) ------------------------------


def test_project_decision_is_no_intake_naming_continuity_decision() -> None:
    routed = route(DECISION)
    assert routed == Routed(
        "domain_owned_no_intake", "canonical_owner_no_intake", "continuity_decision", None
    )
    # Whatever the profile or the evidence, the route precedes the policy.
    for source in (profile(direct=False), profile(proof=KnowledgeReadOnlyProofState.UNPROVEN)):
        assert route(DECISION, source=source, evidence=(CAPTURE,)) == routed


# ---- Knowledge-owned predicates: direct only for operating_requirement -----------------


@pytest.mark.parametrize(
    ("source", "blocker"),
    [
        (profile(direct=False), DirectAdmissionBlocker.PROFILE_DIRECT_ADMISSION_DISABLED),
        (
            profile(direct=False, proof=KnowledgeReadOnlyProofState.UNPROVEN),
            DirectAdmissionBlocker.PROFILE_READ_ONLY_UNPROVEN,
        ),
        (
            profile(direct=False, ceiling=KnowledgeEvidenceAuthority.OBSERVED_SOURCE),
            DirectAdmissionBlocker.PROFILE_CEILING_NOT_AUTHORITATIVE,
        ),
    ],
    ids=["direct_disabled", "unproven", "observed_ceiling"],
)
def test_operating_requirement_is_reviewed_unless_the_profile_is_direct_capable(
    source: SourceProfileFacts, blocker: DirectAdmissionBlocker
) -> None:
    assert route(OPERATING, source=source) == Routed("review_queued", "requires_review", None)
    decision = decide_direct_admission(
        DirectAdmissionFacts(
            predicate=predicate(OPERATING),
            profile=source,
            subject=SubjectResolution.CANONICAL,
            evidence=(EXTERNAL,),
            candidate_effective_from=None,
            now=NOW,
        )
    )
    assert blocker in decision.blockers


def test_operating_requirement_without_direct_external_evidence_is_reviewed() -> None:
    assert route(OPERATING, evidence=(CAPTURE,)) == Routed("review_queued", "requires_review", None)


@pytest.mark.parametrize("code", [PAYMENT, POLICY, LESSON, CRITICAL, FINANCIAL])
def test_a_never_admitting_predicate_is_reviewed_under_every_profile(code: str) -> None:
    requirement = matrix_seeds()[code]["review_requirement"]
    for source in (
        profile(),
        profile(direct=False),
        profile(direct=False, ceiling=KnowledgeEvidenceAuthority.OBSERVED_SOURCE),
    ):
        assert route(code, source=source) == Routed("review_queued", requirement, None), code


def test_the_requires_operator_rows_are_exactly_the_consequential_and_payment_rows() -> None:
    operator = {
        code
        for code, row in matrix_seeds().items()
        if row["review_requirement"] == "requires_operator"
    }
    assert operator == {PAYMENT, CRITICAL, FINANCIAL}
    for code in operator:
        assert route(code).reason == "requires_operator"


# ---- entity.communication_preference (DEV-32 ruling, WP-07 DEV-01) ---------------------


@pytest.mark.parametrize(
    ("rm_composed", "evidence"),
    [
        (True, (EXTERNAL, CAPTURE)),
        (True, (EXTERNAL, MEMORY)),
        (True, (EXTERNAL,)),
        (False, (EXTERNAL, CAPTURE)),
    ],
    ids=["rm_composed_capture", "rm_composed_memory", "rm_composed_external_only", "rm_absent"],
)
def test_communication_preference_is_no_intake_in_every_case(
    rm_composed: bool, evidence: tuple[AdmissionEvidence, ...]
) -> None:
    """(b) does not hold in this build, so (a) and (c) cannot change the outcome.

    `rm_composed` is not an input of the route: `decide_domain_route` reads only
    the predicate head and the owner ref, which is what makes the outcome the
    same in every case. The signature is pinned below so that adding an RM input
    is a visible change that has to re-prove this table.
    """
    del rm_composed
    assert route(PREFERENCE, evidence=evidence) == Routed(
        "domain_owned_no_intake", "canonical_owner_no_intake", "relationship_memory", None
    )


def test_the_route_reads_only_the_head_and_the_owner_ref() -> None:
    assert list(inspect.signature(decide_domain_route).parameters) == [
        "predicate",
        "owner_ref_kind",
        "owner_ref_id",
        "owner_ref_resolves",
    ]


def test_communication_preference_subjects_are_the_r6_entity_types() -> None:
    row = matrix_seeds()[PREFERENCE]
    assert row["allowed_subject_kinds"] == ["entity"]
    assert set(row["allowed_entity_types"]) == PREFERENCE_ENTITY_TYPES
    assert {member.value for member in EntityType} >= PREFERENCE_ENTITY_TYPES


def test_no_knowledge_citation_is_an_rm_proposal_target() -> None:
    """Repository truth behind DEV-32 (b): no faithful RM intake exists.

    `relationship_memory.propose` takes `ProposedEvidence` naming exactly one of
    an entity observation (`eobs_`), a capture *span* (`span_`) or an extraction
    knowledge record (`kn_`). A Knowledge citation is an external object, a
    capture *root* (`cap_`) or a Relationship Memory (`mem_`). The two sets of
    targets are disjoint, so no Knowledge evidence row can be carried into an RM
    proposal without inventing an identifier -- which the ruling forbids.
    """
    rm_targets = {field.name for field in dataclasses.fields(ProposedEvidence)} - {"role"}
    assert rm_targets == {"entity_observation_id", "capture_span_id", "knowledge_id"}
    knowledge_product = {field.name for field in dataclasses.fields(EvidenceIdentity)} - {
        "identity_kind",
        "content_hash",
        "source_profile_id",
    }
    assert knowledge_product == {
        "external_object_id",
        "external_version_id",
        "capture_id",
        "relationship_memory_id",
    }
    assert not rm_targets & knowledge_product
    assert {member.value for member in KnowledgeEvidenceIdentityKind} == {
        "external_object",
        "capture",
        "relationship_memory",
    }


def test_no_route_outcome_is_ever_a_knowledge_write() -> None:
    """Every DOMAIN_OWNED completion is one of the two route outcomes or a refusal."""
    for code in PLAN_ROUTES:
        for kind in (None, *KnowledgeOwnerRefKind):
            for resolves in (True, False):
                domain = decide_domain_route(
                    predicate(code),
                    owner_ref_kind=kind,
                    owner_ref_id=None if kind is None else OWNER_REF_IDS[kind],
                    owner_ref_resolves=resolves,
                )
                if domain is None:
                    assert matrix_seeds()[code]["canonical_owner"] == "knowledge_assertion"
                    continue
                assert domain.outcome in {
                    KnowledgeSubmissionOutcome.DOMAIN_OWNED_ROUTED,
                    KnowledgeSubmissionOutcome.DOMAIN_OWNED_NO_INTAKE,
                    KnowledgeSubmissionOutcome.REFUSED,
                }
                if domain.outcome is KnowledgeSubmissionOutcome.REFUSED:
                    assert domain.reason is KnowledgeSubmissionReason.OWNER_REF_INVALID
