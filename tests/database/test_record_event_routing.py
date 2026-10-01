"""RECR-1: every listed event is resolvable from the event alone, on a real database.

Marked `database` (auto `database_clone`), routed to `database-current-head`.
Every write goes through `ApplicationService.invoke` -- the production writers,
on the production SQL units of work, with every plane composed -- and every
reread goes through the documented public read, keyed by the event's
`record_id` or, for a routed family, by its `routing_record_id`.

* **RECR-AC-003** `test_every_family_resolves_from_the_event_alone`, one case per
  family: the event a production writer committed is listed with the routing
  `RECORD_EVENT_ROUTING` names, and the documented read, called with
  `record_id` or `routing_record_id`, returns a record whose id is `record_id`.
  An affiliation is reread through its **person** end (MR-R05 (i),
  RECR-AC-021).
* **RECR-AC-020 / R-2** `test_an_orphaned_observation_lists_with_null_routing`:
  an observation with no Entity lists with both routing fields null, and is
  reachable only through the unkeyed `unresolved_only` scan.
* **RECR-AC-004** `test_routing_follows_a_merge_to_the_survivor`: after an
  Entity merge reparents an identifier, the identifier's earlier event routes
  to the survivor -- routing is the *current* owner (MR-R01).
* **RECR-AC-005** `test_remote_routing_is_the_events_own_visibility`: routing
  appears only on items the caller already sees, is identical local and
  remote, and a withheld item contributes none.
* **RECR-AC-008** `test_routing_is_read_by_the_page_statement`: the page,
  its routing and the watermark are one statement.
* `test_routing_never_reads_another_partition`: an owner lookup is scoped to the
  caller's partition, so a forged event naming another Principal's child routes
  nowhere (the RECR-AC-005 class; the M1c prove-red's target).

Every identity, name and text here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import event

from my_pa.application.commands import (
    AddEntityAddress,
    AddEntityAlias,
    AddEntityCommunicationMethod,
    AddEntityName,
    BindEntityIdentifier,
    ConfigureProjectControls,
    CreateCapture,
    CreateConstraintCategory,
    CreateConstraintDraft,
    CreateEntity,
    CreateEntityAffiliation,
    CreateEntityAssignment,
    CreateEntityParticipation,
    CreateEntityRelationship,
    CreateMeeting,
    CreateProject,
    CreateRelationshipMemory,
    CreateTask,
    CreateTaskComment,
    GetEntity,
    GetEntityProfile,
    GetEntityRelationships,
    GetRelationshipMemory,
    ListConstraintCategories,
    ListEntityAddresses,
    ListEntityAliases,
    ListEntityAssignments,
    ListEntityCommunicationMethods,
    ListEntityIdentifiers,
    ListEntityNames,
    ListEntityObservations,
    ListEntityParticipations,
    ListMeetings,
    ListTaskComments,
    MergeEntities,
    ObserveEntityMention,
    PreviewEntityMerge,
    ReadCapture,
    ReadCommitment,
    ReadConstraint,
    ReadMeeting,
    ReadProject,
    ReadProjectControlsStatus,
    ReadTask,
)
from my_pa.application.commitments import CommitmentManagementService
from my_pa.application.record_events import list_record_events
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.record_events import RecordEventItemView, RecordEventListView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.record_events import (
    RECORD_EVENT_ROUTING,
    RecordEventFamily,
    task_comment_record_event,
)
from my_pa.domain.relationship.authoring import CallerNamespace
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    AffiliationTypeCode,
    AliasType,
    AssignmentType,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    EntityRelationshipType,
    EntityType,
    NameTypeCode,
    ParticipationStatusCode,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
)
from my_pa.domain.relationship.governance import ObservationAuthority, ObservationKind
from my_pa.domain.relationship.memory import MemoryKind
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationActor
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.constraints import SqlAlchemyConstraintManagementUnitOfWork
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_task_record_events import LIMITS

pytestmark = pytest.mark.database

PRINCIPAL: Final = "prn_recrrouting00001"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
ALL: Final = frozenset(Capability)
F = RecordEventFamily


class Runtime:
    """`ApplicationService` with every plane this test writes or reads composed."""

    def __init__(self, url: str) -> None:
        self.engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.engine, audit=audit, relationship_memory_enabled=True)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            task_management_unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(self.engine),
            commitment_management_unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(
                self.engine
            ),
            constraint_management_unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(
                self.engine
            ),
            relationship_intelligence_enabled=True,
            relationship_intelligence_writes_enabled=True,
            relationship_memory_enabled=True,
            relationship_identity_correction_enabled=True,
        )

    def close(self) -> None:
        self.engine.dispose()
        self.audit_engine.dispose()

    def ok(self, command: Any, principal_id: str = PRINCIPAL) -> dict[str, Any]:  # noqa: ANN401
        capability = command.capability
        envelope: ResponseEnvelope = self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=sorted(permitted_purposes(capability))[0],
                principal_id=principal_id,
                requested_at=WHEN,
            ),
            command,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
        )
        assert envelope.error is None, (capability.value, envelope.error)
        dumped = envelope.to_canonical_dict()["result"]
        assert isinstance(dumped, dict)
        return dumped

    def listing(
        self, *, capability_grants: frozenset[tuple[Capability, Any]] | None = None
    ) -> RecordEventListView:
        with SqlAlchemyUnitOfWork(self.engine, audit=SqlAlchemyAuditSink(self.engine)) as uow:
            return list_record_events(
                uow.record_event_reader,
                principal_id=PRINCIPAL,
                available_capabilities=ALL,
                capability_grants=capability_grants,
                record_families=None,
                page_size=100,
                cursor=None,
            )


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def values_of(document: object, key: str) -> set[str]:
    """Every string value stored under `key`, anywhere in a nested result."""
    found: set[str] = set()
    if isinstance(document, dict):
        for name, value in document.items():
            if name == key and isinstance(value, str):
                found.add(value)
            found |= values_of(value, key)
    elif isinstance(document, list):
        for value in document:
            found |= values_of(value, key)
    return found


@dataclass
class World:
    """One of every family, written through the production writers."""

    ids: dict[RecordEventFamily, str]
    person: str
    organization: str
    project: str
    capture: dict[str, Any]


def build_world(rt: Runtime) -> World:
    ids: dict[RecordEventFamily, str] = {}
    task = rt.ok(
        CreateTask(
            title="Synthetic routing task",
            idempotency_key="recr-routing-task-0001",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        )
    )["task"]["task_id"]
    ids[F.TASK] = task
    ids[F.TASK_COMMENT] = rt.ok(
        CreateTaskComment(task_id=task, body="Synthetic note", idempotency_key="recr-comment-0001")
    )["comment"]["comment_id"]
    capture = rt.ok(
        CreateCapture(text="Synthetic routing capture", idempotency_key="recr-capture-0001")
    )
    ids[F.CAPTURE] = capture["capture_id"]
    # The production Commitment writer, on its own unit of work: the public
    # create also requires a legacy counterparty row this plane does not seed.
    commitments = CommitmentManagementService(
        unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(rt.engine),
        clock=lambda: WHEN,
    )
    ids[F.COMMITMENT] = commitments.create_commitment(
        principal_id=PRINCIPAL,
        counterparty_person_id="per_recrrouting0001",
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Send the synthetic report",
        origin_evidence_ref=capture["capture_id"],
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="recr-commitment-0001",
        source_capability="commitments.create",
    ).commitment.commitment_id
    project = rt.ok(CreateProject(name="Routing Tower", idempotency_key="recr-project-0001"))[
        "project_id"
    ]
    ids[F.PROJECT] = project
    rt.ok(
        ConfigureProjectControls(
            project_id=project, timezone_name="UTC", idempotency_key="recr-configure-0001"
        )
    )
    ids[F.PROJECT_CONTROLS_SETTINGS] = project
    category = rt.ok(
        CreateConstraintCategory(project_id=project, code_segment="RTG", title="Routing")
    )["category"]["category_id"]
    ids[F.CONSTRAINT_CATEGORY] = category
    ids[F.CONSTRAINT] = rt.ok(
        CreateConstraintDraft(
            project_id=project, category_id=category, description="Synthetic constraint"
        )
    )["constraint"]["constraint_id"]
    meeting = rt.ok(
        CreateMeeting(
            title="Synthetic sync",
            start_at=WHEN,
            timezone_name="UTC",
            idempotency_key="recr-meeting-0001",
            series_title="Synthetic series",
        )
    )["meeting"]
    ids[F.MEETING] = meeting["meeting_id"]
    ids[F.MEETING_SERIES] = meeting["meeting_series_id"]

    person_created = rt.ok(
        CreateEntity(
            entity_type=EntityType.PERSON,
            display_name="Pat Routing",
            idempotency_key="recr-person-0001",
        )
    )
    person = person_created["entity_id"]
    ids[F.ENTITY] = person
    organization = rt.ok(
        CreateEntity(
            entity_type=EntityType.ORGANIZATION,
            display_name="Routing Synthetic Ltd",
            idempotency_key="recr-organization-0001",
        )
    )["entity_id"]
    version = {"person": person_created["entity_version"], "organization": 1}

    def step(result: dict[str, Any]) -> str:
        """The child's id; and the person's version, which every child write advances."""
        for name, entity_id in (("person", person), ("organization", organization)):
            version[name] = rt.ok(GetEntity(entity_id=entity_id))["entity"]["version"]
        return str(result.get("record_id") or result["observation_id"])

    ids[F.ENTITY_IDENTIFIER] = step(
        rt.ok(
            BindEntityIdentifier(
                entity_id=person,
                expected_version=version["person"],
                namespace=CallerNamespace.EMAIL,
                display_value="pat.routing@example.invalid",
                idempotency_key="recr-identifier-0001",
            )
        )
    )
    ids[F.ENTITY_ALIAS] = step(
        rt.ok(
            AddEntityAlias(
                entity_id=person,
                expected_version=version["person"],
                alias_type=AliasType.INITIALS,
                display_value="PR",
                idempotency_key="recr-alias-0001",
            )
        )
    )
    ids[F.ENTITY_ASSIGNMENT] = step(
        rt.ok(
            CreateEntityAssignment(
                entity_id=person,
                expected_entity_version=version["person"],
                assignment_type=AssignmentType.EMPLOYMENT,
                scope_entity_id=organization,
                expected_scope_version=version["organization"],
                idempotency_key="recr-assignment-0001",
            )
        )
    )
    ids[F.ENTITY_RELATIONSHIP] = step(
        rt.ok(
            CreateEntityRelationship(
                from_entity_id=person,
                expected_from_version=version["person"],
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=organization,
                expected_to_version=version["organization"],
                idempotency_key="recr-relationship-0001",
            )
        )
    )
    ids[F.ENTITY_OBSERVATION] = step(
        rt.ok(
            ObserveEntityMention(
                kind=ObservationKind.USER_STATEMENT,
                authority=ObservationAuthority.USER_AUTHORED_STATEMENT,
                observed_value="Pat Routing",
                observed_at=WHEN,
                idempotency_key="recr-observation-0001",
                capture_id=capture["capture_id"],
                capture_version_id=capture["version_id"],
                entity_id=person,
                expected_entity_version=version["person"],
            )
        )
    )
    ids[F.ENTITY_NAME] = str(
        rt.ok(
            AddEntityName(
                entity_id=person,
                name_type_code=NameTypeCode.LEGAL,
                display_value="Patricia Routing",
                idempotency_key="recr-name-0001",
            )
        )["record_id"]
    )
    ids[F.ENTITY_ADDRESS] = str(
        rt.ok(
            AddEntityAddress(
                entity_id=person,
                address_type_code=AddressTypeCode.BUSINESS,
                raw_value="1 Synthetic Way",
                idempotency_key="recr-address-0001",
            )
        )["record_id"]
    )
    ids[F.ENTITY_COMMUNICATION_METHOD] = str(
        rt.ok(
            AddEntityCommunicationMethod(
                entity_id=person,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="pat.work@example.test",
                idempotency_key="recr-channel-0001",
            )
        )["record_id"]
    )
    ids[F.ENTITY_PROJECT_PARTICIPATION] = str(
        rt.ok(
            CreateEntityParticipation(
                participant_entity_id=person,
                project_display_name="Pat on Routing Tower",
                role_basis_code=RoleBasisCode.CONTRACTUAL,
                stakeholder_side_code=StakeholderSideCode.DESIGN,
                stakeholder_class_code=StakeholderClassCode.CORE,
                relationship_status_code=ParticipationStatusCode.ACTIVE,
                idempotency_key="recr-participation-0001",
                project_id=project,
            )
        )["record_id"]
    )
    ids[F.PERSON_ORGANIZATION_AFFILIATION] = str(
        rt.ok(
            CreateEntityAffiliation(
                person_entity_id=person,
                affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
                idempotency_key="recr-affiliation-0001",
                organization_entity_id=organization,
            )
        )["record_id"]
    )
    ids[F.RELATIONSHIP_MEMORY] = str(
        rt.ok(
            CreateRelationshipMemory(
                entity_id=person,
                statement="Pat prefers written closeout notes.",
                idempotency_key="recr-memory-0001",
                kind=MemoryKind.WORKING_PREFERENCE,
            )
        )["memory_id"]
    )
    return World(
        ids=ids, person=person, organization=organization, project=project, capture=capture
    )


#: Per family: the documented reread, given the key (record_id or routing id),
#: and the result key under which the record's own id appears.
REREADS: Final[dict[RecordEventFamily, tuple[Callable[[str], Any], str]]] = {
    F.TASK: (lambda key: ReadTask(task_id=key), "task_id"),
    F.COMMITMENT: (lambda key: ReadCommitment(commitment_id=key), "commitment_id"),
    F.PROJECT: (lambda key: ReadProject(project_id=key), "project_id"),
    F.ENTITY: (lambda key: GetEntity(entity_id=key), "entity_id"),
    F.ENTITY_IDENTIFIER: (lambda key: ListEntityIdentifiers(entity_id=key), "identifier_id"),
    F.ENTITY_ALIAS: (lambda key: ListEntityAliases(entity_id=key), "alias_id"),
    F.ENTITY_ASSIGNMENT: (
        lambda key: ListEntityAssignments(entity_id=key, active_only=False),
        "assignment_id",
    ),
    F.ENTITY_RELATIONSHIP: (
        lambda key: GetEntityRelationships(entity_id=key, direction="outgoing"),
        "relationship_id",
    ),
    F.ENTITY_OBSERVATION: (lambda key: ListEntityObservations(entity_id=key), "observation_id"),
    F.ENTITY_NAME: (lambda key: ListEntityNames(entity_id=key), "entity_name_id"),
    F.ENTITY_ADDRESS: (lambda key: ListEntityAddresses(entity_id=key), "entity_address_id"),
    F.ENTITY_COMMUNICATION_METHOD: (
        lambda key: ListEntityCommunicationMethods(entity_id=key),
        "communication_method_id",
    ),
    F.ENTITY_PROJECT_PARTICIPATION: (
        lambda key: ListEntityParticipations(entity_id=key, perspective="participant"),
        "participation_id",
    ),
    # MR-R05 (i): the person end; bounded at 25 per collection (residual R-1).
    F.PERSON_ORGANIZATION_AFFILIATION: (
        lambda key: GetEntityProfile(entity_id=key),
        "affiliation_id",
    ),
    F.RELATIONSHIP_MEMORY: (lambda key: GetRelationshipMemory(memory_id=key), "memory_id"),
    F.CONSTRAINT: (lambda key: ReadConstraint(constraint_id=key), "constraint_id"),
    F.CONSTRAINT_CATEGORY: (
        lambda key: ListConstraintCategories(project_id=key),
        "category_id",
    ),
    F.PROJECT_CONTROLS_SETTINGS: (
        lambda key: ReadProjectControlsStatus(project_id=key),
        "project_id",
    ),
    F.MEETING: (lambda key: ReadMeeting(meeting_id=key), "meeting_id"),
    F.MEETING_SERIES: (lambda key: ListMeetings(meeting_series_id=key), "meeting_series_id"),
    F.CAPTURE: (lambda key: ReadCapture(capture_id=key), "capture_id"),
    F.TASK_COMMENT: (lambda key: ListTaskComments(task_id=key), "comment_id"),
}


def expected_owner(world: World, family: RecordEventFamily) -> str:
    """The owner a routed event must name, from the world that wrote it."""
    if family is F.TASK_COMMENT:
        return world.ids[F.TASK]
    if family is F.CONSTRAINT_CATEGORY:
        return world.project
    return world.person


def event_for(
    view: RecordEventListView, family: RecordEventFamily, record_id: str
) -> RecordEventItemView:
    matches = [
        item for item in view.events if item.record_family is family and item.record_id == record_id
    ]
    assert matches, (family, record_id, [(i.record_family.value, i.record_id) for i in view.events])
    return matches[0]


# ---- RECR-AC-003 / 021 ---------------------------------------------------------------


@pytest.mark.parametrize("family", list(RecordEventFamily), ids=lambda family: family.value)
def test_every_family_resolves_from_the_event_alone(
    runtime: Runtime, family: RecordEventFamily
) -> None:
    world = build_world(runtime)
    item = event_for(runtime.listing(), family, world.ids[family])
    routed = RECORD_EVENT_ROUTING.get(family)
    if routed is None:
        assert (item.routing_family, item.routing_record_id) == (None, None)
        key = item.record_id
    else:
        assert item.routing_family is routed
        assert item.routing_record_id == expected_owner(world, family)
        assert item.routing_record_id is not None
        key = item.routing_record_id
    build, id_key = REREADS[family]
    assert item.record_id in values_of(runtime.ok(build(key)), id_key), (family, key)
    if family is F.PERSON_ORGANIZATION_AFFILIATION:
        # RECR-AC-021: the person end, never the organization's.
        assert item.routing_record_id == world.person
        assert world.person != world.organization


# ---- RECR-AC-020 / R-2 ------------------------------------------------------------------


def test_an_orphaned_observation_lists_with_null_routing(runtime: Runtime) -> None:
    """MR-R05 (ii): no owner, so no routing: "not currently resolvable"."""
    capture = runtime.ok(
        CreateCapture(text="Synthetic orphan capture", idempotency_key="recr-orphan-capture")
    )
    observed = runtime.ok(
        ObserveEntityMention(
            kind=ObservationKind.USER_STATEMENT,
            authority=ObservationAuthority.USER_AUTHORED_STATEMENT,
            observed_value="Quorra Unmatchedname",
            observed_at=WHEN,
            idempotency_key="recr-orphan-observation",
            capture_id=capture["capture_id"],
            capture_version_id=capture["version_id"],
        )
    )
    assert observed["entity_id"] is None
    item = event_for(runtime.listing(), F.ENTITY_OBSERVATION, observed["observation_id"])
    assert item.routing_family is None
    assert item.routing_record_id is None
    # R-2: the only path to it is the unkeyed scan of unresolved observations.
    scan = runtime.ok(ListEntityObservations(unresolved_only=True))
    assert observed["observation_id"] in values_of(scan, "observation_id")


# ---- RECR-AC-004 ---------------------------------------------------------------------


def test_routing_follows_a_merge_to_the_survivor(runtime: Runtime) -> None:
    """MR-R01: routing is read at list time, so it names the *current* owner."""
    survivor = runtime.ok(
        CreateEntity(
            entity_type=EntityType.PERSON,
            display_name="Morgan Survivor",
            idempotency_key="recr-merge-survivor",
        )
    )["entity_id"]
    absorbed = runtime.ok(
        CreateEntity(
            entity_type=EntityType.PERSON,
            display_name="Morgan Absorbed",
            idempotency_key="recr-merge-absorbed",
        )
    )["entity_id"]
    identifier = runtime.ok(
        BindEntityIdentifier(
            entity_id=absorbed,
            expected_version=1,
            namespace=CallerNamespace.EMAIL,
            display_value="morgan.absorbed@example.invalid",
            idempotency_key="recr-merge-identifier",
        )
    )["record_id"]
    before = event_for(runtime.listing(), F.ENTITY_IDENTIFIER, identifier)
    assert before.routing_record_id == absorbed

    def version(entity_id: str) -> int:
        return int(runtime.ok(GetEntity(entity_id=entity_id))["entity"]["version"])

    preview = runtime.ok(
        PreviewEntityMerge(
            survivor_entity_id=survivor,
            expected_survivor_version=version(survivor),
            merged_away=({"entity_id": absorbed, "expected_version": version(absorbed)},),
            reason="Synthetic duplicate person for the routing test.",
        )
    )
    runtime.ok(
        MergeEntities(
            preview_id=preview["preview_id"],
            preview_digest=preview["preview_token"],
            reason="Synthetic duplicate person for the routing test.",
        )
    )
    after = [
        item
        for item in runtime.listing().events
        if item.record_family is F.ENTITY_IDENTIFIER and item.record_id == identifier
    ]
    assert after, "the identifier's events are still listed"
    # The earliest event -- written while the absorbed entity owned it -- now
    # routes to the survivor, and so does every later one.
    assert after[0].event_id == before.event_id
    assert {item.routing_record_id for item in after} == {survivor}
    assert identifier in values_of(
        runtime.ok(ListEntityIdentifiers(entity_id=survivor)), "identifier_id"
    )


# ---- RECR-AC-005 ---------------------------------------------------------------------


def _grants(*capabilities: Capability) -> frozenset[tuple[Capability, Any]]:
    return frozenset(
        (capability, next(iter(permitted_purposes(capability)))) for capability in capabilities
    )


def test_remote_routing_is_the_events_own_visibility(runtime: Runtime) -> None:
    world = build_world(runtime)
    local = runtime.listing()
    local_routing = {item.event_id: item.routing_record_id for item in local.events}
    # A comment-only remote caller: it sees comments (routed to their Task) and
    # nothing else -- not the Task, and no Entity-plane child.
    remote = runtime.listing(capability_grants=_grants(Capability.TASKS_COMMENTS_LIST))
    assert {item.record_family for item in remote.events} == {F.TASK_COMMENT}
    for item in remote.events:
        assert item.routing_record_id == local_routing[item.event_id] == world.ids[F.TASK]
    # The entity floor withholds every Entity-plane child from a caller holding
    # only their list reads; none of their routing reaches it.
    floorless = runtime.listing(
        capability_grants=_grants(
            Capability.ENTITIES_IDENTIFIERS_LIST, Capability.ENTITIES_ALIASES_LIST
        )
    )
    assert floorless.events == ()
    assert world.person not in {item.routing_record_id for item in floorless.events}
    # With the floor, the same children appear with the same routing as locally.
    floored = runtime.listing(
        capability_grants=_grants(
            Capability.ENTITIES_GET,
            Capability.ENTITIES_IDENTIFIERS_LIST,
            Capability.ENTITIES_ALIASES_LIST,
        )
    )
    routed = [item for item in floored.events if item.routing_family is not None]
    assert {item.record_family for item in routed} == {F.ENTITY_IDENTIFIER, F.ENTITY_ALIAS}
    for item in routed:
        assert item.routing_record_id == local_routing[item.event_id] == world.person


# ---- RECR-AC-008 ---------------------------------------------------------------------


def test_routing_is_read_by_the_page_statement(runtime: Runtime) -> None:
    """G1-TX-004 kept: the page, its routing and the watermark are one statement."""
    build_world(runtime)
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *_: Any) -> None:  # noqa: ANN401
        if "record_events" in statement:
            statements.append(statement)

    event.listen(runtime.engine, "before_cursor_execute", record)
    try:
        view = runtime.listing()
    finally:
        event.remove(runtime.engine, "before_cursor_execute", record)
    assert any(item.routing_record_id is not None for item in view.events)
    (page,) = statements
    assert "routing_record_id" in page
    assert "high_watermark_event_id" in page
    assert "task_comments" in page


def test_routing_never_reads_another_partition(runtime: Runtime) -> None:
    """Each owner lookup is scoped to the caller's partition (`partition_criterion`).

    Keys are unique, so only a forged event can name another Principal's child;
    this one is fixture-written onto the production stager, and its routing
    stays null rather than disclosing the other Principal's Task.
    """
    other = issue_identifier(IdKind.PRINCIPAL)
    foreign_task = runtime.ok(
        CreateTask(
            title="Another principal's task",
            idempotency_key="recr-foreign-task-0001",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        ),
        principal_id=other,
    )["task"]["task_id"]
    foreign_comment = runtime.ok(
        CreateTaskComment(
            task_id=foreign_task, body="Not yours", idempotency_key="recr-foreign-comment"
        ),
        principal_id=other,
    )["comment"]["comment_id"]
    with SqlAlchemyUnitOfWork(runtime.engine, audit=SqlAlchemyAuditSink(runtime.engine)) as uow:
        uow.record_events.stage(
            task_comment_record_event(
                principal_id=PRINCIPAL,
                comment_id=foreign_comment,
                actor=TaskMutationActor.PRINCIPAL,
                capability="tasks.comments.create",
                occurred_at=WHEN,
                correlation_id=None,
            )
        )
    item = event_for(runtime.listing(), F.TASK_COMMENT, foreign_comment)
    assert (item.routing_family, item.routing_record_id) == (None, None)
    assert foreign_task not in {listed.routing_record_id for listed in runtime.listing().events}
