"""One authorization path, and the negative evidence `P05-SPEC-AC-002` asks for.

Two claims are made here, and they are different in kind.

**Structural.** `ApplicationService` exposes one public method. A use case is a
private method reached only through the dispatch table `invoke` consults *after*
`authorize` has returned an allowed decision, so there is no call a caller can
make that performs a capability without a decision. The first test asserts the
surface, because that is what makes the second set of tests exhaustive rather
than a sample.

**Behavioural.** Every capability is then invoked with an unauthorized request
and required to be denied — not one capability, all eight, and for each of the
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
    staged_search,
)

from my_pa.application.commands import (
    Command,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetSourceMetadata,
    GetSourceStatus,
    ListSources,
    ReadKnowledge,
    SearchKnowledge,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.audit.events import AuditOutcome
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import DenialReason
from my_pa.domain.source.provider import SourceProvider
from my_pa.domain.source.registry import issue_identifier


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


#: Capabilities whose authority is a held scope. `capabilities.get` describes the
#: interface and carries no scope at all; `sources.enroll` is the operation that
#: *grants* scope, so requiring the scope to be held already would make it
#: permanently unusable — `domain.policy.decision._scope_is_authorized` says so,
#: and its authority is the operator-only check instead, which has its own row
#: below. Both exclusions are derived from the domain rule rather than chosen.
SCOPED_CAPABILITIES = [
    c for c in Capability if c not in {Capability.CAPABILITIES_GET, Capability.SOURCES_ENROLL}
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


def test_the_two_capabilities_outside_the_scope_matrix_are_the_domains_own_two() -> None:
    """Guard the exclusions above, which would otherwise narrow the matrix silently.

    A capability dropped from `SCOPED_CAPABILITIES` for convenience would lose
    its unknown-scope row and nothing would say so. The two that are excluded are
    excluded because the domain treats them specially, and each is identified
    here by the property that makes it special rather than by name.
    """
    excluded = set(Capability) - set(SCOPED_CAPABILITIES)
    assert excluded == {Capability.CAPABILITIES_GET, Capability.SOURCES_ENROLL}

    unheld = frozenset({issue_identifier(IdKind.SOURCE)})
    granting = {c for c in Capability if _decision(c, unheld, frozenset())}
    assert granting == {Capability.SOURCES_ENROLL}, (
        "exactly one capability may name a scope it does not hold: the one that grants scope"
    )

    scopeless = {c for c in Capability if _decision(c, frozenset(), frozenset())}
    assert scopeless == {Capability.CAPABILITIES_GET}, (
        "exactly one capability carries no source scope: the one that describes the interface"
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

    service = ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world),
        providers=FakeProviders({source.source_id: provider}),
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
    """Every capability, run once, against a provider that records what it did."""
    service = build_service(scene.world, scene.providers)
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    for capability, command in commands_for(scene).items():
        invoke(
            service,
            scene.principal,
            capability,
            a_permitted_purpose(capability),
            command,
        )
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
    """Auditing the refusal must not have turned it into an execution."""
    service = build_service(scene.world, scene.providers)
    service.invoke(
        metadata_for(Capability.SOURCES_METADATA, Purpose.SOURCE_INSPECTION, scene.principal),
        commands_for(scene)[Capability.SOURCES_LIST],
        principal=scene.principal,
    )
    assert scene.provider.calls == [], "a mismatched request touched the provider"
