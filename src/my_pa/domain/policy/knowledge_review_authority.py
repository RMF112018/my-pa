"""Who a Knowledge Review decision is made by (KLP-WP-04, R6 section 3.2).

`derive_knowledge_review_authority` is the single, pure derivation of the
`(operator_authority_class, decision_channel)` pair a Knowledge `review.decide`
persists. Its table is matrix `profile_contract.review_authority_derivation`:

* `local_operator` needs an explicitly stamped operator surface (CLI or the HTTP
  gateway), the LOCAL transport, an operator principal and no client;
* `remote_operator_attested` needs the remote transport and a client in the
  exact operator-review allowlist or -- KLP Step 8 -- the exact Knowledge
  Manager allowlist. The manager reuses this persisted class and the
  `remote_operator_review` channel, so no new vocabulary and no migration;
* any other remote client is an `ordinary_reviewer` deciding interactively;
* every other local caller -- stdio MCP, an unstamped surface, a non-operator, a
  grant-ceilinged composition -- is an `ordinary_reviewer`, unattested.

Two compositions are refused rather than classified:

* an operator surface together with the remote transport, a client id or a
  grant ceiling is an inconsistent composition (`Authorization.__post_init__`
  already refuses to build one; KLP-R6V-102). Raised as
  `InconsistentKnowledgeReviewCompositionError`, which the application maps to
  `internal_error`;
* the remote transport with no client (the remote capture HTTP route) cannot
  decide a Knowledge case at all. Raised as
  `UnsupportedKnowledgeReviewCompositionError`, mapped to `unsupported`.

No request payload field reaches this function, and `PrincipalKind` alone never
qualifies anyone: every surface today authenticates an operator principal.
"""

from __future__ import annotations

from typing import Final

from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeDecisionChannel,
    KnowledgeReviewAuthorityClass,
)

__all__ = [
    "InconsistentKnowledgeReviewCompositionError",
    "UnsupportedKnowledgeReviewCompositionError",
    "derive_knowledge_review_authority",
]

_LOCAL_CHANNEL: Final = {
    OperatorSurface.CLI: KnowledgeDecisionChannel.LOCAL_CLI,
    OperatorSurface.HTTP_GATEWAY: KnowledgeDecisionChannel.LOCAL_WEB,
}


class InconsistentKnowledgeReviewCompositionError(ValueError):
    """An operator surface was stamped on a remote or grant-ceilinged composition."""


class UnsupportedKnowledgeReviewCompositionError(ValueError):
    """The remote transport without an authenticated client cannot decide a Knowledge case."""


def derive_knowledge_review_authority(
    *,
    operator_surface: OperatorSurface | None,
    transport: CaptureTransport,
    principal_is_operator: bool,
    authenticated_client_id: str | None,
    operator_review_allowlist: frozenset[str],
    manager_allowlist: frozenset[str],
    capability_grants_present: bool = False,
) -> tuple[KnowledgeReviewAuthorityClass, KnowledgeDecisionChannel]:
    """The authority class and decision channel of one Knowledge decision."""
    remote = transport is CaptureTransport.REMOTE_CLIENT
    if operator_surface is not None and (
        remote or authenticated_client_id is not None or capability_grants_present
    ):
        raise InconsistentKnowledgeReviewCompositionError(
            "an operator surface cannot accompany a remote transport, a client or a grant ceiling"
        )
    if remote:
        if authenticated_client_id is None:
            raise UnsupportedKnowledgeReviewCompositionError(
                "the remote transport without a client cannot decide a Knowledge case"
            )
        if (
            authenticated_client_id in operator_review_allowlist
            or authenticated_client_id in manager_allowlist
        ):
            return (
                KnowledgeReviewAuthorityClass.REMOTE_OPERATOR_ATTESTED,
                KnowledgeDecisionChannel.REMOTE_OPERATOR_REVIEW,
            )
        return (
            KnowledgeReviewAuthorityClass.ORDINARY_REVIEWER,
            KnowledgeDecisionChannel.REMOTE_INTERACTIVE,
        )
    if (
        operator_surface is not None
        and principal_is_operator
        and authenticated_client_id is None
        and not capability_grants_present
    ):
        return KnowledgeReviewAuthorityClass.LOCAL_OPERATOR, _LOCAL_CHANNEL[operator_surface]
    return (
        KnowledgeReviewAuthorityClass.ORDINARY_REVIEWER,
        KnowledgeDecisionChannel.LOCAL_UNATTESTED,
    )
