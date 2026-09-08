"""PC-CM-IMP-WP06: `ConstraintManagementService`, against an in-memory partition.

The FAST half of the mutation plane's proof. The fake below is not a stub that
agrees with whatever it is handed: it partitions by Principal exactly as the
adapter does, enforces the two stored uniqueness rules the allocator depends on
(`(project_id, constraint_code)` and `(principal_id, idempotency_key)`), and
rolls its whole state back when a transaction leaves by exception — so
atomicity, replay and the version rules are measured here rather than deferred
whole to the database tier, where `tests/database/test_constraint_management_
service.py` measures them again against PostgreSQL.

Every identifier, prefix, label and date here is synthetic.
"""

from __future__ import annotations

import copy
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any, Final

import pytest

from my_pa.application.constraint_management import (
    ConstraintCategoryNotFoundError,
    ConstraintCategoryVersionConflictError,
    ConstraintFollowUpResult,
    ConstraintIdempotencyConflictError,
    ConstraintManagementService,
    ConstraintMutationDisposition,
    ConstraintNotFoundError,
    ConstraintOperationError,
    ConstraintPartyError,
    ConstraintProjectUnavailableError,
    ConstraintReorderError,
    ConstraintVersionConflictError,
)
from my_pa.domain.project_controls.category import (
    ConstraintCategory,
    ConstraintCategoryError,
    ConstraintCategoryState,
)
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleError,
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintPublishError,
    ConstraintRecordQuality,
    ProjectConstraint,
    missing_publish_fields,
)
from my_pa.domain.project_controls.history import (
    ConstraintCategoryHistoryEntry,
    ConstraintHistoryEntry,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import (
    ConstraintCategoryRow,
    ConstraintRelationshipRow,
    RelationshipDirection,
)
from my_pa.domain.project_controls.relationship import ConstraintRelationship
from my_pa.domain.project_controls.revision import ConstraintRevision
from my_pa.domain.project_controls.settings import ConstraintProjectSettings

PRINCIPAL_A: Final = "prn_wp06aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_wp06bbbb0002bbbb0002"
PROJECT_A: Final = "prj_wp06aaaa0001aaaa"
PROJECT_B: Final = "prj_wp06bbbb0002bbbb"
ENTITY_MINE: Final = "ent_wp06aaaa0001aaaa"
ENTITY_THEIRS: Final = "ent_wp06bbbb0002bbbb"
ZONE: Final = "America/Chicago"

#: A Wednesday, chosen so `+10` business days lands on a weekday two weeks out
#: and the arithmetic in the assertions is checkable by hand.
T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

PRINCIPAL_PARTY: Final = PartyRef(kind=PartyKind.PRINCIPAL)
ENTITY_PARTY: Final = PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_MINE, label="A Vendor")
UNRESOLVED_PARTY: Final = PartyRef(kind=PartyKind.UNRESOLVED, label="whoever signs the RFI")


class FakeIntegrityError(RuntimeError):
    """What the fake raises where PostgreSQL would raise on a unique index."""


@dataclass
class _CategoryRecord:
    category: ConstraintCategory
    next_sequence: int = 1
    issued_count: int = 0
    version: int = 1


@dataclass
class _State:
    """One shared in-memory partition set, keyed the way the tables are."""

    settings: dict[tuple[str, str], ConstraintProjectSettings] = field(default_factory=dict)
    categories: dict[tuple[str, str], _CategoryRecord] = field(default_factory=dict)
    constraints: dict[tuple[str, str], ProjectConstraint] = field(default_factory=dict)
    revisions: list[tuple[str, ConstraintRevision]] = field(default_factory=list)
    history: list[tuple[str, ConstraintHistoryEntry]] = field(default_factory=list)
    category_history: list[tuple[str, ConstraintCategoryHistoryEntry]] = field(default_factory=list)
    relationships: list[tuple[str, ConstraintRelationship]] = field(default_factory=list)
    entities: dict[tuple[str, str], str] = field(default_factory=dict)
    #: Set to a callable to make the next matching write fail, which is how the
    #: rollback tests induce a failure at one exact stage.
    fail_on: str | None = None


