"""The reconciliation harness: its judgements, and its result on a real load.

The unit tests here are about the judgements, because those are what a reviewer
is trusting: that a shortfall no decision has looked at fails rather than being
waived, that an unmeasurable criterion reads UNEVALUATED rather than PASS, and
that the absence list is compared against OD-001 as written rather than against
the registry that is supposed to implement it.

The database test runs the whole harness against a synthetic corpus loaded by
the real loader into a disposable database. It asserts the shape of the answer
-- parity, quarantine, identity coverage, keyless content equality, emptiness,
exclusions, sequences -- without ever touching the real corpus.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from conftest import (
    PHASE_ONE,
    TARGET_SCHEMA,
    build_source,
    prepare_target,
    synthetic_registry,
)
from sqlalchemy import Engine

from my_pa.infrastructure.migration import binding, loader, reconciliation, redaction, runs
from my_pa.infrastructure.migration.reconciliation_report import render
from my_pa.infrastructure.migration.source import Disposition

#: The synthetic corpus, shaped so every judgement has something to judge: a
#: value that will not cast, a NULL TEXT primary key, a NUL byte in text, two
#: byte-identical rows in a keyless table, and an operational-state table that
#: must stay empty.
ROWS: tuple[tuple[str, Sequence[object]], ...] = (
    (
        "INSERT INTO widget_records (widget_id, label, weight, tally, is_current) "
        "VALUES (?, ?, ?, ?, ?)",
        ("w1", "alpha", 1.5, 10, 1),
    ),
    (
        "INSERT INTO widget_records (widget_id, label, weight, tally, is_current) "
        "VALUES (?, ?, ?, ?, ?)",
        ("w2", "beta", None, None, 0),
    ),
    ("INSERT INTO widget_defects (defect_id, note) VALUES (?, ?)", ("d1", "present")),
    ("INSERT INTO widget_defects (defect_id, note) VALUES (?, ?)", (None, "absent key")),
    ("INSERT INTO widget_defects (defect_id, note) VALUES (?, ?)", ("d3", "a\x00b")),
    ("INSERT INTO widget_events (event_id, widget_id, detail) VALUES (?, ?, ?)", (7, "w1", "e1")),
    ("INSERT INTO widget_notes (note_id, body) VALUES (?, ?)", (4, "note")),
    ("INSERT INTO widget_metrics (sample, taken_utc) VALUES (?, ?)", (1.0, "t0")),
    ("INSERT INTO widget_metrics (sample, taken_utc) VALUES (?, ?)", (1.0, "t0")),
)


def _parity(**overrides: object) -> reconciliation.TableParity:
    defaults: dict[str, object] = {
        "legacy_table": "widget_records",
        "phase": PHASE_ONE,
        "treatment": "SCHEMA_AND_DATA",
        "planning_disposition": "MIGRATE_DATA",
        "target_schema": TARGET_SCHEMA,
        "target_table": "widget_records",
        "source_rows": 10,
        "target_rows": 10,
        "quarantined_rows": 0,
    }
    return reconciliation.TableParity(**{**defaults, **overrides})  # type: ignore[arg-type]


def _quarantine(code: str, table: str = "widget_records") -> reconciliation.QuarantineGroup:
    return reconciliation.QuarantineGroup(
        error_code=code, legacy_table=table, column_name="note", rows=1
    )


def _report(**overrides: object) -> reconciliation.Reconciliation:
    """A report with everything clean, so a test can dirty exactly one thing."""
    defaults: dict[str, object] = {
        "generated_at": "2026-08-01T00:00:00+00:00",
        "source_schema_version": 128,
        "target_alembic_revision": "revision",
        "source": reconciliation.SourceIntegrity(
            file_name="synthetic.sqlite",
            sha256="0" * 64,
            byte_count=1,
            schema_version=128,
            journal_siblings=(),
            runs_agreeing=1,
            runs_disagreeing=(),
        ),
        "runs": (),
        "parity": (_parity(),),
        "quarantine": (),
        "identity": (
            reconciliation.IdentityCoverage(
                legacy_table="widget_records", key_map_entries=10, target_rows=10, keyed=True
            ),
        ),
        "keyless": (
            reconciliation.KeylessTableCheck(
                legacy_table="widget_metrics",
                target_schema=TARGET_SCHEMA,
                target_table="widget_metrics",
                source_rows=2,
                target_rows=2,
                distinct_surrogate_ids=2,
                distinct_source_hashes=1,
                hashes_only_in_source=0,
                hashes_only_in_target=0,
            ),
        ),
        "foreign_keys": reconciliation.ForeignKeySummary(
            total=1, validated=1, not_valid=(), by_schema=((TARGET_SCHEMA, 1, 1),)
        ),
        "empty_assertions": (),
        "exclusions": (),
        "absence": reconciliation.check_absence(
            {
                "absent_from_source": [
                    {"legacy_object": name, "planning_disposition": "MIGRATE_DATA"}
                    for name in reconciliation.ABSENT_FROM_SOURCE_AT_SCHEMA_128
                ]
            }
        ),
        "renames": reconciliation.RenameReport(
            total=1,
            by_kind=(("column", 1),),
            neutralised=(
                reconciliation.IdentifierRename(
                    object_kind="column",
                    owning_table=reconciliation.NEUTRALISED_COLUMN[0],
                    original=reconciliation.NEUTRALISED_COLUMN[1],
                    shortened=reconciliation.NEUTRALISED_COLUMN[2],
                ),
            ),
            longest_originals=(),
        ),
        "provenance": reconciliation.ProvenanceReport(
            columns=("migration_run_id",), tables_checked=1, rows_checked=10, gaps=()
        ),
        "sequences": (
            reconciliation.SequenceState(
                schema=TARGET_SCHEMA,
                table="widget_events",
                column="event_id",
                sequence="core.widget_events_event_id_seq",
                max_key=7,
                next_value=8,
                expected_next_value=8,
            ),
        ),
        "views": (
            reconciliation.ViewCheck(
                legacy_view="v_widget",
                target_schema=TARGET_SCHEMA,
                target_view="v_widget",
                source_rows=3,
                present_in_target=True,
                target_rows=3,
            ),
        ),
        "accounting": reconciliation.RowAccounting(
            source_tables=1,
            source_rows=10,
            registry_tables=1,
            loaded_rows=10,
            excluded_rows=0,
            asserted_empty_rows=0,
            objects_missing_from_registry=(),
            objects_in_no_bucket=(),
        ),
        "retention": reconciliation.RetentionRisk(
            source_file_name="synthetic.sqlite",
            source_bytes=1,
            source_sha256="0" * 64,
            siblings=(),
            verified_copies=0,
            rows_held_only_here=0,
        ),
        "scan": redaction.ScanResult(
            roots=("evidence",), files_scanned=1, files_skipped=0, findings=(), patterns=()
        ),
    }
    report = reconciliation.Reconciliation(**{**defaults, **overrides})  # type: ignore[arg-type]
    report.criteria = reconciliation.evaluate(report)
    return report


def _status(report: reconciliation.Reconciliation, identifier: str) -> reconciliation.Criterion:
    return next(item for item in report.criteria if item.identifier == identifier)


def test_a_clean_report_passes() -> None:
    assert _report().verdict == reconciliation.PASSED


def test_a_shortfall_a_decision_adjudicated_is_waived_and_names_the_decision() -> None:
    report = _report(
        parity=(_parity(source_rows=10, target_rows=9, quarantined_rows=1),),
        quarantine=(_quarantine("UNSUPPORTED_TEXT_NUL"),),
    )
    criterion = _status(report, "P10-02")
    assert criterion.status == reconciliation.WAIVED
    assert criterion.waiver == "OD-029"
    assert report.verdict == reconciliation.PASSED_WITH_WAIVERS


def test_a_shortfall_no_decision_has_looked_at_fails() -> None:
    report = _report(
        parity=(_parity(source_rows=10, target_rows=9, quarantined_rows=1),),
        quarantine=(_quarantine("TARGET_REJECTED_ROW"),),
    )
    assert _status(report, "P10-02").status == reconciliation.FAILED
    assert report.verdict == reconciliation.FAILED


def test_a_shortfall_quarantine_does_not_account_for_is_a_silent_loss() -> None:
    report = _report(parity=(_parity(source_rows=10, target_rows=9),))
    assert _status(report, "P10-01").status == reconciliation.FAILED
    assert _status(report, "P10-03").status == reconciliation.FAILED


def test_no_keyless_table_reads_unevaluated_rather_than_passing() -> None:
    report = _report(keyless=())
    assert _status(report, "P10-05").status == reconciliation.UNEVALUATED
    assert report.verdict == reconciliation.UNEVALUATED


def test_an_unequal_row_hash_multiset_fails_even_when_the_counts_match() -> None:
    report = _report(
        keyless=(
            reconciliation.KeylessTableCheck(
                legacy_table="widget_metrics",
                target_schema=TARGET_SCHEMA,
                target_table="widget_metrics",
                source_rows=2,
                target_rows=2,
                distinct_surrogate_ids=2,
                distinct_source_hashes=2,
                hashes_only_in_source=1,
                hashes_only_in_target=1,
            ),
        )
    )
    assert _status(report, "P10-05").status == reconciliation.FAILED


def test_an_unvalidated_foreign_key_fails_with_its_orphan_count() -> None:
    report = _report(
        foreign_keys=reconciliation.ForeignKeySummary(
            total=2,
            validated=1,
            not_valid=(
                reconciliation.ForeignKeyState(
                    schema=TARGET_SCHEMA,
                    table="widget_events",
                    constraint="fk",
                    referenced="core.widget_records",
                    orphan_rows=3,
                ),
            ),
            by_schema=((TARGET_SCHEMA, 2, 1),),
        )
    )
    assert _status(report, "P10-06").status == reconciliation.FAILED
    assert "3 orphan rows" in _status(report, "P10-06").detail


def test_a_missing_target_view_fails_rather_than_going_unmentioned() -> None:
    report = _report(
        views=(
            reconciliation.ViewCheck(
                legacy_view="v_widget",
                target_schema=TARGET_SCHEMA,
                target_view="v_widget",
                source_rows=3,
                present_in_target=False,
                target_rows=None,
            ),
        )
    )
    assert _status(report, "P10-16").status == reconciliation.FAILED
    assert "v_widget" in render(report)


def test_a_view_that_exists_but_does_not_match_its_source_count_fails() -> None:
    report = _report(
        views=(
            reconciliation.ViewCheck(
                legacy_view="v_widget",
                target_schema=TARGET_SCHEMA,
                target_view="v_widget",
                source_rows=3,
                present_in_target=True,
                target_rows=2,
            ),
        )
    )
    assert _status(report, "P10-16").status == reconciliation.FAILED


def test_the_withheld_total_is_both_non_loaded_buckets_together() -> None:
    accounting = reconciliation.RowAccounting(
        source_tables=3,
        source_rows=100,
        registry_tables=3,
        loaded_rows=90,
        excluded_rows=7,
        asserted_empty_rows=3,
        objects_missing_from_registry=(),
        objects_in_no_bucket=(),
    )
    assert accounting.withheld_rows == 10
    assert accounting.withheld_share == 0.1
    assert accounting.balanced


def test_the_retention_risk_prices_what_only_the_source_holds(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    source.write_bytes(b"payload")
    (tmp_path / "legacy.sqlite.bak").write_bytes(b"a different, earlier snapshot")
    (tmp_path / "legacy.sqlite.copy").write_bytes(b"payload")
    integrity = reconciliation.SourceIntegrity(
        file_name=source.name,
        sha256=binding.file_digest(source)[0],
        byte_count=source.stat().st_size,
        schema_version=128,
        journal_siblings=(),
        runs_agreeing=1,
        runs_disagreeing=(),
    )
    accounting = reconciliation.RowAccounting(
        source_tables=1,
        source_rows=100,
        registry_tables=1,
        loaded_rows=90,
        excluded_rows=7,
        asserted_empty_rows=3,
        objects_missing_from_registry=(),
        objects_in_no_bucket=(),
    )
    risk = reconciliation.check_retention(source, integrity, accounting, quarantined_rows=2)
    assert risk.rows_held_only_here == 12
    identical = {item.file_name for item in risk.siblings if item.identical_to_source}
    assert identical == {"legacy.sqlite.copy"}
    assert risk.verified_copies == 1
    assert risk.mitigated


def test_a_source_with_no_verified_copy_reports_the_risk_unmitigated(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    source.write_bytes(b"payload")
    integrity = reconciliation.SourceIntegrity(
        file_name=source.name,
        sha256=binding.file_digest(source)[0],
        byte_count=source.stat().st_size,
        schema_version=128,
        journal_siblings=(),
        runs_agreeing=1,
        runs_disagreeing=(),
    )
    accounting = reconciliation.RowAccounting(
        source_tables=1,
        source_rows=1,
        registry_tables=1,
        loaded_rows=1,
        excluded_rows=0,
        asserted_empty_rows=0,
        objects_missing_from_registry=(),
        objects_in_no_bucket=(),
    )
    risk = reconciliation.check_retention(source, integrity, accounting, quarantined_rows=0)
    assert risk.verified_copies == 0
    assert not risk.mitigated


def test_the_recorded_retention_risk_does_not_gate_the_verdict() -> None:
    report = _report()
    assert not report.retention.mitigated
    assert report.verdict == reconciliation.PASSED
    assert "recorded risk, not an acceptance criterion" in render(report)


def test_the_absence_list_is_compared_with_od_001_in_both_directions() -> None:
    short = reconciliation.check_absence(
        {
            "absent_from_source": [
                {"legacy_object": name, "planning_disposition": "MIGRATE_DATA"}
                for name in reconciliation.ABSENT_FROM_SOURCE_AT_SCHEMA_128[:-1]
            ]
        }
    )
    assert not short.matches
    assert short.missing_from_registry == (reconciliation.ABSENT_FROM_SOURCE_AT_SCHEMA_128[-1],)

    extra = reconciliation.check_absence(
        {
            "absent_from_source": [
                *(
                    {"legacy_object": name, "planning_disposition": "MIGRATE_DATA"}
                    for name in reconciliation.ABSENT_FROM_SOURCE_AT_SCHEMA_128
                ),
                {"legacy_object": "invented_table", "planning_disposition": "MIGRATE_DATA"},
            ]
        }
    )
    assert extra.unexpected_in_registry == ("invented_table",)


def test_row_accounting_refuses_a_source_object_with_no_disposition() -> None:
    report = _report(
        accounting=reconciliation.RowAccounting(
            source_tables=2,
            source_rows=10,
            registry_tables=1,
            loaded_rows=10,
            excluded_rows=0,
            asserted_empty_rows=0,
            objects_missing_from_registry=("orphan_table",),
            objects_in_no_bucket=("orphan_table",),
        )
    )
    assert _status(report, "P10-15").status == reconciliation.FAILED


def test_row_accounting_refuses_buckets_that_do_not_add_up() -> None:
    report = _report(
        accounting=reconciliation.RowAccounting(
            source_tables=1,
            source_rows=11,
            registry_tables=1,
            loaded_rows=10,
            excluded_rows=0,
            asserted_empty_rows=0,
            objects_missing_from_registry=(),
            objects_in_no_bucket=(),
        )
    )
    assert _status(report, "P10-15").status == reconciliation.FAILED


def test_a_redaction_finding_fails_the_phase() -> None:
    report = _report(
        scan=redaction.ScanResult(
            roots=("evidence",),
            files_scanned=1,
            files_skipped=0,
            findings=(redaction.Finding(path="evidence/a.md", line=1, pattern="EMAIL_ADDRESS"),),
            patterns=("EMAIL_ADDRESS",),
        )
    )
    assert _status(report, "P10-14").status == reconciliation.FAILED


def test_the_rendered_report_surfaces_the_neutralised_column_both_ways() -> None:
    owner, original, target = reconciliation.NEUTRALISED_COLUMN
    rendered = render(_report())
    assert original in rendered
    assert target in rendered
    assert owner in rendered


def test_the_rendered_report_names_every_criterion_and_its_result() -> None:
    report = _report()
    rendered = render(report)
    for criterion in report.criteria:
        assert criterion.identifier in rendered
    assert "PASSES against OD-012" in rendered


def test_the_rendered_report_is_itself_clean_of_personal_data() -> None:
    rendered = render(_report())
    assert redaction.scan_text("RECONCILIATION.md", rendered, redaction.patterns()) == ()


def test_the_machine_readable_record_carries_the_totals_and_the_verdict() -> None:
    document = reconciliation.as_dict(_report())
    assert document["record_type"] == "MIGRATION_PHASE_10_RECONCILIATION"
    assert document["verdict"] == reconciliation.PASSED
    assert document["totals"]["target_rows"] == 10
    assert document["parity_mismatches"] == []


@pytest.mark.database
class TestAgainstALoadedDatabase:
    """The whole harness, against a synthetic corpus the real loader loaded."""

    @pytest.fixture
    def source(self, tmp_path: Path) -> Path:
        return build_source(tmp_path / "synthetic.sqlite", ROWS)

    @pytest.fixture
    def registry(self) -> dict[str, Disposition]:
        entries = synthetic_registry()
        # `AUTOINCREMENT` makes SQLite create this; it is never migrated (OD-016),
        # and the row accounting starts from the catalogue, so it needs a
        # disposition like any other object.
        entries["sqlite_sequence"] = Disposition(
            legacy_object="sqlite_sequence",
            object_type="table",
            target_schema=TARGET_SCHEMA,
            target_treatment="NOT_CREATED",
            planning_disposition="DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE",
            ordering_group=f"{PHASE_ONE}:CROSS_CUTTING",
        )
        return entries

    @pytest.fixture
    def reconciled(
        self, target: Engine, source: Path, registry: dict[str, Disposition]
    ) -> reconciliation.Reconciliation:
        prepare_target(target, source)
        with target.begin() as connection:
            run_id = runs.create_run(connection, binding.observe(source, connection), dry_run=False)
        loader.load(target, source, registry, run_id)
        scan = redaction.ScanResult(
            roots=(), files_scanned=0, files_skipped=0, findings=(), patterns=()
        )
        return reconciliation.reconcile(target, source, registry, {"absent_from_source": []}, scan)

    def test_every_loaded_table_is_counted_on_both_sides(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        counted = {table.legacy_table for table in reconciled.parity}
        assert counted == {
            "widget_records",
            "widget_defects",
            "widget_metrics",
            "widget_notes",
            "widget_events",
        }
        assert all(table.accounted for table in reconciled.parity)

    def test_the_quarantined_rows_are_reported_by_table_column_and_code(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        codes = {(group.legacy_table, group.error_code) for group in reconciled.quarantine}
        assert ("widget_defects", "NULL_PRIMARY_KEY") in codes
        assert ("widget_defects", "UNSUPPORTED_TEXT_NUL") in codes
        assert reconciled.quarantined_rows == 2

    def test_the_shortfall_is_waived_by_the_decisions_that_adjudicated_it(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        criterion = _status(reconciled, "P10-02")
        assert criterion.status == reconciliation.WAIVED
        assert criterion.waiver == "OD-023, OD-029"

    def test_identity_coverage_matches_the_loaded_rows_of_every_keyed_table(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        assert all(item.covered for item in reconciled.identity)
        keyless = [item for item in reconciled.identity if not item.keyed]
        assert [item.legacy_table for item in keyless] == ["widget_metrics"]
        assert keyless[0].key_map_entries == 0

    def test_the_keyless_table_reconciles_by_row_hash_multiset(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        (check,) = reconciled.keyless
        assert check.legacy_table == "widget_metrics"
        assert check.source_rows == check.target_rows == 2
        assert check.distinct_surrogate_ids == 2
        # Two byte-identical source rows share one hash, and both are kept.
        assert check.distinct_source_hashes == 1
        assert check.multisets_equal

    def test_the_operational_state_table_is_asserted_empty_not_assumed(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        assert [item.legacy_table for item in reconciled.empty_assertions] == ["widget_cursors"]
        assert reconciled.empty_assertions[0].empty

    def test_every_excluded_object_is_named_with_its_reason_and_absent(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        excluded = {item.legacy_object: item for item in reconciled.exclusions}
        assert set(excluded) == {"schema_migrations", "sqlite_sequence"}
        assert not any(item.present_in_target for item in excluded.values())
        assert all(item.reason for item in excluded.values())

    def test_every_loaded_row_carries_a_complete_provenance_stamp(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        assert reconciled.provenance.complete
        assert reconciled.provenance.rows_checked == reconciled.target_rows

    def test_every_identity_sequence_sits_past_the_keys_that_were_loaded(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        assert reconciled.sequences
        assert all(state.correct for state in reconciled.sequences)
        events = next(state for state in reconciled.sequences if state.table == "widget_events")
        assert events.max_key == 7
        assert events.next_value == 8

    def test_the_source_file_is_unchanged_and_grew_no_journal(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        assert reconciled.source.journal_siblings == ()
        assert reconciled.source.runs_disagreeing == ()

    def test_every_source_row_lands_in_exactly_one_bucket(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        accounting = reconciled.accounting
        assert accounting.objects_missing_from_registry == ()
        assert accounting.objects_in_no_bucket == ()
        assert accounting.bucketed_rows == accounting.source_rows
        assert accounting.balanced

    def test_each_source_view_is_reconciled_by_existence_and_row_count(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        # The synthetic source defines no view, so the criterion has nothing to
        # measure. UNEVALUATED, not a pass by vacuous truth and not a failure of
        # a migration that had no view to port.
        assert reconciled.views == ()
        assert _status(reconciled, "P10-16").status == reconciliation.UNEVALUATED

    def test_the_report_renders_without_a_personal_data_finding(
        self, reconciled: reconciliation.Reconciliation
    ) -> None:
        rendered = render(reconciled)
        assert redaction.scan_text("RECONCILIATION.md", rendered, redaction.patterns()) == ()
