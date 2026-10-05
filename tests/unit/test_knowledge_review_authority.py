"""Who a Knowledge Review decision is made by (KLP-WP-04, R6 section 3.2).

FAST, pure. `derive_knowledge_review_authority` against matrix
`profile_contract.review_authority_derivation`, every row, plus the R6 section
3.2 item 5 negatives this module owns:

* (b) an `McpAccess` built without a transport (default LOCAL) -> ordinary/unattested;
* (c) an `Authorization` built without `operator_surface` -> ordinary_reviewer;
* (d) `operator_surface` with `REMOTE_CLIENT`, a client id or a grant ceiling ->
  `ValueError` (KLP-R6V-102; the matrix row "any surface + grants ->
  ordinary_reviewer" is superseded by R6 section 3.2 item 1 -- KLP-R6V-203,
  recorded as a slice DEV: surface + grants is refused, and grants *without* a
  surface derive ordinary_reviewer / local_unattested);
* (h) a CLI operator and an HTTP-gateway operator -> local_operator with
  local_cli / local_web.

KLP-AC-039 / KLP-AC-114: derivation half (the decide wiring is slice C's).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from my_pa.adapters.mcp.server import McpAccess
from my_pa.application.authorization import Authorization
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeDecisionChannel,
    KnowledgeReviewAuthorityClass,
)
from my_pa.domain.policy.decision import POLICY_VERSION, PolicyDecision
from my_pa.domain.policy.knowledge_review_authority import (
    InconsistentKnowledgeReviewCompositionError,
    UnsupportedKnowledgeReviewCompositionError,
    derive_knowledge_review_authority,
)

MATRIX: Final = json.loads(
    (Path(__file__).parents[1] / "architecture" / "klp_implementation_matrix_r6.json").read_text(
        encoding="utf-8"
    )
)
REVIEWER: Final = "synthetic-operator-review"
CHAT: Final = "synthetic-chatllm"
DISCOVERY: Final = "synthetic-discovery"
ALLOWLIST: Final = frozenset({REVIEWER})
LOCAL: Final = CaptureTransport.LOCAL
REMOTE: Final = CaptureTransport.REMOTE_CLIENT
ORDINARY: Final = KnowledgeReviewAuthorityClass.ORDINARY_REVIEWER
PRINCIPAL: Final = Principal(
    principal_id="prn_klpwp04authority1", kind=PrincipalKind.OPERATOR, authenticated=True
)


def _derive(
    *,
    surface: OperatorSurface | None = None,
    transport: CaptureTransport = LOCAL,
    operator: bool = True,
    client: str | None = None,
    grants: bool = False,
) -> tuple[KnowledgeReviewAuthorityClass, KnowledgeDecisionChannel]:
    return derive_knowledge_review_authority(
        operator_surface=surface,
        transport=transport,
        principal_is_operator=operator,
        authenticated_client_id=client,
        operator_review_allowlist=ALLOWLIST,
        capability_grants_present=grants,
    )


# ---- the matrix table, row by row ------------------------------------------------


def test_the_matrix_table_has_the_rows_this_module_proves() -> None:
    rows = MATRIX["profile_contract"]["review_authority_derivation"]
    assert len(rows) == 9
    assert {row["authority_class"] for row in rows} == {
        "local_operator",
        "ordinary_reviewer",
        "remote_operator_attested",
        "REFUSED (InternalError: inconsistent composition)",
        "REFUSED for Knowledge review.decide (unsupported)",
    }


@pytest.mark.parametrize(
    ("surface", "channel"),
    [
        (OperatorSurface.CLI, KnowledgeDecisionChannel.LOCAL_CLI),
        (OperatorSurface.HTTP_GATEWAY, KnowledgeDecisionChannel.LOCAL_WEB),
    ],
)
def test_rows_1_2_and_h_a_stamped_local_operator_is_local_operator(
    surface: OperatorSurface, channel: KnowledgeDecisionChannel
) -> None:
    assert _derive(surface=surface) == (KnowledgeReviewAuthorityClass.LOCAL_OPERATOR, channel)


@pytest.mark.parametrize("operator", [True, False])
def test_row_3_an_unstamped_local_caller_is_unattested(operator: bool) -> None:
    assert _derive(operator=operator) == (ORDINARY, KnowledgeDecisionChannel.LOCAL_UNATTESTED)


@pytest.mark.parametrize("surface", list(OperatorSurface))
def test_row_4_a_stamped_non_operator_is_unattested(surface: OperatorSurface) -> None:
    assert _derive(surface=surface, operator=False) == (
        ORDINARY,
        KnowledgeDecisionChannel.LOCAL_UNATTESTED,
    )


@pytest.mark.parametrize("operator", [True, False])
def test_row_5_a_grant_ceiling_without_a_surface_is_never_local_operator(operator: bool) -> None:
    """KLP-R6V-203: grants without a surface derive ordinary_reviewer / local_unattested."""
    assert _derive(operator=operator, grants=True) == (
        ORDINARY,
        KnowledgeDecisionChannel.LOCAL_UNATTESTED,
    )


@pytest.mark.parametrize("operator", [True, False])
def test_row_6_an_operator_review_client_is_remote_operator_attested(operator: bool) -> None:
    assert _derive(transport=REMOTE, client=REVIEWER, operator=operator) == (
        KnowledgeReviewAuthorityClass.REMOTE_OPERATOR_ATTESTED,
        KnowledgeDecisionChannel.REMOTE_OPERATOR_REVIEW,
    )


@pytest.mark.parametrize("client", [CHAT, DISCOVERY, f"{REVIEWER}-x", REVIEWER[:-1]])
def test_row_7_and_e_f_any_other_remote_client_is_interactive(client: str) -> None:
    assert _derive(transport=REMOTE, client=client) == (
        ORDINARY,
        KnowledgeDecisionChannel.REMOTE_INTERACTIVE,
    )


def test_row_7_an_empty_operator_review_allowlist_attests_nobody() -> None:
    assert derive_knowledge_review_authority(
        operator_surface=None,
        transport=REMOTE,
        principal_is_operator=True,
        authenticated_client_id=REVIEWER,
        operator_review_allowlist=frozenset(),
    ) == (ORDINARY, KnowledgeDecisionChannel.REMOTE_INTERACTIVE)


@pytest.mark.parametrize("surface", list(OperatorSurface))
@pytest.mark.parametrize(
    ("transport", "client", "grants"),
    [
        (REMOTE, REVIEWER, False),
        (REMOTE, None, False),
        (LOCAL, REVIEWER, False),
        (LOCAL, None, True),
        (REMOTE, CHAT, True),
    ],
)
def test_row_8_a_surface_with_a_remote_composition_is_refused(
    surface: OperatorSurface, transport: CaptureTransport, client: str | None, grants: bool
) -> None:
    with pytest.raises(InconsistentKnowledgeReviewCompositionError):
        _derive(surface=surface, transport=transport, client=client, grants=grants)


@pytest.mark.parametrize("operator", [True, False])
def test_row_9_and_g_the_remote_transport_without_a_client_is_unsupported(operator: bool) -> None:
    with pytest.raises(UnsupportedKnowledgeReviewCompositionError):
        _derive(transport=REMOTE, operator=operator)


def test_a_local_transport_with_a_client_never_gains_operator_authority() -> None:
    """Not a matrix row: most-restrictive -- a client on LOCAL is unattested."""
    assert _derive(client=REVIEWER) == (ORDINARY, KnowledgeDecisionChannel.LOCAL_UNATTESTED)


def test_principal_kind_alone_never_qualifies() -> None:
    """Every surface authenticates an OPERATOR principal; without a stamp it is ordinary."""
    assert PRINCIPAL.is_operator
    assert _derive(operator=PRINCIPAL.is_operator)[0] is ORDINARY


# ---- (b), (c), (d): what the compositions carry ------------------------------------


def test_b_an_mcp_access_without_a_transport_derives_unattested() -> None:
    access = McpAccess(principal=PRINCIPAL)
    assert access.transport is LOCAL
    assert not hasattr(access, "operator_surface")
    assert derive_knowledge_review_authority(
        operator_surface=None,
        transport=access.transport,
        principal_is_operator=access.principal.is_operator,
        authenticated_client_id=access.authenticated_client_id,
        operator_review_allowlist=ALLOWLIST,
        capability_grants_present=access.allowed_capability_purposes is not None,
    ) == (ORDINARY, KnowledgeDecisionChannel.LOCAL_UNATTESTED)


def _authorization(**overrides: object) -> Authorization:
    values: dict[str, object] = {
        "principal": PRINCIPAL,
        "capability": Capability.REVIEW_DECIDE,
        "purpose": Purpose.REVIEW_DISPOSITION,
        "correlation_id": "corr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "request_id": "req-klpwp04",
        "audit_id": "aud_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "at": datetime(2026, 10, 5, 12, tzinfo=UTC),
        "decision": PolicyDecision(allowed=True, policy_version=POLICY_VERSION),
        "requested_source_ids": frozenset(),
        "enrollments": (),
    }
    values.update(overrides)
    return Authorization(**values)  # type: ignore[arg-type]


def test_c_an_authorization_without_a_surface_derives_ordinary_reviewer() -> None:
    authorization = _authorization()
    assert authorization.operator_surface is None
    assert (
        derive_knowledge_review_authority(
            operator_surface=authorization.operator_surface,
            transport=authorization.transport,
            principal_is_operator=authorization.principal.is_operator,
            authenticated_client_id=authorization.authenticated_client_id,
            operator_review_allowlist=ALLOWLIST,
            capability_grants_present=authorization.capability_grants is not None,
        )[0]
        is ORDINARY
    )


@pytest.mark.parametrize("surface", list(OperatorSurface))
@pytest.mark.parametrize(
    "overrides",
    [
        {"transport": REMOTE},
        {"authenticated_client_id": REVIEWER},
        {"capability_grants": frozenset()},
        {"capability_grants": frozenset({(Capability.REVIEW_DECIDE, None)})},
    ],
    ids=["remote-transport", "client", "empty-grants", "grants"],
)
def test_d_a_surface_with_a_remote_composition_cannot_be_built(
    surface: OperatorSurface, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="operator_surface"):
        _authorization(operator_surface=surface, **overrides)


@pytest.mark.parametrize("surface", list(OperatorSurface))
def test_d_control_a_surface_on_a_local_composition_is_built(surface: OperatorSurface) -> None:
    assert _authorization(operator_surface=surface).operator_surface is surface