class _FakeRepository:
    """The Constraint tables, partitioned by Principal, in memory.

    Every method takes `principal_id` first and answers a foreign row as an
    absent one, because that asymmetry — refusing rather than not finding — is
    the disclosure the real adapter's partition guard exists to prevent.
    """

    def __init__(self, state: _State) -> None:
        self._state = state

    def _trip(self, name: str) -> None:
        if self._state.fail_on == name:
            self._state.fail_on = None
            raise FakeIntegrityError(f"induced failure at {name}")

    # settings ---------------------------------------------------------
    def get_project_settings(
        self, principal_id: str, project_id: str
    ) -> ConstraintProjectSettings | None:
        return self._state.settings.get((principal_id, project_id))

    # categories -------------------------------------------------------
    def get_category(self, principal_id: str, category_id: str) -> ConstraintCategory | None:
        record = self._state.categories.get((principal_id, category_id))
        return None if record is None else record.category

    def get_category_for_update(
        self, principal_id: str, category_id: str
    ) -> ConstraintCategory | None:
        return self.get_category(principal_id, category_id)

    def insert_category(
        self,
        principal_id: str,
        category: ConstraintCategory,
        *,
        next_sequence: int = 1,
        issued_count: int = 0,
        version: int = 1,
    ) -> None:
        self._trip("insert_category")
        collision = any(
            record.category.project_id == category.project_id
            and record.category.prefix == category.prefix
            for record in self._state.categories.values()
        )
        if collision:
            raise FakeIntegrityError("a category prefix is unique within its project")
        self._state.categories[(principal_id, category.category_id)] = _CategoryRecord(
            category=category,
            next_sequence=next_sequence,
            issued_count=issued_count,
            version=version,
        )

    def update_category(
        self,
        principal_id: str,
        category: ConstraintCategory,
        *,
        next_sequence: int,
        issued_count: int,
        version: int,
    ) -> None:
        self._trip("update_category")
        self._state.categories[(principal_id, category.category_id)] = _CategoryRecord(
            category=category,
            next_sequence=next_sequence,
            issued_count=issued_count,
            version=version,
        )

    def list_categories(
        self,
        principal_id: str,
        project_id: str,
        *,
        include_states: frozenset[ConstraintCategoryState] | None = None,
    ) -> tuple[ConstraintCategoryRow, ...]:
        rows = [
            ConstraintCategoryRow(
                category_id=record.category.category_id,
                project_id=record.category.project_id,
                prefix=record.category.prefix,
                title=record.category.title,
                description=record.category.description,
                display_order=record.category.display_order,
                state=record.category.state,
                next_sequence=record.next_sequence,
                issued_count=record.issued_count,
                version=record.version,
                prefix_locked_at=record.category.prefix_locked_at,
            )
            for (owner, _), record in self._state.categories.items()
            if owner == principal_id
            and record.category.project_id == project_id
            and (include_states is None or record.category.state in include_states)
        ]
        return tuple(sorted(rows, key=lambda row: (row.display_order, row.category_id)))

    # constraints ------------------------------------------------------
    def get(self, principal_id: str, constraint_id: str) -> ProjectConstraint | None:
        return self._state.constraints.get((principal_id, constraint_id))

    def get_for_update(self, principal_id: str, constraint_id: str) -> ProjectConstraint | None:
        return self.get(principal_id, constraint_id)

    def _refuse_duplicate_code(self, constraint: ProjectConstraint) -> None:
        if constraint.constraint_code is None:
            return
        for (_, identity), stored in self._state.constraints.items():
            if (
                identity != constraint.constraint_id
                and stored.project_id == constraint.project_id
                and stored.constraint_code == constraint.constraint_code
            ):
                raise FakeIntegrityError("a public code is unique within its project")

    def insert_constraint(
        self,
        principal_id: str,
        constraint: ProjectConstraint,
        *,
        current_revision_id: str | None = None,
    ) -> None:
        self._trip("insert_constraint")
        self._refuse_duplicate_code(constraint)
        self._state.constraints[(principal_id, constraint.constraint_id)] = constraint

    def update_constraint(
        self,
        principal_id: str,
        constraint: ProjectConstraint,
        *,
        current_revision_id: str | None = None,
    ) -> None:
        self._trip("update_constraint")
        self._refuse_duplicate_code(constraint)
        self._state.constraints[(principal_id, constraint.constraint_id)] = constraint

    # ledgers ----------------------------------------------------------
    def insert_revision(self, principal_id: str, revision: ConstraintRevision) -> None:
        self._trip("insert_revision")
        taken = any(
            owner == principal_id
            and stored.constraint_id == revision.constraint_id
            and stored.version == revision.version
            for owner, stored in self._state.revisions
        )
        if taken:
            raise FakeIntegrityError("one revision per constraint version")
        self._state.revisions.append((principal_id, revision))

    def get_revision(
        self, principal_id: str, constraint_id: str, version: int
    ) -> ConstraintRevision | None:
        for owner, stored in self._state.revisions:
            if (
                owner == principal_id
                and stored.constraint_id == constraint_id
                and stored.version == version
            ):
                return stored
        return None

    def insert_history(self, principal_id: str, entry: ConstraintHistoryEntry) -> None:
        self._trip("insert_history")
        if entry.idempotency_key is not None and self.find_history_by_idempotency_key(
            principal_id, entry.idempotency_key
        ):
            raise FakeIntegrityError("one idempotency key per principal")
        self._state.history.append((principal_id, entry))

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> ConstraintHistoryEntry | None:
        for owner, entry in self._state.history:
            if owner == principal_id and entry.idempotency_key == idempotency_key:
                return entry
        return None

    def insert_category_history(
        self, principal_id: str, entry: ConstraintCategoryHistoryEntry
    ) -> None:
        self._trip("insert_category_history")
        if entry.idempotency_key is not None and self.find_category_history_by_idempotency_key(
            principal_id, entry.idempotency_key
        ):
            raise FakeIntegrityError("one idempotency key per principal")
        self._state.category_history.append((principal_id, entry))

    def find_category_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> ConstraintCategoryHistoryEntry | None:
        for owner, entry in self._state.category_history:
            if owner == principal_id and entry.idempotency_key == idempotency_key:
                return entry
        return None

    def insert_relationship(self, principal_id: str, relationship: ConstraintRelationship) -> None:
        self._trip("insert_relationship")
        duplicate = any(
            stored.source_constraint_id == relationship.source_constraint_id
            and stored.target_constraint_id == relationship.target_constraint_id
            and stored.relationship_type is relationship.relationship_type
            for _, stored in self._state.relationships
        )
        if duplicate:
            raise FakeIntegrityError("one relationship per pair and type")
        self._state.relationships.append((principal_id, relationship))

    def relationships_for(
        self, principal_id: str, constraint_id: str
    ) -> tuple[ConstraintRelationshipRow, ...]:
        rows = []
        for owner, stored in self._state.relationships:
            if owner != principal_id:
                continue
            if stored.source_constraint_id == constraint_id:
                far, direction = stored.target_constraint_id, RelationshipDirection.OUTGOING
            elif stored.target_constraint_id == constraint_id:
                far, direction = stored.source_constraint_id, RelationshipDirection.INCOMING
            else:
                continue
            related = self._state.constraints.get((principal_id, far))
            if related is None:
                continue
            rows.append(
                ConstraintRelationshipRow(
                    relationship_id=stored.relationship_id,
                    relationship_type=stored.relationship_type.value,
                    direction=direction,
                    related_constraint_id=far,
                    related_constraint_code=related.constraint_code,
                    related_status=related.lifecycle_state,
                )
            )
        return tuple(rows)

    def entity_labels(self, principal_id: str, entity_ids: Collection[str]) -> Mapping[str, str]:
        return {
            entity_id: self._state.entities[(principal_id, entity_id)]
            for entity_id in entity_ids
            if (principal_id, entity_id) in self._state.entities
        }


class _FakeUnitOfWork:
    """One transaction: it snapshots on entry and restores on any exception.

    That is the whole atomicity contract in four lines, and it makes an induced
    failure at any stage observable here rather than only against a server.
    """

    def __init__(self, state: _State) -> None:
        self._state = state
        self._snapshot: _State | None = None

    def __enter__(self) -> _FakeUnitOfWork:
        self._snapshot = copy.deepcopy(self._state)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        snapshot = self._snapshot
        self._snapshot = None
        if exc_type is not None and snapshot is not None:
            self._state.__dict__.update(copy.deepcopy(snapshot).__dict__)

    @property
    def constraints(self) -> _FakeRepository:
        return _FakeRepository(self._state)


@dataclass
class _World:
    """One Principal's synthetic Project, category and service, ready to mutate."""

    state: _State
    service: ConstraintManagementService

    def category(self, principal_id: str = PRINCIPAL_A) -> str:
        for (owner, category_id), _ in self.state.categories.items():
            if owner == principal_id:
                return category_id
        raise AssertionError("no category was seeded")


