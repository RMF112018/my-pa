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

import hashlib
import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from typing import Any, Final, cast

import pytest
from sqlalchemy import (
    Engine,
    ForeignKeyConstraint,
    Table,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, InternalError, OperationalError, ProgrammingError
from sqlalchemy.sql import Executable

from my_pa.adapters.normalization import _preview_constraint_sync
from my_pa.application.commands import (
    ApplyConstraintSync,
    PreviewConstraintSync,
    ResolveConstraintSyncConflict,
)
from my_pa.application.constraint_management import (
    ConstraintManagementService,
    ConstraintOperationError,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.sync import (
    ConstraintSyncAction,
    ConstraintSyncResolution,
    NormalizedExternalConstraintRow,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
    SqlConstraintManagementRepository,
)
from my_pa.infrastructure.persistence.tables import (
    SCHEMA,
    constraint_categories,
    constraint_category_history,
    constraint_project_settings,
    constraint_sync_baselines,
    constraint_sync_conflicts,
    constraint_sync_legacy_unbound_conflicts,
    constraint_sync_resolution_history,
    constraint_sync_run_items,
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
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import DEFAULT_LIMITS

pytestmark = pytest.mark.database

#: The seventeen tables plan §C plus WP11 declare, in their dependency order.
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
    constraint_sync_legacy_unbound_conflicts,
    constraint_sync_run_items,
    constraint_sync_resolution_history,
)

#: The five append-only ledgers an immutability trigger protects.
IMMUTABLE_LEDGERS: Final[tuple[Table, ...]] = (
    project_constraint_revisions,
    project_constraint_revision_parties,
    project_constraint_history,
    constraint_category_history,
    constraint_sync_resolution_history,
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
#: found a home in this plane. The admitted names are bounded synchronization
#: controls, never provider credentials or request bodies.
FORBIDDEN_FRAGMENTS: Final = ("token", "secret", "password", "credential", "cookie", "key")
ADMITTED_KEY_COLUMNS: Final = frozenset(
    {
        "idempotency_key",
        "lease_token",
        "preview_idempotency_key",
        "apply_idempotency_key",
        "acknowledge_idempotency_key",
        "external_row_key",
    }
)

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
    """Columns, constraint names and index names agree for all seventeen tables."""
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
        if ledger is constraint_sync_resolution_history:
            connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
            connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
            connection.execute(
                insert(constraint_sync_conflicts).values(
                    **_sync_conflict_values(
                        state="resolved",
                        resolved_at=T0,
                        resolution_history_id="csyrh_wpzeroaaaa0001aaaa",
                    )
                )
            )
            connection.execute(
                insert(constraint_sync_resolution_history).values(
                    resolution_history_id="csyrh_wpzeroaaaa0001aaaa",
                    principal_id=PRINCIPAL,
                    project_id=PROJECT,
                    sync_target_id=SYNC_TARGET,
                    sync_conflict_id="csyc_wpzeroaaaa0001aaaa",
                    sync_run_id=SYNC_RUN,
                    resolution="keep_canonical",
                    expected_constraint_version=1,
                    idempotency_key="resolved_sync_0001",
                    request_digest=DIGEST,
                    constraint_version=1,
                    created_at=T0,
                )
            )
        assert connection.execute(select(ledger.c.principal_id)).all() != []
        _refuses(connection, update(ledger).values(principal_id=PRINCIPAL))
        _refuses(connection, delete(ledger))
        assert connection.execute(select(ledger.c.principal_id)).all() != []


@pytest.mark.parametrize("duplicate", ["constraint_id", "constraint_code"])
def test_duplicate_sync_identity_is_rejected_before_any_persistence(
    migrated_engine: Engine, duplicate: str
) -> None:
    first = NormalizedExternalConstraintRow(
        external_row_key="row-1",
        constraint_id=CONSTRAINT,
        constraint_code="C.01",
    )
    second = NormalizedExternalConstraintRow(
        external_row_key="row-2",
        constraint_id=CONSTRAINT if duplicate == "constraint_id" else CONSTRAINT_TWO,
        constraint_code=" C.02 " if duplicate == "constraint_id" else " C.01 ",
    )
    with pytest.raises(InvalidRequestError):
        PreviewConstraintSync(
            project_id=PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=(first, second),
            idempotency_key="preview_sync_0001",
        )
    with migrated_engine.begin() as connection:
        for table in (
            constraint_sync_targets,
            constraint_sync_runs,
            constraint_sync_baselines,
            constraint_sync_conflicts,
            constraint_sync_run_items,
            constraint_sync_resolution_history,
        ):
            assert connection.execute(select(func.count()).select_from(table)).scalar_one() == 0


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
        "sync_state": "never_synced",
        "lease_token": DIGEST,
        "preview_lease_until": T0,
        "started_at": T0,
        "finished_at": None,
        "provider_version_before": None,
        "provider_version_after": None,
        "workbook_digest_before": None,
        "workbook_digest_after": None,
        "preview_digest": None,
        "outcome": None,
        "safe_failure_reason": None,
        "failure_kind": None,
        "preview_idempotency_key": "preview_sync_0001",
        "preview_request_digest": DIGEST,
        "apply_idempotency_key": None,
        "apply_request_digest": None,
        "apply_canonical_digest": None,
        "apply_sync_state": None,
        "acknowledge_idempotency_key": None,
        "acknowledge_request_digest": None,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return values


def _sync_conflict_values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
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
    values.update(overrides)
    return values


def _activate_sync_run(connection: Connection) -> None:
    connection.execute(
        update(constraint_sync_targets)
        .where(constraint_sync_targets.c.sync_target_id == SYNC_TARGET)
        .values(
            last_run_id=SYNC_RUN,
            active_run_id=SYNC_RUN,
            active_run_lease_until=T0 + timedelta(minutes=5),
        )
    )


def test_sync_delta_authenticates_the_exact_principal_project_target_before_reading(
    migrated_engine: Engine,
) -> None:
    other_project = "prj_wpzerocccc0003cccc"
    other_target = "csyt_wpzerocccc0003cccc"
    foreign_principal = "prn_wpzerobbbb0002bbbb0002"
    foreign_project = "prj_wpzerobbbb0002bbbb"
    foreign_target = "csyt_wpzerobbbb0002bbbb"
    with migrated_engine.begin() as connection:
        _base(connection)
        _seed_project(connection, project=other_project)
        _seed_project(connection, principal=foreign_principal, project=foreign_project)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_targets).values(
                **_sync_target_values(
                    sync_target_id=other_target,
                    project_id=other_project,
                    external_identity="synthetic-workbook-identity-0002",
                )
            )
        )
        connection.execute(
            insert(constraint_sync_targets).values(
                **_sync_target_values(
                    sync_target_id=foreign_target,
                    principal_id=foreign_principal,
                    project_id=foreign_project,
                    external_identity="synthetic-workbook-identity-0003",
                )
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        visible = repository.read_sync_delta(
            PRINCIPAL, PROJECT, SYNC_TARGET, limit=100, cursor=None
        )
        assert visible is not None and [row["constraint_id"] for row in visible] == [CONSTRAINT]
        hidden = (
            repository.read_sync_delta(
                PRINCIPAL,
                PROJECT,
                "csyt_wpzeroabsent0004aaaa",
                limit=100,
                cursor=None,
            ),
            repository.read_sync_delta(
                PRINCIPAL, foreign_project, foreign_target, limit=100, cursor=None
            ),
            repository.read_sync_delta(PRINCIPAL, PROJECT, other_target, limit=100, cursor=None),
        )
        assert hidden == (None, None, None)


def test_sync_preview_hides_foreign_and_absent_projects_alike(migrated_engine: Engine) -> None:
    foreign_principal = "prn_wpzerobbbb0002bbbb0002"
    foreign_project = "prj_wpzerobbbb0002bbbb"
    absent_project = "prj_wpzerocccc0003cccc"
    with migrated_engine.begin() as connection:
        _seed_project(connection, principal=foreign_principal, project=foreign_project)
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=foreign_principal,
                project_id=foreign_project,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        errors = []
        for project_id in (foreign_project, absent_project):
            with pytest.raises(ValueError) as refusal:
                repository.preview_sync(
                    PRINCIPAL,
                    project_id,
                    external_identity="synthetic-workbook-identity-0001",
                    normalization_version="1",
                    rows=(NormalizedExternalConstraintRow(external_row_key="row-1"),),
                    provider_version=None,
                    workbook_digest=None,
                    idempotency_key="preview_sync_0001",
                    at=T0,
                    lease_until=T0,
                )
            errors.append(str(refusal.value))
        assert errors == ["the synchronization project is unavailable"] * 2


def test_a_sync_conflict_names_a_run_in_the_same_project_and_target(
    migrated_engine: Engine,
) -> None:
    other_project = "prj_wpzerobbbb0002bbbb"
    other_target = "csyt_wpzerobbbb0002bbbb"
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        _seed_project(connection, project=other_project)
        connection.execute(
            insert(constraint_sync_targets).values(
                **_sync_target_values(
                    sync_target_id=other_target,
                    project_id=other_project,
                    external_identity="synthetic-workbook-identity-0002",
                )
            )
        )
        _refuses(
            connection,
            insert(constraint_sync_conflicts).values(
                **_sync_conflict_values(
                    project_id=other_project,
                    sync_target_id=other_target,
                    constraint_id=None,
                    conflict_kind="new_in_external",
                    baseline_revision_id=None,
                    db_version=None,
                )
            ),
            names="a_sync_conflict_names_a_run_of_its_principal",
        )


def test_sync_target_run_pointers_name_only_runs_in_the_same_scope(
    migrated_engine: Engine,
) -> None:
    other_target = "csyt_wpzerobbbb0002bbbb"
    other_run = "csyr_wpzerobbbb0002bbbb"
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_targets).values(
                **_sync_target_values(
                    sync_target_id=other_target,
                    external_identity="synthetic-workbook-identity-0002",
                )
            )
        )
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(sync_run_id=other_run, sync_target_id=other_target)
            )
        )
        for constraint_name, values in (
            (
                "a_sync_target_names_an_active_run_of_its_principal",
                {"active_run_id": other_run, "active_run_lease_until": T0},
            ),
            (
                "a_sync_target_names_a_verified_run_of_its_principal",
                {"last_verified_sync_run_id": other_run},
            ),
            (
                "a_sync_target_names_its_last_run_of_its_principal",
                {"last_run_id": other_run},
            ),
        ):
            with pytest.raises(_REFUSALS) as refusal, connection.begin_nested():
                connection.execute(
                    update(constraint_sync_targets)
                    .where(constraint_sync_targets.c.sync_target_id == SYNC_TARGET)
                    .values(**values)
                )
                connection.execute(text(f'SET CONSTRAINTS "{constraint_name}" IMMEDIATE'))
            assert constraint_name in str(refusal.value)


@pytest.mark.parametrize("foreign_lease_until", [T0 - timedelta(minutes=1), T0 + timedelta(5)])
def test_preview_never_blocks_on_or_mutates_a_foreign_target_run_pointer(
    migrated_engine: Engine,
    foreign_lease_until: datetime,
) -> None:
    other_target = "csyt_wpzerobbbb0002bbbb"
    other_run = "csyr_wpzerobbbb0002bbbb"
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_targets).values(
                **_sync_target_values(
                    sync_target_id=other_target,
                    external_identity="synthetic-workbook-identity-0002",
                )
            )
        )
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(sync_run_id=other_run, sync_target_id=other_target)
            )
        )
        connection.execute(
            update(constraint_sync_targets)
            .where(constraint_sync_targets.c.sync_target_id == SYNC_TARGET)
            .values(
                active_run_id=other_run,
                active_run_lease_until=foreign_lease_until,
                last_run_id=other_run,
            )
        )

        preview = SqlConstraintManagementRepository(connection).preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=(),
            provider_version=None,
            workbook_digest=None,
            idempotency_key=(
                "preview_foreign_live_0001"
                if foreign_lease_until > T0
                else "preview_foreign_expired_0001"
            ),
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )

        assert preview["run_id"] != other_run
        foreign = (
            connection.execute(
                select(constraint_sync_runs).where(constraint_sync_runs.c.sync_run_id == other_run)
            )
            .one()
            ._mapping
        )
        assert foreign["state"] == "started"
        assert foreign["safe_failure_reason"] is None
        target = (
            connection.execute(
                select(constraint_sync_targets).where(
                    constraint_sync_targets.c.sync_target_id == SYNC_TARGET
                )
            )
            .one()
            ._mapping
        )
        assert target["active_run_id"] == preview["run_id"]
        assert target["last_run_id"] == preview["run_id"]


