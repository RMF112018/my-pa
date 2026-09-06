"""Principal-bound GoodNotes browser list, read, search, and correct contracts.

Lists, read, and search never return filesystem paths or raster bytes.
Correction wraps `GoodNotesCorrectionService.apply` and does not invent
new revision semantics.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Protocol, cast

from my_pa.application.authorization import Authorization
from my_pa.application.commands import (
    CorrectGoodNotes,
    ListGoodNotesNotebooks,
    ListGoodNotesPages,
    ListGoodNotesRuns,
    ReadGoodNotes,
    SearchGoodNotes,
)
from my_pa.application.errors import InvalidRequestError, NotFoundError, SafeDetail
from my_pa.application.goodnotes_corrections import (
    GoodNotesCorrectionRepository,
    GoodNotesCorrectionService,
)
from my_pa.application.goodnotes_semantics import lookup_work
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.common.time import format_rfc3339
from my_pa.domain.goodnotes.models import GoodNotesIngestionRun, GoodNotesIngestionStatus

DEFAULT_PAGE_SIZE = 25
# Catalog presence is not a NAS liveness probe. Do not claim the source is
# unavailable merely because this read did not re-check the filesystem.
_CATALOGUE_LIVENESS = "unknown"
_OPERATOR_CORRECTION = "operator-correction"
_PROCESSING_STATUSES = frozenset(
    {GoodNotesIngestionStatus.PENDING, GoodNotesIngestionStatus.RUNNING}
)


def _page_size(requested: int | None) -> int:
    return DEFAULT_PAGE_SIZE if requested is None else requested


def _encode_cursor(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(token: str, *, principal_id: str) -> dict[str, object]:
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded = json.loads(
            base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        )
    except (
        binascii.Error,
        UnicodeEncodeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        raise InvalidRequestError(SafeDetail.CURSOR) from None
    if not isinstance(decoded, dict) or decoded.get("p") != principal_id:
        raise InvalidRequestError(SafeDetail.CURSOR)
    return decoded


def _keyset(cursor: str | None, *, principal_id: str) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    decoded = _decode_cursor(cursor, principal_id=principal_id)
    stamp, identity = decoded.get("t"), decoded.get("i")
    if not isinstance(stamp, str) or not isinstance(identity, str):
        raise InvalidRequestError(SafeDetail.CURSOR)
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        raise InvalidRequestError(SafeDetail.CURSOR) from None
    return when, identity


def _search_keyset(cursor: str | None, *, principal_id: str) -> tuple[int, str] | None:
    if cursor is None:
        return None
    decoded = _decode_cursor(cursor, principal_id=principal_id)
    rank, identity = decoded.get("r"), decoded.get("i")
    if not isinstance(rank, int) or isinstance(rank, bool) or not isinstance(identity, str):
        raise InvalidRequestError(SafeDetail.CURSOR)
    return rank, identity


class _NotebookRow(Protocol):
    notebook_id: str
    title: str
    updated_at: datetime
    page_count: int


class _PageRow(Protocol):
    logical_page_id: str
    page_version_id: str
    run_id: str | None
    content_sha256: str
    is_latest: bool
    updated_at: datetime


class _RunRow(Protocol):
    run_id: str
    state: str
    failure_class: str | None
    started_at: datetime
    completed_at: datetime | None
    page_version_id: str | None


class _SearchRow(Protocol):
    kind: str
    id: str
    title: str
    snippet: str
    notebook_id: str | None
    logical_page_id: str | None
    page_version_id: str | None
    run_id: str | None
    freshness: str
    rank: int


class _BrowserStore(GoodNotesCorrectionRepository, Protocol):
    def notebook(self, principal_id: str, notebook_id: str) -> object | None: ...

    def run(self, principal_id: str, run_id: str) -> GoodNotesIngestionRun | None: ...

    def browse_notebooks(
        self, principal_id: str, *, limit: int, after: tuple[datetime, str] | None
    ) -> tuple[_NotebookRow, ...]: ...

    def browse_pages(
        self,
        principal_id: str,
        notebook_id: str,
        *,
        limit: int,
        after: tuple[datetime, str] | None,
    ) -> tuple[_PageRow, ...]: ...

    def browse_runs(
        self,
        principal_id: str,
        *,
        notebook_id: str | None,
        page_version_id: str | None,
        limit: int,
        after: tuple[datetime, str] | None,
    ) -> tuple[_RunRow, ...]: ...

    def browse_search(
        self,
        principal_id: str,
        query: str,
        *,
        limit: int,
        after: tuple[int, str] | None,
    ) -> tuple[_SearchRow, ...]: ...

    def browse_interpretation(
        self, principal_id: str, run_id: str, page_version_id: str
    ) -> list[dict[str, object]]: ...


def _durable(unit_of_work: UnitOfWork) -> _BrowserStore:
    try:
        return cast(_BrowserStore, unit_of_work.goodnotes_durable_notes)
    except NotImplementedError:
        raise NotFoundError() from None


def list_notebooks(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    command: ListGoodNotesNotebooks,
) -> dict[str, object]:
    principal_id = authorization.principal.principal_id
    size = _page_size(command.page_size)
    after = _keyset(command.cursor, principal_id=principal_id)
    rows = _durable(unit_of_work).browse_notebooks(principal_id, limit=size + 1, after=after)
    page, nxt = rows[:size], rows[size:]
    payload: dict[str, object] = {
        "notebooks": [
            {
                "notebook_id": row.notebook_id,
                "title": row.title,
                "updated_at": format_rfc3339(row.updated_at),
                "page_count": row.page_count,
                "liveness": _CATALOGUE_LIVENESS,
            }
            for row in page
        ]
    }
    if nxt:
        last = page[-1]
        payload["next_cursor"] = _encode_cursor(
            {"p": principal_id, "t": format_rfc3339(last.updated_at), "i": last.notebook_id}
        )
    return payload


def list_pages(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    command: ListGoodNotesPages,
) -> dict[str, object]:
    principal_id = authorization.principal.principal_id
    store = _durable(unit_of_work)
    if store.notebook(principal_id, command.notebook_id) is None:
        return {"pages": []}
    size = _page_size(command.page_size)
    after = _keyset(command.cursor, principal_id=principal_id)
    rows = store.browse_pages(principal_id, command.notebook_id, limit=size + 1, after=after)
    page, nxt = rows[:size], rows[size:]
    payload: dict[str, object] = {
        "pages": [
            {
                "logical_page_id": row.logical_page_id,
                "page_version_id": row.page_version_id,
                "run_id": row.run_id,
                "content_sha256": row.content_sha256,
                "is_latest": row.is_latest,
                "updated_at": format_rfc3339(row.updated_at),
            }
            for row in page
        ]
    }
    if nxt:
        last = page[-1]
        payload["next_cursor"] = _encode_cursor(
            {
                "p": principal_id,
                "t": format_rfc3339(last.updated_at),
                "i": last.page_version_id,
            }
        )
    return payload


def list_runs(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    command: ListGoodNotesRuns,
) -> dict[str, object]:
    principal_id = authorization.principal.principal_id
    store = _durable(unit_of_work)
    if command.notebook_id is not None and (
        store.notebook(principal_id, command.notebook_id) is None
    ):
        raise NotFoundError()
    size = _page_size(command.page_size)
    after = _keyset(command.cursor, principal_id=principal_id)
    rows = store.browse_runs(
        principal_id,
        notebook_id=command.notebook_id,
        page_version_id=command.page_version_id,
        limit=size + 1,
        after=after,
    )
    page, nxt = rows[:size], rows[size:]
    items: list[dict[str, object]] = []
    for row in page:
        item: dict[str, object] = {
            "run_id": row.run_id,
            "state": row.state,
            "failure_class": row.failure_class,
            "started_at": format_rfc3339(row.started_at),
            "completed_at": None if row.completed_at is None else format_rfc3339(row.completed_at),
        }
        if command.page_version_id is not None and row.page_version_id is not None:
            item["page_version_id"] = row.page_version_id
        items.append(item)
    payload: dict[str, object] = {"runs": items}
    if nxt:
        last = page[-1]
        payload["next_cursor"] = _encode_cursor(
            {"p": principal_id, "t": format_rfc3339(last.started_at), "i": last.run_id}
        )
    return payload


def read_page(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    command: ReadGoodNotes,
) -> dict[str, object]:
    work = lookup_work(
        unit_of_work,
        authorization,
        run_id=command.run_id,
        page_version_id=command.page_version_id,
    )
    if command.content_sha256 is not None and work.content_sha256 != command.content_sha256:
        raise InvalidRequestError(SafeDetail.CONTENT_SHA256)
    raster = unit_of_work.goodnotes_semantics.page_raster(
        authorization.principal.principal_id, command.run_id, command.page_version_id
    )
    if raster is None:
        raise NotFoundError()
    store = _durable(unit_of_work)
    run = store.run(authorization.principal.principal_id, command.run_id)
    interpretation = store.browse_interpretation(
        authorization.principal.principal_id, command.run_id, command.page_version_id
    )
    authority = _authority(
        run_status=None if run is None else run.status.value,
        interpretation=interpretation,
    )
    return {
        "run_id": work.run_id,
        "page_version_id": work.page_version_id,
        "content_sha256": work.content_sha256,
        "exact_render_sha256": raster.exact_render_sha256,
        "raster_digest": raster.png_sha256,
        "media_type": raster.media_type,
        "renderer_name": raster.renderer_name,
        "renderer_version": raster.renderer_version,
        "render_profile_version": raster.render_profile_version,
        "interpretation": {"authority": authority, "items": interpretation},
        "provenance": {
            "run_id": work.run_id,
            "page_version_id": work.page_version_id,
            "content_sha256": work.content_sha256,
        },
        "processing": {
            "run_status": None if run is None else run.status.value,
            "failure_class": None if run is None else run.error_class,
        },
    }


def search(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    command: SearchGoodNotes,
) -> dict[str, object]:
    principal_id = authorization.principal.principal_id
    size = _page_size(command.page_size)
    after = _search_keyset(command.cursor, principal_id=principal_id)
    rows = _durable(unit_of_work).browse_search(
        principal_id, command.query.strip(), limit=size + 1, after=after
    )
    page, nxt = rows[:size], rows[size:]
    payload: dict[str, object] = {
        "hits": [
            {
                "kind": row.kind,
                "id": row.id,
                "title": row.title,
                "snippet": row.snippet,
                "notebook_id": row.notebook_id,
                "logical_page_id": row.logical_page_id,
                "page_version_id": row.page_version_id,
                "run_id": row.run_id,
                "freshness": row.freshness,
            }
            for row in page
        ]
    }
    if nxt:
        last = page[-1]
        payload["next_cursor"] = _encode_cursor({"p": principal_id, "r": last.rank, "i": last.id})
    return payload


def correct(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    command: CorrectGoodNotes,
) -> dict[str, object]:
    try:
        result = GoodNotesCorrectionService().apply(
            authorization.principal.principal_id,
            command.occurrence_id,
            transcription=command.transcription,
            repository=_durable(unit_of_work),
        )
    except ValueError as error:
        raise _correction_error(error) from None
    return {
        "occurrence_id": command.occurrence_id,
        "revision_id": result.revision.revision_id,
        "prior_revision_id": result.prior_revision.revision_id,
        "replayed": result.replayed,
        "disposition": "canonical_revision_appended",
    }


def _correction_error(error: ValueError) -> NotFoundError | InvalidRequestError:
    message = str(error)
    if (
        "no stored GoodNotes note occurrence" in message
        or "no stored GoodNotes note revision" in message
    ):
        return NotFoundError()
    if "missing required transcription" in message:
        return InvalidRequestError(SafeDetail.TRANSCRIPTION)
    if "missing required geometry" in message:
        return InvalidRequestError(SafeDetail.GEOMETRY)
    if "not eligible" in message or "trace" in message:
        return InvalidRequestError(SafeDetail.OCCURRENCE_ID)
    return InvalidRequestError(SafeDetail.OCCURRENCE_ID)


def _authority(*, run_status: str | None, interpretation: list[dict[str, object]]) -> str:
    if run_status in {status.value for status in _PROCESSING_STATUSES}:
        return "processing"
    if any(item.get("analyzer_name") == _OPERATOR_CORRECTION for item in interpretation):
        return "user_confirmed"
    dispositions = {item.get("disposition") for item in interpretation}
    if (
        "reject" in dispositions
        and "accept" not in dispositions
        and "correct_and_accept" not in dispositions
    ):
        return "rejected"
    if any(item.get("proposal_id") and item.get("disposition") is None for item in interpretation):
        return "pending_review"
    if interpretation:
        return "interpretation"
    return "source"
