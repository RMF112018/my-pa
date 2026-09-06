"""Revision `b8e4d1a6c073` against a real PostgreSQL server (RI-ENT-WP-12).

The revision backfills the legacy entity plane into the new typed-name family,
and the whole of its value is in what it *refuses* to write. This module is the
evidence for that refusal, not just for the one write.

What is proved here, in the order the module states it:

- **One fact is carried.** Every `knowledge.entities` row whose `status` is
  `'active'` gains exactly one `knowledge.entity_names` row, `display`-typed,
  carrying `display_name` as `display_value` and `canonical_name` as
  `normalized_value`, with every other column asserted individually rather than
  by a count.
- **Nothing becomes a `legal` name.** `ENTITY-SCHEMA-001` -- the campaign's
  founding finding -- exists because the legacy plane conflated "the string we
  show" with "what this entity is legally called". A test that only counted
  rows would pass on a backfill that wrote `legal`, so the type is asserted
  directly, twice: no row is anything other than `display`, and specifically no
  row is `legal`.
- **The status narrowing holds.** `archived`, `historical`, `inactive` and
  `merged_redirect` entities are each staged alongside active ones, and each is
  asserted to produce no row.
- **Zero participation rows, and the staged data is data a careless
  implementation would have consumed.** See
  `test_no_project_participation_row_is_fabricated_from_a_legacy_assignment`
  for why zero is the rule correctly applied rather than a gap.
- **No inferred types**, no touched legacy, and a downgrade that is exact:
  the other writer's row survives it, and an entangled row refuses it.
- **Each of the three upgrade guards refuses whole rather than half-applying.**
  Every guard test asserts the raise, the count in the message, *and* that
  `entity_names` is byte-identical to what it was before the attempt. An
  assertion that a migration raised says nothing about whether it wrote first.

Fixture/engine/`Config`/`command.upgrade` idiom is copied from
`tests/schema/test_entity_relationship_types_migration.py` and
`tests/database/test_phase_b_audit_vocabulary_migration.py`. Empty catalogs
come from `tests.db.fixtures.empty_database_url` (PR #186); this module still
drives Alembic to `PREVIOUS_REVISION` itself.

Every vocabulary literal below is **restated, not imported** from `NameTypeCode`,
`EntityNameState` or `EntityStatus` -- the same frozen-literal discipline the
revision itself keeps (`D-69`). The derived `entity_name_id` is likewise
recomputed in Python from the salt rather than re-derived in SQL, so the
expectation is independent of the expression the migration uses to build it.

All fixture data is synthetic: invented organization/person/project labels and
`example.invalid` addresses only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]

REVISION: Final = "b8e4d1a6c073"
PULL_REVISION: Final = "6a2f9d1c4b80"
PROMOTION_REVISION: Final = "a4d8e31b2c90"
HEAD_REVISION: Final = "a1c9e4b72f80"
CURRENT_HEAD_REVISION: Final = HEAD_REVISION
GRAPH_REVISION: Final = "c3f8a1d07e94"
#: What was head until `REVISION` stacked on it, and therefore the revision
#: this module downgrades to. `REVISION` was written against `c99cd8ed8d1c` and
#: re-parented onto `16f05c46b8c3` (RI-ENT-WP-10/11) once that merged, because
#: both had been written against `c99cd8ed8d1c` and the pair would otherwise
#: have stood as two heads (RULING-M11). `16f05c46b8c3` widens three closed-set
#: CHECKs and creates and alters no table, so nothing this module reads or
#: writes in `entity_names` differs between the two parents.
PREVIOUS_REVISION: Final = "16f05c46b8c3"

#: Every `migrations/versions/*.py` on the chain, this revision included.
#: Counted on the merged tree after the re-parent (RULING-M2): 88 on
#: `origin/main` at `16f05c46b8c3` plus this revision, graph vocabulary,
#: GoodNotes pull, promotion receipt, and canvas overlay successors.
REVISION_FILE_COUNT: Final = 95

#: The revision's frozen salt, restated. If this and the revision ever disagree
#: the expectations below stop matching, which is the point of restating it.
ID_SALT: Final = "ri-ent-wp-12:display:"

#: Restated vocabulary literals (`D-69`): not imported from any domain enum.
NAME_TYPE_DISPLAY: Final = "display"
NAME_TYPE_LEGAL: Final = "legal"
NAME_TYPE_ALIAS: Final = "alias"
NAME_STATE_ACTIVE: Final = "active"
NAME_STATE_SUPERSEDED: Final = "superseded"

#: The one `entities.status` in scope, and the four deliberately out of it.
STATUS_ACTIVE: Final = "active"
STATUS_ARCHIVED: Final = "archived"
STATUS_HISTORICAL: Final = "historical"
STATUS_INACTIVE: Final = "inactive"
STATUS_MERGED_REDIRECT: Final = "merged_redirect"

#: Every guard message this revision can emit opens with this.
GUARD_PREFIX: Final = "RI-ENT-WP-12"

PRINCIPAL: Final = "prn_wp12aaaa0001aaaa0001"

ACTIVE_ORGANIZATION: Final = "ent_wp12active0001"
ACTIVE_PERSON: Final = "ent_wp12active0002"
PROJECT: Final = "ent_wp12project001"
ARCHIVED_ENTITY: Final = "ent_wp12archived01"
HISTORICAL_ENTITY: Final = "ent_wp12historic01"
INACTIVE_ENTITY: Final = "ent_wp12inactive01"
MERGED_REDIRECT_ENTITY: Final = "ent_wp12merged0001"

#: Invented labels. The display/canonical pair differs in case and punctuation
#: on purpose: a backfill that wrote one column into both would pass a test
#: whose fixture used the same string for each.
ORGANIZATION_DISPLAY: Final = "Fixture Harborline Structural Group, LLC"
ORGANIZATION_CANONICAL: Final = "fixture harborline structural group llc"
PERSON_DISPLAY: Final = "Fixture Person Alpha"
PERSON_CANONICAL: Final = "fixture person alpha"
PROJECT_DISPLAY: Final = "Fixture Project Northgate Phase One"
PROJECT_CANONICAL: Final = "fixture project northgate phase one"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _derived_entity_name_id(entity_id: str) -> str:
    """`'enam_' || md5(salt || entity_id)`, computed in Python.

    Recomputed here rather than re-derived in SQL so the expected identity is
    independent of the expression the revision uses to write it. `md5()` in
    PostgreSQL hashes the bytes of the text in the server encoding; every
    fixture value in this module is ASCII, so the two agree by construction.

    `usedforsecurity=False` because this is a stable naming derivation, not a
    security primitive -- the same reason the revision may use `md5()` at all.
    """
    digest = hashlib.md5((ID_SALT + entity_id).encode(), usedforsecurity=False).hexdigest()
    return f"enam_{digest}"


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; this module still drives Alembic itself."""
    return empty_database_url


