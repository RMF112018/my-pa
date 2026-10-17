"""Who a record lineage S1 write is made by (S1 contract section 6.1).

`lineage_authority` derives the `(authority_class, decision_channel)` pair an S1
write records, through the one Knowledge derivation
(`domain.policy.knowledge_review_authority.derive_knowledge_review_authority`),
with the server-stamped operator surface, transport, operator flag,
authenticated client and grant-ceiling flag -- and **both allowlists empty**.
The Knowledge operator-review and Knowledge Manager allowlists are never read,
reused or widened here: their clients belong to Knowledge profiles that hold no
S1 capability, and S1 introduces no lineage allowlist. With both empty the
derivation cannot return `remote_operator_attested`, so in S1:

* an **attested** write (`issues.project_links.*`, and the S1 membership and
  association writes) is admitted only for `local_operator` -- the CLI or the
  HTTP gateway's stamped operator surface -- and is `denied` otherwise, before
  any row is written and before any replay lookup;
* a **recorded** write (`issues.create`, `issues.update`) is admitted for any
  caller the ordinary grant and purpose rules admitted, and records the class
  and channel on the Issue revision.

An inconsistent composition is `internal_error` and a remote transport without
a client is `unsupported`, as for Knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.application.authorization import Authorization
from my_pa.application.errors import DeniedError, InternalError, UnsupportedError
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeDecisionChannel,
    KnowledgeReviewAuthorityClass,
)
from my_pa.domain.lineage.vocabulary import (
    ATTESTED_AUTHORITY_CLASSES,
    ATTESTED_DECISION_CHANNELS,
)
from my_pa.domain.policy.knowledge_review_authority import (
    InconsistentKnowledgeReviewCompositionError,
    UnsupportedKnowledgeReviewCompositionError,
    derive_knowledge_review_authority,
)

__all__ = ["LineageAuthority", "attested_lineage_authority", "lineage_authority"]


@dataclass(frozen=True, slots=True)
class LineageAuthority:
    """The authority class and decision channel one S1 write records."""

    authority_class: KnowledgeReviewAuthorityClass
    decision_channel: KnowledgeDecisionChannel


def lineage_authority(authorization: Authorization) -> LineageAuthority:
    """The pair a recorded S1 write stores, from server-stamped context only."""
    failure: InternalError | UnsupportedError | None = None
    try:
        authority, channel = derive_knowledge_review_authority(
            operator_surface=authorization.operator_surface,
            transport=authorization.transport,
            principal_is_operator=authorization.principal.is_operator,
            authenticated_client_id=authorization.authenticated_client_id,
            # Section 6.1: never the Knowledge allowlists.
            operator_review_allowlist=frozenset(),
            manager_allowlist=frozenset(),
            capability_grants_present=authorization.capability_grants is not None,
        )
    except InconsistentKnowledgeReviewCompositionError:
        failure = InternalError()
    except UnsupportedKnowledgeReviewCompositionError:
        failure = UnsupportedError()
    if failure is not None:
        raise failure
    return LineageAuthority(authority_class=authority, decision_channel=channel)


def attested_lineage_authority(authorization: Authorization) -> LineageAuthority:
    """The pair an attested S1 write stores; `denied` unless local-operator."""
    derived = lineage_authority(authorization)
    if (
        derived.authority_class.value not in ATTESTED_AUTHORITY_CLASSES
        or derived.decision_channel.value not in ATTESTED_DECISION_CHANNELS
    ):
        raise DeniedError()
    return derived
