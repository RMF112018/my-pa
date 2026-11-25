"""WP3P-S4: `bindings check` and `bindings apply` end to end on PostgreSQL (PULSE-AC-10, AC-12).

The `database` tier, on a disposable head-migrated clone. The command is run
through `apps.cli.project_reports.main` exactly as an operator runs it: the
database from `MY_PA_DATABASE_URL`, the expectations asserted, the workspace
composed from `MY_PA_FILES_WORKSPACES` over a temporary directory whose
folders and files are read-only (mode 0555/0444). Proved here:

* `check` prints the diff and the unbound CSV folder count with its stated
  depth, and writes nothing;
* `apply` admits, binds and enables in one transaction (ruling D7): the
  sources (`admitted_by = operator_cli`), the first revisions (`recorded_by =
  operator_cli`, the file's SHA-256, reason `initial`), the pointers and the
  filter declarations; no `audit_events` row (D6); re-applying writes nothing;
* a correction writes a superseding revision and moves the pointer; a filter
  change writes a `filter_update` revision carrying the new declaration
  (PULSE-AC-10); a retire writes a `retired` revision, marks the pointer
  retired, disables the source and keeps every row; binding the folder again
  re-enables it;
* atomicity: a write the database refuses part-way leaves no row at all;
* every refusal (rules 1 to 5, `folder_not_found`, `folder_nested`, a
  duplicate key, an unknown key, a Project swap) writes nothing;
* `lock_held` while another session holds the project-reports poll lock (and
  the communications lock does not block it);
* the generic `communications_ingest.py admit --consumer pulse_csv_export`
  refuses `consumer_not_registered` and admits nothing;
* `IngestionLifecycle.admit_within` commits or rolls back with its caller's
  unit of work.

Every identifier, folder, number and text here is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import communications_ingest as comms_cli
from apps.cli import project_reports as cli
from sqlalchemy import Engine, insert, text
from sqlalchemy.engine import Row, make_url

from my_pa.application.ingestion import IngestionLifecycle
from my_pa.application.project_reports_ingest import AdmissionOnlyHandler
from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.project_reports import project_reports_unit_of_work
from my_pa.contracts.ports import IngestConsumer, UnitOfWork
from my_pa.infrastructure.jobs.cycle_scheduler import (
    COMMS_INGEST_LOCK_KEY,
    PROJECT_REPORTS_POLL_LOCK_KEY,
)
from my_pa.infrastructure.persistence.tables import projects

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
EXPORT_ROOT: Final = "Synthetic Area"
FOLDER_A: Final = f"{EXPORT_ROOT}/Alpha Synth/REPORTS/EXPORTS"
FOLDER_B: Final = f"{EXPORT_ROOT}/Bravo Synth/REPORTS/EXPORTS"
FOLDER_C: Final = f"{EXPORT_ROOT}/Charlie Synth/REPORTS/EXPORTS"
#: Holds CSV files and is bound by no file below.
FOLDER_UNBOUND: Final = f"{EXPORT_ROOT}/Delta Synth/REPORTS/EXPORTS"
#: Holds CSV files four levels below the root: past the stated depth, never counted.
FOLDER_TOO_DEEP: Final = f"{EXPORT_ROOT}/Echo Synth/REPORTS/EXPORTS/OLDER"
#: A directory with no CSV file: not a CSV folder.
FOLDER_EMPTY: Final = f"{EXPORT_ROOT}/Foxtrot Synth/REPORTS"
PROJECTS: Final = {
    "prj_synbindalpha1": "SYN-8101",
    "prj_synbindbravo1": "SYN-8102",
    "prj_synbindcharl1": "SYN-8103",
}
PROJECT_NO_NUMBER: Final = "prj_synbindnonum1"
PA, PB, PC = PROJECTS
SLUG: Final = "synthetic-saved-report"
FILTER: Final = "Synthetic filter: open items only"
FILE_NAME: Final = "20261120-synthetic-saved-report.csv"
TABLES: Final = (
    "ingest_sources",
    "project_report_binding_revisions",
    "project_report_filter_declarations",
    "project_report_bindings",
    "audit_events",
)


def _lock(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o444 if path.is_file() else 0o555)
    root.chmod(0o555)


def _unlock(root: Path) -> None:
    root.chmod(0o755)
    for path in root.rglob("*"):
        path.chmod(0o644 if path.is_file() else 0o755)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "workspace"
    for folder in (FOLDER_A, FOLDER_B, FOLDER_C, FOLDER_UNBOUND, FOLDER_TOO_DEEP):
        (root / folder).mkdir(parents=True)
        (root / folder / FILE_NAME).write_bytes(b"Synthetic,Header\n")
    (root / FOLDER_EMPTY).mkdir(parents=True)
    (root / FOLDER_EMPTY / "notes.txt").write_bytes(b"synthetic")
    _lock(root)
    monkeypatch.setenv("MY_PA_FILES_WORKSPACES", f"mcp={root};mode=direct")
    monkeypatch.delenv("MY_PA_FILES_WORKSPACE_ROOT", raising=False)
    try:
        yield root
    finally:
        _unlock(root)


class Operator:
    def __init__(self, engine: Engine, capsys: pytest.CaptureFixture[str], files: Path) -> None:
        self.engine = engine
        self.capsys = capsys
        self.files = files
        self.principal = local_principal().principal_id
        database = make_url(os.environ["MY_PA_DATABASE_URL"]).database
        with engine.connect() as connection:
            head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.expect = ["--expected-database", str(database), "--expected-alembic-head", str(head)]
        self.outputs: list[str] = []
        with engine.begin() as connection:
            for project_id, number in (*PROJECTS.items(), (PROJECT_NO_NUMBER, None)):
                connection.execute(
                    insert(projects).values(
                        project_id=project_id,
                        principal_id=self.principal,
                        name="Synthetic project",
                        opened_at=WHEN,
                        created_at=WHEN,
                        updated_at=WHEN,
                        project_number=number,
                    )
                )

    def file(self, document: object, name: str = "bindings.json") -> str:
        path = self.files / name
        path.write_text(document if isinstance(document, str) else json.dumps(document))
        return str(path)

    def __call__(self, *argv: str) -> tuple[int, dict[str, Any]]:
        code = cli.main([*self.expect, *argv])
        captured = self.capsys.readouterr()
        assert captured.err == ""
        lines = captured.out.splitlines()
        assert len(lines) == 1, captured.out
        self.outputs.append(captured.out)
        return code, json.loads(lines[0])

    def check(self, path: str) -> tuple[int, dict[str, Any]]:
        return self("bindings", "check", "--file", path)

    def apply(self, path: str, reason: str = "initial") -> tuple[int, dict[str, Any]]:
        return self("bindings", "apply", "--file", path, "--reason", reason)

    def counts(self) -> dict[str, int]:
        with self.engine.connect() as connection:
            return {
                table: int(
                    connection.execute(
                        text(f"SELECT count(*) FROM knowledge.{table}")  # noqa: S608 - constants
                    ).scalar_one()
                )
                for table in TABLES
            }

    def rows(self, sql: str, **params: object) -> list[Row[Any]]:
        with self.engine.connect() as connection:
            return list(connection.execute(text(sql), params))

    def source_of(self, folder: str) -> Row[Any]:
        found = self.rows(
            "SELECT ingest_source_id, enabled, consumer, file_pattern, admitted_by "
            "FROM knowledge.ingest_sources WHERE path_prefix = :prefix",
            prefix=folder + "/",
        )
        assert len(found) == 1
        return found[0]

    def pointer_of(self, folder: str) -> Row[Any]:
        source = self.source_of(folder).ingest_source_id
        found = self.rows(
            "SELECT b.binding_revision_id, b.project_id, b.state, r.reason_code, "
            "r.supersedes_revision_id, r.currency, r.change_set_sha256, r.recorded_by "
            "FROM knowledge.project_report_bindings b JOIN "
            "knowledge.project_report_binding_revisions r USING (binding_revision_id) "
            "WHERE b.ingest_source_id = :source",
            source=source,
        )
        assert len(found) == 1
        return found[0]


@pytest.fixture
def operator(
    migrated_engine: Engine,
    workspace: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> Operator:
    files = tmp_path / "operator"
    files.mkdir()
    return Operator(migrated_engine, capsys, files)


def _document(*bindings: dict[str, object], export_root: str = EXPORT_ROOT) -> dict[str, object]:
    return {
        "schema": "my_pa_project_report_bindings_v1",
        "workspace_id": "mcp",
        "export_root": export_root,
        "bindings": list(bindings),
    }


def _entry(folder: str, project_id: str, **extra: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "folder": folder,
        "project_id": project_id,
        "project_number": PROJECTS[project_id],
    }
    return {**entry, **extra}


def _a(**extra: object) -> dict[str, object]:
    return {**_entry(FOLDER_A, PA, reports=[{"slug": SLUG, "filter": FILTER}]), **extra}


def _b(**extra: object) -> dict[str, object]:
    return {**_entry(FOLDER_B, PB), **extra}


# ---- check ---------------------------------------------------------------------------


def test_check_prints_the_diff_and_the_unbound_folders_and_writes_nothing(
    operator: Operator,
) -> None:
    before = operator.counts()
    code, out = operator.check(operator.file(_document(_a(), _b())))
    assert code == cli.EXIT_OK, out
    assert out["applied"] is False
    assert out["counts"] == {
        "add": 2,
        "correction": 0,
        "filter_update": 0,
        "retire": 0,
        "unchanged": 0,
        "filter_declarations": 1,
    }
    assert out["project_numbers"]["add"] == sorted([PROJECTS[PA], PROJECTS[PB]])
    # Charlie and Delta hold CSV files and no binding; Echo is past the depth;
    # Foxtrot holds no CSV file.
    assert (out["unbound_folders"], out["unbound_folder_depth"]) == (2, 3)
    assert out["unbound_listing_truncated"] is False
    assert operator.counts() == before


# ---- apply -----------------------------------------------------------------------


def test_apply_admits_binds_and_enables_in_one_transaction_then_is_idempotent(
    operator: Operator,
) -> None:
    path = operator.file(_document(_a(), _b()))
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    code, out = operator.apply(path)
    assert code == cli.EXIT_OK, out
    assert out["writes"] == {
        "revisions": 2,
        "filter_declarations": 1,
        "sources_admitted": 2,
        "sources_enabled": 0,
        "sources_disabled": 0,
    }
    assert operator.counts() == {
        "ingest_sources": 2,
        "project_report_binding_revisions": 2,
        "project_report_filter_declarations": 1,
        "project_report_bindings": 2,
        "audit_events": 0,
    }
    for folder, project_id in ((FOLDER_A, PA), (FOLDER_B, PB)):
        source = operator.source_of(folder)
        assert (source.enabled, source.consumer, source.file_pattern, source.admitted_by) == (
            True,
            IngestConsumer.PULSE_CSV_EXPORT.value,
            "*.csv",
            "operator_cli",
        )
        pointer = operator.pointer_of(folder)
        assert (pointer.project_id, pointer.state, pointer.reason_code) == (
            project_id,
            "active",
            "initial",
        )
        assert (pointer.supersedes_revision_id, pointer.currency) == (None, "USD")
        assert (pointer.change_set_sha256, pointer.recorded_by) == (digest, "operator_cli")
    declared = operator.rows(
        "SELECT slug_label, description, binding_revision_id "
        "FROM knowledge.project_report_filter_declarations"
    )
    assert [(row.slug_label, row.description) for row in declared] == [(SLUG, FILTER)]
    assert declared[0].binding_revision_id == operator.pointer_of(FOLDER_A).binding_revision_id

    # Applying the same file again writes nothing.
    before = operator.counts()
    code, again = operator.apply(path)
    assert (code, again["counts"]["unchanged"]) == (cli.EXIT_OK, 2)
    assert set(again["writes"].values()) == {0}
    assert operator.counts() == before


def test_a_correction_a_filter_update_a_retire_and_a_rebind(operator: Operator) -> None:
    assert operator.apply(operator.file(_document(_a(), _b()), "one.json"))[0] == cli.EXIT_OK
    first_a = operator.pointer_of(FOLDER_A)
    first_b = operator.pointer_of(FOLDER_B)
    source_b = operator.source_of(FOLDER_B).ingest_source_id
    # A lifecycle snapshot of B's source: a retire must keep it.
    with operator.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.ingest_snapshots (snapshot_id, principal_id, "
                "ingest_source_id, file_sha256, byte_count, status, first_seen_at) VALUES "
                "('isnp_synbindkeep1', :p, :s, :d, 10, 'pending', :t)"
            ),
            {"p": operator.principal, "s": source_b, "d": "f" * 64, "t": WHEN},
        )

    # The currency of A is corrected, and B's filter declared; nothing else.
    second = _document(
        _a(currency="CAD"), _b(reports=[{"slug": SLUG, "filter": FILTER + " (bravo)"}])
    )
    code, out = operator.apply(operator.file(second, "two.json"), "correction")
    assert code == cli.EXIT_OK, out
    assert out["project_numbers"]["correction"] == [PROJECTS[PA]]
    assert out["project_numbers"]["filter_update"] == [PROJECTS[PB]]
    a, b = operator.pointer_of(FOLDER_A), operator.pointer_of(FOLDER_B)
    assert (a.reason_code, a.currency, a.supersedes_revision_id) == (
        "correction",
        "CAD",
        first_a.binding_revision_id,
    )
    assert (b.reason_code, b.supersedes_revision_id) == (
        "filter_update",
        first_b.binding_revision_id,
    )
    # Each new active revision carries its folder's declarations (AC-10).
    for pointer, description in ((a, FILTER), (b, FILTER + " (bravo)")):
        assert [
            row.description
            for row in operator.rows(
                "SELECT description FROM knowledge.project_report_filter_declarations "
                "WHERE binding_revision_id = :r",
                r=pointer.binding_revision_id,
            )
        ] == [description]

    # B is omitted: retired, its source disabled, every row kept.
    before = operator.counts()
    code, out = operator.apply(operator.file(_document(_a(currency="CAD")), "three.json"), "retire")
    assert code == cli.EXIT_OK, out
    assert out["project_numbers"]["retire"] == [PROJECTS[PB]]
    assert out["writes"]["sources_disabled"] == 1
    retired = operator.pointer_of(FOLDER_B)
    assert (retired.state, retired.reason_code, retired.supersedes_revision_id) == (
        "retired",
        "retire",
        b.binding_revision_id,
    )
    assert retired.project_id == PB
    assert operator.source_of(FOLDER_B).enabled is False
    after = operator.counts()
    assert after["project_report_binding_revisions"] == (
        before["project_report_binding_revisions"] + 1
    )
    assert (
        after["project_report_filter_declarations"]
        == (before["project_report_filter_declarations"])
    )
    assert operator.rows(
        "SELECT snapshot_id FROM knowledge.ingest_snapshots WHERE ingest_source_id = :s",
        s=source_b,
    ) == [("isnp_synbindkeep1",)]

    # B bound again: the retired source is enabled, not admitted twice.
    code, out = operator.apply(
        operator.file(_document(_a(currency="CAD"), _b()), "four.json"), "add"
    )
    assert code == cli.EXIT_OK, out
    assert out["project_numbers"]["add"] == [PROJECTS[PB]]
    assert (out["writes"]["sources_admitted"], out["writes"]["sources_enabled"]) == (0, 1)
    rebound = operator.pointer_of(FOLDER_B)
    assert (rebound.state, rebound.reason_code, rebound.supersedes_revision_id) == (
        "active",
        "add",
        retired.binding_revision_id,
    )
    assert operator.source_of(FOLDER_B).enabled is True
    assert operator.counts()["ingest_sources"] == 2


def test_a_project_moved_between_folders_is_ordered_and_a_swap_is_refused(
    operator: Operator,
) -> None:
    assert operator.apply(operator.file(_document(_a(), _b()), "one.json"))[0] == cli.EXIT_OK
    # B moves to C's Project while A keeps its own: one correction.
    moved = _document(_a(), _entry(FOLDER_B, PC))
    code, out = operator.apply(operator.file(moved, "two.json"), "correction")
    assert (code, out["project_numbers"]["correction"]) == (cli.EXIT_OK, [PROJECTS[PC]])
    # A swap (A takes C from B while B takes A's Project) cannot be ordered.
    before = operator.counts()
    swap = _document(
        _entry(FOLDER_A, PC, reports=[{"slug": SLUG, "filter": FILTER}]), _entry(FOLDER_B, PA)
    )
    code, out = operator.apply(operator.file(swap, "three.json"), "correction")
    assert (code, out) == (
        cli.EXIT_REFUSED,
        {"command": "bindings_apply", "refused": "project_duplicated"},
    )
    assert operator.counts() == before
    # A chain is ordered: B releases C to A only after taking B's own Project.
    chain = _document(
        _entry(FOLDER_A, PC, reports=[{"slug": SLUG, "filter": FILTER}]), _entry(FOLDER_B, PB)
    )
    code, out = operator.apply(operator.file(chain, "four.json"), "correction")
    assert code == cli.EXIT_OK, out
    assert operator.pointer_of(FOLDER_A).project_id == PC
    assert operator.pointer_of(FOLDER_B).project_id == PB


def test_a_write_refused_part_way_leaves_no_row(operator: Operator) -> None:
    """Atomicity: the second binding's declaration is refused after the first was written."""
    with operator.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION public.s4_refuse_marked() RETURNS trigger LANGUAGE plpgsql AS "
                "$$BEGIN IF NEW.description = 'SYNTHETIC-REFUSE' THEN RAISE EXCEPTION "
                "'synthetic refusal' USING ERRCODE = '23514'; END IF; RETURN NEW; END$$"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER s4_refuse_marked BEFORE INSERT ON "
                "knowledge.project_report_filter_declarations FOR EACH ROW "
                "EXECUTE FUNCTION public.s4_refuse_marked()"
            )
        )
    before = operator.counts()
    document = _document(_a(), _b(reports=[{"slug": SLUG, "filter": "SYNTHETIC-REFUSE"}]))
    code, out = operator.apply(operator.file(document))
    assert (code, out) == (
        cli.EXIT_REFUSED,
        {"command": "bindings_apply", "refused": "write_refused"},
    )
    assert operator.counts() == before


