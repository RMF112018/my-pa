"""Report the state of the relationship-intelligence entity plane.

    MY_PA_DATABASE_URL=... PGPASSWORD=... \\
        .venv/bin/python scripts/inspect_entity_plane.py --principal prn_...

READ-ONLY. It issues `SELECT` and `count(*)` and nothing else: no `INSERT`, no
`UPDATE`, no `DDL`, and no capability invocation. Running it cannot change what
it reports.

**It prints no personal data.** Every figure is a count, a status name, or an
opaque identifier. Names, email addresses, alias text and observed values are
never selected — `AGENTS.md` section 5 keeps contact details out of logs, and an
operator report is a log. The one place a reader might expect a name is the
unresolved-mention queue, and it deliberately shows identifiers and counts
instead: the whole point of that queue is that nobody has decided who those
references are, so printing them would be printing unattributed personal data.

**A Principal is required and never inferred.** `--principal` has no default.
The plane is partitioned per Principal, and a report that quietly aggregated
across all of them would be the cross-Principal read the partition exists to
prevent — so the argument is mandatory and the query is scoped by it.

Exit status is 0 when the report was produced and 1 when it could not be, so a
shell cannot mistake an unreachable database for an empty plane.

The engine is built on `Settings.parsed_database_url()` — the reading that was
validated, not a second reading of the same characters — and states its own
`statement_timeout_ms`, the same thirty seconds every other operator entry point
in this repository states. A report is a thing somebody is waiting on, so a
count over a plane larger than the one this was measured against should fail
rather than hold a connection until the terminal is closed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Final

from sqlalchemy import Engine, text

from my_pa.bootstrap.settings import load_settings
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.relationship.governance import UNDECIDED_PROPOSAL_STATES
from my_pa.infrastructure.database.engine import create_database_engine

SCHEMA: Final = "knowledge"

#: `(label, table)` for the plain per-table counts. Written out rather than
#: derived from the metadata, so this report covers the plane it was written for
#: and a new table is a deliberate addition here rather than a silent one.
_COUNTED: Final[tuple[tuple[str, str], ...]] = (
    ("entities", "entities"),
    ("aliases", "entity_aliases"),
    ("external_identifiers", "entity_external_identifiers"),
    ("assignments", "entity_assignments"),
    ("relationships", "entity_relationships"),
    ("observations", "entity_observations"),
    ("proposals", "entity_proposals"),
    ("merges", "entity_merge_records"),
)


def _count(engine: Engine, table: str, principal_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.{table} "  # noqa: S608 - fixed table list
                    "WHERE principal_id = :principal_id"
                ),
                {"principal_id": principal_id},
            ).scalar_one()
        )


def _grouped(engine: Engine, table: str, column: str, principal_id: str) -> dict[str, int]:
    """`column` value to row count, for one Principal. Values are closed-set names."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT {column}, count(*) FROM {SCHEMA}.{table} "  # noqa: S608 - fixed list
                "WHERE principal_id = :principal_id GROUP BY 1 ORDER BY 1"
            ),
            {"principal_id": principal_id},
        ).all()
    return {str(value): int(count) for value, count in rows}


def _unresolved_mentions(engine: Engine, principal_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.entity_observations "  # noqa: S608
                    "WHERE principal_id = :principal_id AND entity_id IS NULL"
                ),
                {"principal_id": principal_id},
            ).scalar_one()
        )


def _open_proposals(engine: Engine, principal_id: str) -> list[dict[str, Any]]:
    """Proposals awaiting a decision, as identifiers and kinds.

    No payload and no observed value: a proposal's payload names the entities it
    would join, and an operator deciding one reads it through a reviewed surface
    rather than out of a report.

    **And no `proposed_by`.** It reads like provenance, but the column is free
    text the proposing caller supplies -- "resolver" today, and a person's name
    or address the moment anything records who asked for the change. This
    module's standing claim is that every figure it prints is a count, a
    closed-set status name, or an opaque identifier, and one free-text column is
    all it takes for that to stop being true. An operator who needs to know who
    proposed something reads the proposal, by identifier, through the reviewed
    surface -- exactly as they do for the payload.

    **"Awaiting a decision" is derived from the domain, not spelled here.** This
    read matched `state = 'proposed'` as a literal until `WP-RI-B-05` made
    `initial_state_for` write `needs_review` for every kind a person has to look
    at -- so an operator asking what was waiting on them was answered with the
    subset that was *not*, and a plane holding nothing but review-requiring
    proposals reported an empty queue. It under-reported in silence, which is
    the failure mode worse than the report refusing to run: an operator reads
    "no open proposals" and stops looking.

    `UNDECIDED_PROPOSAL_STATES` is the tuple `EntityGovernanceService.open_proposals`
    reads, so the report and the service answer one question, and a state added
    to it reaches this report on the day it is added rather than when somebody
    notices. The values are bound rather than interpolated: they are a closed
    set from this repository's own domain and could be pasted in safely, but a
    query that builds a predicate out of values is a shape this file should not
    contain even once.
    """
    states = {
        f"state_{index}": state.value for index, state in enumerate(UNDECIDED_PROPOSAL_STATES)
    }
    placeholders = ", ".join(f":{name}" for name in states)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT proposal_id, kind, proposed_at "  # noqa: S608
                f"FROM {SCHEMA}.entity_proposals "
                f"WHERE principal_id = :principal_id AND state IN ({placeholders}) "
                "ORDER BY proposed_at, proposal_id"
            ),
            {"principal_id": principal_id, **states},
        ).all()
    return [
        {
            "proposal_id": str(row.proposal_id),
            "kind": str(row.kind),
            "proposed_at": row.proposed_at.isoformat(),
        }
        for row in rows
    ]


def report(engine: Engine, principal_id: str) -> dict[str, Any]:
    """Everything this script knows about one Principal's entity plane."""
    return {
        "principal_id": principal_id,
        "counts": {label: _count(engine, table, principal_id) for label, table in _COUNTED},
        "entities_by_status": _grouped(engine, "entities", "status", principal_id),
        "entities_by_type": _grouped(engine, "entities", "entity_type", principal_id),
        "observations_by_kind": _grouped(engine, "entity_observations", "kind", principal_id),
        "proposals_by_state": _grouped(engine, "entity_proposals", "state", principal_id),
        "unresolved_mentions": _unresolved_mentions(engine, principal_id),
        "open_proposals": _open_proposals(engine, principal_id),
    }


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--principal",
        required=True,
        help="the prn_... identifier whose plane to report. No default: the plane "
        "is partitioned, and a report across all of them would be a "
        "cross-Principal read.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _parse(sys.argv[1:] if argv is None else argv)
    try:
        validate_identifier(arguments.principal, IdKind.PRINCIPAL)
    except InvalidIdentifierError as error:
        print(f"not a Principal identifier: {error}", file=sys.stderr)
        return 1

    if not os.environ.get("MY_PA_DATABASE_URL"):
        print("MY_PA_DATABASE_URL is not set", file=sys.stderr)
        return 1

    engine = create_database_engine(
        load_settings().parsed_database_url(), statement_timeout_ms=30_000
    )
    try:
        print(json.dumps(report(engine, arguments.principal), indent=2, sort_keys=True))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point
    raise SystemExit(main())
