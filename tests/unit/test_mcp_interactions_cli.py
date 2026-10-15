"""`apps/cli/mcp_interactions.py` without a database (FAST).

Argument parsing, the argument refusals that happen before any connection, the
local-operator refusal in `main`, and the rendering helpers. The engine handed
to every runtime here raises if it is touched, so each refusal below is proven
to come before the database rather than from it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Final, NoReturn

import apps.cli.mcp_interactions as cli
import pytest
from apps.cli.mcp_interactions import (
    DEFAULT_BATCH,
    DEFAULT_LIMIT,
    EXIT_REFUSED,
    InteractionRefusalError,
    Runtime,
    build_parser,
    parse_duration,
    parse_instant,
    record_document,
    record_lines,
    run_mcp_interactions,
    safe,
    summary_line,
)

from my_pa.infrastructure.persistence.mcp_interactions import (
    MAX_PAGE,
    MAX_PURGE_BATCH,
    OUTCOMES,
    Interaction,
)

NOW: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
BODY_MARKER: Final = "synthetic-body-marker-7f3a"


class _UntouchableEngine:
    """An engine whose every use is a test failure."""

    def connect(self) -> NoReturn:
        raise AssertionError("the database was reached")

    def begin(self) -> NoReturn:
        raise AssertionError("the database was reached")

    def dispose(self) -> None:
        return None


def _runtime() -> Runtime:
    return Runtime(engine=_UntouchableEngine(), clock=lambda: NOW)  # type: ignore[arg-type]


def _run(*argv: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = run_mcp_interactions(argv, _runtime(), out=lines.append)
    return code, lines


def _record(**overrides: object) -> Interaction:
    values: dict[str, object] = {
        "interaction_id": "mcpi_" + "0" * 32,
        "recorded_at": NOW,
        "started_at": NOW - timedelta(milliseconds=15),
        "latency_ms": 12.5,
        "http_method": "POST",
        "http_status": 200,
        "oauth_client_id": "client-synthetic-a",
        "principal_id": "prn_synthetic0001",
        "principal_kind": "operator",
        "mcp_session_id": None,
        "jsonrpc_method": "tools/call",
        "jsonrpc_id": "1",
        "tool_name": "invoke",
        "capability": "tasks.list",
        "correlation_id": None,
        "outcome": "ok",
        "error_code": None,
        "request_bytes": 64,
        "response_bytes": 128,
        "request_sha256": "a" * 64,
        "response_sha256": "b" * 64,
        "request_truncated": False,
        "response_truncated": False,
        "request_body": {"jsonrpc": "2.0", "params": {"note": BODY_MARKER}},
        "response_body": {"jsonrpc": "2.0", "result": {"content": []}},
        "request_body_text": None,
        "response_body_text": None,
        "request_headers": {"content-type": "application/json"},
        "diagnostics": {"is_error": False, "capture": {"redactions": 0}},
    }
    values.update(overrides)
    return Interaction(**values)  # type: ignore[arg-type]


# ---- parsing ------------------------------------------------------------------------


def test_the_four_subcommands_parse_with_their_defaults() -> None:
    parser = build_parser()
    assert parser.parse_args(["list"]).limit == DEFAULT_LIMIT
    show = parser.parse_args(["show", "mcpi_x", "--json"])
    assert (show.interaction_id, show.json) == ("mcpi_x", True)
    search = parser.parse_args(["search"])
    assert search.client is search.tool is search.capability is None
    assert search.since is search.last is search.until is search.outcome is None
    purge = parser.parse_args(["purge"])
    assert (purge.dry_run, purge.batch_size) == (False, DEFAULT_BATCH)


def test_search_parses_every_filter() -> None:
    args = build_parser().parse_args(
        [
            "search",
            "--client",
            "c",
            "--tool",
            "t",
            "--capability",
            "k",
            "--correlation-id",
            "r",
            "--last",
            "2h",
            "--until",
            "2026-10-11T00:00:00Z",
            "--outcome",
            "tool_error",
            "--limit",
            "7",
        ]
    )
    assert (args.client, args.tool, args.capability, args.correlation_id) == ("c", "t", "k", "r")
    assert (args.last, args.until, args.outcome, args.limit) == (
        "2h",
        "2026-10-11T00:00:00Z",
        "tool_error",
        7,
    )


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["unknown"],
        ["show"],
        ["search", "--since", "2026-10-11T00:00:00Z", "--last", "1h"],
        ["search", "--outcome", "not_an_outcome"],
        ["purge", "--batch-size", "many"],
        ["purge", "--retention-days", "1"],
        ["list", "--limit", "ten"],
    ],
    ids=lambda value: " ".join(value) or "<empty>",
)
def test_argparse_rejects_a_malformed_command_line(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        build_parser().parse_args(argv)
    assert exited.value.code == 2


def test_the_outcome_choices_are_the_store_vocabulary() -> None:
    search = next(
        action
        for action in build_parser()._subparsers._group_actions[0].choices["search"]._actions  # type: ignore[union-attr]
        if action.dest == "outcome"
    )
    assert set(search.choices) == set(OUTCOMES)


def test_purge_offers_no_way_to_shorten_retention() -> None:
    purge = build_parser()._subparsers._group_actions[0].choices["purge"]  # type: ignore[union-attr]
    options = {option for action in purge._actions for option in action.option_strings}
    assert options == {"-h", "--help", "--dry-run", "--batch-size"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [("30s", timedelta(seconds=30)), ("15m", timedelta(minutes=15)), ("2d", timedelta(days=2))],
)
def test_durations_parse(text: str, expected: timedelta) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "0h", "-1h", "1w", "1.5h", "h", "1 h", "123456d"])
def test_malformed_durations_are_refused(text: str) -> None:
    with pytest.raises(InteractionRefusalError):
        parse_duration(text)


def test_instants_need_an_offset() -> None:
    assert parse_instant("2026-10-11T12:00:00Z", "--since") == NOW
    assert parse_instant("2026-10-11T14:00:00+02:00", "--since") == NOW
    with pytest.raises(InteractionRefusalError, match="explicit offset"):
        parse_instant("2026-10-11T12:00:00", "--since")
    with pytest.raises(InteractionRefusalError, match="ISO 8601"):
        parse_instant("yesterday", "--until")


# ---- refusals before the database -------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["list", "--limit", "0"],
        ["list", "--limit", str(MAX_PAGE + 1)],
        ["show", "not-an-id"],
        ["show", "mcpi_" + "G" * 32],
        ["search", "--since", "2026-10-11T12:00:00"],
        ["search", "--last", "1w"],
        ["search", "--since", "2026-10-11T12:00:00Z", "--until", "2026-10-11T12:00:00Z"],
        ["search", "--last", "1h", "--until", "2026-10-10T00:00:00Z"],
        ["search", "--limit", "0"],
        ["purge", "--batch-size", "0"],
        ["purge", "--batch-size", str(MAX_PURGE_BATCH + 1)],
    ],
    ids=lambda value: " ".join(value),
)
def test_a_malformed_argument_is_refused_before_the_database(argv: list[str]) -> None:
    code, lines = _run(*argv)
    assert code == EXIT_REFUSED
    assert len(lines) == 1
    assert lines[0].startswith("refused")


def test_main_refuses_outside_a_local_operator_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The `knowledge_source_profiles.py` refusal: exit 1, one line, no engine built."""
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: SimpleNamespace(admissible_client_principal_id=lambda: None),
    )

    def _no_engine(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("an engine was built for a refused process")

    monkeypatch.setattr(cli, "create_database_engine", _no_engine)
    for argv in (["list"], ["purge"], ["show", "mcpi_" + "0" * 32]):
        assert cli.main(argv) == EXIT_REFUSED
        printed = capsys.readouterr()
        assert printed.out.startswith("refused")
        assert "AUTH_MODE" in printed.out
        assert printed.err == ""


def test_main_disposes_the_engine_it_built(monkeypatch: pytest.MonkeyPatch) -> None:
    disposed: list[bool] = []

    class _Engine(_UntouchableEngine):
        def dispose(self) -> None:
            disposed.append(True)

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: SimpleNamespace(
            admissible_client_principal_id=lambda: "prn_synthetic0001",
            parsed_database_url=lambda: "postgresql+psycopg://synthetic/none",
        ),
    )
    monkeypatch.setattr(cli, "create_database_engine", lambda *_a, **_k: _Engine())
    assert cli.main(["list", "--limit", "0"]) == EXIT_REFUSED
    assert disposed == [True]


