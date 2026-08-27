"""Shared Principal-owned context-target validation for Relationship Memory writes."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.common.identifiers import validate_identifier
from my_pa.domain.relationship.entity import EntityStatus
from my_pa.domain.relationship.memory import CONTEXT_TARGET_ID_KINDS, ContextLinkTargetType
from my_pa.infrastructure.persistence.principal_scope import capture_context, partition_criterion
from my_pa.infrastructure.persistence.tables import entities


def requested_entity_context_ids(links: tuple[Mapping[str, str], ...]) -> frozenset[str]:
    """Entity identifiers that must join the caller's mutation lock set."""
    return frozenset(
        link["target_id"]
        for link in links
        if link["target_type"] == ContextLinkTargetType.ENTITY.value
    )


def require_own_writable_context_targets(
    connection: Connection,
    principal_id: str,
    links: tuple[Mapping[str, str], ...],
    *,
    reject_merged: bool = False,
) -> None:
    """Refuse missing, foreign, merged, or presently unverifiable context targets."""
    for link in links:
        target_type = ContextLinkTargetType(link["target_type"])
        target_id = link["target_id"]
        validate_identifier(target_id, CONTEXT_TARGET_ID_KINDS[target_type])
        if target_type is not ContextLinkTargetType.ENTITY:
            raise UnknownScopeError("this build validates only entity context targets")
        row = connection.execute(
            select(entities.c.status).where(
                partition_criterion(entities, capture_context(principal_id)),
                entities.c.entity_id == target_id,
            )
        ).one_or_none()
        if row is None:
            raise UnknownScopeError("a context link names an entity outside this scope")
        if reject_merged and EntityStatus(row.status) is EntityStatus.MERGED_REDIRECT:
            raise UnknownScopeError("a context link names no writable entity in this scope")
