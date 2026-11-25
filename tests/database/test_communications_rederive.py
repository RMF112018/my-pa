"""WP4-S3: `communications_ingest.py rederive` end to end on PostgreSQL (rulings D2, D3, R4, R9).

The `database` tier, on a disposable head-migrated clone, through
`apps.cli.communications_ingest.main` exactly as an operator runs it, over a
read-only workspace directory composed from `MY_PA_FILES_WORKSPACES`. The
synthetic publications are first ingested by the real command with the search
text and identifiers pinned to v1 (the state a WP3a database holds); the
rederive then brings them to v2. Proved here: text, `search_document` and
identifier rows are rebuilt and the v1 rows stay (no prune, R4); a rerun is
idempotent; a changed file flags `source_unavailable` and keeps the stored
text while the identifiers become current (R9), and restoring the file clears
the flag; the command refuses `lock_held` while another session holds the
poll lock; a dry run writes nothing; output is counts only. Synthetic only.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import communications_ingest as cli
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application import communications_ingest as ingest_module
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION_V1
from my_pa.domain.communications.search_text import derive_search_text_v1
from my_pa.infrastructure.jobs.cycle_scheduler import COMMS_INGEST_LOCK_KEY
from tests.database.test_communications_ingest_cli import COMMS_TABLES, Operator, _lock, _unlock
from tests.fixtures.communications_evidence import synthetic as s

pytestmark = pytest.mark.database

FOLDER: Final = "My PA/Daily Intelligence/communications"
#: A mid-body "Disclaimer" line above the trailing region: v1 cuts there, v2 keeps it.
MID_BODY: Final = (
    "<p>Hi team,</p>"
    "<p>Disclaimer language for the contract is attached; please review RFI 12 and PCO 7.</p>"
    + "".join(f"<p>Schedule note {i} for the synthetic site.</p>" for i in range(16))
    + "<p>Thanks, Alpha</p>"
)
PLAIN: Final = "<p>Please see Change Order 5 for the slab.</p>"


def _window(day: int) -> dict[str, Any]:
    return s.window(
        f"2026-11-{day:02d}T05:00:00Z",
        f"2026-11-{day + 1:02d}T04:59:59Z",
        24,
        "weekday_prior_24h",
    )


def _message(n: int, day: int, content: str) -> dict[str, Any]:
    return s.message(
        n, selected=f"2026-11-{day:02d}T12:00:00Z", subject=f"Synthetic {n}", content=content
    )


FILES: Final = {
    "20261117-comms.json": s.encode(s.publication([_message(1, 17, MID_BODY)], _window(17))),
    "20261118-comms.json": s.encode(
        s.publication([_message(2, 18, PLAIN), _message(3, 18, MID_BODY)], _window(18))
    ),
}


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "workspace"
    (root / FOLDER).mkdir(parents=True)
    for name, data in FILES.items():
        (root / FOLDER / name).write_bytes(data)
    _lock(root)
    monkeypatch.setenv("MY_PA_FILES_WORKSPACES", f"mcp={root};mode=direct")
    monkeypatch.delenv("MY_PA_FILES_WORKSPACE_ROOT", raising=False)
    try:
        yield root
    finally:
        _unlock(root)


def _seed_v1(operator: Operator) -> str:
    code, out, _ = operator(
        "admit",
        "--consumer",
        "communications_evidence_v2",
        "--workspace",
        "mcp",
        "--path-prefix",
        FOLDER + "/",
        "--file-pattern",
        "*-comms.json",
    )
    assert code == cli.EXIT_OK, out
    source = str(out["ingest_source_id"])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ingest_module, "derive_search_text", derive_search_text_v1)
        patch.setattr(ingest_module, "IDENTIFIER_VERSION", IDENTIFIER_VERSION_V1)
        code, report, _ = operator("backfill", "--source", source)
    assert (code, report["counts"]["snapshots_ingested"]) == (cli.EXIT_OK, 2), report
    return source


def _rows(engine: Engine, sql: str, **params: object) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql), params)]


def _messages(engine: Engine) -> dict[str, tuple[Any, ...]]:
    return {
        row[0]: row[1:]
        for row in _rows(
            engine,
            "SELECT subject, search_text_version, identifiers_version, source_unavailable,"
            " search_text, search_document @@ to_tsquery('english', 'pco')"
            " FROM knowledge.communication_messages",
        )
    }


def _identifiers(engine: Engine, subject: str) -> set[tuple[str, str]]:
    return {
        (str(version), f"{kind}:{value}")
        for version, kind, value in _rows(
            engine,
            "SELECT i.extractor_version, i.kind, i.value FROM knowledge.communication_identifiers i"
            " JOIN knowledge.communication_messages m USING (principal_id, message_id)"
            " WHERE m.subject = :subject",
            subject=subject,
        )
    }


def test_rederive_rebuilds_text_document_and_identifiers_and_is_idempotent(
    migrated_engine: Engine, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    operator = Operator(migrated_engine, capsys)
    source = _seed_v1(operator)
    before = _messages(migrated_engine)
    assert {row[0] for row in before.values()} == {"comms_search_text_v1"}
    assert {row[1] for row in before.values()} == {"comms_identifiers_v1"}
    assert before["Synthetic 1"][3] == "Hi team,"
    assert before["Synthetic 1"][4] is False  # "PCO 7" is not in the v1 text
    assert _identifiers(migrated_engine, "Synthetic 1") == set()
    v1_plain = _identifiers(migrated_engine, "Synthetic 2")

    # Dry run: the due set, and nothing written.
    counts_before = operator.counts()
    code, dry, raw_dry = operator("rederive", "--dry-run")
    assert (code, dry["dry_run"], dry["counts"]["messages_due_text"]) == (cli.EXIT_OK, True, 3)
    # Scoped by the text pointer's snapshot source (SQL `list_rederive_due`).
    code, scoped, _ = operator("rederive", "--dry-run", "--source", source, "--limit", "2")
    assert (scoped["counts"]["messages_checked"], scoped["counts"]["messages_deferred"]) == (2, 1)
    assert operator.counts() == counts_before
    assert _messages(migrated_engine) == before

    code, out, raw = operator("rederive")
    assert code == cli.EXIT_OK, out
    counts = out["counts"]
    assert (counts["messages_rederived"], counts["messages_text_changed"]) == (3, 2)
    assert (counts["snapshots_read"], counts["snapshots_unavailable"]) == (2, 0)
    after = _messages(migrated_engine)
    assert {row[:3] for row in after.values()} == {
        ("comms_search_text_v2", "comms_identifiers_v2", False)
    }
    assert str(after["Synthetic 1"][3]).startswith("Hi team,")
    assert after["Synthetic 1"][4] is True  # the server regenerated `search_document`
    assert _identifiers(migrated_engine, "Synthetic 1") == {
        ("comms_identifiers_v2", "rfi:12"),
        ("comms_identifiers_v2", "pco:7"),
    }
    # R4: the v1 rows stay beside the v2 rows.
    assert v1_plain <= _identifiers(migrated_engine, "Synthetic 2")
    assert ("comms_identifiers_v2", "co:5") in _identifiers(migrated_engine, "Synthetic 2")
    assert operator.scalar("SELECT count(*) FROM knowledge.audit_events") == 0

    rows = operator.counts()
    code, again, raw_again = operator("rederive")
    assert (code, again["counts"]["messages_checked"]) == (cli.EXIT_OK, 0)
    assert {t: operator.counts()[t] for t in COMMS_TABLES} == {t: rows[t] for t in COMMS_TABLES}

    url = make_url(os.environ["MY_PA_DATABASE_URL"])
    for output in (raw_dry, raw, raw_again):
        assert "Synthetic" not in output
        assert "RFI" not in output
        assert "Daily Intelligence" not in output
        assert ".json" not in output
        assert str(url.host) not in output
        assert str(workspace) not in output


def test_a_changed_file_flags_source_unavailable_and_a_restored_one_clears_it(
    migrated_engine: Engine, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    operator = Operator(migrated_engine, capsys)
    _seed_v1(operator)
    path = workspace / FOLDER / "20261117-comms.json"
    stored = _messages(migrated_engine)["Synthetic 1"]
    _unlock(workspace)
    path.write_bytes(FILES["20261117-comms.json"].replace(b"Hi team,", b"Hi crew,"))
    _lock(workspace)
    code, out, _ = operator("rederive")
    assert code == cli.EXIT_OK, out
    assert out["counts"]["snapshots_unavailable"] == 1
    assert out["counts"]["messages_source_unavailable"] == 1
    flagged = _messages(migrated_engine)["Synthetic 1"]
    # The stored projection is kept; the identifier marker is current (R9).
    assert flagged[0] == stored[0] == "comms_search_text_v1"
    assert flagged[3] == stored[3]
    assert (flagged[1], flagged[2]) == ("comms_identifiers_v2", True)

    _unlock(workspace)
    path.write_bytes(FILES["20261117-comms.json"])
    _lock(workspace)
    code, out, _ = operator("rederive")
    assert (code, out["counts"]["messages_source_restored"]) == (cli.EXIT_OK, 1)
    restored = _messages(migrated_engine)["Synthetic 1"]
    assert restored[:3] == ("comms_search_text_v2", "comms_identifiers_v2", False)


def test_rederive_refuses_lock_held_while_another_session_holds_the_poll_lock(
    migrated_engine: Engine, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    operator = Operator(migrated_engine, capsys)
    _seed_v1(operator)
    before = operator.counts()
    seeded = _messages(migrated_engine)
    with migrated_engine.connect() as holder:
        assert holder.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": COMMS_INGEST_LOCK_KEY}
        ).scalar_one()
        holder.commit()
        try:
            code, out, _ = operator("rederive")
            assert (code, out) == (
                cli.EXIT_REFUSED,
                {"command": "rederive", "refused": "lock_held"},
            )
            code, dry, _ = operator("rederive", "--dry-run")  # takes no lock
            assert (code, dry["dry_run"]) == (cli.EXIT_OK, True)
            assert operator.counts() == before
            assert _messages(migrated_engine) == seeded
        finally:
            holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": COMMS_INGEST_LOCK_KEY})
            holder.commit()
    code, out, _ = operator("rederive")
    assert (code, out["counts"]["messages_rederived"]) == (cli.EXIT_OK, 3)
    assert json.dumps(out).count("Synthetic") == 0