# ---- every refusal writes nothing ---------------------------------------------------


REFUSED: Final = (
    (
        "rule_1_project_not_found",
        _document(_a(project_id="prj_synbindmissing1")),
        "project_not_found",
    ),
    (
        "rule_1_not_a_project_id",
        _document(_a(project_id="ent_synbindnotprj01")),
        "project_not_found",
    ),
    (
        "rule_2_number_mismatch",
        _document(_a(project_number="SYN-0000")),
        "project_number_mismatch",
    ),
    (
        "rule_2_no_number",
        _document(_a(project_id=PROJECT_NO_NUMBER)),
        "project_has_no_number",
    ),
    ("rule_3_folder_twice", _document(_a(), _entry(FOLDER_A, PB)), "folder_duplicated"),
    (
        "rule_3_same_normalized_path",
        _document(_a(), _entry(FOLDER_A.upper(), PB)),
        "folder_duplicated",
    ),
    ("rule_4_project_twice", _document(_a(), _entry(FOLDER_B, PA)), "project_duplicated"),
    (
        "rule_5_absolute",
        _document(_a(folder="/" + FOLDER_A)),
        "folder_outside_export_root",
    ),
    (
        "rule_5_dot_dot",
        _document(_a(folder=f"{EXPORT_ROOT}/../Elsewhere")),
        "folder_outside_export_root",
    ),
    (
        "rule_5_outside_export_root",
        _document(_a(folder="Elsewhere/Alpha Synth")),
        "folder_outside_export_root",
    ),
    (
        "folder_not_found",
        _document(_a(folder=f"{EXPORT_ROOT}/Missing Synth/REPORTS")),
        "folder_not_found",
    ),
    (
        "folder_is_a_file",
        _document(_a(folder=f"{FOLDER_A}/{FILE_NAME}")),
        "folder_not_found",
    ),
    ("folder_nested", _document(_a(), _entry(FOLDER_A + "/Inner", PB)), "folder_nested"),
    ("duplicate_key", '{"schema": "a", "schema": "b"}', "duplicate_json_key"),
    ("unknown_key", {**_document(_a()), "comment": "x"}, "unknown_key"),
)


