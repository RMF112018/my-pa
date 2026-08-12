"""WP-12E frozen-window, paging and recovery application contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from my_pa.application.native_baseline import (
    BaselineResumePoint,
    FrozenBaseline,
    NativeBaselineExecutor,
    NativeBaselineJob,
)
from my_pa.application.native_sources import NativeAdmissionReceipt, NativeReadPageReceipt
from my_pa.contracts.v1.native_sources import NativeSourceKind

WHEN = datetime(2026, 8, 5, 12, tzinfo=UTC)
CONFIGURATION = "ncfg_0000000000000001"
RUN = "nrun_0000000000000001"


class SyntheticController:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_next = False

    def adapter_identity(self, kind: NativeSourceKind) -> str:
        return f"synthetic-{kind.value}-v1"

    def read_and_admit_page(self, *contexts: object, **request: object) -> NativeReadPageReceipt:
        del contexts
        self.calls.append(request)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthetic admission outage")
        bucket = str(request["bucket_id"])
        cursor = cast(str | None, request["cursor"])
        if bucket.endswith("1") and cursor is None:
            next_cursor, count = "mail-page-2", 100
        else:
            next_cursor, count = None, {"2": 2, "3": 3}.get(bucket[-1], 1)
        return NativeReadPageReceipt(
            admission=NativeAdmissionReceipt(
                request_id="synthetic",
                bucket_id=bucket,
                admitted_count=count,
                duplicate_count=0,
                evidence_digest="a" * 64,
                enrichment_proposal_count=0,
                enrichment_failed=False,
            ),
            authority_id=f"nauth_{len(self.calls):016d}",
            next_cursor=next_cursor,
        )


class DurableStore:
    def __init__(self) -> None:
        self.frozen: FrozenBaseline | None = None
        self.prepare_cutoffs: list[datetime] = []
        self.jobs = [
            NativeBaselineJob(
                "njob_0000000000000001",
                RUN,
                CONFIGURATION,
                1,
                "nbkt_0000000000000001",
                NativeSourceKind.MAIL,
                WHEN - timedelta(days=30),
                WHEN,
                False,
                "worker",
            ),
            NativeBaselineJob(
                "njob_0000000000000002",
                RUN,
                CONFIGURATION,
                1,
                "nbkt_0000000000000002",
                NativeSourceKind.CALENDAR,
                WHEN - timedelta(days=30),
                WHEN + timedelta(days=90),
                False,
                "worker",
            ),
            NativeBaselineJob(
                "njob_0000000000000003",
                RUN,
                CONFIGURATION,
                1,
                "nbkt_0000000000000003",
                NativeSourceKind.CONTACTS,
                WHEN,
                WHEN,
                True,
                "worker",
            ),
        ]
        self.resume: dict[str, BaselineResumePoint] = {}
        self.finished: set[str] = set()
        self.checkpoints: list[tuple[str, str | None, int]] = []
        self.fail_finish_once = False

    def selected_kinds(self, configuration_id: str) -> tuple[NativeSourceKind, ...]:
        assert configuration_id == CONFIGURATION
        return tuple(job.kind for job in self.jobs)

    def prepare(
        self,
        *,
        configuration_id: str,
        idempotency_key: str,
        proposed_cutoff_at: datetime,
        adapter_identity: str,
    ) -> FrozenBaseline:
        assert idempotency_key == "baseline-1"
        assert len(adapter_identity) == 64
        self.prepare_cutoffs.append(proposed_cutoff_at)
        if self.frozen is None:
            self.frozen = FrozenBaseline(RUN, configuration_id, 1, proposed_cutoff_at)
        return self.frozen

    def claim(self, run_id: str, *, owner: str, lease_for: timedelta) -> NativeBaselineJob | None:
        assert run_id == RUN and owner == "worker" and lease_for <= timedelta(minutes=5)
        return next(
            (
                replace(job, lease_owner=owner)
                for job in self.jobs
                if job.job_id not in self.finished
            ),
            None,
        )

    def resume_point(self, job_id: str) -> BaselineResumePoint:
        return self.resume.get(job_id, BaselineResumePoint(None, False, 0))

    def checkpoint_admitted_page(
        self,
        job: NativeBaselineJob,
        page: NativeReadPageReceipt,
        *,
        recorded_at: datetime,
    ) -> None:
        del recorded_at
        prior = self.resume_point(job.job_id)
        count = page.admission.admitted_count + page.admission.duplicate_count
        self.resume[job.job_id] = BaselineResumePoint(
            page.next_cursor,
            page.next_cursor is None,
            prior.page_count + 1,
        )
        self.checkpoints.append((job.job_id, page.next_cursor, count))

    def finish(self, job: NativeBaselineJob, *, recorded_at: datetime) -> None:
        del recorded_at
        if self.fail_finish_once:
            self.fail_finish_once = False
            raise RuntimeError("synthetic crash after terminal checkpoint")
        assert self.resume_point(job.job_id).terminal
        self.finished.add(job.job_id)

    def complete(self, run_id: str) -> bool:
        assert run_id == RUN
        return len(self.finished) == len(self.jobs)


def _contexts(request_id: str, at: datetime) -> tuple[Any, Any]:
    del request_id, at
    return object(), object()


def test_all_source_windows_are_exact_bounded_and_cutoff_is_reused() -> None:
    store = DurableStore()
    controller = SyntheticController()
    calls = 0

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        return WHEN if calls <= 8 else WHEN + timedelta(days=1)

    executor = NativeBaselineExecutor(
        controller=controller,  # type: ignore[arg-type]
        store=store,
        contexts=_contexts,
        clock=clock,
    )
    first = executor.execute(
        configuration_id=CONFIGURATION, idempotency_key="baseline-1", owner="worker"
    )
    second = executor.execute(
        configuration_id=CONFIGURATION, idempotency_key="baseline-1", owner="worker"
    )
    assert first.cutoff_at == second.cutoff_at == WHEN
    assert len(controller.calls) == 4
    assert all(call["limit"] == 100 for call in controller.calls)
    assert controller.calls[0]["time_range"] == (WHEN - timedelta(days=30), WHEN)
    assert controller.calls[1]["cursor"] == "mail-page-2"
    assert controller.calls[2]["time_range"] == (
        WHEN - timedelta(days=30),
        WHEN + timedelta(days=90),
    )
    assert controller.calls[3]["time_range"] is None


def test_admission_failure_and_post_admission_crash_never_advance_checkpoint() -> None:
    store = DurableStore()
    controller = SyntheticController()
    controller.fail_next = True
    executor = NativeBaselineExecutor(
        controller=controller,  # type: ignore[arg-type]
        store=store,
        contexts=_contexts,
        clock=lambda: WHEN,
    )
    with pytest.raises(RuntimeError, match="admission outage"):
        executor.execute(
            configuration_id=CONFIGURATION,
            idempotency_key="baseline-1",
            owner="worker",
        )
    assert store.checkpoints == []

    crash_once = True

    def crash_after_admission(job: NativeBaselineJob, page: NativeReadPageReceipt) -> None:
        nonlocal crash_once
        del job, page
        if crash_once:
            crash_once = False
            raise RuntimeError("synthetic crash before checkpoint")

    crashing = NativeBaselineExecutor(
        controller=controller,  # type: ignore[arg-type]
        store=store,
        contexts=_contexts,
        clock=lambda: WHEN,
        after_admission=crash_after_admission,
    )
    with pytest.raises(RuntimeError, match="before checkpoint"):
        crashing.execute(
            configuration_id=CONFIGURATION,
            idempotency_key="baseline-1",
            owner="worker",
        )
    assert store.checkpoints == []

    store.fail_finish_once = True
    with pytest.raises(RuntimeError, match="terminal checkpoint"):
        executor.execute(
            configuration_id=CONFIGURATION,
            idempotency_key="baseline-1",
            owner="worker",
        )
    calls_after_terminal = len(controller.calls)
    executor.execute(configuration_id=CONFIGURATION, idempotency_key="baseline-1", owner="worker")
    assert len(controller.calls) == calls_after_terminal + 2
    assert store.complete(RUN)
