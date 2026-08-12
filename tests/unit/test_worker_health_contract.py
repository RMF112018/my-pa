from __future__ import annotations

from my_pa.infrastructure.persistence.tables import capture_jobs, jobs, worker_heartbeats


def test_job_planes_have_retry_schedule_and_dead_letter_evidence() -> None:
    for table in (jobs, capture_jobs):
        assert {"next_attempt_at", "dead_lettered_at"} <= set(table.c.keys())
        claim_index = next(index for index in table.indexes if "claim_order" in index.name)
        assert [column.name for column in claim_index.columns][:3] == [
            "principal_id",
            "state",
            "next_attempt_at",
        ]


def test_worker_heartbeat_is_content_free_and_principal_scoped() -> None:
    assert set(worker_heartbeats.c.keys()) == {
        "worker_owner",
        "principal_id",
        "plane",
        "started_at",
        "heartbeat_at",
        "stopped_at",
    }
    assert [column.name for column in worker_heartbeats.primary_key.columns] == [
        "worker_owner",
        "principal_id",
    ]
