"""Who may accept a Knowledge Review case, at the service boundary (KLP-WP-04 slice C).

FAST. KLP-AC-039, KLP-AC-114 (service half; the database CHECK half is
`tests/database/test_knowledge_assertion_review.py`), R6 section 3.2 item 5
(a)-(h) end to end through `ApplicationService.invoke` (and, for the MCP
surfaces, through `adapters.mcp.server._answer` exactly as a tool call runs)
over a canned Knowledge plane that records what the decide port receives:

* (a) stdio MCP (`_answer`, default LOCAL transport, no surface) accepting a
  `requires_operator` case -> `denied(disposition)`, the port is never reached;
* (b) an `McpAccess` built without a transport is LOCAL -> the port receives
  `ordinary_reviewer` / `local_unattested`, no client;
* (c) an invoke without `operator_surface` -> `ordinary_reviewer`;
* (d) `operator_surface` with `REMOTE_CLIENT` or a client id -> refused before
  any read, the port is never reached;
* (e) a remote ChatLLM client -> `remote_interactive` / `ordinary_reviewer`
  with its client id, and `denied` on `requires_operator`;
* (f) a discovery client -> `review.decide` absent from its overlaid grants and
  refused `unsupported` at the tool call;
* (g) `REMOTE_CLIENT` with no client (the remote capture route's composition)
  -> `unsupported` once the case is visible, `not_found` without the read grant;
* (h) the CLI and HTTP-gateway operators -> `local_operator` with `local_cli` /
  `local_web`; an operator-review client -> `remote_operator_attested`.

Plus the structural half of KLP-AC-039: the Knowledge branch derives its pair
from `derive_knowledge_review_authority` alone and never calls
`_operator_authority()`.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest
from apps.gateway import remote_access_context
from tests.conftest import DEFAULT_LIMITS, WHEN, FakeUnitOfWork, Scene, World
from tests.contract.test_knowledge_assertion_capabilities import _CannedKnowledge

from my_pa.adapters.mcp.server import McpAccess, _answer
from my_pa.application.commands import DecideReviewCase
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import (
    KnowledgeAssertionRepository,
    KnowledgeReviewCaseRow,
    KnowledgeReviewDecisionRequest,
    KnowledgeReviewDecisionResult,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose

SERVICE: Final = Path(__file__).resolve().parents[2] / "src/my_pa/application/service.py"
OPERATOR_CASE: Final = "rvw_fastoperatorcase01"
REVIEW_CASE: Final = "rvw_fastreviewcase0001"
REVIEW_CLIENT: Final = "synthetic-operator-review-client"
CHAT_CLIENT: Final = "synthetic-chatllm-client"
DISCOVERY_CLIENT: Final = "synthetic-discovery-client"
READ: Final = frozenset(
    {
        (Capability.REVIEW_DECIDE, None),
        (Capability.REVIEW_LIST, None),
        (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ),
    }
)


def _case(review_case_id: str, requirement: str) -> KnowledgeReviewCaseRow:
    return KnowledgeReviewCaseRow(
        review_case_id=review_case_id,
        proposal_id="kaprp_fastworld0000001",
        subject_kind="entity",
        subject_id="ent_fastworld00000001",
        predicate_code="organization.payment_terms",
        predicate_version=1,
        review_requirement=requirement,
        risk_class="high",
        state="needs_review",
        classification="private_local",
        opened_at=datetime(2026, 10, 5, tzinfo=UTC),
        review_version=0,
        latest_disposition=None,
        value_text="Synthetic net 30",
    )


class _ReviewPlane(_CannedKnowledge):
    """Two canned cases; records every request the decide port receives."""

    def __init__(self) -> None:
        super().__init__(seeded=True)
        self.requests: list[KnowledgeReviewDecisionRequest] = []
        self.cases = {
            OPERATOR_CASE: _case(OPERATOR_CASE, "requires_operator"),
            REVIEW_CASE: _case(REVIEW_CASE, "requires_review"),
        }

    def review_case(
        self, principal_id: str, review_case_id: str, *, remote: bool
    ) -> KnowledgeReviewCaseRow | None:
        self.calls.append("review_case")
        return self.cases.get(review_case_id)

    def decide_review(
        self, principal_id: str, request: KnowledgeReviewDecisionRequest, *, at: datetime
    ) -> KnowledgeReviewDecisionResult:
        self.requests.append(request)
        return KnowledgeReviewDecisionResult(
            decision_id="kadec_fastworld0000001",
            review_case_id=request.review_case_id,
            sequence=1,
            disposition=request.disposition,
            proposal_state="accepted",
            assertion_id="kasr_fastworld00000001",
            receipt_id="kamut_fastworld0000001",
        )


class _UnitOfWork(FakeUnitOfWork):
    def __init__(self, world: World, plane: _ReviewPlane) -> None:
        super().__init__(world)
        self._plane = plane

    @property
    def knowledge_assertions(self) -> KnowledgeAssertionRepository:
        return self._plane


def _service(world: World, plane: _ReviewPlane) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: _UnitOfWork(world, plane),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        relationship_intelligence_enabled=True,
        knowledge_assertions_enabled=True,
        knowledge_discovery_client_ids=frozenset({DISCOVERY_CLIENT}),
        knowledge_operator_review_client_ids=frozenset({REVIEW_CLIENT}),
    )


_SEQUENCE: list[int] = []


def _metadata(principal: Principal) -> RequestMetadata:
    _SEQUENCE.append(1)
    return RequestMetadata(
        request_id=f"req-klp04-authority-{len(_SEQUENCE)}",
        capability=Capability.REVIEW_DECIDE,
        purpose=sorted(permitted_purposes(Capability.REVIEW_DECIDE))[0],
        principal_id=principal.principal_id,
        requested_at=WHEN,
    )


def _decide(
    service: ApplicationService,
    principal: Principal,
    case: str = OPERATOR_CASE,
    **composition: Any,  # noqa: ANN401 - invoke's composition keywords
) -> ResponseEnvelope:
    return service.invoke(
        _metadata(principal),
        DecideReviewCase(
            review_case_id=case, expected_review_version=0, disposition=Disposition.ACCEPT
        ),
        principal=principal,
        **composition,
    )


@pytest.fixture
def plane() -> _ReviewPlane:
    return _ReviewPlane()


@pytest.fixture
def service(scene: Scene, plane: _ReviewPlane) -> ApplicationService:
    return _service(scene.world, plane)


def _authority(plane: _ReviewPlane) -> tuple[str, str, str | None]:
    (request,) = plane.requests
    return (
        request.operator_authority_class,
        request.decision_channel,
        request.authenticated_client_id,
    )


def _arguments(access: McpAccess, case: str) -> dict[str, Any]:
    """A tool call's arguments: the remote boundary stamps the envelope, stdio sends it."""
    payload = {"review_case_id": case, "expected_review_version": 0, "disposition": "accept"}
    if access.transport is CaptureTransport.REMOTE_CLIENT:
        return {"payload": payload}
    metadata = _metadata(access.principal)
    return {
        "request_id": metadata.request_id,
        "purpose": metadata.purpose.value,
        "principal_id": metadata.principal_id,
        "requested_at": metadata.requested_at.isoformat(),
        "payload": payload,
    }


