"""The pre-`ded76e225` search statement, kept verbatim as the equivalence reference.

`ded76e225` stopped re-evaluating the text criterion where it cannot change the
answer: a text-only search marks every retained row `text_hit` (each passed the
criterion in WHERE) and leaves its rank unguarded, and only ids plus text keeps
the `case((text_hit, rank), 0)` guard, now moved out of `_text_criteria`. The
operator's direction on WP5-R1 F-1 requires every performance change to be
result-equivalent, proven against the old formulation (WP5-R4 R4-1): these are
`_text_criteria` and `_search_statement` as they stood at `ded76e225^`, changed
only in their names. Test code only; never imported by `src`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Select,
    Text,
    and_,
    case,
    exists,
    func,
    literal,
    or_,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import ARRAY

from my_pa.contracts.ports import CommunicationSearchQuery
from my_pa.infrastructure.persistence.communications import (
    _after,
    _fold,
    _integer_rank,
    _mine,
    _not_excluded,
    _simple_document,
    _snippet,
    _total_order,
    _tsquery,
)
from my_pa.infrastructure.persistence.principal_scope import matching_partition_criterion
from my_pa.infrastructure.persistence.tables import (
    communication_identifiers,
    communication_mailbox_items,
    communication_messages,
    communication_observations,
    communication_participants,
)

__all__ = ["reference_search_statement", "reference_text_criteria"]


def reference_text_criteria(
    query: CommunicationSearchQuery,
) -> tuple[ColumnElement[bool], ColumnElement[Any]]:
    """`(text_hit, rank)` for a query with searchable terms (section 14 rank)."""
    if query.query is None:
        raise ValueError("a text criterion needs a query")
    messages = communication_messages
    matches: list[ColumnElement[bool]] = []
    ranks: list[ColumnElement[Any]] = []
    if query.english_terms:
        english = _tsquery("english", query.query)
        matches.append(messages.c.search_document.bool_op("@@")(english))
        ranks.append(_integer_rank(messages.c.search_document, english))
    if query.text_fallback:
        simple = _tsquery("simple", query.query)
        matches.append(_simple_document().bool_op("@@")(simple))
        ranks.append(_integer_rank(_simple_document(), simple))
    # WP4-R2 G5: each field is confirmed alone, so a phrase never spans the
    # end of the subject and the start of the text.
    fields = (
        _fold(func.coalesce(messages.c.subject, "")),
        _fold(func.coalesce(messages.c.search_text, "")),
    )
    confirmed = [
        or_(*(func.strpos(field, _fold(literal(phrase))) > 0 for field in fields))
        for phrase in query.phrases
    ]
    text_hit = and_(or_(*matches), *confirmed)
    rank = ranks[0] if len(ranks) == 1 else func.greatest(*ranks)
    return text_hit, case((text_hit, rank), else_=literal(0, BigInteger))


def reference_search_statement(principal_id: str, query: CommunicationSearchQuery) -> Select[Any]:
    """One statement: candidates, tiers, collapse, keyset, page, snippets (module docstring)."""
    messages = communication_messages
    identifiers = communication_identifiers
    participants = communication_participants
    observations, items = communication_observations, communication_mailbox_items
    n_ids = len(query.identifiers)

    # The requested identifiers each message matched (the (principal, kind, value) index).
    id_hit: ColumnElement[Any] = literal(0)
    id_kinds: ColumnElement[Any] = literal([], ARRAY(Text))
    source: Any = messages
    if n_ids:
        matched = (
            select(
                identifiers.c.message_id,
                func.count(tuple_(identifiers.c.kind, identifiers.c.value).distinct()).label("hit"),
                func.array_agg(identifiers.c.kind.distinct()).label("kinds"),
            )
            .where(
                _mine(identifiers, principal_id),
                identifiers.c.extractor_version == query.identifier_version,
                tuple_(identifiers.c.kind, identifiers.c.value).in_(list(query.identifiers)),
            )
            .group_by(identifiers.c.message_id)
            .subquery("matched")
        )
        source = messages.outerjoin(matched, matched.c.message_id == messages.c.message_id)
        id_hit = func.coalesce(matched.c.hit, 0)
        id_kinds = func.coalesce(matched.c.kinds, literal([], ARRAY(Text)))

    # The criteria: a requested identifier, or the text; neither asked is a browse (R8).
    text_hit: ColumnElement[bool] | None = None
    rank: ColumnElement[Any] = literal(0, BigInteger)
    if query.query is not None:
        text_hit, rank = reference_text_criteria(query)
    criteria: list[ColumnElement[bool]] = []
    if n_ids and text_hit is not None:
        criteria.append(or_(id_hit > 0, text_hit))
    elif n_ids:
        criteria.append(id_hit > 0)
    elif text_hit is not None:
        criteria.append(text_hit)
    # WP4-R2 G4: a negated term excludes in every tier, an identifier match too.
    if query.excluded is not None:
        criteria.append(_not_excluded(query.excluded))

    # Structured filters intersect.
    if query.from_utc is not None:
        criteria.append(messages.c.message_time >= query.from_utc)
    if query.to_utc is not None:
        criteria.append(messages.c.message_time < query.to_utc + timedelta(seconds=1))
    if query.conversation_id is not None:
        criteria.append(messages.c.conversation_id == query.conversation_id)
    if query.folder_role is not None:
        criteria.append(
            exists(
                select(literal(1))
                .select_from(observations)
                .join(
                    items,
                    matching_partition_criterion(items, observations)
                    & (items.c.item_id == observations.c.item_id),
                )
                .where(
                    _mine(observations, principal_id),
                    items.c.message_id == messages.c.message_id,
                    observations.c.folder_role == query.folder_role,
                )
            )
        )
    overlap: ColumnElement[Any] = literal(0)
    if query.participants:
        overlap = (
            select(func.count(participants.c.address.distinct()))
            .where(
                _mine(participants, principal_id),
                participants.c.message_id == messages.c.message_id,
                participants.c.address.in_(list(query.participants)),
            )
            .scalar_subquery()
        )
        if query.participants_all:
            criteria.append(overlap == len(query.participants))
        else:
            criteria.append(overlap >= 1)

    tier: ColumnElement[Any] = literal(3)
    if n_ids:
        tier = case((id_hit == n_ids, 1), (id_hit > 0, 2), else_=3)
    group = func.coalesce(messages.c.conversation_id, messages.c.message_id)
    candidates = (
        select(
            messages.c.message_id,
            messages.c.conversation_id,
            messages.c.message_time,
            messages.c.subject,
            messages.c.sender_address,
            messages.c.has_attachments,
            messages.c.body_state,
            messages.c.search_text_version,
            messages.c.search_text_flags,
            messages.c.identity_conflict,
            messages.c.participants_reconciled,
            messages.c.participants_disagreed,
            messages.c.source_unavailable,
            (text_hit if text_hit is not None else literal(False)).label("text_hit"),
            tier.label("tier"),
            rank.label("rank"),
            overlap.label("overlap"),
            id_kinds.label("id_kinds"),
            group.label("group_key"),
        )
        .select_from(source)
        .where(_mine(messages, principal_id), *criteria)
        .subquery("candidates")
    )
    hits = func.count().over(partition_by=candidates.c.group_key).label("conversation_hits")
    ranked = select(candidates, hits)
    if query.collapse:
        # D9: the representative is the best message of its conversation by the
        # full total order; the keyset is applied after the collapse.
        ranked = ranked.distinct(candidates.c.group_key).order_by(
            candidates.c.group_key, *_total_order(candidates.c)
        )
    representatives = ranked.subquery("representatives")
    page = select(representatives)
    if query.after is not None:
        page = page.where(_after(representatives.c, query.after))
    page_rows = page.order_by(*_total_order(representatives.c)).limit(query.limit).subquery("page")
    return select(page_rows, _snippet(principal_id, query, page_rows).label("snippet")).order_by(
        *_total_order(page_rows.c)
    )
