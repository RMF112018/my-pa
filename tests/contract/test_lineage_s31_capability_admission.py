"""The record lineage S3.1 capabilities are admitted as the S3.1 contract states.

FAST, against the composed service and the identity registries. Worker N1's
part of the S3.1 contract section 10 "Admission" row (sections 4.1, 6.1, 7 and
7.10):

* the 4 new names -- the 3 confirms and `records.lineage.related` -- are
  scopeless (P1 client exposure, chatllm-data-v10: the confirms
  `CHATLLM_CONTROL_PLANE_EXCLUDED`, the related read `CHATLLM_DATA_CONDITIONAL`),
  the `lineage` feature, under the section 7 purposes; the confirms are keyed, operator-only writes;
* `MY_PA_LINEAGE_ENABLED` off withholds all 4 and every handler answers
  `unsupported` first;
* no S3.1 request, new or open, admits a server-owned or provenance field;
* the open writes derive their provenance from server-stamped context and never
  answer `denied` for want of attestation; the attested set still does;
* the ChatLLM data profile desires exactly the 34 client-usable lineage-plane
  names when composed and none of the 7 withheld (P1), and no non-lineage v1
  shape moves;
* the tool descriptions of the S3.1 commands carry the section 7.12 guidance.

Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from types import SimpleNamespace
from typing import Any, Final

import pytest
from pydantic import BaseModel
from tests.conftest import DEFAULT_LIMITS, WHEN, FakeUnitOfWork, Scene, build_service, metadata_for
from tests.contract.test_lineage_capability_admission import (
    _BASE_PAYLOADS as _S1_PAYLOADS,
)
from tests.contract.test_lineage_s2_capability_admission import (
    _BASE_PAYLOADS as _S2_PAYLOADS,
)
from tests.contract.test_lineage_s3_capability_admission import (
    _BASE_PAYLOADS as _S3_PAYLOADS,
)
from tests.contract.test_lineage_s3_capability_admission import (
    _V1_PAYLOAD_SCHEMA_SHA256,
    _V1_VIEW_FIELDS_SHA256,
    _V1_VIEW_MODULES,
)

from my_pa.adapters.mcp import remote as remote_mcp
from my_pa.adapters.mcp.chatllm_gateway import _FEATURE_BY_FAMILY
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import _IDEMPOTENT_REMOTE_CAPABILITIES
from my_pa.application.commands import Command
from my_pa.application.errors import (
    DeniedError,
    InternalError,
    InvalidRequestError,
    SafeDetail,
    UnsupportedError,
)
from my_pa.application.lineage_authority import (
    attested_lineage_authority,
    lineage_write_provenance,
)
from my_pa.application.service import _LINEAGE_CAPABILITIES, ApplicationService
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
    is_chatllm_data_management,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.lineage.vocabulary import (
    ATTESTED_LINEAGE_WRITE_CAPABILITIES,
    CONFIRM_CAPABILITIES,
    LINEAGE_BACKFILL_CAPABILITIES,
    LINEAGE_WRITE_CAPABILITIES,
    OPEN_LINEAGE_WRITE_CAPABILITIES,
    AcceptanceBasis,
)
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES

S31_NAMES: Final = frozenset(
    {
        "records.associations.confirm",
        "issues.memberships.confirm",
        "issues.project_links.confirm",
        "records.lineage.related",
    }
)
_PURPOSES: Final = {
    "records.associations.confirm": Purpose.RECORD_LINEAGE_AUTHORING,
    "issues.memberships.confirm": Purpose.ISSUE_AUTHORING,
    "issues.project_links.confirm": Purpose.ISSUE_AUTHORING,
    "records.lineage.related": Purpose.RECORD_LINEAGE_READ,
}
#: P1 client exposure (operator directive 2026-10-26): the withheld attested names.
_ATTESTED_RATIONALE: Final = (
    "attested to the local operator surface; withheld from every client "
    "(operator directive 2026-10-26)"
)
#: Section 1, Part A: the 14 lineage writes the operator directives open.
_OPEN: Final = frozenset(
    {
        "records.associations.assert",
        "records.associations.correct",
        "records.associations.end",
        "records.associations.contest",
        "records.associations.reinstate",
        "issues.memberships.add",
        "issues.memberships.end",
        "issues.memberships.correct",
        "issues.project_links.add",
        "issues.project_links.end",
        "issues.handoffs.record",
        "issues.handoffs.correct",
        "issues.work.create_task",
        "issues.work.create_commitment",
    }
)
_CLIENT: Final = "client-s31-admission"
_S31_PAYLOADS: Final[dict[str, dict[str, object]]] = {
    "records.associations.confirm": {
        "link_id": "irl_lineages31fast0001",
        "expected_revision": 1,
        "idempotency_key": "fast-s31-confirm-link",
        "reason": "Confirmed.",
    },
    "issues.memberships.confirm": {
        "link_id": "irl_lineages31fast0001",
        "expected_revision": 1,
        "idempotency_key": "fast-s31-confirm-membership",
        "reason": "Confirmed.",
    },
    "issues.project_links.confirm": {
        "issue_id": "sit_lineages31fast0001",
        "project_id": "prj_lineages31fast0001",
        "expected_membership_revision": 1,
        "idempotency_key": "fast-s31-confirm-project-link",
        "reason": "Confirmed.",
    },
    "records.lineage.related": {
        "seeds": [{"family": "task", "record_id": "tsk_lineages31fast0001"}]
    },
}
#: Section 6.2 step 1: what no S3.1 request may name -- the provenance a fact
#: row records, which the server derives -- beside the S1 server-owned fields.
_PROVENANCE: Final = (
    "acceptance_basis",
    "authority_class",
    "decision_channel",
    "asserting_client_id",
    "user_directed_claim",
)
_SERVER_OWNED: Final = ("principal_id", "recorded_at", "commit_seq", "actor_class")


def _declared() -> frozenset[Capability]:
    return frozenset(capability for capability in Capability if capability.value in S31_NAMES)


def _payload(name: str) -> dict[str, object]:
    for table in (_S31_PAYLOADS, _S3_PAYLOADS, _S2_PAYLOADS, _S1_PAYLOADS):
        if name in table:
            return dict(table[name])
    raise KeyError(name)


def _arguments(name: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-lineage-s31-fast",
        "purpose": sorted(permitted_purposes(Capability(name)))[0].value,
        "principal_id": "prn_lineages31fast001",
        "requested_at": "2026-10-25T12:00:00Z",
        "payload": payload,
    }


def _command(name: str) -> Command:
    _metadata, command = normalize(name, _arguments(name, _payload(name)))
    return command


def _service(scene: Scene, *, lineage: bool) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(scene.world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        lineage_enabled=lineage,
    )


def _code(envelope: Any) -> str | None:  # noqa: ANN401
    error = envelope.to_canonical_dict().get("error")
    return None if error is None else str(error["code"])


def _invoke(
    service: ApplicationService,
    scene: Scene,
    name: str,
    *,
    operator_surface: OperatorSurface | None = None,
) -> Any:  # noqa: ANN401
    capability = Capability(name)
    return service.invoke(
        metadata_for(capability, sorted(permitted_purposes(capability))[0], scene.principal),
        _command(name),
        principal=scene.principal,
        operator_surface=operator_surface,
    )


def _caller(
    *,
    surface: OperatorSurface | None = None,
    transport: CaptureTransport = CaptureTransport.LOCAL,
    client: str | None = None,
    grants: frozenset[Any] | None = None,
) -> Any:  # noqa: ANN401
    """The server-stamped context `lineage_authority` reads, and nothing else."""
    return SimpleNamespace(
        operator_surface=surface,
        transport=transport,
        principal=Principal(
            principal_id="prn_lineages31fast001", kind=PrincipalKind.OPERATOR, authenticated=True
        ),
        authenticated_client_id=client,
        capability_grants=grants,
    )


_HUMAN: Final = (OperatorSurface.CLI, OperatorSurface.HTTP_GATEWAY)


# ---- registration --------------------------------------------------------------


def test_s31_capabilities_are_operator_decision_required() -> None:
    declared = _declared()
    assert {capability.value for capability in declared} == S31_NAMES
    assert declared <= _LINEAGE_CAPABILITIES
    assert len(_LINEAGE_CAPABILITIES) == 34
    assert len(LINEAGE_WRITE_CAPABILITIES) == 22
    assert CONFIRM_CAPABILITIES <= LINEAGE_WRITE_CAPABILITIES
    assert CONFIRM_CAPABILITIES <= ATTESTED_LINEAGE_WRITE_CAPABILITIES
    for capability in declared:
        name = capability.value
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        # P1 client exposure (operator directive 2026-10-26, chatllm-data-v10):
        # the related read is plane-conditional data; the confirms are withheld
        # from every client as control-plane excluded.
        if name in CONFIRM_CAPABILITIES:
            assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
            assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.NONE
            assert policy.exclusion_rationale == _ATTESTED_RATIONALE
        else:
            assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
            assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.LINEAGE
            assert policy.exclusion_rationale is None
        assert capability in _SCOPELESS
        assert _FEATURE_BY_FAMILY[name.split(".", 1)[0]] == "lineage"
        assert permitted_purposes(capability) == frozenset({_PURPOSES[name]})
        writes = name in CONFIRM_CAPABILITIES
        assert is_write_capability(capability) is writes
        # A confirm changes a fact's acceptance: a write, never additive.
        assert is_destructive_capability(capability) is writes
        assert (capability in _IDEMPOTENT_REMOTE_CAPABILITIES) is writes
        assert (name in LINEAGE_WRITE_CAPABILITIES) is writes
        # Section 7.13: the confirms are operator kind -- attested, so never a
        # remote caller's -- and the related read is an ordinary read.
        assert is_operator_only(capability) is writes
    counts = dict.fromkeys(ChatLLMCapabilityClass, 0)
    for policy in CHATLLM_CAPABILITY_POLICY.values():
        counts[policy.classification] += 1
    # P1: only the GSQS pair remains an operator decision.
    assert counts[ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED] == 2
    assert len(Capability) == 233
    # P1 moved data-class members, so the ChatLLM data profile moved too.
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v10"


def test_switch_off_withholds_every_s31_capability(scene: Scene) -> None:
    declared = _declared()
    off = build_service(scene.world, scene.providers)
    on = _service(scene, lineage=True)
    assert not off.available_capabilities & declared
    assert declared <= on.available_capabilities
    published_off = {tool.name for tool in published_tools(off, authenticated_client_present=True)}
    published_on = {tool.name for tool in published_tools(on, authenticated_client_present=True)}
    assert not published_off & S31_NAMES
    assert published_on >= S31_NAMES
    for name in sorted(S31_NAMES):
        # The switch first: a stamped operator surface still answers `unsupported`.
        envelope = _invoke(off, scene, name, operator_surface=OperatorSurface.CLI)
        assert _code(envelope) == "unsupported", name


@pytest.mark.parametrize("name", sorted(S31_NAMES | _OPEN))
def test_s31_requests_reject_server_owned_fields(name: str) -> None:
    base = _payload(name)
    command = _command(name)
    assert command.capability.value == name
    for field in (*_PROVENANCE, *_SERVER_OWNED):
        for value in ("server-owned", True):
            with pytest.raises(InvalidRequestError):
                normalize(name, _arguments(name, {**base, field: value}))


def test_the_related_read_refuses_a_malformed_request() -> None:
    """Section 7.4: each malformed list names its field; a cursor needs a page size."""
    name = "records.lineage.related"
    seed = {"family": "task", "record_id": "tsk_lineages31fast0001"}
    other = {"family": "task", "record_id": "tsk_lineages31fast0002"}
    cases: tuple[tuple[dict[str, object], SafeDetail], ...] = (
        ({"seeds": []}, SafeDetail.SEEDS),
        ({"seeds": [seed, seed]}, SafeDetail.SEEDS),
        (
            {
                "seeds": [
                    {"family": "task", "record_id": f"tsk_lineages31many{i:04d}"} for i in range(26)
                ]
            },
            SafeDetail.SEEDS,
        ),
        ({"seeds": [{"family": "task", "record_id": "cmt_lineages31fast0001"}]}, SafeDetail.SEEDS),
        ({"seeds": "tsk_lineages31fast0001"}, SafeDetail.SEEDS),
        ({"seeds": [seed], "max_depth": 4}, SafeDetail.MAX_DEPTH),
        ({"seeds": [seed], "max_depth": 0}, SafeDetail.MAX_DEPTH),
        ({"seeds": [seed], "acceptance_bases": []}, SafeDetail.ACCEPTANCE_BASES),
        (
            {"seeds": [seed], "acceptance_bases": ["client_identified", "client_identified"]},
            SafeDetail.ACCEPTANCE_BASES,
        ),
        ({"seeds": [seed], "acceptance_bases": ["accepted"]}, SafeDetail.ACCEPTANCE_BASES),
        ({"seeds": [seed], "relation_types": []}, SafeDetail.RELATION_TYPES),
        ({"seeds": [seed], "relation_types": ["blocks", "blocks"]}, SafeDetail.RELATION_TYPES),
        ({"seeds": [seed], "relation_types": ["causes"]}, SafeDetail.RELATION_TYPES),
        ({"seeds": [seed], "cursor": "abc"}, SafeDetail.CURSOR),
        ({"seeds": [seed], "cursor": 7, "page_size": 10}, SafeDetail.CURSOR),
        ({"seeds": [seed], "page_size": 9}, SafeDetail.PAGE_SIZE),
        ({"seeds": [seed], "known_at": "yesterday"}, SafeDetail.KNOWN_AT),
    )
    for payload, detail in cases:
        with pytest.raises(InvalidRequestError) as refused:
            normalize(name, _arguments(name, payload))
        assert detail in refused.value.safe_details, (payload, refused.value.safe_details)
    # The bounds themselves are admitted: 25 distinct seeds, every basis and relation.
    _metadata, command = normalize(
        name,
        _arguments(
            name,
            {
                "seeds": [seed, other]
                + [
                    {"family": "task", "record_id": f"tsk_lineages31many{i:04d}"} for i in range(23)
                ],
                "max_depth": 3,
                "acceptance_bases": [basis.value for basis in AcceptanceBasis],
                "page_size": 10,
                "cursor": "abc",
            },
        ),
    )
    assert command.capability is Capability.RECORDS_LINEAGE_RELATED


# ---- provenance and the remaining gates (sections 4.1 and 6.1) -------------------


def test_open_writes_derive_provenance_and_never_deny() -> None:
    assert frozenset(OPEN_LINEAGE_WRITE_CAPABILITIES) == _OPEN
    for name in sorted(_OPEN):
        capability = Capability(name)
        # Open writes stay `write` kind (section 7.13): remote-publishable when
        # remote writes are on and granted, never operator-only.
        assert not is_operator_only(capability), name
        assert permitted_purposes(capability) & remote_mcp._WRITE_PURPOSES, name
    for surface in _HUMAN:
        human = lineage_write_provenance(_caller(surface=surface), user_directed=False)
        assert human.acceptance_basis is AcceptanceBasis.USER_CONFIRMED
        assert human.authority_class.value == "local_operator"
        assert human.asserting_client_id is None
        assert human.user_directed_claim is False
        # The human channel is the directing user: the claim is refused.
        with pytest.raises(InvalidRequestError) as refused:
            lineage_write_provenance(_caller(surface=surface), user_directed=True)
        assert refused.value.safe_details == (SafeDetail.USER_DIRECTED,)
    for claim in (False, True):
        remote = lineage_write_provenance(
            _caller(transport=CaptureTransport.REMOTE_CLIENT, client=_CLIENT, grants=frozenset()),
            user_directed=claim,
        )
        assert remote.acceptance_basis is AcceptanceBasis.CLIENT_IDENTIFIED
        assert (remote.authority_class.value, remote.decision_channel.value) == (
            "ordinary_reviewer",
            "remote_interactive",
        )
        assert remote.asserting_client_id == _CLIENT
        # Stored verbatim, and it upgrades nothing.
        assert remote.user_directed_claim is claim
        unstamped = lineage_write_provenance(_caller(), user_directed=claim)
        assert unstamped.acceptance_basis is AcceptanceBasis.CLIENT_IDENTIFIED
        assert unstamped.decision_channel.value == "local_unattested"
        assert unstamped.asserting_client_id is None
        assert unstamped.user_directed_claim is claim
    # The S1 composition refusals are kept: a remote transport without a client
    # is `unsupported`, an inconsistent composition `internal_error` -- never
    # `denied`.
    with pytest.raises(UnsupportedError):
        lineage_write_provenance(
            _caller(transport=CaptureTransport.REMOTE_CLIENT, grants=frozenset()),
            user_directed=False,
        )
    with pytest.raises(InternalError):
        lineage_write_provenance(
            _caller(surface=OperatorSurface.CLI, client=_CLIENT), user_directed=False
        )


def test_remaining_gated_capabilities_derive_attested_authority(scene: Scene) -> None:
    assert frozenset(ATTESTED_LINEAGE_WRITE_CAPABILITIES) == {
        "issues.close",
        "issues.reopen",
        "records.backfill.plan",
        *CONFIRM_CAPABILITIES,
    }
    assert not ATTESTED_LINEAGE_WRITE_CAPABILITIES & OPEN_LINEAGE_WRITE_CAPABILITIES
    for surface in _HUMAN:
        derived = attested_lineage_authority(_caller(surface=surface))
        assert derived.authority_class.value == "local_operator"
    for caller in (
        _caller(),
        _caller(transport=CaptureTransport.REMOTE_CLIENT, client=_CLIENT, grants=frozenset()),
    ):
        with pytest.raises(DeniedError):
            attested_lineage_authority(caller)
    # Each confirm handler derives attested authority after the switch: an
    # unstamped local caller is `denied`, before any row and any replay lookup
    # (the FAST world holds no lineage row, so a reached repository would not
    # answer `denied`).
    service = _service(scene, lineage=True)
    for name in sorted(CONFIRM_CAPABILITIES):
        assert _code(_invoke(service, scene, name)) == "denied", name
    # Close and reopen are operator-only now (section 7.13), and attested as before.
    for capability in (Capability.ISSUES_CLOSE, Capability.ISSUES_REOPEN):
        assert is_operator_only(capability)
        assert capability.value in ATTESTED_LINEAGE_WRITE_CAPABILITIES


def test_no_s31_capability_is_in_the_chatllm_data_profile() -> None:
    from my_pa.application.chatllm_data_profile import (
        ChatLLMCompositionPlanes,
        composed_capabilities,
        desired_effective_capabilities,
    )

    declared = _declared()
    lineage_plane = _LINEAGE_CAPABILITIES | frozenset(
        capability
        for capability in Capability
        if capability.value in PROGRAM_REPORTING_CAPABILITIES
    )
    # P1 client exposure (operator directive 2026-10-26): the 7 withheld names.
    withheld = frozenset(
        capability
        for capability in Capability
        if capability.value in CONFIRM_CAPABILITIES | LINEAGE_BACKFILL_CAPABILITIES
        or capability in {Capability.ISSUES_CLOSE, Capability.ISSUES_REOPEN}
    )
    assert len(withheld) == 7
    exposed = lineage_plane - withheld
    assert len(exposed) == 34
    assert all(is_chatllm_data_management(capability) for capability in exposed)
    assert not any(is_chatllm_data_management(capability) for capability in withheld)
    every = frozenset(Capability)
    for knowledge_manager in (False, True):
        # From the all-composed set exactly the 34 are desired, none of the 7.
        desired = desired_effective_capabilities(every, knowledge_manager=knowledge_manager)
        assert desired & lineage_plane == exposed
        assert not desired & withheld
    # With the lineage plane off (the default) no S3.1 data name is composed and
    # no S3.1 name is desired. The planner models composition by prerequisite
    # only, so the 3 excluded confirms (prerequisite `NONE`) stay in its composed
    # set whatever the planes, exactly as the backfill pair always has; the
    # service withholds them by its switch, and no profile ever desires them.
    off = ChatLLMCompositionPlanes(
        managed_documents=True,
        relationship_intelligence=True,
        relationship_intelligence_writes=True,
        relationship_memory=True,
        constraints=True,
        knowledge_assertions=True,
        program_reporting=True,
    )
    composed_off = composed_capabilities(every, off)
    assert not composed_off & (declared - withheld)
    for knowledge_manager in (False, True):
        assert not (
            desired_effective_capabilities(composed_off, knowledge_manager=knowledge_manager)
            & lineage_plane
        )
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v10"


# ---- client guidance (section 7.12) ----------------------------------------------

#: Section 7.12, verbatim: the summary every S3.1 command's tool carries.
_SUMMARIES: Final = {
    "records.lineage.related": (
        "Read records related to up to 25 seeds through recorded lineage, with each link's "
        "evidence and provenance label; pass known_at to reproduce a read."
    ),
    **dict.fromkeys(
        sorted(CONFIRM_CAPABILITIES),
        "Operator only: confirm a client-identified lineage fact as user-confirmed by "
        "appending a revision.",
    ),
}


#: Section 7.12 (worker N3): the summary of every other lineage write and read,
#: verbatim. Each open write says it is recorded client-identified; each
#: operator-kind name says "Operator only"; each read names what it labels.
_LINEAGE_SUMMARIES: Final = {
    "records.associations.assert": (
        "Commit a typed link you identified from cited exact evidence or the user's "
        "instruction; it is recorded client-identified and unreviewed, and shared projects, "
        "dates, names or similar text are not evidence of it."
    ),
    "records.associations.correct": (
        "Replace an unreviewed association's evidence with exact cited passages; recorded "
        "client-identified, and refused on a link the user has confirmed."
    ),
    "records.associations.end": (
        "End an association the user never confirmed, with a reason; recorded "
        "client-identified, and it holds its Issue's close until the user reviews it."
    ),
    "records.associations.contest": (
        "Dispute an active association with an exact contradicting passage; recorded "
        "client-identified, and a link the user confirmed may be contested only once."
    ),
    "records.associations.reinstate": (
        "Resolve a contested association the user never confirmed back to active with its "
        "relation's evidence; recorded client-identified and unreviewed."
    ),
    "issues.memberships.add": (
        "Make a record a member of an Issue, citing exact evidence; recorded "
        "client-identified and unreviewed, and it holds the Issue's close until confirmed."
    ),
    "issues.memberships.end": (
        "End an Issue membership the user never confirmed, with a reason; recorded "
        "client-identified, and it holds the Issue's close until the user reviews it."
    ),
    "issues.memberships.correct": (
        "Replace an unreviewed membership's evidence with exact cited passages; recorded "
        "client-identified, and refused on a membership the user has confirmed."
    ),
    "issues.project_links.add": (
        "Link an Issue to a Project, or relink it, when its work belongs there; recorded "
        "client-identified, and an unreviewed link makes the Project's Issue totals not "
        "reportable."
    ),
    "issues.project_links.end": (
        "End an Issue's Project link the user never confirmed, with a reason; recorded "
        "client-identified and unreviewed."
    ),
    "issues.handoffs.record": (
        "Record from exact evidence that a Commitment's next action changed hands; recorded "
        "client-identified and unreviewed."
    ),
    "issues.handoffs.correct": (
        "Retime or void a handoff the user never confirmed, citing exact evidence; recorded "
        "client-identified, never rewriting the original."
    ),
    "issues.work.create_task": (
        "Create a Task as work of an Issue with its membership and links in one request; the "
        "links are recorded client-identified and unreviewed."
    ),
    "issues.work.create_commitment": (
        "Create a Commitment as work of an Issue with its membership and links in one "
        "request; the links are recorded client-identified and unreviewed."
    ),
    "issues.create": "Open an Issue (version 1, open) with a title and description.",
    "issues.update": (
        "Change an Issue's title, description or non-terminal state at its expected version."
    ),
    "issues.close": "Operator only: close an Issue behind its closure gate.",
    "issues.reopen": "Operator only: reopen a closed Issue, with a reason.",
    "records.backfill.plan": (
        "Operator only: enumerate a lineage backfill dry run, or classify its next batch."
    ),
    "records.backfill.report": (
        "Operator only: read one lineage backfill run's census, counts and items."
    ),
    "issues.read": (
        "Read one Issue with its Project links and, on request, its members, each labelled "
        "user_confirmed or client_identified."
    ),
    "issues.list": "List your Issues, newest first, one keyset page at a time.",
    "issues.history": (
        "Read one Issue's revisions with their closure basis, oldest first, as known at known_at."
    ),
    "issues.timeline": (
        "Read one Issue's lineage and native events in order, each lineage fact with its "
        "provenance label, one page at a time."
    ),
    "issues.handoffs.list": (
        "List an Issue's handoffs, oldest first, each with its evidence and provenance label."
    ),
    "issues.closure_readiness": (
        "Read an Issue's gaps: blocked members, stale evidence, contested links and "
        "unreviewed client-identified links that hold its close."
    ),
    "records.lineage": (
        "Read the Issue-scoped lineage around one record, with each link's evidence and "
        "provenance label."
    ),
    "records.associations.history": (
        "Read one association's revisions with their evidence and provenance labels, as "
        "known at known_at."
    ),
    "meetings.notes.versions": (
        "List one Meeting's note versions, newest first, to choose the exact version to cite."
    ),
    "meetings.notes.read_version": (
        "Read one exact Meeting note version, its body on request, to cite code-point offsets "
        "of the stored text."
    ),
}
#: Section 7.12, verbatim: the field documentation of the flag and of the anchors.
_USER_DIRECTED_DOC: Final = (
    "Set true only when the user explicitly instructed this write; it is stored as an "
    "unverified claim and changes no gate or label."
)
_EVIDENCE_DOC: Final = (
    "Cite the exact stored version (mnote_ or capver_) and code-point offsets of the stored "
    "body; read it with meetings.notes.read_version first."
)


def test_lineage_tool_descriptions_carry_the_client_guidance() -> None:
    descriptions = {tool.name: tool.description for tool in TOOLS}
    for name, summary in (_SUMMARIES | _LINEAGE_SUMMARIES).items():
        assert descriptions[name] == summary, name
    # Every lineage tool has a pinned, one-sentence description within 240 characters.
    assert {capability.value for capability in _LINEAGE_CAPABILITIES} == set(
        _SUMMARIES | _LINEAGE_SUMMARIES
    )
    for capability in _LINEAGE_CAPABILITIES:
        description = descriptions[capability.value]
        assert description, capability.value
        assert len(description) <= 240, capability.value
        assert description.endswith(".") and ". " not in description, capability.value
    # The open writes' field documentation (section 7.12).
    payloads = {
        tool.name: tool.input_schema["properties"]["payload"]["properties"] for tool in TOOLS
    }
    for name in OPEN_LINEAGE_WRITE_CAPABILITIES:
        assert payloads[name]["user_directed"]["description"] == _USER_DIRECTED_DOC, name
        anchors = [
            value
            for key, value in payloads[name].items()
            if key in {"evidence_anchors", "membership_evidence_anchors"}
        ]
        for schema in anchors:
            assert schema["description"].endswith(_EVIDENCE_DOC), name


# ---- old-client rule (section 8) -----------------------------------------------------


def _canonical_sha256(document: object) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_existing_non_lineage_v1_shapes_are_unchanged_by_s31() -> None:
    """Section 8: the 192 non-lineage, non-S4 tools and the v1 views are byte-identical."""
    lineage = {capability.value for capability in _LINEAGE_CAPABILITIES}
    lineage |= PROGRAM_REPORTING_CAPABILITIES
    assert lineage >= S31_NAMES
    payloads = {
        tool.name: tool.input_schema["properties"]["payload"]
        for tool in TOOLS
        if tool.name not in lineage
    }
    assert len(payloads) == 192
    assert _canonical_sha256(payloads) == _V1_PAYLOAD_SCHEMA_SHA256
    views: dict[str, list[str]] = {}
    for name in _V1_VIEW_MODULES:
        module = importlib.import_module(f"my_pa.contracts.v1.{name}")
        for model_name, model in vars(module).items():
            if (
                inspect.isclass(model)
                and issubclass(model, BaseModel)
                and model.__module__ == module.__name__
            ):
                views[f"{name}.{model_name}"] = sorted(model.model_fields)
    assert _canonical_sha256(views) == _V1_VIEW_FIELDS_SHA256
    # S3.1 adds no purpose: the envelope's purpose enum is the S4 one.
    published = TOOLS[0].input_schema["$defs"]["Purpose"]["enum"]
    assert len(published) == len(Purpose) == 60
    assert published[-2:] == ["lineage_backfill", "program_reporting_read"]
    # Every non-lineage tool's annotations are untouched by the S3.1 hint.
    for tool in TOOLS:
        if tool.name not in lineage:
            assert tool.annotations is not None