def test_sync_state_does_not_consume_or_disclose_foreign_target_pointers(
    migrated_engine: Engine,
) -> None:
    other_target = "csyt_wpzerobbbb0002bbbb"
    other_run = "csyr_wpzerobbbb0002bbbb"
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_targets).values(
                **_sync_target_values(
                    sync_target_id=other_target,
                    external_identity="synthetic-workbook-identity-0002",
                )
            )
        )
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    sync_run_id=other_run,
                    sync_target_id=other_target,
                    sync_state="conflict",
                )
            )
        )
        connection.execute(
            update(constraint_sync_targets)
            .where(constraint_sync_targets.c.sync_target_id == SYNC_TARGET)
            .values(
                active_run_id=other_run,
                active_run_lease_until=T0 + timedelta(minutes=5),
                last_run_id=other_run,
            )
        )
        state = SqlConstraintManagementRepository(connection).read_sync_state(
            PRINCIPAL, PROJECT, SYNC_TARGET
        )
        assert state is not None
        assert state["state"] == "never_synced"
        assert state["last_run_id"] is None
        assert state["active_run_id"] is None
        assert state["active_run_lease_until"] is None
        connection.execute(
            update(constraint_sync_targets)
            .where(constraint_sync_targets.c.sync_target_id == SYNC_TARGET)
            .values(active_run_id=None, active_run_lease_until=None, last_run_id=None)
        )


def test_a_sync_run_item_row_identity_matches_the_verified_baseline_contract(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        row = {
            "sync_run_id": SYNC_RUN,
            "principal_id": PRINCIPAL,
            "project_id": PROJECT,
            "sync_target_id": SYNC_TARGET,
            "external_row_key": "r" * 256,
            "constraint_id": CONSTRAINT,
            "action": "no_op",
            "expected_constraint_version": 1,
            "field_names": [],
            "response_summary": {},
            "created_at": T0,
            "updated_at": T0,
        }
        _accepts(connection, insert(constraint_sync_run_items).values(**row))
        _refuses(
            connection,
            insert(constraint_sync_run_items).values(
                **{**row, "external_row_key": "row with spaces"}
            ),
            names="a_sync_item_row_identity_is_bounded",
        )
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_run_items)
            ).scalar_one()
            == 1
        )


def test_preview_turns_verified_row_key_swaps_into_bounded_identity_conflicts(
    migrated_engine: Engine,
) -> None:
    second_revision = "crev_wpzerobbbb0002bbbb"
    second_history = "chst_wpzerobbbb0002bbbb"

    def external(record: object, row_key: str) -> NormalizedExternalConstraintRow:
        item = cast(Any, record)
        return NormalizedExternalConstraintRow(
            external_row_key=row_key,
            constraint_id=item.constraint_id,
            constraint_code=item.constraint_code,
            category=item.category_id,
            description=item.description,
            date_identified=item.date_identified,
            status=item.lifecycle_state,
            bic=item.bic,
            responsible=item.responsible,
            due_date=item.due_date,
            reference=item.reference,
            current_update=item.current_update,
            completion_date=item.completion_date,
        )

    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(project_constraints).values(
                **_constraint_values(constraint_id=CONSTRAINT_TWO, constraint_code="2.02")
            )
        )
        connection.execute(
            insert(project_constraint_history).values(
                **_history_values(history_id=second_history, constraint_id=CONSTRAINT_TWO)
            )
        )
        connection.execute(
            insert(project_constraint_revisions).values(
                **_revision_values(
                    revision_id=second_revision,
                    history_id=second_history,
                    constraint_id=CONSTRAINT_TWO,
                    constraint_code="2.02",
                )
            )
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        first = repository.read_constraint(PRINCIPAL, CONSTRAINT)
        second = repository.read_constraint(PRINCIPAL, CONSTRAINT_TWO)
        assert first is not None and second is not None
        baseline_rows = (
            (first, REVISION, "row-1"),
            (second, second_revision, "row-2"),
        )
        for record, revision_id, row_key in baseline_rows:
            row = external(record, row_key)
            connection.execute(
                insert(constraint_sync_baselines).values(
                    sync_target_id=SYNC_TARGET,
                    constraint_id=record.constraint_id,
                    principal_id=PRINCIPAL,
                    project_id=PROJECT,
                    baseline_revision_id=revision_id,
                    baseline_constraint_version=record.version,
                    baseline_field_digests=row.field_digests(),
                    baseline_record_digest=row.record_digest(),
                    workbook_row_identity=row_key,
                    verified_at=T0,
                    created_at=T0,
                    updated_at=T0,
                )
            )
        preview = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=(external(first, "row-2"), external(second, "row-1")),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_0001",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        assert preview["state"] == "conflict"
        assert {
            (item["row"], item["action"], item["kind"])
            for item in cast(list[Mapping[str, object]], preview["items"])
        } == {
            ("row-1", "conflict", "identity"),
            ("row-2", "conflict", "identity"),
        }
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_run_items)
            ).scalar_one()
            == 2
        )
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_conflicts)
            ).scalar_one()
            == 2
        )
        assert connection.execute(
            select(constraint_sync_baselines.c.workbook_row_identity).order_by(
                constraint_sync_baselines.c.workbook_row_identity
            )
        ).scalars().all() == ["row-1", "row-2"]


def test_preview_caps_the_combined_plan_at_one_hundred_before_any_write(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        for index in range(2, 100):
            connection.execute(
                insert(project_constraints).values(
                    **_constraint_values(
                        constraint_id=f"cst_bound{index:04d}aaaa",
                        constraint_code=f"2.{index:02d}",
                    )
                )
            )
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        accepted = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0100",
            normalization_version="1",
            rows=(NormalizedExternalConstraintRow(external_row_key="new-row"),),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_0100",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        assert len(cast(list[object], accepted["items"])) == 100
        before = tuple(
            connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (
                constraint_sync_targets,
                constraint_sync_runs,
                constraint_sync_run_items,
                constraint_sync_conflicts,
            )
        )
        with pytest.raises(ValueError, match="100 total plan items"):
            repository.preview_sync(
                PRINCIPAL,
                PROJECT,
                external_identity="synthetic-workbook-identity-0101",
                normalization_version="1",
                rows=(
                    NormalizedExternalConstraintRow(external_row_key="new-row-a"),
                    NormalizedExternalConstraintRow(external_row_key="new-row-b"),
                ),
                provider_version=None,
                workbook_digest=None,
                idempotency_key="preview_sync_0101",
                at=T0,
                lease_until=T0 + timedelta(minutes=5),
            )
        after = tuple(
            connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (
                constraint_sync_targets,
                constraint_sync_runs,
                constraint_sync_run_items,
                constraint_sync_conflicts,
            )
        )
        assert after == before
        accepted_run_id = str(accepted["run_id"])
        run_before = connection.execute(
            select(
                constraint_sync_runs.c.state,
                constraint_sync_runs.c.sync_state,
                constraint_sync_runs.c.safe_failure_reason,
            ).where(constraint_sync_runs.c.sync_run_id == accepted_run_id)
        ).one()
        target_before = connection.execute(
            select(
                constraint_sync_targets.c.active_run_id,
                constraint_sync_targets.c.active_run_lease_until,
            ).where(constraint_sync_targets.c.sync_target_id == accepted["target_id"])
        ).one()
        with pytest.raises(ValueError, match="100 total plan items"):
            repository.preview_sync(
                PRINCIPAL,
                PROJECT,
                external_identity="synthetic-workbook-identity-0100",
                normalization_version="1",
                rows=(
                    NormalizedExternalConstraintRow(external_row_key="new-row-c"),
                    NormalizedExternalConstraintRow(external_row_key="new-row-d"),
                ),
                provider_version=None,
                workbook_digest=None,
                idempotency_key="preview_sync_0102",
                at=T0 + timedelta(minutes=6),
                lease_until=T0 + timedelta(minutes=11),
            )
        assert (
            connection.execute(
                select(
                    constraint_sync_runs.c.state,
                    constraint_sync_runs.c.sync_state,
                    constraint_sync_runs.c.safe_failure_reason,
                ).where(constraint_sync_runs.c.sync_run_id == accepted_run_id)
            ).one()
            == run_before
        )
        assert (
            connection.execute(
                select(
                    constraint_sync_targets.c.active_run_id,
                    constraint_sync_targets.c.active_run_lease_until,
                ).where(constraint_sync_targets.c.sync_target_id == accepted["target_id"])
            ).one()
            == target_before
        )


@pytest.mark.parametrize("explicit_code", [None, "unrelated-code"])
@pytest.mark.parametrize("reverse", [False, True])
def test_preview_rejects_two_rows_resolving_to_one_canonical_constraint_before_writes(
    migrated_engine: Engine, explicit_code: str | None, reverse: bool
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(constraint_code="C.01")
        )
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        rows = (
            NormalizedExternalConstraintRow(
                external_row_key="row-explicit",
                constraint_id=CONSTRAINT,
                constraint_code=explicit_code,
            ),
            NormalizedExternalConstraintRow(
                external_row_key="row-code",
                constraint_code="c.01",
            ),
        )
        if reverse:
            rows = tuple(reversed(rows))
        with pytest.raises(ValueError, match="resolve to one canonical constraint"):
            SqlConstraintManagementRepository(connection).preview_sync(
                PRINCIPAL,
                PROJECT,
                external_identity="synthetic-workbook-identity-alias",
                normalization_version="1",
                rows=rows,
                provider_version=None,
                workbook_digest=None,
                idempotency_key="preview_sync_alias0001",
                at=T0,
                lease_until=T0 + timedelta(minutes=5),
            )
        for table in (
            constraint_sync_targets,
            constraint_sync_runs,
            constraint_sync_run_items,
            constraint_sync_conflicts,
        ):
            assert connection.execute(select(func.count()).select_from(table)).scalar_one() == 0


def test_one_explicit_identity_with_a_mismatched_code_remains_an_identity_conflict(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        preview = SqlConstraintManagementRepository(connection).preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-mismatch",
            normalization_version="1",
            rows=(
                NormalizedExternalConstraintRow(
                    external_row_key="row-1",
                    constraint_id=CONSTRAINT,
                    constraint_code="wrong-code",
                ),
            ),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_mismatch0001",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        assert preview["state"] == "conflict"
        assert cast(list[Mapping[str, object]], preview["items"])[0]["kind"] == "identity"


def test_a_sync_resolution_names_the_conflicts_exact_target_and_run(
    migrated_engine: Engine,
) -> None:
    other_target = "csyt_wpzerobbbb0002bbbb"
    other_run = "csyr_wpzerobbbb0002bbbb"
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(insert(constraint_sync_conflicts).values(**_sync_conflict_values()))
        connection.execute(
            insert(constraint_sync_targets).values(
                **_sync_target_values(
                    sync_target_id=other_target,
                    external_identity="synthetic-workbook-identity-0002",
                )
            )
        )
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    sync_run_id=other_run,
                    sync_target_id=other_target,
                    preview_idempotency_key="preview_sync_0002",
                )
            )
        )
        _refuses(
            connection,
            insert(constraint_sync_resolution_history).values(
                resolution_history_id="csyrh_wpzeroaaaa0001aaaa",
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                sync_target_id=other_target,
                sync_conflict_id="csyc_wpzeroaaaa0001aaaa",
                sync_run_id=other_run,
                resolution="keep_canonical",
                expected_constraint_version=1,
                idempotency_key="resolved_sync_0001",
                request_digest=DIGEST,
                constraint_version=1,
                created_at=T0,
            ),
            names="a_sync_resolution_names_its_principals_conflict",
        )


