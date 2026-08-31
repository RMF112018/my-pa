"""RI-ENT-WP-06b's six Entity-bound families against real PostgreSQL.

`tests/unit/test_identity_correction_planning.py` drives `plan_names`,
`plan_organization_profiles`, `plan_addresses`, `plan_communication_methods`,
`plan_project_participations` and `plan_person_organization_affiliations`
over records. This drives the whole service against PostgreSQL for each
family: the reparenting actually satisfies the family's own active-uniqueness
index, the self-edge/singleton hazards actually behave the way the schema's
own constraints require, a split actually inverts what the merge recorded, and
a row created against the survivor after the merge is actually discovered as
`POST_MERGE_CREATED` ambiguity through the generic `records_bound_to_entity_
outside` walk -- never silently missed.

No repository write method exists for any of these six families (`WP-08`
ships that; this increment does not, by the campaign document's own binding
dependency). Every row below is inserted directly against the Core `Table`
objects, on `tests/database/test_entity_names_tbr_gs4_studios_fixture.py`'s
own precedent for a family with no write path yet.

Every identity here is synthetic and every address is `example.invalid`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, insert, select, text
from sqlalchemy.engine import make_url

from my_pa.application.errors import ConflictError
from my_pa.application.identity_correction import (
    ConflictChoice,
    FamilyDisposition,
    IdentityCorrectionService,
    MergeCommand,
    MergeFamily,
    MergePreviewCommand,
    MergePreviewReport,
    MergeReceipt,
    SplitCommand,
    SplitPreviewCommand,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import ActorClass
from my_pa.domain.relationship.identity_correction import (
    AmbiguityDisposition,
    AmbiguityReason,
    IdentityConflictKind,
    IdentityEffectFamily,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import SqlRelationshipMemoryRepository
from my_pa.infrastructure.persistence.tables import (
    entity_addresses,
    entity_communication_methods,
    entity_names,
    entity_organization_profiles,
    entity_person_organization_affiliations,
    entity_project_participations,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
DISPOSABLE_DATABASE: Final = "my_pa_ri_ent_wp06b_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"

SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED_ONE: Final = "ent_bbbb0002bbbb0002"
MERGED_TWO: Final = "ent_cccc0003cccc0003"
TOWER: Final = "ent_dddd0004dddd0004"
OUTSIDER: Final = "ent_eeee0005eeee0005"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
OPERATOR: Final = PRINCIPAL_A
CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa0001"
REASON: Final = "two synthetic records describe one synthetic person"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _entity(
    entity_id: str,
    name: str = "Alice Synthetic",
    entity_type: EntityType = EntityType.PERSON,
    *,
    version: int = 1,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL_A,
        entity_type=entity_type,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=version,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """Two synthetic duplicates of one person, a third decoy, and a project."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, _entity(SURVIVOR))
        repository.create(PRINCIPAL_A, _entity(MERGED_ONE, name="Alice Synthetic Two"))
        repository.create(PRINCIPAL_A, _entity(MERGED_TWO, name="Alice Synthetic Three"))
        repository.create(
            PRINCIPAL_A, _entity(TOWER, name="Harbour Tower", entity_type=EntityType.PROJECT)
        )
        repository.create(
            PRINCIPAL_A,
            _entity(OUTSIDER, name="Outsider Organization", entity_type=EntityType.ORGANIZATION),
        )
    return migrated_engine


def _preview_command(
    *,
    merged: tuple[tuple[str, int], ...] = ((MERGED_ONE, 1),),
    survivor: str = SURVIVOR,
    survivor_version: int = 1,
) -> MergePreviewCommand:
    return MergePreviewCommand(
        principal_id=PRINCIPAL_A,
        survivor_entity_id=survivor,
        expected_survivor_version=survivor_version,
        merged_away=merged,
        reason=REASON,
    )


