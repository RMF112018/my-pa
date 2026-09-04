"""The supported predecessor `3d07af4dc513` reaching the corrective head `b727e870d45e`.

`AGENTS.md` section 6 requires migrations to be tested "from an empty schema to
head and, when relevant, **from the preceding supported revision**". Every other
migration suite in this repository builds from empty, so the second half of that
sentence had no regression behind it for the RI remediation chain -- and the
chain is exactly where it matters, because `8e1c4a7b2d90` is not a pure DDL
revision. It carries `_settle_completed_merges()`, a real backfill that reads
`entity_identity_effects` and writes `entity_identity_operations.effect_count`
and `.effects_digest`.

**The seed is the test.** `_settle_completed_merges()` is a no-op when no
completed merge exists, so a from-empty upgrade -- and an unseeded predecessor
upgrade -- proves nothing about it at all. What proves something is a predecessor
database holding a *completed merge with a contiguous effect ledger and no
settlement*, upgraded online, and then checked against
`domain.relationship.identity_correction.effects_digest_for` recomputed from the
ledger rows the migration read. That equality is the claim: the historical
settlement the migration performs and the digest the running application would
compute are the same value, so a split admitted after the upgrade binds the same
ledger a merge performed before it.

The settlement is also why every upgrade here is a programmatic, **online**
`command.upgrade`. `8e1c4a7b2d90` fails closed under `--sql`, which is correct
and which means an offline rehearsal would say nothing about the backfill.

Non-vacuity is asserted rather than asserted-about:
`test_the_backfill_settles_nothing_without_a_completed_merge` runs the same
upgrade over the same seed with the merge removed and requires the settlement
column to stay empty, and
`test_a_gapped_effect_ledger_refuses_the_upgrade` requires the guard inside the
backfill to fire on a ledger with a hole. Between them, the settlement assertion
below cannot pass for a reason other than the one it names.

Two Principals throughout. Cross-Principal isolation is the one property a
single-Principal fixture cannot express: with one Principal, "nothing leaked"
and "there was nowhere to leak to" are the same observation.
"""

# ruff: noqa: S608 -- every interpolated identifier is a frozen test literal.

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError
from tests.db.provisioning import (
    configured_application_url,
    create_empty_database,
    force_drop_database,
    protected_from,
    url_for_database,
)

from my_pa.bootstrap.settings import ENV_PREFIX
from my_pa.domain.relationship.identity_correction import (
    IdentityEffect,
    IdentityEffectFamily,
    IdentityEffectKind,
    effects_digest_for,
    state_digest,
)
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: The three revisions this module is about, written out rather than derived, so
#: that a chain edit is a failure here rather than a silently different subject.
PREDECESSOR: Final = "3d07af4dc513"
IDENTITY_RECOVERY: Final = "8e1c4a7b2d90"
CORRECTIVE_HEAD: Final = "b727e870d45e"

#: Distinct from every other database-tier fixture's database on this shared
#: server, and distinct from each other so the comparison test can hold both at
#: once. Nothing here ever names the development database.
PREDECESSOR_DATABASE: Final = "my_pa_p_e_ri_pred"
FRESH_DATABASE: Final = "my_pa_p_e_ri_fresh"

# --- the two synthetic Principals and their records --------------------------

ALPHA: Final = "prn_alpha0001alpha0001"
BETA: Final = "prn_beta0002beta0002bb"

ALPHA_SURVIVOR: Final = "ent_alphasurvivor0001"
ALPHA_MERGED_AWAY: Final = "ent_alphamergedaway01"
ALPHA_ORGANIZATION: Final = "ent_alphaorganization"
BETA_SURVIVOR: Final = "ent_betasurvivor00001"
BETA_MERGED_AWAY: Final = "ent_betamergedaway001"
BETA_ORGANIZATION: Final = "ent_betaorganization1"

ALPHA_ENTITIES: Final = (ALPHA_SURVIVOR, ALPHA_MERGED_AWAY, ALPHA_ORGANIZATION)
BETA_ENTITIES: Final = (BETA_SURVIVOR, BETA_MERGED_AWAY, BETA_ORGANIZATION)

ALPHA_PRIMARY_ALIAS: Final = "eals_alphaprimary0001"
ALPHA_REPARENTED_ALIAS: Final = "eals_alphareparented1"
BETA_PRIMARY_ALIAS: Final = "eals_betaprimary00001"
BETA_REPARENTED_ALIAS: Final = "eals_betareparented01"

ALPHA_IDENTIFIER: Final = "xid_alphaemail000001"
BETA_IDENTIFIER: Final = "xid_betaemail0000001"

ALPHA_ASSIGNMENT: Final = "asn_alphaassignment1"
BETA_ASSIGNMENT: Final = "asn_betaassignment01"

ALPHA_RELATIONSHIP: Final = "erel_alpharelation01"
BETA_RELATIONSHIP: Final = "erel_betarelation0001"

ALPHA_OBSERVATION: Final = "eobs_alphaobserved01"
BETA_OBSERVATION: Final = "eobs_betaobserved0001"

ALPHA_PROPOSAL: Final = "eprp_alphaproposal01"
BETA_PROPOSAL: Final = "eprp_betaproposal0001"
ALPHA_REVIEW_CASE: Final = "rvw_alphacase000001"
BETA_REVIEW_CASE: Final = "rvw_betacase00000001"
ALPHA_DECISION: Final = "rdec_alphadecision01"
BETA_DECISION: Final = "rdec_betadecision0001"

#: One memory on each Principal's survivor and one on Alpha's merged-away entity.
#: The third is what makes the origin backfill a per-row statement rather than a
#: constant: `origin_subject_entity_id` must come from *that memory's* subject.
ALPHA_SURVIVOR_MEMORY: Final = "mem_alphasurvivormem1"
ALPHA_MERGED_MEMORY: Final = "mem_alphamergedmem001"
BETA_MEMORY: Final = "mem_betamemory000001"
ALPHA_SURVIVOR_MEMORY_VERSION: Final = "memver_alphasurvivorv1"
ALPHA_MERGED_MEMORY_VERSION: Final = "memver_alphamergedv01"
BETA_MEMORY_VERSION: Final = "memver_betav000000001"

ALPHA_SURVIVOR_CONTEXT_LINK: Final = "mctx_alphasurvivorent"
ALPHA_MERGED_CONTEXT_LINK: Final = "mctx_alphamergedent01"
ALPHA_TASK_CONTEXT_LINK: Final = "mctx_alphatasklink01"
BETA_CONTEXT_LINK: Final = "mctx_betaentitylink1"
ALPHA_TASK: Final = "tsk_alphatask000001"

ALPHA_MEMORY_PROPOSAL: Final = "mprop_alphaproposal1"
BETA_MEMORY_PROPOSAL: Final = "mprop_betaproposal001"

ALPHA_PREVIEW: Final = "eipv_alphamergeprev1"
BETA_PREVIEW: Final = "eipv_betamergeprev01"
ALPHA_MERGE: Final = "eiop_alphamerge00001"
BETA_MERGE: Final = "eiop_betamerge000001"

WHEN: Final = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

