"""`16f05c46b8c3` is what lets an `RI-ENT-WP-10`/`WP-11` request be audited at all.

`authorize` commits an `audit_events` row **before** the handler runs. So a
capability that is in the `Capability` enum and absent from the stored
`capability_is_known` CHECK answers `internal_error` against a migrated
database while every from-scratch test in the repository passes -- the trap
`tests/database/test_phase_b_audit_vocabulary_migration.py` records for Phase B,
arrived at again by two work packages that were each forbidden a revision of
their own. The revision that closes it is `16f05c46b8c3`, which admits
`RI-ENT-WP-10`'s five paged reads, `RI-ENT-WP-11`'s fifteen writes, and the five
record families those writes append to the mutation ledger under.

Nothing referenced that revision. What stood in its place was the whole-suite
comparison of stored vocabulary against `Capability` **at head** -- a true
statement, and one that says nothing about which revision makes it true or about
what happens either side of it. This module is the direct test: it drives all
three widened CHECKs with a real `INSERT` at head, downgrades exactly one
revision, drives the same inserts and requires them to be refused, and upgrades
again.

Written as inserts rather than as a parse of `pg_constraint`, because the shape
these packages can actually fail in is an insert being refused at request time,
and because a parse would pass on a CHECK that names the right literals in a
predicate that never fires.

All three CHECKs are driven separately, and the two record-family halves are
driven on **both** tables: `a_mutated_record_family_is_known` on
`entity_mutation_events` and `an_accepted_proposal_record_family_is_known` on
`entity_proposals` are two constraints built from one enum, and a revision that
widened one and forgot the other would leave a from-scratch database and a
migrated one enforcing different rules about one column. The proposal half has
no behavioural effect today -- `application/entity_promotion.py` maps no
proposal kind to any of the five new families, so this module writes a proposal
whose `kind` and whose `accepted_record_type` do not correspond, which the DDL
permits because the constraint under test is a closed set on one column and
nothing cross-checks the pair. That is the constraint this module is about.

`purpose_is_known` is deliberately not widened by this revision, and this module
does not claim it was. What it does claim is the direction that breaks a
request: every live `Purpose`, like every live `Capability`, is driven through
the stored CHECK at head, so a member added later without a revision reddens
here rather than in production.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import partial
from itertools import count
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.governance import MutationRecordFamily
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: Distinct from every other database-tier fixture's database, so this suite can
#: run beside them without one dropping what another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_ri_ent_wp_10_11_vocabulary_test"

#: This revision -- the edge this suite removes. Written out rather than
#: imported so current chain drift and historical identity are checked
#: independently.
REVISION: Final = "16f05c46b8c3"
#: The RI successor to this module's subject revision: `b8e4d1a6c073`
#: (RI-ENT-WP-12, backfilling one
#: `display`-typed `entity_names` row per active `entities` row), which was
#: written against `c99cd8ed8d1c` and re-parented onto `REVISION` once this
#: revision merged (RULING-M11), so the head this suite sees is that one and
#: `REVISION` is the link directly beneath it. Written out rather than derived
#: so chain drift fails here rather than passing.
HEAD_REVISION: Final = "b8e4d1a6c073"
#: PR192's graph-vocabulary admission directly above `HEAD_REVISION`.
GRAPH_REVISION: Final = "c3f8a1d07e94"
#: The additive GoodNotes migration directly above `GRAPH_REVISION`, and the
#: sole current chain head.
CURRENT_HEAD_REVISION: Final = "6a2f9d1c4b80"
#: What was head until `REVISION` stacked on it, and therefore the revision
#: this module downgrades to. This revision was written against `c99cd8ed8d1c`
#: and re-parented onto `UI-IMP-WP02`'s `2c00c9ac64bc` when `origin/main` merged
#: (RULING-M11): both had been written against `c99cd8ed8d1c`, so the pair would
#: otherwise have stood as two heads. `2c00c9ac64bc` adds WebAuthn credential,
#: challenge, recovery-code and opaque session tables in the `identity` schema
#: and widens none of the three `knowledge`-schema CHECKs this module exercises,
#: so downgrading to it leaves exactly the pre-`REVISION` vocabularies the
#: assertions below expect.
PREVIOUS_REVISION: Final = "2c00c9ac64bc"
#: What was head until `PREVIOUS_REVISION` stacked on it (`RI-ENT-WP-08`'s
#: blocker-clearing pass, renaming the seeded `entity_relationship_types` row
#: `design_coordinates_with` to `design_coordination_with`).
SECOND_TO_PREVIOUS_REVISION: Final = "c99cd8ed8d1c"
#: What was head until `SECOND_TO_PREVIOUS_REVISION` stacked on it
#: (`RI-ENT-WP-07`, adding entity_assertions/entity_assertion_evidence).
THIRD_TO_PREVIOUS_REVISION: Final = "1cda4d536268"

#: What the revision admits to `capability_is_known`: `RI-ENT-WP-10`'s five paged
#: reads and `RI-ENT-WP-11`'s fifteen writes. Restated here for the reason the
#: revision's own literals are restated, and compared against `Capability` below
#: so a *domain* rename cannot drift away from it either.
ADMITTED_CAPABILITIES: Final[tuple[str, ...]] = (
    "entities.addresses.add",
    "entities.addresses.list",
    "entities.addresses.retire",
    "entities.addresses.revise",
    "entities.affiliations.create",
    "entities.affiliations.end",
    "entities.affiliations.revise",
    "entities.communication.add",
    "entities.communication.list",
    "entities.communication.retire",
    "entities.communication.revise",
    "entities.names.add",
    "entities.names.list",
    "entities.names.retire",
    "entities.names.supersede",
    "entities.participations.create",
    "entities.participations.end",
    "entities.participations.list",
    "entities.participations.revise",
    "entities.profile",
)

#: What the revision admits to both record-family CHECKs. The five Entity-bound
#: families `RI-ENT-WP-11`'s fifteen writes record under.
ADMITTED_RECORD_FAMILIES: Final[tuple[str, ...]] = (
    "address",
    "communication_method",
    "name",
    "person_organization_affiliation",
    "project_participation",
)

#: A capability, a purpose and a record family that predate this revision, used
#: as the control: each must be admitted on both sides of the downgrade, so a
#: refusal below is evidence about this revision's literals and not about a
#: table that stopped accepting anything.
SETTLED_CAPABILITY: Final = "capabilities.get"
SETTLED_PURPOSE: Final = "status_observation"
SETTLED_RECORD_FAMILY: Final = "entity"

#: Names nothing declares, in each of the two vocabularies. The widening widened;
#: it did not open, and without these the acceptance tests above are vacuous.
UNDECLARED_CAPABILITY: Final = "nope.nope"
UNDECLARED_RECORD_FAMILY: Final = "nope_family"

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
WHEN: Final = datetime(2026, 9, 2, 12, tzinfo=UTC)

#: `audit_policy_version_is_a_known_shape` matches `POLICY_VERSION_PATTERN`, so
#: a placeholder would be refused by a *shape* rule and this module would be
#: reporting the wrong constraint.
POLICY_VERSION: Final = "policy-v1"

#: `a_mutation_request_digest_is_a_sha256_digest` admits `^[0-9a-f]{64}$`. The
#: derivation is not what is under test here, so any well-shaped digest does.
REQUEST_DIGEST: Final = "a" * 64


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


#: A row identifier counter. `audit_id`, `correlation_id`, `event_id`,
#: `record_id` and `proposal_id` all carry the opaque-identifier CHECK, whose
#: suffix admits `[A-Za-z0-9]{8,64}` and no separator, so a readable slug of the
#: capability or family name would be refused by the shape rule before the
#: vocabulary rule was reached -- and this module would be reporting the wrong
#: constraint. A counter keeps every row distinct and every identifier legal.
_ROWS = count(1)


def _index() -> str:
    """Sixteen hex digits: distinct per row, and clears the eight-character floor."""
    return f"{next(_ROWS):016x}"


def _audit(engine: Engine, *, capability: str, purpose: str) -> None:
    """One audit row, exactly as `authorize` writes one before a handler runs."""
    index = _index()
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.audit_events "  # noqa: S608
                "(audit_id, correlation_id, principal_id, capability, purpose, outcome, "
                " policy_version, scope_source_id_count, recorded_at) "
                "VALUES (:audit_id, :correlation_id, :principal_id, :capability, :purpose, "
                " 'allowed', :policy_version, 0, :recorded_at)"
            ),
            {
                "audit_id": f"audit_{index}",
                "correlation_id": f"corr_{index}",
                "principal_id": PRINCIPAL,
                "capability": capability,
                "purpose": purpose,
                "policy_version": POLICY_VERSION,
                "recorded_at": WHEN,
            },
        )


def _mutation(engine: Engine, *, record_family: str) -> None:
    """One mutation-ledger row, as a governed entity write appends one.

    A creation: no prior version, version one, and the default authority and
    actor class a user's own write carries. Every column other than
    `record_family` is held at a value the table's other CHECKs admit, so the
    only rule this row can be refused by is the vocabulary one.
    """
    index = _index()
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_mutation_events "  # noqa: S608
                "(event_id, principal_id, capability, record_family, record_id, prior_version, "
                " new_version, authority, idempotency_key, request_digest, correlation_id, "
                " audit_id, actor_class, recorded_at) "
                "VALUES (:event_id, :principal_id, :capability, :record_family, :record_id, NULL, "
                " 1, 'user_confirmed_assertion', :idempotency_key, :request_digest, "
                " :correlation_id, :audit_id, 'user', :recorded_at)"
            ),
            {
                "event_id": f"emut_{index}",
                "principal_id": PRINCIPAL,
                "capability": SETTLED_CAPABILITY,
                "record_family": record_family,
                "record_id": f"rec_{index}",
                "idempotency_key": f"key-{index}",
                "request_digest": REQUEST_DIGEST,
                "correlation_id": f"corr_{index}",
                "audit_id": f"audit_{index}",
                "recorded_at": WHEN,
            },
        )


def _accepted_proposal(engine: Engine, *, record_family: str) -> None:
    """One accepted proposal naming the record it produced.

    `kind` is `record_alias` and does not correspond to `accepted_record_type`,
    deliberately: `an_accepted_proposal_record_family_is_known` is a closed set
    on one column and no DDL rule pairs the two, so a row that made them agree
    would be testing a correspondence the server does not enforce and would be
    unwritable for the five families under test -- no proposal kind promotes to
    any of them. Every other column is held where this table's twenty-odd other
    CHECKs admit it, so the only rule this row can be refused by is the
    vocabulary one.
    """
    index = _index()
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_proposals "  # noqa: S608
                "(proposal_id, principal_id, kind, state, payload, observation_ids, proposed_at, "
                " proposed_by, method, method_version, dedupe_sha256, accepted_record_type, "
                " accepted_record_id, accepted_record_version, decided_by, decided_at) "
                "VALUES (:proposal_id, :principal_id, 'record_alias', 'accepted', "
                " CAST('{}' AS jsonb), CAST('[]' AS jsonb), :proposed_at, 'promotion', "
                " 'deterministic', '1', :dedupe_sha256, :accepted_record_type, "
                " :accepted_record_id, 1, 'a reviewer', :decided_at)"
            ),
            {
                "proposal_id": f"eprp_{index}",
                "principal_id": PRINCIPAL,
                "proposed_at": WHEN,
                "dedupe_sha256": f"{next(_ROWS):064x}",
                "accepted_record_type": record_family,
                "accepted_record_id": f"rec_{index}",
                "decided_at": WHEN,
            },
        )


def _refused_by(constraint: str, write: Callable[[], None]) -> None:
    """Require the refusal to come from the constraint named, not from any other.

    `audit_events` carries eight CHECKs, `entity_mutation_events` twelve and
    `entity_proposals` more than twenty. Three of all those are the vocabularies
    this module is about and the rest are shapes -- and a test that only asked
    "was this refused?" would report a malformed identifier as a missing
    literal, which is how a guard ends up proving something nobody meant. The
    constraint name is read off the error.
    """
    with pytest.raises(IntegrityError) as refusal:
        write()
    assert constraint in str(refusal.value), (
        f"refused, but by something other than `{constraint}`: {refusal.value}"
    )


def test_the_names_this_module_checks_are_the_names_the_domain_declares() -> None:
    """The restatements above are restatements of something true, not third lists."""
    declared = {member.value for member in Capability}
    families = {member.value for member in MutationRecordFamily}
    assert set(ADMITTED_CAPABILITIES) <= declared
    assert set(ADMITTED_RECORD_FAMILIES) <= families
    assert SETTLED_CAPABILITY in declared
    assert SETTLED_PURPOSE in {member.value for member in Purpose}
    assert SETTLED_RECORD_FAMILY in families
    # And the two the module relies on being *un*declared, so the refusal tests
    # below are refusals of something the domain genuinely does not name.
    assert UNDECLARED_CAPABILITY not in declared
    assert UNDECLARED_RECORD_FAMILY not in families


def test_the_chain_reaches_this_head_and_holds_one(migrated_engine: Engine) -> None:
    """One Alembic head, and it is this one, on a database built from empty.

    The reason both work packages share a revision: three closed-set CHECKs
    restated on two branches would produce two heads and two conflicting
    statements of one vocabulary, and whichever merged last would silently
    decide what the other admitted.
    """
    script = ScriptDirectory.from_config(_config())
    heads = list(script.get_heads())
    assert heads == [CURRENT_HEAD_REVISION], (
        f"expected exactly {CURRENT_HEAD_REVISION}, found {heads}"
    )
    assert script.get_revision(CURRENT_HEAD_REVISION).down_revision == GRAPH_REVISION
    assert script.get_revision(GRAPH_REVISION).down_revision == HEAD_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(PREVIOUS_REVISION).down_revision == SECOND_TO_PREVIOUS_REVISION
    assert (
        script.get_revision(SECOND_TO_PREVIOUS_REVISION).down_revision == THIRD_TO_PREVIOUS_REVISION
    )
    with migrated_engine.begin() as connection:
        rows = connection.execute(text("SELECT version_num FROM alembic_version"))
        stamped = list(rows.scalars())
    assert stamped == [CURRENT_HEAD_REVISION]


@pytest.mark.parametrize("capability", ADMITTED_CAPABILITIES)
def test_the_stored_capability_vocabulary_admits_each_name_this_revision_adds(
    migrated_engine: Engine, capability: str
) -> None:
    """The direction that produces `internal_error` is a *missing* name.

    An audit row is written before the handler runs, so this insert is the one
    the request itself performs. If the stored CHECK does not name the
    capability, the request fails after authorization and before any handler --
    reported to the caller as an internal error, which is the least informative
    answer this build can give, and the answer all twenty of these gave against
    a migrated database until this revision.
    """
    _audit(migrated_engine, capability=capability, purpose=SETTLED_PURPOSE)


@pytest.mark.parametrize("record_family", ADMITTED_RECORD_FAMILIES)
def test_the_mutation_ledger_admits_each_record_family_this_revision_adds(
    migrated_engine: Engine, record_family: str
) -> None:
    """The second CHECK, driven separately from the first.

    A capability admitted to the audit table whose ledger row is then refused is
    a request that authorizes, runs, and fails on its own accounting -- half-open
    in the other direction from a missing capability, and just as invisible to a
    suite that builds every database from scratch.
    """
    _mutation(migrated_engine, record_family=record_family)


@pytest.mark.parametrize("record_family", ADMITTED_RECORD_FAMILIES)
def test_the_proposal_ledger_admits_each_record_family_this_revision_adds(
    migrated_engine: Engine, record_family: str
) -> None:
    """The third CHECK, on the other table, built from the same enum.

    Nothing promotes a proposal into one of these five families today, so this
    is metadata parity rather than a capability: `tables.py` builds this
    constraint and the mutation ledger's from one `_one_of(...,
    MutationRecordFamily, ...)`, and a revision that widened one and left the
    other narrow would leave a from-scratch database and a migrated one
    enforcing different rules about one column.
    """
    _accepted_proposal(migrated_engine, record_family=record_family)


def test_a_name_nothing_declares_is_still_refused(migrated_engine: Engine) -> None:
    """The widening widened; it did not open. Otherwise the tests above are vacuous."""
    _refused_by(
        "capability_is_known",
        partial(_audit, migrated_engine, capability=UNDECLARED_CAPABILITY, purpose=SETTLED_PURPOSE),
    )
    _refused_by(
        "a_mutated_record_family_is_known",
        partial(_mutation, migrated_engine, record_family=UNDECLARED_RECORD_FAMILY),
    )
    _refused_by(
        "an_accepted_proposal_record_family_is_known",
        partial(_accepted_proposal, migrated_engine, record_family=UNDECLARED_RECORD_FAMILY),
    )


def test_this_revision_is_what_admits_them(migrated_engine: Engine) -> None:
    """Downgrade one revision: every new name is refused, and the settled ones are not.

    This is the whole claim, and it is the assertion that binds the revision
    rather than the schema. An equality at head between the stored vocabulary
    and the enums is true either side of a revision that did nothing; what makes
    `16f05c46b8c3` load-bearing is that removing it takes the 20 capability
    names and the five record families with it and leaves everything else
    standing.

    The control rows are written *after* the downgrade and before the upgrade,
    so they are rows the narrow constraints admitted -- `ALTER TABLE ... ADD
    CONSTRAINT` validates what is already stored, and a control row carrying a
    new name would make the upgrade below fail for a reason that had nothing to
    do with the vocabulary.
    """
    command.downgrade(_config(), PREVIOUS_REVISION)

    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
    _mutation(migrated_engine, record_family=SETTLED_RECORD_FAMILY)
    _accepted_proposal(migrated_engine, record_family=SETTLED_RECORD_FAMILY)

    for capability in ADMITTED_CAPABILITIES:
        _refused_by(
            "capability_is_known",
            partial(_audit, migrated_engine, capability=capability, purpose=SETTLED_PURPOSE),
        )
    for record_family in ADMITTED_RECORD_FAMILIES:
        _refused_by(
            "a_mutated_record_family_is_known",
            partial(_mutation, migrated_engine, record_family=record_family),
        )
        _refused_by(
            "an_accepted_proposal_record_family_is_known",
            partial(_accepted_proposal, migrated_engine, record_family=record_family),
        )

    command.upgrade(_config(), "head")

    for capability in ADMITTED_CAPABILITIES:
        _audit(migrated_engine, capability=capability, purpose=SETTLED_PURPOSE)
    for record_family in ADMITTED_RECORD_FAMILIES:
        _mutation(migrated_engine, record_family=record_family)
        _accepted_proposal(migrated_engine, record_family=record_family)


def test_the_stored_vocabularies_are_missing_nothing_the_domain_declares(
    migrated_engine: Engine,
) -> None:
    """Every declared name, driven through the stored CHECKs, one row each.

    This is the control the 20-name gap needed and did not have. The
    superset direction is harmless -- the eleven retired `native_sources.*`
    names are stored and are not in `Capability`, and they predate all of this.
    The direction that breaks a request is a name the domain declares and the
    database has never heard of, and the only way to be sure of it for all one
    hundred and twenty-eight is to try all one hundred and twenty-eight.

    `Purpose` is driven for the same reason and not because this revision
    touched it: it deliberately does not widen `purpose_is_known`, because
    neither work package adds a member. That is a decision that stops being safe
    the moment one does, and this loop is what would say so.

    `MutationRecordFamily` is driven through both family CHECKs on the same
    argument. Its literal in the revision is exactly equal to the live enum --
    eleven against eleven -- so the next member added is the moment the two stop
    agreeing, and nothing in the revision itself will notice.
    """
    for capability in sorted(member.value for member in Capability):
        _audit(migrated_engine, capability=capability, purpose=SETTLED_PURPOSE)
    for purpose in sorted(member.value for member in Purpose):
        _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=purpose)
    for record_family in sorted(member.value for member in MutationRecordFamily):
        _mutation(migrated_engine, record_family=record_family)
        _accepted_proposal(migrated_engine, record_family=record_family)


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
