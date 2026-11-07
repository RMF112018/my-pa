"""Reports Modernization WP06 (W3c): consumption, the GC and `transfer-gc` on PostgreSQL.

The `database` tier, each test on its own disposable clone (`migrated_engine`),
through `ApplicationService` with the real `SqlAlchemyUnitOfWork`, a real
`FilesystemReportContentStore` and `FilesystemReportTransferStaging` on one
`tmp_path` root (W3b's rig):

* publish and update consume transfers: the session row names the content the
  version references (new, or the head's reused one), the staging is gone
  after the commit, a retry replays the original receipt, a second use of the
  token is the bare `not_found`; the raw token is in no `knowledge.report_*`
  row and no audit event;
* cross-client and foreign-Principal consumption is the same `not_found` with
  zero mutation (sessions, versions, receipts, content objects, staging);
* `collect_report_transfers` expires, discards and finds orphans, and skips
  a session another transaction holds (`FOR UPDATE SKIP LOCKED`);
* `apps/cli/report_content.py transfer-gc` exit codes 0 / 1 / 3 and its JSON
  summary (no identifier, no path);
* (slow) a 16 MiB identity random-ASCII text transfer through the service and
  back through 64 read_chunk calls, byte-exact, timed and measured.

Every byte is synthetic.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import time
import tracemalloc
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import report_content as report_content_cli
from sqlalchemy import Engine, text

from my_pa.application.report_transfer_gc import collect_report_transfers
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import operator
from tests.database.test_reports_transfer_application import (
    CHUNK,
    CLIENT_A,
    CLIENT_B,
    WHEN,
    Rig,
    _append,
    _begin,
    _error,
    _ok,
    _op,
    _sha,
    _text,
)

pytestmark = pytest.mark.database

LATER: Final = WHEN + timedelta(hours=2)
MIB: Final = 1024 * 1024
_REPORT_TABLES: Final = (
    "knowledge.report_transfer_sessions",
    "knowledge.report_transfer_chunks",
    "knowledge.report_receipts",
    "knowledge.report_versions",
    "knowledge.report_content_objects",
    "knowledge.audit_events",
)


def _finalized(
    rig: Rig, principal: Principal, staged: bytes, *, key: str, client: str | None = CLIENT_A
) -> tuple[str, str]:
    session_id = _begin(rig, principal, staged, key=key, client=client)
    for sequence, offset in enumerate(range(0, len(staged), CHUNK)):
        piece = staged[offset : offset + CHUNK]
        _ok(_append(rig, principal, session_id, sequence, piece, client=client))
    finalized = _ok(
        _op(rig, principal, Capability.REPORTS_TRANSFER_FINALIZE, session_id, client=client)
    )
    return session_id, str(finalized["content_token"])


def _reference(session_id: str, token: str) -> dict[str, Any]:
    return {"transfer": {"session_id": session_id, "content_token": token}}


def _publish(
    rig: Rig, principal: Principal, content: dict[str, Any], *, key: str, client: str | None
) -> dict[str, Any]:
    return rig.invoke(
        principal,
        Capability.REPORTS_PUBLISH,
        {"title": "Synthetic transfer report", "content": content, "idempotency_key": key},
        client=client,
    )


def _update(
    rig: Rig,
    principal: Principal,
    report_id: str,
    patch: dict[str, Any],
    *,
    key: str,
    expected_version: int,
    client: str | None,
) -> dict[str, Any]:
    return rig.invoke(
        principal,
        Capability.REPORTS_UPDATE,
        {
            "report_id": report_id,
            "expected_version": expected_version,
            "patch": patch,
            "change_reason": "Synthetic transfer update.",
            "idempotency_key": key,
        },
        client=client,
    )


def _session(engine: Engine, session_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT state, consumed_content_id, consumed_at "
                    "FROM knowledge.report_transfer_sessions WHERE session_id = :id"
                ),
                {"id": session_id},
            )
            .mappings()
            .one()
        )
        return dict(row)


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
            )
            for table in _REPORT_TABLES
            if table != "knowledge.audit_events"
        }


def _plane(rig: Rig) -> tuple[object, ...]:
    """Zero-mutation evidence: sessions, ledger, staging and every report row count."""
    return (rig.snapshot(), _counts(rig.engine))


def _read_back(rig: Rig, principal: Principal, report_id: str, version: int) -> bytes:
    out = bytearray()
    offset: int | None = 0
    while offset is not None:
        answer = _ok(
            rig.invoke(
                principal,
                Capability.REPORTS_TRANSFER_READ_CHUNK,
                {"report_id": report_id, "version_number": version, "offset": offset},
            )
        )
        out += base64.b64decode(answer["chunk"])
        offset = answer["next_offset"]
    return bytes(out)


def test_publish_and_update_consume_transfers(migrated_engine: Engine, tmp_path: Path) -> None:
    rig = Rig(migrated_engine, tmp_path)
    owner = operator()
    staged = _text(CHUNK + 3333, seed=31)
    sid, token = _finalized(rig, owner, staged, key="p")
    published = _ok(_publish(rig, owner, _reference(sid, token), key="pub", client=CLIENT_A))
    print("DB_TRANSFER_PUBLISH_JSON", json.dumps(published, sort_keys=True))
    content_id = published["content"]["content_id"]
    row = _session(migrated_engine, sid)
    assert row["state"] == "consumed" and row["consumed_content_id"] == content_id
    assert row["consumed_at"] == WHEN
    assert not rig.staging.has_session(sid)
    assert _read_back(rig, owner, published["report_id"], 1) == staged
    # The retry replays the original receipt; another key is the bare not_found.
    before = _plane(rig)
    again = _ok(_publish(rig, owner, _reference(sid, token), key="pub", client=CLIENT_A))
    assert again == {**published, "replayed": True}
    reused = _error(_publish(rig, owner, _reference(sid, token), key="pub-2", client=CLIENT_A))
    assert reused["code"] == "not_found" and reused["safe_details"] == []
    assert _plane(rig) == before
    # Update with new content: a content version naming the new object.
    new = _text(2 * CHUNK + 11, seed=32)
    uid, utoken = _finalized(rig, owner, new, key="u")
    updated = _ok(
        _update(
            rig,
            owner,
            published["report_id"],
            {"content": _reference(uid, utoken)},
            key="upd",
            expected_version=1,
            client=CLIENT_A,
        )
    )
    print("DB_TRANSFER_UPDATE_JSON", json.dumps(updated, sort_keys=True))
    assert updated["change_kind"] == "content" and updated["content_id"] != content_id
    assert _session(migrated_engine, uid)["consumed_content_id"] == updated["content_id"]
    assert _read_back(rig, owner, published["report_id"], 2) == new
    # The head's content again, with a title change: the head's object is reused.
    sid3, token3 = _finalized(rig, owner, new, key="same")
    objects = _counts(migrated_engine)["knowledge.report_content_objects"]
    same = _ok(
        _update(
            rig,
            owner,
            published["report_id"],
            {"content": _reference(sid3, token3), "title": "Synthetic retitled"},
            key="upd-same",
            expected_version=2,
            client=CLIENT_A,
        )
    )
    assert same["change_kind"] == "metadata" and same["content_id"] == updated["content_id"]
    assert _session(migrated_engine, sid3)["consumed_content_id"] == updated["content_id"]
    assert _counts(migrated_engine)["knowledge.report_content_objects"] == objects
    # The raw tokens are stored nowhere in the plane or the audit trail.
    with migrated_engine.connect() as connection:
        for table in _REPORT_TABLES:
            dumped = connection.execute(
                text(f"SELECT coalesce(string_agg(t::text, ''), '') FROM {table} t")  # noqa: S608
            ).scalar_one()
            for raw in (token, utoken, token3):
                assert raw[len("grxtk_") :] not in dumped, table


def test_cross_client_and_foreign_consumption_is_the_one_not_found(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    rig = Rig(migrated_engine, tmp_path)
    owner = operator()
    stranger = operator()
    sid, token = _finalized(rig, owner, _text(5000, seed=33), key="mine")
    head = _ok(
        _publish(rig, owner, {"format": "text", "body": "synthetic head"}, key="h", client=None)
    )
    before = _plane(rig)
    rendered = []
    callers: list[tuple[Principal, str | None]] = [
        (owner, CLIENT_B),
        (owner, None),
        (stranger, CLIENT_A),
    ]
    for principal, client in callers:
        rendered.append(
            _error(_publish(rig, principal, _reference(sid, token), key="x", client=client))
        )
    rendered.append(
        _error(
            _update(
                rig,
                owner,
                head["report_id"],
                {"content": _reference(sid, token)},
                key="y",
                expected_version=1,
                client=CLIENT_B,
            )
        )
    )
    rendered.append(
        _error(_publish(rig, owner, _reference(sid, "grxtk_" + "e" * 64), key="z", client=CLIENT_A))
    )
    assert all(error == rendered[0] for error in rendered), rendered
    assert rendered[0]["code"] == "not_found" and rendered[0]["safe_details"] == []
    assert _plane(rig) == before
    assert _session(migrated_engine, sid)["state"] == "finalized"


def _transactions(engine: Engine) -> Any:  # noqa: ANN401
    audit = SqlAlchemyAuditSink(engine)
    return lambda: SqlAlchemyUnitOfWork(engine, audit=audit)


def test_the_gc_expires_discards_finds_orphans_and_skips_locked(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    rig = Rig(migrated_engine, tmp_path)
    owner = operator()
    held = _begin(rig, owner, _text(100, seed=34), key="held")
    _ok(_append(rig, owner, held, 0, _text(100, seed=34)))
    free = _begin(rig, owner, _text(120, seed=35), key="free")
    _ok(_append(rig, owner, free, 0, _text(120, seed=35)))
    orphan = "grxfr_" + "9" * 32
    data = b"synthetic orphan"
    rig.staging.put_chunk(orphan, 0, chunk_sha256=_sha(data), data=data)
    with migrated_engine.connect() as locker:
        transaction = locker.begin()
        locker.execute(
            text(
                "SELECT 1 FROM knowledge.report_transfer_sessions WHERE session_id = :id FOR UPDATE"
            ),
            {"id": held},
        )
        first = collect_report_transfers(_transactions(migrated_engine), rig.staging, now=LATER)
        transaction.rollback()
    print("DB_TRANSFER_GC_SUMMARY", json.dumps(first.summary(), sort_keys=True))
    assert (first.expired, first.discarded, first.orphans_found) == (1, 1, 1)
    assert _session(migrated_engine, free)["state"] == "expired"
    assert _session(migrated_engine, held)["state"] == "open"
    assert rig.staging.has_session(held) and not rig.staging.has_session(free)
    second = collect_report_transfers(
        _transactions(migrated_engine), rig.staging, now=LATER, discard_orphans=True
    )
    assert (second.expired, second.discarded, second.orphans_discarded) == (1, 1, 1)
    assert second.clean
    third = collect_report_transfers(_transactions(migrated_engine), rig.staging, now=LATER)
    assert third.summary()["expired"] == 0 and third.clean
    assert rig.staging.staged_session_ids() == ()


class _Later(datetime):
    """The CLI's clock, pinned two hours after the rig's request clock."""

    @classmethod
    def now(cls, tz: Any = None) -> _Later:  # noqa: ANN401
        return cls.fromtimestamp(LATER.timestamp(), tz=tz)


def test_the_transfer_gc_command_exit_codes(
    migrated_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = Rig(migrated_engine, tmp_path)
    owner = operator()
    for index in range(2):
        session_id = _begin(rig, owner, _text(80 + index, seed=36), key=f"due-{index}")
        _ok(_append(rig, owner, session_id, 0, _text(80 + index, seed=36)))
    orphan = "grxfr_" + "8" * 32
    rig.staging.put_chunk(orphan, 0, chunk_sha256=_sha(b"o"), data=b"o")
    monkeypatch.setattr(report_content_cli, "datetime", _Later)
    monkeypatch.delenv("MY_PA_REPORT_CONTENT_ROOT", raising=False)
    assert report_content_cli.main(["transfer-gc"]) == report_content_cli.EXIT_REFUSED
    capsys.readouterr()
    monkeypatch.setenv("MY_PA_REPORT_CONTENT_ROOT", str(rig.root))
    assert (
        report_content_cli.main(["transfer-gc", "--limit", "0"]) == report_content_cli.EXIT_REFUSED
    )
    capsys.readouterr()

    def run(*arguments: str) -> tuple[int, dict[str, Any]]:
        code = report_content_cli.main(["transfer-gc", *arguments])
        out = capsys.readouterr().out
        assert "grxfr_" not in out and str(tmp_path) not in out
        return code, json.loads(out.strip().splitlines()[-1])

    code, bounded = run("--limit", "1")
    print("CLI_TRANSFER_GC", code, bounded)
    assert code == report_content_cli.EXIT_MORE_REMAINING == 3
    assert bounded["expired"] == 1 and bounded["more_remaining"] is True
    code, orphans = run()
    assert code == 3 and orphans["orphans_remaining"] == 1 and orphans["expired"] == 1
    code, clean = run("--discard-orphans")
    print("CLI_TRANSFER_GC", code, clean)
    assert code == report_content_cli.EXIT_OK and clean["orphans_discarded"] == 1
    assert run()[0] == report_content_cli.EXIT_OK


@pytest.mark.slow
def test_a_16_mib_identity_text_transfer_through_the_service_on_postgres(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    rig = Rig(migrated_engine, tmp_path)
    owner = operator()
    rng = random.Random(16)  # noqa: S311 - deterministic synthetic text, not a secret
    staged = bytes(rng.choices(bytes(range(0x21, 0x7F)) + b" \n", k=16 * MIB))
    peaks: dict[str, int] = {}
    timings: dict[str, float] = {}

    def measured(name: str, call: Any) -> dict[str, Any]:  # noqa: ANN401
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        answer = call()
        peaks[name] = max(peaks.get(name, 0), tracemalloc.get_traced_memory()[1] - base)
        return _ok(answer)

    session_id = _begin(rig, owner, staged, key="big", client=CLIENT_A)
    tracemalloc.start()
    try:
        started = time.perf_counter()
        for sequence, offset in enumerate(range(0, len(staged), CHUNK)):
            piece = staged[offset : offset + CHUNK]
            measured(
                "append",
                lambda s=sequence, p=piece: _append(rig, owner, session_id, s, p, client=CLIENT_A),
            )
        timings["upload"] = time.perf_counter() - started
        started = time.perf_counter()
        token = measured(
            "finalize",
            lambda: _op(
                rig, owner, Capability.REPORTS_TRANSFER_FINALIZE, session_id, client=CLIENT_A
            ),
        )["content_token"]
        timings["finalize"] = time.perf_counter() - started
        started = time.perf_counter()
        report = measured(
            "publish",
            lambda: _publish(rig, owner, _reference(session_id, token), key="pub", client=CLIENT_A),
        )
        timings["publish"] = time.perf_counter() - started
        started = time.perf_counter()
        digest = hashlib.sha256()
        total, calls = 0, 0
        offset_: int | None = 0
        while offset_ is not None:
            answer = measured(
                "read_chunk",
                lambda o=offset_: rig.invoke(
                    owner,
                    Capability.REPORTS_TRANSFER_READ_CHUNK,
                    {"report_id": report["report_id"], "version_number": 1, "offset": o},
                ),
            )
            chunk = base64.b64decode(answer["chunk"])
            assert chunk == staged[total : total + len(chunk)]
            digest.update(chunk)
            total += len(chunk)
            calls += 1
            offset_ = answer["next_offset"]
        timings["read_back"] = time.perf_counter() - started
    finally:
        tracemalloc.stop()
    assert total == len(staged) and calls == 64 and digest.hexdigest() == _sha(staged)
    assert _session(migrated_engine, session_id)["state"] == "consumed"
    print(
        "DB_TRANSFER_MEASURE 16MiB "
        + " ".join(f"peak_{k}={v / MIB:.2f}MiB" for k, v in sorted(peaks.items()))
        + " "
        + " ".join(f"{k}={v:.2f}s" for k, v in timings.items())
    )
    # These peaks include the transport normalization `Rig.invoke` performs.
    assert peaks["append"] < 32 * MIB and peaks["read_chunk"] < 32 * MIB, peaks
    assert peaks["finalize"] < 160 * MIB and peaks["publish"] < 160 * MIB, peaks