#: The twelve families `8e1c4a7b2d90` widens `an_identity_effect_family_is_known`
#: to, in that revision's own order. Frozen here rather than read from
#: `IdentityEffectFamily`, for the reason every revision in this repository
#: freezes its vocabularies: a constraint that followed a live enum would change
#: meaning the day the enum did.
#: Each is paired with the identifier prefix its records actually carry, because
#: `entity_identity_effects.record_id` is an opaque identifier at the server
#: *and* in `domain.common.identifiers`: a synthetic `rec_...` would satisfy the
#: stored regex and be refused by the domain, which would make the recomputation
#: in `_recomputed_digest` impossible for reasons unrelated to this revision.
RECORD_FAMILY_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("entity", "ent"),
    ("alias", "eals"),
    ("identifier", "xid"),
    ("assignment", "asn"),
    ("relationship", "erel"),
    ("observation", "eobs"),
    ("proposal", "eprp"),
    ("review_case", "rvw"),
    ("relationship_memory", "mem"),
    ("memory_proposal", "mprop"),
    ("memory_context_link", "mctx"),
    ("derived_context", "ctxm"),
)
RECORD_FAMILIES: Final[tuple[str, ...]] = tuple(family for family, _ in RECORD_FAMILY_PREFIXES)
_PREFIX_FOR_FAMILY: Final = dict(RECORD_FAMILY_PREFIXES)

#: The objects `b727e870d45e` adds, by the name the server holds them under.
CORRECTIVE_TABLES: Final = (
    "entity_identity_preview_ambiguities",
    "entity_identity_ambiguity_settlements",
)
CORRECTIVE_TRIGGERS: Final = (
    "identity_ambiguity_settlements_are_append_only",
    "entity_proposal_review_decisions_are_append_only",
)

