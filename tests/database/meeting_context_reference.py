"""The WP5-S3 per-pair context statement, kept verbatim as the equivalence reference.

WP5-R1 F-1 rewrote the text branch of `_context_statement` set-based (the
Project number's `simple` text once per message, behind a `strpos` superset
pre-filter; the message columns joined to the page only). The operator's
direction on F-1 requires the rewrite to be result-equivalent, proven against
the old formulation: this is that formulation, as it stood at `bc8464fe2`,
changed only in its name. Test code only; never imported by `src`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ColumnElement,
    DateTime,
    Integer,
    Select,
    Text,
    and_,
    case,
    column,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSQUERY
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import MeetingContextCandidateQuery, MeetingContextCandidateRow
from my_pa.infrastructure.persistence.communications import (
    _NO_TEXT_BODY_STATES,
    SNIPPET_CHARACTERS,
    _array,
    _config,
    _context_order,
    _integer_rank,
    _mine,
    _simple_document,
    _title_tsquery_text,
    _to_candidate,
)
from my_pa.infrastructure.persistence.principal_scope import matching_partition_criterion
from my_pa.infrastructure.persistence.tables import (
    communication_identifiers,
    communication_messages,
    communication_participants,
)

__all__ = ["per_pair_candidates"]


def per_pair_candidates(
    connection: Connection, principal_id: str, query: MeetingContextCandidateQuery
) -> tuple[MeetingContextCandidateRow, ...]:
    """What `context_candidates` answered at `bc8464fe2`, row for row."""
    if not query.meetings:
        return ()
    return tuple(
        _to_candidate(row) for row in connection.execute(_per_pair_statement(principal_id, query))
    )


def _per_pair_statement(principal_id: str, query: MeetingContextCandidateQuery) -> Select[Any]:
    """One statement for every Meeting of the batch (module docstring; WP5 design #16).

    The inputs are arrays unnested into `inputs` (one row per Meeting),
    `addresses` and `identifiers` (one row per criterion). Each evidence class
    is joined to the Meeting's window on its own index; the three are a
    `UNION ALL` grouped per `(Meeting, message)` -- a full outer join by
    another name -- so one message is one row with all its reasons. Then the
    tier, the collapse by conversation (the best of each by the D5 order), the
    per-Meeting position and total, the page, and the snippet of the page only.
    """
    messages = communication_messages
    participants = communication_participants
    identifiers = communication_identifiers
    meetings = query.meetings
    second = timedelta(seconds=1)

    inputs = select(
        func.unnest(
            _array([m.ordinal for m in meetings], Integer),
            _array([m.window_start for m in meetings], DateTime(timezone=True)),
            # Inclusive of the end's whole second, exactly as a search's `to_utc`.
            _array([m.window_end + second for m in meetings], DateTime(timezone=True)),
            _array([_title_tsquery_text(m.title_terms) for m in meetings], Text),
            _array([m.project_number for m in meetings], Text),
        )
        .table_valued(
            column("ord", Integer),
            column("w_start", DateTime(timezone=True)),
            column("w_until", DateTime(timezone=True)),
            column("title_q", Text),
            column("number", Text),
        )
        .render_derived()
    ).cte("inputs")
    addresses = select(
        func.unnest(
            _array([m.ordinal for m in meetings for _ in m.addresses], Integer),
            _array([address for m in meetings for address, _ in m.addresses], Text),
            _array([key for m in meetings for _, key in m.addresses], Text),
        )
        .table_valued(column("ord", Integer), column("address", Text), column("key", Text))
        .render_derived()
    ).subquery("addresses")
    wanted = select(
        func.unnest(
            _array([m.ordinal for m in meetings for _ in m.identifiers], Integer),
            _array([kind for m in meetings for kind, _ in m.identifiers], Text),
            _array([value for m in meetings for _, value in m.identifiers], Text),
        )
        .table_valued(column("ord", Integer), column("kind", Text), column("value", Text))
        .render_derived()
    ).subquery("wanted")

    def windowed() -> ColumnElement[bool]:
        return and_(
            messages.c.message_time >= inputs.c.w_start,
            messages.c.message_time < inputs.c.w_until,
        )

    no_text = literal(None, Text)
    no = literal(False, Boolean)
    zero = literal(0, BigInteger)
    # Participants: each attendee key under each of its spellings (the address index).
    by_participant = (
        select(
            addresses.c.ord,
            participants.c.message_id,
            addresses.c.key.label("key"),
            no_text.label("ident"),
            no.label("title_hit"),
            no.label("number_hit"),
            zero.label("rank"),
        )
        .select_from(
            addresses.join(
                participants,
                and_(
                    _mine(participants, principal_id),
                    participants.c.address == addresses.c.address,
                ),
            )
            .join(
                messages,
                and_(
                    matching_partition_criterion(messages, participants),
                    messages.c.message_id == participants.c.message_id,
                ),
            )
            .join(inputs, inputs.c.ord == addresses.c.ord)
        )
        .where(_mine(messages, principal_id), windowed())
    )
    # Identifiers: `(kind, value)` under the read version (the value index).
    by_identifier = (
        select(
            wanted.c.ord,
            identifiers.c.message_id,
            no_text.label("key"),
            (identifiers.c.kind + ":" + identifiers.c.value).label("ident"),
            no.label("title_hit"),
            no.label("number_hit"),
            zero.label("rank"),
        )
        .select_from(
            wanted.join(
                identifiers,
                and_(
                    _mine(identifiers, principal_id),
                    identifiers.c.kind == wanted.c.kind,
                    identifiers.c.value == wanted.c.value,
                    identifiers.c.extractor_version == query.identifier_version,
                ),
            )
            .join(
                messages,
                and_(
                    matching_partition_criterion(messages, identifiers),
                    messages.c.message_id == identifiers.c.message_id,
                ),
            )
            .join(inputs, inputs.c.ord == wanted.c.ord)
        )
        .where(_mine(messages, principal_id), windowed())
    )
    # Text: the title terms (`english`, the stored document) and the Project
    # number (one exact `simple` term, on the fly), over the window's messages.
    title_query = func.to_tsquery(_config("english"), inputs.c.title_q, type_=TSQUERY)
    title_hit = func.coalesce(messages.c.search_document.bool_op("@@")(title_query), False)
    number_query = func.plainto_tsquery(_config("simple"), inputs.c.number, type_=TSQUERY)
    number_hit = func.coalesce(_simple_document().bool_op("@@")(number_query), False)
    by_text = (
        select(
            inputs.c.ord,
            messages.c.message_id,
            no_text.label("key"),
            no_text.label("ident"),
            title_hit.label("title_hit"),
            number_hit.label("number_hit"),
            case(
                (title_hit, _integer_rank(messages.c.search_document, title_query)),
                else_=zero,
            ).label("rank"),
        )
        .select_from(inputs.join(messages, and_(_mine(messages, principal_id), windowed())))
        .where(
            or_(inputs.c.title_q.is_not(None), inputs.c.number.is_not(None)),
            or_(title_hit, number_hit),
        )
    )
    hits = union_all(by_participant, by_identifier, by_text).subquery("hits")
    grouped = (
        select(
            hits.c.ord,
            hits.c.message_id,
            func.count(hits.c.key.distinct()).label("overlap"),
            func.coalesce(
                func.array_agg(hits.c.key.distinct()).filter(hits.c.key.is_not(None)),
                literal([], ARRAY(Text)),
            ).label("matched_keys"),
            func.count(hits.c.ident.distinct()).label("id_hit"),
            func.coalesce(
                func.array_agg(hits.c.ident.distinct()).filter(hits.c.ident.is_not(None)),
                literal([], ARRAY(Text)),
            ).label("matched_identifiers"),
            func.bool_or(hits.c.title_hit).label("title_hit"),
            func.bool_or(hits.c.number_hit).label("number_hit"),
            func.max(hits.c.rank).label("rank"),
        )
        .group_by(hits.c.ord, hits.c.message_id)
        .subquery("grouped")
    )
    strong = or_(grouped.c.id_hit > 0, grouped.c.number_hit)
    tier = case(
        (and_(strong, grouped.c.overlap > 0), 1),
        (strong, 2),
        (grouped.c.overlap > 0, 3),
        else_=4,
    )
    group = func.coalesce(messages.c.conversation_id, messages.c.message_id)
    candidates = (
        select(
            grouped.c.ord,
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
            tier.label("tier"),
            grouped.c.overlap,
            grouped.c.rank,
            grouped.c.matched_keys,
            grouped.c.matched_identifiers,
            grouped.c.title_hit,
            grouped.c.number_hit,
            group.label("group_key"),
            func.count().over(partition_by=(grouped.c.ord, group)).label("conversation_hits"),
        )
        .select_from(
            grouped.join(
                messages,
                and_(
                    _mine(messages, principal_id),
                    messages.c.message_id == grouped.c.message_id,
                ),
            )
        )
        .subquery("candidates")
    )
    # D5 (iii): each conversation's representative is its best message.
    representatives = (
        select(candidates)
        .distinct(candidates.c.ord, candidates.c.group_key)
        .order_by(candidates.c.ord, candidates.c.group_key, *_context_order(candidates.c))
        .subquery("representatives")
    )
    numbered = select(
        representatives,
        func.row_number()
        .over(partition_by=representatives.c.ord, order_by=_context_order(representatives.c))
        .label("position"),
        func.count().over(partition_by=representatives.c.ord).label("matched_total"),
    ).subquery("numbered")
    page = select(numbered).where(numbered.c.position <= query.limit).subquery("page")
    text = messages.c.search_text
    snippet = (
        select(
            case(
                (messages.c.body_state.in_(_NO_TEXT_BODY_STATES), literal(None, Text)),
                else_=func.left(text, SNIPPET_CHARACTERS),
            )
        )
        .where(_mine(messages, principal_id), messages.c.message_id == page.c.message_id)
        .scalar_subquery()
    )
    return select(page, snippet.label("snippet")).order_by(page.c.ord, page.c.position)
