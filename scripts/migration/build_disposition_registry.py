"""Build the migration disposition registry from the plan matrix and the live source.

The plan's disposition matrix says what should happen to each legacy object. This
script reconciles that against what the source database actually contains at
schema version 128, resolves each row to a target treatment (OD-025) and a target
PostgreSQL schema (OD-007), and records the plan rows with no matching source
object as a named, expected gap (OD-001).

Each row keeps its original `planning_disposition` alongside the treatment it
resolves to, so where OD-025 departs from the plan the deviation is visible in
the artefact rather than only in the register.

READ-ONLY. The source is opened with `immutable=1` and is never written to. The
output holds object names, dispositions, and counts -- no row content.

    python scripts/migration/build_disposition_registry.py \\
        --matrix <plan>/03_COMPLETE-LEGACY-TABLE-DISPOSITION-MATRIX.csv \\
        --source <legacy>.sqlite \\
        --output migrations/data/disposition_registry.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

SOURCE_SCHEMA_VERSION = 128

#: OD-025: what each planning disposition means for the target database.
#:
#: Three of these differ from the plan, because the plan's reasons did not hold.
#: `REBUILD_AND_VALIDATE` assumed an application that would recompute the derived
#: values; that application is the legacy one and it is not being ported, so
#: "rebuild later" meant "empty forever" for 40% of the corpus. The data is
#: loaded and the class is marked rebuildable, which keeps a future recompute
#: available without betting the rows on it. `ARCHIVE_LEGACY_SOURCE_ONLY` assumed
#: the legacy file stays queryable; under OD-003 it is a retired 4.4 GB archive
#: nothing opens, so leaving records only there contradicts PostgreSQL being
#: canonical.
TREATMENTS: dict[str, str] = {
    "MIGRATE_DATA": "SCHEMA_AND_DATA",
    "MIGRATE_SCHEMA_EMPTY": "SCHEMA_ONLY_ASSERT_EMPTY",
    "MIGRATE_PROVENANCE_ONLY": "PROVENANCE_ONLY",
    "REBUILD_AND_VALIDATE": "SCHEMA_AND_DATA_REBUILDABLE",
    "ARCHIVE_LEGACY_SOURCE_ONLY": "SCHEMA_AND_DATA",
    # Unchanged, and correct. Operational state is queue cursors and sync
    # watermarks: carrying them forward would make a fresh system believe it had
    # already done work it has not, so empty is the right value rather than a
    # shortfall -- with the five provenance exceptions named below (OD-028). A
    # superseded table has a newer authority, and loading both would leave two
    # candidate sources of truth for one fact.
    "REINITIALIZE_OPERATIONAL_STATE": "SCHEMA_ONLY_EMPTY_BY_DESIGN",
    "DO_NOT_MIGRATE_EMPTY_OR_OBSOLETE": "NOT_CREATED",
    "REPLACED_BY_NEWER_AUTHORITATIVE_TABLE": "NOT_CREATED_SUPERSEDED",
}

#: OD-028. Five named exceptions to `REINITIALIZE_OPERATIONAL_STATE`.
#:
#: The class-level reason for emptying operational state is sound and still
#: applies to the other 85 tables: a fresh system must not believe it has already
#: processed work it has not. It does not apply to these five, because nothing
#: reads them as a queue, a cursor, or a watermark. They are the provenance
#: records naming which computation produced the derived rows OD-025 decided to
#: load — so withholding them does not preserve a clean slate, it orphans 194,760
#: loaded rows against parents that exist in the source and leaves 6% of the
#: corpus unable to say where it came from.
#:
#: This is a list of five names, deliberately, and not a rule inferred from
#: shape. A `_runs` suffix is not evidence of anything; being the parent of a
#: loaded derived table is. Do not widen it without measuring the same way.
OPERATIONAL_STATE_PROVENANCE_EXCEPTIONS = frozenset(
    {
        "procore_live_sync_runs",
        "schedule_cpm_runs",
        "schedule_cost_mapping_runs",
        "schedule_quality_evaluation_runs",
        "forecast_runs",
    }
)

#: OD-025 splits the deferred class by what was actually being deferred.
#: Operational metadata is ordinary owner-owned data and migrating it is not
#: activating a product feature (OP-PROD-001). Anything carrying content or
#: personal identity is what the privacy gate meant, and is neither created nor
#: loaded.
DEFERRED_DISPOSITION = "DEFER_PENDING_PRODUCT_OR_PRIVACY_DECISION"
DEFERRED_LOADABLE_CLASS = "NONSENSITIVE_OR_OPERATIONAL_METADATA"


def treatment_for(legacy_object: str, planning_disposition: str, sensitive_data_class: str) -> str:
    """Resolve one plan row to its target treatment."""
    if legacy_object in OPERATIONAL_STATE_PROVENANCE_EXCEPTIONS:
        return "SCHEMA_AND_DATA"
    if planning_disposition == DEFERRED_DISPOSITION:
        if sensitive_data_class == DEFERRED_LOADABLE_CLASS:
            return "SCHEMA_AND_DATA"
        return "NOT_CREATED_PRIVACY_GATED"
    return TREATMENTS[planning_disposition]


#: OD-007: one PostgreSQL schema per domain area. Cross-cutting, bridge, and
#: unscoped tables go to `core`.
SCHEMAS: dict[str, str] = {
    "PROCORE": "procore",
    "EMAIL": "email",
    "CALENDAR": "calendar",
    "CONTACTS": "contacts",
    "FINANCIAL": "financial",
    "SCHEDULE": "schedule",
    "CONSTRUCTION_ADJACENT": "construction",
    "CROSS_CUTTING": "core",
    "SOURCE_BRIDGE": "core",
    "OTHER_LINKED": "core",
    "UNSCOPED": "core",
}

#: OD-010: FTS5 shadow tables are a SQLite index format, not data.
FTS_SHADOW_SUFFIXES = (
    "_data",
    "_idx",
    "_content",
    "_docsize",
    "_config",
    "_segments",
    "_segdir",
    "_stat",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True, help="disposition matrix CSV")
    parser.add_argument("--source", type=Path, required=True, help="legacy SQLite file")
    parser.add_argument("--output", type=Path, required=True, help="registry JSON to write")
    args = parser.parse_args()

    connection = sqlite3.connect(f"file:{args.source}?immutable=1", uri=True)
    try:
        master = list(
            connection.execute(
                "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        )
    finally:
        connection.close()
    live = {name: sql or "" for name, _, sql in master}
    kinds = {name: kind for name, kind, _ in master}

    virtual = {name for name, sql in live.items() if "virtual table" in sql.lower()}
    shadow = {
        name
        for name in live
        if any(name.endswith(sfx) and name[: -len(sfx)] in virtual for sfx in FTS_SHADOW_SUFFIXES)
    }

    with args.matrix.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    entries: list[dict[str, Any]] = []
    absent: list[dict[str, str]] = []
    for row in rows:
        name = row["legacy_object"]
        disposition = row["planning_disposition"]
        if name not in live:
            absent.append(
                {
                    "legacy_object": name,
                    "planning_disposition": disposition,
                    "reason": "ABSENT_FROM_SOURCE_AT_SCHEMA_128",
                }
            )
            continue
        treatment = treatment_for(name, disposition, row["sensitive_data_class"])
        if name in virtual or name in shadow:
            treatment = "NOT_CREATED_FTS_REBUILT_IN_POSTGRES"
        entries.append(
            {
                "legacy_object": name,
                "object_type": kinds[name],
                "primary_domain": row["primary_domain"],
                "target_schema": SCHEMAS.get(row["primary_domain"], "core"),
                "planning_disposition": disposition,
                "target_treatment": treatment,
                "phase_id": row["phase_id"],
                "ordering_group": row["ordering_group"],
                "sensitive_data_class": row["sensitive_data_class"],
                "identity_mapping": row["identity_mapping"],
                "reconciliation_method": row["reconciliation_method"],
                "is_fts_virtual": name in virtual,
                "is_fts_shadow": name in shadow,
                "plan_row_count": row["row_count"],
            }
        )

    registry = {
        "record_type": "MIGRATION_DISPOSITION_REGISTRY",
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "plan_object_count": len(rows),
        "source_object_count": len(live),
        "absent_from_source": absent,
        "entries": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    counts = Counter(entry["target_treatment"] for entry in entries)
    print(f"plan rows {len(rows)} | in source {len(entries)} | absent {len(absent)}")
    for treatment, count in sorted(counts.items()):
        print(f"  {treatment:42s} {count:4d}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