#: The three triggers `8e1c4a7b2d90` arms over the Relationship Memory plane.
ORIGIN_TRIGGERS: Final = (
    "relationship_memory_origin_stays_fixed",
    "relationship_memory_proposal_origin_stays_fixed",
    "relationship_memory_context_origin_stays_fixed",
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _sha256(label: str) -> str:
    """A stable synthetic sha256 for a column whose CHECK is a shape rule."""
    return hashlib.sha256(label.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Disposable:
    """One disposable database, and the Alembic runs pointed at it.

    `command.upgrade` reads the URL from `MY_PA_DATABASE_URL` through
    `migrations/env.py`, so driving two databases in one test means re-pointing
    the variable before each run rather than holding two configs.
    """

    name: str
    url: str
    engine: Engine
    monkeypatch: pytest.MonkeyPatch

    def _aim_alembic_here(self) -> None:
        self.monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", self.url)

    def upgrade(self, revision: str) -> None:
        """Online, in process. Never `--sql`: `8e1c4a7b2d90` fails closed offline."""
        self._aim_alembic_here()
        command.upgrade(_config(), revision)

    def downgrade(self, revision: str) -> None:
        self._aim_alembic_here()
        command.downgrade(_config(), revision)


#: `build(name, revision)` -- create a database and carry it to `revision`.
BuildDatabase = Callable[[str, str], "Disposable"]


@pytest.fixture
def disposable(
    monkeypatch: pytest.MonkeyPatch, postgres_admin_engine: Engine
) -> Iterator[BuildDatabase]:
    """Build named disposable databases off `postgres`, and drop every one.

    The configured URL supplies the server and role only; the database it names
    is never connected to, never migrated, and never mutated.
    """
    configured = configured_application_url()
    protected = protected_from(configured)
    built: list[Disposable] = []

    def build(name: str, revision: str) -> Disposable:
        create_empty_database(postgres_admin_engine, name, protected=protected)
        url = url_for_database(configured, name)
        database = Disposable(
            name=name, url=url, engine=create_database_engine(url), monkeypatch=monkeypatch
        )
        built.append(database)
        database.upgrade(revision)
        return database

    try:
        yield build
    finally:
        for database in built:
            database.engine.dispose()
            force_drop_database(postgres_admin_engine, database.name, protected=protected)


# --- the predecessor seed ----------------------------------------------------


def _entity(connection: Connection, entity_id: str, principal: str, **overrides: object) -> None:
    values: dict[str, object] = {
        "entity_id": entity_id,
        "principal_id": principal,
        "entity_type": "person",
        "canonical_name": f"synthetic {entity_id}",
        "display_name": f"Synthetic {entity_id}",
        "status": "active",
        "superseded_by_entity_id": None,
        "version": 1,
        "created_at": WHEN,
        "updated_at": WHEN,
    }
    values.update(overrides)
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entities (entity_id, principal_id, entity_type, "
            "canonical_name, display_name, status, superseded_by_entity_id, version, "
            "created_at, updated_at) VALUES (:entity_id, :principal_id, :entity_type, "
            ":canonical_name, :display_name, :status, :superseded_by_entity_id, :version, "
            ":created_at, :updated_at)"
        ),
        values,
    )


def _effect_rows(
    operation_id: str, principal: str, subjects: Sequence[tuple[str, str, str]]
) -> list[dict[str, object]]:
    """Ledger rows for `operation_id`, numbered contiguously from one.

    `before_sha256` and `after_sha256` are the domain's own `state_digest`, not a
    placeholder: `IdentityEffect` recomputes them on construction and refuses a
    disagreement, so a fabricated digest would make the recomputation below
    impossible rather than merely dishonest.
    """
    rows: list[dict[str, object]] = []
    for sequence, (family, record_id, kind) in enumerate(subjects, start=1):
        before: dict[str, object] = {"owner_entity_id": record_id, "state": "before"}
        after: dict[str, object] = {"owner_entity_id": record_id, "state": "after"}
        rows.append(
            {
                "effect_id": f"eief_{principal[4:12]}effect{sequence:04d}",
                "identity_operation_id": operation_id,
                "principal_id": principal,
                "sequence": sequence,
                "record_family": family,
                "record_id": record_id,
                "effect_kind": kind,
                "before_state": json.dumps(before),
                "after_state": json.dumps(after),
                "before_sha256": state_digest(before),
                "after_sha256": state_digest(after),
                "recorded_at": LATER,
            }
        )
    return rows


ALPHA_LEDGER: Final = (
    ("entity", ALPHA_MERGED_AWAY, "entity_redirected"),
    ("alias", ALPHA_REPARENTED_ALIAS, "owner_reparented"),
    ("assignment", ALPHA_ASSIGNMENT, "owner_reparented"),
)
BETA_LEDGER: Final = (
    ("entity", BETA_MERGED_AWAY, "entity_redirected"),
    ("alias", BETA_REPARENTED_ALIAS, "owner_reparented"),
)


def _seed_predecessor(engine: Engine, *, merges: bool = True, gapped: bool = False) -> None:
    """Representative `3d07af4dc513` state for two Principals.

    Nothing here names `origin_subject_entity_id`: the column does not exist at
    this revision, and seeding it would be seeding the answer.
    """
    with engine.begin() as connection:
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        for entity_id in (ALPHA_SURVIVOR, ALPHA_ORGANIZATION, BETA_SURVIVOR, BETA_ORGANIZATION):
            principal = ALPHA if entity_id.startswith("ent_alpha") else BETA
            kind = "organization" if "organization" in entity_id else "person"
            _entity(connection, entity_id, principal, entity_type=kind, version=3)
        _entity(
            connection,
            ALPHA_MERGED_AWAY,
            ALPHA,
            status="merged_redirect",
            superseded_by_entity_id=ALPHA_SURVIVOR,
            version=2,
        )
        _entity(
            connection,
            BETA_MERGED_AWAY,
            BETA,
            status="merged_redirect",
            superseded_by_entity_id=BETA_SURVIVOR,
            version=2,
        )

        alias_sql = text(
            f"INSERT INTO {SCHEMA}.entity_aliases (alias_id, entity_id, principal_id, "
            "alias_type, normalized_value, display_value, state, version, updated_at) "
            "VALUES (:alias_id, :entity_id, :principal_id, :alias_type, :normalized_value, "
            ":display_value, 'active', 1, :updated_at)"
        )
        for alias_id, entity_id, principal, alias_type in (
            (ALPHA_PRIMARY_ALIAS, ALPHA_SURVIVOR, ALPHA, "preferred_name"),
            (ALPHA_REPARENTED_ALIAS, ALPHA_SURVIVOR, ALPHA, "former_name"),
            (BETA_PRIMARY_ALIAS, BETA_SURVIVOR, BETA, "preferred_name"),
            (BETA_REPARENTED_ALIAS, BETA_SURVIVOR, BETA, "former_name"),
        ):
            connection.execute(
                alias_sql,
                {
                    "alias_id": alias_id,
                    "entity_id": entity_id,
                    "principal_id": principal,
                    "alias_type": alias_type,
                    "normalized_value": alias_id,
                    "display_value": f"Synthetic {alias_id}",
                    "updated_at": WHEN,
                },
            )

        identifier_sql = text(
            f"INSERT INTO {SCHEMA}.entity_external_identifiers (identifier_id, entity_id, "
            "principal_id, namespace, normalized_value, display_value, verified, state, "
            "version, updated_at) VALUES (:identifier_id, :entity_id, :principal_id, 'email', "
            ":normalized_value, :display_value, false, 'active', 1, :updated_at)"
        )
        for identifier_id, entity_id, principal in (
            (ALPHA_IDENTIFIER, ALPHA_SURVIVOR, ALPHA),
            (BETA_IDENTIFIER, BETA_SURVIVOR, BETA),
        ):
            connection.execute(
                identifier_sql,
                {
                    "identifier_id": identifier_id,
                    "entity_id": entity_id,
                    "principal_id": principal,
                    "normalized_value": f"{identifier_id}@synthetic.invalid",
                    "display_value": f"{identifier_id}@synthetic.invalid",
                    "updated_at": WHEN,
                },
            )

        assignment_sql = text(
            f"INSERT INTO {SCHEMA}.entity_assignments (assignment_id, entity_id, "
            "scope_entity_id, assignment_type, state, principal_id, version, updated_at) "
            "VALUES (:assignment_id, :entity_id, :scope_entity_id, 'employment', 'active', "
            ":principal_id, 1, :updated_at)"
        )
        relationship_sql = text(
            f"INSERT INTO {SCHEMA}.entity_relationships (relationship_id, from_entity_id, "
            "to_entity_id, relationship_type, state, version, principal_id, updated_at) "
            "VALUES (:relationship_id, :from_entity_id, :to_entity_id, 'works_for', 'active', "
            "1, :principal_id, :updated_at)"
        )
        for assignment_id, relationship_id, entity_id, organization, principal in (
            (ALPHA_ASSIGNMENT, ALPHA_RELATIONSHIP, ALPHA_SURVIVOR, ALPHA_ORGANIZATION, ALPHA),
            (BETA_ASSIGNMENT, BETA_RELATIONSHIP, BETA_SURVIVOR, BETA_ORGANIZATION, BETA),
        ):
            connection.execute(
                assignment_sql,
                {
                    "assignment_id": assignment_id,
                    "entity_id": entity_id,
                    "scope_entity_id": organization,
                    "principal_id": principal,
                    "updated_at": WHEN,
                },
            )
            connection.execute(
                relationship_sql,
                {
                    "relationship_id": relationship_id,
                    "from_entity_id": entity_id,
                    "to_entity_id": organization,
                    "principal_id": principal,
                    "updated_at": WHEN,
                },
            )

        observation_sql = text(
            f"INSERT INTO {SCHEMA}.entity_observations (observation_id, principal_id, kind, "
            "observed_value, normalized_value, source_id, source_object_id, source_version_id, "
            "observed_at, recorded_at, entity_id, authority, state, resolution_version) "
            "VALUES (:observation_id, :principal_id, 'contact_record', :observed_value, "
            ":normalized_value, :source_id, :source_object_id, :source_version_id, :observed_at, "
            ":recorded_at, :entity_id, 'source_observation', 'current', 1)"
        )
        for observation_id, entity_id, principal in (
            (ALPHA_OBSERVATION, ALPHA_SURVIVOR, ALPHA),
            (BETA_OBSERVATION, BETA_SURVIVOR, BETA),
        ):
            connection.execute(
                observation_sql,
                {
                    "observation_id": observation_id,
                    "principal_id": principal,
                    "observed_value": f"Synthetic {observation_id}",
                    "normalized_value": observation_id,
                    "source_id": f"src_{observation_id}",
                    "source_object_id": f"sobj_{observation_id}",
                    "source_version_id": f"sver_{observation_id}",
                    "observed_at": WHEN,
                    "recorded_at": WHEN,
                    "entity_id": entity_id,
                },
            )

        proposal_sql = text(
            f"INSERT INTO {SCHEMA}.entity_proposals (proposal_id, principal_id, kind, state, "
            "payload, observation_ids, proposed_at, proposed_by, decided_by, decided_at, "
            "method, method_version, dedupe_sha256, review_case_id, accepted_record_type, "
            "accepted_record_id, accepted_record_version) VALUES (:proposal_id, :principal_id, "
            "'record_alias', 'accepted', CAST(:payload AS jsonb), CAST(:observation_ids AS jsonb), "
            ":proposed_at, 'synthetic-operator', 'synthetic-operator', :decided_at, 'rule', "
            "'rule-v1', :dedupe_sha256, :review_case_id, 'alias', :accepted_record_id, 1)"
        )
        decision_sql = text(
            f"INSERT INTO {SCHEMA}.entity_proposal_review_decisions (decision_id, proposal_id, "
            "review_case_id, principal_id, sequence, disposition, correlation_id, audit_id, "
            "decided_at) VALUES (:decision_id, :proposal_id, :review_case_id, :principal_id, 1, "
            "'accept', :correlation_id, :audit_id, :decided_at)"
        )
        for proposal_id, decision_id, review_case, alias_id, principal, tag in (
            (ALPHA_PROPOSAL, ALPHA_DECISION, ALPHA_REVIEW_CASE, ALPHA_PRIMARY_ALIAS, ALPHA, "a"),
            (BETA_PROPOSAL, BETA_DECISION, BETA_REVIEW_CASE, BETA_PRIMARY_ALIAS, BETA, "b"),
        ):
            connection.execute(
                proposal_sql,
                {
                    "proposal_id": proposal_id,
                    "principal_id": principal,
                    "payload": json.dumps({"alias_id": alias_id}),
                    "observation_ids": json.dumps([]),
                    "proposed_at": WHEN,
                    "decided_at": LATER,
                    "dedupe_sha256": _sha256(proposal_id),
                    "review_case_id": review_case,
                    "accepted_record_id": alias_id,
                },
            )
            connection.execute(
                decision_sql,
                {
                    "decision_id": decision_id,
                    "proposal_id": proposal_id,
                    "review_case_id": review_case,
                    "principal_id": principal,
                    "correlation_id": f"corr_{tag}decision00001",
                    "audit_id": f"audit_{tag}decision0001",
                    "decided_at": LATER,
                },
            )

        memory_sql = text(
            f"INSERT INTO {SCHEMA}.relationship_memories (memory_id, principal_id, "
            "subject_entity_id, memory_kind, lifecycle_state, current_version_id, "
            "current_version_number, version, pinned, created_at, updated_at) VALUES "
            "(:memory_id, :principal_id, :subject_entity_id, 'general_note', 'active', "
            ":current_version_id, 1, 1, false, :created_at, :updated_at)"
        )
        version_sql = text(
            f"INSERT INTO {SCHEMA}.relationship_memory_versions (memory_version_id, memory_id, "
            "principal_id, version_number, statement_text, statement_sha256, memory_kind, "
            "authority, classification, cloud_eligible, created_by_actor, recorded_at, "
            "idempotency_key, correlation_id) VALUES (:memory_version_id, :memory_id, "
            ":principal_id, 1, :statement_text, :statement_sha256, 'general_note', "
            "'user_authored_private_note', 'synthetic_test', false, 'user', :recorded_at, "
            ":idempotency_key, :correlation_id)"
        )
        for memory_id, version_id, subject, principal, tag in (
            (ALPHA_SURVIVOR_MEMORY, ALPHA_SURVIVOR_MEMORY_VERSION, ALPHA_SURVIVOR, ALPHA, "a1"),
            (ALPHA_MERGED_MEMORY, ALPHA_MERGED_MEMORY_VERSION, ALPHA_MERGED_AWAY, ALPHA, "a2"),
            (BETA_MEMORY, BETA_MEMORY_VERSION, BETA_SURVIVOR, BETA, "b1"),
        ):
            statement = f"Synthetic note about {subject}."
            connection.execute(
                memory_sql,
                {
                    "memory_id": memory_id,
                    "principal_id": principal,
                    "subject_entity_id": subject,
                    "current_version_id": version_id,
                    "created_at": WHEN,
                    "updated_at": WHEN,
                },
            )
            connection.execute(
                version_sql,
                {
                    "memory_version_id": version_id,
                    "memory_id": memory_id,
                    "principal_id": principal,
                    "statement_text": statement,
                    "statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
                    "recorded_at": WHEN,
                    "idempotency_key": f"seed-{memory_id}",
                    "correlation_id": f"corr_{tag}memory000001",
                },
            )

        context_sql = text(
            f"INSERT INTO {SCHEMA}.relationship_memory_context_links (context_link_id, "
            "memory_version_id, principal_id, target_type, target_id, role, authority, "
            "created_at) VALUES (:context_link_id, :memory_version_id, :principal_id, "
            ":target_type, :target_id, :role, :authority, :created_at)"
        )
        for link_id, version_id, principal, target_type, target_id, role, authority in (
            (
                ALPHA_SURVIVOR_CONTEXT_LINK,
                ALPHA_SURVIVOR_MEMORY_VERSION,
                ALPHA,
                "entity",
                ALPHA_SURVIVOR,
                "related_to",
                "user_confirmed",
            ),
            (
                ALPHA_MERGED_CONTEXT_LINK,
                ALPHA_MERGED_MEMORY_VERSION,
                ALPHA,
                "entity",
                ALPHA_MERGED_AWAY,
                "arose_from",
                "deterministic",
            ),
            (
                ALPHA_TASK_CONTEXT_LINK,
                ALPHA_SURVIVOR_MEMORY_VERSION,
                ALPHA,
                "task",
                ALPHA_TASK,
                "applies_in",
                "deterministic",
            ),
            (
                BETA_CONTEXT_LINK,
                BETA_MEMORY_VERSION,
                BETA,
                "entity",
                BETA_SURVIVOR,
                "related_to",
                "user_confirmed",
            ),
        ):
            connection.execute(
                context_sql,
                {
                    "context_link_id": link_id,
                    "memory_version_id": version_id,
                    "principal_id": principal,
                    "target_type": target_type,
                    "target_id": target_id,
                    "role": role,
                    "authority": authority,
                    "created_at": WHEN,
                },
            )

        memory_proposal_sql = text(
            f"INSERT INTO {SCHEMA}.relationship_memory_proposals (memory_proposal_id, "
            "principal_id, subject_entity_id, proposed_kind, proposed_statement, "
            "proposed_statement_sha256, state, method, method_version, classification, "
            "proposed_at, review_case_id, expected_subject_version, dedupe_sha256, "
            "context_links) VALUES (:memory_proposal_id, :principal_id, :subject_entity_id, "
            "'general_note', :proposed_statement, :proposed_statement_sha256, 'needs_review', "
            "'rule', 'rule-v1', 'synthetic_test', :proposed_at, NULL, 1, :dedupe_sha256, "
            "CAST(:context_links AS jsonb))"
        )
        for proposal_id, subject, principal, extra_target in (
            (ALPHA_MEMORY_PROPOSAL, ALPHA_MERGED_AWAY, ALPHA, ALPHA_TASK),
            (BETA_MEMORY_PROPOSAL, BETA_SURVIVOR, BETA, "tsk_betatask00000001"),
        ):
            statement = f"Synthetic proposed note about {subject}."
            connection.execute(
                memory_proposal_sql,
                {
                    "memory_proposal_id": proposal_id,
                    "principal_id": principal,
                    "subject_entity_id": subject,
                    "proposed_statement": statement,
                    "proposed_statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
                    "proposed_at": WHEN,
                    "dedupe_sha256": _sha256(proposal_id),
                    "context_links": json.dumps(
                        [
                            {"target_type": "entity", "target_id": subject, "role": "related_to"},
                            {
                                "target_type": "task",
                                "target_id": extra_target,
                                "role": "applies_in",
                            },
                        ]
                    ),
                },
            )

        if not merges:
            return

        preview_sql = text(
            f"INSERT INTO {SCHEMA}.entity_identity_previews (preview_id, principal_id, "
            "operation_type, survivor_entity_id, expected_survivor_version, merged_away, "
            "preview_digest, conflict_digest, created_by, actor_class, created_at, expires_at, "
            "consumed_at, plan_digest) VALUES (:preview_id, :principal_id, 'merge', "
            ":survivor_entity_id, 2, CAST(:merged_away AS jsonb), :preview_digest, "
            ":conflict_digest, 'synthetic-operator', 'user', :created_at, :expires_at, "
            ":consumed_at, :plan_digest)"
        )
        operation_sql = text(
            f"INSERT INTO {SCHEMA}.entity_identity_operations (identity_operation_id, "
            "principal_id, operation_type, survivor_entity_id, merged_entity_ids, preview_id, "
            "preview_digest, idempotency_key, request_digest, performed_by, actor_class, "
            "correlation_id, audit_id, receipt_id, state, started_at, completed_at) VALUES "
            "(:identity_operation_id, :principal_id, 'merge', :survivor_entity_id, "
            "CAST(:merged_entity_ids AS jsonb), :preview_id, :preview_digest, :idempotency_key, "
            ":request_digest, 'synthetic-operator', 'user', :correlation_id, :audit_id, "
            ":receipt_id, 'completed', :started_at, :completed_at)"
        )
        effect_sql = text(
            f"INSERT INTO {SCHEMA}.entity_identity_effects (effect_id, identity_operation_id, "
            "principal_id, sequence, record_family, record_id, effect_kind, before_state, "
            "after_state, before_sha256, after_sha256, recorded_at) VALUES (:effect_id, "
            ":identity_operation_id, :principal_id, :sequence, :record_family, :record_id, "
            ":effect_kind, CAST(:before_state AS jsonb), CAST(:after_state AS jsonb), "
            ":before_sha256, :after_sha256, :recorded_at)"
        )
        for preview_id, operation_id, survivor, merged, principal, ledger, tag in (
            (
                ALPHA_PREVIEW,
                ALPHA_MERGE,
                ALPHA_SURVIVOR,
                ALPHA_MERGED_AWAY,
                ALPHA,
                ALPHA_LEDGER,
                "a",
            ),
            (BETA_PREVIEW, BETA_MERGE, BETA_SURVIVOR, BETA_MERGED_AWAY, BETA, BETA_LEDGER, "b"),
        ):
            connection.execute(
                preview_sql,
                {
                    "preview_id": preview_id,
                    "principal_id": principal,
                    "survivor_entity_id": survivor,
                    "merged_away": json.dumps([{"entity_id": merged, "version": 1}]),
                    "preview_digest": _sha256(preview_id),
                    "conflict_digest": _sha256(f"conflict-{preview_id}"),
                    "created_at": WHEN,
                    "expires_at": WHEN + timedelta(minutes=15),
                    "consumed_at": WHEN,
                    "plan_digest": _sha256(f"plan-{preview_id}"),
                },
            )
            connection.execute(
                operation_sql,
                {
                    "identity_operation_id": operation_id,
                    "principal_id": principal,
                    "survivor_entity_id": survivor,
                    "merged_entity_ids": json.dumps([merged]),
                    "preview_id": preview_id,
                    "preview_digest": _sha256(preview_id),
                    "idempotency_key": f"seed-{operation_id}",
                    "request_digest": _sha256(f"request-{operation_id}"),
                    "correlation_id": f"corr_{tag}merge000000001",
                    "audit_id": f"audit_{tag}merge00000001",
                    "receipt_id": f"rcpt_{tag}merge000000001",
                    "started_at": WHEN,
                    "completed_at": LATER,
                },
            )
            rows = _effect_rows(operation_id, principal, ledger)
            if gapped:
                # One hole, exactly where `_settle_completed_merges` looks for it.
                rows = [row for row in rows if row["sequence"] != 2]
            for row in rows:
                connection.execute(effect_sql, row)


# --- reading the migrated database -------------------------------------------


def _recomputed_digest(connection: Connection, operation_id: str) -> str:
    """`effects_digest_for` over the ledger, through the domain's own type.

    Reading the rows back into `IdentityEffect` is deliberate. The constructor
    recomputes both state digests and refuses a row whose stored digest does not
    match its stored state, so this is not only "the same JSON encoding" -- it is
    "a ledger the running application would accept", which is what a split
    admitted after this upgrade has to be able to do.
    """
    rows = (
        connection.execute(
            text(
                f"SELECT effect_id, identity_operation_id, principal_id, sequence, record_family, "
                f"record_id, effect_kind, before_state, after_state, before_sha256, after_sha256, "
                f"recorded_at FROM {SCHEMA}.entity_identity_effects "
                "WHERE identity_operation_id = :operation_id ORDER BY sequence"
            ),
            {"operation_id": operation_id},
        )
        .mappings()
        .all()
    )
    return effects_digest_for(
        IdentityEffect(
            effect_id=row["effect_id"],
            identity_operation_id=row["identity_operation_id"],
            principal_id=row["principal_id"],
            sequence=row["sequence"],
            family=IdentityEffectFamily(row["record_family"]),
            record_id=row["record_id"],
            kind=IdentityEffectKind(row["effect_kind"]),
            before_state=row["before_state"],
            after_state=row["after_state"],
            before_sha256=row["before_sha256"],
            after_sha256=row["after_sha256"],
            recorded_at=row["recorded_at"],
        )
        for row in rows
    )


def _settlement(connection: Connection, operation_id: str) -> Mapping[str, Any]:
    return (
        connection.execute(
            text(
                f"SELECT effect_count, effects_digest FROM {SCHEMA}.entity_identity_operations "
                "WHERE identity_operation_id = :operation_id"
            ),
            {"operation_id": operation_id},
        )
        .mappings()
        .one()
    )


def _names(connection: Connection, query: str, **params: object) -> set[str]:
    return set(connection.execute(text(query), params).scalars())


def _triggers(connection: Connection) -> set[str]:
    return _names(
        connection,
        "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND NOT t.tgisinternal",
        schema=SCHEMA,
    )


def _tables(connection: Connection) -> set[str]:
    return _names(
        connection,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema",
        schema=SCHEMA,
    )


def _indexes(connection: Connection) -> set[str]:
    return _names(
        connection,
        "SELECT indexname FROM pg_indexes WHERE schemaname = :schema",
        schema=SCHEMA,
    )


def _check_definition(connection: Connection, constraint: str) -> str:
    return connection.execute(
        text(
            "SELECT pg_get_constraintdef(pg_constraint.oid) FROM pg_constraint "
            "JOIN pg_class ON pg_class.oid = pg_constraint.conrelid "
            "JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace "
            "WHERE pg_namespace.nspname = :schema AND conname = :constraint"
        ),
        {"schema": SCHEMA, "constraint": constraint},
    ).scalar_one()


def _schema_snapshot(connection: Connection) -> dict[str, list[tuple[Any, ...]]]:
    """Every column, constraint, index and trigger the `knowledge` schema holds."""
    queries = {
        "columns": (
            "SELECT table_name, column_name, ordinal_position, data_type, is_nullable, "
            "column_default, character_maximum_length, numeric_precision "
            "FROM information_schema.columns WHERE table_schema = :schema "
            "ORDER BY table_name, ordinal_position"
        ),
        "constraints": (
            "SELECT c.relname, con.conname, pg_get_constraintdef(con.oid), con.convalidated "
            "FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema ORDER BY 1, 2"
        ),
        "indexes": (
            "SELECT tablename, indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = :schema ORDER BY 1, 2"
        ),
        "triggers": (
            "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND NOT t.tgisinternal ORDER BY 1, 2"
        ),
    }
    return {
        name: [tuple(row) for row in connection.execute(text(query), {"schema": SCHEMA})]
        for name, query in queries.items()
    }


def _migrated(disposable: BuildDatabase, *, merges: bool = True) -> Disposable:
    """A seeded predecessor database carried online to the corrective head."""
    database = disposable(PREDECESSOR_DATABASE, PREDECESSOR)
    _seed_predecessor(database.engine, merges=merges)
    database.upgrade("head")
    return database


# --- the chain itself --------------------------------------------------------


def test_the_chain_still_reaches_the_corrective_head_from_the_predecessor() -> None:
    """The two revisions between the corrective head and the supported predecessor.

    Deliberately not "`CORRECTIVE_HEAD` is the chain head", for the reason
    `test_the_entity_revision_is_in_the_chain_on_the_goodnotes_revision` gives
    for the same shape of claim: that property is true only until the next
    revision is written, and asserting it makes every later work package edit
    this file. `7e114f822af2` (RI-ENT-WP-02) is additive on `CORRECTIVE_HEAD`
    and is now the actual head; what this test still guards is that
    `CORRECTIVE_HEAD` remains reachable with its own lineage to the supported
    predecessor unbroken, whatever now sits above it.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert CORRECTIVE_HEAD in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(CORRECTIVE_HEAD).down_revision == IDENTITY_RECOVERY
    assert script.get_revision(IDENTITY_RECOVERY).down_revision == PREDECESSOR


# --- the backfill ------------------------------------------------------------


def test_the_completed_merges_settle_to_the_applications_canonical_digest(
    disposable: BuildDatabase,
) -> None:
    """The one thing a from-empty upgrade cannot say anything about.

    `_settle_completed_merges` writes `effect_count` and `effects_digest` for
    every completed merge that has neither. What makes the value right rather
    than merely present is that it equals `effects_digest_for` over the same
    ledger -- the function the application uses to admit a split against a merge
    it did not perform. Both Principals settle, and to different digests, so the
    backfill is not writing one value over everything it finds.
    """
    database = _migrated(disposable)
    with database.engine.begin() as connection:
        alpha = _settlement(connection, ALPHA_MERGE)
        beta = _settlement(connection, BETA_MERGE)

        assert alpha["effect_count"] == len(ALPHA_LEDGER)
        assert beta["effect_count"] == len(BETA_LEDGER)
        assert alpha["effects_digest"] == _recomputed_digest(connection, ALPHA_MERGE)
        assert beta["effects_digest"] == _recomputed_digest(connection, BETA_MERGE)
        assert alpha["effects_digest"] != beta["effects_digest"]

        # The settlement is now required, not merely recorded: the revision adds
        # the CHECK after the backfill, so unsettling a completed operation is
        # refused rather than accepted and forgotten.
        with (
            pytest.raises(IntegrityError, match="a_completed_identity_operation_has_settled"),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.entity_identity_operations "
                    "SET effect_count = NULL, effects_digest = NULL "
                    "WHERE identity_operation_id = :operation_id"
                ),
                {"operation_id": ALPHA_MERGE},
            )


def test_the_backfill_settles_nothing_without_a_completed_merge(disposable: BuildDatabase) -> None:
    """The control that makes the test above non-vacuous.

    Same seed, same online upgrade, merge removed. `_settle_completed_merges`
    selects nothing and writes nothing, so `effect_count` stays NULL everywhere
    -- which is to say the equality asserted above is reachable only because the
    seed put a completed merge in front of the backfill, and not because the
    upgrade sets those columns for some other reason.
    """
    database = _migrated(disposable, merges=False)
    with database.engine.connect() as connection:
        settled = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_identity_operations "
                "WHERE effect_count IS NOT NULL OR effects_digest IS NOT NULL"
            )
        ).scalar_one()
        operations = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.entity_identity_operations")
        ).scalar_one()
    assert operations == 0
    assert settled == 0


def test_a_gapped_effect_ledger_refuses_the_upgrade(disposable: BuildDatabase) -> None:
    """The backfill reads the ledger it settles, and refuses one with a hole.

    Second evidence that the assertions above bind: remove one sequence from the
    middle of the seeded ledger and the upgrade fails, which it could not do if
    the migration were not actually reading those rows.
    """
    database = disposable(PREDECESSOR_DATABASE, PREDECESSOR)
    _seed_predecessor(database.engine, gapped=True)
    with pytest.raises(RuntimeError, match="one contiguous effect ledger"):
        database.upgrade("head")


# --- the origin bindings -----------------------------------------------------


def test_the_relationship_memory_planes_gain_their_origin_bindings(
    disposable: BuildDatabase,
) -> None:
    """Every memory row learns where it came from, from its own subject.

    Three memories on three different subjects, so "backfilled from the subject"
    is distinguishable from "backfilled to a constant". The proposal plane's
    embedded `context_links` are backfilled too, and only for entity links --
    which is the half a JSONB rewrite is most likely to get wrong.
    """
    database = _migrated(disposable)
    with database.engine.begin() as connection:
        nullability = dict(
            connection.execute(
                text(
                    "SELECT table_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = :schema AND column_name = 'origin_subject_entity_id' "
                    "ORDER BY table_name"
                ),
                {"schema": SCHEMA},
            ).all()
        )
        assert nullability["relationship_memories"] == "NO"
        assert nullability["relationship_memory_proposals"] == "NO"

        memories = dict(
            connection.execute(
                text(
                    f"SELECT memory_id, origin_subject_entity_id FROM {SCHEMA}."
                    "relationship_memories ORDER BY memory_id"
                )
            ).all()
        )
        assert memories == {
            ALPHA_SURVIVOR_MEMORY: ALPHA_SURVIVOR,
            ALPHA_MERGED_MEMORY: ALPHA_MERGED_AWAY,
            BETA_MEMORY: BETA_SURVIVOR,
        }

        proposals = dict(
            connection.execute(
                text(
                    f"SELECT memory_proposal_id, origin_subject_entity_id FROM {SCHEMA}."
                    "relationship_memory_proposals ORDER BY memory_proposal_id"
                )
            ).all()
        )
        assert proposals == {
            ALPHA_MEMORY_PROPOSAL: ALPHA_MERGED_AWAY,
            BETA_MEMORY_PROPOSAL: BETA_SURVIVOR,
        }

        links = dict(
            connection.execute(
                text(
                    f"SELECT context_link_id, origin_subject_entity_id FROM {SCHEMA}."
                    "relationship_memory_context_links ORDER BY context_link_id"
                )
            ).all()
        )
        assert links == {
            ALPHA_SURVIVOR_CONTEXT_LINK: ALPHA_SURVIVOR,
            ALPHA_MERGED_CONTEXT_LINK: ALPHA_MERGED_AWAY,
            ALPHA_TASK_CONTEXT_LINK: None,
            BETA_CONTEXT_LINK: BETA_SURVIVOR,
        }

        embedded = connection.execute(
            text(
                f"SELECT context_links FROM {SCHEMA}.relationship_memory_proposals "
                "WHERE memory_proposal_id = :proposal_id"
            ),
            {"proposal_id": ALPHA_MEMORY_PROPOSAL},
        ).scalar_one()
        assert embedded == [
            {
                "role": "related_to",
                "target_id": ALPHA_MERGED_AWAY,
                "target_type": "entity",
                "origin_subject_entity_id": ALPHA_MERGED_AWAY,
            },
            {"role": "applies_in", "target_id": ALPHA_TASK, "target_type": "task"},
        ]

        assert set(ORIGIN_TRIGGERS) <= _triggers(connection)
        with (
            pytest.raises(DBAPIError, match="origin subject is immutable"),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.relationship_memories "
                    "SET origin_subject_entity_id = :other WHERE memory_id = :memory_id"
                ),
                {"other": ALPHA_SURVIVOR, "memory_id": ALPHA_MERGED_MEMORY},
            )


# --- the widened vocabularies and the corrective objects ---------------------


def _admit_a_split(connection: Connection, *, suffix: str, families: Sequence[str]) -> str:
    """Write one governed split against the seeded Alpha merge, and settle it.

    Written as inserts rather than as a parse of `pg_constraint`, for the reason
    `tests/database/test_phase_b_audit_vocabulary_migration.py` gives: a parse
    passes on a CHECK that names the right literals in a predicate that never
    fires.
    """
    preview_id = f"eipv_split{suffix}0000001"
    operation_id = f"eiop_split{suffix}0000001"
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entity_identity_previews (preview_id, principal_id, "
            "operation_type, survivor_entity_id, expected_survivor_version, merged_away, "
            "preview_digest, conflict_digest, created_by, actor_class, created_at, expires_at, "
            "plan_digest, source_identity_operation_id) VALUES (:preview_id, :principal, "
            "'split', :survivor, 3, CAST(:merged_away AS jsonb), :digest, :conflict, "
            "'synthetic-operator', 'user', :created_at, :expires_at, :plan, :source)"
        ),
        {
            "preview_id": preview_id,
            "principal": ALPHA,
            "survivor": ALPHA_SURVIVOR,
            "merged_away": json.dumps([{"entity_id": ALPHA_MERGED_AWAY, "version": 2}]),
            "digest": _sha256(preview_id),
            "conflict": _sha256(f"conflict-{preview_id}"),
            "created_at": LATER,
            "expires_at": LATER + timedelta(minutes=15),
            "plan": _sha256(f"plan-{preview_id}"),
            "source": ALPHA_MERGE,
        },
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entity_identity_operations (identity_operation_id, "
            "principal_id, operation_type, survivor_entity_id, merged_entity_ids, preview_id, "
            "preview_digest, idempotency_key, request_digest, performed_by, actor_class, "
            "correlation_id, audit_id, receipt_id, state, started_at, "
            "source_identity_operation_id) VALUES (:operation_id, :principal, 'split', "
            ":survivor, CAST(:merged AS jsonb), :preview_id, :digest, :key, :request, "
            "'synthetic-operator', 'user', :correlation_id, :audit_id, :receipt_id, "
            "'in_progress', :started_at, :source)"
        ),
        {
            "operation_id": operation_id,
            "principal": ALPHA,
            "survivor": ALPHA_SURVIVOR,
            "merged": json.dumps([ALPHA_MERGED_AWAY]),
            "preview_id": preview_id,
            "digest": _sha256(preview_id),
            "key": f"split-{suffix}",
            "request": _sha256(f"request-{operation_id}"),
            "correlation_id": f"corr_split{suffix}00000001",
            "audit_id": f"audit_split{suffix}0000001",
            "receipt_id": f"rcpt_split{suffix}00000001",
            "started_at": LATER,
            "source": ALPHA_MERGE,
        },
    )
    effect_sql = text(
        f"INSERT INTO {SCHEMA}.entity_identity_effects (effect_id, identity_operation_id, "
        "principal_id, sequence, record_family, record_id, effect_kind, before_state, "
        "after_state, before_sha256, after_sha256, recorded_at) VALUES (:effect_id, "
        ":identity_operation_id, :principal_id, :sequence, :record_family, :record_id, "
        ":effect_kind, CAST(:before_state AS jsonb), CAST(:after_state AS jsonb), "
        ":before_sha256, :after_sha256, :recorded_at)"
    )
    for sequence, family in enumerate(families, start=1):
        record_id = f"{_PREFIX_FOR_FAMILY[family]}_{sequence:02d}{suffix}splitrecord"
        before: dict[str, object] = {"family": family, "state": "before"}
        after: dict[str, object] = {"family": family, "state": "after"}
        connection.execute(
            effect_sql,
            {
                "effect_id": f"eief_split{suffix}effect{sequence:02d}",
                "identity_operation_id": operation_id,
                "principal_id": ALPHA,
                "sequence": sequence,
                "record_family": family,
                "record_id": record_id,
                "effect_kind": "owner_reparented",
                "before_state": json.dumps(before),
                "after_state": json.dumps(after),
                "before_sha256": state_digest(before),
                "after_sha256": state_digest(after),
                "recorded_at": LATER,
            },
        )
    return operation_id


def test_the_widened_identity_vocabularies_admit_split_and_the_twelve_families(
    disposable: BuildDatabase,
) -> None:
    """`split` on both identity tables, and all twelve effect families, driven.

    The split is written against the merge the backfill settled, which is the
    sequence the remediation exists for: a merge performed before the upgrade,
    a split admitted after it, bound by the digest the upgrade computed.
    """
    database = _migrated(disposable)
    with database.engine.begin() as connection:
        operation_id = _admit_a_split(connection, suffix="a", families=RECORD_FAMILIES)
        stored = _names(
            connection,
            f"SELECT DISTINCT record_family FROM {SCHEMA}.entity_identity_effects "
            "WHERE identity_operation_id = :operation_id",
            operation_id=operation_id,
        )
        assert stored == set(RECORD_FAMILIES)

        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_identity_operations SET state = 'completed', "
                "completed_at = :at, effect_count = :count, effects_digest = :digest "
                "WHERE identity_operation_id = :operation_id"
            ),
            {
                "at": LATER,
                "count": len(RECORD_FAMILIES),
                "digest": _recomputed_digest(connection, operation_id),
                "operation_id": operation_id,
            },
        )

        # The widening widened; it did not open. Written as an insert because
        # the ledger carries `entity_identity_effects_are_append_only`, so an
        # update would be refused by the trigger and would say nothing at all
        # about the vocabulary.
        unknown: dict[str, object] = {"family": "not_a_family", "state": "before"}
        changed: dict[str, object] = {"family": "not_a_family", "state": "after"}
        with (
            pytest.raises(IntegrityError, match="an_identity_effect_family_is_known"),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.entity_identity_effects (effect_id, "
                    "identity_operation_id, principal_id, sequence, record_family, record_id, "
                    "effect_kind, before_state, after_state, before_sha256, after_sha256, "
                    "recorded_at) VALUES ('eief_splitaeffect99', :operation_id, :principal, 99, "
                    "'not_a_family', 'ent_99asplitrecord', 'owner_reparented', "
                    "CAST(:before_state AS jsonb), CAST(:after_state AS jsonb), :before_sha256, "
                    ":after_sha256, :recorded_at)"
                ),
                {
                    "operation_id": operation_id,
                    "principal": ALPHA,
                    "before_state": json.dumps(unknown),
                    "after_state": json.dumps(changed),
                    "before_sha256": state_digest(unknown),
                    "after_sha256": state_digest(changed),
                    "recorded_at": LATER,
                },
            )


def test_one_completed_split_per_source_merge_is_enforced(disposable: BuildDatabase) -> None:
    """The partial unique index exists and refuses the second completed split."""
    database = _migrated(disposable)
    with database.engine.begin() as connection:
        assert "one_completed_split_per_source_merge" in _indexes(connection)
        first = _admit_a_split(connection, suffix="a", families=("entity",))
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_identity_operations SET state = 'completed', "
                "completed_at = :at, effect_count = 1, effects_digest = :digest "
                "WHERE identity_operation_id = :operation_id"
            ),
            {"at": LATER, "digest": _recomputed_digest(connection, first), "operation_id": first},
        )
        second = _admit_a_split(connection, suffix="b", families=("entity",))
        with (
            pytest.raises(IntegrityError, match="one_completed_split_per_source_merge"),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.entity_identity_operations SET state = 'completed', "
                    "completed_at = :at, effect_count = 1, effects_digest = :digest "
                    "WHERE identity_operation_id = :operation_id"
                ),
                {
                    "at": LATER,
                    "digest": _recomputed_digest(connection, second),
                    "operation_id": second,
                },
            )


def test_the_corrective_head_objects_are_present_and_bind(disposable: BuildDatabase) -> None:
    """Everything `b727e870d45e` adds, over a database that arrived with data.

    The append-only trigger is driven against a *seeded* review decision rather
    than one written at head: a trigger added over an empty ledger and a trigger
    added over a ledger that already held rows are the same DDL and not the same
    evidence.
    """
    database = _migrated(disposable)
    with database.engine.begin() as connection:
        assert set(CORRECTIVE_TABLES) <= _tables(connection)
        assert set(CORRECTIVE_TRIGGERS) <= _triggers(connection)
        assert "limitations" in _names(
            connection,
            "SELECT column_name FROM information_schema.columns WHERE table_schema = :schema "
            "AND table_name = 'entity_reenrichment_work'",
            schema=SCHEMA,
        )
        assert "'partial'" in _check_definition(connection, "a_reenrichment_state_is_known")
        assert "'reenrichment'" in _check_definition(connection, "worker_plane_is_known")

        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_reenrichment_work (work_id, principal_id, trigger, "
                "cause_record_id, binding_sha256, input_versions, producer_versions, "
                "policy_version, state, next_attempt_at, limitations, created_at, updated_at, "
                "completed_at) VALUES (:work_id, :principal, 'corrected_identity', :cause, "
                ":binding, '[]'::jsonb, '[]'::jsonb, 'policy-v1', 'partial', :at, "
                "ARRAY[:limitation]::text[], :at, :at, :at)"
            ),
            {
                "work_id": "erwk_" + "0123456789abcdef01234567",
                "principal": ALPHA,
                "cause": ALPHA_MERGE,
                "binding": _sha256("reenrichment-binding"),
                "at": LATER,
                "limitation": "synthetic partial coverage",
            },
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.worker_heartbeats (worker_owner, principal_id, plane, "
                "started_at, heartbeat_at) VALUES ('synthetic-reenrichment', :principal, "
                "'reenrichment', :at, :at)"
            ),
            {"principal": ALPHA, "at": LATER},
        )

        with (
            pytest.raises(IntegrityError, match="append only"),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.entity_proposal_review_decisions "
                    "SET decided_at = decided_at WHERE decision_id = :decision_id"
                ),
                {"decision_id": ALPHA_DECISION},
            )
        with (
            pytest.raises(IntegrityError, match="append only"),
            connection.begin_nested(),
        ):
            connection.execute(
                text(
                    f"DELETE FROM {SCHEMA}.entity_proposal_review_decisions "
                    "WHERE decision_id = :decision_id"
                ),
                {"decision_id": BETA_DECISION},
            )


# --- what the two Principals kept --------------------------------------------


def test_both_principals_keep_their_records_and_stay_separated(disposable: BuildDatabase) -> None:
    """Every seeded row survives, under its own Principal, with no bleed.

    A data-carrying upgrade has two ways to be wrong that a from-empty upgrade
    cannot have: it can lose a row, and it can attribute one row's backfilled
    value to another Principal's record. Both are asked here, per table.
    """
    database = _migrated(disposable)
    expected: dict[str, dict[str, set[str]]] = {
        "entities:entity_id": {ALPHA: set(ALPHA_ENTITIES), BETA: set(BETA_ENTITIES)},
        "entity_aliases:alias_id": {
            ALPHA: {ALPHA_PRIMARY_ALIAS, ALPHA_REPARENTED_ALIAS},
            BETA: {BETA_PRIMARY_ALIAS, BETA_REPARENTED_ALIAS},
        },
        "entity_external_identifiers:identifier_id": {
            ALPHA: {ALPHA_IDENTIFIER},
            BETA: {BETA_IDENTIFIER},
        },
        "entity_assignments:assignment_id": {ALPHA: {ALPHA_ASSIGNMENT}, BETA: {BETA_ASSIGNMENT}},
        "entity_relationships:relationship_id": {
            ALPHA: {ALPHA_RELATIONSHIP},
            BETA: {BETA_RELATIONSHIP},
        },
        "entity_observations:observation_id": {
            ALPHA: {ALPHA_OBSERVATION},
            BETA: {BETA_OBSERVATION},
        },
        "entity_proposals:proposal_id": {ALPHA: {ALPHA_PROPOSAL}, BETA: {BETA_PROPOSAL}},
        "entity_proposal_review_decisions:decision_id": {
            ALPHA: {ALPHA_DECISION},
            BETA: {BETA_DECISION},
        },
        "relationship_memories:memory_id": {
            ALPHA: {ALPHA_SURVIVOR_MEMORY, ALPHA_MERGED_MEMORY},
            BETA: {BETA_MEMORY},
        },
        "relationship_memory_proposals:memory_proposal_id": {
            ALPHA: {ALPHA_MEMORY_PROPOSAL},
            BETA: {BETA_MEMORY_PROPOSAL},
        },
        "relationship_memory_context_links:context_link_id": {
            ALPHA: {
                ALPHA_SURVIVOR_CONTEXT_LINK,
                ALPHA_MERGED_CONTEXT_LINK,
                ALPHA_TASK_CONTEXT_LINK,
            },
            BETA: {BETA_CONTEXT_LINK},
        },
        "entity_identity_operations:identity_operation_id": {
            ALPHA: {ALPHA_MERGE},
            BETA: {BETA_MERGE},
        },
        "entity_identity_effects:effect_id": {
            ALPHA: {row["effect_id"] for row in _effect_rows(ALPHA_MERGE, ALPHA, ALPHA_LEDGER)},
            BETA: {row["effect_id"] for row in _effect_rows(BETA_MERGE, BETA, BETA_LEDGER)},
        },
    }
    with database.engine.connect() as connection:
        for target, by_principal in expected.items():
            table, key = target.split(":")
            for principal, identifiers in by_principal.items():
                stored = _names(
                    connection,
                    f"SELECT {key} FROM {SCHEMA}.{table} WHERE principal_id = :principal",
                    principal=principal,
                )
                assert stored == identifiers, f"{table} for {principal}"

        # The backfilled column is the one place a cross-Principal write would
        # land, because it is the only value this upgrade derives per row.
        crossings = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.relationship_memories WHERE (principal_id = "
                ":alpha AND origin_subject_entity_id = ANY(CAST(:beta_entities AS text[]))) "
                "OR (principal_id = :beta AND origin_subject_entity_id = "
                "ANY(CAST(:alpha_entities AS text[])))"
            ),
            {
                "alpha": ALPHA,
                "beta": BETA,
                "alpha_entities": list(ALPHA_ENTITIES),
                "beta_entities": list(BETA_ENTITIES),
            },
        ).scalar_one()
        assert crossings == 0

        principals = connection.execute(
            text(
                f"SELECT DISTINCT effect.principal_id, operation.principal_id "
                f"FROM {SCHEMA}.entity_identity_effects AS effect "
                f"JOIN {SCHEMA}.entity_identity_operations AS operation "
                "ON operation.identity_operation_id = effect.identity_operation_id"
            )
        ).all()
        assert all(effect == operation for effect, operation in principals)


# --- the predecessor path against a fresh build ------------------------------


def test_the_predecessor_path_and_a_fresh_build_denote_the_same_schema(
    disposable: BuildDatabase,
) -> None:
    """Every column, constraint, index and trigger in `knowledge`, both ways.

    Both paths run the same revision chain, so what this compares is whether
    *carrying data through it* changed the result -- an unvalidated constraint,
    an index that was not built, a column left nullable because a backfill found
    nothing to prove it could tighten. Those are the failures that only show up
    on a database that had rows in it.
    """
    migrated = _migrated(disposable)
    fresh = disposable(FRESH_DATABASE, "head")

    with migrated.engine.connect() as connection:
        upgraded_snapshot = _schema_snapshot(connection)
    with fresh.engine.connect() as connection:
        fresh_snapshot = _schema_snapshot(connection)

    differences = {
        name: (
            sorted(set(upgraded_snapshot[name]) - set(fresh_snapshot[name])),
            sorted(set(fresh_snapshot[name]) - set(upgraded_snapshot[name])),
        )
        for name in upgraded_snapshot
        if upgraded_snapshot[name] != fresh_snapshot[name]
    }
    assert differences == {}, f"predecessor path and fresh build disagree: {differences}"


# --- the round trip ----------------------------------------------------------


def test_the_corrective_revision_round_trips_over_carried_data(disposable: BuildDatabase) -> None:
    """Down one revision and back up, with both Principals' records in place.

    A downgrade that is only ever run against an empty database is a downgrade
    nobody has tested. This one runs over the seeded, settled, backfilled state.
    """
    database = _migrated(disposable)
    with database.engine.connect() as connection:
        assert set(CORRECTIVE_TABLES) <= _tables(connection)
        assert set(CORRECTIVE_TRIGGERS) <= _triggers(connection)

    database.downgrade(IDENTITY_RECOVERY)
    with database.engine.connect() as connection:
        assert set(CORRECTIVE_TABLES).isdisjoint(_tables(connection))
        assert set(CORRECTIVE_TRIGGERS).isdisjoint(_triggers(connection))
        assert "limitations" not in _names(
            connection,
            "SELECT column_name FROM information_schema.columns WHERE table_schema = :schema "
            "AND table_name = 'entity_reenrichment_work'",
            schema=SCHEMA,
        )
        # The settlement `8e1c4a7b2d90` performed is below this revision and stays.
        assert _settlement(connection, ALPHA_MERGE)["effect_count"] == len(ALPHA_LEDGER)

    database.upgrade("head")
    with database.engine.connect() as connection:
        assert set(CORRECTIVE_TABLES) <= _tables(connection)
        assert set(CORRECTIVE_TRIGGERS) <= _triggers(connection)
        assert _settlement(connection, BETA_MERGE)["effect_count"] == len(BETA_LEDGER)
        stamped = list(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
    # Not `[CORRECTIVE_HEAD]`, for the reason
    # `test_the_chain_still_reaches_the_corrective_head_from_the_predecessor`
    # gives: `database.upgrade("head")` stamps the chain's actual current head,
    # which a later work package may have moved past `CORRECTIVE_HEAD`.
    script = ScriptDirectory.from_config(_config())
    assert stamped == list(script.get_heads())