def test_complete_sync_apply_returns_and_persists_partial(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    state="previewed",
                    sync_state="conflict",
                    preview_digest=DIGEST,
                    apply_idempotency_key="apply_sync_0001",
                    apply_request_digest="e" * 64,
                )
            )
        )
        connection.execute(insert(constraint_sync_conflicts).values(**_sync_conflict_values()))
        repository = SqlConstraintManagementRepository(connection)
        result = repository.complete_sync_apply(PRINCIPAL, SYNC_RUN, applied={}, at=T0)
        assert result["state"] == "partial"
        assert result["canonical_digest"] == hashlib.sha256(b"[]").hexdigest()
        assert result["item_count"] == 0
        assert result["action_counts"] == {action.value: 0 for action in ConstraintSyncAction}
        replay = repository.prepare_sync_apply(
            PRINCIPAL,
            PROJECT,
            SYNC_TARGET,
            SYNC_RUN,
            lease_token=DIGEST,
            preview_digest=DIGEST,
            idempotency_key="apply_sync_0001",
            request_digest="e" * 64,
            at=T0,
        )
        assert replay is not None
        assert replay["apply_result"] == {**result, "replayed": True}
        stored = connection.execute(
            select(constraint_sync_runs.c.sync_state).where(
                constraint_sync_runs.c.sync_run_id == SYNC_RUN
            )
        ).scalar_one()
        assert stored == "partial"


def test_disjoint_merge_applies_description_without_reverting_canonical_status(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(current_revision_id=REVISION)
        )
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        repository = SqlConstraintManagementRepository(connection)
        original = repository.read_constraint(PRINCIPAL, CONSTRAINT)
        assert original is not None
        baseline_row = NormalizedExternalConstraintRow(
            external_row_key="row-1",
            constraint_id=CONSTRAINT,
            constraint_code=original.constraint_code,
            category=original.category_id,
            description=original.description,
            date_identified=original.date_identified,
            status=original.lifecycle_state,
            bic=original.bic,
            responsible=original.responsible,
            due_date=original.due_date,
            reference=original.reference,
            current_update=original.current_update,
            completion_date=original.completion_date,
        )
        connection.execute(
            insert(constraint_sync_baselines).values(
                sync_target_id=SYNC_TARGET,
                constraint_id=CONSTRAINT,
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                baseline_revision_id=REVISION,
                baseline_constraint_version=original.version,
                baseline_field_digests=baseline_row.field_digests(),
                baseline_record_digest=baseline_row.record_digest(),
                workbook_row_identity="row-1",
                verified_at=T0,
                created_at=T0,
                updated_at=T0,
            )
        )
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(lifecycle_state="in_progress", version=2, updated_at=T0)
        )
        external = NormalizedExternalConstraintRow(
            external_row_key="row-1",
            constraint_id=CONSTRAINT,
            constraint_code=original.constraint_code,
            category=original.category_id,
            description="External description",
            date_identified=original.date_identified,
            status=original.lifecycle_state,
            bic=original.bic,
            responsible=original.responsible,
            due_date=original.due_date,
            reference=original.reference,
            current_update=original.current_update,
            completion_date=original.completion_date,
        )
        preview = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=(external,),
            provider_version="v1",
            workbook_digest=DIGEST,
            idempotency_key="preview_sync_disjoint0001",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        item = connection.execute(select(constraint_sync_run_items)).one()._mapping
        assert item["action"] == "merge", (
            item["action"],
            item["field_names"],
            item["response_summary"],
        )
        assert item["field_names"] == ["description"]
        assert preview["state"] == "external_import_pending"
        history_before = connection.execute(
            select(func.count()).select_from(project_constraint_history)
        ).scalar_one()

    audit = SqlAlchemyAuditSink(migrated_engine)
    service = ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(migrated_engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: T0,
        constraint_management_unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(
            migrated_engine
        ),
    )
    principal = Principal(principal_id=PRINCIPAL, kind=PrincipalKind.GATEWAY, authenticated=True)
    command = ApplyConstraintSync(
        project_id=PROJECT,
        target_id=str(preview["target_id"]),
        run_id=str(preview["run_id"]),
        lease_token=str(preview["lease_token"]),
        preview_digest=str(preview["preview_digest"]),
        idempotency_key="apply_sync_disjoint0001",
    )
    metadata = RequestMetadata(
        request_id="request-sync-disjoint-merge-0001",
        capability=Capability.CONSTRAINT_SYNC_APPLY,
        purpose=Purpose.CONSTRAINT_SYNC_AUTHORING,
        principal_id=PRINCIPAL,
        requested_at=T0,
    )
    initial = service.invoke(metadata, command, principal=principal)
    assert initial.error is None and initial.result is not None
    assert initial.result["action_counts"]["merge"] == 1  # type: ignore[index]
    assert initial.result["item_count"] == 1
    assert initial.result["state"] == "verification_pending"
    replay = service.invoke(metadata, command, principal=principal)
    assert replay.error is None and replay.result == {**initial.result, "replayed": True}
    with migrated_engine.begin() as connection:
        stored = connection.execute(
            select(
                project_constraints.c.lifecycle_state,
                project_constraints.c.description,
                project_constraints.c.version,
            ).where(project_constraints.c.constraint_id == CONSTRAINT)
        ).one()
        assert stored == ("in_progress", "External description", 3)
        assert (
            connection.execute(
                select(func.count()).select_from(project_constraint_history)
            ).scalar_one()
            == history_before + 1
        )
        run = connection.execute(
            select(
                constraint_sync_runs.c.apply_canonical_digest,
                constraint_sync_runs.c.apply_sync_state,
            ).where(constraint_sync_runs.c.sync_run_id == preview["run_id"])
        ).one()
        assert run == (initial.result["canonical_digest"], "verification_pending")


@pytest.mark.parametrize(
    ("closed", "repair_after_failed_ack"),
    [(False, False), (True, True)],
    ids=("ordinary-convergence", "closed-convergence-repair"),
)
def test_converged_rows_verify_without_duplicate_canonical_mutation(
    migrated_engine: Engine,
    closed: bool,
    repair_after_failed_ack: bool,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(current_revision_id=REVISION)
        )
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        original = repository.read_constraint(PRINCIPAL, CONSTRAINT)
        assert original is not None
        baseline_row = NormalizedExternalConstraintRow(
            external_row_key="row-converged",
            constraint_id=CONSTRAINT,
            constraint_code=original.constraint_code,
            category=original.category_id,
            description=original.description,
            date_identified=original.date_identified,
            status=original.lifecycle_state,
            bic=original.bic,
            responsible=original.responsible,
            due_date=original.due_date,
            reference=original.reference,
            current_update=original.current_update,
            completion_date=original.completion_date,
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_baselines).values(
                sync_target_id=SYNC_TARGET,
                constraint_id=CONSTRAINT,
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                baseline_revision_id=REVISION,
                baseline_constraint_version=original.version,
                baseline_field_digests=baseline_row.field_digests(),
                baseline_record_digest=baseline_row.record_digest(),
                workbook_row_identity="row-converged",
                verified_at=T0,
                created_at=T0,
                updated_at=T0,
            )
        )
        converged_description = original.description if closed else "Converged description"
        converged_state = ConstraintLifecycleState.CLOSED if closed else original.lifecycle_state
        converged_completion = date(2026, 9, 8) if closed else original.completion_date
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(
                description=converged_description,
                lifecycle_state=converged_state.value,
                completion_date=converged_completion,
                version=2,
                updated_at=T0,
            )
        )
        history_count = connection.execute(
            select(func.count()).select_from(project_constraint_history)
        ).scalar_one()

    external = NormalizedExternalConstraintRow(
        external_row_key="row-converged",
        constraint_id=CONSTRAINT,
        constraint_code=original.constraint_code,
        category=original.category_id,
        description=converged_description,
        date_identified=original.date_identified,
        status=converged_state,
        bic=original.bic,
        responsible=original.responsible,
        due_date=original.due_date,
        reference=original.reference,
        current_update=original.current_update,
        completion_date=converged_completion,
    )
    audit = SqlAlchemyAuditSink(migrated_engine)
    service = ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(migrated_engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: T0,
        constraint_management_unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(
            migrated_engine
        ),
    )
    principal = Principal(principal_id=PRINCIPAL, kind=PrincipalKind.GATEWAY, authenticated=True)

    def preview_apply(sequence: int) -> tuple[Mapping[str, object], Mapping[str, object]]:
        with migrated_engine.begin() as connection:
            repository = SqlConstraintManagementRepository(connection)
            preview = repository.preview_sync(
                PRINCIPAL,
                PROJECT,
                external_identity=str(_sync_target_values()["external_identity"]),
                normalization_version="1",
                rows=(external,),
                provider_version=f"v{sequence}",
                workbook_digest=DIGEST,
                idempotency_key=f"preview_sync_converged{sequence:04d}",
                at=T0 + timedelta(seconds=sequence),
                lease_until=T0 + timedelta(minutes=5),
            )
            item = (
                connection.execute(
                    select(constraint_sync_run_items).where(
                        constraint_sync_run_items.c.sync_run_id == preview["run_id"]
                    )
                )
                .one()
                ._mapping
            )
            assert item["action"] == "no_op"
            assert item["field_names"] == []
        command = ApplyConstraintSync(
            project_id=PROJECT,
            target_id=str(preview["target_id"]),
            run_id=str(preview["run_id"]),
            lease_token=str(preview["lease_token"]),
            preview_digest=str(preview["preview_digest"]),
            idempotency_key=f"apply_sync_converged{sequence:04d}",
        )
        result = service.invoke(
            RequestMetadata(
                request_id=f"request-sync-converged-{sequence:04d}",
                capability=Capability.CONSTRAINT_SYNC_APPLY,
                purpose=Purpose.CONSTRAINT_SYNC_AUTHORING,
                principal_id=PRINCIPAL,
                requested_at=T0 + timedelta(seconds=sequence),
            ),
            command,
            principal=principal,
        )
        assert result.error is None and result.result is not None
        assert result.result["action_counts"]["no_op"] == 1  # type: ignore[index]
        return preview, result.result

    preview, applied = preview_apply(1)
    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        acknowledged = repository.acknowledge_sync(
            PRINCIPAL,
            PROJECT,
            str(preview["target_id"]),
            str(preview["run_id"]),
            lease_token=str(preview["lease_token"]),
            canonical_digest=(
                "f" * 64 if repair_after_failed_ack else str(applied["canonical_digest"])
            ),
            item_count=cast(int, applied["item_count"]),
            action_counts=cast(Mapping[str, int], applied["action_counts"]),
            provider_version="v1",
            workbook_digest=DIGEST,
            idempotency_key="ack_sync_converged0001",
            request_digest="a" * 64,
            at=T0 + timedelta(seconds=1),
        )
        assert acknowledged is not None
        assert acknowledged["state"] == (
            "verification_failed" if repair_after_failed_ack else "in_sync"
        )

    if repair_after_failed_ack:
        preview, applied = preview_apply(2)
        with migrated_engine.begin() as connection:
            acknowledged = SqlConstraintManagementRepository(connection).acknowledge_sync(
                PRINCIPAL,
                PROJECT,
                str(preview["target_id"]),
                str(preview["run_id"]),
                lease_token=str(preview["lease_token"]),
                canonical_digest=str(applied["canonical_digest"]),
                item_count=cast(int, applied["item_count"]),
                action_counts=cast(Mapping[str, int], applied["action_counts"]),
                provider_version="v2",
                workbook_digest=DIGEST,
                idempotency_key="ack_sync_converged0002",
                request_digest="b" * 64,
                at=T0 + timedelta(seconds=2),
            )
            assert acknowledged is not None and acknowledged["state"] == "in_sync"

    with migrated_engine.begin() as connection:
        stored = connection.execute(
            select(
                project_constraints.c.description,
                project_constraints.c.lifecycle_state,
                project_constraints.c.completion_date,
                project_constraints.c.version,
            ).where(project_constraints.c.constraint_id == CONSTRAINT)
        ).one()
        assert stored == (
            converged_description,
            converged_state.value,
            converged_completion,
            2,
        )
        assert (
            connection.execute(
                select(func.count()).select_from(project_constraint_history)
            ).scalar_one()
            == history_count
        )
        baseline = (
            connection.execute(
                select(constraint_sync_baselines).where(
                    constraint_sync_baselines.c.sync_target_id == SYNC_TARGET,
                    constraint_sync_baselines.c.constraint_id == CONSTRAINT,
                )
            )
            .one()
            ._mapping
        )
        assert baseline["baseline_constraint_version"] == 2
        assert baseline["baseline_record_digest"] == external.record_digest()