def _world(*, timezone_name: str | None = ZONE) -> _World:
    state = _State()
    if timezone_name is not None:
        for principal, project in ((PRINCIPAL_A, PROJECT_A), (PRINCIPAL_B, PROJECT_B)):
            state.settings[(principal, project)] = ConstraintProjectSettings(
                principal_id=principal,
                project_id=project,
                timezone_name=timezone_name,
                version=1,
                created_at=T0,
                updated_at=T0,
            )
    state.entities[(PRINCIPAL_A, ENTITY_MINE)] = "A Vendor"
    state.entities[(PRINCIPAL_B, ENTITY_THEIRS)] = "Their Vendor"
    service = ConstraintManagementService(
        unit_of_work=lambda: _FakeUnitOfWork(state),  # type: ignore[arg-type,return-value]
        clock=lambda: T0,
    )
    world = _World(state=state, service=service)
    world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="DES",
        title="Design",
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    return world


def _draft(world: _World, **overrides: object) -> ProjectConstraint:
    values: dict[str, Any] = {
        "principal_id": PRINCIPAL_A,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "project_id": PROJECT_A,
        "category_id": world.category(),
        "description": "The permit set is not stamped.",
        "date_identified": date(2026, 9, 2),
        "bic": (PRINCIPAL_PARTY,),
    }
    values.update(overrides)
    return world.service.create_draft(**values).record


def _published(world: _World, **overrides: object) -> ProjectConstraint:
    draft = _draft(world, **overrides)
    return world.service.publish(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=draft.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    ).record


def _history(world: _World, constraint_id: str) -> list[ConstraintHistoryEntry]:
    return [entry for _, entry in world.state.history if entry.constraint_id == constraint_id]


# --- Draft -------------------------------------------------------------------


def test_a_draft_is_saved_with_an_opaque_identity_version_one_and_no_public_code() -> None:
    """CM-BE-AC-005. The Draft exists, is identified, and has consumed no number."""
    world = _world()
    result = world.service.create_draft(
        principal_id=PRINCIPAL_A,
        actor=ConstraintMutationActor.PRINCIPAL,
        project_id=PROJECT_A,
        description="A drafted constraint.",
    )
    assert result.disposition is ConstraintMutationDisposition.APPLIED
    assert result.record.constraint_id.startswith("cst_")
    assert result.record.version == 1
    assert result.record.constraint_code is None
    assert result.record.published_at is None
    assert result.record.lifecycle_state is ConstraintLifecycleState.DRAFT
    assert result.record.principal_id == PRINCIPAL_A
    assert result.receipt.operation is ConstraintMutationOperation.CREATE
    assert result.receipt.outcome is ConstraintMutationOutcome.APPLIED
    assert (result.receipt.before_version, result.receipt.after_version) == (0, 1)


def test_a_draft_may_be_incomplete_and_reports_exactly_what_publish_still_needs() -> None:
    """CM-BE-AC-005: Draft rules are lenient, and the gap is named rather than inferred."""
    world = _world()
    draft = world.service.create_draft(
        principal_id=PRINCIPAL_A, actor=ConstraintMutationActor.PRINCIPAL
    ).record
    assert [key.value for key in missing_publish_fields(draft)] == [
        "project_id",
        "category_id",
        "description",
        "date_identified",
        "due_date",
        "bic",
    ]


def test_a_draft_consumes_no_number_from_its_category() -> None:
    """CM-BE-AC-026. The allocator is untouched until a Publish succeeds."""
    world = _world()
    _draft(world)
    _draft(world)
    row = world.state.categories[(PRINCIPAL_A, world.category())]
    assert (row.next_sequence, row.issued_count) == (1, 0)
    assert row.category.prefix_locked_at is None


def test_a_draft_cannot_bind_a_project_this_principal_does_not_have() -> None:
    """The Project seam: foreign and unconfigured are the same refusal."""
    world = _world()
    with pytest.raises(ConstraintProjectUnavailableError):
        world.service.create_draft(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            project_id=PROJECT_B,
        )


def test_a_draft_cannot_bind_another_principals_category() -> None:
    world = _world()
    world.service.create_category(
        principal_id=PRINCIPAL_B,
        project_id=PROJECT_B,
        prefix="THEIRS",
        title="Theirs",
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    theirs = world.category(PRINCIPAL_B)
    with pytest.raises(ConstraintCategoryNotFoundError):
        world.service.create_draft(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            project_id=PROJECT_A,
            category_id=theirs,
        )


def test_no_ordinary_mutation_can_create_a_legacy_incomplete_record() -> None:
    """The §17 exception stays an import path, not an authoring one."""
    world = _world()
    draft = _draft(world)
    assert draft.origin is ConstraintOrigin.PRODUCT
    assert draft.record_quality is ConstraintRecordQuality.NORMAL
    with pytest.raises(TypeError):
        world.service.create_draft(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            record_quality=ConstraintRecordQuality.LEGACY_INCOMPLETE,  # type: ignore[call-arg]
        )


# --- Publish -----------------------------------------------------------------


def test_publish_allocates_the_first_public_code_and_writes_the_first_revision() -> None:
    """CM-BE-AC-024/027/062/063. One Publish, one code, one immutable snapshot."""
    world = _world()
    draft = _draft(world, bic=(PRINCIPAL_PARTY, ENTITY_PARTY), responsible=(UNRESOLVED_PARTY,))
    result = world.service.publish(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert result.disposition is ConstraintMutationDisposition.APPLIED
    assert result.record.constraint_code == "DES.01"
    assert result.record.lifecycle_state is ConstraintLifecycleState.IDENTIFIED
    assert result.record.published_at == T0
    assert result.record.version == 2
    assert result.receipt.operation is ConstraintMutationOperation.PUBLISH
    revision = next(stored for _, stored in world.state.revisions if stored.version == 2)
    assert revision.constraint_code == "DES.01"
    assert revision.bic == (PRINCIPAL_PARTY, ENTITY_PARTY)
    assert revision.responsible == (UNRESOLVED_PARTY,)
    assert revision.history_id == result.receipt.history_id
    assert result.receipt.revision_id == revision.revision_id


def test_publish_defaults_the_due_date_to_ten_business_days_after_date_identified() -> None:
    """CM-BE-AC-044 consumed: Wednesday 2 September plus ten working days."""
    world = _world()
    published = _published(world, due_date=None, date_identified=date(2026, 9, 2))
    assert published.due_date == date(2026, 9, 16)


def test_publish_defaults_date_identified_to_the_project_calendar_date() -> None:
    world = _world()
    draft = _draft(world, date_identified=None)
    published = world.service.publish(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
    ).record
    #: 15:00 UTC on 2 September is still 2 September in America/Chicago.
    assert published.date_identified == date(2026, 9, 2)


def test_publish_fails_closed_when_the_project_calendar_is_not_available() -> None:
    """The accepted typed refusal, rather than a guessed fallback timezone.

    The Project seam and the calendar are the same settings row, so a Publish
    that needs a defaulted Date Identified from a Project this Principal has no
    settings for is refused before anything is written — and refused
    identically to naming another Principal's Project, which is the
    nondisclosure the read plane already keeps.
    """
    world = _world()
    draft = _draft(world, date_identified=None)
    del world.state.settings[(PRINCIPAL_A, PROJECT_A)]
    with pytest.raises(ConstraintProjectUnavailableError):
        world.service.publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    assert world.state.constraints[(PRINCIPAL_A, draft.constraint_id)].constraint_code is None
    row = world.state.categories[(PRINCIPAL_A, world.category())]
    assert (row.next_sequence, row.issued_count) == (1, 0)


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"description": None}, "description"),
        ({"bic": ()}, "bic"),
        ({"category_id": None}, "category_id"),
    ],
)
def test_publish_refuses_every_missing_required_field(
    overrides: dict[str, Any], missing: str
) -> None:
    """CM-BE-AC-034 among them: a normal Publish requires at least one BIC."""
    world = _world()
    draft = _draft(world, **overrides)
    with pytest.raises(ConstraintPublishError) as caught:
        world.service.publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    assert missing in str(caught.value)


