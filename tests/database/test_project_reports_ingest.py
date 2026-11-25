"""WP3P-S5: ingestion, re-derivation and the stored aggregate on PostgreSQL.

PULSE-AC-02, 04, 06, 13 and 17 at the database tier.

The `database` tier, on a disposable head-migrated clone, through
`apps.cli.project_reports.main` exactly as an operator runs it: the database
from `MY_PA_DATABASE_URL`, the expectations asserted, the workspace composed
from `MY_PA_FILES_WORKSPACES` over a temporary, read-only directory holding
every synthetic fixture directory as its own folder (distinctive synthetic
folder and file names), the folders bound by `bindings apply`. Proved here:

* every fixture ingests through the lifecycle (rejected, classified or
  quarantined), and the stored aggregate equals the file-level aggregate of
  the same files key for key (AC-17 at the DB level);
* stored role counts sum to the snapshot's data rows and equal its stored row
  roles; each stated total's `computed_value` is the sum of exactly the detail
  lines in its scope (detail-only sums);
* the same bytes twice write once; byte-identical files in two sources are two
  snapshots;
* a quarantined derivation keeps every Layer A row and writes no role, line or
  total, and counts its rows `unclassified`;
* an unknown-signature snapshot is re-derived once a test adapter is
  registered (the registry is injected); a rebind re-derives (a wrong number
  quarantines the financial views, the right one classifies them again);
* `--dry-run` (backfill and rederive) writes nothing; a backfill resumes;
* a retired source's backfill fails `source_unbound` and writes nothing;
* the cross-report check is written once, left the buyout summary, in both
  arrival orders.

Every identifier, folder, number and text here is synthetic.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import project_reports as cli
from sqlalchemy import Engine, insert, text
from sqlalchemy.engine import Row, make_url

from my_pa.application.project_reports_rederive import ProjectReportsRederiver
from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.project_reports import (
    PulseExportReader,
    project_reports_unit_of_work,
)
from my_pa.domain.project_reports.model import FamilyView, ValueKind
from my_pa.infrastructure.persistence.tables import projects
from my_pa.infrastructure.project_reports import pulse_csv
from my_pa.infrastructure.project_reports.aggregate_cli import summarize_paths
from tests.unit.project_reports_scene import (
    DIRECTORIES,
    EXPORT_ROOT,
    FIXTURES,
    fixture_files,
    folder_of,
    name_of,
    project_number_of,
    project_of,
)

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
REPORT_TABLES: Final = (
    "ingest_snapshots",
    "ingest_snapshot_paths",
    "ingest_runs",
    "project_report_snapshots",
    "project_report_rows",
    "project_report_derivations",
    "project_report_row_roles",
    "project_report_lines",
    "project_report_line_values",
    "project_report_stated_totals",
    "project_report_records",
    "project_report_cross_checks",
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
    for directory in DIRECTORIES:
        folder = root / folder_of(directory)
        folder.mkdir(parents=True)
        for index, path in enumerate(fixture_files(directory)):
            shutil.copyfile(path, folder / name_of(index))
    _lock(root)
    monkeypatch.setenv("MY_PA_FILES_WORKSPACES", f"mcp={root};mode=direct")
    monkeypatch.delenv("MY_PA_FILES_WORKSPACE_ROOT", raising=False)
    try:
        yield root
    finally:
        _unlock(root)


class Operator:
    def __init__(
        self, engine: Engine, capsys: pytest.CaptureFixture[str], files: Path, root: Path
    ) -> None:
        self.engine = engine
        self.capsys = capsys
        self.files = files
        self.root = root
        self.principal = local_principal().principal_id
        database = make_url(os.environ["MY_PA_DATABASE_URL"]).database
        with engine.connect() as connection:
            head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.expect = ["--expected-database", str(database), "--expected-alembic-head", str(head)]
        with engine.begin() as connection:
            for directory in DIRECTORIES:
                connection.execute(
                    insert(projects).values(
                        project_id=project_of(directory),
                        principal_id=self.principal,
                        name="Synthetic project",
                        opened_at=WHEN,
                        created_at=WHEN,
                        updated_at=WHEN,
                        project_number=project_number_of(directory),
                    )
                )
            # A spare Project for the rebind (its number is not the fixtures').
            connection.execute(
                insert(projects).values(
                    project_id="prj_synpulsespare1",
                    principal_id=self.principal,
                    name="Synthetic project",
                    opened_at=WHEN,
                    created_at=WHEN,
                    updated_at=WHEN,
                    project_number="SYN-0999",
                )
            )

    def __call__(self, *argv: str) -> tuple[int, dict[str, Any]]:
        code = cli.main([*self.expect, *argv])
        captured = self.capsys.readouterr()
        assert captured.err == ""
        lines = captured.out.splitlines()
        assert len(lines) == 1, captured.out
        return code, json.loads(lines[0])

    def bind(self, directories: tuple[str, ...] = DIRECTORIES, **projects_of: str) -> None:
        document = {
            "schema": "my_pa_project_report_bindings_v1",
            "workspace_id": "mcp",
            "export_root": EXPORT_ROOT,
            "bindings": [
                {
                    "folder": folder_of(d),
                    "project_id": projects_of.get(d.replace("/", "_"), project_of(d)),
                    "project_number": "SYN-0999"
                    if d.replace("/", "_") in projects_of
                    else project_number_of(d),
                }
                for d in directories
            ],
        }
        path = self.files / f"bindings-{len(list(self.files.iterdir()))}.json"
        path.write_text(json.dumps(document))
        code, out = self("bindings", "apply", "--file", str(path))
        assert code == cli.EXIT_OK, out

    def source(self, directory: str) -> str:
        found = self.rows(
            "SELECT ingest_source_id FROM knowledge.ingest_sources WHERE path_prefix = :prefix",
            prefix=folder_of(directory) + "/",
        )
        assert len(found) == 1
        return str(found[0].ingest_source_id)

    def backfill(self, directory: str, *extra: str) -> dict[str, Any]:
        code, out = self("backfill", "--source", self.source(directory), *extra)
        assert code in (cli.EXIT_OK, cli.EXIT_RUN_INCOMPLETE), out
        return out

    def rows(self, sql: str, **params: object) -> list[Row[Any]]:
        with self.engine.connect() as connection:
            return list(connection.execute(text(sql), params))

    def counts(self) -> dict[str, int]:
        return {
            table: int(
                self.rows(f"SELECT count(*) AS n FROM knowledge.{table}")[0].n  # noqa: S608
            )
            for table in REPORT_TABLES
        }


@pytest.fixture
def operator(
    migrated_engine: Engine,
    workspace: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> Operator:
    files = tmp_path / "operator"
    files.mkdir()
    return Operator(migrated_engine, capsys, files, workspace)


def _file_level(directories: tuple[str, ...] = DIRECTORIES) -> dict[str, int]:
    numbers = {FIXTURES / d: project_number_of(d) for d in directories}
    document, ok = summarize_paths(list(numbers), numbers)
    assert ok
    return dict(document["counts"])  # type: ignore[call-overload]


def test_every_fixture_ingests_and_the_stored_aggregate_is_the_file_aggregate(
    operator: Operator,
) -> None:
    operator.bind()
    for directory in DIRECTORIES:
        out = operator.backfill(directory)
        assert (out["outcome"], out["counts"]["snapshots_failed"]) == ("completed", 0), directory
    argv = [arg for d in DIRECTORIES for arg in ("--source", operator.source(d))]
    code, out = operator("aggregate", *argv)
    assert code == cli.EXIT_OK
    assert out["counts"] == _file_level()
    assert out["counts"]["cross_report.match"] == 1
    assert out["counts"]["derivations.quarantined"] == 3
    # AC-17 mechanically: the committed real-data figures differ on synthetic rows.
    expected = FIXTURES.parent / "expected" / "evidence_aggregate_v1.json"
    code, differs = operator("aggregate", *argv, "--expect", str(expected))
    assert code == cli.EXIT_EXPECT_DIFFERS and differs["expect"]["differing"]

    # Stored role counts sum to the rows and equal the stored row roles.
    for row in operator.rows(
        "SELECT d.derivation_id, d.role_counts, s.data_row_count, d.state, "
        "(SELECT count(*) FROM knowledge.project_report_row_roles r "
        " WHERE r.derivation_id = d.derivation_id) AS roles, "
        "(SELECT count(*) FROM knowledge.project_report_rows w "
        " WHERE w.snapshot_id = d.snapshot_id) AS raw "
        "FROM knowledge.project_report_derivations d "
        "JOIN knowledge.project_report_snapshots s USING (principal_id, snapshot_id)"
    ):
        assert sum(row.role_counts.values()) == row.data_row_count == row.raw
        assert row.roles == (row.data_row_count if row.state == "classified" else 0)

    # Detail-only sums: each checked total is the sum of the detail lines in scope.
    totals = operator.rows(
        "SELECT t.derivation_id, t.row_ordinal, t.scope, t.field_key, t.computed_value "
        "FROM knowledge.project_report_stated_totals t WHERE t.outcome <> 'not_checked'"
    )
    assert totals
    checked = 0
    for total in totals:
        values = operator.rows(
            "SELECT v.value_decimal, r.group_path FROM knowledge.project_report_line_values v "
            "JOIN knowledge.project_report_row_roles r "
            "  ON (r.principal_id, r.derivation_id, r.row_ordinal) = "
            "     (v.principal_id, v.derivation_id, v.row_ordinal) "
            "WHERE v.derivation_id = :d AND v.field_key = :f AND r.row_role = 'detail' "
            "AND v.value_decimal IS NOT NULL",
            d=total.derivation_id,
            f=total.field_key,
        )
        if total.scope == "group":
            values = [
                v for v in values if any(step[2] == total.row_ordinal for step in v.group_path)
            ]
        expected_sum = sum((v.value_decimal for v in values), Decimal(0)) if values else None
        assert total.computed_value == expected_sum
        checked += 1
    assert checked == len(totals)


def test_the_same_bytes_write_once_and_two_sources_hold_two_snapshots(operator: Operator) -> None:
    operator.bind()
    for directory in ("sources/source_a", "sources/source_b"):
        assert operator.backfill(directory)["counts"]["snapshots_ingested"] == 1
    before = operator.counts()
    again = operator.backfill("sources/source_a")
    assert again["counts"]["snapshots_already_known"] == 1
    assert again["counts"]["snapshots_ingested"] == 0
    after = operator.counts()
    assert {k: v for k, v in after.items() if k != "ingest_runs"} == {
        k: v for k, v in before.items() if k != "ingest_runs"
    }
    shared = operator.rows(
        "SELECT file_sha256, count(*) AS n FROM knowledge.project_report_snapshots "
        "GROUP BY file_sha256"
    )
    assert [row.n for row in shared] == [2]


def test_a_quarantine_keeps_every_row_and_classifies_none(operator: Operator) -> None:
    operator.bind(("variants",))
    operator.backfill("variants")
    rows = operator.rows(
        "SELECT d.derivation_id, d.quarantine_reason, d.role_counts, s.data_row_count, "
        "(SELECT count(*) FROM knowledge.project_report_rows w "
        " WHERE w.snapshot_id = d.snapshot_id) AS raw, "
        "(SELECT count(*) FROM knowledge.project_report_row_roles r "
        " WHERE r.derivation_id = d.derivation_id) AS roles, "
        "(SELECT count(*) FROM knowledge.project_report_lines l "
        " WHERE l.derivation_id = d.derivation_id) AS lines "
        "FROM knowledge.project_report_derivations d "
        "JOIN knowledge.project_report_snapshots s USING (principal_id, snapshot_id)"
    )
    assert sorted(row.quarantine_reason for row in rows) == [
        "malformed_ratio_exceeded",
        "unknown_header_signature",
        "unknown_header_signature",
    ]
    for row in rows:
        assert row.raw == row.data_row_count > 0
        assert (row.roles, row.lines) == (0, 0)
        assert row.role_counts == {"unclassified": row.data_row_count}


def _with_unknown_registered() -> dict[str, pulse_csv.FamilyAdapter]:
    data = (FIXTURES / "variants" / "unknown_family.csv").read_bytes()
    header = pulse_csv.prepare_export(data).header.cells
    notes = next(a for a in pulse_csv.REGISTRY.values() if a.view is FamilyView.NOTES)
    fields = tuple(
        pulse_csv.FieldSpec(index, cell, f"note.synthetic_{index}", ValueKind.TEXT)
        for index, cell in enumerate(header)
    )
    adapter = dataclasses.replace(notes, fields=fields)
    return {**pulse_csv.REGISTRY, adapter.signature: adapter}


def test_an_unknown_signature_is_rederived_after_its_adapter_is_registered(
    operator: Operator,
) -> None:
    operator.bind(("variants",))
    operator.backfill("variants")
    sweep = ProjectReportsRederiver(
        unit_of_work=project_reports_unit_of_work(operator.engine),
        reader=PulseExportReader(_with_unknown_registered()),
    )
    report = sweep.sweep(operator.principal)
    assert report.counts["derivations_written_rederive_adapter"] == 1
    current = operator.rows(
        "SELECT state, family_view, trigger, supersedes_derivation_id "
        "FROM knowledge.project_report_current_derivations ORDER BY state"
    )
    assert [(r.state, r.trigger) for r in current] == [
        ("classified", "rederive_adapter"),
        ("quarantined", "ingest"),
        ("quarantined", "ingest"),
    ]
    assert current[0].family_view == "notes" and current[0].supersedes_derivation_id
    # Version current now: a second sweep writes nothing.
    assert "derivations_written_rederive_adapter" not in sweep.sweep(operator.principal).counts


def test_a_rebind_rederives_and_the_number_check_quarantines_then_clears(
    operator: Operator,
) -> None:
    operator.bind(("signatures",))
    operator.backfill("signatures")
    files = len(fixture_files("signatures"))
    operator.bind(("signatures",), signatures="prj_synpulsespare1")
    code, out = operator("rederive", "--dry-run")
    assert (code, out["counts"]["derivations_due_rederive_binding"]) == (cli.EXIT_OK, files)
    code, out = operator("rederive")
    assert out["counts"]["derivations_written_rederive_binding"] == files
    reasons = operator.rows(
        "SELECT quarantine_reason, count(*) AS n FROM knowledge.project_report_current_derivations "
        "WHERE quarantine_reason IS NOT NULL GROUP BY quarantine_reason"
    )
    assert [(r.quarantine_reason, r.n) for r in reasons] == [("binding_project_number_mismatch", 3)]
    operator.bind(("signatures",))
    code, out = operator("rederive")
    assert out["counts"]["derivations_written_rederive_binding"] == files
    assert not operator.rows(
        "SELECT 1 FROM knowledge.project_report_current_derivations WHERE state = 'quarantined'"
    )


def test_dry_runs_write_nothing_and_a_backfill_resumes(operator: Operator) -> None:
    operator.bind(("signatures",))
    before = operator.counts()
    out = operator.backfill("signatures", "--dry-run")
    assert (out["dry_run"], out["counts"]["snapshots_ingested"]) == (
        True,
        len(fixture_files("signatures")),
    )
    assert operator("rederive", "--dry-run")[0] == cli.EXIT_OK
    assert operator.counts() == before
    first = operator.backfill("signatures", "--file", name_of(0))
    assert first["counts"]["snapshots_ingested"] == 1
    rest = operator.backfill("signatures")
    assert (rest["counts"]["snapshots_already_known"], rest["counts"]["snapshots_ingested"]) == (
        1,
        len(fixture_files("signatures")) - 1,
    )


def test_a_retired_source_is_unbound_and_writes_nothing(operator: Operator) -> None:
    operator.bind(("signatures", "rfc"))
    operator.bind(("rfc",))  # signatures omitted: retired, its source disabled
    before = operator.counts()
    out = operator.backfill("signatures")
    assert (out["outcome"], out["counts"]["snapshots_failed"]) == (
        "failed",
        len(fixture_files("signatures")),
    )
    after = operator.counts()
    assert {k: v for k, v in after.items() if k != "ingest_runs"} == {
        k: v for k, v in before.items() if k != "ingest_runs"
    }


@pytest.mark.parametrize(
    "order", [("buyout_summary", "reconciliation"), ("reconciliation", "buyout_summary")]
)
def test_the_cross_report_check_is_written_once_in_either_order(
    operator: Operator, order: tuple[str, str]
) -> None:
    operator.bind(("signatures",))
    stems = [path.stem for path in fixture_files("signatures")]
    for view in order:
        operator.backfill("signatures", "--file", name_of(stems.index(view)))
    checks = operator.rows(
        "SELECT c.outcome, l.family_view AS left_view, r.family_view AS right_view "
        "FROM knowledge.project_report_cross_checks c "
        "JOIN knowledge.project_report_derivations l ON l.derivation_id = c.left_derivation_id "
        "JOIN knowledge.project_report_derivations r ON r.derivation_id = c.right_derivation_id"
    )
    assert [(c.outcome, c.left_view, c.right_view) for c in checks] == [
        ("match", "buyout_summary", "reconciliation")
    ]
    operator.backfill("signatures")
    assert len(operator.rows("SELECT 1 FROM knowledge.project_report_cross_checks")) == 1