@pytest.mark.parametrize(
    ("resolution", "manual_patch", "external_only", "resolved_description", "version"),
    [
        (ConstraintSyncResolution.KEEP_CANONICAL, None, False, "Sample constraint", 1),
        (ConstraintSyncResolution.ACCEPT_EXTERNAL, None, False, "External constraint", 2),
        (
            ConstraintSyncResolution.MANUAL_PATCH,
            {"description": "Manual constraint"},
            False,
            "Manual constraint",
            2,
        ),
        (ConstraintSyncResolution.KEEP_CANONICAL, None, True, "Sample constraint", 1),
    ],
    ids=("keep-canonical", "accept-external", "manual-patch", "external-only-dismissal"),
)
def test_resolved_conflict_requires_fresh_verified_run_before_baseline_advances(
    migrated_engine: Engine,
    resolution: ConstraintSyncResolution,
    manual_patch: dict[str, object] | None,
    external_only: bool,
    resolved_description: str,
    version: int,
) -> None:
    def canonical_row(description: str) -> NormalizedExternalConstraintRow:
        return NormalizedExternalConstraintRow(
            external_row_key="row-1",
            constraint_id=CONSTRAINT,
            constraint_code="2.01",
            category=CATEGORY,
            description=description,
            date_identified=D0,
            status=ConstraintLifecycleState.IDENTIFIED,
            due_date=date(2026, 9, 30),
        )

    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(current_revision_id=REVISION)
        )
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        initial_rows = (
            (canonical_row("Sample constraint"), NormalizedExternalConstraintRow("row-new"))
            if external_only
            else (canonical_row("External constraint"),)
        )
        preview = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=initial_rows,
            provider_version="v1",
            workbook_digest=DIGEST,
            idempotency_key="preview_sync_0001",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        assert preview["state"] == "conflict"
        target_id = str(preview["target_id"])
        run_id = str(preview["run_id"])
        prepared = repository.prepare_sync_apply(
            PRINCIPAL,
            PROJECT,
            target_id,
            run_id,
            lease_token=str(preview["lease_token"]),
            preview_digest=str(preview["preview_digest"]),
            idempotency_key="apply_sync_0001",
            request_digest="a" * 64,
            at=T0,
        )
        assert prepared is not None
        applied = repository.complete_sync_apply(PRINCIPAL, run_id, applied={}, at=T0)
        assert applied["state"] == "partial"
        after_apply_replay = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=initial_rows,
            provider_version="v1",
            workbook_digest=DIGEST,
            idempotency_key="preview_sync_0001",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        assert after_apply_replay == {**preview, "replayed": True}
        conflict_id = connection.execute(
            select(constraint_sync_conflicts.c.sync_conflict_id).where(
                constraint_sync_conflicts.c.sync_run_id == run_id,
                constraint_sync_conflicts.c.state == "open",
            )
        ).scalar_one()
        service = ConstraintManagementService(
            unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(migrated_engine),
            clock=lambda: T0,
        )
        resolved = repository.resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            conflict_id,
            resolution=resolution,
            expected_version=1,
            manual_patch=manual_patch,
            idempotency_key="resolve_sync_0001",
            at=T0,
            mutation_service=service,
            active_uow=SimpleNamespace(constraints=repository),
            correlation_id=None,
        )
        assert resolved is not None and resolved["constraint_version"] == (
            None if external_only else version
        )
        replay = repository.resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            conflict_id,
            resolution=resolution,
            expected_version=1,
            manual_patch=manual_patch,
            idempotency_key="resolve_sync_0001",
            at=T0,
            mutation_service=service,
            active_uow=SimpleNamespace(constraints=repository),
            correlation_id=None,
        )
        assert replay == {**resolved, "replayed": True}
        after_resolution_replay = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=initial_rows,
            provider_version="v1",
            workbook_digest=DIGEST,
            idempotency_key="preview_sync_0001",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        assert after_resolution_replay == {**preview, "replayed": True}
        stored = repository.read_constraint(PRINCIPAL, CONSTRAINT)
        assert stored is not None
        assert stored.description == resolved_description and stored.version == version
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_baselines)
            ).scalar_one()
            == 0
        )
        old_run_state = connection.execute(
            select(constraint_sync_runs.c.sync_state).where(
                constraint_sync_runs.c.sync_run_id == run_id
            )
        ).scalar_one()
        active_run_id = connection.execute(
            select(constraint_sync_targets.c.active_run_id).where(
                constraint_sync_targets.c.sync_target_id == target_id
            )
        ).scalar_one()
        assert old_run_state == "partial"
        assert active_run_id is None
        with pytest.raises(ValueError, match="requires a fresh preview"):
            repository.acknowledge_sync(
                PRINCIPAL,
                PROJECT,
                target_id,
                run_id,
                lease_token=str(preview["lease_token"]),
                canonical_digest=str(applied["canonical_digest"]),
                item_count=cast(int, applied["item_count"]),
                action_counts=cast(Mapping[str, int], applied["action_counts"]),
                provider_version="v1",
                workbook_digest=DIGEST,
                idempotency_key="acknowledge_sync_0001",
                request_digest="b" * 64,
                at=T0,
            )

        refreshed = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=(canonical_row(resolved_description),),
            provider_version="v2",
            workbook_digest="1" * 64,
            idempotency_key="preview_sync_0002",
            at=T0 + timedelta(seconds=1),
            lease_until=T0 + timedelta(minutes=5),
        )
        assert refreshed["state"] == "in_sync"
        refreshed_run_id = str(refreshed["run_id"])
        assert (
            repository.prepare_sync_apply(
                PRINCIPAL,
                PROJECT,
                target_id,
                refreshed_run_id,
                lease_token=str(refreshed["lease_token"]),
                preview_digest=str(refreshed["preview_digest"]),
                idempotency_key="apply_sync_0002",
                request_digest="c" * 64,
                at=T0 + timedelta(seconds=1),
            )
            is not None
        )
        reapplied = repository.complete_sync_apply(
            PRINCIPAL, refreshed_run_id, applied={}, at=T0 + timedelta(seconds=1)
        )
        acknowledged = repository.acknowledge_sync(
            PRINCIPAL,
            PROJECT,
            target_id,
            refreshed_run_id,
            lease_token=str(refreshed["lease_token"]),
            canonical_digest=str(reapplied["canonical_digest"]),
            item_count=cast(int, reapplied["item_count"]),
            action_counts=cast(Mapping[str, int], reapplied["action_counts"]),
            provider_version="v2",
            workbook_digest="1" * 64,
            idempotency_key="acknowledge_sync_0002",
            request_digest="d" * 64,
            at=T0 + timedelta(seconds=1),
        )
        assert acknowledged is not None and acknowledged["state"] == "in_sync"
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_baselines)
            ).scalar_one()
            == 1
        )
        assert repository.read_constraint(PRINCIPAL, CONSTRAINT).version == version  # type: ignore[union-attr]


def test_a_run_keeps_its_lease_until_its_last_open_conflict_is_resolved(
    migrated_engine: Engine,
) -> None:
    def canonical_row(description: str) -> NormalizedExternalConstraintRow:
        return NormalizedExternalConstraintRow(
            external_row_key="row-1",
            constraint_id=CONSTRAINT,
            constraint_code="2.01",
            category=CATEGORY,
            description=description,
            date_identified=D0,
            status=ConstraintLifecycleState.IDENTIFIED,
            due_date=date(2026, 9, 30),
        )

    class NoMutation:
        def update(self, **_values: object) -> object:
            raise AssertionError("KEEP_CANONICAL must not mutate")

    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        preview = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=(
                canonical_row("External constraint"),
                NormalizedExternalConstraintRow(external_row_key="row-new"),
            ),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_0001",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        run_id = str(preview["run_id"])
        target_id = str(preview["target_id"])
        assert (
            repository.prepare_sync_apply(
                PRINCIPAL,
                PROJECT,
                target_id,
                run_id,
                lease_token=str(preview["lease_token"]),
                preview_digest=str(preview["preview_digest"]),
                idempotency_key="apply_sync_0001",
                request_digest="a" * 64,
                at=T0,
            )
            is not None
        )
        repository.complete_sync_apply(PRINCIPAL, run_id, applied={}, at=T0)
        conflicts = {
            row.constraint_id: row.sync_conflict_id
            for row in connection.execute(
                select(
                    constraint_sync_conflicts.c.constraint_id,
                    constraint_sync_conflicts.c.sync_conflict_id,
                ).where(constraint_sync_conflicts.c.sync_run_id == run_id)
            )
        }
        first = repository.resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            conflicts[CONSTRAINT],
            resolution=ConstraintSyncResolution.KEEP_CANONICAL,
            expected_version=1,
            manual_patch=None,
            idempotency_key="resolve_sync_0001",
            at=T0,
            mutation_service=NoMutation(),
            active_uow=object(),
            correlation_id=None,
        )
        assert first is not None
        interim = repository.read_sync_state(PRINCIPAL, PROJECT, target_id)
        assert interim is not None
        assert interim["state"] == "partial" and interim["active_run_id"] == run_id
        run_count = connection.execute(
            select(func.count()).select_from(constraint_sync_runs)
        ).scalar_one()
        with pytest.raises(ValueError, match="already holds the lease"):
            repository.preview_sync(
                PRINCIPAL,
                PROJECT,
                external_identity="synthetic-workbook-identity-0001",
                normalization_version="1",
                rows=(canonical_row("Sample constraint"),),
                provider_version=None,
                workbook_digest=None,
                idempotency_key="preview_sync_0002",
                at=T0 + timedelta(seconds=1),
                lease_until=T0 + timedelta(minutes=5),
            )
        assert (
            connection.execute(select(func.count()).select_from(constraint_sync_runs)).scalar_one()
            == run_count
        )
        final = repository.resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            conflicts[None],
            resolution=ConstraintSyncResolution.KEEP_CANONICAL,
            expected_version=1,
            manual_patch=None,
            idempotency_key="resolve_sync_0002",
            at=T0 + timedelta(seconds=1),
            mutation_service=NoMutation(),
            active_uow=object(),
            correlation_id=None,
        )
        assert final is not None
        released = repository.read_sync_state(PRINCIPAL, PROJECT, target_id)
        assert released is not None
        assert released["state"] == "partial" and released["active_run_id"] is None
        refreshed = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=(canonical_row("Sample constraint"),),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_0003",
            at=T0 + timedelta(seconds=2),
            lease_until=T0 + timedelta(minutes=5),
        )
        assert refreshed["state"] == "in_sync"