def test_publish_refuses_an_inactive_category() -> None:
    world = _world()
    draft = _draft(world)
    world.service.deactivate_category(
        principal_id=PRINCIPAL_A,
        category_id=world.category(),
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    with pytest.raises(ConstraintPublishError) as caught:
        world.service.publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    assert caught.value.code == "constraint_publish_category_not_active"


def test_publish_refuses_a_second_publication_of_the_same_record() -> None:
    """DRAFT is the only state Publish moves from; a published record is done."""
    world = _world()
    published = _published(world)
    with pytest.raises(ConstraintPublishError) as caught:
        world.service.publish(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    assert caught.value.code == "constraint_publish_not_draft"


def test_a_refused_publish_consumes_no_number_and_leaves_no_partial_state() -> None:
    """CM-BE-AC-026 and atomicity: the allocator is not advanced by a failure."""
    world = _world()
    draft = _draft(world, bic=())
    before = replace(world.state.categories[(PRINCIPAL_A, world.category())])
    with pytest.raises(ConstraintPublishError):
        world.service.publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    after = world.state.categories[(PRINCIPAL_A, world.category())]
    assert (after.next_sequence, after.issued_count) == (before.next_sequence, before.issued_count)
    assert world.state.constraints[(PRINCIPAL_A, draft.constraint_id)].version == 1


# --- Public numbering --------------------------------------------------------


def test_the_public_code_sequence_is_exact_text_at_every_width() -> None:
    """CM-BE-AC-027/028. `2.01`, `2.09`, `2.10`, `2.100`, and never `1.1`."""
    world = _world()
    world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="2",
        title="Numbered",
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    numbered = next(
        category_id
        for (owner, category_id), record in world.state.categories.items()
        if owner == PRINCIPAL_A and record.category.prefix == "2"
    )
    codes = [_published(world, category_id=numbered).constraint_code for _ in range(10)]
    assert codes[0] == "2.01"
    assert codes[8] == "2.09"
    assert codes[9] == "2.10"
    assert codes[9] != "2.1"
    world.state.categories[(PRINCIPAL_A, numbered)].next_sequence = 100
    assert _published(world, category_id=numbered).constraint_code == "2.100"


def test_each_category_numbers_independently() -> None:
    world = _world()
    world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="PRO",
        title="Procurement",
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    other = next(
        category_id
        for (owner, category_id), record in world.state.categories.items()
        if owner == PRINCIPAL_A and record.category.prefix == "PRO"
    )
    assert _published(world).constraint_code == "DES.01"
    assert _published(world, category_id=other).constraint_code == "PRO.01"
    assert _published(world).constraint_code == "DES.02"


def test_the_prefix_locks_at_the_first_issuance_and_the_title_still_moves() -> None:
    """CM-BE-AC-021/022."""
    world = _world()
    category_id = world.category()
    world.service.update_category(
        principal_id=PRINCIPAL_A,
        category_id=category_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"prefix": "DSN"},
    )
    assert world.state.categories[(PRINCIPAL_A, category_id)].category.prefix == "DSN"
    _published(world)
    assert world.state.categories[(PRINCIPAL_A, category_id)].category.is_prefix_locked
    version = world.state.categories[(PRINCIPAL_A, category_id)].version
    with pytest.raises(ConstraintCategoryError) as caught:
        world.service.update_category(
            principal_id=PRINCIPAL_A,
            category_id=category_id,
            expected_version=version,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"prefix": "XYZ"},
        )
    assert caught.value.code == "category_prefix_locked"
    renamed = world.service.update_category(
        principal_id=PRINCIPAL_A,
        category_id=category_id,
        expected_version=version,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"title": "Design and Engineering", "display_order": 4},
    )
    assert renamed.record.title == "Design and Engineering"
    assert renamed.record.display_order == 4


# --- Version -----------------------------------------------------------------


def test_an_applied_mutation_advances_the_version_exactly_once() -> None:
    """CM-BE-AC-058."""
    world = _world()
    published = _published(world)
    updated = world.service.update(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"reference": "RFI-014"},
    )
    assert updated.record.version == published.version + 1
    assert (updated.receipt.before_version, updated.receipt.after_version) == (2, 3)


