"""Transaction locks shared by every external-identifier claim path.

The database's active-binding unique protects only active rows. Identity merge
also has to serialize against former claims and against a brand-new claim whose
key did not exist when analysis began. Domain-separated advisory locks cover
both dimensions without storing or logging the identifier value itself:

* an entity-scope key blocks any claim being added to a merge participant while
  its complete identifier population is discovered;
* a claim-value key serializes every active, retired, or superseded use of one
  normalized address.

All keys are acquired in numeric order and live until transaction end.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

__all__ = ["lock_identifier_claim_keys", "lock_identifier_entity_scopes"]


def _key(*parts: str) -> int:
    encoded = "\x1f".join(parts).encode("utf-8")
    digest = hashlib.sha256(encoded).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def _lock(connection: Connection, keys: Iterable[int]) -> None:
    for key in sorted(set(keys)):
        connection.execute(select(func.pg_advisory_xact_lock(key))).scalar_one()


def lock_identifier_entity_scopes(
    connection: Connection, principal_id: str, entity_ids: Iterable[str]
) -> None:
    """Block any identifier claim mutation for these Principal-owned entities."""
    _lock(
        connection,
        (_key("entity-identifier-scope", principal_id, entity_id) for entity_id in entity_ids),
    )


def lock_identifier_claim_keys(
    connection: Connection,
    principal_id: str,
    claims: Iterable[tuple[str, str]],
) -> None:
    """Serialize all states of each `(namespace, normalized_value)` claim."""
    _lock(
        connection,
        (
            _key("external-identifier-claim", principal_id, namespace, normalized_value)
            for namespace, normalized_value in claims
        ),
    )