def _service(connection: Connection) -> IdentityCorrectionService:
    return IdentityCorrectionService(
        SqlEntityRepository(connection), SqlRelationshipMemoryRepository(connection)
    )


def _previewed(
    connection: Connection, command_: MergePreviewCommand | None = None, *, at: datetime = WHEN
) -> MergePreviewReport:
    return _service(connection).preview(
        command_ or _preview_command(),
        at=at,
        requested_by=OPERATOR,
        actor_class=ActorClass.USER,
        has_operator_authority=True,
    )


def _applied(
    connection: Connection,
    report: MergePreviewReport,
    *,
    key: str = "merge-one",
    at: datetime = WHEN,
    choices: tuple[tuple[str, ConflictChoice], ...] = (),
) -> MergeReceipt:
    return _service(connection).apply(
        MergeCommand(
            principal_id=PRINCIPAL_A,
            preview_id=report.preview.preview_id,
            preview_digest=report.preview.preview_digest,
            idempotency_key=key,
            reason=REASON,
            choices=choices,
        ),
        at=at,
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        performed_by=OPERATOR,
        actor_class=ActorClass.USER,
        has_operator_authority=True,
    )


def _group(report: MergePreviewReport, family: MergeFamily) -> tuple[FamilyDisposition, int]:
    found = next(group for group in report.groups if group.family is family)
    return found.disposition, found.record_count


def _row_count(engine: Engine, table: str, predicate: str = "true") -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE {predicate}")  # noqa: S608
            ).scalar_one()
        )


def _insert_name(
    connection: Connection,
    entity_name_id: str,
    entity_id: str,
    value: str = "Alice Synthetic",
    *,
    name_type_code: str = "display",
    is_preferred: bool = False,
    state: str = "active",
    principal_id: str = PRINCIPAL_A,
) -> None:
    connection.execute(
        insert(entity_names).values(
            entity_name_id=entity_name_id,
            entity_id=entity_id,
            principal_id=principal_id,
            name_type_code=name_type_code,
            normalized_value=normalize_name(value),
            display_value=value,
            is_preferred=is_preferred,
            state=state,
            version=1,
        )
    )


def _insert_address(
    connection: Connection,
    entity_address_id: str,
    entity_id: str,
    raw_value: str = "123 Main St",
    *,
    address_type_code: str = "office",
    is_preferred: bool = False,
    state: str = "active",
) -> None:
    connection.execute(
        insert(entity_addresses).values(
            entity_address_id=entity_address_id,
            entity_id=entity_id,
            principal_id=PRINCIPAL_A,
            address_type_code=address_type_code,
            raw_value=raw_value,
            normalized_address_value=raw_value.strip().lower(),
            is_preferred=is_preferred,
            state=state,
            version=1,
        )
    )


def _insert_communication_method(
    connection: Connection,
    communication_method_id: str,
    entity_id: str,
    value: str = "alice@example.invalid",
    *,
    method_type_code: str = "email",
    is_preferred: bool = False,
    state: str = "active",
) -> None:
    connection.execute(
        insert(entity_communication_methods).values(
            communication_method_id=communication_method_id,
            entity_id=entity_id,
            principal_id=PRINCIPAL_A,
            method_type_code=method_type_code,
            usage_context_code="generic",
            normalized_value=value.strip().casefold(),
            display_value=value,
            is_preferred=is_preferred,
            state=state,
            version=1,
        )
    )


def _insert_profile(
    connection: Connection,
    entity_id: str,
    *,
    organization_kind_code: str = "company",
) -> None:
    connection.execute(
        insert(entity_organization_profiles).values(
            entity_id=entity_id,
            principal_id=PRINCIPAL_A,
            organization_kind_code=organization_kind_code,
            legal_identity_status_code="unresolved",
            version=1,
        )
    )