@pytest.fixture
def legacy_engine(disposable_database: str) -> Iterator[Engine]:
    """An engine on a database at `PREVIOUS_REVISION`.

    That is the state the legacy entity plane is in the instant before this
    revision runs: `entities`, `entity_aliases`, `entity_assignments`,
    `entity_external_identifiers` and the empty `entity_names` all present.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        yield engine
    finally:
        engine.dispose()


# --- staging helpers ---------------------------------------------------------


def _stage_entity(
    engine: Engine,
    *,
    entity_id: str,
    entity_type: str,
    canonical_name: str,
    display_name: str,
    status: str = STATUS_ACTIVE,
    archived_from_status: str | None = None,
    superseded_by_entity_id: str | None = None,
    principal_id: str = PRINCIPAL,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.entities "
                "(entity_id, principal_id, entity_type, canonical_name, display_name, "
                " status, archived_from_status, superseded_by_entity_id) "
                "VALUES (:entity_id, :principal_id, :entity_type, :canonical_name, "
                " :display_name, :status, :archived_from_status, :superseded_by_entity_id)"
            ),
            {
                "entity_id": entity_id,
                "principal_id": principal_id,
                "entity_type": entity_type,
                "canonical_name": canonical_name,
                "display_name": display_name,
                "status": status,
                "archived_from_status": archived_from_status,
                "superseded_by_entity_id": superseded_by_entity_id,
            },
        )


def _stage_entity_name(
    engine: Engine,
    *,
    entity_name_id: str,
    entity_id: str,
    name_type_code: str,
    normalized_value: str,
    display_value: str,
    state: str = NAME_STATE_ACTIVE,
    superseded_by_entity_name_id: str | None = None,
    principal_id: str = PRINCIPAL,
) -> None:
    """One `entity_names` row written by something other than this migration."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.entity_names "
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                " display_value, is_preferred, effective_from, effective_to, principal_id, "
                " state, version, updated_at, retired_at, superseded_by_entity_name_id) "
                "VALUES (:entity_name_id, :entity_id, :name_type_code, :normalized_value, "
                " :display_value, false, NULL, NULL, :principal_id, :state, 1, NULL, NULL, "
                " :superseded_by_entity_name_id)"
            ),
            {
                "entity_name_id": entity_name_id,
                "entity_id": entity_id,
                "name_type_code": name_type_code,
                "normalized_value": normalized_value,
                "display_value": display_value,
                "principal_id": principal_id,
                "state": state,
                "superseded_by_entity_name_id": superseded_by_entity_name_id,
            },
        )


