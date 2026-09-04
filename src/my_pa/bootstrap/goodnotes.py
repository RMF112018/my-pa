"""Production composition for an explicitly admitted local GoodNotes source.

Construction is inert.  The engine-based reconciliation deliberately closes
the receipt transaction before any OCR/model work and opens the write
transaction only after all bounded external work has completed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from sqlalchemy.engine import Engine

from my_pa.application.goodnotes import (
    GoodNotesService,
    PageTranscriber,
    ReadOnlyGoodNotesSource,
    ReconciliationConflictError,
    require_available_liveness,
)
from my_pa.domain.goodnotes.liveness import GoodNotesSourceLivenessReceipt
from my_pa.domain.goodnotes.models import ReconciliationReceipt, SourcePage
from my_pa.infrastructure.goodnotes.local import (
    BoundedLocalOCRTranscriber,
    LocalGoodNotesObserver,
    ManifestGoodNotesSource,
)
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository

_MAX_MANIFEST_BYTES = 1_048_576
_DEFAULT_LIVENESS_INTERVAL = timedelta(minutes=5)


@dataclass(slots=True)
class _LocalLivenessSession:
    observer: LocalGoodNotesObserver
    issued: dict[str, GoodNotesSourceLivenessReceipt] = field(default_factory=dict)

    def remember(self, receipt: GoodNotesSourceLivenessReceipt) -> None:
        self.issued[receipt.relative_path] = receipt

    def issued_here(self, receipt: GoodNotesSourceLivenessReceipt) -> bool:
        return self.issued.get(receipt.relative_path) is receipt


@dataclass(frozen=True, slots=True)
class _SettledGoodNotesSource:
    """Immutable bytes admitted before any database or OCR boundary opens."""

    pages: tuple[SourcePage, ...]

    def inventory(self, _principal_id: str) -> tuple[SourcePage, ...]:
        return self.pages


@dataclass(frozen=True, slots=True)
class LocalGoodNotesRuntime:
    source: ReadOnlyGoodNotesSource
    transcriber: PageTranscriber
    _liveness: _LocalLivenessSession | None = field(default=None, repr=False)
    _clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC), repr=False)

    def observe_liveness(
        self,
        *,
        principal_id: str,
        previous: tuple[GoodNotesSourceLivenessReceipt, ...] = (),
        maximum_staleness: timedelta = _DEFAULT_LIVENESS_INTERVAL,
    ) -> tuple[GoodNotesSourceLivenessReceipt, ...]:
        """Mint liveness evidence inside the composed runtime, never from CLI input."""
        session = self._require_liveness_session()
        paths = self._manifest_paths(principal_id)
        prior_by_path = {receipt.relative_path: receipt for receipt in previous}
        receipts = tuple(
            session.observer.liveness(
                path,
                checked_at=self._clock(),
                maximum_staleness=maximum_staleness,
                previous=prior_by_path.get(str(path)),
            )
            for path in paths
        )
        for receipt in receipts:
            session.remember(receipt)
        return receipts

    def reconcile(
        self,
        *,
        engine: Engine,
        principal_id: str,
        idempotency_key: str,
        liveness_receipts: tuple[GoodNotesSourceLivenessReceipt, ...] | None = None,
    ) -> ReconciliationReceipt:
        admitted_manifest_sha256: str | None = None
        reconciliation_source = self.source
        if self._liveness is not None:
            admitted_manifest_sha256 = self.require_current_liveness(
                principal_id, liveness_receipts
            )
            reconciliation_source = _SettledGoodNotesSource(
                tuple(self.source.inventory(principal_id))
            )
            if self._manifest_sha256() != admitted_manifest_sha256:
                raise ValueError("the GoodNotes manifest changed after liveness admission")
        service = GoodNotesService()
        plan = service.plan(
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            source=reconciliation_source,
            transcriber=self.transcriber,
        )
        # Short admission/receipt connection: exact registry + enrollment
        # identity is proven before OCR/model execution, then closed.
        with engine.connect() as connection:
            repository = PostgresGoodNotesRepository(connection)
            service.admit(plan, repository)
            prior = repository.receipt(principal_id, idempotency_key)
            service.require_within_deadline(plan)
        if prior is not None:
            if prior.request_fingerprint != plan.request_fingerprint:
                raise ReconciliationConflictError(
                    "the idempotency key is already bound to another inventory"
                )
            return ReconciliationReceipt(
                receipt_id=prior.receipt_id,
                principal_id=prior.principal_id,
                idempotency_key=prior.idempotency_key,
                request_fingerprint=prior.request_fingerprint,
                page_version_ids=prior.page_version_ids,
                created_regions=prior.created_regions,
                replayed=True,
            )
        prepared = service.prepare(
            plan=plan,
            source=reconciliation_source,
            transcriber=self.transcriber,
        )
        # The durable transaction starts only after OCR and the proposal gate.
        with engine.begin() as connection:
            receipt = service.persist(prepared, PostgresGoodNotesRepository(connection))
            service.require_within_deadline(plan)
            return receipt

    def _require_liveness_session(self) -> _LocalLivenessSession:
        if self._liveness is None:
            raise ValueError("GoodNotes liveness is unavailable for this runtime")
        return self._liveness

    def _manifest_paths(self, principal_id: str) -> tuple[PurePosixPath, ...]:
        if not isinstance(self.source, ManifestGoodNotesSource):
            raise ValueError("GoodNotes liveness requires a manifest-backed local source")
        raw = self.source._read(self.source.manifest_relative_path, _MAX_MANIFEST_BYTES)
        try:
            document = json.loads(raw)
            if not isinstance(document, dict) or not isinstance(document.get("pages"), list):
                raise ValueError
            entries = document["pages"]
            paths = tuple(
                dict.fromkeys(
                    PurePosixPath(str(entry["relative_path"]))
                    for entry in entries
                    if isinstance(entry, dict) and entry.get("principal_id") == principal_id
                )
            )
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("the GoodNotes manifest is invalid for liveness") from error
        if not paths:
            raise ValueError("the GoodNotes manifest has no source for this Principal")
        return paths

    def _manifest_sha256(self) -> str:
        if not isinstance(self.source, ManifestGoodNotesSource):
            raise ValueError("GoodNotes liveness requires a manifest-backed local source")
        raw = self.source._read(self.source.manifest_relative_path, _MAX_MANIFEST_BYTES)
        return hashlib.sha256(raw).hexdigest()

    def require_current_liveness(
        self,
        principal_id: str,
        receipts: tuple[GoodNotesSourceLivenessReceipt, ...] | None,
    ) -> str:
        session = self._require_liveness_session()
        if not receipts:
            raise ValueError("fresh GoodNotes liveness receipts are required")
        manifest_sha256 = self._manifest_sha256()
        paths = self._manifest_paths(principal_id)
        receipts_by_path = {receipt.relative_path: receipt for receipt in receipts}
        if len(receipts_by_path) != len(receipts) or set(receipts_by_path) != set(map(str, paths)):
            raise ValueError("GoodNotes liveness receipts do not cover the admitted source")
        if any(not session.issued_here(receipt) for receipt in receipts):
            raise ValueError("GoodNotes liveness receipts were not issued by this runtime")
        checked_at = self._clock()
        for path in paths:
            receipt = receipts_by_path[str(path)]
            observation = session.observer.settle(path)
            require_available_liveness(
                receipt,
                source_root_id=session.observer.source_root_id,
                relative_path=str(path),
                content_sha256=observation.sha256,
                at=checked_at,
            )
        if self._manifest_sha256() != manifest_sha256:
            raise ValueError("the GoodNotes manifest changed during liveness admission")
        return manifest_sha256


def compose_local_goodnotes_runtime(
    *,
    admitted_root: Path,
    manifest_relative_path: PurePosixPath,
    ocr_command: tuple[str, ...],
    ocr_name: str,
    ocr_version: str,
    ocr_root: Path,
    source_root_id: str = "goodnotes-local",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> LocalGoodNotesRuntime:
    return LocalGoodNotesRuntime(
        source=ManifestGoodNotesSource(
            root=admitted_root,
            manifest_relative_path=manifest_relative_path,
        ),
        transcriber=BoundedLocalOCRTranscriber(
            command=ocr_command,
            name=ocr_name,
            version=ocr_version,
            executable_root=ocr_root,
        ),
        _liveness=_LocalLivenessSession(
            LocalGoodNotesObserver(root=admitted_root, source_root_id=source_root_id)
        ),
        _clock=clock,
    )