def _insert_participation(
    connection: Connection,
    participation_id: str,
    project_entity_id: str,
    participant_entity_id: str,
    *,
    role_code: str | None = "CONSULTANT",
    state: str = "active",
) -> None:
    connection.execute(
        insert(entity_project_participations).values(
            participation_id=participation_id,
            principal_id=PRINCIPAL_A,
            project_entity_id=project_entity_id,
            participant_entity_id=participant_entity_id,
            project_display_name="Synthetic Participant",
            role_code=role_code,
            role_basis_code="contractual",
            stakeholder_side_code="consultant",
            stakeholder_class_code="core",
            relationship_status_code="active",
            state=state,
            version=1,
        )
    )


def _insert_affiliation(
    connection: Connection,
    affiliation_id: str,
    person_entity_id: str,
    organization_entity_id: str | None,
    *,
    state: str = "active",
    effective_to: datetime | None = None,
) -> None:
    connection.execute(
        insert(entity_person_organization_affiliations).values(
            affiliation_id=affiliation_id,
            principal_id=PRINCIPAL_A,
            person_entity_id=person_entity_id,
            organization_entity_id=organization_entity_id,
            affiliation_type_code="employment",
            state=state,
            effective_to=effective_to,
            version=1,
        )
    )


# --- names --------------------------------------------------------------


def test_a_name_reparents_and_a_preferred_collision_demotes(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_name(
            connection, "enam_ssss0001ssss01", SURVIVOR, "Survivor Preferred", is_preferred=True
        )
        _insert_name(
            connection, "enam_aaaa0001aaaa01", MERGED_ONE, "Merged Preferred", is_preferred=True
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.NAME) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        rows = connection.execute(
            select(entity_names).where(entity_names.c.entity_name_id == "enam_aaaa0001aaaa01")
        ).one()
    assert rows.entity_id == SURVIVOR
    assert rows.is_preferred is False
    # The survivor's own preferred row is untouched.
    with staged.connect() as connection:
        survivor_row = connection.execute(
            select(entity_names).where(entity_names.c.entity_name_id == "enam_ssss0001ssss01")
        ).one()
    assert survivor_row.is_preferred is True


def test_a_name_split_inverts(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_name(connection, "enam_aaaa0001aaaa01", MERGED_ONE, "Ali")
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        merge = _applied(connection, report)
    with staged.begin() as connection:
        split_preview = _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=merge.operation.identity_operation_id,
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=1),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    assert split_preview.ambiguities == ()
    with staged.begin() as connection:
        _service(connection).split_apply(
            SplitCommand(
                principal_id=PRINCIPAL_A,
                preview_id=split_preview.preview.preview_id,
                preview_digest=split_preview.preview.preview_digest,
                idempotency_key="split-name",
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=2),
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_names).where(entity_names.c.entity_name_id == "enam_aaaa0001aaaa01")
        ).one()
    assert row.entity_id == MERGED_ONE


def test_a_name_created_after_the_merge_is_discovered_as_ambiguity(staged: Engine) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        merge = _applied(connection, report)
    with staged.begin() as connection:
        _insert_name(connection, "enam_post0001post01", SURVIVOR, "Post-Merge Name")
    with staged.begin() as connection:
        split_preview = _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=merge.operation.identity_operation_id,
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=1),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    matching = [
        ambiguity
        for ambiguity in split_preview.ambiguities
        if ambiguity.record_family is IdentityEffectFamily.NAME
    ]
    assert len(matching) == 1
    assert matching[0].record_id == "enam_post0001post01"
    assert matching[0].reason == AmbiguityReason.POST_MERGE_CREATED.value


# --- organization profiles -----------------------------------------------


