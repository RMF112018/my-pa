"""PC-CM-IMP-WP02 §H.4: the stored Constraint Management schema, exercised both ways.

The `database` tier, on a disposable head-migrated clone. Nothing here goes
through the persistence adapter: every statement is SQLAlchemy Core against the
declared tables, so what is being proven is the *server's* refusal, not a Python
guard that happens to sit in front of it. Every CHECK, unique index, partial
unique index, foreign key and trigger plan §C declares is exercised in both
directions — a row the rule admits is written, and the row it forbids is
refused — because a constraint only tested from the accepting side is a
constraint that could be missing.

Every identifier, code, and label here is synthetic.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, Table, delete, insert, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, InternalError, OperationalError, ProgrammingError
from sqlalchemy.sql import Executable

from my_pa.infrastructure.persistence.tables import (
    SCHEMA,
    constraint_categories,
    constraint_category_history,
    constraint_project_settings,
    constraint_sync_baselines,
    constraint_sync_conflicts,
    constraint_sync_runs,
    constraint_sync_targets,
    project_constraint_evidence_links,
    project_constraint_history,
    project_constraint_parties,
    project_constraint_relationships,
    project_constraint_revision_parties,
    project_constraint_revisions,
    project_constraints,
    projects,
)

pytestmark = pytest.mark.database

#: The fourteen tables plan §C declares, in its own order.
CONSTRAINT_TABLES: Final[tuple[Table, ...]] = (
    constraint_project_settings,
    constraint_categories,
    project_constraints,
    project_constraint_parties,
    project_constraint_revisions,
    project_constraint_revision_parties,
    project_constraint_history,
    constraint_category_history,
    project_constraint_relationships,
    project_constraint_evidence_links,
    constraint_sync_targets,
    constraint_sync_runs,
    constraint_sync_baselines,
    constraint_sync_conflicts,
)

#: The four append-only ledgers an immutability trigger protects.
IMMUTABLE_LEDGERS: Final[tuple[Table, ...]] = (
    project_constraint_revisions,
    project_constraint_revision_parties,
    project_constraint_history,
    constraint_category_history,
)

PRINCIPAL = "prn_wpzeroaaaa0001aaaa0001"
PROJECT = "prj_wpzeroaaaa0001aaaa"
CATEGORY = "ccat_wpzeroaaaa0001aaaa"
CONSTRAINT = "cst_wpzeroaaaa0001aaaa"
CONSTRAINT_TWO = "cst_wpzerobbbb0002bbbb"
REVISION = "crev_wpzeroaaaa0001aaaa"
HISTORY = "chst_wpzeroaaaa0001aaaa"
CATEGORY_HISTORY = "cchst_wpzeroaaaa0001aaaa"
SYNC_TARGET = "csyt_wpzeroaaaa0001aaaa"
SYNC_RUN = "csyr_wpzeroaaaa0001aaaa"
DIGEST = "0" * 64
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
D0 = date(2026, 9, 1)

#: Column-name fragments that would mean a credential or a caller's own text had
#: found a home in this plane. `idempotency_key` is the one admitted `key`.
FORBIDDEN_FRAGMENTS: Final = ("token", "secret", "password", "credential", "cookie", "key")
ADMITTED_KEY_COLUMNS: Final = frozenset({"idempotency_key"})

_REFUSALS = (IntegrityError, InternalError, OperationalError, ProgrammingError)


def _refuses(connection: Connection, statement: Executable, *, names: str | None = None) -> None:
    """The server refuses `statement`, and the outer transaction survives to say so."""
    with pytest.raises(_REFUSALS) as refusal, connection.begin_nested():
        connection.execute(statement)
    if names is not None:
        assert names in str(refusal.value), str(refusal.value)


def _accepts(connection: Connection, statement: Executable) -> None:
    with connection.begin_nested():
        connection.execute(statement)


def _seed_project(
    connection: Connection, *, principal: str = PRINCIPAL, project: str = PROJECT
) -> None:
    connection.execute(
        insert(projects).values(
            project_id=project,
            principal_id=principal,
            name="Sample Project",
            state="active",
            participants=[],
            opened_at=T0,
            created_at=T0,
            updated_at=T0,
        )
    )


def _category_values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "category_id": CATEGORY,
        "principal_id": PRINCIPAL,
        "project_id": PROJECT,
        "prefix": "DES",
        "title": "Design",
        "description": None,
        "display_order": 0,
        "state": "active",
        "next_sequence": 1,
        "issued_count": 0,
        "prefix_locked_at": None,
        "version": 1,
        "created_at": T0,
        "updated_at": T0,
        "archived_at": None,
    }
    values.update(overrides)
    return values


def _constraint_values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "constraint_id": CONSTRAINT,
        "principal_id": PRINCIPAL,
        "project_id": PROJECT,
        "category_id": CATEGORY,
        "constraint_code": "2.01",
        "description": "Sample constraint",
        "date_identified": D0,
        "lifecycle_state": "identified",
        "due_date": date(2026, 9, 30),
        "reference": None,
        "current_update": None,
        "completion_date": None,
        "closure_commentary": None,
        "voided_date": None,
        "void_reason": None,
        "record_quality": "normal",
        "origin": "product",
        "published_at": T0,
        "version": 1,
        "current_revision_id": None,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return values


def _history_values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "history_id": HISTORY,
        "principal_id": PRINCIPAL,
        "project_id": PROJECT,
        "constraint_id": CONSTRAINT,
        "operation": "update",
        "actor": "principal",
        "outcome": "no_op",
        "before_version": 1,
        "after_version": 1,
        "occurred_at": T0,
        "recorded_at": T0,
        "idempotency_key": None,
        "request_digest": None,
        "client_context": None,
        "revision_id": None,
        "correlation_id": None,
        "safe_failure_reason": None,
    }
    values.update(overrides)
    return values


def _category_history_values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "history_id": CATEGORY_HISTORY,
        "principal_id": PRINCIPAL,
        "project_id": PROJECT,
        "category_id": CATEGORY,
        "operation": "create",
        "actor": "principal",
        "outcome": "no_op",
        "before_version": 1,
        "after_version": 1,
        "occurred_at": T0,
        "recorded_at": T0,
        "idempotency_key": None,
        "request_digest": None,
        "client_context": None,
        "correlation_id": None,
        "safe_failure_reason": None,
    }
    values.update(overrides)
    return values


def _revision_values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "revision_id": REVISION,
        "principal_id": PRINCIPAL,
        "project_id": PROJECT,
        "constraint_id": CONSTRAINT,
        "version": 1,
        "history_id": HISTORY,
        "category_id": CATEGORY,
        "constraint_code": "2.01",
        "description": "Sample constraint",
        "date_identified": D0,
        "lifecycle_state": "identified",
        "due_date": date(2026, 9, 30),
        "reference": None,
        "current_update": None,
        "completion_date": None,
        "closure_commentary": None,
        "voided_date": None,
        "void_reason": None,
        "record_quality": "normal",
        "origin": "product",
        "published_at": T0,
        "recorded_at": T0,
    }
    values.update(overrides)
    return values


def _party_values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "party_assignment_id": "cpty_wpzeroaaaa0001aaaa",
        "principal_id": PRINCIPAL,
        "constraint_id": CONSTRAINT,
        "role": "bic",
        "ordinal": 0,
        "party_kind": "principal",
        "entity_id": None,
        "display_label": None,
        "original_label": None,
        "resolved_at": None,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return values


def _base(connection: Connection) -> None:
    """Project, Category, Constraint, one receipt and one revision, all accepted."""
    _seed_project(connection)
    connection.execute(insert(constraint_categories).values(**_category_values()))
    connection.execute(insert(project_constraints).values(**_constraint_values()))
    connection.execute(insert(project_constraint_history).values(**_history_values()))
    connection.execute(insert(project_constraint_revisions).values(**_revision_values()))


# --- Correspondence and shape ------------------------------------------------


def test_the_declared_metadata_matches_the_migrated_database(migrated_engine: Engine) -> None:
    """Columns, constraint names and index names agree, for all fourteen tables."""
    with migrated_engine.begin() as connection:
        for table in CONSTRAINT_TABLES:
            stored_columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema = :schema AND table_name = :name"
                    ),
                    {"schema": SCHEMA, "name": table.name},
                )
            }
            assert stored_columns, f"{table.name} is absent from the migrated database"
            assert stored_columns == {column.name for column in table.c}, table.name

            stored_constraints = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint c"
                        " JOIN pg_class t ON t.oid = c.conrelid"
                        " JOIN pg_namespace n ON n.oid = t.relnamespace"
                        " WHERE n.nspname = :schema AND t.relname = :name"
                        " AND c.contype IN ('c', 'f', 'p', 'u')"
                    ),
                    {"schema": SCHEMA, "name": table.name},
                )
            }
            declared = {
                constraint.name
                for constraint in table.constraints
                if constraint.name is not None and not constraint.name.startswith("_unnamed_")
            }
            missing = {name for name in declared if name not in stored_constraints}
            assert missing == set(), f"{table.name} declares {sorted(missing)} the database lacks"

            stored_indexes = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes"
                        " WHERE schemaname = :schema AND tablename = :name"
                    ),
                    {"schema": SCHEMA, "name": table.name},
                )
            }
            declared_indexes = {index.name for index in table.indexes if index.name is not None}
            assert declared_indexes <= stored_indexes, table.name


def test_every_constraint_table_partitions_by_a_well_formed_principal(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        for table in CONSTRAINT_TABLES:
            column = table.c["principal_id"]
            assert not column.nullable, table.name
        _base(connection)
        _refuses(
            connection,
            insert(constraint_project_settings).values(
                principal_id="not-a-principal",
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            ),
        )
        _accepts(
            connection,
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            ),
        )


def test_no_constraint_table_carries_a_credential_or_payload_column(
    migrated_engine: Engine,
) -> None:
    """CM-BE-AC-067/133: there is nowhere for a secret or a request body to go."""
    with migrated_engine.begin() as connection:
        for table in CONSTRAINT_TABLES:
            for column in table.c:
                if column.name in ADMITTED_KEY_COLUMNS:
                    continue
                offending = [
                    fragment for fragment in FORBIDDEN_FRAGMENTS if fragment in column.name
                ]
                assert offending == [], f"{table.name}.{column.name}"
        assert connection.execute(select(constraint_sync_targets.c.principal_id)).all() == []


# --- C.1 project settings ----------------------------------------------------


def test_project_settings_are_unique_per_principal_and_project(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        row = {
            "principal_id": PRINCIPAL,
            "project_id": PROJECT,
            "timezone_name": "America/New_York",
            "version": 1,
            "created_at": T0,
            "updated_at": T0,
        }
        _accepts(connection, insert(constraint_project_settings).values(**row))
        _refuses(connection, insert(constraint_project_settings).values(**row))
        _refuses(
            connection,
            insert(constraint_project_settings).values(
                **{**row, "project_id": PROJECT, "timezone_name": "America/New York"}
            ),
        )
        _refuses(
            connection,
            insert(constraint_project_settings).values(**{**row, "version": 0}),
        )


# --- C.2 categories ----------------------------------------------------------


def test_a_category_prefix_is_unique_per_project_and_well_formed(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        _accepts(connection, insert(constraint_categories).values(**_category_values()))
        _refuses(
            connection,
            insert(constraint_categories).values(
                **_category_values(category_id="ccat_wpzerobbbb0002bbbb")
            ),
            names="constraint_categories_prefix_is_unique_per_project",
        )
        _accepts(
            connection,
            insert(constraint_categories).values(
                **_category_values(category_id="ccat_wpzerobbbb0002bbbb", prefix="PRO")
            ),
        )
        _refuses(
            connection,
            insert(constraint_categories).values(
                **_category_values(category_id="ccat_wpzerocccc0003cccc", prefix="_bad")
            ),
        )


def test_a_category_state_and_its_allocator_columns_are_bounded(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        for overrides in (
            {"state": "retired"},
            {"next_sequence": 0},
            {"issued_count": -1},
            {"version": 0},
            {"title": "   "},
            {"state": "archived", "archived_at": None},
            {"archived_at": T0},
            {"prefix_locked_at": T0},
            {"issued_count": 3},
        ):
            _refuses(
                connection, insert(constraint_categories).values(**_category_values(**overrides))
            )
        _accepts(
            connection,
            insert(constraint_categories).values(
                **_category_values(state="archived", archived_at=T0)
            ),
        )
        _accepts(
            connection,
            insert(constraint_categories).values(
                **_category_values(
                    category_id="ccat_wpzerobbbb0002bbbb",
                    prefix="PRO",
                    issued_count=3,
                    prefix_locked_at=T0,
                    next_sequence=4,
                )
            ),
        )


# --- C.3 constraints ---------------------------------------------------------


def test_a_constraint_code_is_unique_per_project_and_drafts_coexist(
    migrated_engine: Engine,
) -> None:
    """CM-BE-AC-071: the partial unique index is the final word on a public code."""
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        _accepts(connection, insert(project_constraints).values(**_constraint_values()))
        _refuses(
            connection,
            insert(project_constraints).values(**_constraint_values(constraint_id=CONSTRAINT_TWO)),
            names="project_constraints_code_is_unique_per_project",
        )
        draft = _constraint_values(
            lifecycle_state="draft",
            constraint_code=None,
            published_at=None,
            project_id=None,
            category_id=None,
            description=None,
            date_identified=None,
            due_date=None,
        )
        _accepts(
            connection,
            insert(project_constraints).values(
                **{**draft, "constraint_id": "cst_wpzerocccc0003cccc"}
            ),
        )
        _accepts(
            connection,
            insert(project_constraints).values(
                **{**draft, "constraint_id": "cst_wpzeroddd00004dddd"}
            ),
        )


def test_a_code_is_stored_as_text_and_returned_byte_exact(migrated_engine: Engine) -> None:
    """CM-BE-AC-027/028: `1.10` is not `1.1`, and `2.100` is not `2.1`."""
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        codes = ("1.10", "2.01", "2.10", "2.100")
        for index, code in enumerate(codes):
            connection.execute(
                insert(project_constraints).values(
                    **_constraint_values(
                        constraint_id=f"cst_wpzero{index}aaa0001aaaa", constraint_code=code
                    )
                )
            )
        stored = connection.execute(
            select(project_constraints.c.constraint_code).order_by(
                project_constraints.c.constraint_code
            )
        ).scalars()
        assert sorted(stored) == sorted(codes)


def test_a_draft_carries_no_code_and_a_published_row_carries_one(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        _refuses(
            connection,
            insert(project_constraints).values(
                **_constraint_values(lifecycle_state="draft", published_at=None)
            ),
            names="a_draft_constraint_carries_no_code",
        )
        _refuses(
            connection,
            insert(project_constraints).values(**_constraint_values(constraint_code=None)),
            names="a_draft_constraint_carries_no_code",
        )
        _refuses(
            connection,
            insert(project_constraints).values(**_constraint_values(published_at=None)),
            names="a_published_constraint_records_when_it_published",
        )
        _refuses(
            connection,
            insert(project_constraints).values(**_constraint_values(constraint_code="   ")),
        )


def test_a_published_constraint_is_complete_and_project_bound(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        for field in ("category_id", "description", "date_identified", "due_date"):
            _refuses(
                connection,
                insert(project_constraints).values(**_constraint_values(**{field: None})),
                names="a_published_constraint_is_complete",
            )
        _refuses(
            connection,
            insert(project_constraints).values(**_constraint_values(project_id=None)),
        )


def test_terminal_and_active_constraints_carry_only_their_own_fields(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        _refuses(
            connection,
            insert(project_constraints).values(**_constraint_values(lifecycle_state="closed")),
            names="a_closed_constraint_records_its_completion",
        )
        _accepts(
            connection,
            insert(project_constraints).values(
                **_constraint_values(lifecycle_state="closed", completion_date=D0)
            ),
        )
        _refuses(
            connection,
            insert(project_constraints).values(
                **_constraint_values(
                    constraint_id=CONSTRAINT_TWO,
                    constraint_code="2.02",
                    lifecycle_state="closed",
                    completion_date=D0,
                    voided_date=D0,
                    void_reason="duplicated",
                )
            ),
            names="a_closed_constraint_carries_no_void_fields",
        )
        _refuses(
            connection,
            insert(project_constraints).values(
                **_constraint_values(
                    constraint_id=CONSTRAINT_TWO, constraint_code="2.02", lifecycle_state="void"
                )
            ),
            names="a_void_constraint_records_its_reason",
        )
        _refuses(
            connection,
            insert(project_constraints).values(
                **_constraint_values(
                    constraint_id=CONSTRAINT_TWO,
                    constraint_code="2.02",
                    lifecycle_state="void",
                    voided_date=D0,
                    void_reason="duplicated",
                    completion_date=D0,
                )
            ),
            names="a_void_constraint_carries_no_completion",
        )
        _accepts(
            connection,
            insert(project_constraints).values(
                **_constraint_values(
                    constraint_id=CONSTRAINT_TWO,
                    constraint_code="2.02",
                    lifecycle_state="void",
                    voided_date=D0,
                    void_reason="duplicated",
                )
            ),
        )
        _refuses(
            connection,
            insert(project_constraints).values(
                **_constraint_values(
                    constraint_id="cst_wpzerocccc0003cccc",
                    constraint_code="2.03",
                    completion_date=D0,
                )
            ),
            names="an_active_constraint_carries_no_terminal_fields",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lifecycle_state", "retired"),
        ("record_quality", "partial"),
        ("origin", "spreadsheet"),
        ("version", 0),
    ],
)
def test_every_constraint_vocabulary_and_bound_is_closed(
    migrated_engine: Engine, field: str, value: object
) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        _refuses(
            connection, insert(project_constraints).values(**_constraint_values(**{field: value}))
        )


def test_a_constraint_belongs_to_its_own_principal_s_category(migrated_engine: Engine) -> None:
    """The composite same-Principal foreign key, from the refusing side."""
    other_principal = "prn_wpzerobbbb0002bbbb0002"
    other_project = "prj_wpzerobbbb0002bbbb"
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        _seed_project(connection, principal=other_principal, project=other_project)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        _refuses(
            connection,
            insert(project_constraints).values(
                **_constraint_values(principal_id=other_principal, project_id=other_project)
            ),
        )


# --- C.4 / C.6 parties -------------------------------------------------------


def test_a_party_row_names_its_entity_only_when_it_is_one(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        _refuses(
            connection,
            insert(project_constraint_parties).values(
                **_party_values(party_kind="entity", entity_id=None)
            ),
            names="an_entity_constraint_party_names_its_entity",
        )
        _refuses(
            connection,
            insert(project_constraint_parties).values(
                **_party_values(party_kind="principal", entity_id="ent_wpzeroaaaa0001aaaa")
            ),
            names="an_entity_constraint_party_names_its_entity",
        )
        _refuses(
            connection,
            insert(project_constraint_parties).values(
                **_party_values(party_kind="unresolved", display_label=None)
            ),
            names="an_unresolved_constraint_party_keeps_its_label",
        )
        _refuses(
            connection,
            insert(project_constraint_parties).values(**_party_values(role="approver")),
        )
        _refuses(
            connection,
            insert(project_constraint_parties).values(**_party_values(ordinal=-1)),
        )
        _accepts(connection, insert(project_constraint_parties).values(**_party_values()))
        _accepts(
            connection,
            insert(project_constraint_parties).values(
                **_party_values(
                    party_assignment_id="cpty_wpzerobbbb0002bbbb",
                    role="responsible",
                    party_kind="entity",
                    entity_id="ent_wpzeroaaaa0001aaaa",
                    display_label="Sample Vendor",
                )
            ),
        )


def test_a_constraint_holds_one_party_per_role_and_ordinal(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        _accepts(connection, insert(project_constraint_parties).values(**_party_values()))
        _refuses(
            connection,
            insert(project_constraint_parties).values(
                **_party_values(party_assignment_id="cpty_wpzerobbbb0002bbbb")
            ),
            names="project_constraint_parties_role_ordinal_is_unique",
        )
        _accepts(
            connection,
            insert(project_constraint_parties).values(
                **_party_values(party_assignment_id="cpty_wpzerobbbb0002bbbb", ordinal=1)
            ),
        )


def test_a_revision_party_row_is_keyed_by_revision_role_and_ordinal(
    migrated_engine: Engine,
) -> None:
    row = {
        "revision_id": REVISION,
        "principal_id": PRINCIPAL,
        "role": "bic",
        "ordinal": 0,
        "party_kind": "principal",
        "entity_id": None,
        "display_label": None,
        "original_label": None,
        "resolved_at": None,
    }
    with migrated_engine.begin() as connection:
        _base(connection)
        _accepts(connection, insert(project_constraint_revision_parties).values(**row))
        _refuses(connection, insert(project_constraint_revision_parties).values(**row))
        _refuses(
            connection,
            insert(project_constraint_revision_parties).values(
                **{**row, "ordinal": 1, "party_kind": "unresolved", "display_label": None}
            ),
            names="an_unresolved_revision_party_keeps_its_label",
        )
        _accepts(
            connection,
            insert(project_constraint_revision_parties).values({**row, "ordinal": 1}),
        )


# --- C.5 revisions -----------------------------------------------------------


def test_one_revision_per_constraint_version(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        _refuses(
            connection,
            insert(project_constraint_revisions).values(
                **_revision_values(revision_id="crev_wpzerobbbb0002bbbb")
            ),
            names="project_constraint_revisions_version_is_unique",
        )
        _accepts(
            connection,
            insert(project_constraint_revisions).values(
                **_revision_values(revision_id="crev_wpzerobbbb0002bbbb", version=2)
            ),
        )
        _refuses(
            connection,
            insert(project_constraint_revisions).values(
                **_revision_values(revision_id="crev_wpzerocccc0003cccc", version=0)
            ),
        )


def test_a_revision_snapshots_a_shape_the_current_row_could_not_hold(
    migrated_engine: Engine,
) -> None:
    """§C.5: completeness CHECKs are deliberately not repeated on the ledger."""
    with migrated_engine.begin() as connection:
        _base(connection)
        _accepts(
            connection,
            insert(project_constraint_revisions).values(
                **_revision_values(
                    revision_id="crev_wpzerobbbb0002bbbb",
                    version=2,
                    description=None,
                    due_date=None,
                    date_identified=None,
                )
            ),
        )


@pytest.mark.parametrize("ledger", IMMUTABLE_LEDGERS, ids=lambda table: table.name)
def test_an_append_only_ledger_refuses_update_and_delete(
    migrated_engine: Engine, ledger: Table
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_category_history).values(**_category_history_values()))
        connection.execute(
            insert(project_constraint_revision_parties).values(
                revision_id=REVISION,
                principal_id=PRINCIPAL,
                role="bic",
                ordinal=0,
                party_kind="principal",
                entity_id=None,
                display_label=None,
                original_label=None,
                resolved_at=None,
            )
        )
        assert connection.execute(select(ledger.c.principal_id)).all() != []
        _refuses(connection, update(ledger).values(principal_id=PRINCIPAL))
        _refuses(connection, delete(ledger))


# --- C.7 / C.8 receipts ------------------------------------------------------


def test_a_receipt_pairs_its_outcome_with_its_versions_and_revision(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        _refuses(
            connection,
            insert(project_constraint_history).values(
                **_history_values(
                    history_id="chst_wpzerobbbb0002bbbb", outcome="applied", after_version=1
                )
            ),
        )
        _refuses(
            connection,
            insert(project_constraint_history).values(
                **_history_values(history_id="chst_wpzerobbbb0002bbbb", after_version=2)
            ),
        )
        _refuses(
            connection,
            insert(project_constraint_history).values(
                **_history_values(
                    history_id="chst_wpzerobbbb0002bbbb",
                    outcome="applied",
                    after_version=2,
                    revision_id=None,
                )
            ),
        )
        _refuses(
            connection,
            insert(project_constraint_history).values(
                **_history_values(history_id="chst_wpzerobbbb0002bbbb", revision_id=REVISION)
            ),
        )
        _refuses(
            connection,
            insert(project_constraint_history).values(
                **_history_values(history_id="chst_wpzerobbbb0002bbbb", before_version=-1)
            ),
        )
        _accepts(
            connection,
            insert(project_constraint_history).values(
                **_history_values(
                    history_id="chst_wpzerobbbb0002bbbb",
                    outcome="applied",
                    after_version=2,
                    revision_id=REVISION,
                )
            ),
        )


def test_a_receipt_bounds_every_safe_field_and_admits_no_payload(
    migrated_engine: Engine,
) -> None:
    """CM-BE-AC-067: bounded label, bounded reason, sha256 digest, opaque key."""
    with migrated_engine.begin() as connection:
        _base(connection)
        for overrides in (
            {"safe_failure_reason": "x" * 129},
            {"outcome": "no_op", "safe_failure_reason": "version_conflict"},
            {"request_digest": "not-a-digest"},
            {"request_digest": "A" * 64},
            {"idempotency_key": "short"},
            {"idempotency_key": "has space in it"},
            {"client_context": "x" * 4096},
            {"correlation_id": "cst_wpzeroaaaa0001aaaa"},
            {"operation": "annotate"},
            {"actor": "robot"},
            {"outcome": "deferred"},
        ):
            _refuses(
                connection,
                insert(project_constraint_history).values(
                    **_history_values(history_id="chst_wpzerobbbb0002bbbb", **overrides)
                ),
            )
        _accepts(
            connection,
            insert(project_constraint_history).values(
                **_history_values(
                    history_id="chst_wpzerobbbb0002bbbb",
                    outcome="rejected",
                    safe_failure_reason="version_conflict",
                    request_digest=DIGEST,
                    idempotency_key="synthetic-key-0001",
                    client_context="cli",
                    correlation_id="corr_wpzeroaaaa0001aaaa",
                )
            ),
        )


def test_an_idempotency_key_is_unique_per_principal_on_both_ledgers(
    migrated_engine: Engine,
) -> None:
    """CM-BE-AC-072, and two NULL keys still coexist on each ledger."""
    with migrated_engine.begin() as connection:
        _base(connection)
        _accepts(
            connection,
            insert(project_constraint_history).values(
                **_history_values(
                    history_id="chst_wpzerobbbb0002bbbb", idempotency_key="synthetic-key-0001"
                )
            ),
        )
        _refuses(
            connection,
            insert(project_constraint_history).values(
                **_history_values(
                    history_id="chst_wpzerocccc0003cccc", idempotency_key="synthetic-key-0001"
                )
            ),
            names="project_constraint_history_key_is_unique_per_principal",
        )
        _accepts(
            connection,
            insert(project_constraint_history).values(
                **_history_values(history_id="chst_wpzerocccc0003cccc")
            ),
        )
        _accepts(
            connection,
            insert(constraint_category_history).values(
                **_category_history_values(idempotency_key="synthetic-key-0001")
            ),
        )
        _refuses(
            connection,
            insert(constraint_category_history).values(
                **_category_history_values(
                    history_id="cchst_wpzerobbbb0002bbbb", idempotency_key="synthetic-key-0001"
                )
            ),
        )
        _accepts(
            connection,
            insert(constraint_category_history).values(
                **_category_history_values(history_id="cchst_wpzerobbbb0002bbbb")
            ),
        )


def test_a_category_receipt_names_only_category_operations(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        _refuses(
            connection,
            insert(constraint_category_history).values(
                **_category_history_values(operation="publish")
            ),
        )
        _accepts(
            connection,
            insert(constraint_category_history).values(
                **_category_history_values(operation="archive")
            ),
        )


# --- C.9 / C.10 relationships and evidence -----------------------------------


def test_a_relationship_never_points_a_constraint_at_itself(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(project_constraints).values(
                **_constraint_values(constraint_id=CONSTRAINT_TWO, constraint_code="2.02")
            )
        )
        row = {
            "relationship_id": "crel_wpzeroaaaa0001aaaa",
            "principal_id": PRINCIPAL,
            "project_id": PROJECT,
            "source_constraint_id": CONSTRAINT,
            "target_constraint_id": CONSTRAINT_TWO,
            "relationship_type": "follow_up_of",
            "created_by_history_id": HISTORY,
            "created_at": T0,
        }
        _refuses(
            connection,
            insert(project_constraint_relationships).values(
                **{**row, "target_constraint_id": CONSTRAINT}
            ),
        )
        _refuses(
            connection,
            insert(project_constraint_relationships).values(
                **{**row, "relationship_type": "blocks"}
            ),
        )
        _accepts(connection, insert(project_constraint_relationships).values(**row))
        _refuses(
            connection,
            insert(project_constraint_relationships).values(
                **{**row, "relationship_id": "crel_wpzerobbbb0002bbbb"}
            ),
        )


def test_an_evidence_link_matches_its_reference_to_its_kind(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        row = {
            "evidence_link_id": "cevd_wpzeroaaaa0001aaaa",
            "principal_id": PRINCIPAL,
            "project_id": PROJECT,
            "constraint_id": CONSTRAINT,
            "evidence_kind": "capture",
            "evidence_ref": "cap_wpzeroaaaa0001aaaa",
            "role": "closure",
            "created_by_history_id": HISTORY,
            "created_at": T0,
        }
        _accepts(connection, insert(project_constraint_evidence_links).values(**row))
        _refuses(
            connection,
            insert(project_constraint_evidence_links).values(
                **{
                    **row,
                    "evidence_link_id": "cevd_wpzerobbbb0002bbbb",
                    "evidence_ref": "mdoc_wpzeroaaaa0001aaaa",
                }
            ),
            names="a_constraint_evidence_ref_matches_its_kind",
        )
        _refuses(
            connection,
            insert(project_constraint_evidence_links).values(
                **{
                    **row,
                    "evidence_link_id": "cevd_wpzerobbbb0002bbbb",
                    "evidence_kind": "email",
                    "evidence_ref": "cap_wpzerobbbb0002bbbb",
                }
            ),
        )
        _refuses(
            connection,
            insert(project_constraint_evidence_links).values(
                **{**row, "evidence_link_id": "cevd_wpzerobbbb0002bbbb", "role": "attachment"}
            ),
        )
        _refuses(
            connection,
            insert(project_constraint_evidence_links).values(
                **{**row, "evidence_link_id": "cevd_wpzerobbbb0002bbbb"}
            ),
        )


# --- C.11..C.14 sync substrate -----------------------------------------------


def _sync_target_values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "sync_target_id": SYNC_TARGET,
        "principal_id": PRINCIPAL,
        "project_id": PROJECT,
        "external_kind": "excel_workbook",
        "external_identity": "synthetic-workbook-identity-0001",
        "normalization_contract_version": "1",
        "last_verified_provider_version": None,
        "last_verified_workbook_digest": None,
        "last_verified_at": None,
        "last_verified_sync_run_id": None,
        "active_run_id": None,
        "active_run_lease_until": None,
        "version": 1,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return values


def _sync_run_values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "sync_run_id": SYNC_RUN,
        "principal_id": PRINCIPAL,
        "project_id": PROJECT,
        "sync_target_id": SYNC_TARGET,
        "state": "started",
        "started_at": T0,
        "finished_at": None,
        "provider_version_before": None,
        "provider_version_after": None,
        "workbook_digest_before": None,
        "workbook_digest_after": None,
        "preview_digest": None,
        "outcome": None,
        "safe_failure_reason": None,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return values


def test_a_sync_target_is_unique_per_project_and_holds_no_credential(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        _accepts(connection, insert(constraint_sync_targets).values(**_sync_target_values()))
        _refuses(
            connection,
            insert(constraint_sync_targets).values(
                **_sync_target_values(sync_target_id="csyt_wpzerobbbb0002bbbb")
            ),
        )
        for overrides in (
            {"external_kind": "google_sheet"},
            {"external_identity": "https://example.invalid/a b?token=x"},
            {"external_identity": "   "},
            {"last_verified_workbook_digest": "not-a-digest"},
            {"active_run_lease_until": T0},
            {"version": 0},
        ):
            candidate = {
                "sync_target_id": "csyt_wpzerobbbb0002bbbb",
                "external_identity": "synthetic-workbook-identity-0002",
                **overrides,
            }
            _refuses(
                connection,
                insert(constraint_sync_targets).values(**_sync_target_values(**candidate)),
            )


def test_a_sync_run_pairs_its_state_with_its_finish_and_reason(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        _accepts(connection, insert(constraint_sync_runs).values(**_sync_run_values()))
        for overrides in (
            {"state": "cancelled"},
            {"state": "started", "finished_at": T0},
            {"state": "applied"},
            {"state": "failed", "finished_at": T0},
            {"outcome": "partial"},
            {"workbook_digest_before": "not-a-digest"},
        ):
            _refuses(
                connection,
                insert(constraint_sync_runs).values(
                    **_sync_run_values(sync_run_id="csyr_wpzerobbbb0002bbbb", **overrides)
                ),
            )
        _accepts(
            connection,
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    sync_run_id="csyr_wpzerobbbb0002bbbb",
                    state="failed",
                    finished_at=T0,
                    outcome="failed",
                    safe_failure_reason="provider_unavailable",
                )
            ),
        )


def test_a_baseline_is_keyed_by_target_and_constraint_and_is_bounded(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        row = {
            "sync_target_id": SYNC_TARGET,
            "constraint_id": CONSTRAINT,
            "principal_id": PRINCIPAL,
            "project_id": PROJECT,
            "baseline_revision_id": REVISION,
            "baseline_constraint_version": 1,
            "baseline_field_digests": {"description": DIGEST},
            "baseline_record_digest": DIGEST,
            "workbook_row_identity": "synthetic-row-0001",
            "verified_provider_version": None,
            "verified_at": T0,
            "created_at": T0,
            "updated_at": T0,
        }
        _accepts(connection, insert(constraint_sync_baselines).values(**row))
        _refuses(connection, insert(constraint_sync_baselines).values(**row))
        for overrides in (
            {"baseline_constraint_version": 0},
            {"baseline_field_digests": ["not-an-object"]},
            {"baseline_field_digests": {"blob": "x" * 9216}},
            {"baseline_record_digest": "not-a-digest"},
            {"workbook_row_identity": "row with spaces"},
        ):
            _refuses(
                connection,
                insert(constraint_sync_baselines).values(
                    **{**row, "constraint_id": CONSTRAINT_TWO, **overrides}
                ),
            )


def test_one_open_conflict_per_target_constraint_and_kind(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        row = {
            "sync_conflict_id": "csyc_wpzeroaaaa0001aaaa",
            "principal_id": PRINCIPAL,
            "project_id": PROJECT,
            "sync_target_id": SYNC_TARGET,
            "constraint_id": CONSTRAINT,
            "sync_run_id": SYNC_RUN,
            "conflict_kind": "both_changed",
            "field_names": ["description"],
            "baseline_revision_id": REVISION,
            "db_version": 1,
            "provider_version": None,
            "external_candidate": {"description": "synthetic"},
            "external_candidate_digest": DIGEST,
            "state": "open",
            "created_at": T0,
            "resolved_at": None,
            "resolution_history_id": None,
        }
        _accepts(connection, insert(constraint_sync_conflicts).values(**row))
        _refuses(
            connection,
            insert(constraint_sync_conflicts).values(
                **{**row, "sync_conflict_id": "csyc_wpzerobbbb0002bbbb"}
            ),
            names="one_open_constraint_sync_conflict_per_kind",
        )
        for overrides in (
            {"conflict_kind": "renamed"},
            {"field_names": {"description": True}},
            {"external_candidate": {"blob": "x" * 9216}},
            {"state": "ignored"},
            {"state": "resolved", "resolved_at": None},
            {"state": "resolved", "resolved_at": T0},
            {"db_version": 0},
        ):
            _refuses(
                connection,
                insert(constraint_sync_conflicts).values(
                    **{
                        **row,
                        "sync_conflict_id": "csyc_wpzerobbbb0002bbbb",
                        "conflict_kind": "new_in_external",
                        **overrides,
                    }
                ),
            )
        _accepts(
            connection,
            insert(constraint_sync_conflicts).values(
                **{
                    **row,
                    "sync_conflict_id": "csyc_wpzerocccc0003cccc",
                    "state": "resolved",
                    "resolved_at": T0,
                    "resolution_history_id": HISTORY,
                }
            ),
        )


def test_a_bounded_jsonb_column_refuses_nine_kilobytes(migrated_engine: Engine) -> None:
    """No sync column is an unbounded document store."""
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        oversized = json.loads(json.dumps({"field": "x" * 9216}))
        _refuses(
            connection,
            insert(constraint_sync_baselines).values(
                sync_target_id=SYNC_TARGET,
                constraint_id=CONSTRAINT,
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                baseline_revision_id=REVISION,
                baseline_constraint_version=1,
                baseline_field_digests=oversized,
                baseline_record_digest=DIGEST,
                workbook_row_identity="synthetic-row-0001",
                verified_provider_version=None,
                verified_at=T0,
                created_at=T0,
                updated_at=T0,
            ),
        )


# --- The deferred foreign-key cycle ------------------------------------------


def test_the_deferred_cycle_commits_in_one_transaction(migrated_engine: Engine) -> None:
    """A Constraint, its newest revision and the receipt that wrote it, mutually linked."""
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        connection.execute(
            insert(project_constraints).values(**_constraint_values(current_revision_id=REVISION))
        )
        connection.execute(
            insert(project_constraint_revisions).values(**_revision_values(history_id=HISTORY))
        )
        connection.execute(
            insert(project_constraint_history).values(
                **_history_values(outcome="applied", after_version=2, revision_id=REVISION)
            )
        )
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                select(project_constraints.c.current_revision_id).where(
                    project_constraints.c.constraint_id == CONSTRAINT
                )
            ).scalar_one()
            == REVISION
        )


def test_a_dangling_deferred_reference_fails_at_commit(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        connection.execute(
            insert(project_constraints).values(
                **_constraint_values(current_revision_id="crev_wpzeronever0001nev")
            )
        )
        with pytest.raises(IntegrityError):
            transaction.commit()


# --- The narrow legacy exception (dispatch §12.4) ----------------------------


def _legacy_values(**overrides: object) -> dict[str, Any]:
    values = _constraint_values(
        constraint_id="cst_wpzerolegacy0001aa",
        origin="legacy_workbook_import",
        record_quality="legacy_incomplete",
        lifecycle_state="closed",
        constraint_code="7.03",
        published_at=None,
        description=None,
        date_identified=None,
        due_date=None,
        category_id=None,
        completion_date=None,
    )
    values.update(overrides)
    return values


def test_a_legacy_workbook_row_is_accepted_with_its_absences(migrated_engine: Engine) -> None:
    """CM-BE-AC-069: the four relaxations, gated on both columns together."""
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        _accepts(connection, insert(project_constraints).values(**_legacy_values()))
        stored = connection.execute(
            select(project_constraints.c.constraint_code, project_constraints.c.published_at).where(
                project_constraints.c.constraint_id == "cst_wpzerolegacy0001aa"
            )
        ).one()
        assert stored.constraint_code == "7.03"
        assert stored.published_at is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"origin": "product"},
        {"record_quality": "normal"},
    ],
    ids=["product_origin", "normal_quality"],
)
def test_the_legacy_relaxation_is_unreachable_from_a_product_row(
    migrated_engine: Engine, overrides: dict[str, Any]
) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        _refuses(connection, insert(project_constraints).values(**_legacy_values(**overrides)))


def test_the_legacy_exception_never_becomes_an_authoring_path(migrated_engine: Engine) -> None:
    """A Draft carrying a code is refused whatever its origin and quality say."""
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        _refuses(
            connection,
            insert(project_constraints).values(**_legacy_values(lifecycle_state="draft")),
            names="a_draft_constraint_carries_no_code",
        )
        _refuses(
            connection,
            insert(project_constraints).values(
                **_legacy_values(lifecycle_state="identified", project_id=None)
            ),
            names="a_published_constraint_belongs_to_a_project",
        )