def test_a_no_op_writes_a_receipt_and_advances_nothing() -> None:
    """CM-BE-AC-059, first half."""
    world = _world()
    published = _published(world)
    same = world.service.transition_active(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        target_state=published.lifecycle_state,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert same.disposition is ConstraintMutationDisposition.NO_OP
    assert same.record.version == published.version
    assert same.receipt.outcome is ConstraintMutationOutcome.NO_OP
    assert same.receipt.revision_id is None
    assert world.service.__class__ is ConstraintManagementService
    assert [stored.version for _, stored in world.state.revisions] == [1, 2]


def test_a_stale_expected_version_is_rejected_and_the_rejection_is_still_recorded() -> None:
    """CM-BE-AC-059/060/061. The receipt commits; the mutation does not."""
    world = _world()
    published = _published(world)
    with pytest.raises(ConstraintVersionConflictError) as caught:
        world.service.update(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version - 1,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"reference": "RFI-014"},
        )
    receipt = caught.value.receipt
    assert receipt.outcome is ConstraintMutationOutcome.REJECTED
    assert receipt.before_version == receipt.after_version == published.version
    assert receipt.safe_failure_reason == "version_conflict"
    assert receipt.revision_id is None
    stored = world.state.constraints[(PRINCIPAL_A, published.constraint_id)]
    assert stored.version == published.version
    assert stored.reference is None
    assert receipt in _history(world, published.constraint_id)


def test_a_mutation_of_an_absent_or_foreign_constraint_is_the_same_refusal() -> None:
    """CM-BE-AC-132 consumed: Principal A cannot reach, or learn about, B's record."""
    world = _world()
    published = _published(world)
    with pytest.raises(ConstraintNotFoundError):
        world.service.update(
            principal_id=PRINCIPAL_B,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"reference": "peeking"},
        )
    with pytest.raises(ConstraintNotFoundError):
        world.service.update(
            principal_id=PRINCIPAL_B,
            constraint_id="cst_neverissuedaaaa0001",
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"reference": "peeking"},
        )
    assert world.state.constraints[(PRINCIPAL_A, published.constraint_id)].reference is None


# --- Idempotency -------------------------------------------------------------


def test_the_same_key_and_digest_replays_the_original_receipt_and_executes_nothing() -> None:
    """CM-BE-AC-065."""
    world = _world()
    published = _published(world)
    first = world.service.update(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"reference": "RFI-014"},
        idempotency_key="wp06-replay-key-0001",
    )
    second = world.service.update(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"reference": "RFI-014"},
        idempotency_key="wp06-replay-key-0001",
    )
    assert second.disposition is ConstraintMutationDisposition.REPLAYED
    assert second.receipt == first.receipt
    assert second.record.version == first.record.version
    assert len(_history(world, published.constraint_id)) == 3


def test_the_same_key_with_a_different_digest_conflicts_and_executes_nothing() -> None:
    """CM-BE-AC-066."""
    world = _world()
    published = _published(world)
    world.service.update(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"reference": "RFI-014"},
        idempotency_key="wp06-conflict-key-0001",
    )
    with pytest.raises(ConstraintIdempotencyConflictError):
        world.service.update(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"reference": "RFI-999"},
            idempotency_key="wp06-conflict-key-0001",
        )
    assert world.state.constraints[(PRINCIPAL_A, published.constraint_id)].reference == "RFI-014"


def test_a_replayed_publish_consumes_no_second_number() -> None:
    world = _world()
    draft = _draft(world)
    first = world.service.publish(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        idempotency_key="wp06-publish-key-0001",
    )
    again = world.service.publish(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        idempotency_key="wp06-publish-key-0001",
    )
    assert again.disposition is ConstraintMutationDisposition.REPLAYED
    assert again.record.constraint_code == first.record.constraint_code
    row = world.state.categories[(PRINCIPAL_A, world.category())]
    assert (row.next_sequence, row.issued_count) == (2, 1)


def test_a_key_that_is_not_a_well_formed_string_is_refused_by_type_not_truthiness() -> None:
    world = _world()
    published = _published(world)
    for bad in (1234567890, "short", "not a valid key"):
        with pytest.raises(ConstraintOperationError):
            world.service.update(
                principal_id=PRINCIPAL_A,
                constraint_id=published.constraint_id,
                expected_version=published.version,
                actor=ConstraintMutationActor.PRINCIPAL,
                values={"reference": "RFI-014"},
                idempotency_key=bad,  # type: ignore[arg-type]
            )


# --- Transitions -------------------------------------------------------------

_ACTIVE: Final = (
    ConstraintLifecycleState.IDENTIFIED,
    ConstraintLifecycleState.PENDING,
    ConstraintLifecycleState.IN_PROGRESS,
    ConstraintLifecycleState.ON_HOLD,
)