def test_a_superseded_run_cannot_resolve_its_stale_conflict(
    migrated_engine: Engine,
) -> None:
    def canonical_row(
        description: str,
        status: ConstraintLifecycleState = ConstraintLifecycleState.IDENTIFIED,
    ) -> NormalizedExternalConstraintRow:
        return NormalizedExternalConstraintRow(
            external_row_key="row-1",
            constraint_id=CONSTRAINT,
            constraint_code="2.01",
            category=CATEGORY,
            description=description,
            date_identified=D0,
            status=status,
            due_date=date(2026, 9, 30),
        )

    class NoMutation:
        def update(self, **_values: object) -> object:
            raise AssertionError("a stale conflict must not mutate")

    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        stale = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=(canonical_row("External constraint"),),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_0001",
            at=T0,
            lease_until=T0 + timedelta(seconds=1),
        )
        stale_run_id = str(stale["run_id"])
        conflict_id = connection.execute(
            select(constraint_sync_conflicts.c.sync_conflict_id).where(
                constraint_sync_conflicts.c.sync_run_id == stale_run_id
            )
        ).scalar_one()
        newer = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-identity-0001",
            normalization_version="1",
            rows=(canonical_row("Sample constraint", ConstraintLifecycleState.VOID),),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_0002",
            at=T0 + timedelta(seconds=2),
            lease_until=T0 + timedelta(minutes=5),
        )
        assert newer["state"] == "conflict"
        before_state = repository.read_sync_state(PRINCIPAL, PROJECT, str(newer["target_id"]))
        before_record = repository.read_constraint(PRINCIPAL, CONSTRAINT)
        with pytest.raises(ValueError, match="conflict is no longer open"):
            repository.resolve_sync_conflict(
                PRINCIPAL,
                PROJECT,
                conflict_id,
                resolution=ConstraintSyncResolution.KEEP_CANONICAL,
                expected_version=1,
                manual_patch=None,
                idempotency_key="resolve_sync_0001",
                at=T0 + timedelta(seconds=2),
                mutation_service=NoMutation(),
                active_uow=object(),
                correlation_id=None,
            )
        assert (
            repository.read_sync_state(PRINCIPAL, PROJECT, str(newer["target_id"])) == before_state
        )
        assert repository.read_constraint(PRINCIPAL, CONSTRAINT) == before_record
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_resolution_history)
            ).scalar_one()
            == 0
        )
        assert repository.read_constraint(PRINCIPAL, CONSTRAINT).version == 1  # type: ignore[union-attr]
        conflicts = connection.execute(
            select(
                constraint_sync_conflicts.c.sync_conflict_id,
                constraint_sync_conflicts.c.conflict_kind,
                constraint_sync_conflicts.c.state,
            ).order_by(constraint_sync_conflicts.c.created_at)
        ).all()
        assert conflicts[0] == (conflict_id, "both_changed", "superseded")
        assert conflicts[1][1:] == ("lifecycle", "open")
        visible = tuple(
            item
            for item in repository.list_sync_conflicts(
                PRINCIPAL, PROJECT, str(newer["target_id"]), limit=100, cursor=None
            )
            if item["state"] == "open"
        )
        assert len(visible) == 1
        assert visible[0]["sync_conflict_id"] == conflicts[1][0]


def test_expired_conflict_is_superseded_before_the_same_disagreement_is_replanned(
    migrated_engine: Engine,
) -> None:
    row = NormalizedExternalConstraintRow(
        external_row_key="row-1",
        constraint_id=CONSTRAINT,
        constraint_code="2.01",
        category=CATEGORY,
        description="External constraint",
        date_identified=D0,
        status=ConstraintLifecycleState.IDENTIFIED,
        due_date=date(2026, 9, 30),
    )
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        first = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-expired-conflict",
            normalization_version="1",
            rows=(row,),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_expired0001",
            at=T0,
            lease_until=T0 + timedelta(seconds=1),
        )
        replay = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-expired-conflict",
            normalization_version="1",
            rows=(row,),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_expired0001",
            at=T0,
            lease_until=T0 + timedelta(seconds=1),
        )
        assert replay == {**first, "replayed": True}
        replacement = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-expired-conflict",
            normalization_version="1",
            rows=(row,),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_expired0002",
            at=T0 + timedelta(seconds=2),
            lease_until=T0 + timedelta(minutes=5),
        )
        assert replacement["state"] == "conflict"
        target = connection.execute(
            select(
                constraint_sync_targets.c.active_run_id,
                constraint_sync_targets.c.last_run_id,
            )
        ).one()
        assert target == (replacement["run_id"], replacement["run_id"])
        runs = connection.execute(
            select(
                constraint_sync_runs.c.sync_run_id,
                constraint_sync_runs.c.state,
                constraint_sync_runs.c.safe_failure_reason,
            ).order_by(constraint_sync_runs.c.created_at)
        ).all()
        assert runs[0] == (first["run_id"], "failed", "lease_expired")
        assert runs[1] == (replacement["run_id"], "previewed", None)
        conflicts = connection.execute(
            select(
                constraint_sync_conflicts.c.sync_run_id,
                constraint_sync_conflicts.c.conflict_kind,
                constraint_sync_conflicts.c.state,
                constraint_sync_conflicts.c.resolution_history_id,
            ).order_by(constraint_sync_conflicts.c.created_at)
        ).all()
        assert conflicts == [
            (first["run_id"], "both_changed", "superseded", None),
            (replacement["run_id"], "both_changed", "open", None),
        ]
        superseded_replay = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-expired-conflict",
            normalization_version="1",
            rows=(row,),
            provider_version=None,
            workbook_digest=None,
            idempotency_key="preview_sync_expired0001",
            at=T0 + timedelta(seconds=2),
            lease_until=T0 + timedelta(minutes=5),
        )
        assert superseded_replay == {**first, "replayed": True}
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_resolution_history)
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_baselines)
            ).scalar_one()
            == 0
        )


def test_apply_replay_preserves_its_verification_response_after_acknowledgement(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    state="previewed",
                    sync_state="in_sync",
                    preview_digest=DIGEST,
                    apply_idempotency_key="apply_sync_0001",
                    apply_request_digest="e" * 64,
                )
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        connection.execute(
            update(constraint_sync_targets)
            .where(constraint_sync_targets.c.sync_target_id == SYNC_TARGET)
            .values(active_run_id=SYNC_RUN, active_run_lease_until=T0)
        )
        initial = repository.complete_sync_apply(PRINCIPAL, SYNC_RUN, applied={}, at=T0)
        assert initial["state"] == "verification_pending"
        acknowledged = repository.acknowledge_sync(
            PRINCIPAL,
            PROJECT,
            SYNC_TARGET,
            SYNC_RUN,
            lease_token=DIGEST,
            canonical_digest=str(initial["canonical_digest"]),
            item_count=int(initial["item_count"]),
            action_counts=initial["action_counts"],
            provider_version=None,
            workbook_digest=None,
            idempotency_key="acknowledge_sync_0001",
            request_digest="f" * 64,
            at=T0,
        )
        assert acknowledged is not None and acknowledged["state"] == "in_sync"
        assert acknowledged["item_count"] == initial["item_count"]
        assert acknowledged["action_counts"] == initial["action_counts"]
        acknowledged_replay = repository.acknowledge_sync(
            PRINCIPAL,
            PROJECT,
            SYNC_TARGET,
            SYNC_RUN,
            lease_token=DIGEST,
            canonical_digest=str(initial["canonical_digest"]),
            item_count=int(initial["item_count"]),
            action_counts=initial["action_counts"],
            provider_version=None,
            workbook_digest=None,
            idempotency_key="acknowledge_sync_0001",
            request_digest="f" * 64,
            at=T0,
        )
        assert acknowledged_replay == {**acknowledged, "replayed": True}
        replay = repository.prepare_sync_apply(
            PRINCIPAL,
            PROJECT,
            SYNC_TARGET,
            SYNC_RUN,
            lease_token=DIGEST,
            preview_digest=DIGEST,
            idempotency_key="apply_sync_0001",
            request_digest="e" * 64,
            at=T0,
        )
        assert replay is not None
        assert replay["apply_result"] == {**initial, "replayed": True}


def test_preview_replay_preserves_its_original_state_after_acknowledgement(
    migrated_engine: Engine,
) -> None:
    row = NormalizedExternalConstraintRow(
        external_row_key="row-1",
        constraint_id=CONSTRAINT,
        constraint_code="2.01",
        category=CATEGORY,
        description="Sample constraint",
        date_identified=D0,
        status=ConstraintLifecycleState.IDENTIFIED,
        due_date=date(2026, 9, 30),
    )
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(current_revision_id=REVISION)
        )
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        preview = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-preview-replay",
            normalization_version="1",
            rows=(row,),
            provider_version="v1",
            workbook_digest=DIGEST,
            idempotency_key="preview_sync_replay0001",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        assert preview["state"] == "in_sync"
        prepared = repository.prepare_sync_apply(
            PRINCIPAL,
            PROJECT,
            str(preview["target_id"]),
            str(preview["run_id"]),
            lease_token=str(preview["lease_token"]),
            preview_digest=str(preview["preview_digest"]),
            idempotency_key="apply_sync_replay0001",
            request_digest="e" * 64,
            at=T0,
        )
        assert prepared is not None
        applied = repository.complete_sync_apply(
            PRINCIPAL, str(preview["run_id"]), applied={}, at=T0
        )
        acknowledged = repository.acknowledge_sync(
            PRINCIPAL,
            PROJECT,
            str(preview["target_id"]),
            str(preview["run_id"]),
            lease_token=str(preview["lease_token"]),
            canonical_digest=str(applied["canonical_digest"]),
            item_count=cast(int, applied["item_count"]),
            action_counts=cast(Mapping[str, int], applied["action_counts"]),
            provider_version="v1",
            workbook_digest=DIGEST,
            idempotency_key="acknowledge_sync_replay0001",
            request_digest="f" * 64,
            at=T0,
        )
        assert acknowledged is not None and acknowledged["state"] == "in_sync"
        replay = repository.preview_sync(
            PRINCIPAL,
            PROJECT,
            external_identity="synthetic-workbook-preview-replay",
            normalization_version="1",
            rows=(row,),
            provider_version="v1",
            workbook_digest=DIGEST,
            idempotency_key="preview_sync_replay0001",
            at=T0,
            lease_until=T0 + timedelta(minutes=5),
        )
        assert replay == {**preview, "replayed": True}


def test_verification_digest_failure_is_committed_as_a_safe_failure(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    state="applied",
                    sync_state="verification_pending",
                    finished_at=T0,
                    outcome="applied",
                )
            )
        )
        connection.execute(
            update(constraint_sync_targets)
            .where(constraint_sync_targets.c.sync_target_id == SYNC_TARGET)
            .values(active_run_id=SYNC_RUN, active_run_lease_until=T0)
        )
        result = SqlConstraintManagementRepository(connection).acknowledge_sync(
            PRINCIPAL,
            PROJECT,
            SYNC_TARGET,
            SYNC_RUN,
            lease_token=DIGEST,
            canonical_digest="f" * 64,
            item_count=0,
            action_counts={action.value: 0 for action in ConstraintSyncAction},
            provider_version=None,
            workbook_digest=None,
            idempotency_key="acknowledge_sync_0001",
            request_digest="e" * 64,
            at=T0,
        )
        assert result is not None and result["verification_failed"] is True
    with migrated_engine.begin() as connection:
        run = (
            connection.execute(
                select(constraint_sync_runs).where(constraint_sync_runs.c.sync_run_id == SYNC_RUN)
            )
            .one()
            ._mapping
        )
        target = (
            connection.execute(
                select(constraint_sync_targets).where(
                    constraint_sync_targets.c.sync_target_id == SYNC_TARGET
                )
            )
            .one()
            ._mapping
        )
        assert (run["state"], run["sync_state"], run["failure_kind"]) == (
            "failed",
            "verification_failed",
            "verification_failed",
        )
        assert target["active_run_id"] is None


def test_verification_cardinality_mismatch_advances_no_baseline(
    migrated_engine: Engine,
) -> None:
    digest = hashlib.sha256(b"[]").hexdigest()
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    state="applied",
                    sync_state="verification_pending",
                    apply_canonical_digest=digest,
                    apply_sync_state="verification_pending",
                    finished_at=T0,
                    outcome="applied",
                )
            )
        )
        connection.execute(
            update(constraint_sync_targets)
            .where(constraint_sync_targets.c.sync_target_id == SYNC_TARGET)
            .values(active_run_id=SYNC_RUN, active_run_lease_until=T0)
        )
        counts = {action.value: 0 for action in ConstraintSyncAction}
        counts[ConstraintSyncAction.NO_OP.value] = 1
        result = SqlConstraintManagementRepository(connection).acknowledge_sync(
            PRINCIPAL,
            PROJECT,
            SYNC_TARGET,
            SYNC_RUN,
            lease_token=DIGEST,
            canonical_digest=digest,
            item_count=1,
            action_counts=counts,
            provider_version="v1",
            workbook_digest=None,
            idempotency_key="acknowledge_sync_0001",
            request_digest="e" * 64,
            at=T0,
        )
        assert result is not None and result["verification_failed"] is True
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_baselines)
            ).scalar_one()
            == 0
        )
        target = connection.execute(select(constraint_sync_targets)).one()._mapping
        assert target["last_verified_sync_run_id"] is None
        assert target["active_run_lease_until"] is None