def _stage_alias(
    engine: Engine,
    *,
    alias_id: str,
    entity_id: str,
    alias_type: str,
    normalized_value: str,
    display_value: str,
    principal_id: str = PRINCIPAL,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.entity_aliases "
                "(alias_id, entity_id, alias_type, normalized_value, display_value, "
                " effective_from, effective_to, principal_id) "
                "VALUES (:alias_id, :entity_id, :alias_type, :normalized_value, "
                " :display_value, NULL, NULL, :principal_id)"
            ),
            {
                "alias_id": alias_id,
                "entity_id": entity_id,
                "alias_type": alias_type,
                "normalized_value": normalized_value,
                "display_value": display_value,
                "principal_id": principal_id,
            },
        )


def _stage_external_identifier(
    engine: Engine,
    *,
    identifier_id: str,
    entity_id: str,
    namespace: str,
    normalized_value: str,
    display_value: str,
    principal_id: str = PRINCIPAL,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.entity_external_identifiers "
                "(identifier_id, entity_id, namespace, normalized_value, display_value, "
                " verified, effective_from, effective_to, principal_id) "
                "VALUES (:identifier_id, :entity_id, :namespace, :normalized_value, "
                " :display_value, false, NULL, NULL, :principal_id)"
            ),
            {
                "identifier_id": identifier_id,
                "entity_id": entity_id,
                "namespace": namespace,
                "normalized_value": normalized_value,
                "display_value": display_value,
                "principal_id": principal_id,
            },
        )


