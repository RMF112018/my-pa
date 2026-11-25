"""Bounded re-derivation of stored communications messages (WP4 rulings D2, D3, R2-R4, R9).

`CommunicationsRederiver.rederive` brings stored messages to the current
`comms_search_text_v2` text and `comms_identifiers_v2` identifier rows. A
message is **due** when its `search_text_version` is not the current one, its
`identifiers_version` is not the current one, or it is flagged
`source_unavailable` (so a file that comes back is retried). The due set is
the state itself, so a run is idempotent and a stopped run resumes: at most
`limit` due messages (by `message_id`) are visited, the rest are counted
`messages_deferred` and wait for the next run.

**Text due** (`search_text_version` stale, or `source_unavailable`): the
messages are grouped by their text pointer's snapshot, and each snapshot's
bytes are read through the source's read-only workspace store -- every path
row of the snapshot, current paths first, each `stat`ed and read with
`open_download(expected_version=...)`, at most `max_bytes` -- and accepted
only when their SHA-256 equals the snapshot's `file_sha256`.

* **Verified.** The publication is parsed with the injected parser and each
  message's text is derived again from the record its pointer names (the same
  ordinal, the same item primary, the same canonical key and body digest, else
  `messages_pointer_mismatch` and nothing is written). The projection keeps
  its pointer; `search_text` and its version are rewritten. Because the v1
  text is a prefix of the v2 text (`search_text.py`), the projection-selection
  key is unchanged and no observation is re-selected. `source_unavailable` is
  cleared (`messages_source_restored`).
* **Missing, or the digest differs** (`snapshots_unavailable`): the stored
  projection is kept, the message is flagged `source_unavailable`
  (`messages_source_unavailable`), and the current identifiers are still
  extracted over the **stored** text (ruling R9), so identifier search covers it.
* **The parser now rejects the bytes** (`snapshots_unparseable`): nothing is
  written; the messages count `messages_failed` and stay due.

**Identifiers due only** (text current): the current identifiers are
extracted from the stored text; no file is read.

In every written case the current version's identifier rows are added beside
the old ones (set-like; the table is append-only and nothing is pruned, ruling
R4) and `identifiers_version` is set.

**Transactions.** The due read is one short transaction. Each snapshot group,
and each batch of identifier-only messages, is its own transaction, in which
every message is re-read `FOR UPDATE` and re-checked (its pointer unchanged and
still due, else `messages_current`); a failure rolls back that group alone and
counts its messages `messages_failed`. The caller holds the communications
poll lock for the run (the operator CLI's `rederive`), so no ingest
interleaves. A **dry run** reads the due set, counts and writes nothing; it
reads no file.

Counts are the closed `REDERIVE_COUNT_KEYS`, never content; nothing here logs.
No audit row is written and no capability is involved: this is an operator
step over the ingestion transactions.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from my_pa.application.communications_ingest import ParsedPublication, message_projection
from my_pa.contracts.ports import (
    CommunicationIdentifierRecord,
    CommunicationMessageRecord,
    FileWorkspaceStore,
    FileWorkspaceUnavailableError,
    IngestSnapshotPathRecord,
    UnitOfWork,
)
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION, extract_identifiers
from my_pa.domain.communications.model import NormalizedMessage, Publication
from my_pa.domain.communications.search_text import SEARCH_TEXT_VERSION, derive_search_text
from my_pa.domain.files.errors import FilesDomainError
from my_pa.domain.files.versions import EntryKind

__all__ = [
    "DEFAULT_REDERIVE_LIMIT",
    "MAX_REDERIVE_LIMIT",
    "REDERIVE_COUNT_KEYS",
    "CommunicationsRederiver",
    "RederiveReport",
]

DEFAULT_REDERIVE_LIMIT: Final = 1_000
MAX_REDERIVE_LIMIT: Final = 20_000
#: Identifier-only messages are written in transactions of this many.
IDENTIFIER_BATCH: Final = 500
#: Every key a run's counts carry (always all of them, zero when nothing happened).
REDERIVE_COUNT_KEYS: Final = (
    "messages_checked",
    "messages_current",
    "messages_due_text",
    "messages_due_identifiers",
    "messages_rederived",
    "messages_text_changed",
    "messages_source_unavailable",
    "messages_source_restored",
    "messages_pointer_mismatch",
    "messages_deferred",
    "messages_failed",
    "snapshots_read",
    "snapshots_unavailable",
    "snapshots_unparseable",
    "identifiers_added",
)
_READ_CHUNK: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class RederiveReport:
    dry_run: bool
    search_text_version: str
    identifier_version: str
    counts: Mapping[str, int]


def _text_due(message: CommunicationMessageRecord) -> bool:
    return (
        message.projection.search_text_version != SEARCH_TEXT_VERSION or message.source_unavailable
    )


def _due(message: CommunicationMessageRecord) -> bool:
    return _text_due(message) or message.identifiers_version != IDENTIFIER_VERSION


def _batches(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class _UnavailableError(Exception):
    """No path of the snapshot yields bytes with its digest."""


class _MismatchError(Exception):
    """The pointer names no record of this message in the verified publication."""


class CommunicationsRederiver:
    """The rederive (module docstring)."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], UnitOfWork],
        stores: Callable[[str], FileWorkspaceStore],
        parse: Callable[[bytes], ParsedPublication],
        max_bytes: int,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._stores = stores
        self._parse = parse
        self._max_bytes = max_bytes

    # --- the run -----------------------------------------------------------------

    def rederive(
        self,
        principal_id: str,
        *,
        limit: int = DEFAULT_REDERIVE_LIMIT,
        ingest_source_id: str | None = None,
        dry_run: bool = False,
    ) -> RederiveReport:
        if type(limit) is not int or not 1 <= limit <= MAX_REDERIVE_LIMIT:
            raise ValueError("a rederive limit is an integer in [1, MAX_REDERIVE_LIMIT]")
        counts: Counter[str] = Counter(dict.fromkeys(REDERIVE_COUNT_KEYS, 0))
        with self._unit_of_work() as unit:
            repository = unit.communications
            due = repository.list_rederive_due(
                principal_id,
                search_text_version=SEARCH_TEXT_VERSION,
                identifiers_version=IDENTIFIER_VERSION,
                ingest_source_id=ingest_source_id,
                limit=limit,
            )
            total = repository.count_rederive_due(
                principal_id,
                search_text_version=SEARCH_TEXT_VERSION,
                identifiers_version=IDENTIFIER_VERSION,
                ingest_source_id=ingest_source_id,
            )
        counts["messages_checked"] = len(due)
        counts["messages_deferred"] = max(total - len(due), 0)
        groups: dict[str, list[str]] = {}
        identifier_only: list[str] = []
        for message in due:
            if _text_due(message):
                counts["messages_due_text"] += 1
                groups.setdefault(message.projection.text_snapshot_id, []).append(
                    message.message_id
                )
            else:
                counts["messages_due_identifiers"] += 1
                identifier_only.append(message.message_id)
        if not dry_run:
            for snapshot_id in sorted(groups):
                self._snapshot(principal_id, snapshot_id, groups[snapshot_id], counts)
            for batch in _batches(identifier_only, IDENTIFIER_BATCH):
                self._identifiers_only(principal_id, batch, counts)
        return RederiveReport(
            dry_run=dry_run,
            search_text_version=SEARCH_TEXT_VERSION,
            identifier_version=IDENTIFIER_VERSION,
            counts=dict(sorted(counts.items())),
        )

    # --- one snapshot group ----------------------------------------------------------

    def _snapshot(
        self, principal_id: str, snapshot_id: str, message_ids: Sequence[str], counts: Counter[str]
    ) -> None:
        try:
            data = self._verified_bytes(principal_id, snapshot_id)
        except _UnavailableError:
            counts["snapshots_unavailable"] += 1
            self._write_group(principal_id, snapshot_id, message_ids, None, counts)
            return
        counts["snapshots_read"] += 1
        parsed = self._parse(data)
        if parsed.publication is None:
            counts["snapshots_unparseable"] += 1
            counts["messages_failed"] += len(message_ids)
            return
        self._write_group(principal_id, snapshot_id, message_ids, parsed.publication, counts)

    def _verified_bytes(self, principal_id: str, snapshot_id: str) -> bytes:
        """The snapshot's bytes from one of its paths, digest-checked; else `_UnavailableError`."""
        with self._unit_of_work() as unit:
            snapshot = unit.ingestion.get_snapshot(principal_id, snapshot_id)
            if snapshot is None:
                raise _UnavailableError
            source = unit.ingestion.get_source(principal_id, snapshot.ingest_source_id)
            paths = unit.ingestion.list_paths_of_snapshot(principal_id, snapshot_id)
        if source is None:
            raise _UnavailableError
        try:
            store = self._stores(source.workspace_id)
        except (LookupError, FileWorkspaceUnavailableError):
            raise _UnavailableError from None
        for path in sorted(paths, key=_current_first):
            data = self._read(store, path.relative_path)
            if data is not None and hashlib.sha256(data).hexdigest() == snapshot.file_sha256:
                return data
        raise _UnavailableError

    def _read(self, store: FileWorkspaceStore, path: str) -> bytes | None:
        """One path's bytes bound to the observed version, or `None` (missing, moved, too big)."""
        reader = None
        try:
            entry = store.stat(path)
            if entry.kind is not EntryKind.FILE or entry.size is None:
                return None
            if entry.size > self._max_bytes:
                return None
            reader = store.open_download(path, expected_version=entry.version)
            data = b"".join(reader.read_range(0, min(reader.size, self._max_bytes)))
        except (FilesDomainError, FileWorkspaceUnavailableError):
            return None
        finally:
            if reader is not None:
                reader.close()
        return data if len(data) == entry.size else None

    def _write_group(
        self,
        principal_id: str,
        snapshot_id: str,
        message_ids: Sequence[str],
        publication: Publication | None,
        counts: Counter[str],
    ) -> None:
        """One transaction for the group; `publication` is `None` when the source is unavailable."""
        local: Counter[str] = Counter()
        try:
            with self._unit_of_work() as unit:
                for message_id in message_ids:
                    self._write_message(
                        unit, principal_id, snapshot_id, message_id, publication, local
                    )
        except Exception:  # this group rolls back; the run continues
            counts["messages_failed"] += len(message_ids)
            return
        counts.update(local)

    def _write_message(
        self,
        unit: UnitOfWork,
        principal_id: str,
        snapshot_id: str,
        message_id: str,
        publication: Publication | None,
        counts: Counter[str],
    ) -> None:
        repository = unit.communications
        message = repository.get_message(principal_id, message_id, for_update=True)
        if (
            message is None
            or message.projection.text_snapshot_id != snapshot_id
            or not _text_due(message)
        ):
            counts["messages_current"] += 1
            return
        if publication is None:
            if not message.source_unavailable:
                repository.set_source_unavailable(principal_id, message_id, source_unavailable=True)
            counts["messages_source_unavailable"] += 1
            self._identifiers(unit, principal_id, message, message.projection.search_text, counts)
            return
        try:
            normalized = _pointed(publication, message)
        except _MismatchError:
            counts["messages_pointer_mismatch"] += 1
            return
        projection = message_projection(normalized, derive_search_text(normalized), snapshot_id)
        repository.update_message_projection(
            principal_id,
            message_id,
            projection=projection,
            latest_snapshot_id=message.latest_snapshot_id,
        )
        if projection.search_text != message.projection.search_text:
            counts["messages_text_changed"] += 1
        if message.source_unavailable:
            repository.set_source_unavailable(principal_id, message_id, source_unavailable=False)
            counts["messages_source_restored"] += 1
        self._identifiers(unit, principal_id, message, projection.search_text, counts)
        counts["messages_rederived"] += 1

    # --- identifiers ----------------------------------------------------------------

    def _identifiers_only(
        self, principal_id: str, message_ids: Sequence[str], counts: Counter[str]
    ) -> None:
        local: Counter[str] = Counter()
        try:
            with self._unit_of_work() as unit:
                for message_id in message_ids:
                    message = unit.communications.get_message(
                        principal_id, message_id, for_update=True
                    )
                    if message is None or not _due(message) or _text_due(message):
                        local["messages_current"] += 1
                        continue
                    self._identifiers(
                        unit, principal_id, message, message.projection.search_text, local
                    )
                    local["messages_rederived"] += 1
        except Exception:  # this batch rolls back; the run continues
            counts["messages_failed"] += len(message_ids)
            return
        counts.update(local)

    @staticmethod
    def _identifiers(
        unit: UnitOfWork,
        principal_id: str,
        message: CommunicationMessageRecord,
        text: str | None,
        counts: Counter[str],
    ) -> None:
        """Add the current version's rows over `subject + text`; record the version."""
        repository = unit.communications
        found = extract_identifiers(
            f"{message.subject or ''}\n{text or ''}", version=IDENTIFIER_VERSION
        )
        counts["identifiers_added"] += repository.insert_identifiers(
            principal_id,
            [
                CommunicationIdentifierRecord(
                    message_id=message.message_id,
                    kind=identifier.kind.value,
                    value=identifier.value,
                    extractor_version=IDENTIFIER_VERSION,
                )
                for identifier in found
            ],
        )
        if message.identifiers_version != IDENTIFIER_VERSION:
            repository.set_identifiers_version(principal_id, message.message_id, IDENTIFIER_VERSION)


def _current_first(path: IngestSnapshotPathRecord) -> tuple[bool, object, str]:
    return (path.superseded_at is not None, path.first_seen_at, path.relative_path)


def _pointed(publication: Publication, message: CommunicationMessageRecord) -> NormalizedMessage:
    """The normalized message the text pointer names, checked against the stored message."""
    ordinal = message.projection.text_record_ordinal
    record = next((r for r in publication.records if r.ordinal == ordinal), None)
    if record is None or record.message is None:
        raise _MismatchError
    normalized = record.message
    item = next(
        (i for i in publication.items if i.provider_id == normalized.provider_id),
        None,
    )
    if item is None or item.primary_ordinal != ordinal:
        raise _MismatchError
    key = item.canonical_key
    if (key.mailbox_ref, key.kind.value, key.value) != (
        message.mailbox_ref,
        message.identity_kind,
        message.identity_value,
    ):
        raise _MismatchError
    if normalized.body.sha256 != message.projection.body_sha256:
        raise _MismatchError
    return normalized