@pytest.mark.parametrize("action", ["no_op", "export_canonical"])
@pytest.mark.parametrize("run_state", ["applied", "acknowledged", "failed"])
def test_terminal_apply_binding_replays_without_reviving_the_run(
    migrated_engine: Engine, action: str, run_state: str
) -> None:
    canonical_digest = hashlib.sha256(b"[]").hexdigest()
    terminal_sync_state = {
        "applied": "verification_pending",
        "acknowledged": "in_sync",
        "failed": "verification_failed",
    }[run_state]
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    state=run_state,
                    sync_state=terminal_sync_state,
                    preview_digest=DIGEST,
                    apply_idempotency_key="apply_sync_0001",
                    apply_request_digest="e" * 64,
                    apply_canonical_digest=canonical_digest,
                    apply_sync_state="verification_pending",
                    finished_at=T0,
                    outcome="failed" if run_state == "failed" else "applied",
                    failure_kind="verification_failed" if run_state == "failed" else None,
                    safe_failure_reason=("verification_failed" if run_state == "failed" else None),
                )
            )
        )
        connection.execute(
            insert(constraint_sync_run_items).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                sync_target_id=SYNC_TARGET,
                sync_run_id=SYNC_RUN,
                external_row_key="row-1",
                constraint_id=CONSTRAINT,
                action=action,
                expected_constraint_version=1,
                field_names=[],
                response_summary={"action": action},
                created_at=T0,
                updated_at=T0,
            )
        )
        before_constraint = connection.execute(
            select(project_constraints.c.version, project_constraints.c.description).where(
                project_constraints.c.constraint_id == CONSTRAINT
            )
        ).one()
        repository = SqlConstraintManagementRepository(connection)
        replay = repository.prepare_sync_apply(
            PRINCIPAL,
            PROJECT,
            SYNC_TARGET,
            SYNC_RUN,
            lease_token=DIGEST,
            preview_digest=DIGEST,
            idempotency_key="apply_sync_0001",
            request_digest="e" * 64,
            at=T0,
        )
        assert replay is not None and replay["replayed"] is True
        assert cast(Mapping[str, object], replay["apply_result"])["replayed"] is True
        with pytest.raises(ValueError, match="already terminal"):
            repository.complete_sync_apply(PRINCIPAL, SYNC_RUN, applied={}, at=T0)
        stored_run = connection.execute(
            select(
                constraint_sync_runs.c.state,
                constraint_sync_runs.c.sync_state,
                constraint_sync_runs.c.failure_kind,
            ).where(constraint_sync_runs.c.sync_run_id == SYNC_RUN)
        ).one()
        assert stored_run == (
            run_state,
            terminal_sync_state,
            "verification_failed" if run_state == "failed" else None,
        )
        assert (
            connection.execute(
                select(project_constraints.c.version, project_constraints.c.description).where(
                    project_constraints.c.constraint_id == CONSTRAINT
                )
            ).one()
            == before_constraint
        )
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_baselines)
            ).scalar_one()
            == 0
        )


def test_failed_apply_binding_without_completed_material_is_irrecoverable(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    state="failed",
                    sync_state="verification_failed",
                    preview_digest=DIGEST,
                    apply_idempotency_key="apply_sync_0001",
                    apply_request_digest="e" * 64,
                    finished_at=T0,
                    outcome="failed",
                    failure_kind="verification_failed",
                    safe_failure_reason="verification_failed",
                )
            )
        )
        with pytest.raises(ValueError, match="failed synchronization apply"):
            SqlConstraintManagementRepository(connection).prepare_sync_apply(
                PRINCIPAL,
                PROJECT,
                SYNC_TARGET,
                SYNC_RUN,
                lease_token=DIGEST,
                preview_digest=DIGEST,
                idempotency_key="apply_sync_0001",
                request_digest="e" * 64,
                at=T0,
            )
        assert connection.execute(
            select(
                constraint_sync_runs.c.state,
                constraint_sync_runs.c.sync_state,
                constraint_sync_runs.c.failure_kind,
            )
        ).one() == ("failed", "verification_failed", "verification_failed")
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_baselines)
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    ("field_names", "candidate", "expected_values", "expected_clears"),
    [
        (
            ["description"],
            {
                "external_row_key": "row-1",
                "description": "External description",
                "reference": "unselected reference",
                "current_update": "unselected update",
            },
            {"description": "External description"},
            frozenset(),
        ),
        (
            ["description", "date_identified", "due_date", "reference", "current_update"],
            {
                "external_row_key": "row-1",
                "description": None,
                "date_identified": None,
                "due_date": None,
                "reference": None,
                "current_update": None,
            },
            {},
            frozenset(
                {"description", "date_identified", "due_date", "reference", "current_update"}
            ),
        ),
    ],
)
def test_accept_external_updates_only_selected_fields_and_carries_null_clears(
    migrated_engine: Engine,
    field_names: list[str],
    candidate: dict[str, object],
    expected_values: dict[str, object],
    expected_clears: frozenset[str],
) -> None:
    class MutationService:
        called: dict[str, object]

        def update(self, **values: object) -> object:
            self.called = values
            return SimpleNamespace(
                record=SimpleNamespace(version=2),
                receipt=SimpleNamespace(history_id=HISTORY),
            )

    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(
            insert(constraint_sync_conflicts).values(
                **_sync_conflict_values(
                    field_names=field_names,
                    external_candidate=candidate,
                )
            )
        )
        _activate_sync_run(connection)
        service = MutationService()
        result = SqlConstraintManagementRepository(connection).resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            "csyc_wpzeroaaaa0001aaaa",
            resolution=ConstraintSyncResolution.ACCEPT_EXTERNAL,
            expected_version=1,
            manual_patch=None,
            idempotency_key="resolve_sync_0001",
            at=T0,
            mutation_service=service,
            active_uow=object(),
            correlation_id=None,
        )
        assert result is not None
        assert service.called["values"] == expected_values
        assert service.called["clear_fields"] == expected_clears
        replay = SqlConstraintManagementRepository(connection).resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            "csyc_wpzeroaaaa0001aaaa",
            resolution=ConstraintSyncResolution.ACCEPT_EXTERNAL,
            expected_version=1,
            manual_patch=None,
            idempotency_key="resolve_sync_0001",
            at=T0,
            mutation_service=service,
            active_uow=object(),
            correlation_id=None,
        )
        assert replay == {**result, "replayed": True}


@pytest.mark.parametrize(
    ("field_name", "candidate"),
    [
        ("constraint_code", "OTHER.01"),
        ("category", "ccat_wpzerobbbb0002bbbb"),
        ("status", "closed"),
        ("completion_date", "2026-09-08"),
    ],
)
def test_accept_external_keeps_named_operation_conflicts_open(
    migrated_engine: Engine, field_name: str, candidate: object
) -> None:
    class NoMutation:
        def update(self, **_values: object) -> object:
            raise AssertionError("an unsupported external resolution must not mutate")

    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(
            insert(constraint_sync_conflicts).values(
                **_sync_conflict_values(
                    conflict_kind="lifecycle"
                    if field_name in {"status", "completion_date"}
                    else "identity",
                    field_names=[field_name],
                    external_candidate={"external_row_key": "row-1", field_name: candidate},
                )
            )
        )
        _activate_sync_run(connection)
        with pytest.raises(ValueError, match="named canonical operation"):
            SqlConstraintManagementRepository(connection).resolve_sync_conflict(
                PRINCIPAL,
                PROJECT,
                "csyc_wpzeroaaaa0001aaaa",
                resolution=ConstraintSyncResolution.ACCEPT_EXTERNAL,
                expected_version=1,
                manual_patch=None,
                idempotency_key="resolve_sync_0001",
                at=T0,
                mutation_service=NoMutation(),
                active_uow=object(),
                correlation_id=None,
            )
        state = connection.execute(select(constraint_sync_conflicts.c.state)).scalar_one()
        receipts = connection.execute(
            select(func.count()).select_from(constraint_sync_resolution_history)
        ).scalar_one()
        assert state == "open"
        assert receipts == 0


@pytest.mark.parametrize(
    ("terminal_state", "terminal_values", "target_state"),
    [
        (
            ConstraintLifecycleState.CLOSED,
            {"completion_date": D0, "closure_commentary": "Synthetic closure"},
            ConstraintLifecycleState.IN_PROGRESS,
        ),
        (
            ConstraintLifecycleState.VOID,
            {"voided_date": D0, "void_reason": "Synthetic void"},
            ConstraintLifecycleState.PENDING,
        ),
    ],
    ids=("closed-to-in-progress", "void-to-pending"),
)
def test_reopen_resolution_uses_canonical_reopen_and_replays_without_duplicate_history(
    migrated_engine: Engine,
    terminal_state: ConstraintLifecycleState,
    terminal_values: dict[str, object],
    target_state: ConstraintLifecycleState,
) -> None:
    candidate = {
        "external_row_key": "row-1",
        "constraint_id": CONSTRAINT,
        "constraint_code": "2.01",
        "category": CATEGORY,
        "description": "Sample constraint",
        "date_identified": D0.isoformat(),
        "status": target_state.value,
        "bic": [],
        "responsible": [],
        "due_date": date(2026, 9, 30).isoformat(),
        "reference": None,
        "current_update": None,
        "completion_date": None,
    }
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(lifecycle_state=terminal_state.value, **terminal_values)
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(
            insert(constraint_sync_conflicts).values(
                **_sync_conflict_values(
                    conflict_kind="lifecycle",
                    field_names=["status"],
                    external_candidate=candidate,
                )
            )
        )
        _activate_sync_run(connection)
        repository = SqlConstraintManagementRepository(connection)
        service = ConstraintManagementService(
            unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(migrated_engine),
            clock=lambda: T0,
        )
        result = repository.resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            "csyc_wpzeroaaaa0001aaaa",
            resolution=ConstraintSyncResolution.REOPEN,
            expected_version=1,
            manual_patch=None,
            idempotency_key="resolve_sync_reopen0001",
            at=T0,
            mutation_service=service,
            active_uow=SimpleNamespace(constraints=repository),
            correlation_id="corr_syncreopen0001",
        )
        assert result is not None
        assert result["resolution"] == "reopen"
        assert result["constraint_version"] == 2
        stored = repository.read_constraint(PRINCIPAL, CONSTRAINT)
        assert stored is not None
        assert stored.lifecycle_state is target_state
        assert (
            stored.completion_date,
            stored.closure_commentary,
            stored.voided_date,
            stored.void_reason,
        ) == (None, None, None, None)
        histories = connection.execute(
            select(
                project_constraint_history.c.history_id,
                project_constraint_history.c.operation,
                project_constraint_history.c.actor,
            ).order_by(
                project_constraint_history.c.recorded_at, project_constraint_history.c.history_id
            )
        ).all()
        assert len(histories) == 2
        reopen_history = next(row for row in histories if row.operation == "reopen")
        assert reopen_history.actor == "system"
        receipt = connection.execute(select(constraint_sync_resolution_history)).one()._mapping
        assert receipt["resolution"] == "reopen"
        assert receipt["constraint_history_id"] == reopen_history.history_id
        assert (
            connection.execute(select(constraint_sync_conflicts.c.state)).scalar_one() == "resolved"
        )

        replay = repository.resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            "csyc_wpzeroaaaa0001aaaa",
            resolution=ConstraintSyncResolution.REOPEN,
            expected_version=1,
            manual_patch=None,
            idempotency_key="resolve_sync_reopen0001",
            at=T0,
            mutation_service=service,
            active_uow=SimpleNamespace(constraints=repository),
            correlation_id="corr_syncreopen0001",
        )
        assert replay == {**result, "replayed": True}
        assert (
            connection.execute(
                select(func.count()).select_from(project_constraint_history)
            ).scalar_one()
            == 2
        )
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_resolution_history)
            ).scalar_one()
            == 1
        )