def _mcp_call(
    service: ApplicationService, access: McpAccess, case: str = OPERATOR_CASE
) -> dict[str, Any]:
    text, failed, _image = _answer(
        service,
        access.principal,
        Capability.REVIEW_DECIDE.value,
        _arguments(access, case),
        transport=access.transport,
        allowed_capability_purposes=access.allowed_capability_purposes,
        authenticated_client_id=access.authenticated_client_id,
    )
    document = json.loads(text)
    return {"failed": failed, **document}


def _code(document: dict[str, Any]) -> str | None:
    error = document.get("error") or document
    return error.get("code") if isinstance(error, dict) else None


# ---- (a) / (b) / (c): unattested local callers ---------------------------------------


def test_a_stdio_mcp_accept_of_an_operator_case_is_denied_before_the_port(
    scene: Scene, service: ApplicationService, plane: _ReviewPlane
) -> None:
    document = _mcp_call(service, McpAccess(principal=scene.principal))
    assert document["failed"] is True
    assert _code(document) == "denied"
    assert plane.requests == []


def test_b_an_mcp_access_without_a_transport_decides_unattested(
    scene: Scene, service: ApplicationService, plane: _ReviewPlane
) -> None:
    access = McpAccess(principal=scene.principal)
    assert access.transport is CaptureTransport.LOCAL
    document = _mcp_call(service, access, REVIEW_CASE)
    assert document["failed"] is False, document
    assert _authority(plane) == ("ordinary_reviewer", "local_unattested", None)


