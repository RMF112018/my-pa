"""`b64e29a0f7c1` is what lets a Phase B request be audited at all.

`authorize` commits an `audit_events` row **before** the handler runs. So a
capability that is in the `Capability` enum and absent from the stored
`capability_is_known` CHECK answers `internal_error` against a migrated
database while every from-scratch test in the repository passes -- B5 and B6
both recorded that trap and B7 measured it. The revision that closes it is
`b64e29a0f7c1`, which admits the capability names Phase B publishes and the
purposes they carry.

Nothing tested that revision directly. What stood in its place was
`tests/schema/test_context_feedback_migration.py`, which compares the stored
vocabulary against `Capability`/`Purpose` **at head** -- a true statement, and
one that says nothing about which revision makes it true or about what happens
either side of it. This module is the direct test: it drives the stored CHECK
with a real `INSERT` at head, downgrades exactly one revision, drives the same
`INSERT` and requires it to be refused, and upgrades again.

Written as inserts rather than as a parse of `pg_constraint`, because the shape
this phase can actually fail in is an insert being refused at request time, and
because a parse would pass on a CHECK that names the right literals in a
predicate that never fires.

Both directions are asserted for every Phase B name, and the *purpose* half is
asserted separately from the *capability* half: they are two CHECKs on
one table and a revision that widened one and forgot the other would leave half
the surface answering `internal_error`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
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
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: Distinct from every other database-tier fixture's database, so this suite can
#: run beside them without one dropping what another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_phase_b_vocabulary_test"

#: The current head and the Phase B vocabulary edge this suite removes. Written
#: out rather than imported so current chain drift and historical identity are
#: checked independently.
HEAD_REVISION: Final = "c3f8a1d07e94"
#: What was head until `HEAD_REVISION` stacked on it (RI-ENT-WP-10/11, widening
#: three closed-set CHECKs to admit that phase's capability names and record
#: families, creating and altering no table).
#: `b8e4d1a6c073` (RI-ENT-WP-12, backfilling one `display`-typed `entity_names`
#: row per active `entities` row) was written against `c99cd8ed8d1c` and
#: re-parented onto `16f05c46b8c3` once RI-ENT-WP-10/11 merged, because the two
#: would otherwise have stood as two heads (RULING-M11). Named so the chain
#: assertion below stays a statement about the order rather than about whichever
#: revision happens to be last.
SECOND_TO_HEAD_REVISION: Final = "16f05c46b8c3"
#: What was head until `SECOND_TO_HEAD_REVISION` stacked on it (UI-IMP-WP02, adding
#: WebAuthn credential, challenge, recovery-code, and opaque session tables).
#: `16f05c46b8c3` was written against `c99cd8ed8d1c`, as `2c00c9ac64bc` was, and
#: was re-parented onto it when `origin/main` merged, for the same reason.
THIRD_TO_HEAD_REVISION: Final = "2c00c9ac64bc"
#: What was head until `THIRD_TO_HEAD_REVISION` stacked on it (RI-ENT-WP-08's
#: blocker-clearing pass, renaming the seeded `entity_relationship_types` row
#: `design_coordinates_with` to `design_coordination_with`).
FOURTH_TO_HEAD_REVISION: Final = "c99cd8ed8d1c"
#: What was head until `FOURTH_TO_HEAD_REVISION` stacked on it (RI-ENT-WP-07,
#: adding entity_assertions/entity_assertion_evidence).
FIFTH_TO_HEAD_REVISION: Final = "1cda4d536268"
#: What was head until `FIFTH_TO_HEAD_REVISION` stacked on it (RI-ENT-WP-06b,
#: widening the identity-effect family CHECKs).
SIXTH_TO_HEAD_REVISION: Final = "9a3f6c1e8d24"
#: The identity-history revision, several links below `SIXTH_TO_HEAD_REVISION`
#: rather than immediately beneath it -- the chain assertion below walks the
#: intervening links by literal. Named so that assertion stays a statement about
#: the order rather than about whichever revision happens to be last.
IDENTITY_HISTORY_REVISION: Final = "8e1c4a7b2d90"
PHASE_B_SCHEMA_REVISION: Final = "3d07af4dc513"
PHASE_B_REVISION: Final = "b64e29a0f7c1"
PREVIOUS_REVISION: Final = "a1f7d3c85e40"

#: What the revision admits. Restated here for the reason above, and compared
#: against the enums below so a *domain* rename cannot drift away from it either.
PHASE_B_CAPABILITIES: Final[tuple[str, ...]] = (
    "entities.merge",
    "entities.merge.preview",
    "entities.proposals.create",
    "relationship_memory.propose",
)
PHASE_B_PURPOSES: Final[tuple[str, ...]] = (
    "entity_identity_correction",
    "entity_proposal",
    "relationship_memory_proposal",
)

#: A capability and a purpose that predate this revision, used as the control:
#: they must be admitted on both sides of the downgrade, so a refusal below is
#: evidence about the Phase B literals and not about a table that stopped
#: accepting anything.
SETTLED_CAPABILITY: Final = "capabilities.get"
SETTLED_PURPOSE: Final = "status_observation"

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)

#: `audit_policy_version_is_a_known_shape` matches `POLICY_VERSION_PATTERN`, so
#: a placeholder would be refused by a *shape* rule and this module would be
#: reporting the wrong constraint.
POLICY_VERSION: Final = "policy-v1"


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


#: A row identifier counter. `audit_id` and `correlation_id` both carry the
#: opaque-identifier CHECK, whose suffix admits `[A-Za-z0-9]{8,64}` and no
#: separator, so a readable slug of the capability name would be refused by the
#: shape rule before the vocabulary rule was reached -- and this module would be
#: reporting the wrong constraint. A counter keeps every row distinct and every
#: identifier legal.
_ROWS = count(1)


def _audit(engine: Engine, *, capability: str, purpose: str) -> None:
    """One audit row, exactly as `authorize` writes one before a handler runs."""
    index = f"{next(_ROWS):016x}"  # sixteen hex digits clears the eight-character floor
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


def _refused_by(constraint: str, **kwargs: object) -> None:
    """Require the refusal to come from the constraint named, not from any other.

    `audit_events` carries eight CHECKs. Two of them are the vocabularies this
    module is about and the other six are shapes -- and a test that only asked
    "was this refused?" would report a malformed identifier as a missing
    capability literal, which is how a guard ends up proving something nobody
    meant. The constraint name is read off the error.
    """
    with pytest.raises(IntegrityError) as refusal:
        _audit(**kwargs)  # type: ignore[arg-type]
    assert constraint in str(refusal.value), (
        f"refused, but by something other than `{constraint}`: {refusal.value}"
    )


def test_the_names_this_module_checks_are_the_names_the_domain_declares() -> None:
    """The restatement above is a restatement of something true, not a third list."""
    declared = {member.value for member in Capability}
    assert set(PHASE_B_CAPABILITIES) <= declared
    assert set(PHASE_B_PURPOSES) <= {member.value for member in Purpose}
    assert SETTLED_CAPABILITY in declared
    assert SETTLED_PURPOSE in {member.value for member in Purpose}


def test_the_chain_reaches_this_head_and_holds_one(migrated_engine: Engine) -> None:
    """One Alembic head, and it is this one, on a database built from empty."""
    script = ScriptDirectory.from_config(_config())
    heads = list(script.get_heads())
    assert heads == [HEAD_REVISION], f"expected exactly {HEAD_REVISION}, found {heads}"
    # `b8e4d1a6c073` (RI-ENT-WP-12, backfilling one `display`-typed
    # `entity_names` row per active `entities` row and writing no
    # `entity_project_participations` row, RULING-M10) is additive on
    # `16f05c46b8c3` -- an edge RI-ENT-WP-12's integration made, because it had
    # been written against `c99cd8ed8d1c` and would otherwise have stood beside
    # `16f05c46b8c3` as a second head (RULING-M11). `16f05c46b8c3` (RI-ENT-WP-10/11,
    # widening `audit_events.capability_is_known` 115 -> 135,
    # `entity_mutation_events.a_mutated_record_family_is_known` 6 -> 11 and
    # `entity_proposals.an_accepted_proposal_record_family_is_known` 6 -> 11 for
    # RI-ENT-WP-10's five entity reads and RI-ENT-WP-11's fifteen entity
    # mutation contracts, and creating and altering no table) is additive on
    # `2c00c9ac64bc` (UI-IMP-WP02, adding the WebAuthn credential, challenge,
    # recovery-code and opaque session tables) -- an edge the base merge made,
    # because both revisions had been written against `c99cd8ed8d1c` and the
    # pair would otherwise have stood as two heads (RULING-M11). `2c00c9ac64bc`
    # is itself additive on `c99cd8ed8d1c` (RI-ENT-WP-08's blocker-clearing
    # pass, renaming the seeded `entity_relationship_types` row
    # `design_coordinates_with` to `design_coordination_with`), itself additive
    # on `1cda4d536268` (RI-ENT-WP-07), itself additive on `9a3f6c1e8d24`
    # (RI-ENT-WP-06b), itself additive on `8dc3619891bb` (RI-ENT-WP-06a), itself
    # additive on `17149a48fa30` (RI-ENT-WP-05), itself additive on
    # `f5b06925857e` (RI-ENT-WP-04), itself additive on `441b071bf37b`
    # (RI-ENT-WP-03), itself additive on `7e114f822af2` (RI-ENT-WP-02), itself
    # additive on `b727e870d45e`, which is additive on
    # `IDENTITY_HISTORY_REVISION` -- three more links than this chain had before
    # `c99cd8ed8d1c` landed, and one more than it had before `b8e4d1a6c073` did.
    assert script.get_revision(HEAD_REVISION).down_revision == "b8e4d1a6c073"
    assert script.get_revision("b8e4d1a6c073").down_revision == SECOND_TO_HEAD_REVISION
    assert script.get_revision(SECOND_TO_HEAD_REVISION).down_revision == THIRD_TO_HEAD_REVISION
    assert script.get_revision(THIRD_TO_HEAD_REVISION).down_revision == FOURTH_TO_HEAD_REVISION
    assert script.get_revision(FOURTH_TO_HEAD_REVISION).down_revision == FIFTH_TO_HEAD_REVISION
    assert script.get_revision(FIFTH_TO_HEAD_REVISION).down_revision == SIXTH_TO_HEAD_REVISION
    assert script.get_revision(SIXTH_TO_HEAD_REVISION).down_revision == "8dc3619891bb"
    # `8dc3619891bb` used to be `FOURTH_TO_HEAD_REVISION` itself, and
    # `17149a48fa30` before that; naming both explicitly here keeps this chain
    # covering exactly the links it covered before the constants above shifted --
    # once when `c99cd8ed8d1c` landed, once when `16f05c46b8c3` did, once more
    # when the base merge put `2c00c9ac64bc` between the two, and once more when
    # `b8e4d1a6c073` was re-parented onto `16f05c46b8c3`.
    assert script.get_revision("8dc3619891bb").down_revision == "17149a48fa30"
    assert script.get_revision("17149a48fa30").down_revision == "f5b06925857e"
    assert script.get_revision("441b071bf37b").down_revision == "7e114f822af2"
    assert script.get_revision("7e114f822af2").down_revision == "b727e870d45e"
    assert script.get_revision("b727e870d45e").down_revision == IDENTITY_HISTORY_REVISION
    assert script.get_revision(IDENTITY_HISTORY_REVISION).down_revision == PHASE_B_SCHEMA_REVISION
    assert script.get_revision(PHASE_B_SCHEMA_REVISION).down_revision == PHASE_B_REVISION
    assert script.get_revision(PHASE_B_REVISION).down_revision == PREVIOUS_REVISION
    with migrated_engine.begin() as connection:
        rows = connection.execute(text("SELECT version_num FROM alembic_version"))
        stamped = list(rows.scalars())
    assert stamped == [HEAD_REVISION]


@pytest.mark.parametrize("capability", PHASE_B_CAPABILITIES)
def test_the_stored_capability_vocabulary_admits_each_phase_b_name(
    migrated_engine: Engine, capability: str
) -> None:
    """The direction that produces `internal_error` is a *missing* name.

    An audit row is written before the handler runs, so this insert is the one
    the request itself performs. If the stored CHECK does not name the
    capability, the request fails after authorization and before any handler --
    reported to the caller as an internal error, which is the least informative
    answer this build can give.
    """
    _audit(migrated_engine, capability=capability, purpose=SETTLED_PURPOSE)


@pytest.mark.parametrize("purpose", PHASE_B_PURPOSES)
def test_the_stored_purpose_vocabulary_admits_each_phase_b_purpose(
    migrated_engine: Engine, purpose: str
) -> None:
    """The second CHECK, driven separately from the first.

    Two constraints on one table. A revision that widened the capability half
    and forgot the purpose half would leave every Phase B request failing in
    exactly the same way, and a test that only drove one pair would not say
    which half was missing.
    """
    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=purpose)


def test_a_name_nothing_declares_is_still_refused(migrated_engine: Engine) -> None:
    """The widening widened; it did not open. Otherwise the tests above are vacuous."""
    _refused_by(
        "capability_is_known",
        engine=migrated_engine,
        capability="entities.merge.definitelynot",
        purpose=SETTLED_PURPOSE,
    )
    _refused_by(
        "purpose_is_known",
        engine=migrated_engine,
        capability=SETTLED_CAPABILITY,
        purpose="entity_identity_definitely_not",
    )


def test_this_revision_is_what_admits_them(migrated_engine: Engine) -> None:
    """Downgrade one revision: every Phase B name is refused, and the settled pair is not.

    This is the whole claim. The equality at head that
    `tests/schema/test_context_feedback_migration.py` asserts is true either
    side of a revision that did nothing; what makes `b64e29a0f7c1` load-bearing
    is that removing it takes the seven names with it and leaves everything else
    standing.
    """
    command.downgrade(_config(), PREVIOUS_REVISION)

    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
    for capability in PHASE_B_CAPABILITIES:
        _refused_by(
            "capability_is_known",
            engine=migrated_engine,
            capability=capability,
            purpose=SETTLED_PURPOSE,
        )
    for purpose in PHASE_B_PURPOSES:
        _refused_by(
            "purpose_is_known",
            engine=migrated_engine,
            capability=SETTLED_CAPABILITY,
            purpose=purpose,
        )

    command.upgrade(_config(), "head")

    for capability in PHASE_B_CAPABILITIES:
        _audit(migrated_engine, capability=capability, purpose=SETTLED_PURPOSE)
    for purpose in PHASE_B_PURPOSES:
        _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=purpose)


def test_the_stored_vocabulary_is_missing_nothing_the_domain_declares(
    migrated_engine: Engine,
) -> None:
    """Every declared name, driven through the stored CHECK, one row each.

    The superset direction is harmless -- the `native_sources.*` names are stored
    and are not in `Capability`, and they predate this phase. The
    direction that breaks a request is a name the domain declares and the
    database has never heard of, and the only way to be sure of it for all
    one hundred one is to try all one hundred one.
    """
    for capability in sorted(member.value for member in Capability):
        _audit(migrated_engine, capability=capability, purpose=SETTLED_PURPOSE)
    for purpose in sorted(member.value for member in Purpose):
        _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=purpose)


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
