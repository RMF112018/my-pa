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

**S3.1** (S3.1 contract section 6.1) opens the 14 lineage writes the operator
directives name to any admitted caller and adds `lineage_write_provenance`:
the same derivation, mapped to the provenance every fact row of an open write
records. The human channel (`local_operator` with `local_cli` or `local_web`)
is `user_confirmed`; a remote client (`ordinary_reviewer` /
`remote_interactive`, its OAuth client id recorded) and stdio MCP or another
unstamped local caller (`ordinary_reviewer` / `local_unattested`, no client
id) are `client_identified`. It never raises `DeniedError`: an open write is
never refused for want of attestation. The client-declared `user_directed`
flag is stored verbatim as `user_directed_claim`; it upgrades nothing, and the
human channel may not send it (`invalid_request` / `user_directed`).
`attested_lineage_authority` is now used only by the attested set (Issue close
and reopen, the closed-Issue correction, the backfill plan and the 3 confirms).
"""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.application.authorization import Authorization
from my_pa.application.errors import (
    DeniedError,
    InternalError,
    InvalidRequestError,
    SafeDetail,
    UnsupportedError,
)
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeDecisionChannel,
    KnowledgeReviewAuthorityClass,
)
from my_pa.domain.lineage.vocabulary import (
    ATTESTED_AUTHORITY_CLASSES,
    ATTESTED_DECISION_CHANNELS,
    MAX_ASSERTING_CLIENT_ID_CHARACTERS,
    AcceptanceBasis,
)
from my_pa.domain.policy.knowledge_review_authority import (
    InconsistentKnowledgeReviewCompositionError,
    UnsupportedKnowledgeReviewCompositionError,
    derive_knowledge_review_authority,
)

__all__ = [
    "LineageAuthority",
    "LineageProvenance",
    "attested_lineage_authority",
    "lineage_authority",
    "lineage_write_provenance",
]


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


@dataclass(frozen=True, slots=True)
class LineageProvenance:
    """What every fact row of one open lineage write records (S3.1 section 4.1).

    Server-derived: nothing in a payload reaches any field but
    `user_directed_claim`, which is the client's own unverified statement.
    """

    authority_class: KnowledgeReviewAuthorityClass
    decision_channel: KnowledgeDecisionChannel
    acceptance_basis: AcceptanceBasis
    asserting_client_id: str | None
    user_directed_claim: bool


def lineage_write_provenance(
    authorization: Authorization, *, user_directed: bool
) -> LineageProvenance:
    """The provenance an open S3.1 lineage write records; never `denied`.

    Section 6.1: the pair through `lineage_authority` (both allowlists empty,
    unchanged), then `local_operator` with a local operator channel is
    `user_confirmed` (refusing `user_directed=True`), and `ordinary_reviewer`
    with `remote_interactive` or `local_unattested` is `client_identified`.
    Any other pair -- `remote_operator_attested`, unreachable with both
    allowlists empty -- is `internal_error`.
    """
    derived = lineage_authority(authorization)
    authority = derived.authority_class
    channel = derived.decision_channel
    if (
        authority is KnowledgeReviewAuthorityClass.LOCAL_OPERATOR
        and channel.value in ATTESTED_DECISION_CHANNELS
    ):
        if user_directed:
            # The human channel is the directing user: the claim would be
            # meaningless, and the database refuses it.
            raise InvalidRequestError(SafeDetail.USER_DIRECTED)
        return LineageProvenance(
            authority_class=authority,
            decision_channel=channel,
            acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
            asserting_client_id=None,
            user_directed_claim=False,
        )
    if authority is KnowledgeReviewAuthorityClass.ORDINARY_REVIEWER:
        if channel is KnowledgeDecisionChannel.REMOTE_INTERACTIVE:
            client = authorization.authenticated_client_id
            if client is None or not 1 <= len(client) <= MAX_ASSERTING_CLIENT_ID_CHARACTERS:
                raise InternalError()
            return LineageProvenance(
                authority_class=authority,
                decision_channel=channel,
                acceptance_basis=AcceptanceBasis.CLIENT_IDENTIFIED,
                asserting_client_id=client,
                user_directed_claim=user_directed,
            )
        if channel is KnowledgeDecisionChannel.LOCAL_UNATTESTED:
            return LineageProvenance(
                authority_class=authority,
                decision_channel=channel,
                acceptance_basis=AcceptanceBasis.CLIENT_IDENTIFIED,
                asserting_client_id=None,
                user_directed_claim=user_directed,
            )
    raise InternalError()