def test_reopen_resolution_stale_version_has_zero_effects(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(
                lifecycle_state="closed",
                completion_date=D0,
                closure_commentary="Synthetic closure",
            )
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(
            insert(constraint_sync_conflicts).values(
                **_sync_conflict_values(
                    conflict_kind="lifecycle",
                    field_names=["status"],
                    external_candidate={
                        "external_row_key": "row-1",
                        "status": "identified",
                    },
                )
            )
        )
        _activate_sync_run(connection)
        repository = SqlConstraintManagementRepository(connection)
        service = ConstraintManagementService(
            unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(migrated_engine),
            clock=lambda: T0,
        )
        with pytest.raises(ValueError, match="version is stale"):
            repository.resolve_sync_conflict(
                PRINCIPAL,
                PROJECT,
                "csyc_wpzeroaaaa0001aaaa",
                resolution=ConstraintSyncResolution.REOPEN,
                expected_version=2,
                manual_patch=None,
                idempotency_key="resolve_sync_reopen0002",
                at=T0,
                mutation_service=service,
                active_uow=SimpleNamespace(constraints=repository),
                correlation_id=None,
            )
        stored = repository.read_constraint(PRINCIPAL, CONSTRAINT)
        assert stored is not None
        assert stored.lifecycle_state is ConstraintLifecycleState.CLOSED
        assert stored.version == 1
        assert connection.execute(select(constraint_sync_conflicts.c.state)).scalar_one() == "open"
        assert (
            connection.execute(
                select(func.count()).select_from(project_constraint_history)
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_resolution_history)
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    ("resolution", "target_state", "message"),
    [
        (ConstraintSyncResolution.ACCEPT_EXTERNAL, "identified", "named canonical operation"),
        (ConstraintSyncResolution.REOPEN, "draft", "active target state"),
        (ConstraintSyncResolution.REOPEN, "closed", "active target state"),
    ],
)
def test_wrong_or_unsupported_terminal_resolution_keeps_the_conflict_open(
    migrated_engine: Engine,
    resolution: ConstraintSyncResolution,
    target_state: str,
    message: str,
) -> None:
    class NoMutation:
        def update(self, **_values: object) -> object:
            raise AssertionError("a refused resolution must not update")

        def reopen(self, **_values: object) -> object:
            raise AssertionError("a refused resolution must not reopen")

    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            update(project_constraints)
            .where(project_constraints.c.constraint_id == CONSTRAINT)
            .values(lifecycle_state="closed", completion_date=D0)
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(
            insert(constraint_sync_conflicts).values(
                **_sync_conflict_values(
                    conflict_kind="lifecycle",
                    field_names=["status"],
                    external_candidate={
                        "external_row_key": "row-1",
                        "status": target_state,
                    },
                )
            )
        )
        _activate_sync_run(connection)
        with pytest.raises(ValueError, match=message):
            SqlConstraintManagementRepository(connection).resolve_sync_conflict(
                PRINCIPAL,
                PROJECT,
                "csyc_wpzeroaaaa0001aaaa",
                resolution=resolution,
                expected_version=1,
                manual_patch=None,
                idempotency_key="resolve_sync_reopen0003",
                at=T0,
                mutation_service=NoMutation(),
                active_uow=object(),
                correlation_id=None,
            )
        assert connection.execute(select(constraint_sync_conflicts.c.state)).scalar_one() == "open"
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_resolution_history)
            ).scalar_one()
            == 0
        )


def test_manual_patch_turns_nulls_into_canonical_draft_clears(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _seed_project(connection)
        connection.execute(insert(constraint_categories).values(**_category_values()))
        connection.execute(
            insert(project_constraints).values(
                **_constraint_values(
                    constraint_code=None,
                    lifecycle_state="draft",
                    published_at=None,
                )
            )
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(
            insert(constraint_sync_conflicts).values(
                **_sync_conflict_values(baseline_revision_id=None)
            )
        )
        _activate_sync_run(connection)
        repository = SqlConstraintManagementRepository(connection)
        service = ConstraintManagementService(
            unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(migrated_engine),
            clock=lambda: T0,
        )
        result = repository.resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            "csyc_wpzeroaaaa0001aaaa",
            resolution=ConstraintSyncResolution.MANUAL_PATCH,
            expected_version=1,
            manual_patch={
                "description": None,
                "date_identified": None,
                "due_date": None,
                "reference": None,
                "current_update": None,
            },
            idempotency_key="resolve_sync_0001",
            at=T0,
            mutation_service=service,
            active_uow=SimpleNamespace(constraints=repository),
            correlation_id=None,
        )
        assert result is not None and result["constraint_version"] == 2
        stored = repository.read_constraint(PRINCIPAL, CONSTRAINT)
        assert stored is not None
        assert (
            stored.description,
            stored.date_identified,
            stored.due_date,
            stored.reference,
            stored.current_update,
        ) == (None, None, None, None, None)


def test_manual_patch_cannot_clear_published_required_fields(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(insert(constraint_sync_conflicts).values(**_sync_conflict_values()))
        _activate_sync_run(connection)
        repository = SqlConstraintManagementRepository(connection)
        service = ConstraintManagementService(
            unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(migrated_engine),
            clock=lambda: T0,
        )
        with pytest.raises(ConstraintOperationError, match="published constraint keeps"):
            repository.resolve_sync_conflict(
                PRINCIPAL,
                PROJECT,
                "csyc_wpzeroaaaa0001aaaa",
                resolution=ConstraintSyncResolution.MANUAL_PATCH,
                expected_version=1,
                manual_patch={"description": None},
                idempotency_key="resolve_sync_0001",
                at=T0,
                mutation_service=service,
                active_uow=SimpleNamespace(constraints=repository),
                correlation_id=None,
            )
        assert connection.execute(select(constraint_sync_conflicts.c.state)).scalar_one() == "open"
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_resolution_history)
            ).scalar_one()
            == 0
        )
        stored = repository.read_constraint(PRINCIPAL, CONSTRAINT)
        assert stored is not None and stored.version == 1


def test_invalid_manual_patch_bounds_have_zero_database_effects(migrated_engine: Engine) -> None:
    invalid = (
        {"description": "x" * 4097},
        {"current_update": "x" * 4097},
        {"reference": "x" * 1025},
        {"bic": tuple(PartyRef(PartyKind.PRINCIPAL) for _ in range(33))},
        {"bic": [PartyRef(PartyKind.PRINCIPAL)]},
        {"responsible": (object(),)},
        {"bic": (PartyRef(PartyKind.UNRESOLVED, label="x" * 513),)},
    )
    with migrated_engine.begin() as connection:
        _base(connection)
        before = connection.execute(
            select(project_constraints.c.version, project_constraints.c.description).where(
                project_constraints.c.constraint_id == CONSTRAINT
            )
        ).one()
        for patch in invalid:
            with pytest.raises(InvalidRequestError):
                ResolveConstraintSyncConflict(
                    project_id=PROJECT,
                    conflict_id="csyc_wpzeroaaaa0001aaaa",
                    resolution=ConstraintSyncResolution.MANUAL_PATCH,
                    expected_version=1,
                    idempotency_key="resolve_sync_bounds0001",
                    manual_patch=patch,
                )
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_targets)
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(select(func.count()).select_from(constraint_sync_runs)).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_conflicts)
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_resolution_history)
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                select(project_constraints.c.version, project_constraints.c.description).where(
                    project_constraints.c.constraint_id == CONSTRAINT
                )
            ).one()
            == before
        )


@pytest.mark.parametrize(
    "manual_patch",
    [
        {"project_id": "prj_wpzerobbbb0002bbbb"},
        {"project_id": None},
        {"category_id": "ccat_wpzerobbbb0002bbbb"},
        {"category_id": "ccat_wpzerocccc0003cccc"},
    ],
)
def test_manual_patch_cannot_escape_the_conflicts_project(
    migrated_engine: Engine, manual_patch: dict[str, object]
) -> None:
    class NoMutation:
        def update(self, **_values: object) -> object:
            raise AssertionError("an out-of-scope manual patch must not mutate")

    foreign_principal = "prn_wpzerobbbb0002bbbb0002"
    foreign_project = "prj_wpzerobbbb0002bbbb"
    with migrated_engine.begin() as connection:
        _base(connection)
        _seed_project(connection, principal=foreign_principal, project=foreign_project)
        connection.execute(
            insert(constraint_categories).values(
                **_category_values(
                    category_id="ccat_wpzerobbbb0002bbbb",
                    principal_id=foreign_principal,
                    project_id=foreign_project,
                    prefix="X",
                )
            )
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(insert(constraint_sync_conflicts).values(**_sync_conflict_values()))
        _activate_sync_run(connection)
        with pytest.raises(ValueError, match="manual patch scope is unavailable"):
            SqlConstraintManagementRepository(connection).resolve_sync_conflict(
                PRINCIPAL,
                PROJECT,
                "csyc_wpzeroaaaa0001aaaa",
                resolution=ConstraintSyncResolution.MANUAL_PATCH,
                expected_version=1,
                manual_patch=manual_patch,
                idempotency_key="resolve_sync_0001",
                at=T0,
                mutation_service=NoMutation(),
                active_uow=object(),
                correlation_id=None,
            )
        assert connection.execute(select(constraint_sync_conflicts.c.state)).scalar_one() == "open"
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_resolution_history)
            ).scalar_one()
            == 0
        )


def test_keep_canonical_dismisses_a_new_external_row_without_mutation(
    migrated_engine: Engine,
) -> None:
    class NoMutation:
        def update(self, **_values: object) -> object:
            raise AssertionError("KEEP_CANONICAL must not mutate a new external row")

    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(
            insert(constraint_sync_conflicts).values(
                **_sync_conflict_values(
                    constraint_id=None,
                    conflict_kind="new_in_external",
                    baseline_revision_id=None,
                    db_version=None,
                )
            )
        )
        _activate_sync_run(connection)
        result = SqlConstraintManagementRepository(connection).resolve_sync_conflict(
            PRINCIPAL,
            PROJECT,
            "csyc_wpzeroaaaa0001aaaa",
            resolution=ConstraintSyncResolution.KEEP_CANONICAL,
            expected_version=1,
            manual_patch=None,
            idempotency_key="resolve_sync_0001",
            at=T0,
            mutation_service=NoMutation(),
            active_uow=object(),
            correlation_id=None,
        )
        assert result is not None
        assert result["constraint_version"] is None
        assert result["resolution"] == "keep_canonical"


def test_concurrent_preview_idempotency_replays_one_database_run(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
    barrier = Barrier(2)

    def preview() -> dict[str, object]:
        with migrated_engine.begin() as connection:
            barrier.wait()
            return dict(
                SqlConstraintManagementRepository(connection).preview_sync(
                    PRINCIPAL,
                    PROJECT,
                    external_identity="synthetic-workbook-identity-0001",
                    normalization_version="1",
                    rows=(
                        NormalizedExternalConstraintRow(
                            external_row_key="row-1",
                            constraint_id=CONSTRAINT,
                            constraint_code="2.01",
                            category=CATEGORY,
                            description="Sample constraint",
                            date_identified=D0,
                            status=ConstraintLifecycleState.IDENTIFIED,
                            due_date=date(2026, 9, 30),
                        ),
                    ),
                    provider_version=None,
                    workbook_digest=None,
                    idempotency_key="preview_sync_0001",
                    at=T0,
                    lease_until=T0,
                )
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _index: preview(), range(2)))
    assert {result["replayed"] for result in results} == {False, True}
    assert len({result["run_id"] for result in results}) == 1
    initial = next(result for result in results if not result["replayed"])
    replay = next(result for result in results if result["replayed"])
    assert {**initial, "replayed": True} == replay
    assert set(initial) == {
        "target_id",
        "run_id",
        "lease_token",
        "lease_until",
        "preview_digest",
        "state",
        "replayed",
        "items",
    }
    assert isinstance(initial["items"], list)
    assert set(initial["items"][0]) == {
        "row",
        "constraint_id",
        "action",
        "db",
        "external",
        "conflicts",
        "kind",
    }
    with migrated_engine.begin() as connection:
        run_count = connection.execute(
            select(func.count()).select_from(constraint_sync_runs)
        ).scalar_one()
        assert run_count == 1


