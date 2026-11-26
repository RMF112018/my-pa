"""P6 XER S7-3/S7-4a: the admission service `import_p6`.

Contract `docs/architecture/schedule-xer-import-contract.md` sections 9.1
(admission), 10.2 (switch), 10.3 (strict inputs) and 10.6 (errors) under
ADR-023. S7-4a wraps `ScheduleP6Application.import_p6` in
`schedule_publications.import_p6` (policy, audit, ChatLLM, remote) and adds
the section 7.7 import budgets and snapshot quota (`rate_limited`, checked in
the admission transaction after every answer that writes nothing); this
module holds the behaviour the capability serves:

1. the switch (read at every call): off answers `unsupported` before anything
   is read; then strict input (an unknown, missing or mistyped key is
   `invalid_request` naming the field, never its value); `p6_xml` is
   `unsupported(FORMAT)` until the XML slice;
2. outside any transaction, the files-workspace store's contained read path
   (no symlink, no special or multiply-linked file): the current version must
   equal `expected_version` (`conflict(EXPECTED_VERSION)`), the size must be at
   most 16 MiB before a byte is read (`unsupported(MAX_BYTES)`), the bytes'
   SHA-256 must equal `expected_sha256` (`conflict(EXPECTED_SHA256)`), and the
   fingerprint is re-read after reading (`conflict(EXPECTED_VERSION)`);
3. the bytes are sniffed (the path's extension is never consulted):
   `unsupported(SOURCE_FORMAT)` unless they are XER;
4. one transaction (`admit_p6_publication`): replay, Project, Series,
   format, content idempotency, snapshot, publication, job.

The answer names the publication, its job, the outcome and the admitted
bytes' digest and size; it never carries the workspace path (stored for
provenance, never served, section 10.4).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final

from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    SafeDetail,
    UnavailableError,
    UnsupportedError,
)
from my_pa.contracts.ports import (
    FileWorkspaceReader,
    FileWorkspaceStore,
    FileWorkspaceUnavailableError,
    ScheduleP6UnitOfWork,
)
from my_pa.domain.files.errors import FilesArgumentError, FilesRefusal
from my_pa.domain.files.vocabulary import FilesReason
from my_pa.domain.schedule.p6_import import (
    MAX_P6_SNAPSHOT_BYTES,
    P6Admission,
    P6AdmissionLimits,
    P6AdmissionOutcome,
    P6AdmissionRefusal,
    P6AdmissionRejectedError,
    P6ImportRequest,
    P6RequestError,
    P6Snapshot,
    P6SourceFormat,
    p6_import_request,
    p6_import_request_digest,
    sniff_p6_format,
)

__all__ = ["ScheduleP6Application", "p6_admission_answer"]

#: Section 10.3: each request field and the detail an `invalid_request` names.
_FIELD_DETAILS: Final[Mapping[str, SafeDetail]] = {
    "project_id": SafeDetail.PROJECT_ID,
    "series_id": SafeDetail.SERIES_ID,
    "series_name": SafeDetail.SERIES_NAME,
    "series_auto": SafeDetail.SERIES_AUTO,
    "workspace_id": SafeDetail.WORKSPACE_ID,
    "path": SafeDetail.PATH,
    "expected_version": SafeDetail.EXPECTED_VERSION,
    "expected_sha256": SafeDetail.EXPECTED_SHA256,
    "format": SafeDetail.FORMAT,
    "accept_project_identity_change": SafeDetail.ACCEPT_PROJECT_IDENTITY_CHANGE,
    "supersedes_publication_id": SafeDetail.SUPERSEDES_PUBLICATION_ID,
    "idempotency_key": SafeDetail.IDEMPOTENCY_KEY,
}

#: Section 9.1 step 4: each typed refusal and its public answer.
_REFUSALS: Final[Mapping[P6AdmissionRefusal, tuple[type[ApplicationError], SafeDetail | None]]] = {
    P6AdmissionRefusal.PROJECT_NOT_FOUND: (NotFoundError, SafeDetail.PROJECT_ID),
    P6AdmissionRefusal.SERIES_NOT_FOUND: (NotFoundError, SafeDetail.SERIES_ID),
    P6AdmissionRefusal.SERIES_FORMAT: (ConflictError, SafeDetail.SERIES_FORMAT),
    P6AdmissionRefusal.IDEMPOTENCY_KEY_CONFLICT: (ConflictError, SafeDetail.IDEMPOTENCY_KEY),
    P6AdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND: (
        NotFoundError,
        SafeDetail.SUPERSEDES_PUBLICATION_ID,
    ),
    P6AdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_TERMINAL: (
        ConflictError,
        SafeDetail.SUPERSEDES_PUBLICATION_ID,
    ),
    P6AdmissionRefusal.SUPERSEDED_PUBLICATION_HAS_SUCCESSOR: (
        ConflictError,
        SafeDetail.SUPERSEDES_PUBLICATION_ID,
    ),
    # S7-4a (section 7.7): the quota names its limit; the import budget is the
    # bare bounded-retry answer.
    P6AdmissionRefusal.STORAGE_QUOTA: (RateLimitedError, SafeDetail.STORAGE_QUOTA),
    P6AdmissionRefusal.IMPORT_RATE: (RateLimitedError, None),
}


def _read_refusal(reason: FilesReason) -> ApplicationError:
    if reason is FilesReason.NOT_FOUND:
        return NotFoundError(SafeDetail.PATH)
    if reason in (FilesReason.EXTERNAL_CHANGE_DETECTED, FilesReason.VERSION_CONFLICT):
        return ConflictError(SafeDetail.EXPECTED_VERSION)
    if reason is FilesReason.UNSUPPORTED_ENTRY:
        return UnsupportedError(SafeDetail.PATH)
    if reason is FilesReason.INVALID_PATH:
        return InvalidRequestError(SafeDetail.PATH)
    return UnavailableError()


@contextmanager
def _contained_read() -> Iterator[None]:
    """Map the store's refusals to public errors, naming no value (no store error rides along)."""
    failure: ApplicationError | None = None
    try:
        yield
    except FilesRefusal as error:
        failure = _read_refusal(error.reason)
    except FilesArgumentError as error:
        failure = InvalidRequestError(
            SafeDetail.EXPECTED_VERSION if error.field == "expected_version" else SafeDetail.PATH
        )
    except FileWorkspaceUnavailableError:
        failure = UnavailableError()
    if failure is not None:
        raise failure


