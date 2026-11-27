"""`communications_ingest.py measure-context`, counts only (WP5-S6, design 3.12, ruling D16).

FAST tier. The command runs over the CLI test's fakes (`_Scene`: the fake
engine answers the identity queries only; the ingestion and communications
planes are the in-memory `IngestWorld`, backfilled with the synthetic
fixtures) and the real `MeetingContextMeasurement`, whose probe facts are a
fake that hands the fixtures' own participant addresses to the probes. The
candidate statement is canned with rows whose subject, sender, snippet and ids
are distinctive. A bound Project with a distinctive number links the probes.

Proved here:

* the output shape: one JSON object; the four latency shapes (1 and N
  Meetings, PULSE off and on) with p50, p95, maximum and statements; per probe
  the input counts, `missing[]`, the tiers and reasons, coverage and `pulse`;
  the self-address, bridge and `quarantined_identity_kind_mismatch` counts;
* **the leak test (prove-red m19):** no fixture address or subject, no canned
  subject, sender, snippet or id, no Project number or id, no probe title,
  identifier or id appears anywhere in the output;
* the refusals: a database or Alembic head mismatch refuses `target_mismatch`
  before anything is measured; out-of-range bounds are usage errors (exit 2).

The database run is `tests/database/test_communications_measure_context_cli.py`.
Every value is synthetic.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast
from unittest.mock import MagicMock

import pytest
from apps.cli import communications_ingest as cli
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from my_pa.application.meeting_context_measure import (
    PROBE_TITLE,
    MeetingContextMeasurement,
    probe_anchors,
)
from my_pa.bootstrap.communications_ingest import ingest_unit_of_work
from my_pa.contracts.ports import (
    MeetingContextCandidateRow,
    ProjectReportBindingRecord,
    UnitOfWork,
)
from my_pa.domain.communications.coverage import WindowFact, summarize_coverage
from my_pa.domain.communications.identifiers import (
    IdentifierKind,
    TechnicalIdentifier,
    extract_identifiers,
    surface_form,
)
from my_pa.domain.project_reports.model import BindingState
from my_pa.domain.situation.situation import Project, ProjectState
from tests.conftest import World
from tests.unit.communications_ingest_fakes import IngestUnitOfWork
from tests.unit.test_communications_ingest_cli import (
    EXPECT,
    HEAD,
    _content_strings,
    _Engine,
    _Scene,
    run,
)

NOW: Final = datetime(2026, 11, 26, 12, tzinfo=UTC)
PROJECT_ID: Final = "prj_measureleak0001"
PROJECT_NUMBER: Final = "PN-LEAK-4471"
PROJECT_NAME: Final = "Leaky Project Name"
SUBJECT: Final = "Canned subject never printed"
SENDER: Final = "canned.sender@example.invalid"
SNIPPET: Final = "canned snippet never printed"
MESSAGE_ID: Final = "cmsg_measureleak000001"
CONVERSATION_ID: Final = "conv-measure-leak-0001"
SHAPES: Final = (
    "meetings_1_pulse_off",
    "meetings_1_pulse_on",
    "meetings_3_pulse_off",
    "meetings_3_pulse_on",
)


def _row(ordinal: int, n: int, address: str) -> MeetingContextCandidateRow:
    return MeetingContextCandidateRow(
        ordinal=ordinal,
        message_id=f"{MESSAGE_ID}{n}",
        conversation_id=CONVERSATION_ID,
        message_time=NOW - timedelta(hours=n),
        subject=SUBJECT,
        sender_address=SENDER,
        has_attachments=False,
        body_state="present",
        search_text_version="comms_search_text_v2",
        search_text_flags=(),
        identity_conflict=False,
        participants_reconciled=False,
        participants_disagreed=False,
        source_unavailable=False,
        tier=1 if n % 2 else 3,
        overlap=1,
        rank=0,
        matched_keys=(address,),
        matched_identifiers=(("rfi", "174"),) if n % 2 else (),
        title_hit=False,
        project_number_hit=False,
        conversation_hits=1,
        matched_total=2,
        snippet=SNIPPET,
    )


class _Measured:
    """The scene: the CLI fakes, a general world with a bound Project, and the measurement."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        *,
        timer: Callable[[], float] | None = None,
    ) -> None:
        self.scene = _Scene(monkeypatch)
        source = self.scene.admit(capsys)
        self.scene.put_fixtures()
        assert run(capsys, "backfill", "--source", source)[0] == cli.EXIT_OK
        self.general = World()
        self.general.projects.append(
            Project(
                project_id=PROJECT_ID,
                principal_id=self._principal(),
                name=PROJECT_NAME,
                state=ProjectState.ACTIVE,
                opened_at=NOW,
                created_at=NOW,
                updated_at=NOW,
                project_number=PROJECT_NUMBER,
            )
        )
        self.general.project_reports.bindings[(self._principal(), "isrc_measureleak01")] = (
            ProjectReportBindingRecord(
                ingest_source_id="isrc_measureleak01",
                binding_revision_id="pbrv_measureleak01",
                project_id=PROJECT_ID,
                state=BindingState.ACTIVE,
            )
        )
        world = self.scene.world
        stored = {p.address for p in world.participants.values()}
        assert len(stored) >= 2
        self.addresses = tuple(sorted({*stored, "charlie.measure@example.invalid"}))
        world.context_rows = [
            _row(ordinal, n, self.addresses[0]) for ordinal in range(3) for n in (1, 2)
        ]
        self.built: list[str] = []
        self.given: tuple[str, ...] = ()
        self.anchors: list[Sequence[datetime]] = []
        ticks = itertools.count()

        def synthetic_timer() -> float:
            return next(ticks) / 1000

        def unit() -> UnitOfWork:
            return IngestUnitOfWork(world, meetings=self.general)

        def facts(
            anchors: Sequence[datetime], _lookback: timedelta, excluded: Sequence[str]
        ) -> list[tuple[tuple[str, ...], tuple[tuple[str, str], ...]]]:
            self.anchors.append(anchors)
            mine = tuple(a for a in self.addresses if a not in excluded)
            self.given = mine[:8]
            return [(mine[:8], (("rfi", "174"), ("co", "5"))) for _ in anchors]

        def build(_engine: object, principal_id: str) -> MeetingContextMeasurement:
            self.built.append(principal_id)
            return MeetingContextMeasurement(
                unit_of_work=unit,
                probe_facts=facts,
                quarantined=lambda reason: 2 if reason == "identity_kind_mismatch" else 99,
                statements=lambda: len(world.context_calls) * 17,
                clock=lambda: NOW,
                timer=timer if timer is not None else synthetic_timer,
            )

        monkeypatch.setattr(cli, "meeting_context_measurement", build)

    @staticmethod
    def _principal() -> str:
        from my_pa.bootstrap.gateway import local_principal

        return local_principal().principal_id

    def forbidden(self) -> set[str]:
        found = {
            *_content_strings(),
            *self.addresses,
            SUBJECT,
            SENDER,
            SNIPPET,
            MESSAGE_ID,
            CONVERSATION_ID,
            PROJECT_ID,
            PROJECT_NUMBER,
            PROJECT_NAME,
            PROBE_TITLE,
            "rfi:174",
            "RFI 174",
            "co:5",
            "mtg_",
            "matt_",
            "probe0",
        }
        return {value for value in found if value}


