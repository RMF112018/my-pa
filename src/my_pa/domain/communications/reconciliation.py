"""Mailbox items: one provider item, its lane observations, and reconciled participants.

A provider id names **one mailbox item**. Each record carrying it is one
*lane observation* of that item (corpus v2: in backfill publications every Sent
item also appears as an `inbox`-lane record with the same provider id -- a lane
or query artifact, not a second item). `build_items` turns the classified
records of one publication into one `MailboxItem` per usable provider id.

**Observations taken.** Every record whose classification is not `quarantined`
or `duplicate_observation` -- i.e. the primary observation plus any
`lane_observation_merged` siblings (an exact repeat adds no evidence).

**Primary observation.** The sent-lane observation when there is one (the
sent copy is the item's own folder; it also carries `bcc`), else the lowest
ordinal. `classify_records` chooses it; this module only reads it.

**Participant reconciliation** (`reconcile_participants`):

* each observation's participant sets stay on its own `NormalizedMessage` as
  evidence;
* canonical participants per field = the union, by normalized address, of
  every observation's addresses, each with provenance -- the ordinals and lanes
  that contributed it -- in first-seen order;
* `bcc` prefers the sent lane: if any sent-lane observation returned bcc
  (state `provider_returned`), canonical bcc is the union over sent-lane
  observations only (`bcc_from_sent_lane`); otherwise the union over all;
* an item with more than one observation is flagged `participants_reconciled`;
  if any two observations' `to` or `cc` address sets differ it is also flagged
  `participants_disagreed`. A bcc difference is expected (only the sent copy
  exposes bcc) and is not a disagreement. Nothing is dropped silently.

**Canonical message time.** The primary observation's sent time when it is a
sent-lane observation, its received time when an inbox-lane one; if that raw
value is absent the selected time is used. The basis is recorded.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Final

from my_pa.domain.communications.model import (
    FolderRole,
    ItemFlag,
    LaneObservation,
    MailboxItem,
    MessageTimeBasis,
    NormalizedMessage,
    ParticipantState,
    ReconciledParticipant,
    RecordClassification,
    RecordOutcome,
)

__all__ = ["PARTICIPANT_ORDER", "build_items", "reconcile_participants"]

PARTICIPANT_ORDER: Final = ("from", "sender", "to", "cc", "bcc", "reply_to")
_DISAGREEMENT_FIELDS: Final = ("to", "cc")
_OBSERVED: Final = frozenset(
    {
        RecordClassification.ACCEPTED,
        RecordClassification.ACCEPTED_DEGRADED,
        RecordClassification.OUT_OF_WINDOW,
        RecordClassification.LANE_OBSERVATION_MERGED,
    }
)


def _union(
    field: str, observations: Sequence[NormalizedMessage]
) -> tuple[ReconciledParticipant, ...]:
    ordinals: defaultdict[str, list[int]] = defaultdict(list)
    lanes: defaultdict[str, list[FolderRole]] = defaultdict(list)
    for message in observations:
        for address in message.participants[field].addresses:
            ordinals[address].append(message.ordinal)
            if message.folder_role not in lanes[address]:
                lanes[address].append(message.folder_role)
    return tuple(
        ReconciledParticipant(address, tuple(ordinals[address]), tuple(lanes[address]))
        for address in ordinals
    )


def reconcile_participants(
    observations: Sequence[NormalizedMessage],
) -> tuple[Mapping[str, tuple[ReconciledParticipant, ...]], frozenset[ItemFlag]]:
    """Canonical participants of one item from its lane observations (module docstring)."""
    flags: set[ItemFlag] = set()
    participants = {field: _union(field, observations) for field in PARTICIPANT_ORDER}
    sent_with_bcc = [
        m
        for m in observations
        if m.folder_role is FolderRole.SENT
        and m.participants["bcc"].state is ParticipantState.PROVIDER_RETURNED
    ]
    if sent_with_bcc and len(observations) > 1:
        participants["bcc"] = _union("bcc", sent_with_bcc)
        flags.add(ItemFlag.BCC_FROM_SENT_LANE)
    if len(observations) > 1:
        flags.add(ItemFlag.PARTICIPANTS_RECONCILED)
        for field in _DISAGREEMENT_FIELDS:
            if len({frozenset(m.participants[field].addresses) for m in observations}) > 1:
                flags.add(ItemFlag.PARTICIPANTS_DISAGREED)
    return MappingProxyType(participants), frozenset(flags)


def _message_time(primary: NormalizedMessage) -> tuple[datetime, MessageTimeBasis]:
    timestamps = primary.timestamps
    if primary.folder_role is FolderRole.SENT and timestamps.sent_utc is not None:
        return timestamps.sent_utc, MessageTimeBasis.SENT
    if primary.folder_role is not FolderRole.SENT and timestamps.received_utc is not None:
        return timestamps.received_utc, MessageTimeBasis.RECEIVED
    return timestamps.selected_utc, MessageTimeBasis.SELECTED_FALLBACK


def build_items(records: Sequence[RecordOutcome]) -> tuple[MailboxItem, ...]:
    """One `MailboxItem` per usable provider id, ordered by primary ordinal."""
    groups: defaultdict[str, list[RecordOutcome]] = defaultdict(list)
    for record in records:
        if record.classification in _OBSERVED and record.message is not None:
            groups[record.message.provider_id].append(record)
    items: list[MailboxItem] = []
    for provider_id, group in groups.items():
        primaries = [
            r for r in group if r.classification is not RecordClassification.LANE_OBSERVATION_MERGED
        ]
        if len(primaries) != 1:  # classification invariant; never true when classified
            raise ValueError("a mailbox item must have exactly one primary observation")
        primary = primaries[0].message
        if primary is None:  # guarded by the grouping above
            raise ValueError("a primary observation must carry its message")
        ordered = sorted(group, key=lambda record: record.ordinal)
        observations = [record.message for record in ordered if record.message is not None]
        participants, flags = reconcile_participants(observations)
        if len(observations) > 1:
            flags = flags | {ItemFlag.MULTI_LANE}
        moment, basis = _message_time(primary)
        items.append(
            MailboxItem(
                provider_id=provider_id,
                canonical_key=primary.canonical_key,
                primary_ordinal=primary.ordinal,
                observations=tuple(
                    LaneObservation(
                        m.ordinal, m.folder_role, m.folder_verification, m.timestamps.selected_field
                    )
                    for m in observations
                ),
                participants=participants,
                flags=frozenset(flags),
                message_time=moment,
                message_time_basis=basis,
            )
        )
    return tuple(sorted(items, key=lambda item: item.primary_ordinal))