# ---- rendering -----------------------------------------------------------------------


def test_safe_escapes_terminal_active_characters_and_keeps_layout() -> None:
    hostile = "a\x1b[31mred\x07\x9b\u202eevil\u2028x\ty\nz\x7f"
    rendered = safe(hostile)
    for character in ("\x1b", "\x07", "\x9b", "\u202e", "\u2028", "\x7f"):
        assert character not in rendered
    assert "\\u001b" in rendered and "\\u202e" in rendered
    assert "\t" in rendered and "\n" in rendered
    assert safe("plain ascii, ümlaut") == "plain ascii, ümlaut"


def test_a_summary_line_carries_no_body() -> None:
    line = summary_line(_record())
    assert BODY_MARKER not in line
    for fragment in (
        "mcpi_" + "0" * 32,
        "client=client-synthetic-a",
        "method=POST:tools/call",
        "tool=invoke",
        "capability=tasks.list",
        "outcome=ok",
        "error=-",
        "status=200",
        "latency_ms=12.5",
        "bytes=64/128",
    ):
        assert fragment in line


def test_a_summary_line_escapes_a_hostile_client_id() -> None:
    line = summary_line(_record(oauth_client_id="evil\x1b]0;title\x07"))
    assert "\x1b" not in line and "\x07" not in line


def test_the_full_rendering_shows_bodies_headers_and_diagnostics() -> None:
    text = "\n".join(
        record_lines(
            _record(
                response_body=None,
                response_body_text='{"partial": "\x1b[2J',
                response_truncated=True,
            )
        )
    )
    assert BODY_MARKER in text
    assert "request_headers:" in text and "diagnostics:" in text
    assert "response_body       -" in text
    assert "response_truncated  True" in text
    assert "\x1b" not in text


def test_the_json_rendering_round_trips_every_column() -> None:
    record = _record()
    document = json.loads(safe(json.dumps(record_document(record), ensure_ascii=False)))
    assert document["recorded_at"] == "2026-10-11T12:00:00+00:00"
    assert document["request_body"]["params"]["note"] == BODY_MARKER
    assert set(document) == set(Interaction.__dataclass_fields__)
