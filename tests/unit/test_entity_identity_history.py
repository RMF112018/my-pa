"""Identity history keeps exact ledger states and binds every continuation input."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.identity_history import IdentityHistoryService
from my_pa.domain.relationship.identity_history import (
    IdentityHistoryChange,
    IdentityHistoryCursorError,
    IdentityHistoryEntry,
    IdentityHistoryOperation,
    IdentityHistoryPosition,
    IdentityHistorySource,
)

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL: Final = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY: Final = "ent_aaaa0001aaaa0001"
OTHER_ENTITY: Final = "ent_bbbb0002bbbb0002"
WHEN: Final = datetime(2026, 8, 28, 12, tzinfo=UTC)


def _entry(index: int) -> IdentityHistoryEntry:
    return IdentityHistoryEntry(
        history_id=f"emut_aaaa0001aaaa0{index}",
        occurred_at=WHEN + timedelta(minutes=index),
        source=IdentityHistorySource.DIRECT_MUTATION,
        operation=IdentityHistoryOperation.UPDATE,
        involved_entity_ids=(ENTITY,),
        changes=(
            IdentityHistoryChange(
                family="entity",
                record_id=ENTITY,
                effect_kind=IdentityHistoryOperation.UPDATE.value,
                before_state={"version": index},
                # Deliberately receipt-shaped: history returns what the ledger
                # authoritatively holds and does not invent a full snapshot.
                after_state={"entity_id": ENTITY, "entity_version": index + 1},
            ),
        ),
        actor_class="user",
    )


class _Query:
    def __init__(self, entries: tuple[IdentityHistoryEntry, ...]) -> None:
        self._entries = entries
        self.positions: list[IdentityHistoryPosition | None] = []

    def entries(
        self,
        principal_id: str,
        entity_id: str,
        *,
        limit: int,
        after: IdentityHistoryPosition | None = None,
    ) -> tuple[tuple[IdentityHistoryEntry, int], ...]:
        assert principal_id == PRINCIPAL
        assert entity_id == ENTITY
        self.positions.append(after)
        start = 0
        if after is not None:
            start = next(
                index + 1
                for index, entry in enumerate(self._entries)
                if entry.history_id == after.history_id
            )
        return tuple((entry, 1) for entry in self._entries[start : start + limit])


def test_history_pages_without_rewriting_the_ledger_states() -> None:
    query = _Query((_entry(1), _entry(2), _entry(3)))
    service = IdentityHistoryService()

    first = service.history(query, principal_id=PRINCIPAL, entity_id=ENTITY, page_size=2)
    second = service.history(
        query,
        principal_id=PRINCIPAL,
        entity_id=ENTITY,
        page_size=2,
        after=first.next_cursor,
    )

    assert [entry.history_id for entry in first.entries + second.entries] == [
        _entry(1).history_id,
        _entry(2).history_id,
        _entry(3).history_id,
    ]
    assert first.entries[0].changes[0].after_state == {
        "entity_id": ENTITY,
        "entity_version": 2,
    }
    assert first.is_truncated and first.next_cursor is not None
    assert not second.is_truncated and second.next_cursor is None
    assert query.positions[1] == IdentityHistoryPosition(
        _entry(2).occurred_at, 1, _entry(2).history_id
    )


@pytest.mark.parametrize(
    ("principal_id", "entity_id", "page_size"),
    ((OTHER_PRINCIPAL, ENTITY, 2), (PRINCIPAL, OTHER_ENTITY, 2), (PRINCIPAL, ENTITY, 3)),
)
def test_cursor_is_bound_to_principal_entity_and_page_size(
    principal_id: str, entity_id: str, page_size: int
) -> None:
    query = _Query((_entry(1), _entry(2), _entry(3)))
    service = IdentityHistoryService()
    issued = service.history(query, principal_id=PRINCIPAL, entity_id=ENTITY, page_size=2)

    with pytest.raises(IdentityHistoryCursorError):
        service.history(
            query,
            principal_id=principal_id,
            entity_id=entity_id,
            page_size=page_size,
            after=issued.next_cursor,
        )


@pytest.mark.parametrize("token", ("", "not-a-cursor", "A" * 513))
def test_malformed_cursor_has_one_safe_refusal(token: str) -> None:
    with pytest.raises(IdentityHistoryCursorError):
        IdentityHistoryService().history(
            _Query((_entry(1),)),
            principal_id=PRINCIPAL,
            entity_id=ENTITY,
            page_size=2,
            after=token,
        )


def test_split_is_in_the_generic_history_vocabulary_without_implementing_split() -> None:
    assert IdentityHistoryOperation("split") is IdentityHistoryOperation.SPLIT