def test_unsupported_normalization_schema_persists_safe_state_and_requires_fresh_repair(
    migrated_engine: Engine,
) -> None:
    external = NormalizedExternalConstraintRow(
        external_row_key="row-1",
        constraint_id=CONSTRAINT,
        constraint_code="2.01",
        category=CATEGORY,
        description="Sample constraint",
        date_identified=D0,
        status=ConstraintLifecycleState.IDENTIFIED,
        due_date=date(2026, 9, 30),
    )
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))

    audit = SqlAlchemyAuditSink(migrated_engine)
    service = ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(migrated_engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: T0,
        constraint_management_unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(
            migrated_engine
        ),
    )
    principal = Principal(principal_id=PRINCIPAL, kind=PrincipalKind.GATEWAY, authenticated=True)
    unsupported = PreviewConstraintSync(
        project_id=PROJECT,
        external_identity="synthetic-workbook-identity-0001",
        normalization_version="2",
        rows=(external,),
        idempotency_key="preview_schema_unsupported0001",
        provider_version="v2",
        workbook_digest=DIGEST,
    )
    metadata = RequestMetadata(
        request_id="request-sync-schema-unsupported-0001",
        capability=Capability.CONSTRAINT_SYNC_PREVIEW,
        purpose=Purpose.CONSTRAINT_SYNC_AUTHORING,
        principal_id=PRINCIPAL,
        requested_at=T0,
    )
    initial = service.invoke(metadata, unsupported, principal=principal)
    assert initial.error is None and initial.result is not None
    assert initial.result["state"] == "schema_unsupported"
    assert initial.result["items"] == []
    assert initial.result["replayed"] is False
    replay = service.invoke(metadata, unsupported, principal=principal)
    assert replay.error is None
    assert replay.result == {**initial.result, "replayed": True}

    with migrated_engine.begin() as connection:
        repository = SqlConstraintManagementRepository(connection)
        run = connection.execute(select(constraint_sync_runs)).one()._mapping
        assert (
            run["state"],
            run["sync_state"],
            run["failure_kind"],
            run["safe_failure_reason"],
            run["finished_at"],
        ) == ("failed", "schema_unsupported", "schema_unsupported", "schema_unsupported", T0)
        target = connection.execute(select(constraint_sync_targets)).one()._mapping
        assert target["last_run_id"] == run["sync_run_id"]
        assert target["active_run_id"] is None
        state = repository.read_sync_state(PRINCIPAL, PROJECT, SYNC_TARGET)
        assert state is not None
        assert state["state"] == "schema_unsupported"
        assert state["last_run_id"] == run["sync_run_id"]
        for table in (
            constraint_sync_run_items,
            constraint_sync_conflicts,
            constraint_sync_baselines,
        ):
            assert connection.execute(select(func.count()).select_from(table)).scalar_one() == 0
        assert (
            connection.execute(select(project_constraints.c.version)).scalar_one(),
            connection.execute(
                select(func.count()).select_from(project_constraint_history)
            ).scalar_one(),
        ) == (1, 1)
        with pytest.raises(ValueError, match="lease is no longer active"):
            repository.prepare_sync_apply(
                PRINCIPAL,
                PROJECT,
                SYNC_TARGET,
                str(run["sync_run_id"]),
                lease_token=str(run["lease_token"]),
                preview_digest=str(run["preview_digest"]),
                idempotency_key="apply_schema_unsupported0001",
                request_digest=DIGEST,
                at=T0,
            )

    repair = PreviewConstraintSync(
        project_id=PROJECT,
        external_identity="synthetic-workbook-identity-0001",
        normalization_version="1",
        rows=(external,),
        idempotency_key="preview_schema_repair0001",
        provider_version="v2",
        workbook_digest=DIGEST,
    )
    repaired = service.invoke(
        RequestMetadata(
            request_id="request-sync-schema-repair-0001",
            capability=Capability.CONSTRAINT_SYNC_PREVIEW,
            purpose=Purpose.CONSTRAINT_SYNC_AUTHORING,
            principal_id=PRINCIPAL,
            requested_at=T0,
        ),
        repair,
        principal=principal,
    )
    assert repaired.error is None and repaired.result is not None
    assert repaired.result["state"] == "in_sync"
    assert repaired.result["run_id"] != initial.result["run_id"]
    late_replay = service.invoke(metadata, unsupported, principal=principal)
    assert late_replay.error is None
    assert late_replay.result == {**initial.result, "replayed": True}
    with migrated_engine.begin() as connection:
        assert (
            connection.execute(select(func.count()).select_from(constraint_sync_runs)).scalar_one()
            == 2
        )
        assert (
            connection.execute(select(project_constraints.c.version)).scalar_one(),
            connection.execute(
                select(func.count()).select_from(project_constraint_history)
            ).scalar_one(),
        ) == (1, 1)
        current = SqlConstraintManagementRepository(connection).read_sync_state(
            PRINCIPAL, PROJECT, SYNC_TARGET
        )
        assert current is not None
        assert current["state"] == "in_sync"
        assert current["last_run_id"] == repaired.result["run_id"]


def test_malformed_external_party_preview_has_zero_database_effects(
    migrated_engine: Engine,
) -> None:
    malformed = (
        ("bic", [{"kind": "bogus"}]),
        ("responsible", [{"kind": "unresolved"}]),
        ("bic", "principal"),
        ("responsible", {"kind": "principal"}),
        ("bic", [[{"kind": "principal"}]]),
    )
    with migrated_engine.begin() as connection:
        _base(connection)
        before = (
            connection.execute(select(project_constraints.c.version)).scalar_one(),
            connection.execute(
                select(func.count()).select_from(project_constraint_history)
            ).scalar_one(),
        )
        for field, value in malformed:
            with pytest.raises(InvalidRequestError):
                _preview_constraint_sync(
                    {
                        "project_id": PROJECT,
                        "external_identity": "synthetic-workbook-identity-0001",
                        "normalization_version": "1",
                        "rows": [{"external_row_key": "row-1", field: value}],
                        "idempotency_key": "preview_party_invalid0001",
                    }
                )
        for table in (
            constraint_sync_targets,
            constraint_sync_runs,
            constraint_sync_run_items,
            constraint_sync_conflicts,
            constraint_sync_baselines,
        ):
            assert connection.execute(select(func.count()).select_from(table)).scalar_one() == 0
        assert (
            connection.execute(select(project_constraints.c.version)).scalar_one(),
            connection.execute(
                select(func.count()).select_from(project_constraint_history)
            ).scalar_one(),
        ) == before


def test_concurrent_first_previews_with_different_keys_create_one_target_and_run(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(
            insert(constraint_project_settings).values(
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            )
        )
    barrier = Barrier(2)

    def preview(index: int) -> Mapping[str, object] | str:
        with migrated_engine.begin() as connection:
            barrier.wait()
            try:
                return SqlConstraintManagementRepository(connection).preview_sync(
                    PRINCIPAL,
                    PROJECT,
                    external_identity="synthetic-workbook-identity-0001",
                    normalization_version="1",
                    rows=(NormalizedExternalConstraintRow(external_row_key="row-1"),),
                    provider_version=None,
                    workbook_digest=None,
                    idempotency_key=f"preview_sync_000{index + 1}",
                    at=T0,
                    lease_until=T0 + timedelta(minutes=5),
                )
            except ValueError as error:
                return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(preview, range(2)))
    accepted = [result for result in results if isinstance(result, Mapping)]
    refused = [result for result in results if isinstance(result, str)]
    assert len(accepted) == 1
    assert refused == ["a synchronization run already holds the lease"]
    with migrated_engine.begin() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_targets)
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(select(func.count()).select_from(constraint_sync_runs)).scalar_one()
            == 1
        )


def test_concurrent_identical_resolutions_return_one_exact_replay(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        connection.execute(insert(constraint_sync_conflicts).values(**_sync_conflict_values()))
        _activate_sync_run(connection)
    barrier = Barrier(2)

    class NoMutation:
        def update(self, **_values: object) -> object:
            raise AssertionError("KEEP_CANONICAL must not mutate")

    def resolve() -> dict[str, object]:
        with migrated_engine.begin() as connection:
            barrier.wait()
            result = SqlConstraintManagementRepository(connection).resolve_sync_conflict(
                PRINCIPAL,
                PROJECT,
                "csyc_wpzeroaaaa0001aaaa",
                resolution=ConstraintSyncResolution.KEEP_CANONICAL,
                expected_version=1,
                manual_patch=None,
                idempotency_key="resolve_sync_0001",
                at=T0,
                mutation_service=NoMutation(),
                active_uow=object(),
                correlation_id=None,
            )
            assert result is not None
            return dict(result)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _index: resolve(), range(2)))
    assert {result["replayed"] for result in results} == {False, True}
    initial = next(result for result in results if not result["replayed"])
    replay = next(result for result in results if result["replayed"])
    assert replay == {**initial, "replayed": True}
    with migrated_engine.begin() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(constraint_sync_resolution_history)
            ).scalar_one()
            == 1
        )


def test_sync_run_item_metadata_binds_the_full_run_scope() -> None:
    foreign_key = next(
        constraint
        for constraint in constraint_sync_run_items.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "a_sync_item_belongs_to_its_principals_run"
    )
    assert tuple(foreign_key.column_keys) == (
        "principal_id",
        "project_id",
        "sync_target_id",
        "sync_run_id",
    )
    conflict_key = next(
        constraint
        for constraint in constraint_sync_resolution_history.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "a_sync_resolution_names_its_principals_conflict"
    )
    run_key = next(
        constraint
        for constraint in constraint_sync_resolution_history.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "a_sync_resolution_names_its_principals_run"
    )
    assert tuple(conflict_key.column_keys) == (
        "principal_id",
        "project_id",
        "sync_target_id",
        "sync_run_id",
        "sync_conflict_id",
    )
    assert tuple(run_key.column_keys) == (
        "principal_id",
        "project_id",
        "sync_target_id",
        "sync_run_id",
    )
    resolution_check = next(
        constraint
        for constraint in constraint_sync_resolution_history.constraints
        if constraint.name == "a_sync_resolution_is_known"
    )
    assert "legacy_migrated" in str(resolution_check.sqltext)
    assert "reopen" in str(resolution_check.sqltext)


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
                    **_sync_run_values(
                        sync_run_id="csyr_wpzerobbbb0002bbbb",
                        preview_idempotency_key="preview_sync_0002",
                        **overrides,
                    )
                ),
            )
        _accepts(
            connection,
            insert(constraint_sync_runs).values(
                **_sync_run_values(
                    sync_run_id="csyr_wpzerobbbb0002bbbb",
                    preview_idempotency_key="preview_sync_0002",
                    state="failed",
                    finished_at=T0,
                    outcome="failed",
                    safe_failure_reason="provider_unavailable",
                )
            ),
        )


def test_a_preview_idempotency_key_names_one_run_per_principal(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _base(connection)
        connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
        connection.execute(insert(constraint_sync_runs).values(**_sync_run_values()))
        _refuses(
            connection,
            insert(constraint_sync_runs).values(
                **_sync_run_values(sync_run_id="csyr_wpzerobbbb0002bbbb")
            ),
            names="constraint_sync_runs_principal_preview_key_is_unique",
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
        row = _sync_conflict_values()
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
                    "resolution_history_id": "csyrh_wpzeroaaaa0001aaaa",
                }
            ),
        )
        _accepts(
            connection,
            insert(constraint_sync_resolution_history).values(
                resolution_history_id="csyrh_wpzeroaaaa0001aaaa",
                principal_id=PRINCIPAL,
                project_id=PROJECT,
                sync_target_id=SYNC_TARGET,
                sync_conflict_id="csyc_wpzerocccc0003cccc",
                sync_run_id=SYNC_RUN,
                resolution="keep_canonical",
                expected_constraint_version=1,
                idempotency_key="resolved_sync_0001",
                request_digest=DIGEST,
                constraint_history_id=None,
                constraint_version=1,
                created_at=T0,
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