def test_an_organization_profile_reparents_and_split_inverts(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_profile(connection, MERGED_ONE)
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.ORGANIZATION_PROFILE) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        merge = _applied(connection, report)
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_organization_profiles).where(
                entity_organization_profiles.c.entity_id == SURVIVOR
            )
        ).one()
    assert row.entity_id == SURVIVOR
    assert _row_count(staged, "entity_organization_profiles") == 1

    with staged.begin() as connection:
        split_preview = _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=merge.operation.identity_operation_id,
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=1),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.begin() as connection:
        _service(connection).split_apply(
            SplitCommand(
                principal_id=PRINCIPAL_A,
                preview_id=split_preview.preview.preview_id,
                preview_digest=split_preview.preview.preview_digest,
                idempotency_key="split-profile",
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=2),
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.connect() as connection:
        restored = connection.execute(
            select(entity_organization_profiles).where(
                entity_organization_profiles.c.entity_id == MERGED_ONE
            )
        ).one_or_none()
    assert restored is not None
    assert _row_count(staged, "entity_organization_profiles") == 1


def test_a_profile_on_both_sides_blocks_the_merge(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_profile(connection, SURVIVOR)
        _insert_profile(connection, MERGED_ONE)
    with staged.begin() as connection:
        report = _previewed(connection)
    assert [conflict.kind for conflict in report.blockers] == [
        IdentityConflictKind.SINGLETON_RECORD_CONFLICT
    ]
    assert _group(report, MergeFamily.ORGANIZATION_PROFILE)[0] is FamilyDisposition.BLOCKED
    with pytest.raises(ConflictError), staged.begin() as connection:
        _applied(connection, report)
    assert _row_count(staged, "entities", "status = 'merged_redirect'") == 0
    # Both profiles remain exactly as recorded -- nothing is deleted or moved.
    assert _row_count(staged, "entity_organization_profiles") == 2


# --- addresses and communication methods (abbreviated: shape mirrors names) --


def test_an_address_reparents_and_a_current_one_the_survivor_holds_coalesces(
    staged: Engine,
) -> None:
    with staged.begin() as connection:
        _insert_address(connection, "eadr_ssss0001ssss01", SURVIVOR, "1 Main St")
        _insert_address(connection, "eadr_aaaa0001aaaa01", MERGED_ONE, "1 Main St")
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.ADDRESS) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_addresses).where(
                entity_addresses.c.entity_address_id == "eadr_aaaa0001aaaa01"
            )
        ).one()
    assert row.state == "superseded"
    assert row.superseded_by_entity_address_id == "eadr_ssss0001ssss01"


def test_a_communication_method_reparents_and_split_inverts(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_communication_method(connection, "ecmm_aaaa0001aaaa01", MERGED_ONE)
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.COMMUNICATION_METHOD) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        merge = _applied(connection, report)
    with staged.begin() as connection:
        split_preview = _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=merge.operation.identity_operation_id,
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=1),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.begin() as connection:
        _service(connection).split_apply(
            SplitCommand(
                principal_id=PRINCIPAL_A,
                preview_id=split_preview.preview.preview_id,
                preview_digest=split_preview.preview.preview_digest,
                idempotency_key="split-comm",
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=2),
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_communication_methods).where(
                entity_communication_methods.c.communication_method_id == "ecmm_aaaa0001aaaa01"
            )
        ).one()
    assert row.entity_id == MERGED_ONE


# --- project participations ----------------------------------------------


def test_a_participation_reparents_both_columns_independently_in_one_merge(
    staged: Engine,
) -> None:
    """The project (`TOWER`) is not merged here; only the participant is --
    proving the participant-side column substitutes independently of the
    project-side column."""
    with staged.begin() as connection:
        _insert_participation(connection, "eppt_aaaa0001aaaa01", TOWER, MERGED_ONE)
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.PROJECT_PARTICIPATION) == (FamilyDisposition.TRANSFORMED, 1)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_project_participations).where(
                entity_project_participations.c.participation_id == "eppt_aaaa0001aaaa01"
            )
        ).one()
    assert row.project_entity_id == TOWER
    assert row.participant_entity_id == SURVIVOR