@pytest.mark.parametrize(("name", "document", "code"), REFUSED, ids=[case[0] for case in REFUSED])
def test_every_refusal_writes_nothing(
    operator: Operator, name: str, document: object, code: str
) -> None:
    # A bound state first, so a refusal that wrote would show as a change.
    assert operator.apply(operator.file(_document(_a(), _b()), "base.json"))[0] == cli.EXIT_OK
    before = operator.counts()
    path = operator.file(document, f"{name}.json")
    for run in (operator.check, operator.apply):
        exit_code, out = run(path)
        assert exit_code == cli.EXIT_REFUSED, out
        assert out["refused"] == code
    assert operator.counts() == before


# ---- the lock ----------------------------------------------------------------------


def test_apply_refuses_lock_held_while_another_session_holds_the_poll_lock(
    operator: Operator,
) -> None:
    path = operator.file(_document(_a()))
    before = operator.counts()
    with operator.engine.connect() as holder:
        assert holder.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": PROJECT_REPORTS_POLL_LOCK_KEY}
        ).scalar_one()
        holder.commit()
        try:
            assert operator.apply(path) == (
                cli.EXIT_REFUSED,
                {"command": "bindings_apply", "refused": "lock_held"},
            )
            assert operator.counts() == before
            assert operator.check(path)[0] == cli.EXIT_OK  # check takes no lock
        finally:
            holder.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": PROJECT_REPORTS_POLL_LOCK_KEY}
            )
            holder.commit()
    # The communications poll lock is another key: it does not block an apply.
    with operator.engine.connect() as holder:
        assert holder.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": COMMS_INGEST_LOCK_KEY}
        ).scalar_one()
        holder.commit()
        try:
            assert operator.apply(path)[0] == cli.EXIT_OK
        finally:
            holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": COMMS_INGEST_LOCK_KEY})
            holder.commit()
    # Released after the apply: a session can take it at once.
    with operator.engine.connect() as probe:
        assert probe.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": PROJECT_REPORTS_POLL_LOCK_KEY}
        ).scalar_one()
        probe.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": PROJECT_REPORTS_POLL_LOCK_KEY}
        )
        probe.commit()


