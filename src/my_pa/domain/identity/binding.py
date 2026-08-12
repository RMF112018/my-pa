"""The bridge between the durable identity plane and the capture-plane identifier.

WP-01 established the durable identity plane: `identity.user_accounts` mints an
opaque `principal_id` **UUID** at first sight of a validated Entra `(tid, oid)`
pair, and every identity-plane table partitions on that UUID. The knowledge
schema predates it and partitions on a **text** identifier of the form
`prn_[A-Za-z0-9]{8,64}` (`IdKind.PRINCIPAL`). WP-03 makes the capture plane's
owner an authorization input, which requires the two vocabularies to name the
same person deterministically — this module is that determination, stated once.

* `capture_principal_id` renders a durable UUID as the capture plane's text
  form: `prn_` followed by the UUID's 32 hex characters. It is injective and
  fits the existing identifier constraint, so no stored row and no CHECK has to
  change shape for a durable principal to own a capture.
* `durable_principal_uuid` is the inverse where an inverse exists and a stable
  digest where it does not: a bound-form identifier recovers its UUID exactly,
  and any other well-formed `prn_...` maps through UUIDv5 under this module's
  namespace. The function is **total over valid principal identifiers** on
  purpose — a legacy process-minted principal still resolves to one stable
  partition rather than to a refusal that would strand its rows, and two
  distinct identifiers cannot share a partition without a UUIDv5 collision.
* `LOCAL_OPERATOR_UUID` is the one durable principal a loopback, single-operator
  composition acts as. It is a fixed UUIDv5, not a per-process mint: `D-67`
  measured that a gateway restart used to mint a new principal, and under
  WP-03's owner-scoped authorization that would have made every stored capture
  unrevisable after a restart. One constant is what keeps `QC-AC-013` provable
  across processes while the owner is enforced.

Nothing here validates a token or reads a store. Claim validation stays in
`user_account.validate_token_claims`, and rejection of caller-supplied identity
stays in `reject_caller_supplied_principal`; this module only translates an
identity that has already been established.
"""

from __future__ import annotations

import re
from typing import Final
from uuid import NAMESPACE_URL, UUID, uuid5

from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "LOCAL_OPERATOR_UUID",
    "PRINCIPAL_NAMESPACE",
    "capture_principal_id",
    "durable_principal_uuid",
]

#: The UUIDv5 namespace for every principal identifier this module digests.
#: Derived from a URL that resolves nowhere (`.invalid` is reserved by RFC 2606),
#: so the namespace cannot collide with one derived from a real resource.
PRINCIPAL_NAMESPACE: Final[UUID] = uuid5(NAMESPACE_URL, "https://my-pa.invalid/principals")

#: The one durable principal of a loopback, single-operator composition. Fixed,
#: so two processes — or one process before and after a restart — act as the
#: same owner, which is what `QC-AC-013` requires once the owner authorizes.
LOCAL_OPERATOR_UUID: Final[UUID] = uuid5(PRINCIPAL_NAMESPACE, "local-operator")

#: `prn_` + 32 hex characters: the bound form. 32 lowercase hex fits the
#: existing `IdKind.PRINCIPAL` shape, so a bound identifier is indistinguishable
#: from any other valid principal identifier to every constraint already merged.
_BOUND_PREFIX: Final = "prn_"

#: Exactly 32 **lowercase** hex characters, the canonical rendering `UUID.hex`
#: produces. Anchored to the canonical form rather than to "whatever
#: `UUID(hex=...)` accepts", because the constructor also accepts uppercase —
#: and letting `prn_AAAA...` and `prn_aaaa...` recover the same UUID would give
#: two distinct valid identifiers one partition, breaking the injectivity the
#: module docstring promises. Uppercase falls through to the digest instead.
_BOUND_SUFFIX: Final = re.compile(r"[0-9a-f]{32}")


def capture_principal_id(principal_uuid: UUID) -> str:
    """Render a durable identity-plane UUID as the capture plane's text form."""
    rendered = f"{_BOUND_PREFIX}{principal_uuid.hex}"
    return validate_identifier(rendered, IdKind.PRINCIPAL)


def durable_principal_uuid(principal_id: str) -> UUID:
    """Resolve a capture-plane identifier to its one durable UUID partition.

    Exact inverse for the bound form; a stable UUIDv5 digest for every other
    valid identifier. Raises what `validate_identifier` raises for anything
    that is not a principal identifier at all — resolution is total over the
    valid vocabulary and closed outside it.
    """
    validated = validate_identifier(principal_id, IdKind.PRINCIPAL)
    suffix = validated[len(_BOUND_PREFIX) :]
    if _BOUND_SUFFIX.fullmatch(suffix):
        return UUID(hex=suffix)
    return uuid5(PRINCIPAL_NAMESPACE, validated)