def test_c_an_invoke_without_a_surface_is_an_ordinary_reviewer(
    scene: Scene, service: ApplicationService, plane: _ReviewPlane
) -> None:
    denied = _decide(service, scene.principal)
    assert denied.error is not None and denied.error.code.value == "denied"
    assert denied.error.safe_details == ("disposition",)
    accepted = _decide(service, scene.principal, REVIEW_CASE)
    assert accepted.error is None, accepted.error
    assert _authority(plane) == ("ordinary_reviewer", "local_unattested", None)


def test_c_a_local_composition_with_grants_is_never_an_operator(
    scene: Scene, service: ApplicationService, plane: _ReviewPlane
) -> None:
    """gsqs_b0-style stdio: LOCAL transport plus a grant ceiling (remote for disclosure)."""
    denied = _decide(service, scene.principal, capability_grants=READ)
    assert denied.error is not None and denied.error.code.value == "denied"
    accepted = _decide(service, scene.principal, REVIEW_CASE, capability_grants=READ)
    assert accepted.error is None, accepted.error
    assert _authority(plane) == ("ordinary_reviewer", "local_unattested", None)


# ---- (d): an operator surface on a remote composition ------------------------------------


@pytest.mark.parametrize(
    "composition",
    [
        {"transport": CaptureTransport.REMOTE_CLIENT, "authenticated_client_id": REVIEW_CLIENT},
        {"authenticated_client_id": REVIEW_CLIENT},
        {"capability_grants": READ},
    ],
    ids=["remote-transport", "client", "grants"],
)
def test_d_a_surface_on_a_remote_composition_is_refused_before_any_read(
    scene: Scene,
    service: ApplicationService,
    plane: _ReviewPlane,
    composition: dict[str, Any],
) -> None:
    try:
        envelope = _decide(
            service, scene.principal, operator_surface=OperatorSurface.CLI, **composition
        )
    except ValueError:
        envelope = None
    if envelope is not None:
        assert envelope.error is not None
        assert envelope.result is None
    assert plane.requests == []
    assert "review_case" not in plane.calls


# ---- (e) / (h): remote and operator channels ---------------------------------------------


def test_e_a_remote_chatllm_client_is_interactive_and_denied_operator_cases(
    scene: Scene, service: ApplicationService, plane: _ReviewPlane
) -> None:
    remote = {
        "transport": CaptureTransport.REMOTE_CLIENT,
        "capability_grants": READ,
        "authenticated_client_id": CHAT_CLIENT,
    }
    denied = _decide(service, scene.principal, **remote)
    assert denied.error is not None and denied.error.code.value == "denied"
    assert plane.requests == []
    accepted = _decide(service, scene.principal, REVIEW_CASE, **remote)
    assert accepted.error is None, accepted.error
    assert _authority(plane) == ("ordinary_reviewer", "remote_interactive", CHAT_CLIENT)


@pytest.mark.parametrize(
    ("composition", "expected"),
    [
        (
            {"operator_surface": OperatorSurface.CLI},
            ("local_operator", "local_cli", None),
        ),
        (
            {"operator_surface": OperatorSurface.HTTP_GATEWAY},
            ("local_operator", "local_web", None),
        ),
        (
            {
                "transport": CaptureTransport.REMOTE_CLIENT,
                "capability_grants": READ,
                "authenticated_client_id": REVIEW_CLIENT,
            },
            ("remote_operator_attested", "remote_operator_review", REVIEW_CLIENT),
        ),
    ],
    ids=["cli", "http_gateway", "operator_review_client"],
)
def test_h_operators_accept_operator_cases_with_their_derived_channel(
    scene: Scene,
    service: ApplicationService,
    plane: _ReviewPlane,
    composition: dict[str, Any],
    expected: tuple[str, str, str | None],
) -> None:
    accepted = _decide(service, scene.principal, **composition)
    assert accepted.error is None, accepted.error
    assert _authority(plane) == expected