# ---- the generic admit, admit_within, and counts-only output ------------------------


def test_the_generic_admit_refuses_the_project_report_consumer(
    operator: Operator, capsys: pytest.CaptureFixture[str]
) -> None:
    code = comms_cli.main(
        [
            *operator.expect,
            "admit",
            "--consumer",
            IngestConsumer.PULSE_CSV_EXPORT.value,
            "--workspace",
            "mcp",
            "--path-prefix",
            FOLDER_A + "/",
            "--file-pattern",
            "*.csv",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert (code, out) == (
        comms_cli.EXIT_REFUSED,
        {"command": "admit", "refused": "consumer_not_registered"},
    )
    assert operator.counts()["ingest_sources"] == 0


class _AbortError(Exception):
    pass


def test_admit_within_commits_or_rolls_back_with_its_callers_unit(operator: Operator) -> None:
    unit_of_work = project_reports_unit_of_work(operator.engine)
    lifecycle = IngestionLifecycle(
        unit_of_work=unit_of_work,
        stores=lambda _w: None,
        handlers=[AdmissionOnlyHandler()],  # type: ignore[arg-type,return-value]
    )

    def admit(unit: UnitOfWork, folder: str) -> None:
        lifecycle.admit_within(
            unit,
            operator.principal,
            consumer=IngestConsumer.PULSE_CSV_EXPORT,
            workspace_id="mcp",
            path_prefix=folder + "/",
            file_pattern="*.csv",
        )

    with pytest.raises(_AbortError), unit_of_work() as unit:
        admit(unit, FOLDER_A)
        raise _AbortError
    assert operator.counts()["ingest_sources"] == 0
    with unit_of_work() as unit:
        admit(unit, FOLDER_A)
    assert operator.counts()["ingest_sources"] == 1


def test_no_output_carries_a_folder_a_path_a_file_name_or_a_filter(
    operator: Operator, workspace: Path
) -> None:
    operator.check(operator.file(_document(_a(), _b()), "one.json"))
    operator.apply(operator.file(_document(_a(), _b()), "one.json"))
    operator.apply(operator.file(_document(_a(currency="CAD")), "two.json"), "retire")
    operator.check(operator.file(_document(_a(folder=f"{EXPORT_ROOT}/Missing")), "three.json"))
    url = make_url(os.environ["MY_PA_DATABASE_URL"])
    forbidden = (
        EXPORT_ROOT,
        "Synth",
        "REPORTS",
        "EXPORTS",
        SLUG,
        FILTER,
        FILE_NAME,
        ".csv",
        ".json",
        str(workspace),
        str(operator.files),
        str(url.host),
        *PROJECTS,
    )
    assert len(operator.outputs) == 4
    for output in operator.outputs:
        leaked = [value for value in forbidden if value in output]
        assert not leaked, leaked