def _measure(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any], str]:
    code = cli.main([*EXPECT, "measure-context", *argv])
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert len(lines) == 1, captured.out
    return code, json.loads(lines[0]), lines[0]


def test_p95_counts_the_slower_sample_in_a_two_run_measurement(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ticks = iter((0.0, 0.1, 1.0, 2.0) * 2)
    _Measured(monkeypatch, capsys, timer=lambda: next(ticks))

    code, out, _text = _measure(capsys, "--meetings", "1", "--runs", "2")

    assert code == cli.EXIT_OK
    for shape in out["latency"].values():
        assert (shape["p50_ms"], shape["p95_ms"], shape["max_ms"]) == (550.0, 1000.0, 1000.0)
    assert out["targets"]["meetings_1_defaults"] == {"off": False, "on": False}


def test_the_output_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    measured = _Measured(monkeypatch, capsys)
    code, out, _text = _measure(capsys, "--meetings", "3", "--runs", "5")
    assert code == cli.EXIT_OK
    assert set(out) == {
        "command",
        "probes",
        "anchor_basis",
        "runs",
        "lookback_days",
        "per_meeting_limit",
        "probe_attendees_skipped",
        "latency",
        "targets",
        "per_probe",
        "coverage",
        "pulse",
        "self_addresses",
        "bridge",
        "quarantined_identity_kind_mismatch",
    }
    assert out["command"] == "measure-context"
    assert (out["probes"], out["runs"], out["lookback_days"], out["per_meeting_limit"]) == (
        3,
        5,
        14,
        15,
    )
    assert out["anchor_basis"] == "coverage"
    assert len(measured.anchors[0]) == 3
    assert tuple(out["latency"]) == SHAPES
    for shape in out["latency"].values():
        assert set(shape) == {"p50_ms", "p95_ms", "max_ms", "statements"}
        assert shape["p50_ms"] == shape["p95_ms"] == shape["max_ms"] == 1.0  # one tick a run
        assert shape["statements"] == 17  # one canned candidate call per batch
    # Not the D15 shapes (3 Meetings): no target is judged.
    assert out["targets"] == {
        "meetings_10_defaults": None,
        "meetings_1_defaults": {"off": True, "on": True},
        "meetings_10_maximum": None,
    }
    assert len(out["per_probe"]) == 3
    first = out["per_probe"][0]
    assert first["inputs"] == {
        "attendee_keys": len(measured.given),
        "self_attendees": 0,
        "identifiers": 2,
        "title_terms": first["inputs"]["title_terms"],
        "project_number": "used",
    }
    assert first["inputs"]["title_terms"] >= 2
    assert (first["matched_total"], first["returned"], first["truncated"]) == (2, 2, False)
    assert first["by_tier"] == {"1": 1, "3": 1}
    assert first["by_matched_by"] == {"identifiers": 1, "participants": 2}
    assert first["state"] == "ok"
    assert "provider_unbound" in first["missing"]
    assert first["pulse_state"] == "unavailable"
    assert out["pulse"]["bound_projects"] == 1
    assert out["pulse"]["by_state"] == {"unavailable": 3}
    assert set(out["coverage"]) == {"by_state", "gaps"}
    assert set(out["self_addresses"]) == {"state", "count", "used"}
    assert out["bridge"] == {
        "non_ascii_participant_addresses": 0,
        "truncated": False,
        "bridged_spellings": 0,
    }
    assert out["quarantined_identity_kind_mismatch"] == 2
    assert measured.built == [measured._principal()]


def test_the_output_carries_no_address_subject_snippet_name_number_or_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Prove-red m19: printing one address (or any content) makes this red."""
    measured = _Measured(monkeypatch, capsys)
    malformed_address = "oversized" * 40 + "@example.invalid"
    measured.addresses = (malformed_address, *measured.addresses)
    for argv in ((), ("--meetings", "1", "--runs", "1")):
        code, out, text = _measure(capsys, *argv)
        assert code == cli.EXIT_OK
        assert out["probe_attendees_skipped"] == out["probes"]
        forbidden = measured.forbidden()
        assert len(forbidden) > 20  # the check decides something
        leaked = sorted(value for value in forbidden if value in text)
        assert not leaked, leaked
        assert "@" not in text


@pytest.mark.parametrize(
    "engine", [_Engine(database="other"), _Engine(heads=["0123abcd"])], ids=["database", "head"]
)
def test_a_mismatched_target_refuses_before_any_measurement(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    engine: _Engine,
) -> None:
    built: list[object] = []
    _Scene(monkeypatch, engine)
    monkeypatch.setattr(cli, "meeting_context_measurement", lambda *a: built.append(a))
    assert run(capsys, "measure-context") == (
        cli.EXIT_REFUSED,
        {"command": "measure-context", "refused": "target_mismatch"},
    )
    assert built == []


def test_a_mismatched_configured_database_refuses_before_an_engine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    code = cli.main(
        ["--expected-database", "elsewhere", "--expected-alembic-head", HEAD, "measure-context"]
    )
    assert code == cli.EXIT_REFUSED
    assert json.loads(capsys.readouterr().out) == {
        "command": "measure-context",
        "refused": "target_mismatch",
    }
    assert scene.engines_built == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["--meetings", "0"],
        ["--meetings", "11"],
        ["--runs", "0"],
        ["--runs", "501"],
        ["--lookback-days", "0"],
        ["--lookback-days", "91"],
        ["--per-meeting-limit", "0"],
        ["--per-meeting-limit", "51"],
        ["--meetings", "ten"],
    ],
)
def test_out_of_range_bounds_are_usage_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    scene = _Scene(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        cli.main([*EXPECT, "measure-context", *argv])
    assert raised.value.code == 2
    assert scene.engines_built == 0
    capsys.readouterr()


def test_a_statement_timeout_is_its_own_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _CancelledError(Exception):
        sqlstate = "57014"

    class _Measurement:
        def measure(self, *_a: object, **_k: object) -> dict[str, object]:
            raise OperationalError("SELECT 1", {}, _CancelledError())

    _Scene(monkeypatch)
    monkeypatch.setattr(cli, "meeting_context_measurement", lambda *_a: _Measurement())
    assert run(capsys, "measure-context") == (
        cli.EXIT_REFUSED,
        {"command": "measure-context", "refused": "statement_timeout"},
    )


@pytest.mark.parametrize(
    ("failure", "refusal"),
    [(OperationalError, "database_unreachable"), (ProgrammingError, "database_unavailable")],
)
def test_refusal_if_the_store_fails_after_identity_verification(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: type[DBAPIError],
    refusal: str,
) -> None:
    engine = _Engine()
    transaction = MagicMock()
    transaction.__enter__.side_effect = failure("SELECT :subject", {"subject": SUBJECT}, OSError())
    monkeypatch.setattr(engine, "begin", lambda: transaction, raising=False)
    _Scene(monkeypatch, engine)
    monkeypatch.setattr(
        cli,
        "meeting_context_measurement",
        lambda *_args: MeetingContextMeasurement(
            unit_of_work=ingest_unit_of_work(cast(Engine, engine)),
            probe_facts=lambda *_args: (),
            quarantined=lambda _reason: 0,
            statements=lambda: 0,
        ),
    )

    code, out, output = _measure(capsys)

    assert transaction.__enter__.call_count == 1
    assert engine.disposed
    assert (code, out) == (cli.EXIT_REFUSED, {"command": "measure-context", "refused": refusal})
    assert SUBJECT not in output


# ---- the pure probe parts ------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("rfi", "174"),
        ("co", "5"),
        ("cb", "12"),
        ("pco", "7"),
        ("cor", "3"),
        ("submittal", "033000-01"),
        ("spec", "033000"),
    ],
)
def test_a_probe_identifier_is_written_in_a_form_the_extractor_reads_back(
    kind: str, value: str
) -> None:
    identifier = TechnicalIdentifier(IdentifierKind(kind), value)
    surface = surface_form(identifier)
    assert surface is not None
    assert extract_identifiers(surface) == (identifier,)


def test_the_bare_kinds_have_no_probe_surface() -> None:
    assert surface_form(TechnicalIdentifier(IdentifierKind.GMP, "gmp")) is None


def test_the_anchors_span_the_covered_range_less_the_lookback() -> None:
    start = NOW - timedelta(days=30)
    summary = summarize_coverage(
        [
            WindowFact(
                start=start,
                end=NOW,
                state="complete",
                lanes=(),
            )
        ],
        now=NOW,
    )
    anchors, basis = probe_anchors(summary, timedelta(days=14), 3, NOW)
    assert basis == "coverage"
    assert anchors == (start + timedelta(days=14), start + timedelta(days=22), NOW)
    assert probe_anchors(summary, timedelta(days=14), 1, NOW) == ((NOW,), "coverage")
    # Shorter than the lookback: the latest covered instant alone.
    assert probe_anchors(summary, timedelta(days=90), 2, NOW)[0] == (NOW, NOW)
    empty = summarize_coverage([], now=NOW)
    assert probe_anchors(empty, timedelta(days=14), 2, NOW) == ((NOW, NOW), "none")