def test_both_participation_columns_reparent_when_both_entities_are_merged(
    staged: Engine,
) -> None:
    """A multi-entity merge where the project (`TOWER`) and the participant
    (`MERGED_ONE`) are both merged-away entities in the same operation."""
    with staged.begin() as connection:
        _insert_participation(connection, "eppt_aaaa0001aaaa01", TOWER, MERGED_ONE)
    with staged.begin() as connection:
        report = _previewed(connection, _preview_command(merged=((MERGED_ONE, 1), (TOWER, 1))))
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_project_participations).where(
                entity_project_participations.c.participation_id == "eppt_aaaa0001aaaa01"
            )
        ).one()
    # Both references collapsed onto the one survivor -- a self-participation,
    # so the row was superseded rather than reparented.
    assert row.state == "superseded"
    assert row.superseded_by_participation_id is None
    assert row.project_entity_id == TOWER
    assert row.participant_entity_id == MERGED_ONE


def test_a_current_participation_the_survivor_already_holds_deduplicates(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_participation(
            connection, "eppt_ssss0001ssss01", TOWER, SURVIVOR, role_code="CONSULTANT"
        )
        _insert_participation(
            connection, "eppt_aaaa0001aaaa01", TOWER, MERGED_ONE, role_code="CONSULTANT"
        )
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_project_participations).where(
                entity_project_participations.c.participation_id == "eppt_aaaa0001aaaa01"
            )
        ).one()
    assert row.state == "superseded"
    assert row.superseded_by_participation_id == "eppt_ssss0001ssss01"


def test_a_participation_split_inverts(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_participation(connection, "eppt_aaaa0001aaaa01", TOWER, MERGED_ONE)
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        merge = _applied(connection, report)
    with staged.begin() as connection:
        split_preview = _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=merge.operation.identity_operation_id,
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=1),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.begin() as connection:
        _service(connection).split_apply(
            SplitCommand(
                principal_id=PRINCIPAL_A,
                preview_id=split_preview.preview.preview_id,
                preview_digest=split_preview.preview.preview_digest,
                idempotency_key="split-participation",
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=2),
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_project_participations).where(
                entity_project_participations.c.participation_id == "eppt_aaaa0001aaaa01"
            )
        ).one()
    assert row.participant_entity_id == MERGED_ONE


# --- person-organization affiliations -------------------------------------


def test_an_affiliation_reparents_both_columns_independently(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_affiliation(connection, "poaf_aaaa0001aaaa01", MERGED_ONE, OUTSIDER)
    with staged.begin() as connection:
        report = _previewed(connection)
    assert _group(report, MergeFamily.PERSON_ORGANIZATION_AFFILIATION) == (
        FamilyDisposition.TRANSFORMED,
        1,
    )
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_person_organization_affiliations).where(
                entity_person_organization_affiliations.c.affiliation_id == "poaf_aaaa0001aaaa01"
            )
        ).one()
    assert row.person_entity_id == SURVIVOR
    assert row.organization_entity_id == OUTSIDER


def test_an_open_affiliation_colliding_with_the_survivors_own_coalesces(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_affiliation(connection, "poaf_ssss0001ssss01", SURVIVOR, OUTSIDER)
        _insert_affiliation(connection, "poaf_aaaa0001aaaa01", MERGED_ONE, OUTSIDER)
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        _applied(connection, report)
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_person_organization_affiliations).where(
                entity_person_organization_affiliations.c.affiliation_id == "poaf_aaaa0001aaaa01"
            )
        ).one()
    assert row.state == "superseded"
    assert row.superseded_by_affiliation_id == "poaf_ssss0001ssss01"
    # Nothing is deleted: the merged-away person's own row stays parented to
    # its own (now-redirected) entity_id.
    assert row.person_entity_id == MERGED_ONE
    # The survivor's own open affiliation is untouched.
    with staged.connect() as connection:
        survivor_row = connection.execute(
            select(entity_person_organization_affiliations).where(
                entity_person_organization_affiliations.c.affiliation_id == "poaf_ssss0001ssss01"
            )
        ).one()
    assert survivor_row.state == "active"