def _read_bytes(store: FileWorkspaceStore, request: P6ImportRequest) -> bytes:
    """Section 9.1 step 2: version, size before any byte, bytes, digest, fingerprint again."""
    reader: FileWorkspaceReader | None = None
    try:
        with _contained_read():
            reader = store.open_download(request.path, expected_version=request.expected_version)
            if reader.version != request.expected_version:
                raise ConflictError(SafeDetail.EXPECTED_VERSION)
            if reader.size > MAX_P6_SNAPSHOT_BYTES:
                raise UnsupportedError(SafeDetail.MAX_BYTES)
            data = b"".join(reader.read_range(0, reader.size))
        if len(data) != reader.size:
            raise ConflictError(SafeDetail.EXPECTED_VERSION)
        if hashlib.sha256(data).hexdigest() != request.expected_sha256:
            raise ConflictError(SafeDetail.EXPECTED_SHA256)
        with _contained_read():
            # The fingerprint re-read after the bytes: a zero-length read re-checks it.
            reader.read_range(reader.size, 0)
        return data
    finally:
        if reader is not None:
            reader.close()


def p6_admission_answer(admission: P6Admission) -> dict[str, Any]:
    """The admission's public shape: identifiers, outcome and the bytes' digest, no path."""
    return {
        "series_id": admission.series_id,
        "publication_id": admission.publication_id,
        "operation_id": admission.operation_id,
        "status": admission.status,
        "outcome": admission.outcome.value,
        "created": admission.outcome is P6AdmissionOutcome.CREATED,
        "already_present": admission.outcome is P6AdmissionOutcome.ALREADY_PRESENT,
        "series_created": admission.series_created,
        "source_format": P6SourceFormat.P6_XER.value,
        "document": {"sha256": admission.sha256, "size_bytes": admission.size_bytes},
    }


class ScheduleP6Application:
    """`import_p6` over a P6 unit of work and the composed files workspaces."""

    def __init__(
        self,
        unit_of_work: Callable[[], ScheduleP6UnitOfWork],
        workspaces: Callable[[str], FileWorkspaceStore | None],
        *,
        enabled: Callable[[], bool],
        limits: P6AdmissionLimits | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._workspaces = workspaces
        #: Section 10.2: read at every admission, never cached.
        self._enabled = enabled
        #: S7-4a (section 7.7): the budgets and quota; `None` checks neither.
        self._limits = limits

    def import_p6(
        self,
        principal_id: str,
        payload: Mapping[str, object],
        *,
        scenario_plane_effective: bool = False,
    ) -> dict[str, Any]:
        """Admit one P6 export from a files-workspace file (section 9.1)."""
        if not self._enabled():
            raise UnsupportedError()
        try:
            request = p6_import_request(payload)
        except P6RequestError as error:
            detail = _FIELD_DETAILS.get(error.field)
            failure = InvalidRequestError() if detail is None else InvalidRequestError(detail)
            raise failure from None
        if request.format is not P6SourceFormat.P6_XER:
            raise UnsupportedError(SafeDetail.FORMAT)
        # The S6 plane gate, as the PDF import: an automatic Series needs the plane.
        if request.series_auto and not scenario_plane_effective:
            raise InvalidRequestError(SafeDetail.SERIES_AUTO)
        store = self._workspaces(request.workspace_id)
        if store is None:
            raise NotFoundError(SafeDetail.WORKSPACE_ID)
        data = _read_bytes(store, request)
        if sniff_p6_format(data) is not P6SourceFormat.P6_XER:
            raise UnsupportedError(SafeDetail.SOURCE_FORMAT)
        snapshot = P6Snapshot(content=data, format=P6SourceFormat.P6_XER)
        digest = p6_import_request_digest(principal_id, request)
        refusal: P6AdmissionRefusal | None = None
        try:
            with self._unit_of_work() as work:
                admission = work.p6.admit_p6_publication(
                    principal_id, request, digest, snapshot, self._limits
                )
        except P6AdmissionRejectedError as error:
            refusal = error.reason
        if refusal is not None:
            # Raised outside the handler so the refusal is not left in `__context__`.
            error_type, detail = _REFUSALS[refusal]
            raise error_type() if detail is None else error_type(detail)
        return p6_admission_answer(admission)
