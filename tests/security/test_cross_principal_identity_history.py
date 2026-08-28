"""An opaque identity-history continuation cannot cross a Principal boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.application.identity_history import IdentityHistoryService
from my_pa.domain.relationship.identity_history import (
    IdentityHistoryCursorError,
    IdentityHistoryEntry,
    IdentityHistoryOperation,
    IdentityHistoryPosition,
    IdentityHistorySource,
)

PRINCIPAL_A = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY = "ent_aaaa0001aaaa0001"
WHEN = datetime(2026, 8, 28, 12, tzinfo=UTC)


class _PartitionedQuery:
    def entries(
        self,
        principal_id: str,
        entity_id: str,
        *,
        limit: int,
        after: IdentityHistoryPosition | None = None,
    ) -> tuple[tuple[IdentityHistoryEntry, int], ...]:
        del entity_id, after
        if principal_id != PRINCIPAL_A:
            return ()
        entries = tuple(
            IdentityHistoryEntry(
                history_id=f"emut_aaaa0001aaaa0{index}",
                occurred_at=WHEN,
                source=IdentityHistorySource.DIRECT_MUTATION,
                operation=IdentityHistoryOperation.UPDATE,
                involved_entity_ids=(ENTITY,),
                changes=(),
                actor_class="user",
            )
            for index in (1, 2)
        )
        return tuple((entry, 1) for entry in entries[:limit])


def test_another_principal_cannot_replay_a_history_cursor() -> None:
    service = IdentityHistoryService()
    issued = service.history(
        _PartitionedQuery(), principal_id=PRINCIPAL_A, entity_id=ENTITY, page_size=1
    )
    assert issued.next_cursor is not None

    with pytest.raises(IdentityHistoryCursorError):
        service.history(
            _PartitionedQuery(),
            principal_id=PRINCIPAL_B,
            entity_id=ENTITY,
            page_size=1,
            after=issued.next_cursor,
        )
