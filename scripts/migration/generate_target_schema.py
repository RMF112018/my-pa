"""Regenerate the target-schema SQL the Alembic revisions apply.

Reads the source profile (built by `profile_source.py`) and the committed
disposition registry, and writes six SQL files under `migrations/sql/`: the
upgrade and downgrade halves of the table, index, and foreign-key steps. The
statements are deterministic, so re-running this on the same inputs produces a
byte-identical result and any diff is a real schema change.

It also writes `migrations/data/identifier_map.json`, every identifier the
63-byte budget or the neutral-naming rule forced the generator to rename. The
control-plane revision seeds `migration_control.identifier_map` from that file,
so a reader who queries for a legacy name finds the mapping (OD-013, OD-024).

    python scripts/migration/generate_target_schema.py \\
        --profile <scratch>/source_profile.json \\
        --registry migrations/data/disposition_registry.json \\
        --sql-dir migrations/sql
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from my_pa.infrastructure.migration.generator import GeneratedSchema, generate
from my_pa.infrastructure.migration.source import load_profile, load_registry
from my_pa.infrastructure.migration.sql_files import write_statements

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPOSITORY_ROOT / "migrations" / "data" / "disposition_registry.json"
DEFAULT_SQL_DIR = REPOSITORY_ROOT / "migrations" / "sql"
DEFAULT_DATA_DIR = REPOSITORY_ROOT / "migrations" / "data"


def write_sql(schema: GeneratedSchema, sql_dir: Path) -> None:
    write_statements(sql_dir / "target_tables.up.sql", schema.create_tables)
    write_statements(sql_dir / "target_tables.down.sql", schema.drop_tables)
    write_statements(sql_dir / "target_indexes.up.sql", schema.create_indexes)
    write_statements(sql_dir / "target_indexes.down.sql", schema.drop_indexes)
    write_statements(sql_dir / "target_foreign_keys.up.sql", schema.add_foreign_keys)
    write_statements(sql_dir / "target_foreign_keys.down.sql", schema.drop_foreign_keys)


def write_identifier_map(schema: GeneratedSchema, data_dir: Path) -> Path:
    path = data_dir / "identifier_map.json"
    document = {
        "record_type": "TARGET_IDENTIFIER_MAP",
        "renames": [
            {
                "original": rename.original,
                "shortened": rename.shortened,
                "object_kind": rename.object_kind,
                "owner": rename.owner,
            }
            for rename in schema.report.renames
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True, help="source profile JSON")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--sql-dir", type=Path, default=DEFAULT_SQL_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    schema = generate(load_profile(args.profile), load_registry(args.registry))
    write_sql(schema, args.sql_dir)
    identifier_map = write_identifier_map(schema, args.data_dir)

    report = schema.report
    print(f"tables            {len(schema.create_tables):5d}")
    for name, count in sorted(report.tables_by_schema.items()):
        print(f"  {name:18s}{count:5d}")
    print(f"columns           {report.column_count:5d}")
    print(f"check constraints {report.checks_emitted:5d} ({len(report.dropped_checks)} dropped)")
    print(f"boolean columns   {len(report.boolean_promotions):5d}")
    print(f"identity columns  {len(report.identity_columns):5d}")
    print(f"surrogate keys    {len(report.surrogate_key_tables):5d}")
    print(
        f"foreign keys      {report.foreign_key_count:5d} "
        f"({len(report.skipped_foreign_keys)} skipped)"
    )
    print(
        f"indexes           {report.index_count:5d} "
        f"({report.unique_index_count} unique, {report.partial_index_count} partial, "
        f"{report.expression_index_count} expression)"
    )
    print(f"renamed identifiers {len(report.renames):3d}")
    print(f"wrote SQL to {args.sql_dir}")
    print(f"wrote {identifier_map.name} to {args.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
