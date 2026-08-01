"""Produce the Phase 10 reconciliation evidence.

    MY_PA_DATABASE_URL=... PGPASSWORD=... \\
        .venv/bin/python scripts/migration/reconcile.py \\
            --source <legacy>.sqlite \\
            --output evidence/migration/phase-10-reconciliation

Writes `RECONCILIATION.md` and `reconciliation.json`. Re-runnable: it reads the
source read-only, reads PostgreSQL through ordinary queries, validates nothing,
and writes only its two output files.

The redaction scan covers the whole evidence tree and the migration
documentation. Because its own output lives inside that tree, the scan a given
run reports is the state of the tree as the run found it; the run then re-scans
the two files it just wrote and refuses to exit clean if either is dirty. Run it
twice for a report whose scan section covers the report.

Exit status is 0 when the acceptance verdict is PASS and 1 otherwise, so a
failing reconciliation cannot be mistaken for a passing one by a shell.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from my_pa.bootstrap.settings import load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.migration import reconciliation, reconciliation_report, redaction
from my_pa.infrastructure.migration.source import load_registry

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPOSITORY_ROOT / "migrations" / "data" / "disposition_registry.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "evidence" / "migration" / "phase-10-reconciliation"

#: OD-004 makes a redaction scan over the evidence tree a Phase 10 acceptance
#: check. The migration documentation is included because it is written by the
#: same agents from the same material.
SCAN_ROOTS = ("evidence", "docs/migration")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help="path to the legacy SQLite database"
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    registry = load_registry(args.registry)
    document = json.loads(args.registry.read_text(encoding="utf-8"))
    scan = redaction.scan((REPOSITORY_ROOT / root for root in SCAN_ROOTS), base=REPOSITORY_ROOT)

    engine = create_database_engine(load_settings().database_url)
    try:
        report = reconciliation.reconcile(engine, args.source, registry, document, scan)
    finally:
        engine.dispose()

    args.output.mkdir(parents=True, exist_ok=True)
    markdown = args.output / "RECONCILIATION.md"
    machine = args.output / "reconciliation.json"
    markdown.write_text(reconciliation_report.render(report), encoding="utf-8")
    machine.write_text(
        json.dumps(reconciliation.as_dict(report), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    written = redaction.scan((markdown, machine), base=REPOSITORY_ROOT)
    for criterion in report.criteria:
        print(f"{criterion.status:<12s} {criterion.identifier}  {criterion.detail}")
    print(f"verdict     {report.verdict}")
    print(f"wrote       {markdown.relative_to(REPOSITORY_ROOT)}")
    print(f"wrote       {machine.relative_to(REPOSITORY_ROOT)}")
    print(f"output scan {len(written.findings)} findings over {written.files_scanned} files")
    for finding in written.findings:
        print(f"  {finding.path}:{finding.line} {finding.pattern}")
    return 0 if report.verdict == reconciliation.PASSED and written.clean else 1


if __name__ == "__main__":
    sys.exit(main())
