"""One authorization path, and the negative evidence `P05-SPEC-AC-002` asks for.

Two claims are made here, and they are different in kind.

**Structural.** `ApplicationService` exposes one public method. A use case is a
private method reached only through the dispatch table `invoke` consults *after*
`authorize` has returned an allowed decision, so there is no call a caller can
make that performs a capability without a decision. The first test asserts the
surface, because that is what makes the second set of tests exhaustive rather
than a sample.

**Behavioural.** Every capability is then invoked with an unauthorized request
and required to be denied — not one capability, every one of them, and for each of the
four ways authority can be missing. A capability that grew a bypass would fail
its own row here.

The negative evidence follows the same rule. `P05-SPEC-AC-002` names traversal,
source mutation, unknown scope, and purpose escalation; each is proved once at
the layer that decides it, against the real fixture provider where a provider is
involved. WP-4B re-proves them through each transport, which is a different
claim — that no transport can route around this layer — and not a repeat of this
one.

The source-mutation case is worth being exact about, because "prove a mutation
is refused" has no request to send: there is no mutating capability to invoke and
no mutating method on the port to call. So it is proved twice from the other
direction — the port's own surface holds no such method, and every capability run
against a recording provider is shown to have called nothing but the three
read-only ones. A handler that grew a write would have to grow the method first,
and both halves would fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeProviders,
    FakeUnitOfWork,
    Scene,
    World,
    build_provider,
    build_service,
    metadata_for,
    operator,
    staged_capture,
    staged_search,
)

from my_pa.application.commands import (
    ApplyTaskBulk,
    Command,
    CreateCapture,
    CreateCommitment,
    CreateTask,
    DecideReviewCase,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetSourceMetadata,
    GetSourceStatus,
    ListCaptures,
    ListCommitments,
    ListReviewCases,
    ListSources,
    ListTasks,
    PreviewTaskBulk,
    ReadCapture,
    ReadKnowledge,
    ReadTask,
    ReadTaskHistory,
    ReviseCapture,
    SearchCaptures,
    SearchKnowledge,
    SearchTasks,
    TasksAttention,
    TasksWaitingOn,
    TransitionTask,
    UpdateTask,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.audit.events import AuditOutcome
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import DenialReason
from my_pa.domain.source.provider import SourceProvider
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.tasks.models import CommitmentDirection, TaskState


def commands_for(scene: Scene) -> dict[Capability, Command]:
    """One well-formed command per capability, all naming `scene`'s own scope.

    Built from the scene so that the *only* thing wrong in a denial test is the
    authority: a command that named a malformed identifier would be refused as
    an invalid request and would prove nothing about the policy path.
    """
    return {
        Capability.CAPABILITIES_GET: GetCapabilities(),
        Capability.SOURCES_LIST: ListSources(source_id=scene.source.source_id),
        Capability.SOURCES_METADATA: GetSourceMetadata(
            source_id=scene.source.source_id,
            source_object_id=scene.markdown.source_object_id,
        ),
        Capability.SOURCES_FETCH: FetchSource(
            source_id=scene.source.source_id,
            source_object_id=scene.markdown.source_object_id,
        ),
        Capability.SOURCES_STATUS: GetSourceStatus(source_id=scene.source.source_id),
        Capability.SOURCES_ENROLL: EnrollSource(
            source_id=scene.source.source_id,
            media_types=("text/markdown",),
            idempotency_key="denial-probe-0001",
            object_ids=(scene.markdown.source_object_id,),
        ),
        Capability.KNOWLEDGE_SEARCH: SearchKnowledge(
            enrollment_id=scene.enrollment.enrollment_id, query="revenue"
        ),
        Capability.KNOWLEDGE_READ: ReadKnowledge(
            knowledge_id=issue_identifier(IdKind.KNOWLEDGE),
            enrollment_id=scene.enrollment.enrollment_id,
        ),
        # The capture commands name no source and no enrollment, because a
        # capture belongs to neither. Their identifiers are minted rather than
        # taken from the scene for the same reason the knowledge identifier
        # above is: every test here refuses before a handler runs, so what the
        # identifier names is irrelevant and its *shape* is not.
        Capability.CAPTURE_CREATE: CreateCapture(
            text="a synthetic note", idempotency_key="denial-probe-capture-0001"
        ),
        Capability.CAPTURE_REVISE: ReviseCapture(
            capture_id=issue_identifier(IdKind.CAPTURE),
            text="a synthetic note, revised",
            idempotency_key="denial-probe-capture-0002",
        ),
        Capability.CAPTURE_READ: ReadCapture(capture_id=issue_identifier(IdKind.CAPTURE)),
        Capability.CAPTURE_LIST: ListCaptures(),
        Capability.CAPTURE_SEARCH: SearchCaptures(query="synthetic"),
        Capability.REVIEW_LIST: ListReviewCases(),
        Capability.REVIEW_DECIDE: DecideReviewCase(
            review_case_id=issue_identifier(IdKind.REVIEW_CASE),
            expected_review_version=0,
            disposition=Disposition.REJECT,
        ),
        Capability.TASKS_READ: ReadTask(task_id=issue_identifier(IdKind.TASK)),
        Capability.TASKS_LIST: ListTasks(),
        Capability.TASKS_SEARCH: SearchTasks(query="synthetic"),
        Capability.TASKS_HISTORY: ReadTaskHistory(task_id=issue_identifier(IdKind.TASK)),
        Capability.TASKS_ATTENTION: TasksAttention(),
        Capability.TASKS_CREATE: CreateTask(
            title="denial probe", idempotency_key="denial-task-0001"
        ),
        Capability.TASKS_UPDATE: UpdateTask(
            task_id=issue_identifier(IdKind.TASK),
            expected_version=1,
            idempotency_key="denial-task-0002",
        ),
        Capability.TASKS_TRANSITION: TransitionTask(
            task_id=issue_identifier(IdKind.TASK),
            expected_version=1,
            idempotency_key="denial-task-0003",
            target_state=TaskState.COMPLETED,
        ),
        Capability.TASKS_PREVIEW: PreviewTaskBulk(
            operation="reschedule",
            task_ids=(issue_identifier(IdKind.TASK),),
            expected_versions=(1,),
        ),
        Capability.TASKS_BULK: ApplyTaskBulk(
            preview_token=issue_identifier(IdKind.BULK_PREVIEW),
            idempotency_key="denial-task-0004",
        ),
        Capability.TASKS_WAITING_ON: TasksWaitingOn(),
        Capability.COMMITMENTS_CREATE: CreateCommitment(
            counterparty_person_id=issue_identifier(IdKind.PERSON),
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            summary="denial probe",
            idempotency_key="denial-cmt-0001",
        ),
        Capability.COMMITMENTS_LIST: ListCommitments(),
    }


def a_permitted_purpose(capability: Capability) -> Purpose:
    """One purpose the domain permits for `capability`."""
    return sorted(permitted_purposes(capability))[0]


def a_forbidden_purpose(capability: Capability) -> Purpose:
    """One purpose the domain does *not* permit for `capability`.

    Derived from the domain rule rather than listed, so a change to the
    capability-to-purpose binding cannot leave this test asserting an escalation
    that is no longer one.
    """
    permitted = permitted_purposes(capability)
    return next(purpose for purpose in sorted(Purpose) if purpose not in permitted)


def invoke(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    purpose: Purpose,
    command: Command,
) -> ResponseEnvelope:
    return service.invoke(
        metadata_for(capability, purpose, principal), command, principal=principal
    )


ALL_CAPABILITIES = list(Capability)

#: The family whose claim is a zero — a capture reaches no source provider at
#: all — and which therefore has no non-vacuity control of its own.
CAPTURE_CAPABILITIES = frozenset(c for c in Capability if c.value.startswith("capture."))


def test_the_service_offers_exactly_one_public_entry_point() -> None:
    """The structural claim every behavioural test below rests on.

    If a second public method appeared — a per-capability convenience, an
    "internal" variant, a handler exposed for a transport's benefit — this fails,
    and the exhaustiveness of the denial matrix stops being exhaustive.
    """
    public = sorted(name for name in dir(ApplicationService) if not name.startswith("_"))
    assert public == ["invoke"], f"ApplicationService gained a second door: {public}"


@pytest.mark.parametrize("capability", ALL_CAPABILITIES, ids=lambda c: c.value)
def test_every_capability_is_denied_to_an_unauthenticated_principal(
    scene: Scene, capability: Capability
) -> None:
    unauthenticated = Principal(
        principal_id=scene.principal.principal_id,
        kind=PrincipalKind.OPERATOR,
        authenticated=False,
    )
    service = build_service(scene.world, scene.providers)
    envelope = invoke(
        service,
        unauthenticated,
        capability,
        a_permitted_purpose(capability),
        commands_for(scene)[capability],
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert scene.world.audit[-1].denial_reason is DenialReason.PRINCIPAL_NOT_AUTHENTICATED


@pytest.mark.parametrize("capability", ALL_CAPABILITIES, ids=lambda c: c.value)
def test_every_capability_is_denied_to_a_principal_that_cannot_hold_authority(
    scene: Scene, capability: Capability
) -> None:
    """A model gateway is authenticated and still cannot act (`ACT-PKL-007`)."""
    model = Principal(
        principal_id=scene.principal.principal_id,
        kind=PrincipalKind.LOCAL_MODEL_GATEWAY,
        authenticated=True,
    )
    service = build_service(scene.world, scene.providers)
    envelope = invoke(
        service,
        model,
        capability,
        a_permitted_purpose(capability),
        commands_for(scene)[capability],
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert scene.world.audit[-1].denial_reason is DenialReason.PRINCIPAL_MAY_NOT_HOLD_AUTHORITY


@pytest.mark.parametrize("capability", ALL_CAPABILITIES, ids=lambda c: c.value)
def test_every_capability_refuses_a_purpose_it_does_not_permit(
    scene: Scene, capability: Capability
) -> None:
    """Purpose escalation, one row per capability (`P05-SPEC-AC-002`)."""
    service = build_service(scene.world, scene.providers)
    envelope = invoke(
        service,
        scene.principal,
        capability,
        a_forbidden_purpose(capability),
        commands_for(scene)[capability],
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert scene.world.audit[-1].denial_reason is DenialReason.PURPOSE_NOT_PERMITTED_FOR_CAPABILITY


#: Capabilities whose authority is a held scope.
#:
#: `sources.enroll` is the operation that *grants* scope, so requiring the scope
#: to be held already would make it permanently unusable —
#: `domain.policy.decision._scope_is_authorized` says so, and its authority is
#: the operator-only check instead, which has its own row below.
#:
#: The rest carry no source scope at all: `capabilities.get` describes the
#: interface, and the four capture capabilities read and write a product-owned
#: record that `ADR-003` makes a third authority class — it belongs to no
#: configured source and to no enrollment. **This set widens as capture is
#: added; it does not weaken**, because every excluded capability is excluded by
#: a property the domain states, and the guard below re-derives every partition
#: from `evaluate` rather than from this list.
SCOPED_CAPABILITIES = [
    c
    for c in Capability
    if c
    not in {
        Capability.CAPABILITIES_GET,
        Capability.SOURCES_ENROLL,
        Capability.CAPTURE_CREATE,
        Capability.CAPTURE_REVISE,
        Capability.CAPTURE_READ,
        Capability.CAPTURE_LIST,
        Capability.CAPTURE_SEARCH,
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
        Capability.TASKS_READ,
        Capability.TASKS_LIST,
        Capability.TASKS_SEARCH,
        Capability.TASKS_HISTORY,
        Capability.TASKS_ATTENTION,
        Capability.TASKS_CREATE,
        Capability.TASKS_UPDATE,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_PREVIEW,
        Capability.TASKS_BULK,
        Capability.TASKS_WAITING_ON,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_LIST,
    }
]


@pytest.mark.parametrize("capability", SCOPED_CAPABILITIES, ids=lambda c: c.value)
def test_every_scoped_capability_refuses_a_scope_the_principal_does_not_hold(
    scene: Scene, capability: Capability
) -> None:
    """Unknown scope, one row per capability (`P05-SPEC-AC-002`).

    The principal here holds no enrollment at all, so every scoped request names
    a scope it does not have — and an unknown source is denied with the same
    answer as one that exists and is not granted, which is what section 10
    requires of a denial.
    """
    stranger = operator()
    service = build_service(scene.world, scene.providers)
    envelope = invoke(
        service,
        stranger,
        capability,
        a_permitted_purpose(capability),
        commands_for(scene)[capability],
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert scene.world.audit[-1].denial_reason is DenialReason.SCOPE_NOT_AUTHORIZED


def _decision(capability: Capability, requested: frozenset[str], held: frozenset[str]) -> bool:
    """Ask `evaluate` rather than read its source, so this reflects the rule."""
    from my_pa.domain.policy.decision import PolicyRequest, evaluate

    return evaluate(
        PolicyRequest(
            principal=operator(),
            purpose=a_permitted_purpose(capability),
            capability=capability,
            requested_source_ids=requested,
            authorized_source_ids=held,
        )
    ).allowed


def test_the_capabilities_outside_the_scope_matrix_are_the_domains_own() -> None:
    """Guard the exclusions above, which would otherwise narrow the matrix silently.

    A capability dropped from `SCOPED_CAPABILITIES` for convenience would lose
    its unknown-scope row and nothing would say so. Every excluded capability is
    excluded because the domain treats it specially, and each partition below is
    re-derived from `evaluate` rather than read off the list it is guarding —
    which is what makes this a check on the domain rather than a restatement of
    the exclusion.
    """
    scopeless_capabilities = {
        Capability.CAPABILITIES_GET,
        Capability.CAPTURE_CREATE,
        Capability.CAPTURE_REVISE,
        Capability.CAPTURE_READ,
        Capability.CAPTURE_LIST,
        Capability.CAPTURE_SEARCH,
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
        Capability.TASKS_READ,
        Capability.TASKS_LIST,
        Capability.TASKS_SEARCH,
        Capability.TASKS_HISTORY,
        Capability.TASKS_ATTENTION,
        Capability.TASKS_CREATE,
        Capability.TASKS_UPDATE,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_PREVIEW,
        Capability.TASKS_BULK,
        Capability.TASKS_WAITING_ON,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_LIST,
    }
    excluded = set(Capability) - set(SCOPED_CAPABILITIES)
    assert excluded == {Capability.SOURCES_ENROLL, *scopeless_capabilities}

    unheld = frozenset({issue_identifier(IdKind.SOURCE)})
    granting = {c for c in Capability if _decision(c, unheld, frozenset())}
    assert granting == {Capability.SOURCES_ENROLL}, (
        "exactly one capability may name a scope it does not hold: the one that grants scope"
    )

    scopeless = {c for c in Capability if _decision(c, frozenset(), frozenset())}
    assert scopeless == scopeless_capabilities, (
        "the capabilities carrying no source scope are the interface description "
        "and the capture plane, which belongs to no source"
    )


def test_the_operator_only_capability_is_refused_to_a_gateway_principal(
    scene: Scene,
) -> None:
    gateway = Principal(
        principal_id=scene.principal.principal_id,
        kind=PrincipalKind.GATEWAY,
        authenticated=True,
    )
    service = build_service(scene.world, scene.providers)
    envelope = invoke(
        service,
        gateway,
        Capability.SOURCES_ENROLL,
        Purpose.BOUNDED_ENROLLMENT,
        commands_for(scene)[Capability.SOURCES_ENROLL],
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert scene.world.audit[-1].denial_reason is DenialReason.OPERATOR_REQUIRED


def test_a_denial_is_audited_and_its_transaction_commits(scene: Scene) -> None:
    """The record of a refusal must survive the refusal.

    A denial that raised out of the transaction would roll its own audit event
    back, which is exactly the case `AGENTS.md` section 5 asks to be recorded.
    """
    service = build_service(scene.world, scene.providers)
    invoke(
        service,
        scene.principal,
        Capability.KNOWLEDGE_SEARCH,
        Purpose.SOURCE_INSPECTION,
        commands_for(scene)[Capability.KNOWLEDGE_SEARCH],
    )
    assert scene.world.commits == 1
    assert scene.world.rollbacks == 0
    assert len(scene.world.audit) == 1
    assert scene.world.audit[0].outcome is AuditOutcome.DENIED


def test_an_allowed_request_is_audited_as_allowed(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    invoke(
        service,
        scene.principal,
        Capability.SOURCES_LIST,
        Purpose.SOURCE_INSPECTION,
        commands_for(scene)[Capability.SOURCES_LIST],
    )
    assert scene.world.audit[0].outcome is AuditOutcome.ALLOWED
    assert scene.world.audit[0].denial_reason is None
    assert scene.world.audit[0].capability is Capability.SOURCES_LIST


def test_a_failing_handler_rolls_its_transaction_back(scene: Scene) -> None:
    """A partial enrollment must not commit because its queueing failed."""
    from my_pa.contracts.ports import RepositoryFailureError

    scene.world.failures["enqueue"] = RepositoryFailureError("the queue is broken")
    service = build_service(scene.world, scene.providers)
    envelope = invoke(
        service,
        scene.principal,
        Capability.SOURCES_ENROLL,
        Purpose.BOUNDED_ENROLLMENT,
        commands_for(scene)[Capability.SOURCES_ENROLL],
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INTERNAL_ERROR
    assert scene.world.rollbacks == 1
    assert scene.world.commits == 0


def test_a_denial_carries_no_reason_into_the_public_error(scene: Scene) -> None:
    """The reason belongs in the audit trail, not in the answer.

    A caller told `scope_not_authorized` rather than `operator_required` could
    subtract one from the other to learn whether a source exists.
    """
    service = build_service(scene.world, scene.providers)
    envelope = invoke(
        service,
        operator(),
        Capability.SOURCES_LIST,
        Purpose.SOURCE_INSPECTION,
        commands_for(scene)[Capability.SOURCES_LIST],
    )
    assert envelope.error is not None
    rendered = envelope.error.model_dump_json()
    for reason in DenialReason:
        assert reason.value not in rendered


# ---- traversal denial ------------------------------------------------------


def test_a_traversal_attempt_is_denied_with_the_typed_error(world: World, tmp_path: Path) -> None:
    """A contained object replaced by a symlink out of the root is refused.

    The identifier was issued while the object was inside the root, which is the
    only way an escaping object can have one at all — the provider omits an
    unresolvable entry from a listing rather than naming it. Containment is then
    re-proved immediately before the read, and this is what that catches.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"# Secret\n\nOUTSIDE-THE-ROOT\n")
    root = tmp_path / "root"
    root.mkdir()
    decoy = root / "doc.md"
    decoy.write_bytes(b"# Doc\n\ninside\n")

    principal = operator()
    source = world.add_source()
    provider = build_provider(root, source.source_id)
    entry = next(iter(provider.list_children()))
    enrollment = world.add_enrollment(
        source_id=source.source_id,
        principal_id=principal.principal_id,
        object_ids=(entry.source_object_id,),
    )
    assert enrollment.enrollment_id

    decoy.unlink()
    decoy.symlink_to(outside / "secret.md")

    world.providers = FakeProviders({source.source_id: provider})
    service = ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )
    envelope = service.invoke(
        metadata_for(Capability.SOURCES_FETCH, Purpose.CONTENT_EXTRACTION, principal),
        FetchSource(source_id=source.source_id, source_object_id=entry.source_object_id),
        principal=principal,
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert "OUTSIDE-THE-ROOT" not in envelope.to_canonical_json()


def test_an_identifier_the_provider_never_issued_is_denied(scene: Scene) -> None:
    """Denied, not `not_found`: the two must not be separable by a caller."""
    service = build_service(scene.world, scene.providers)
    envelope = invoke(
        service,
        scene.principal,
        Capability.SOURCES_METADATA,
        Purpose.SOURCE_INSPECTION,
        GetSourceMetadata(
            source_id=scene.source.source_id,
            source_object_id=issue_identifier(IdKind.SOURCE_OBJECT),
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED


# ---- source mutation -------------------------------------------------------


#: Names a mutating source operation could plausibly take. The list is what makes
#: the surface test a check rather than a description.
MUTATING_NAMES = (
    "write",
    "create",
    "update",
    "delete",
    "remove",
    "rename",
    "move",
    "copy",
    "upload",
    "put",
    "save",
    "truncate",
    "chmod",
    "set_",
)


def test_the_source_provider_port_exposes_no_mutating_method() -> None:
    """`INV-PKL-001` holds by omission, and this is the omission."""
    surface = [name for name in dir(SourceProvider) if not name.startswith("_")]
    assert sorted(surface) == ["fetch", "list_children", "metadata", "source_id"]
    for name in surface:
        assert not any(name.startswith(prefix) for prefix in MUTATING_NAMES)


def test_no_capability_calls_anything_but_the_read_only_provider_methods(
    scene: Scene,
) -> None:
    """Every capability, run once, against a provider that records what it did.

    **The capture commands are re-pointed at a staged capture, and the answers
    are asserted, and neither is decoration.** `commands_for` mints capture
    identifiers that name nothing, which is correct for the denial matrix above —
    every test there refuses before a handler runs, so what the identifier names
    is irrelevant. It is not correct here, where the purpose is permitted and the
    handler is meant to run: `capture.revise` and `capture.read` answered
    `not_found` and this test still passed. Measured: with all four `capture.*`
    handlers raising on every call, this test passed unchanged.

    That is the same defect the independent reviewer measured in
    `tests/security/test_mcp_and_cli_negative_evidence.py`, at a second site
    nobody had named — "only read-only methods were called" is satisfied for free
    by a capability that never reached a method at all. The zero needs the
    non-zero beside it, and for `capture.*` the non-zero is a successful answer.

    Success is asserted for the capture family only. `knowledge.read` here names
    a *minted* knowledge identifier and answers `not_found` by construction, and
    the source capabilities have `assert scene.provider.calls` as their control —
    reads demonstrably happened. Only `capture.*` claims a zero with no such
    control, which is why only `capture.*` needs the answer checked.
    """
    service = build_service(scene.world, scene.providers)
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    staged = staged_capture(scene)
    commands = commands_for(scene) | {
        Capability.CAPTURE_REVISE: ReviseCapture(
            capture_id=staged.capture_id,
            text="a synthetic note, revised",
            idempotency_key="read-only-probe-capture-0001",
        ),
        Capability.CAPTURE_READ: ReadCapture(capture_id=staged.capture_id),
    }
    for capability, command in commands.items():
        answer = invoke(
            service,
            scene.principal,
            capability,
            a_permitted_purpose(capability),
            command,
        )
        if capability in CAPTURE_CAPABILITIES:
            assert answer.error is None, f"{capability.value} failed: {answer.error}"
            assert answer.result is not None, f"{capability.value} answered nothing"
    assert set(scene.provider.calls) <= {"list_children", "metadata", "fetch"}
    assert scene.provider.calls, "no capability touched the provider at all"


def test_a_capability_payload_mismatch_is_refused_and_audited(scene: Scene) -> None:
    """The third refusal, and the one that used to leave no trace at all.

    A request whose metadata declares one capability while its payload performs
    another would be authorized against the declaration, so refusing it is a
    security-relevant act and `AGENTS.md` section 5 requires a proportionate
    audit event. It was refused before the transaction opened, and a reviewer
    measured the result: zero events, zero commits.

    Recorded as `failed` rather than `denied` because no policy decision was
    reached — there is nothing to name a `DenialReason` from — and against the
    *declared* capability, because that is what authority would have been
    evaluated against.
    """
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(Capability.KNOWLEDGE_READ, Purpose.KNOWLEDGE_READ, scene.principal),
        commands_for(scene)[Capability.SOURCES_LIST],
        principal=scene.principal,
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST

    assert len(scene.world.audit) == 1, "the refusal left no audit event"
    event = scene.world.audit[0]
    assert event.outcome is AuditOutcome.FAILED
    assert event.capability is Capability.KNOWLEDGE_READ
    assert event.denial_reason is None
    assert event.correlation_id == envelope.correlation_id
    assert scene.world.commits == 1, "the audit event was not committed"
    assert scene.world.rollbacks == 0


def test_a_mismatched_request_reaches_no_handler(scene: Scene) -> None:
    """Auditing the refusal must not have turned it into an execution.

    The refusal itself is asserted beside the zero. Without it the request could
    have been refused for any reason at all, or answered, and the empty call log
    would read the same — the shape the class sweep of this correction cycle
    found at four other sites.
    """
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(Capability.SOURCES_METADATA, Purpose.SOURCE_INSPECTION, scene.principal),
        commands_for(scene)[Capability.SOURCES_LIST],
        principal=scene.principal,
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST
    assert scene.provider.calls == [], "a mismatched request touched the provider"