def test_h_a_non_operator_principal_on_an_operator_surface_is_never_local_operator(
    scene: Scene, service: ApplicationService, plane: _ReviewPlane
) -> None:
    gateway = Principal(
        principal_id=scene.principal.principal_id, kind=PrincipalKind.GATEWAY, authenticated=True
    )
    envelope = _decide(service, gateway, operator_surface=OperatorSurface.CLI)
    assert envelope.error is not None
    assert envelope.error.code.value == "denied"
    assert plane.requests == []


# ---- (f): a discovery client ---------------------------------------------------------------


def test_f_a_discovery_client_never_holds_review_decide_and_is_refused_at_the_call(
    scene: Scene, service: ApplicationService, plane: _ReviewPlane
) -> None:
    settings = SimpleNamespace(
        knowledge_discovery_oauth_client_id_set=lambda: frozenset({DISCOVERY_CLIENT}),
        knowledge_operator_review_oauth_client_id_set=frozenset,
        chatllm_gateway_oauth_client_id_set=frozenset,
        compact_publication_for_client=lambda _client: False,
    )
    raw = frozenset({*READ, (Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, None)})
    authenticated = SimpleNamespace(
        principal=scene.principal,
        client_id=DISCOVERY_CLIENT,
        capabilities=frozenset(capability for capability, _purpose in raw),
        capability_purposes=raw,
        write_allowed=True,
    )
    context = remote_access_context(settings, service, authenticated)  # type: ignore[arg-type]
    assert Capability.REVIEW_DECIDE.value not in context.allowed_capabilities
    assert all(
        capability is not Capability.REVIEW_DECIDE for capability, _ in context.capability_purposes
    )
    document = _mcp_call(
        service,
        McpAccess(
            principal=scene.principal,
            transport=CaptureTransport.REMOTE_CLIENT,
            allowed_capability_purposes=context.capability_purposes,
            authenticated_client_id=DISCOVERY_CLIENT,
        ),
    )
    assert document["failed"] is True
    assert _code(document) == "unsupported"
    assert plane.requests == []


# ---- (g): the remote transport without a client ----------------------------------------------


def test_g_the_remote_transport_without_a_client_cannot_decide_a_knowledge_case(
    scene: Scene, service: ApplicationService, plane: _ReviewPlane
) -> None:
    granted = _decide(
        service,
        scene.principal,
        transport=CaptureTransport.REMOTE_CLIENT,
        capability_grants=READ,
    )
    assert granted.error is not None
    assert granted.error.code.value == "unsupported"
    # Without the read grant the case is invisible: the answer is the unknown-id one.
    ungranted = _decide(service, scene.principal, transport=CaptureTransport.REMOTE_CLIENT)
    assert ungranted.error is not None
    assert ungranted.error.code.value == "not_found"
    assert ungranted.error.safe_details == ("review_case_id",)
    assert plane.requests == []


# ---- KLP-AC-039: structure ------------------------------------------------------------------


def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    (found,) = (
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )
    return found


def _calls(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            func = inner.func
            names.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    return names


def test_the_knowledge_branch_never_sees_operator_authority() -> None:
    for name in ("_knowledge_review_decide", "_knowledge_review_case", "_knowledge_review_listed"):
        assert "_operator_authority" not in _calls(_method(name)), name
    assert "derive_knowledge_review_authority" in _calls(_method("_knowledge_review_decide"))
    # The legacy branches keep it; the Knowledge branch returns before they run.
    decide = _method("_review_decide")
    source = ast.unparse(decide)
    assert source.index("_knowledge_review_decide(") < source.index("_operator_authority(")