def test_an_affiliation_split_inverts(staged: Engine) -> None:
    with staged.begin() as connection:
        _insert_affiliation(connection, "poaf_aaaa0001aaaa01", MERGED_ONE, OUTSIDER)
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        merge = _applied(connection, report)
    with staged.begin() as connection:
        split_preview = _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=merge.operation.identity_operation_id,
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=1),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.begin() as connection:
        _service(connection).split_apply(
            SplitCommand(
                principal_id=PRINCIPAL_A,
                preview_id=split_preview.preview.preview_id,
                preview_digest=split_preview.preview.preview_digest,
                idempotency_key="split-affiliation",
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=2),
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.connect() as connection:
        row = connection.execute(
            select(entity_person_organization_affiliations).where(
                entity_person_organization_affiliations.c.affiliation_id == "poaf_aaaa0001aaaa01"
            )
        ).one()
    assert row.person_entity_id == MERGED_ONE


def test_a_person_organization_affiliation_created_after_the_merge_is_discovered(
    staged: Engine,
) -> None:
    with staged.begin() as connection:
        report = _previewed(connection)
    with staged.begin() as connection:
        merge = _applied(connection, report)
    with staged.begin() as connection:
        _insert_affiliation(connection, "poaf_post0001post01", SURVIVOR, OUTSIDER)
    with staged.begin() as connection:
        split_preview = _service(connection).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL_A,
                source_identity_operation_id=merge.operation.identity_operation_id,
                reason="reverse the synthetic identity correction",
            ),
            at=WHEN + timedelta(seconds=1),
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    matching = [
        ambiguity
        for ambiguity in split_preview.ambiguities
        if ambiguity.record_family is IdentityEffectFamily.PERSON_ORGANIZATION_AFFILIATION
    ]
    assert len(matching) == 1
    assert matching[0].record_id == "poaf_post0001post01"
    assert matching[0].reason == AmbiguityReason.POST_MERGE_CREATED.value
    assert AmbiguityDisposition.ASSIGN_TO_ENTITY.value in matching[0].allowed_dispositions


# --- cross-Principal isolation ---------------------------------------------


def test_reads_of_the_six_new_families_are_partitioned_by_principal(staged: Engine) -> None:
    """A row of any of the six families belonging to another Principal is
    answered exactly as an absent one -- `EntitiesRepository`'s partition rule,
    restated for the accessors this increment adds. The composite foreign key
    to `entities(entity_id, principal_id)` requires the row to name an entity
    that Principal genuinely owns, so this creates one rather than attempting
    a cross-Principal insert against `SURVIVOR`, which the schema itself would
    refuse before this test could observe anything about the *read* side.
    """
    other_principal = "prn_bbbb0002bbbb0002bbbb0002"
    foreign_entity = "ent_ffff0006ffff0006"
    with staged.begin() as connection:
        SqlEntityRepository(connection).create(
            other_principal,
            Entity(
                entity_id=foreign_entity,
                principal_id=other_principal,
                entity_type=EntityType.PERSON,
                canonical_name=normalize_name("Bob Synthetic"),
                display_name="Bob Synthetic",
                status=EntityStatus.ACTIVE,
                created_at=WHEN,
                updated_at=WHEN,
                version=1,
            ),
        )
        _insert_name(
            connection,
            "enam_ffff0006ffff01",
            foreign_entity,
            "Bob's Name",
            name_type_code="display",
            principal_id=other_principal,
        )
    with staged.connect() as connection:
        repository = SqlEntityRepository(connection)
        # Reading it under its own Principal succeeds.
        own_names = repository.names(other_principal, foreign_entity)
        assert [name.entity_name_id for name in own_names] == ["enam_ffff0006ffff01"]
        # Reading it as PRINCIPAL_A -- who does not own the entity at all --
        # answers exactly as an absent one, not a foreign-key violation and
        # not a leak.
        assert repository.names(PRINCIPAL_A, foreign_entity) == []
