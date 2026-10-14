"""Operator command: read and purge the remote MCP interaction log.

    .venv/bin/python apps/cli/mcp_interactions.py list [--limit N]
    .venv/bin/python apps/cli/mcp_interactions.py show mcpi_... [--json]
    .venv/bin/python apps/cli/mcp_interactions.py search \\
        [--client ID] [--tool NAME] [--capability NAME] [--correlation-id ID] \\
        [--since ISO8601 | --last DURATION] [--until ISO8601] [--outcome O] [--limit N]
    .venv/bin/python apps/cli/mcp_interactions.py purge [--dry-run] [--batch-size N]

**What it reads.** `observability.mcp_interactions`, the log the remote gateway's
capture middleware writes when `MY_PA_MCP_INTERACTION_LOG_ENABLED` is true
(`ops/runbooks/mcp-interaction-log.md`). Every row was redacted before it was
stored: credential-bearing headers are never kept, and credential-shaped values
in bodies are already `[REDACTED]`. `list` and `search` print summary lines and
never a body. `show` prints one full record, bodies included -- showing them to
the operator is the purpose of storing them (the operator's 2026-10-11 risk
acceptance). Every string this command prints has control, C1 and bidirectional
formatting characters escaped, so a stored body cannot drive the terminal.

**Configuration, not a capability.** This command builds no
`ApplicationService`, imports neither `my_pa.application` nor `my_pa.adapters`,
writes no audit event, and is registered in
`tests/architecture/test_operator_commands_are_not_capabilities.py` with the
store functions it may name. It runs only in a process configured for the local
operator (the `knowledge_source_profiles.py` refusal), because the log holds
every client's traffic and has no Principal partition.

**Purge** mirrors `knowledge_source_profiles.py drain-revalidation`: one bounded
batch per invocation in one committed transaction, then `deleted=<n>
remaining=<n>`; exit 3 while expired rows remain (re-run), 0 when none do.
Retention is the fixed 14 days the database trigger enforces; there is no
option to shorten it. `--dry-run` deletes nothing, reports every expired row as
remaining, and exits 0 so a re-run loop never spins on it.

Exit status: 0 success; 1 refused (no local-operator Principal, a malformed
argument, an unknown interaction, a database error -- named by type, never by
URL); 2 a command line argparse rejects; 3 purge has work remaining.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.mcp_interactions import (
    MAX_PAGE,
    MAX_PURGE_BATCH,
    OUTCOMES,
    RETENTION_DAYS,
    get_interaction,
    list_interactions,
    purge_expired,
    search_interactions,
)

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1
#: Purge is resumable: exit 3 means "re-run, expired rows remain".
EXIT_REMAINING: Final = 3

DEFAULT_LIMIT: Final = 50
DEFAULT_BATCH: Final = 1_000

_INTERACTION_ID: Final = re.compile(r"\Amcpi_[0-9a-f]{32}\Z")
_DURATION: Final = re.compile(r"\A([1-9][0-9]{0,4})([smhd])\Z")
_UNITS: Final = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
#: C0 (except newline and tab), DEL, C1, and bidirectional/line-separator
#: formatting characters. Each is printed as a `\\uXXXX` escape.
_UNSAFE: Final = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069]"
)


class InteractionRefusalError(ValueError):
    """An argument this command refuses. Names the option, never a stored value."""


def safe(text: str) -> str:
    """`text` with every terminal-active character escaped as `\\uXXXX`.

    Applied to everything printed. Inside JSON output the escape is itself a
    valid JSON string escape, so `--json` stays parseable.
    """
    return _UNSAFE.sub(lambda match: f"\\u{ord(match.group()):04x}", text)


def parse_instant(value: str, option: str) -> datetime:
    """An ISO 8601 instant with an explicit offset (`Z` or `+hh:mm`)."""
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        raise InteractionRefusalError(f"{option} is not an ISO 8601 instant") from None
    if instant.tzinfo is None:
        raise InteractionRefusalError(f"{option} needs an explicit offset, e.g. Z or +00:00")
    return instant


def parse_duration(value: str) -> timedelta:
    """`<n>s`, `<n>m`, `<n>h` or `<n>d`, n a positive integer."""
    match = _DURATION.fullmatch(value)
    if match is None:
        raise InteractionRefusalError("--last is <n>s, <n>m, <n>h or <n>d, n a positive integer")
    return timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})


def _limit(value: int) -> int:
    if not 1 <= value <= MAX_PAGE:
        raise InteractionRefusalError(f"--limit is 1..{MAX_PAGE}")
    return value


def _instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _or_dash(value: object) -> str:
    return "-" if value is None else safe(str(value))


def summary_line(summary: Any) -> str:  # noqa: ANN401 - a persistence record
    """One exchange, no body: identifiers, closed tokens, sizes and timings."""
    jsonrpc = _or_dash(summary.jsonrpc_method)
    return (
        f"{_instant(summary.recorded_at)}  {summary.interaction_id}  "
        f"client={_or_dash(summary.oauth_client_id)}  "
        f"method={safe(summary.http_method)}:{jsonrpc}  "
        f"tool={_or_dash(summary.tool_name)}  capability={_or_dash(summary.capability)}  "
        f"outcome={safe(summary.outcome)}  error={_or_dash(summary.error_code)}  "
        f"status={_or_dash(summary.http_status)}  latency_ms={summary.latency_ms:.1f}  "
        f"bytes={summary.request_bytes}/{summary.response_bytes}"
    )


def record_document(record: Any) -> dict[str, object]:  # noqa: ANN401 - a persistence record
    """Every column of one record, instants as UTC ISO 8601."""
    document: dict[str, object] = {}
    for column in fields(record):
        value = getattr(record, column.name)
        document[column.name] = _instant(value) if isinstance(value, datetime) else value
    return document


#: Columns `show` prints as an indented JSON block rather than on one line.
_BLOCK_COLUMNS: Final = frozenset(
    {"request_headers", "diagnostics", "request_body", "response_body"}
)
#: Columns holding redacted body text, printed as one JSON string literal.
_TEXT_COLUMNS: Final = frozenset({"request_body_text", "response_body_text"})


def record_lines(record: Any) -> list[str]:  # noqa: ANN401 - a persistence record
    """The human rendering of one full record."""
    lines: list[str] = []
    for name, value in record_document(record).items():
        if name in _BLOCK_COLUMNS:
            if value is None:
                lines.append(f"{name:<20s}-")
                continue
            lines.append(f"{name}:")
            rendered = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
            lines.extend(f"  {safe(line)}" for line in rendered.splitlines())
        elif name in _TEXT_COLUMNS:
            literal = "-" if value is None else json.dumps(value, ensure_ascii=False)
            lines.append(f"{name:<20s}{safe(literal)}")
        else:
            lines.append(f"{name:<20s}{_or_dash(value)}")
    return lines


# ---- the runtime -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Runtime:
    """What every subcommand runs against: one engine and one clock."""

    engine: Engine
    clock: Callable[[], datetime]


def _list(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    limit = _limit(args.limit)
    with runtime.engine.connect() as connection:
        summaries = list_interactions(connection, limit=limit)
    for summary in summaries:
        out(summary_line(summary))
    out(f"interactions {len(summaries)}")
    return EXIT_OK


def _show(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    if not _INTERACTION_ID.fullmatch(args.interaction_id):
        raise InteractionRefusalError("the interaction id is not an mcpi_ identifier")
    with runtime.engine.connect() as connection:
        record = get_interaction(connection, args.interaction_id)
    if record is None:
        out("refused           no interaction carries that identifier")
        return EXIT_REFUSED
    if args.json:
        out(safe(json.dumps(record_document(record), ensure_ascii=False)))
    else:
        for line in record_lines(record):
            out(line)
    return EXIT_OK


def _search(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    limit = _limit(args.limit)
    since = None if args.since is None else parse_instant(args.since, "--since")
    if args.last is not None:
        since = runtime.clock() - parse_duration(args.last)
    until = None if args.until is None else parse_instant(args.until, "--until")
    if since is not None and until is not None and since >= until:
        raise InteractionRefusalError("the window is empty: --since/--last is not before --until")
    with runtime.engine.connect() as connection:
        summaries = search_interactions(
            connection,
            client_id=args.client,
            tool=args.tool,
            capability=args.capability,
            correlation_id=args.correlation_id,
            since=since,
            until=until,
            outcome=args.outcome,
            limit=limit,
        )
    for summary in summaries:
        out(summary_line(summary))
    out(f"interactions {len(summaries)}")
    return EXIT_OK


def _purge(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    if not 1 <= args.batch_size <= MAX_PURGE_BATCH:
        raise InteractionRefusalError(f"--batch-size is 1..{MAX_PURGE_BATCH}")
    with runtime.engine.begin() as connection:
        result = purge_expired(connection, batch_size=args.batch_size, dry_run=args.dry_run)
    prefix = "dry_run " if args.dry_run else ""
    out(f"{prefix}retention_days={RETENTION_DAYS}")
    out(f"deleted={result.deleted} remaining={result.remaining}")
    if args.dry_run or result.remaining == 0:
        return EXIT_OK
    return EXIT_REMAINING


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp_interactions",
        description="Read and purge the remote MCP interaction log (operator only).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="the newest exchanges, one summary line each")
    listing.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"1..{MAX_PAGE}")
    show = commands.add_parser("show", help="one full record, redacted bodies included")
    show.add_argument("interaction_id", help="an mcpi_ identifier")
    show.add_argument("--json", action="store_true", help="one JSON object instead of text")
    search = commands.add_parser("search", help="exchanges matching every given filter")
    search.add_argument("--client", help="exact OAuth client id")
    search.add_argument("--tool", help="exact MCP tool name")
    search.add_argument("--capability", help="exact canonical capability name")
    search.add_argument("--correlation-id", help="exact ProblemDetail correlation id")
    window = search.add_mutually_exclusive_group()
    window.add_argument("--since", help="inclusive lower bound, ISO 8601 with an offset")
    window.add_argument("--last", help="the last <n>s/<n>m/<n>h/<n>d, from now")
    search.add_argument("--until", help="exclusive upper bound, ISO 8601 with an offset")
    search.add_argument("--outcome", choices=sorted(OUTCOMES))
    search.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"1..{MAX_PAGE}")
    purge = commands.add_parser(
        "purge", help=f"delete one batch of rows older than {RETENTION_DAYS} days"
    )
    purge.add_argument("--dry-run", action="store_true", help="count, delete nothing")
    purge.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH, help=f"1..{MAX_PURGE_BATCH}"
    )
    return parser


def _dispatch(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    match args.command:
        case "list":
            return _list(args, runtime, out)
        case "show":
            return _show(args, runtime, out)
        case "search":
            return _search(args, runtime, out)
        case "purge":
            return _purge(args, runtime, out)
        case unknown:  # pragma: no cover - argparse rejects an unknown command first
            raise SystemExit(f"unhandled command {unknown!r}")


def run_mcp_interactions(
    argv: Sequence[str],
    runtime: Runtime,
    *,
    out: Callable[[str], None] = print,
) -> int:
    """Parse and dispatch against `runtime`. A refusal is exit 1 and one line."""
    args = build_parser().parse_args(list(argv))
    try:
        return _dispatch(args, runtime, out)
    except ValueError as refusal:
        out(f"refused           {refusal}")
        return EXIT_REFUSED
    except SQLAlchemyError as failure:
        # The driver's message can name the endpoint; the type cannot.
        out(f"refused           database error ({type(failure).__name__})")
        return EXIT_REFUSED


def main(argv: list[str] | None = None) -> int:
    """Refuse outside a local-operator process, else run one subcommand.

    The same refusal as `knowledge_source_profiles.py`: no
    `admissible_client_principal_id()` means this process authenticates per
    request and a shell carries no credential, so nothing here may run.
    """
    arguments = sys.argv[1:] if argv is None else argv
    settings = load_settings()
    if settings.admissible_client_principal_id() is None:
        print(
            f"refused           {ENV_PREFIX}AUTH_MODE authenticates each request and a shell "
            "carries no credential, so there is no Principal to act for. Run this from a "
            "process configured for the local operator"
        )
        return EXIT_REFUSED
    runtime = Runtime(
        engine=create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000),
        clock=lambda: datetime.now(UTC),
    )
    try:
        return run_mcp_interactions(arguments, runtime)
    finally:
        runtime.engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
