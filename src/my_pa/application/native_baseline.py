"""WP-12E frozen, bounded and crash-resumable synthetic baselines.

The executor owns orchestration only. Exact source reads and immutable evidence
admission stay at the WP-12C controller boundary; cursors remain private in the
persistence adapter. A checkpoint is requested only after that controller has
returned a durable admission receipt.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Protocol

from my_pa.application.native_sources import (
    NativeReadPageReceipt,
    NativeRequestContext,
    NativeSourceController,
)
from my_pa.contracts.native_baseline import (
    BaselineResumePoint,
    FrozenBaseline,
    NativeBaselineJob,
)
from my_pa.contracts.v1.base import canonical_json
from my_pa.contracts.v1.native_sources import NATIVE_SOURCE_MAX_PAGE_SIZE, NativeSourceKind
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "BaselineExecutionError",
    "BaselineResumePoint",
    "FrozenBaseline",
    "NativeBaselineExecutor",
    "NativeBaselineJob",
    "NativeBaselineStore",
]


class BaselineExecutionError(RuntimeError):
    """The durable baseline state could not make bounded forward progress."""


class NativeBaselineStore(Protocol):
    def selected_kinds(self, configuration_id: str) -> tuple[NativeSourceKind, ...]: ...

    def prepare(
        self,
        *,
        configuration_id: str,
        idempotency_key: str,
        proposed_cutoff_at: datetime,
        adapter_identity: str,
    ) -> FrozenBaseline: ...

    def claim(
        self, run_id: str, *, owner: str, lease_for: timedelta
    ) -> NativeBaselineJob | None: ...

    def resume_point(self, job_id: str) -> BaselineResumePoint: ...

    def checkpoint_admitted_page(
        self,
        job: NativeBaselineJob,
        page: NativeReadPageReceipt,
        *,
        recorded_at: datetime,
    ) -> None: ...

    def finish(self, job: NativeBaselineJob, *, recorded_at: datetime) -> None: ...

    def complete(self, run_id: str) -> bool: ...


ContextPairFactory = Callable[[str, datetime], tuple[NativeRequestContext, NativeRequestContext]]
AdmissionHook = Callable[[NativeBaselineJob, NativeReadPageReceipt], None]


class NativeBaselineExecutor:
    """Execute one immutable run in deterministic pages with durable resume."""

    def __init__(
        self,
        *,
        controller: NativeSourceController,
        store: NativeBaselineStore,
        contexts: ContextPairFactory,
        clock: Callable[[], datetime],
        after_admission: AdmissionHook | None = None,
    ) -> None:
        self._controller = controller
        self._store = store
        self._contexts = contexts
        self._clock = clock
        self._after_admission = after_admission

    def execute(
        self,
        *,
        configuration_id: str,
        idempotency_key: str,
        owner: str,
        lease_for: timedelta = timedelta(minutes=5),
    ) -> FrozenBaseline:
        if not idempotency_key or not owner or lease_for <= timedelta(0):
            raise ValueError("a baseline requires bounded idempotency, owner and lease inputs")
        kinds = self._store.selected_kinds(configuration_id)
        if not kinds:
            raise BaselineExecutionError("the baseline configuration has no selected source kind")
        identities = {kind.value: self._controller.adapter_identity(kind) for kind in sorted(kinds)}
        adapter_identity = sha256(canonical_json(identities).encode()).hexdigest()
        frozen = self._store.prepare(
            configuration_id=configuration_id,
            idempotency_key=idempotency_key,
            proposed_cutoff_at=ensure_utc(self._clock()),
            adapter_identity=adapter_identity,
        )
        while not self._store.complete(frozen.run_id):
            job = self._store.claim(frozen.run_id, owner=owner, lease_for=lease_for)
            if job is None:
                raise BaselineExecutionError(
                    "the baseline has unfinished work but no claimable job"
                )
            resume = self._store.resume_point(job.job_id)
            if resume.terminal:
                self._store.finish(job, recorded_at=ensure_utc(self._clock()))
                continue
            request_id = f"baseline:{job.job_id}:{resume.page_count + 1}"
            at = ensure_utc(self._clock())
            control_context, admission_context = self._contexts(request_id, at)
            page = self._controller.read_and_admit_page(
                control_context,
                admission_context,
                configuration_id=job.configuration_id,
                bucket_id=job.bucket_id,
                time_range=(job.range_start, job.range_end) if not job.current_inventory else None,
                cursor=resume.cursor,
                limit=NATIVE_SOURCE_MAX_PAGE_SIZE,
                checkpoint_job_id=job.job_id,
                checkpoint_run_id=job.run_id,
            )
            if self._after_admission is not None:
                self._after_admission(job, page)
            self._store.checkpoint_admitted_page(job, page, recorded_at=at)
        return frozen