def _stage_assignment(
    engine: Engine,
    *,
    assignment_id: str,
    entity_id: str,
    scope_entity_id: str,
    assignment_type: str,
    role: str,
    discipline: str,
    responsibility_class: str,
    principal_id: str = PRINCIPAL,
) -> None:
    """A legacy assignment row of exactly the shape rule 3 is about.

    `status` was renamed to `state` by `2fe4e13fb449`, which is below
    `PREVIOUS_REVISION`, so the column is `state` here.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.entity_assignments "
                "(assignment_id, entity_id, scope_entity_id, assignment_type, role, "
                " discipline, responsibility_class, effective_from, effective_to, state, "
                " principal_id) "
                "VALUES (:assignment_id, :entity_id, :scope_entity_id, :assignment_type, "
                " :role, :discipline, :responsibility_class, NULL, NULL, 'active', "
                " :principal_id)"
            ),
            {
                "assignment_id": assignment_id,
                "entity_id": entity_id,
                "scope_entity_id": scope_entity_id,
                "assignment_type": assignment_type,
                "role": role,
                "discipline": discipline,
                "responsibility_class": responsibility_class,
                "principal_id": principal_id,
            },
        )


def _stage_the_two_active_entities(engine: Engine) -> None:
    _stage_entity(
        engine,
        entity_id=ACTIVE_ORGANIZATION,
        entity_type="organization",
        canonical_name=ORGANIZATION_CANONICAL,
        display_name=ORGANIZATION_DISPLAY,
    )
    _stage_entity(
        engine,
        entity_id=ACTIVE_PERSON,
        entity_type="person",
        canonical_name=PERSON_CANONICAL,
        display_name=PERSON_DISPLAY,
    )


# --- reading helpers ---------------------------------------------------------

_ENTITY_NAME_COLUMNS: Final = (
    "SELECT entity_name_id, entity_id, name_type_code, normalized_value, display_value, "
    "       is_preferred, effective_from, effective_to, principal_id, state, version, "
    "       updated_at, retired_at, superseded_by_entity_name_id "
    "  FROM knowledge.entity_names "
    " ORDER BY entity_name_id"
)


def _entity_name_rows(engine: Engine) -> list[tuple[Any, ...]]:
    """Every `entity_names` row, whole, in a server-collation-independent order."""
    with engine.connect() as connection:
        return sorted(tuple(row) for row in connection.execute(text(_ENTITY_NAME_COLUMNS)))


def _count(engine: Engine, statement: str, parameters: dict[str, Any] | None = None) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(statement), parameters or {}).scalar_one())


def _rows(
    engine: Engine, statement: str, parameters: dict[str, Any] | None = None
) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(statement), parameters or {})]


def _derived_row_count(engine: Engine, entity_id: str) -> int:
    """How many rows carry the identity this migration derives for `entity_id`."""
    return _count(
        engine,
        "SELECT count(*) FROM knowledge.entity_names WHERE entity_name_id = :entity_name_id",
        {"entity_name_id": _derived_entity_name_id(entity_id)},
    )


def _expected_backfilled_row(
    *, entity_id: str, canonical_name: str, display_name: str
) -> tuple[Any, ...]:
    """The one row the revision is allowed to write for `entity_id`.

    Every column is stated, in the order `_ENTITY_NAME_COLUMNS` reads them:
    derived identity, the entity, `display` (never `legal`), `canonical_name`
    into `normalized_value`, `display_name` into `display_value`,
    `is_preferred` false, both effective bounds NULL, the entity's principal,
    state `active`, version 1, and no mutation or supersession metadata.
    """
    return (
        _derived_entity_name_id(entity_id),
        entity_id,
        NAME_TYPE_DISPLAY,
        canonical_name,
        display_name,
        False,
        None,
        None,
        PRINCIPAL,
        NAME_STATE_ACTIVE,
        1,
        None,
        None,
        None,
    )


# --- 1. chain position (no database) -----------------------------------------


def test_the_revision_is_the_single_head_and_revises_the_prior_head() -> None:
    """One head through the additive successors, retaining every prior edge."""
    script = ScriptDirectory.from_config(_config())
    assert list(script.get_heads()) == [CURRENT_HEAD_REVISION]
    assert script.get_revision(CURRENT_HEAD_REVISION).down_revision == "2774329487be"
    assert script.get_revision("e8f2a6c9d104").down_revision == "d4e8b1c7a902"
    assert script.get_revision("d4e8b1c7a902").down_revision == "a4d8e31b2c90"
    assert script.get_revision("a4d8e31b2c90").down_revision == "6a2f9d1c4b80"
    assert script.get_revision("6a2f9d1c4b80").down_revision == GRAPH_REVISION
    assert script.get_revision(GRAPH_REVISION).down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION


def test_the_chain_holds_the_revision_files_it_claims() -> None:
    """`migrations/versions/*.py` numbers `REVISION_FILE_COUNT`."""
    versions = sorted((ROOT / "migrations" / "versions").glob("*.py"))
    assert len(versions) == REVISION_FILE_COUNT
    assert any(REVISION in path.name for path in versions)


# --- 2 and 3. the one fact carried, and the one type never written -----------


@pytest.mark.database
def test_every_active_entity_gets_one_display_name_carrying_both_legacy_values(
    legacy_engine: Engine,
) -> None:
    """Rule 1: one row per active entity, every column as the revision states it.

    `display_name` lands in `display_value` and `canonical_name` in
    `normalized_value` -- one row holding one name in two representations, not
    two rows and not the display string written into both columns. The two
    fixture entities carry *different* strings in the two source columns, so a
    backfill that copied one into both would fail here rather than pass.
    """
    _stage_the_two_active_entities(legacy_engine)

    command.upgrade(_config(), "head")

    assert _entity_name_rows(legacy_engine) == sorted(
        [
            _expected_backfilled_row(
                entity_id=ACTIVE_ORGANIZATION,
                canonical_name=ORGANIZATION_CANONICAL,
                display_name=ORGANIZATION_DISPLAY,
            ),
            _expected_backfilled_row(
                entity_id=ACTIVE_PERSON,
                canonical_name=PERSON_CANONICAL,
                display_name=PERSON_DISPLAY,
            ),
        ]
    )
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_names") == 2


@pytest.mark.database
def test_nothing_the_backfill_writes_is_a_legal_name(legacy_engine: Engine) -> None:
    """`ENTITY-SCHEMA-001`, asserted directly and unmissably.

    The campaign exists because the legacy plane conflated "the string we show
    for this entity" with "what this entity is legally called". A display name
    is evidence of how an entity has been rendered; it is not evidence of a
    legal, brand, DBA, operating, acronym or historical name, and once a wrong
    inference is stored it is indistinguishable from evidence.

    So this is asserted twice and from both directions: no row carries any
    `name_type_code` other than `display`, and no row carries `legal`
    specifically. The second assertion is not redundant with the first -- it is
    the one a reader of this file is looking for.
    """
    _stage_the_two_active_entities(legacy_engine)

    command.upgrade(_config(), "head")

    assert (
        _count(
            legacy_engine,
            "SELECT count(*) FROM knowledge.entity_names WHERE name_type_code <> 'display'",
        )
        == 0
    )
    assert (
        _count(
            legacy_engine,
            "SELECT count(*) FROM knowledge.entity_names WHERE name_type_code = 'legal'",
        )
        == 0
    )
    stored_types = {
        row[0]
        for row in _rows(
            legacy_engine,
            "SELECT DISTINCT name_type_code FROM knowledge.entity_names",
        )
    }
    assert stored_types == {NAME_TYPE_DISPLAY}
    assert NAME_TYPE_LEGAL not in stored_types
    # Restated so the assertions above cannot all be trivially true by the
    # table simply being empty.
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_names") == 2


# --- 4. the status narrowing -------------------------------------------------


@pytest.mark.database
def test_only_active_entities_are_backfilled_and_the_other_four_statuses_are_not(
    legacy_engine: Engine,
) -> None:
    """`archived`, `historical`, `inactive` and `merged_redirect` produce nothing.

    An `entity_names` row written with `state = 'active'` asserts the name is
    currently in service, and that assertion is unsupported for an entity that
    has been archived, retired or merged away. Each of the four out-of-scope
    statuses is staged individually and asserted individually, rather than by a
    single count that one silently-included status could still satisfy.

    `an_entity_records_the_status_it_was_archived_from` requires a non-null
    `archived_from_status` for `archived`, and
    `an_entity_redirects_exactly_when_it_is_merged_away` requires a non-null
    `superseded_by_entity_id` for `merged_redirect`; both are supplied.
    """
    _stage_the_two_active_entities(legacy_engine)
    _stage_entity(
        legacy_engine,
        entity_id=ARCHIVED_ENTITY,
        entity_type="organization",
        canonical_name="fixture archived organization",
        display_name="Fixture Archived Organization",
        status=STATUS_ARCHIVED,
        archived_from_status=STATUS_ACTIVE,
    )
    _stage_entity(
        legacy_engine,
        entity_id=HISTORICAL_ENTITY,
        entity_type="organization",
        canonical_name="fixture historical organization",
        display_name="Fixture Historical Organization",
        status=STATUS_HISTORICAL,
    )
    _stage_entity(
        legacy_engine,
        entity_id=INACTIVE_ENTITY,
        entity_type="person",
        canonical_name="fixture inactive person",
        display_name="Fixture Inactive Person",
        status=STATUS_INACTIVE,
    )
    _stage_entity(
        legacy_engine,
        entity_id=MERGED_REDIRECT_ENTITY,
        entity_type="organization",
        canonical_name="fixture merged organization",
        display_name="Fixture Merged Organization",
        status=STATUS_MERGED_REDIRECT,
        superseded_by_entity_id=ACTIVE_ORGANIZATION,
    )

    command.upgrade(_config(), "head")

    backfilled = _rows(
        legacy_engine, "SELECT entity_id FROM knowledge.entity_names ORDER BY entity_id"
    )
    assert backfilled == sorted([(ACTIVE_ORGANIZATION,), (ACTIVE_PERSON,)])
    for out_of_scope in (
        ARCHIVED_ENTITY,
        HISTORICAL_ENTITY,
        INACTIVE_ENTITY,
        MERGED_REDIRECT_ENTITY,
    ):
        assert (out_of_scope,) not in backfilled
    # And the six staged entities are all still there: the narrowing is in what
    # was written, not in what was read.
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entities") == 6


# --- 5. rule 3: zero participation rows --------------------------------------


@pytest.mark.database
def test_no_project_participation_row_is_fabricated_from_a_legacy_assignment(
    legacy_engine: Engine,
) -> None:
    """Zero is rule 3 correctly applied, not rule 3 skipped.

    `RULING-M10` rule 3 authorizes backfilling participation **only for
    directly representable values**. `f5b06925857e` declares
    `entity_project_participations.project_display_name` as `text NOT NULL`
    under `a_project_participation_display_name_is_not_blank`, so every
    participation row requires a project-facing name before it can exist. The
    legacy source, `knowledge.entity_assignments` (`9def3c2e63bb`), carries no
    name-bearing column at all: only `role`, `discipline` and
    `responsibility_class`. The one place a name could be found is
    `entities.display_name`/`canonical_name`, and reading either into
    `project_display_name` is expressly forbidden by that column's own DDL
    comment -- a participant's name *on a project* is a different fact from its
    global identity. No legacy row is therefore directly representable, and the
    correct output of rule 3 over this input is the empty set.

    **This test is built to bite.** The rows staged below are precisely the ones
    a careless implementation would have consumed: `assignment_type` is
    `'project_assignment'`, `scope_entity_id` is non-null and points at a real
    entity whose `entity_type` is `'project'`, and `role`, `discipline` and
    `responsibility_class` all carry free text. If anyone ever starts
    fabricating `project_display_name` from the entity's global name, this
    count stops being zero and this test fails on that commit rather than on
    the audit that finds the invented names years later.
    """
    _stage_the_two_active_entities(legacy_engine)
    _stage_entity(
        legacy_engine,
        entity_id=PROJECT,
        entity_type="project",
        canonical_name=PROJECT_CANONICAL,
        display_name=PROJECT_DISPLAY,
    )
    _stage_assignment(
        legacy_engine,
        assignment_id="asn_wp12assign0001",
        entity_id=ACTIVE_PERSON,
        scope_entity_id=PROJECT,
        assignment_type="project_assignment",
        role="project executive",
        discipline="construction management",
        responsibility_class="accountable",
    )
    _stage_assignment(
        legacy_engine,
        assignment_id="asn_wp12assign0002",
        entity_id=ACTIVE_ORGANIZATION,
        scope_entity_id=PROJECT,
        assignment_type="project_assignment",
        role="structural engineer of record",
        discipline="structural",
        responsibility_class="consulted",
    )

    command.upgrade(_config(), "head")

    assert (
        _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_project_participations") == 0
    )
    # The migration did run, and it did write the one thing it is allowed to
    # write -- so the zero above is a refusal, not an upgrade that never
    # happened.
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_names") == 3
    # And the assignments a naive implementation would have consumed are still
    # sitting there, unread and unaltered.
    assert _rows(
        legacy_engine,
        "SELECT assignment_id, entity_id, scope_entity_id, assignment_type, role, "
        "       discipline, responsibility_class, state "
        "  FROM knowledge.entity_assignments ORDER BY assignment_id",
    ) == [
        (
            "asn_wp12assign0001",
            ACTIVE_PERSON,
            PROJECT,
            "project_assignment",
            "project executive",
            "construction management",
            "accountable",
            "active",
        ),
        (
            "asn_wp12assign0002",
            ACTIVE_ORGANIZATION,
            PROJECT,
            "project_assignment",
            "structural engineer of record",
            "structural",
            "consulted",
            "active",
        ),
    ]


# --- 6. rule 4: no inferred types --------------------------------------------


@pytest.mark.database
def test_no_address_or_communication_method_is_inferred(legacy_engine: Engine) -> None:
    """Rule 4: both typed tables stay empty.

    `entity_addresses.address_type_code` and
    `entity_communication_methods.method_type_code` are closed vocabularies, and
    the only way a backfill could supply either is by inferring it from a
    string's position or shape -- which rule 4 forbids, because an inferred type
    is unfalsifiable once stored.
    """
    _stage_the_two_active_entities(legacy_engine)
    _stage_external_identifier(
        legacy_engine,
        identifier_id="xid_wp12email00001",
        entity_id=ACTIVE_PERSON,
        namespace="email",
        normalized_value="fixture.person.alpha@example.invalid",
        display_value="Fixture.Person.Alpha@example.invalid",
    )

    command.upgrade(_config(), "head")

    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_addresses") == 0
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_communication_methods") == 0
    # Staged an email-namespaced identifier on purpose: it is the single most
    # tempting thing to infer a `communication_method` from.
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_external_identifiers") == 1


# --- 7. rules 2 and 5: untouched legacy --------------------------------------


@pytest.mark.database
def test_legacy_aliases_identifiers_and_entity_ids_survive_byte_identical(
    legacy_engine: Engine,
) -> None:
    """Rule 2 and rule 5: `entity_aliases` and `entity_external_identifiers` are
    not read, not written, not migrated, and no `entity_id` is renumbered.

    `SELECT *` deliberately, on both tables: the comparison is of whole rows
    before and after, so a column this module never thought to name is still
    covered by it.
    """
    _stage_the_two_active_entities(legacy_engine)
    _stage_alias(
        legacy_engine,
        alias_id="eals_wp12alias0001",
        entity_id=ACTIVE_ORGANIZATION,
        alias_type="abbreviation",
        normalized_value="fhsg",
        display_value="FHSG",
    )
    _stage_alias(
        legacy_engine,
        alias_id="eals_wp12alias0002",
        entity_id=ACTIVE_PERSON,
        alias_type="nickname",
        normalized_value="fixture alpha",
        display_value="Fixture Alpha",
    )
    _stage_external_identifier(
        legacy_engine,
        identifier_id="xid_wp12email00002",
        entity_id=ACTIVE_ORGANIZATION,
        namespace="email",
        normalized_value="contact@example.invalid",
        display_value="Contact@example.invalid",
    )
    _stage_external_identifier(
        legacy_engine,
        identifier_id="xid_wp12vendor0001",
        entity_id=ACTIVE_PERSON,
        namespace="vendor_system_id",
        normalized_value="fixture-vendor-0001",
        display_value="FIXTURE-VENDOR-0001",
    )

    aliases_before = _rows(
        legacy_engine, "SELECT * FROM knowledge.entity_aliases ORDER BY alias_id"
    )
    identifiers_before = _rows(
        legacy_engine,
        "SELECT * FROM knowledge.entity_external_identifiers ORDER BY identifier_id",
    )
    entity_ids_before = _rows(
        legacy_engine, "SELECT entity_id FROM knowledge.entities ORDER BY entity_id"
    )
    assert len(aliases_before) == 2
    assert len(identifiers_before) == 2

    command.upgrade(_config(), "head")

    assert (
        _rows(legacy_engine, "SELECT * FROM knowledge.entity_aliases ORDER BY alias_id")
        == aliases_before
    )
    assert (
        _rows(
            legacy_engine,
            "SELECT * FROM knowledge.entity_external_identifiers ORDER BY identifier_id",
        )
        == identifiers_before
    )
    assert (
        _rows(legacy_engine, "SELECT entity_id FROM knowledge.entities ORDER BY entity_id")
        == entity_ids_before
    )
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_aliases") == 2
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_external_identifiers") == 2


# --- 8. abort on ambiguity: one test per guard, each proving the refusal ------


@pytest.mark.database
def test_guard_a_refuses_when_an_in_scope_entity_already_has_an_active_display_name(
    legacy_engine: Engine,
) -> None:
    """Guard A refuses, names the count, and writes nothing.

    An entity that already carries an active `display` name row leaves the
    migration unable to decide whether that row or the legacy `entities` value
    is the truth. Skipping asserts the existing row wins; overwriting asserts
    the legacy value wins. Both are guesses, so it refuses.

    The pre-existing row carries a non-derived identifier, so guard B is not
    also satisfied and the refusal below is unambiguously guard A's.
    """
    _stage_the_two_active_entities(legacy_engine)
    _stage_entity_name(
        legacy_engine,
        entity_name_id="enam_wp12otherwriter0001",
        entity_id=ACTIVE_ORGANIZATION,
        name_type_code=NAME_TYPE_DISPLAY,
        normalized_value="fixture harborline structural",
        display_value="Fixture Harborline Structural",
    )
    before = _entity_name_rows(legacy_engine)

    with pytest.raises(DBAPIError) as refusal:
        command.upgrade(_config(), "head")

    message = str(refusal.value)
    assert GUARD_PREFIX in message
    assert "guard A" in message
    assert "1 offending row(s)" in message
    assert ACTIVE_ORGANIZATION in message
    # It refused rather than half-applied: not one derived row was written.
    assert _entity_name_rows(legacy_engine) == before
    assert _derived_row_count(legacy_engine, ACTIVE_ORGANIZATION) == 0
    assert _derived_row_count(legacy_engine, ACTIVE_PERSON) == 0


@pytest.mark.database
def test_guard_b_refuses_when_the_derived_identifier_already_exists(
    legacy_engine: Engine,
) -> None:
    """Guard B refuses, names the count, and writes nothing.

    The colliding row is `alias`-typed so guard A -- which only looks at active
    `display` rows -- is not satisfied, and the refusal is unambiguously guard
    B's. If the derivation is not injective against this database, both the
    INSERT and the `downgrade()` DELETE would act on a row this revision did
    not author, so it refuses rather than deduplicate.
    """
    _stage_the_two_active_entities(legacy_engine)
    _stage_entity_name(
        legacy_engine,
        entity_name_id=_derived_entity_name_id(ACTIVE_PERSON),
        entity_id=ACTIVE_PERSON,
        name_type_code=NAME_TYPE_ALIAS,
        normalized_value="fixture alpha",
        display_value="Fixture Alpha",
    )
    before = _entity_name_rows(legacy_engine)

    with pytest.raises(DBAPIError) as refusal:
        command.upgrade(_config(), "head")

    message = str(refusal.value)
    assert GUARD_PREFIX in message
    assert "guard B" in message
    assert "1 offending row(s)" in message
    assert ACTIVE_PERSON in message
    assert _entity_name_rows(legacy_engine) == before
    assert (
        _count(
            legacy_engine,
            "SELECT count(*) FROM knowledge.entity_names WHERE name_type_code = 'display'",
        )
        == 0
    )


@pytest.mark.database
def test_guard_c_refuses_when_an_in_scope_source_value_is_blank(
    legacy_engine: Engine,
) -> None:
    """Guard C refuses, names the count, and writes nothing.

    `an_entity_display_name_is_not_blank` is what makes this state unreachable
    through the front door, which is exactly why the guard asserts it rather
    than assuming it -- a violation must surface as this migration's own named
    refusal, not as a raw constraint error from the INSERT. Constructing the
    state therefore means dropping that one CHECK on this disposable database
    first. Nothing else is relaxed, and the migration is not modified: the
    source table is put into the shape the guard exists to catch.
    """
    _stage_the_two_active_entities(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE knowledge.entities DROP CONSTRAINT an_entity_display_name_is_not_blank"
            )
        )
        connection.execute(
            text("UPDATE knowledge.entities SET display_name = '   ' WHERE entity_id = :entity_id"),
            {"entity_id": ACTIVE_PERSON},
        )
    before = _entity_name_rows(legacy_engine)
    assert before == []

    with pytest.raises(DBAPIError) as refusal:
        command.upgrade(_config(), "head")

    message = str(refusal.value)
    assert GUARD_PREFIX in message
    assert "guard C" in message
    assert "1 offending row(s)" in message
    assert ACTIVE_PERSON in message
    # Nothing was written -- not even for the entity whose source values were
    # perfectly usable. The refusal is whole-database, not per-row.
    assert _entity_name_rows(legacy_engine) == []


# --- 9 and 10. downgrade is exact, and refuses when it cannot be -------------


@pytest.mark.database
def test_downgrade_removes_only_the_rows_this_migration_derived(
    legacy_engine: Engine,
) -> None:
    """Another writer's row survives the downgrade untouched.

    The surviving row is `display`-typed on an entity this migration backfilled,
    so the only thing separating it from deletion is the derived-identity
    predicate itself -- which is the property under test. It carries a
    different `normalized_value` so
    `an_active_entity_name_is_unique_per_entity_and_type` admits it alongside
    the backfilled row.
    """
    _stage_the_two_active_entities(legacy_engine)

    command.upgrade(_config(), "head")
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_names") == 2

    _stage_entity_name(
        legacy_engine,
        entity_name_id="enam_wp12otherwriter0002",
        entity_id=ACTIVE_ORGANIZATION,
        name_type_code=NAME_TYPE_DISPLAY,
        normalized_value="fixture harborline group",
        display_value="Fixture Harborline Group",
    )
    other_writer_row = _rows(
        legacy_engine,
        "SELECT * FROM knowledge.entity_names WHERE entity_name_id = 'enam_wp12otherwriter0002'",
    )
    assert len(other_writer_row) == 1

    command.downgrade(_config(), PREVIOUS_REVISION)

    assert _derived_row_count(legacy_engine, ACTIVE_ORGANIZATION) == 0
    assert _derived_row_count(legacy_engine, ACTIVE_PERSON) == 0
    assert (
        _rows(
            legacy_engine,
            "SELECT * FROM knowledge.entity_names "
            "WHERE entity_name_id = 'enam_wp12otherwriter0002'",
        )
        == other_writer_row
    )
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entity_names") == 1


@pytest.mark.database
def test_downgrade_refuses_when_a_backfilled_row_is_entangled_in_supersession(
    legacy_engine: Engine,
) -> None:
    """A later writer built on the backfilled row, so the reverse is refused.

    Deleting a row another writer names as its successor would dangle
    `an_entity_name_is_superseded_within_its_principal`. That is not a reversal
    of what this migration did, so `downgrade()` refuses -- and the rows are
    still there afterwards.

    `an_entity_name_names_a_successor_only_when_superseded` requires the naming
    row's own `state` to be `superseded`, which is why the staged row carries
    it.
    """
    _stage_the_two_active_entities(legacy_engine)

    command.upgrade(_config(), "head")

    _stage_entity_name(
        legacy_engine,
        entity_name_id="enam_wp12supersedes0001",
        entity_id=ACTIVE_ORGANIZATION,
        name_type_code=NAME_TYPE_ALIAS,
        normalized_value="fixture harborline legacy",
        display_value="Fixture Harborline Legacy",
        state=NAME_STATE_SUPERSEDED,
        superseded_by_entity_name_id=_derived_entity_name_id(ACTIVE_ORGANIZATION),
    )
    before = _entity_name_rows(legacy_engine)
    assert len(before) == 3

    with pytest.raises(DBAPIError) as refusal:
        command.downgrade(_config(), PREVIOUS_REVISION)

    message = str(refusal.value)
    assert GUARD_PREFIX in message
    assert "downgrade guard" in message
    assert "1 offending row(s)" in message
    assert ACTIVE_ORGANIZATION in message
    assert _entity_name_rows(legacy_engine) == before


# --- 11. the round trip ------------------------------------------------------


@pytest.mark.database
def test_the_round_trip_leaves_no_residue_and_re_applies_cleanly(
    legacy_engine: Engine,
) -> None:
    """Empty to `head` to `PREVIOUS_REVISION` leaves nothing behind.

    Re-upgrading afterwards is the sharper half of the assertion: guard B
    refuses on a colliding derived identifier, so a downgrade that left even one
    of its own rows behind would make the second upgrade raise instead of
    reproducing the same two rows.
    """
    _stage_the_two_active_entities(legacy_engine)

    command.upgrade(_config(), "head")
    first_pass = _entity_name_rows(legacy_engine)
    assert len(first_pass) == 2

    command.downgrade(_config(), PREVIOUS_REVISION)
    assert _entity_name_rows(legacy_engine) == []
    assert _count(legacy_engine, "SELECT count(*) FROM knowledge.entities") == 2

    command.upgrade(_config(), "head")
    assert _entity_name_rows(legacy_engine) == first_pass
