"""Collect expired and terminal transfer sessions and their staging (WP06 T19).

A transfer session's chunks wait in the staging (`ReportTransferStaging`,
the report content root's constant `transfer` directory) until the session is
consumed or aborted, when the request discards them after its commit, best
effort. What that leaves -- a session that simply expired, a discard that
failed, a staging directory whose session row does not exist -- is collected
here, bounded and idempotent:

1. up to `limit` sessions still `open` or `finalized` whose `expires_at` is at
   or before `now` move to `expired` (one short transaction;
   `FOR UPDATE SKIP LOCKED`, so a session a request holds is left for the
   next run);
2. the staging of every session in a terminal state (consumed, aborted,
   expired) still present in `staged_session_ids()` is discarded (at most
   `limit`);
3. staging directories with no session row at all are orphans: reported, and
   with `discard_orphans=True` discarded (at most `limit`).

**Only transfer staging is ever removed.** The staging port's `discard` is
confined to the `transfer` namespace and admits only `grxfr_` identifiers;
the report content store (namespaces `content` and `preservation`) has no
delete and is never reached from here. A session row is never deleted: it
only moves to `expired`.

The session queries are the repository's operator scans
(`expire_due`, `terminal_session_ids`, `known_session_ids`), **not
Principal-scoped on purpose**, as `known_managed_content_ids` and
`hold_seal_events` are: staging is one directory for every owner. Library
only, with an operator command (`apps/cli/report_content.py transfer-gc`); no
capability. Nothing here returns an identifier, a path or a byte: counts only.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from my_pa.contracts.ports import ReportTransferRepository, ReportTransferStaging

__all__ = [
    "DEFAULT_TRANSFER_GC_LIMIT",
    "MAX_TRANSFER_GC_LIMIT",
    "TransferCollection",
    "collect_report_transfers",
]

#: Sessions expired, and staging directories discarded, per kind per run by default.
DEFAULT_TRANSFER_GC_LIMIT: Final = 100
#: The repository's own bound on one expiry batch (`expire_due`).
MAX_TRANSFER_GC_LIMIT: Final = 1000


class _HasReportTransfers(Protocol):
    """What one GC transaction needs: a `UnitOfWork` satisfies it."""

    @property
    def report_transfers(self) -> ReportTransferRepository: ...


#: Opens one short transaction (a `UnitOfWork` factory, or the operator
#: command's connection-bound equivalent); leaving it normally commits.
TransferTransactionFactory = Callable[[], AbstractContextManager[_HasReportTransfers]]


@dataclass(frozen=True, slots=True)
class TransferCollection:
    """What one collection run did. Counts only: no identifier, path or byte."""

    #: Sessions moved to `expired` by this run.
    expired: int
    #: Terminal sessions whose staging this run removed.
    discarded: int
    #: Staging directories with no session row.
    orphans_found: int
    #: Orphans this run removed (`discard_orphans` only).
    orphans_discarded: int
    #: Staging entries that are not well-formed sessions or chunks (never removed).
    unreadable: int
    #: Whether a bound stopped this run short: more due sessions, or more
    #: terminal staging, than `limit`. Running again continues.
    more_remaining: bool

    @property
    def orphans_remaining(self) -> int:
        """Orphans found and still present after this run."""
        return self.orphans_found - self.orphans_discarded

    @property
    def clean(self) -> bool:
        """Nothing left for another run or for the operator."""
        return not self.more_remaining and self.orphans_remaining == 0 and self.unreadable == 0

    def summary(self) -> dict[str, int | bool]:
        """The JSON-ready summary the operator command prints."""
        return {
            "expired": self.expired,
            "discarded": self.discarded,
            "orphans_found": self.orphans_found,
            "orphans_discarded": self.orphans_discarded,
            "orphans_remaining": self.orphans_remaining,
            "unreadable": self.unreadable,
            "more_remaining": self.more_remaining,
        }


def collect_report_transfers(
    transactions: TransferTransactionFactory,
    staging: ReportTransferStaging,
    *,
    now: datetime,
    limit: int = DEFAULT_TRANSFER_GC_LIMIT,
    discard_orphans: bool = False,
) -> TransferCollection:
    """Expire due sessions, discard terminal and (optionally) orphaned staging; bounded.

    Idempotent: a second run over the same state expires and discards
    nothing more. `limit` (1..1000) bounds each of the three steps. A staging
    failure propagates (`ReportTransferStagingError`): what was already
    removed stays removed, and the next run continues.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_TRANSFER_GC_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {MAX_TRANSFER_GC_LIMIT}")
    with transactions() as unit_of_work:
        expired = unit_of_work.report_transfers.expire_due(now=now, limit=limit)
    staged = staging.staged_session_ids()
    with transactions() as unit_of_work:
        transfers = unit_of_work.report_transfers
        terminal = transfers.terminal_session_ids(staged)
        known = transfers.known_session_ids(staged)
    # A terminal state is final, so its staging can never be needed again;
    # a session row is never deleted, so "no row" cannot become "a row".
    terminal_staged = sorted(terminal)
    discarded = sum(1 for session_id in terminal_staged[:limit] if staging.discard(session_id))
    orphans = sorted(session_id for session_id in staged if session_id not in known)
    orphans_discarded = 0
    if discard_orphans:
        orphans_discarded = sum(1 for session_id in orphans[:limit] if staging.discard(session_id))
    return TransferCollection(
        expired=len(expired),
        discarded=discarded,
        orphans_found=len(orphans),
        orphans_discarded=orphans_discarded,
        unreadable=len(staging.unreadable_entries()),
        more_remaining=len(expired) == limit or len(terminal_staged) > limit,
    )
