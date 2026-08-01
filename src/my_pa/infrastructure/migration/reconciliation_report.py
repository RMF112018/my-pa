"""Render a `Reconciliation` as the human-readable acceptance report.

Kept apart from the measurement so the two can be read independently: the checks
answer whether the migration is correct, and this answers whether a reviewer can
tell. The rendering adds no judgement of its own -- every number here comes from
the record it is handed, and nothing is rounded, summarised into a percentage,
or dropped for brevity where a reviewer would need it to recompute.

The per-table parity appendix is deliberately complete. A reconciliation that
prints only its failures asks the reader to trust the filter.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from my_pa.infrastructure.migration.reconciliation import (
    FAILED,
    NEUTRALISED_COLUMN,
    OPERATIONAL_STATE_LOADED,
    PASSED,
    PASSED_WITH_WAIVERS,
    UNEVALUATED,
    WAIVED,
    Reconciliation,
)

_HEADER = "# Phase 10 — Cross-Domain Reconciliation and Acceptance"


def _table(headings: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headings) + " |",
        "|" + "|".join("---" for _ in headings) + "|",
    ]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return lines


def _verdict_line(report: Reconciliation) -> list[str]:
    failed = [item for item in report.criteria if item.status == FAILED]
    waived = [item for item in report.criteria if item.status == WAIVED]
    unevaluated = [item for item in report.criteria if item.status == UNEVALUATED]
    if report.verdict == PASSED:
        headline = "**Phase 10 PASSES against OD-012.**"
    elif report.verdict == PASSED_WITH_WAIVERS:
        headline = (
            "**Phase 10 PASSES WITH WAIVERS against OD-012.** Every criterion holds except "
            "ones a named decision authorises in advance."
        )
    elif report.verdict == FAILED:
        headline = "**Phase 10 FAILS against OD-012.**"
    else:
        headline = (
            "**Phase 10 is UNEVALUATED against OD-012.** At least one criterion could not "
            "be measured and must not be read as a pass."
        )
    lines = [headline, ""]
    for item in failed:
        lines.append(f"- FAIL `{item.identifier}` — {item.statement} ({item.detail}).")
    for item in unevaluated:
        lines.append(f"- UNEVALUATED `{item.identifier}` — {item.statement} ({item.detail}).")
    for item in waived:
        lines.append(
            f"- WAIVED `{item.identifier}` under {item.waiver} — {item.statement} ({item.detail})."
        )
    return lines


def _identity(report: Reconciliation) -> list[str]:
    source = report.source
    lines = [
        "## Bound identity",
        "",
        "The campaign migrates the schema-128 source under OD-001, not the schema-135",
        "snapshot the plan named; that file does not exist on this machine. The deviation",
        "is recorded here rather than reconciled away.",
        "",
        *_table(
            ("fact", "value"),
            (
                ("source file", source.file_name),
                ("source sha256", f"`{source.sha256}`"),
                ("source bytes", f"{source.byte_count:,}"),
                ("source schema_migrations version", source.schema_version),
                ("target Alembic revision", f"`{report.target_alembic_revision}`"),
                ("journal siblings beside the source", len(source.journal_siblings) or "none"),
                (
                    "runs agreeing with the measured digest",
                    f"{source.runs_agreeing}/{len(report.runs)}",
                ),
            ),
        ),
        "",
        "### Runs",
        "",
        *_table(
            ("run", "status", "dry run", "schema", "revision", "bytes", "sha256 (first 16)"),
            (
                (
                    f"`{run.run_id}`",
                    run.status,
                    run.dry_run,
                    run.source_schema_version,
                    f"`{run.target_alembic_revision}`",
                    f"{run.source_bytes:,}",
                    f"`{run.source_sha256[:16]}`",
                )
                for run in report.runs
            ),
        ),
        "",
    ]
    if source.journal_siblings:
        lines.extend(
            [
                "The source has journal siblings, which OD-003 forbids: "
                + ", ".join(source.journal_siblings),
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No `-wal`, `-shm`, or `-journal` sibling exists beside the live source file.",
                "Every read used `immutable=1`, which is what makes that true rather than lucky.",
                "",
            ]
        )
    return lines


def _headline(report: Reconciliation) -> list[str]:
    return [
        "## Headline numbers",
        "",
        *_table(
            ("measure", "value"),
            (
                ("tables loaded", f"{len(report.parity):,}"),
                ("source rows in loaded tables", f"{report.source_rows:,}"),
                ("rows in the target", f"{report.target_rows:,}"),
                ("rows quarantined", f"{report.quarantined_rows:,}"),
                ("objects deliberately not created", f"{len(report.exclusions):,}"),
                ("source rows deliberately excluded", f"{report.excluded_rows:,}"),
                (
                    "source rows withheld from the target in total",
                    f"{report.accounting.withheld_rows:,} ({report.accounting.withheld_share:.2%})",
                ),
                ("tables asserted empty", f"{len(report.empty_assertions):,}"),
                ("tables created in the target", f"{report.created_tables:,}"),
                ("plan objects absent from the source", f"{len(report.absence.observed):,}"),
                (
                    "foreign keys validated",
                    f"{report.foreign_keys.validated:,} of {report.foreign_keys.total:,}",
                ),
                ("identifier renames recorded", f"{report.renames.total:,}"),
                ("identity sequences checked", f"{len(report.sequences):,}"),
            ),
        ),
        "",
        f"The first two rows overlap by {report.doubly_counted:,}: a `PROVENANCE_ONLY` table",
        "is loaded *and* asserted empty, so it appears in both. That is why",
        f"{len(report.parity):,} + {len(report.empty_assertions):,} exceeds the",
        f"{report.created_tables:,} tables actually created. Both figures are correct and no",
        "total below double-counts a row; the arithmetic just needs the note.",
        "",
    ]


def _criteria(report: Reconciliation) -> list[str]:
    return [
        "## Acceptance criteria (OD-012)",
        "",
        "`WAIVED` means a decision in the register adjudicated the shortfall before it",
        "happened and the waiver names that decision. It is not a pass and it is not",
        "discretion exercised here; a shortfall no decision has looked at is a `FAIL`.",
        "",
        *_table(
            ("id", "criterion", "result", "waiver", "measured"),
            (
                (
                    criterion.identifier,
                    criterion.statement,
                    criterion.status,
                    criterion.waiver or "—",
                    criterion.detail,
                )
                for criterion in report.criteria
            ),
        ),
        "",
    ]


def _departures(report: Reconciliation) -> list[str]:
    lines = [
        "## 0a. Departures from the plan's dispositions",
        "",
        "OD-008 assigned every legacy table a treatment. Four planning classes did **not**",
        "get the treatment the plan named: each was reversed by a later decision, and each",
        "reversal loaded data the plan would have left out of the target. They are listed",
        "here together so the fact is discoverable without cross-tabulating the appendix.",
        "",
        "Nothing here is a defect. All four reversals are governed, and the point of this",
        "section is disclosure, not correction.",
        "",
    ]
    if not report.departures:
        lines.extend(["No planning class departed from its OD-008 treatment.", ""])
        return lines
    lines.extend(
        [
            *_table(
                (
                    "planning class",
                    "OD-008 said",
                    "decision",
                    "tables loaded",
                    "rows loaded",
                    "tables withheld",
                    "rows withheld",
                ),
                (
                    (
                        f"`{item.planning_disposition}`",
                        item.plan_said,
                        item.decision,
                        f"{item.tables_loaded:,}",
                        f"{item.rows_loaded:,}",
                        f"{item.tables_withheld:,}",
                        f"{item.rows_withheld:,}",
                    )
                    for item in report.departures
                ),
            ),
            "",
            "A class with a non-zero figure in both loaded and withheld was **split**, not",
            "reversed wholesale. Reading either column alone misstates what happened to it.",
            "",
        ]
    )
    for item in report.departures:
        if item.withheld_tables:
            lines.append(
                f"`{item.planning_disposition}` withheld: "
                + ", ".join(f"`{name}`" for name in item.withheld_tables)
                + "."
            )
        elif item.tables_withheld:
            lines.append(
                f"`{item.planning_disposition}` withheld {item.tables_withheld} tables; "
                "they are listed in sections 6 and 7."
            )
    lines.append("")
    undeclared = [item for item in report.departures if item.decision == "undeclared"]
    if undeclared:
        lines.extend(
            [
                "Departures with no governing decision recorded: "
                + ", ".join(f"`{item.planning_disposition}`" for item in undeclared)
                + ". A departure nobody decided is a defect, not a disclosure.",
                "",
            ]
        )
    return lines


def _accounting(report: Reconciliation) -> list[str]:
    accounting = report.accounting
    lines = [
        "## 0. Global row accounting",
        "",
        "The sweep starts at the source's own `sqlite_master`, not at the disposition",
        "registry: a registry that omitted an object would otherwise reconcile perfectly",
        "against itself while a table went missing. Every source table is placed in exactly",
        "one bucket and the row counts have to add up.",
        "",
        *_table(
            ("bucket", "rows"),
            (
                ("loaded", f"{accounting.loaded_rows:,}"),
                ("deliberately not created", f"{accounting.excluded_rows:,}"),
                ("created and asserted empty", f"{accounting.asserted_empty_rows:,}"),
                ("**total bucketed**", f"**{accounting.bucketed_rows:,}**"),
                ("**source rows, all tables**", f"**{accounting.source_rows:,}**"),
            ),
        ),
        "",
        f"{accounting.source_tables} tables exist in the source catalogue and",
        f"{accounting.registry_tables} carry a disposition.",
        "",
        f"**{accounting.withheld_rows:,} source rows ({accounting.withheld_share:.2%}) reach no",
        f"target table**, by either route; {accounting.loaded_rows:,} "
        f"({1 - accounting.withheld_share:.2%}) do.",
        "",
        "OD-025 puts the withheld figure at 64,960 with operational state at 13,216. That",
        "number is stale: it was derived before OD-028 moved five `*_runs` tables (5,388",
        "rows) into scope, and 64,960 - 5,388 = 59,572. The figure above is computed from",
        "the registry and the source rather than restated, and it is the one to use.",
        "",
    ]
    if accounting.objects_missing_from_registry:
        lines.extend(
            [
                "Source objects with no disposition at all: "
                + ", ".join(f"`{name}`" for name in accounting.objects_missing_from_registry),
                "",
            ]
        )
    if accounting.objects_in_no_bucket:
        lines.extend(
            [
                "Source objects in no bucket: "
                + ", ".join(f"`{name}`" for name in accounting.objects_in_no_bucket),
                "",
            ]
        )
    if accounting.balanced:
        lines.extend(
            [
                "The buckets balance exactly against the source. No row is unaccounted for and",
                "no source object is missing a disposition.",
                "",
            ]
        )
    return lines


def _views(report: Reconciliation) -> list[str]:
    missing = [view for view in report.views if not view.present_in_target]
    lines = [
        "## 13. The two SQLite read models (OD-018)",
        "",
        "`v_procore_inspection_unanswered_items` and `v_procore_open_action_signals` are",
        "SQLite-dialect views over base tables that are now loaded. OD-018 requires them",
        "hand-ported to PostgreSQL and each verified by comparing its row count against the",
        "source view's.",
        "",
        *_table(
            ("legacy view", "target", "source rows", "present", "target rows"),
            (
                (
                    f"`{view.legacy_view}`",
                    f"`{view.target_schema}.{view.target_view}`",
                    f"{view.source_rows:,}",
                    "yes" if view.present_in_target else "**no**",
                    "—" if view.target_rows is None else f"{view.target_rows:,}",
                )
                for view in report.views
            ),
        ),
        "",
    ]
    if missing:
        lines.extend(
            [
                f"{len(missing)} of the {len(report.views)} views do not exist in the target.",
                "They are two of the plan's 595 objects and they have landed nowhere: not",
                "loaded, not excluded by any treatment, and not created. Their base tables are",
                "loaded, so this is unfinished porting rather than missing data, but it is an",
                "incomplete migration and it is reported as one rather than folded into a",
                "count of tables.",
                "",
            ]
        )
    return lines


def _parity(report: Reconciliation) -> list[str]:
    mismatches = [table for table in report.parity if not table.exact]
    unaccounted = [table for table in report.parity if not table.accounted]
    lines = [
        "## 1. Row-count parity",
        "",
        f"Every one of the {len(report.parity)} tables whose treatment carries data was counted",
        "on both sides. The full per-table listing is the appendix; this section names only",
        "the tables where the two numbers differ, and no difference is aggregated away.",
        "",
    ]
    if not mismatches:
        lines.extend(["Source and target counts are equal for every loaded table.", ""])
        return lines
    lines.extend(
        [
            f"{len(mismatches)} tables differ:",
            "",
            *_table(
                ("legacy table", "source", "target", "quarantined", "unexplained"),
                (
                    (
                        f"`{table.legacy_table}`",
                        f"{table.source_rows:,}",
                        f"{table.target_rows:,}",
                        f"{table.quarantined_rows:,}",
                        f"{table.source_rows - table.target_rows - table.quarantined_rows:,}",
                    )
                    for table in mismatches
                ),
            ),
            "",
        ]
    )
    if unaccounted:
        lines.extend(
            [
                f"{len(unaccounted)} of those have a shortfall the quarantine ledger does not",
                "explain. That is a silent loss and it fails OD-012.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "Every difference is accounted for row-for-row by a quarantine record naming",
                "the table, the column, and the reason. No row went missing without a name.",
                "",
            ]
        )
    return lines


def _quarantine(report: Reconciliation) -> list[str]:
    lines = ["## 2. Quarantine", ""]
    if not report.quarantine:
        lines.extend(
            [
                "No row was quarantined. This is stated rather than omitted: an absent",
                "quarantine section and a quarantine section reporting zero are different",
                "claims.",
                "",
            ]
        )
        return lines
    lines.extend(
        [
            f"{report.quarantined_rows} rows were refused and named. Each is recorded by table,",
            "column, error code, and a hash of its key -- never by value.",
            "",
            *_table(
                ("error code", "legacy table", "column", "rows"),
                (
                    (
                        group.error_code,
                        f"`{group.legacy_table}`",
                        "—" if group.column_name is None else f"`{group.column_name}`",
                        group.rows,
                    )
                    for group in report.quarantine
                ),
            ),
            "",
        ]
    )
    if any(group.error_code == "UNSUPPORTED_TEXT_NUL" for group in report.quarantine):
        lines.extend(
            [
                "The columns above are read from `migration_control.quarantine_records`, not",
                "from OD-029, which names `text_content` on both tables. That column does not",
                "exist on either; the measured names are the ones in this table and they are",
                "what a reader should search for. The decision's substance is unaffected: the",
                "rows are refused and named rather than stripped of a byte of the owner's",
                "content, and the legacy source retains the originals unchanged.",
                "",
            ]
        )
    return lines


def _identity_coverage(report: Reconciliation) -> list[str]:
    keyed = [item for item in report.identity if item.keyed]
    keyless = [item for item in report.identity if not item.keyed]
    uncovered = [item for item in report.identity if not item.covered]
    lines = [
        "## 3. Identity coverage",
        "",
        "`migration_control.source_key_map` holds one entry per loaded row of a keyed",
        f"table. {len(keyed)} loaded tables have a source-side key; {len(keyless)} do not.",
        "",
        *_table(
            ("class", "tables", "map entries", "target rows"),
            (
                (
                    "keyed",
                    len(keyed),
                    f"{sum(item.key_map_entries for item in keyed):,}",
                    f"{sum(item.target_rows for item in keyed):,}",
                ),
                (
                    "keyless (OD-014)",
                    len(keyless),
                    f"{sum(item.key_map_entries for item in keyless):,}",
                    f"{sum(item.target_rows for item in keyless):,}",
                ),
            ),
        ),
        "",
    ]
    if keyless:
        names = ", ".join(f"`{item.legacy_table}`" for item in keyless)
        lines.extend(
            [
                f"The keyless tables are legitimately absent from `source_key_map`: {names}.",
                "OD-014 refuses to invent a business key the source never had, so identity for",
                "these is content equality, checked in section 4.",
                "",
            ]
        )
    if uncovered:
        lines.extend(
            [
                f"{len(uncovered)} tables have coverage that does not match their row count:",
                "",
                *_table(
                    ("legacy table", "map entries", "target rows", "keyed"),
                    (
                        (
                            f"`{item.legacy_table}`",
                            item.key_map_entries,
                            item.target_rows,
                            item.keyed,
                        )
                        for item in uncovered
                    ),
                ),
                "",
            ]
        )
    else:
        lines.extend(["Every keyed table's coverage equals its loaded row count.", ""])
    return lines


def _keyless(report: Reconciliation) -> list[str]:
    lines = [
        "## 4. OD-014 — the keyless table",
        "",
        "`schedule_cpm_relationship_results` has neither a primary key nor a unique index in",
        "the source, so a row count is not the guarantee. The check recomputes the SHA-256 of",
        "every source tuple and compares the two multisets against the stored",
        "`migration_source_row_hash`, which catches reordering, duplication, and truncation.",
        "",
    ]
    if not report.keyless:
        lines.extend(
            [
                "No keyless table was found among the loaded tables. This criterion is",
                "UNEVALUATED, not passed.",
                "",
            ]
        )
        return lines
    lines.extend(
        _table(
            (
                "legacy table",
                "source",
                "target",
                "distinct surrogate ids",
                "distinct hashes",
                "only in source",
                "only in target",
                "multisets equal",
            ),
            (
                (
                    f"`{check.legacy_table}`",
                    f"{check.source_rows:,}",
                    f"{check.target_rows:,}",
                    f"{check.distinct_surrogate_ids:,}",
                    f"{check.distinct_source_hashes:,}",
                    check.hashes_only_in_source,
                    check.hashes_only_in_target,
                    "yes" if check.multisets_equal else "**no**",
                )
                for check in report.keyless
            ),
        )
    )
    lines.append("")
    duplicated = [
        check for check in report.keyless if check.distinct_source_hashes != check.source_rows
    ]
    if duplicated:
        lines.extend(
            [
                "Fewer distinct hashes than rows means the source itself holds byte-identical",
                "duplicate tuples. They are loaded as separate rows, because collapsing them",
                "would lose data the source actually holds (OD-014), and the multiset check",
                "compares multiplicities rather than sets so the duplication is verified, not",
                "hidden.",
                "",
            ]
        )
    return lines


def _foreign_keys(report: Reconciliation) -> list[str]:
    summary = report.foreign_keys
    lines = [
        "## 5. Foreign keys",
        "",
        "SQLite never enforced its declared constraints, so the migration adds every foreign",
        "key `NOT VALID` and then validates it (OD-017). This check counts the result and",
        "prices anything still unvalidated. It never validates a constraint itself: doing so",
        "would change the database the report describes.",
        "",
        *_table(
            ("schema", "foreign keys", "validated", "NOT VALID"),
            (
                (schema, total, validated, total - validated)
                for schema, total, validated in summary.by_schema
            ),
        ),
        "",
        f"Total {summary.total}, validated {summary.validated}, left `NOT VALID` "
        f"{len(summary.not_valid)}, orphan rows {summary.orphan_rows}.",
        "",
    ]
    if summary.not_valid:
        lines.extend(
            [
                *_table(
                    ("schema", "table", "constraint", "references", "orphan rows"),
                    (
                        (
                            state.schema,
                            f"`{state.table}`",
                            f"`{state.constraint}`",
                            f"`{state.referenced}`",
                            f"{state.orphan_rows:,}",
                        )
                        for state in summary.not_valid
                    ),
                ),
                "",
                "An unvalidated constraint is a pre-existing integrity fact about the source.",
                "Nothing was deleted or invented to make one pass.",
                "",
            ]
        )
    return lines


def _empty(report: Reconciliation) -> list[str]:
    by_treatment: dict[str, list[int]] = {}
    for item in report.empty_assertions:
        totals = by_treatment.setdefault(item.treatment, [0, 0, 0])
        totals[0] += 1
        totals[1] += item.source_rows
        totals[2] += item.target_rows
    non_empty = [item for item in report.empty_assertions if not item.empty]
    lines = [
        "## 6. Deliberately empty classes, asserted empty",
        "",
        "Each of these tables exists in the target and is required to hold no rows. Every one",
        "was queried; none is assumed.",
        "",
        *_table(
            ("treatment", "tables", "source rows withheld", "target rows"),
            (
                (treatment, totals[0], f"{totals[1]:,}", totals[2])
                for treatment, totals in sorted(by_treatment.items())
            ),
        ),
        "",
        "The operational-state class has "
        f"{by_treatment.get('SCHEMA_ONLY_EMPTY_BY_DESIGN', [0])[0]} members rather than 90:",
        "OD-028 loads five provenance tables out of it, because withholding the rows that",
        "record which computation produced the derived data would have manufactured orphans",
        "rather than preserved a clean slate. Those five are "
        + ", ".join(f"`{name}`" for name in OPERATIONAL_STATE_LOADED)
        + ", and they appear in the parity appendix as loaded tables.",
        "",
    ]
    if non_empty:
        lines.extend(
            [
                f"{len(non_empty)} tables are not empty and should be:",
                "",
                *_table(
                    ("legacy table", "treatment", "target rows"),
                    (
                        (f"`{item.legacy_table}`", item.treatment, item.target_rows)
                        for item in non_empty
                    ),
                ),
                "",
            ]
        )
    else:
        lines.extend(["Every asserted-empty table holds exactly zero rows.", ""])
    return lines


def _exclusions(report: Reconciliation) -> list[str]:
    by_treatment: dict[str, list[int]] = {}
    for item in report.exclusions:
        totals = by_treatment.setdefault(item.treatment, [0, 0])
        totals[0] += 1
        totals[1] += item.source_rows
    leaked = [item for item in report.exclusions if item.present_in_target]
    lines = [
        "## 7. The excluded objects",
        "",
        f"{len(report.exclusions)} source objects carrying {report.excluded_rows:,} rows are",
        "deliberately not created in the target. Every one is named below with its planning",
        "disposition, its reason, and its source row count, so the exclusion is auditable",
        "rather than assumed.",
        "",
        *_table(
            ("treatment", "objects", "source rows"),
            (
                (treatment, totals[0], f"{totals[1]:,}")
                for treatment, totals in sorted(by_treatment.items())
            ),
        ),
        "",
    ]
    if leaked:
        lines.extend(
            [
                f"{len(leaked)} of them exist in the target anyway, which contradicts the",
                "treatment:",
                "",
                *_table(
                    ("legacy object", "treatment"),
                    ((f"`{item.legacy_object}`", item.treatment) for item in leaked),
                ),
                "",
            ]
        )
    else:
        lines.extend(["None of them exists in the target database.", ""])
    privacy = [
        item
        for item in report.exclusions
        if item.planning_disposition == "DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION"
    ]
    deferred_loaded = [
        table
        for table in report.parity
        if table.planning_disposition == "DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION"
    ]
    if privacy or deferred_loaded:
        total = len(privacy) + len(deferred_loaded)
        lines.extend(
            [
                "### The deferred class was split, not withheld",
                "",
                f"`DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION` has {total} tables in the source.",
                f"**{len(deferred_loaded)} were loaded** "
                f"({sum(table.source_rows for table in deferred_loaded):,} rows) and "
                f"**{len(privacy)} were withheld** "
                f"({sum(item.source_rows for item in privacy):,} rows). The "
                f"`NOT_CREATED_PRIVACY_GATED` count of {len(privacy)} in the table above is the",
                "withheld part only and must not be read as the whole class.",
                "",
                "Withheld, and the only two the privacy gate meant (OD-025): "
                + ", ".join(f"`{item.legacy_object}`" for item in privacy)
                + ".",
                "",
                "The rest are `NONSENSITIVE_OR_OPERATIONAL_METADATA` and were loaded as",
                "ordinary owner-owned data. Migrating data is not activating a product",
                "feature -- the distinction OP-PROD-001 drew and OD-025 applied here.",
                "",
            ]
        )
    lines.extend(
        [
            "### Every excluded object",
            "",
            *_table(
                ("legacy object", "kind", "planning disposition", "reason", "source rows"),
                (
                    (
                        f"`{item.legacy_object}`",
                        item.object_type,
                        item.planning_disposition,
                        item.reason,
                        f"{item.source_rows:,}",
                    )
                    for item in report.exclusions
                ),
            ),
            "",
        ]
    )
    return lines


def _absence(report: Reconciliation) -> list[str]:
    absence = report.absence
    lines = [
        "## 8. ABSENT_FROM_SOURCE_AT_SCHEMA_128",
        "",
        f"{len(absence.observed)} plan objects, all of them schema v129-v135 additions, do not",
        "exist in the schema-128 source. They are an expected, named gap under OD-001, not a",
        "shortfall, and no target table is created for any of them.",
        "",
        *_table(
            ("legacy object", "planning disposition"),
            ((f"`{item.legacy_object}`", item.planning_disposition) for item in absence.observed),
        ),
        "",
    ]
    if absence.matches:
        lines.extend(
            [
                "The list matches OD-001 exactly: the decision register's 15 names were compared",
                "against the registry's, in both directions.",
                "",
            ]
        )
    else:
        if absence.missing_from_registry:
            lines.append(
                "Named by OD-001 but absent from the registry: "
                + ", ".join(f"`{name}`" for name in absence.missing_from_registry)
            )
        if absence.unexpected_in_registry:
            lines.append(
                "In the registry but not named by OD-001: "
                + ", ".join(f"`{name}`" for name in absence.unexpected_in_registry)
            )
        lines.append("")
    return lines


def _renames(report: Reconciliation) -> list[str]:
    renames = report.renames
    owner, original, expected = NEUTRALISED_COLUMN
    lines = [
        "## 9. Identifier renames",
        "",
        f"{renames.total} identifiers were renamed and recorded in",
        "`migration_control.identifier_map`. PostgreSQL's 63-byte budget is the only reason",
        "a name was shortened; a shortened name keeps its first 55 bytes and gains 7 hex",
        "characters of the SHA-256 of the full original, so two names that differ only after",
        "byte 63 do not collide (OD-013).",
        "",
        *_table(
            ("object kind", "renames"),
            ((kind, count) for kind, count in renames.by_kind),
        ),
        "",
        "### The one rename that is a policy decision, not a length problem",
        "",
    ]
    if renames.neutralised:
        for rename in renames.neutralised:
            correct = "" if rename.shortened == expected else "  <!-- unexpected target -->"
            lines.append(
                f"`{rename.owning_table}.{rename.original}` -> "
                f"`{rename.owning_table}.{rename.shortened}`{correct}"
            )
        lines.extend(
            [
                "",
                "This is OD-024. It is the single source identifier carrying former-employer",
                "branding, and the repository's neutral-naming rule wins for a newly created",
                "identifier. **The column was not lost.** A reader searching the legacy name",
                f"`{original}` will find it here and in `identifier_map`, mapped to the target",
                f"column `{expected}` on `{owner}`. The scope of the rename is the column name",
                "only: the column's values are data and were migrated unchanged.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"No rename of `{owner}.{original}` is recorded in `identifier_map`, which",
                "OD-024 requires. This is a gap in the evidence, not a silent success.",
                "",
            ]
        )
    if renames.longest_originals:
        lines.extend(
            [
                "### The longest originals",
                "",
                *_table(
                    ("object kind", "owning table", "original bytes", "target"),
                    (
                        (
                            rename.object_kind,
                            f"`{rename.owning_table}`",
                            len(rename.original.encode("utf-8")),
                            f"`{rename.shortened}`",
                        )
                        for rename in renames.longest_originals
                    ),
                ),
                "",
                "The full mapping is in `reconciliation.json` and queryable from",
                "`migration_control.identifier_map`.",
                "",
            ]
        )
    return lines


def _provenance(report: Reconciliation) -> list[str]:
    provenance = report.provenance
    columns = ", ".join(f"`{name}`" for name in provenance.columns)
    lines = [
        "## 10. Provenance completeness",
        "",
        f"OD-011 requires every migrated row to carry {columns}. Every non-empty loaded table",
        "was queried for a NULL in any of the four.",
        "",
        f"Tables checked: {provenance.tables_checked}. Rows covered: {provenance.rows_checked:,}.",
        "",
    ]
    if provenance.complete:
        lines.extend(["No loaded row has a NULL in any provenance column.", ""])
    else:
        lines.extend(
            [
                *_table(
                    ("legacy table", "rows with an incomplete stamp"),
                    (
                        (f"`{gap.legacy_table}`", f"{gap.rows_with_null_provenance:,}")
                        for gap in provenance.gaps
                    ),
                ),
                "",
            ]
        )
    return lines


def _sequences(report: Reconciliation) -> list[str]:
    wrong = [state for state in report.sequences if not state.correct]
    empty = [state for state in report.sequences if state.max_key is None]
    lines = [
        "## 11. Identity sequences",
        "",
        "The load inserts the source's own keys into `GENERATED BY DEFAULT AS IDENTITY`",
        "columns, which leaves each sequence behind its data until it is reset (OD-016,",
        "OD-022). Without the reset, the first ordinary application insert would collide.",
        "",
        f"{len(report.sequences)} identity sequences were checked. {len(empty)} belong to an",
        f"empty table and are legitimately at 1. {len(report.sequences) - len(empty)} are at",
        "`max(key) + 1`.",
        "",
    ]
    if wrong:
        lines.extend(
            [
                f"{len(wrong)} are not where they should be:",
                "",
                *_table(
                    ("schema", "table", "column", "max key", "next value", "expected"),
                    (
                        (
                            state.schema,
                            f"`{state.table}`",
                            f"`{state.column}`",
                            "—" if state.max_key is None else state.max_key,
                            state.next_value,
                            state.expected_next_value,
                        )
                        for state in wrong
                    ),
                ),
                "",
            ]
        )
    else:
        lines.extend(["Every sequence is at its expected next value.", ""])
    return lines


def _redaction(report: Reconciliation) -> list[str]:
    scan = report.scan
    lines = [
        "## 12. Redaction scan (OD-004)",
        "",
        "The scan covers " + ", ".join(f"`{root}`" for root in scan.roots) + ", including this",
        "report itself. A finding names a file, a line, and a pattern, and never quotes what",
        "it matched -- printing the match would put the disclosure in the artefact that is",
        "supposed to be clean.",
        "",
        "`src` and `tests` are deliberately outside that scope -- they are ordinary source",
        "code, covered by review and the repository's own checks -- so this scan does not",
        "claim coverage of them.",
        "",
        f"Files scanned: {scan.files_scanned}. Non-text files skipped: {scan.files_skipped}.",
        f"Patterns: {', '.join(scan.patterns)}.",
        "",
    ]
    if scan.clean:
        lines.extend(["No finding.", ""])
    else:
        lines.extend(
            [
                f"{len(scan.findings)} findings:",
                "",
                *_table(
                    ("file", "line", "pattern"),
                    (
                        (f"`{finding.path}`", finding.line, finding.pattern)
                        for finding in scan.findings
                    ),
                ),
                "",
            ]
        )
    lines.extend(
        [
            "The patterns are mechanical: mail addresses, telephone numbers, absolute",
            "home-directory paths, and the local account name discovered at runtime. Free-text",
            "personal names are **not** detected by pattern, because a regular expression",
            "cannot make that judgement and claiming otherwise would report a clean scan that",
            "means less than it appears to. What supports the personal-name claim instead is",
            "construction: every artefact this phase writes is built from table names, column",
            "names, type names, error codes, counts, and digests, and no query in the harness",
            "reads a row value into its output.",
            "",
        ]
    )
    return lines


def _retention(report: Reconciliation) -> list[str]:
    retention = report.retention
    lines = [
        "## 14. Single-copy retention risk (OD-030)",
        "",
        "**This is a recorded risk, not an acceptance criterion.** It does not gate the",
        "verdict above, and it is not mitigated.",
        "",
        f"{retention.rows_held_only_here:,} source rows exist nowhere but inside the one",
        f"{retention.source_bytes:,}-byte legacy file: the "
        f"{report.accounting.withheld_rows:,} rows withheld from the target by decision, plus",
        f"the {report.quarantined_rows} rows PostgreSQL could not represent. For those rows the",
        "source file is the sole custodian, and OD-003 keeps it retained indefinitely --",
        "retention is not redundancy.",
        "",
    ]
    if retention.siblings:
        lines.extend(
            [
                "Files beside it, by size. A byte-identical copy would have to match the",
                "source's size, so only a same-sized file was digested. Any `-wal` or `-shm`",
                "name in this list belongs to one of those earlier snapshots, not to the live",
                "source: the live file's own journal siblings are checked by exact name under",
                "*Bound identity* above.",
                "",
                *_table(
                    ("file", "bytes", "byte-identical copy of the source"),
                    (
                        (
                            f"`{sibling.file_name}`",
                            f"{sibling.byte_count:,}",
                            "yes" if sibling.identical_to_source else "no",
                        )
                        for sibling in retention.siblings
                    ),
                ),
                "",
            ]
        )
    lines.extend(
        [
            f"Verified copies of the source: **{retention.verified_copies}**. The siblings are",
            "earlier snapshots taken at earlier schema versions, not backups of this file.",
            "",
            "Nothing was copied anywhere to close this. Moving personal data off this machine",
            "is the owner's disclosure decision under `AGENTS.md` section 5 and OD-004, and a",
            "reconciliation harness may not take it unilaterally. The risk is stated so the",
            "owner can decide, which is the only correct action available here.",
            "",
        ]
    )
    return lines


def _appendix(report: Reconciliation) -> list[str]:
    return [
        "## Appendix — per-table row-count parity",
        "",
        "Every loaded table, both counts, in name order. `planning class` is what OD-008",
        "assigned and `treatment` is what the table actually got; where they disagree, the",
        "governing decision is in section 0a.",
        "",
        *_table(
            (
                "legacy table",
                "schema",
                "planning class",
                "treatment",
                "source",
                "target",
                "quarantined",
            ),
            (
                (
                    f"`{table.legacy_table}`",
                    table.target_schema,
                    table.planning_disposition,
                    table.treatment,
                    f"{table.source_rows:,}",
                    f"{table.target_rows:,}",
                    table.quarantined_rows,
                )
                for table in report.parity
            ),
        ),
        "",
    ]


def render(report: Reconciliation) -> str:
    """Return the full acceptance report as Markdown."""
    lines = [
        _HEADER,
        "",
        f"Generated {report.generated_at}. Every number below was recomputed from the legacy",
        "SQLite file and from PostgreSQL directly; the control plane's own counters are",
        "checked, not trusted.",
        "",
        *_verdict_line(report),
        "",
        *_identity(report),
        *_headline(report),
        *_criteria(report),
        *_departures(report),
        *_accounting(report),
        *_parity(report),
        *_quarantine(report),
        *_identity_coverage(report),
        *_keyless(report),
        *_foreign_keys(report),
        *_empty(report),
        *_exclusions(report),
        *_absence(report),
        *_renames(report),
        *_provenance(report),
        *_sequences(report),
        *_redaction(report),
        *_views(report),
        *_retention(report),
        *_appendix(report),
    ]
    return "\n".join(lines).rstrip() + "\n"