@pytest.mark.parametrize("target", _ACTIVE)
def test_every_active_to_active_transition_is_allowed(
    target: ConstraintLifecycleState,
) -> None:
    """CM-BE-AC-011. Same-state is the accepted no-op; the rest change."""
    world = _world()
    published = _published(world)
    result = world.service.transition_active(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        target_state=target,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert result.record.lifecycle_state is target
    expected = (
        ConstraintMutationDisposition.NO_OP
        if target is published.lifecycle_state
        else ConstraintMutationDisposition.APPLIED
    )
    assert result.disposition is expected


@pytest.mark.parametrize(
    "target",
    [
        ConstraintLifecycleState.DRAFT,
        ConstraintLifecycleState.CLOSED,
        ConstraintLifecycleState.VOID,
    ],
)
def test_a_transition_cannot_smuggle_a_named_operation(
    target: ConstraintLifecycleState,
) -> None:
    """CM-BE-AC-011/012/014. There is no generic status patch, by construction."""
    world = _world()
    published = _published(world)
    with pytest.raises(ConstraintLifecycleError) as caught:
        world.service.transition_active(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            target_state=target,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    assert caught.value.code in {
        "constraint_lifecycle_move_prohibited",
        "constraint_lifecycle_operation_mismatch",
    }
    assert world.state.constraints[(PRINCIPAL_A, published.constraint_id)].lifecycle_state is (
        published.lifecycle_state
    )


def test_a_draft_can_be_neither_closed_nor_voided() -> None:
    """CM-BE-AC-012."""
    world = _world()
    draft = _draft(world)
    with pytest.raises(ConstraintLifecycleError):
        world.service.close(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    with pytest.raises(ConstraintLifecycleError):
        world.service.void(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=1,
            actor=ConstraintMutationActor.PRINCIPAL,
            void_reason="not going ahead",
        )


# --- Close, Void, Reopen -----------------------------------------------------


def test_close_records_a_completion_date_and_no_void_fields() -> None:
    """CM-BE-AC-014/015."""
    world = _world()
    published = _published(world)
    result = world.service.close(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        closure_commentary="Stamped set issued.",
    )
    assert result.record.lifecycle_state is ConstraintLifecycleState.CLOSED
    assert result.record.completion_date == date(2026, 9, 2)
    assert result.record.closure_commentary == "Stamped set issued."
    assert result.record.voided_date is None
    assert result.record.void_reason is None
    assert result.receipt.operation is ConstraintMutationOperation.CLOSE


def test_close_accepts_an_explicit_completion_date() -> None:
    world = _world()
    published = _published(world)
    result = world.service.close(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        completion_date=date(2026, 8, 31),
    )
    assert result.record.completion_date == date(2026, 8, 31)


def test_void_requires_a_reason_records_a_date_and_never_a_completion() -> None:
    """CM-BE-AC-014/016."""
    world = _world()
    published = _published(world)
    with pytest.raises(ConstraintOperationError) as caught:
        world.service.void(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            void_reason="   ",
        )
    assert caught.value.code == "constraint_void_reason_blank"
    result = world.service.void(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        void_reason="Scope removed by owner.",
    )
    assert result.record.lifecycle_state is ConstraintLifecycleState.VOID
    assert result.record.voided_date == date(2026, 9, 2)
    assert result.record.void_reason == "Scope removed by owner."
    assert result.record.completion_date is None


@pytest.mark.parametrize("terminal", ["closed", "void"])
def test_reopen_clears_the_terminal_fields_and_leaves_the_revisions_alone(
    terminal: str,
) -> None:
    """CM-BE-AC-013/017. The current row moves; the immutable history does not."""
    world = _world()
    published = _published(world)
    if terminal == "closed":
        ended = world.service.close(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        ).record
    else:
        ended = world.service.void(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            void_reason="Superseded.",
        ).record
    terminal_revision = next(
        stored for _, stored in world.state.revisions if stored.version == ended.version
    )
    reopened = world.service.reopen(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        target_state=ConstraintLifecycleState.IN_PROGRESS,
        expected_version=ended.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        reason="The owner reinstated the scope.",
    )
    assert reopened.record.lifecycle_state is ConstraintLifecycleState.IN_PROGRESS
    assert reopened.record.completion_date is None
    assert reopened.record.closure_commentary is None
    assert reopened.record.voided_date is None
    assert reopened.record.void_reason is None
    assert reopened.receipt.operation is ConstraintMutationOperation.REOPEN
    unchanged = next(
        stored for _, stored in world.state.revisions if stored.version == ended.version
    )
    assert unchanged == terminal_revision


def test_reopen_is_refused_from_an_active_state_and_toward_a_terminal_one() -> None:
    world = _world()
    published = _published(world)
    with pytest.raises(ConstraintLifecycleError):
        world.service.reopen(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            target_state=ConstraintLifecycleState.PENDING,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    closed = world.service.close(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    ).record
    with pytest.raises(ConstraintLifecycleError):
        world.service.reopen(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            target_state=ConstraintLifecycleState.VOID,
            expected_version=closed.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )


# --- Bounded update ----------------------------------------------------------


def test_a_published_records_identity_is_immutable_and_its_required_fields_stay() -> None:
    """CM-BE-AC-004."""
    world = _world()
    published = _published(world)
    for values in ({"project_id": PROJECT_A}, {"category_id": world.category()}):
        with pytest.raises(ConstraintOperationError) as caught:
            world.service.update(
                principal_id=PRINCIPAL_A,
                constraint_id=published.constraint_id,
                expected_version=published.version,
                actor=ConstraintMutationActor.PRINCIPAL,
                values=values,
            )
        assert caught.value.code == "constraint_published_identity_immutable"
    with pytest.raises(ConstraintOperationError) as cleared:
        world.service.update(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            clear_fields=frozenset({"description"}),
        )
    assert cleared.value.code == "constraint_published_field_required"


def test_an_update_cannot_reach_a_field_outside_the_bounded_set() -> None:
    world = _world()
    published = _published(world)
    for values in ({"lifecycle_state": "closed"}, {"constraint_code": "DES.99"}, {"version": 9}):
        with pytest.raises(ConstraintOperationError) as caught:
            world.service.update(
                principal_id=PRINCIPAL_A,
                constraint_id=published.constraint_id,
                expected_version=published.version,
                actor=ConstraintMutationActor.PRINCIPAL,
                values=values,
            )
        assert caught.value.code == "constraint_update_field_unknown"


# --- Parties -----------------------------------------------------------------


def test_bic_and_responsible_are_separate_ordered_collections() -> None:
    """CM-BE-AC-029/030/032/033."""
    world = _world()
    published = _published(
        world,
        bic=(PRINCIPAL_PARTY, ENTITY_PARTY),
        responsible=(ENTITY_PARTY, UNRESOLVED_PARTY),
    )
    assert published.bic == (PRINCIPAL_PARTY, ENTITY_PARTY)
    assert published.responsible == (ENTITY_PARTY, UNRESOLVED_PARTY)
    assert not hasattr(published, "assignee")


def test_an_entity_party_must_be_in_this_principals_partition() -> None:
    """CM-BE-AC-035/037. By identifier, and never by anything that looks like a name."""
    world = _world()
    foreign = PartyRef(kind=PartyKind.ENTITY, entity_id=ENTITY_THEIRS, label="Their Vendor")
    with pytest.raises(ConstraintPartyError) as caught:
        world.service.create_draft(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            project_id=PROJECT_A,
            bic=(foreign,),
        )
    assert caught.value.code == "constraint_party_entity_unavailable"
    assert ENTITY_THEIRS not in str(caught.value)


def test_an_unresolved_party_keeps_its_wording_and_gains_no_identity() -> None:
    """CM-BE-AC-036."""
    world = _world()
    published = _published(world, bic=(PRINCIPAL_PARTY,), responsible=(UNRESOLVED_PARTY,))
    kept = published.responsible[0]
    assert kept.kind is PartyKind.UNRESOLVED
    assert kept.entity_id is None
    assert kept.label == "whoever signs the RFI"


# --- Categories --------------------------------------------------------------


def test_a_category_is_created_scoped_to_one_principal_and_one_project() -> None:
    """CM-BE-AC-019/020."""
    world = _world()
    result = world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="PRO",
        title="Procurement",
        actor=ConstraintMutationActor.PRINCIPAL,
        display_order=2,
    )
    assert result.record.category_id.startswith("ccat_")
    assert result.record.principal_id == PRINCIPAL_A
    assert result.record.project_id == PROJECT_A
    assert result.record.state is ConstraintCategoryState.ACTIVE
    assert result.receipt.before_version == 0
    assert result.receipt.after_version == 1
    with pytest.raises(ConstraintProjectUnavailableError):
        world.service.create_category(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_B,
            prefix="NOPE",
            title="Not mine",
            actor=ConstraintMutationActor.PRINCIPAL,
        )


def test_deactivating_a_category_retires_it_without_deleting_anything() -> None:
    """CM-BE-AC-023. There is no hard delete on the service at all."""
    world = _world()
    published = _published(world)
    result = world.service.deactivate_category(
        principal_id=PRINCIPAL_A,
        category_id=world.category(),
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert result.record.state is ConstraintCategoryState.INACTIVE
    assert (PRINCIPAL_A, world.category()) in world.state.categories
    assert (PRINCIPAL_A, published.constraint_id) in world.state.constraints
    assert not [name for name in dir(world.service) if "delete" in name or "remove" in name]
    again = world.service.deactivate_category(
        principal_id=PRINCIPAL_A,
        category_id=world.category(),
        expected_version=2,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert again.disposition is ConstraintMutationDisposition.NO_OP


def test_a_stale_category_version_is_rejected_and_recorded() -> None:
    world = _world()
    with pytest.raises(ConstraintCategoryVersionConflictError) as caught:
        world.service.update_category(
            principal_id=PRINCIPAL_A,
            category_id=world.category(),
            expected_version=99,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"title": "Nope"},
        )
    assert caught.value.receipts[0].outcome is ConstraintMutationOutcome.REJECTED
    assert world.state.categories[(PRINCIPAL_A, world.category())].category.title == "Design"


def test_a_reorder_is_one_atomic_operation_over_the_whole_project() -> None:
    """CM-BE-AC-022. One operation, one order, one transaction."""
    world = _world()
    for prefix, title in (("PRO", "Procurement"), ("PER", "Permitting")):
        world.service.create_category(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            prefix=prefix,
            title=title,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    ids = [category_id for (owner, category_id) in world.state.categories if owner == PRINCIPAL_A]
    reversed_ids = list(reversed(ids))
    result = world.service.reorder_categories(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        ordered_category_ids=reversed_ids,
        expected_versions=dict.fromkeys(ids, 1),
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    assert [record.category_id for record in result.records] == reversed_ids
    assert [record.display_order for record in result.records] == [0, 1, 2]
    assert len(result.receipts) == 3
    stored = {
        category_id: record.category.display_order
        for (owner, category_id), record in world.state.categories.items()
        if owner == PRINCIPAL_A
    }
    assert [stored[category_id] for category_id in reversed_ids] == [0, 1, 2]


def test_a_reorder_that_conflicts_on_one_member_changes_no_display_order() -> None:
    world = _world()
    world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="PRO",
        title="Procurement",
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    ids = [category_id for (owner, category_id) in world.state.categories if owner == PRINCIPAL_A]
    before = {
        category_id: record.category.display_order
        for (owner, category_id), record in world.state.categories.items()
        if owner == PRINCIPAL_A
    }
    with pytest.raises(ConstraintCategoryVersionConflictError):
        world.service.reorder_categories(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            ordered_category_ids=list(reversed(ids)),
            expected_versions={ids[0]: 1, ids[1]: 99},
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    after = {
        category_id: record.category.display_order
        for (owner, category_id), record in world.state.categories.items()
        if owner == PRINCIPAL_A
    }
    assert after == before


def test_a_partial_reorder_is_refused_rather_than_applied_to_the_part_it_named() -> None:
    world = _world()
    world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="PRO",
        title="Procurement",
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    with pytest.raises(ConstraintReorderError) as caught:
        world.service.reorder_categories(
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            ordered_category_ids=[world.category()],
            expected_versions={world.category(): 1},
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    assert caught.value.code == "constraint_category_reorder_is_not_the_whole_project"


def test_a_reorder_replays_on_the_same_key_and_digest() -> None:
    world = _world()
    world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="PRO",
        title="Procurement",
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    ids = sorted(
        category_id for (owner, category_id) in world.state.categories if owner == PRINCIPAL_A
    )
    order = list(reversed(ids))
    first = world.service.reorder_categories(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        ordered_category_ids=order,
        expected_versions=dict.fromkeys(ids, 1),
        actor=ConstraintMutationActor.PRINCIPAL,
        idempotency_key="wp06-reorder-key-0001",
    )
    again = world.service.reorder_categories(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        ordered_category_ids=order,
        expected_versions=dict.fromkeys(ids, 1),
        actor=ConstraintMutationActor.PRINCIPAL,
        idempotency_key="wp06-reorder-key-0001",
    )
    assert again.disposition is ConstraintMutationDisposition.REPLAYED
    assert [record.category_id for record in again.records] == order
    assert len(world.state.category_history) == len(first.receipts) + 2


# --- Close + Follow-up -------------------------------------------------------


def _follow_up(
    world: _World, **overrides: object
) -> tuple[ProjectConstraint, ConstraintFollowUpResult]:
    published = _published(world, bic=(PRINCIPAL_PARTY,), responsible=(UNRESOLVED_PARTY,))
    values: dict[str, Any] = {
        "principal_id": PRINCIPAL_A,
        "constraint_id": published.constraint_id,
        "expected_version": published.version,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "successor_description": "Re-issue the stamped set.",
    }
    values.update(overrides)
    return published, world.service.close_with_follow_up(**values)


def test_close_with_follow_up_closes_publishes_and_relates_in_one_operation() -> None:
    """CM-BE-AC-018. Six steps, one transaction, one authoritative result."""
    world = _world()
    published, result = _follow_up(world)
    assert result.disposition is ConstraintMutationDisposition.APPLIED
    assert result.predecessor.lifecycle_state is ConstraintLifecycleState.CLOSED
    assert result.predecessor.completion_date == date(2026, 9, 2)
    assert result.successor.constraint_id != published.constraint_id
    assert result.successor.lifecycle_state is ConstraintLifecycleState.IDENTIFIED
    assert result.successor.constraint_code == "DES.02"
    assert result.successor.project_id == published.project_id
    assert result.successor.category_id == published.category_id
    assert result.successor.description == "Re-issue the stamped set."
    assert result.successor.date_identified == date(2026, 9, 2)
    assert result.successor.due_date == date(2026, 9, 16)
    assert result.successor.bic == published.bic
    assert result.successor.responsible == published.responsible
    assert result.successor.reference is None
    assert result.successor.current_update is None
    edge = next(stored for _, stored in world.state.relationships)
    assert edge.source_constraint_id == result.successor.constraint_id
    assert edge.target_constraint_id == published.constraint_id
    assert edge.relationship_type.value == "follow_up_of"
    assert edge.created_by_history_id == result.successor_receipt.history_id


def test_close_with_follow_up_takes_an_explicit_category_and_due_date_override() -> None:
    world = _world()
    world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="PRO",
        title="Procurement",
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    other = next(
        category_id
        for (owner, category_id), record in world.state.categories.items()
        if owner == PRINCIPAL_A and record.category.prefix == "PRO"
    )
    _, result = _follow_up(world, successor_category_id=other, successor_due_date=date(2026, 10, 1))
    assert result.successor.category_id == other
    assert result.successor.constraint_code == "PRO.01"
    assert result.successor.due_date == date(2026, 10, 1)


def test_close_with_follow_up_requires_a_description() -> None:
    world = _world()
    published = _published(world)
    with pytest.raises(ConstraintOperationError) as caught:
        world.service.close_with_follow_up(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            successor_description="   ",
        )
    assert caught.value.code == "constraint_follow_up_description_blank"


@pytest.mark.parametrize(
    "stage",
    [
        "update_constraint",
        "insert_constraint",
        "insert_revision",
        "insert_history",
        "update_category",
        "insert_relationship",
    ],
)
def test_an_induced_failure_at_any_stage_of_close_with_follow_up_rolls_everything_back(
    stage: str,
) -> None:
    """Zero partial state: no closure, no successor, no number, no edge.

    The failure is induced at each write the operation performs in turn, which
    is the only way to show that the guarantee is the transaction's rather than
    the order the writes happen to be in.
    """
    world = _world()
    published = _published(world, bic=(PRINCIPAL_PARTY,))
    before_constraints = copy.deepcopy(world.state.constraints)
    before_category = copy.deepcopy(world.state.categories)
    before_history = len(world.state.history)
    before_revisions = len(world.state.revisions)
    world.state.fail_on = stage
    with pytest.raises(FakeIntegrityError):
        world.service.close_with_follow_up(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            successor_description="Re-issue the stamped set.",
        )
    assert world.state.constraints == before_constraints
    assert world.state.categories == before_category
    assert len(world.state.history) == before_history
    assert len(world.state.revisions) == before_revisions
    assert world.state.relationships == []


def test_a_stale_predecessor_version_leaves_the_whole_follow_up_unapplied() -> None:
    world = _world()
    published = _published(world)
    with pytest.raises(ConstraintVersionConflictError):
        world.service.close_with_follow_up(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version - 1,
            actor=ConstraintMutationActor.PRINCIPAL,
            successor_description="Re-issue the stamped set.",
        )
    stored = world.state.constraints[(PRINCIPAL_A, published.constraint_id)]
    assert stored.lifecycle_state is ConstraintLifecycleState.IDENTIFIED
    assert len(world.state.constraints) == 1
    assert world.state.relationships == []


def test_close_with_follow_up_replays_without_a_second_successor_or_number() -> None:
    world = _world()
    published = _published(world, bic=(PRINCIPAL_PARTY,))
    first = world.service.close_with_follow_up(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        successor_description="Re-issue the stamped set.",
        idempotency_key="wp06-followup-key-0001",
    )
    again = world.service.close_with_follow_up(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        successor_description="Re-issue the stamped set.",
        idempotency_key="wp06-followup-key-0001",
    )
    assert again.disposition is ConstraintMutationDisposition.REPLAYED
    assert again.successor.constraint_id == first.successor.constraint_id
    assert again.relationship_id == first.relationship_id
    assert len(world.state.constraints) == 2
    assert len(world.state.relationships) == 1
    row = world.state.categories[(PRINCIPAL_A, world.category())]
    assert (row.next_sequence, row.issued_count) == (3, 2)


def test_close_with_follow_up_conflicts_on_a_reused_key_with_different_content() -> None:
    world = _world()
    published = _published(world, bic=(PRINCIPAL_PARTY,))
    world.service.close_with_follow_up(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        successor_description="Re-issue the stamped set.",
        idempotency_key="wp06-followup-key-0002",
    )
    with pytest.raises(ConstraintIdempotencyConflictError):
        world.service.close_with_follow_up(
            principal_id=PRINCIPAL_A,
            constraint_id=published.constraint_id,
            expected_version=published.version,
            actor=ConstraintMutationActor.PRINCIPAL,
            successor_description="Something else entirely.",
            idempotency_key="wp06-followup-key-0002",
        )
    assert len(world.state.constraints) == 2


# --- The receipt ledger ------------------------------------------------------


def test_no_receipt_carries_a_prompt_or_an_unbounded_payload() -> None:
    """CM-BE-AC-067. The digest is a fixed hash; there is no payload column."""
    world = _world()
    published = _published(world)
    world.service.update(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"current_update": "x" * 5000},
        client_context="browser",
    )
    for _, entry in world.state.history:
        assert entry.request_digest is not None
        assert len(entry.request_digest) == 64
        assert not hasattr(entry, "payload")
        assert not hasattr(entry, "prompt")
        assert entry.client_context in {None, "browser"}


def test_every_applied_version_has_exactly_one_immutable_revision() -> None:
    """CM-BE-AC-062/064."""
    world = _world()
    published = _published(world)
    world.service.transition_active(
        principal_id=PRINCIPAL_A,
        constraint_id=published.constraint_id,
        target_state=ConstraintLifecycleState.IN_PROGRESS,
        expected_version=published.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    versions = sorted(stored.version for _, stored in world.state.revisions)
    assert versions == [1, 2, 3]
    applied = [
        entry
        for _, entry in world.state.history
        if entry.outcome is ConstraintMutationOutcome.APPLIED
    ]
    assert [(entry.before_version, entry.after_version) for entry in applied] == [
        (0, 1),
        (1, 2),
        (2, 3),
    ]
    assert all(entry.revision_id is not None for entry in applied)


def test_the_service_exposes_no_generic_status_setter() -> None:
    """§9.1: no generic set-status API may bypass the explicit operations."""
    public = {name for name in dir(ConstraintManagementService) if not name.startswith("_")}
    assert public == {
        "close",
        "close_with_follow_up",
        "create_category",
        "create_draft",
        "deactivate_category",
        "publish",
        "reopen",
        "reorder_categories",
        "transition_active",
        "update",
        "update_category",
        "void",
    }
