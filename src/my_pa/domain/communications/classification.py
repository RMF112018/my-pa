"""Per-record classification and the within-publication identity rules.

`classify_records` assigns exactly one `RecordClassification` to every record
ordinal, in this precedence (first match wins):

1. `quarantined` -- the parser could not normalize the record (its reasons are
   carried), or one of the identity rules below fails;
2. `duplicate_observation` -- an exact repeat: a later record with a provider id
   already seen in this publication **in the same folder role**, with the same
   identity and body digest (the first occurrence keeps its classification);
3. `lane_observation_merged` -- the same provider id seen again **in another
   folder role** (corpus v2's backfill defect: every Sent item also listed in the
   inbox lane). A provider id is one mailbox item, so this is a second *lane
   observation* of it, merged into the item (`reconciliation.build_items`), not a
   second item, not a dropped duplicate and not a conflict. The primary
   observation is the sent-lane one when present, else the lowest ordinal;
4. `out_of_window` -- the selected UTC time is outside the inclusive window;
5. `accepted_degraded` -- usable, with at least one degradation reason;
6. `accepted`.

Identity rules, all within one publication:

* **provider id conflict** -- one provider id whose observations disagree on
  canonical key (internet message id) or body digest: every observation of it
  is quarantined (`provider_id_conflict`, the provider-id form of an identity
  conflict); there is no way to know which one is right;
* **identity conflict** -- one canonical internet-message-id key whose primary
  observations (distinct provider ids) disagree on sender address or body
  digest: every observation, merged lane siblings included, is quarantined
  (`identity_conflict`) and never merged;
* Inbox + Sent copies of one internet message id under **two provider ids**
  (two genuine mailbox items, e.g. self-addressed mail) are two observations of
  one identity. That is expected, not a conflict, and their selected timestamps
  legitimately differ (received vs sent).

Where a record declares its own in-window flag (rich dialect), disagreement
with the computed classification degrades the record (`in_window_disagreement`).
One bad record never rejects the publication.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from my_pa.domain.communications.diagnostics import (
    DiagnosticCode,
    DiagnosticCollector,
    ReasonCode,
)
from my_pa.domain.communications.model import (
    CanonicalKey,
    FolderRole,
    IdentityState,
    NormalizedMessage,
    QuarantinedRecord,
    RecordClassification,
    RecordOutcome,
    Window,
)

__all__ = ["classify_records"]

_C = RecordClassification


def classify_records(
    entries: Sequence[NormalizedMessage | QuarantinedRecord],
    window: Window,
    diagnostics: DiagnosticCollector,
) -> tuple[RecordOutcome, ...]:
    outcomes: dict[int, RecordOutcome] = {}
    usable: list[NormalizedMessage] = []
    for entry in entries:
        if isinstance(entry, QuarantinedRecord):
            outcomes[entry.ordinal] = RecordOutcome(
                entry.ordinal, _C.QUARANTINED, entry.reasons, None
            )
        else:
            usable.append(entry)

    def quarantine(message: NormalizedMessage, reason: ReasonCode) -> None:
        outcomes[message.ordinal] = RecordOutcome(
            message.ordinal, _C.QUARANTINED, (*message.degraded_reasons, reason), message
        )

    by_provider_id: defaultdict[str, list[NormalizedMessage]] = defaultdict(list)
    for message in usable:
        by_provider_id[message.provider_id].append(message)
    first_observations: list[NormalizedMessage] = []
    lane_siblings: dict[int, list[NormalizedMessage]] = {}
    for group in by_provider_id.values():
        signatures = {(m.canonical_key, m.body.sha256) for m in group}
        if len(signatures) > 1:
            for message in group:
                quarantine(message, ReasonCode.PROVIDER_ID_CONFLICT)
            continue
        per_role: dict[FolderRole, NormalizedMessage] = {}
        for message in sorted(group, key=lambda m: m.ordinal):
            first = per_role.get(message.folder_role)
            if first is None:
                per_role[message.folder_role] = message
                continue
            diagnostics.add(
                DiagnosticCode.DUPLICATE_PROVIDER_ID,
                "messages[].id",
                message.ordinal,
                first_ordinal=first.ordinal,
            )
            outcomes[message.ordinal] = RecordOutcome(
                message.ordinal, _C.DUPLICATE_OBSERVATION, message.degraded_reasons, message
            )
        lanes = sorted(per_role.values(), key=lambda m: m.ordinal)
        primary = per_role.get(FolderRole.SENT, lanes[0])
        first_observations.append(primary)
        siblings = [m for m in lanes if m is not primary]
        if siblings:
            lane_siblings[primary.ordinal] = siblings
        for message in siblings:
            diagnostics.add(
                DiagnosticCode.MULTI_LANE_ITEM,
                "messages[].source_folder.role",
                message.ordinal,
                primary_ordinal=primary.ordinal,
            )
            outcomes[message.ordinal] = RecordOutcome(
                message.ordinal, _C.LANE_OBSERVATION_MERGED, message.degraded_reasons, message
            )

    by_identity: defaultdict[CanonicalKey, list[NormalizedMessage]] = defaultdict(list)
    for message in first_observations:
        if message.identity_state is IdentityState.PROVIDER_RETURNED:
            by_identity[message.canonical_key].append(message)
    conflicted: set[int] = set()
    for group in by_identity.values():
        senders = {m.sender_address for m in group if m.sender_address is not None}
        digests = {m.body.sha256 for m in group}
        if len(senders) > 1 or len(digests) > 1:
            for message in group:
                for observation in (message, *lane_siblings.get(message.ordinal, ())):
                    quarantine(observation, ReasonCode.IDENTITY_CONFLICT)
                conflicted.add(message.ordinal)

    for message in first_observations:
        if message.ordinal in conflicted or message.ordinal in outcomes:
            continue
        reasons = message.degraded_reasons
        in_window = window.contains(message.timestamps.selected_utc)
        if message.declared_in_window is not None and message.declared_in_window != in_window:
            reasons = (*reasons, ReasonCode.IN_WINDOW_DISAGREEMENT)
        if not in_window:
            diagnostics.add(DiagnosticCode.OUT_OF_WINDOW, "messages[].timestamps", message.ordinal)
            classification = _C.OUT_OF_WINDOW
        elif reasons:
            classification = _C.ACCEPTED_DEGRADED
        else:
            classification = _C.ACCEPTED
        outcomes[message.ordinal] = RecordOutcome(message.ordinal, classification, reasons, message)

    return tuple(outcomes[ordinal] for ordinal in sorted(outcomes))
