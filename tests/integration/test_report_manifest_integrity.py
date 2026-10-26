"""AT-022: every new Intelligence artifact has an immutable, separately hashed manifest.

Record lineage S4 contract sections 4.1, 5.2-5.4, 6.3 and 7.4 (WP-04C, CR-013),
against PostgreSQL through `ApplicationService.invoke` with the Program read
pool composed as the gateway composes it:

* every artifact committed after the revision has its manifest; the Markdown
  digest is unchanged; the manifest digest recomputes from the stored row,
  over the structured content **as read back** (a number JSONB renormalizes);
* a structured-metric change, or a dependency change, with the same Markdown
  changes the manifest;
* a legacy artifact answers `manifest_unavailable_legacy` and is never
  rewritten;
* a Program reference block is recomputed at commit -- on the Program pool,
  after every refusal check and before the first write, under a 5000 ms
  total budget -- and the manifest binds the server's state as the caller
  sees it: `verified_at_commit`, `changed_since_read`, `recompute_failed`
  (never a refusal) or `not_attempted` when `programs.overview` is not served;
* a collector carries no Program reference and its candidates are never typed;
* a replay writes no second manifest, and with the switch off the block is
  ordinary content.

Every identity is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, text

from my_pa.application.commands import (
    CommitIntelligenceArtifact,
    ReadIntelligenceArtifact,
    ReadReportManifest,
)
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import IntelligenceStage
from my_pa.domain.intelligence.models import content_digest
from my_pa.domain.intelligence.source_manifest import (
    STRUCTURED_CONTENT_DIGEST_PREFIX,
    canonical,
    manifest_digest,
    server_state,
)
from my_pa.domain.program.vocabulary import PROGRAM_REFERENCE_BLOCK_KEY
from my_pa.domain.source.registry import issue_identifier
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_s4_harness import T0, S4Runtime

pytestmark = pytest.mark.database

SYNTH: Final = IntelligenceStage.SYNTHESIZER
#: The overview's first statement: the one that takes the snapshot.
SNAPSHOT_MARK: Final = "statement_timestamp()"
#: The commit's first write (`put_receipt`).
FIRST_WRITE_MARK: Final = "INSERT INTO knowledge.intelligence_commit_receipts"
#: Round-trip slack beside the 5000 ms budget on a loaded machine.
BUDGET_SLACK_SECONDS: Final = 0.4


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S4Runtime]:
    composed = S4Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _program(runtime: S4Runtime, name: str = "Manifest Program") -> tuple[str, str]:
    """A Program of one calendared, in-sync member Project: `(program, project)`."""
    seeds = runtime.seeds
    program = seeds.program(name)
    project, entity = seeds.project(f"{name} member")
    seeds.edge(entity, program, effective_from=T0)
    category = seeds.constraint_calendar(project)
    seeds.sync_target(project)
    seeds.constraint(project, category, due_date=date(2099, 1, 1))
    return program, project


def _program_of(manifest: dict[str, Any]) -> dict[str, Any]:
    program = json.loads(manifest["manifest_canonical"])["program"]
    assert isinstance(program, dict)
    return program


def _manifest_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.intelligence_artifact_manifests")
            ).scalar_one()
        )


def _artifact_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.intelligence_artifacts")
            ).scalar_one()
        )


@contextmanager
def _statements(*engines: tuple[str, Engine]) -> Iterator[list[tuple[str, str]]]:
    """Every statement sent on each named engine, in one global order."""
    seen: list[tuple[str, str]] = []
    lock = threading.Lock()
    listeners: list[tuple[Engine, Callable[..., None]]] = []
    for label, engine in engines:

        def record(
            _connection: object,
            _cursor: object,
            statement: str,
            *_rest: object,
            _label: str = label,
        ) -> None:
            with lock:
                seen.append((_label, statement))

        event.listen(engine, "before_cursor_execute", record)
        listeners.append((engine, record))
    try:
        yield seen
    finally:
        for engine, record in listeners:
            event.remove(engine, "before_cursor_execute", record)


def _synthesizer(
    runtime: S4Runtime,
    cycle: str,
    researcher: str,
    key: str,
    content: dict[str, object] | None,
    **kwargs: Any,  # noqa: ANN401
) -> dict[str, Any]:
    return runtime.commit_report(
        runtime.report(cycle, SYNTH, key, dependencies=(researcher,), structured_content=content),
        **kwargs,
    )


def _without_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    """A decoded manifest without what differs between two artifacts by construction."""
    decoded = json.loads(manifest["manifest_canonical"])
    for key in ("report_id", "producer_run_id", "version", "supersedes_report_id", "committed_at"):
        decoded["report"].pop(key)
    return decoded


def test_every_new_artifact_has_a_manifest(runtime: S4Runtime) -> None:
    cycle = runtime.cycle("every")
    researcher = runtime.research(cycle, "every")
    synthesis = _synthesizer(runtime, cycle, researcher, "every-synth", {"metric": 1})
    reporter = runtime.commit_report(
        runtime.report(
            cycle,
            IntelligenceStage.REPORTER,
            "every-reporter",
            dependencies=(synthesis["report_id"],),
        )
    )
    brief = runtime.commit_report(
        runtime.report(
            cycle,
            IntelligenceStage.MORNING_BRIEF,
            "every-brief",
            dependencies=(reporter["report_id"],),
        )
    )
    assert _artifact_count(runtime.engine) == _manifest_count(runtime.engine) == 5
    for report_id in (
        researcher,
        synthesis["report_id"],
        reporter["report_id"],
        brief["report_id"],
    ):
        answer = runtime.manifest(report_id)
        assert answer["manifest_state"] == "recorded"
        assert answer["manifest_schema_version"] == 1
        decoded = json.loads(answer["manifest_canonical"])
        assert decoded["report"]["report_id"] == report_id
        assert runtime.stored_manifest(report_id) is not None


def test_a_structured_metric_change_with_the_same_markdown_changes_the_manifest(
    runtime: S4Runtime,
) -> None:
    cycle = runtime.cycle("metric")
    researcher = runtime.research(cycle, "metric")
    first = _synthesizer(runtime, cycle, researcher, "metric-1", {"open_items": 3})
    second = runtime.commit_report(
        runtime.report(
            cycle,
            SYNTH,
            "metric-2",
            dependencies=(researcher,),
            structured_content={"open_items": 4},
            supersedes=first["report_id"],
        )
    )
    # The same Markdown: the v1 digest cannot tell them apart.
    assert first["content_sha256"] == second["content_sha256"]
    one = runtime.manifest(first["report_id"])
    two = runtime.manifest(second["report_id"])
    assert one["manifest_sha256"] != two["manifest_sha256"]
    # Beyond the 2 artifacts' own identities, exactly the structured digest differs.
    left, right = _without_identity(one), _without_identity(two)
    assert left["structured_content"]["sha256"] != right["structured_content"]["sha256"]
    assert left != right
    left.pop("structured_content")
    right.pop("structured_content")
    assert left == right


def test_a_dependency_change_with_the_same_markdown_changes_the_manifest(
    runtime: S4Runtime,
) -> None:
    cycle = runtime.cycle("dependency")
    researcher = runtime.research(cycle, "dependency")
    first = _synthesizer(runtime, cycle, researcher, "dependency-1", {"open_items": 3})
    reporter_one = runtime.commit_report(
        runtime.report(
            cycle, IntelligenceStage.REPORTER, "dependency-r1", dependencies=(first["report_id"],)
        )
    )
    # The upstream is replaced by one with the same Markdown, other structured content.
    second = runtime.commit_report(
        runtime.report(
            cycle,
            SYNTH,
            "dependency-2",
            dependencies=(researcher,),
            structured_content={"open_items": 4},
            supersedes=first["report_id"],
        )
    )
    reporter_two = runtime.commit_report(
        runtime.report(
            cycle,
            IntelligenceStage.REPORTER,
            "dependency-r2",
            dependencies=(second["report_id"],),
            supersedes=reporter_one["report_id"],
        )
    )
    assert reporter_one["content_sha256"] == reporter_two["content_sha256"]
    (left,) = _without_identity(runtime.manifest(reporter_one["report_id"]))["dependencies"]
    (right,) = _without_identity(runtime.manifest(reporter_two["report_id"]))["dependencies"]
    assert left["content_sha256"] == right["content_sha256"]
    # Each binds its upstream's own structured digest and manifest.
    for row, upstream in ((left, first), (right, second)):
        stored = runtime.stored_manifest(upstream["report_id"])
        assert stored is not None
        assert row["structured_content_sha256"] == stored["structured_content_sha256"]
        assert row["manifest_sha256"] == stored["manifest_sha256"]
        assert row["manifest_state"] == "recorded"
    assert left["structured_content_sha256"] != right["structured_content_sha256"]
    assert (
        runtime.manifest(reporter_one["report_id"])["manifest_sha256"]
        != runtime.manifest(reporter_two["report_id"])["manifest_sha256"]
    )
    # A legacy upstream is bound by the digest recomputed from its immutable row.
    third = runtime.commit_report(
        runtime.report(
            cycle,
            SYNTH,
            "dependency-3",
            dependencies=(researcher,),
            structured_content={"open_items": 5},
            supersedes=second["report_id"],
        )
    )
    runtime.make_legacy(third["report_id"])
    reporter_three = runtime.commit_report(
        runtime.report(
            cycle,
            IntelligenceStage.REPORTER,
            "dependency-r3",
            dependencies=(third["report_id"],),
            supersedes=reporter_two["report_id"],
        )
    )
    (legacy,) = json.loads(runtime.manifest(reporter_three["report_id"])["manifest_canonical"])[
        "dependencies"
    ]
    assert (legacy["manifest_sha256"], legacy["manifest_state"]) == (
        None,
        "manifest_unavailable_legacy",
    )
    assert (
        legacy["structured_content_sha256"]
        == hashlib.sha256(
            STRUCTURED_CONTENT_DIGEST_PREFIX + canonical({"open_items": 5})
        ).hexdigest()
    )


def test_the_markdown_digest_is_unchanged(runtime: S4Runtime) -> None:
    cycle = runtime.cycle("markdown")
    body = "# Synthetic\n\nUnchanged digest é"
    collector = runtime.commit_report(
        runtime.report(cycle, IntelligenceStage.COLLECTOR, "markdown", body=body)
    )
    # The commit answer is the v1 answer: no manifest key in it.
    assert set(collector) == {
        "receipt_id",
        "report_id",
        "report_run_id",
        "cycle_run_id",
        "focus_area_id",
        "stage",
        "artifact_kind",
        "source_lane",
        "report_date",
        "artifact_state",
        "content_sha256",
        "content_bytes",
        "committed_at",
        "version",
        "supersedes_report_id",
        "created",
        "replayed",
    }
    assert collector["content_sha256"] == content_digest(body)
    assert collector["content_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()
    read = runtime.ok(ReadIntelligenceArtifact(report_id=collector["report_id"]))
    assert read["content_sha256"] == collector["content_sha256"]
    report = json.loads(runtime.manifest(collector["report_id"])["manifest_canonical"])["report"]
    assert report["content_sha256"] == collector["content_sha256"]
    assert report["content_bytes"] == len(body.encode("utf-8"))


def test_the_manifest_digest_recomputes_from_the_stored_row(runtime: S4Runtime) -> None:
    cycle = runtime.cycle("readback")
    researcher = runtime.research(cycle, "readback")
    # JSONB renormalizes `1e20` to the integer 100000000000000000000.
    sent: dict[str, object] = {"large": 1e20, "ratio": 0.5, "label": "Café"}
    synthesis = _synthesizer(runtime, cycle, researcher, "readback", sent)
    with runtime.engine.connect() as connection:
        stored_value = connection.execute(
            text(
                "SELECT structured_content FROM knowledge.intelligence_artifacts "
                "WHERE artifact_id = :artifact_id"
            ),
            {"artifact_id": synthesis["report_id"]},
        ).scalar_one()
    assert stored_value["large"] == 10**20
    assert isinstance(stored_value["large"], int)
    from_row = hashlib.sha256(
        STRUCTURED_CONTENT_DIGEST_PREFIX + canonical(stored_value)
    ).hexdigest()
    from_request = hashlib.sha256(STRUCTURED_CONTENT_DIGEST_PREFIX + canonical(sent)).hexdigest()
    assert from_row != from_request
    row = runtime.stored_manifest(synthesis["report_id"])
    assert row is not None
    assert row["structured_content_sha256"] == from_row
    decoded = json.loads(row["manifest_canonical"])
    assert decoded["structured_content"] == {"present": True, "sha256": from_row}
    # The stored digest is the CHECK's and the client's recomputation of the stored text.
    assert row["manifest_sha256"] == manifest_digest(row["manifest_canonical"])
    answer = runtime.manifest(synthesis["report_id"])
    assert (answer["manifest_sha256"], answer["manifest_canonical"]) == (
        row["manifest_sha256"],
        row["manifest_canonical"],
    )
    # A DEL in a provenance reference is escaped, so the manifest stays printable.
    collector = runtime.commit_report(
        runtime.report(
            cycle,
            IntelligenceStage.COLLECTOR,
            "readback-del",
            provenance=(
                {"source_system": "outlook", "source_ref": "msg\x7fdel", "relation": "context"},
            ),
        )
    )
    escaped = runtime.stored_manifest(collector["report_id"])
    assert escaped is not None
    assert '"source_ref":"msg\\u007fdel"' in escaped["manifest_canonical"]
    assert escaped["manifest_sha256"] == manifest_digest(escaped["manifest_canonical"])


def test_a_legacy_report_answers_unavailable_and_is_never_rewritten(runtime: S4Runtime) -> None:
    cycle = runtime.cycle("legacy")
    collector = runtime.commit_report(runtime.report(cycle, IntelligenceStage.COLLECTOR, "legacy"))
    report_id = collector["report_id"]
    runtime.make_legacy(report_id)
    before = _manifest_count(runtime.engine)
    for _attempt in range(2):
        answer = runtime.manifest(report_id)
        assert answer == {
            "report_id": report_id,
            "manifest_state": "manifest_unavailable_legacy",
            "manifest_schema_version": None,
            "manifest_sha256": None,
            "manifest_canonical": None,
        }
    # Nothing was written: no backfill of a legacy manifest exists.
    assert _manifest_count(runtime.engine) == before
    assert runtime.stored_manifest(report_id) is None
    # An absent artifact is `not_found` / `artifact_id`, as `reports.read`.
    error = runtime.refused(ReadReportManifest(report_id="rpt_manifestabsent0001"))
    assert (error["code"], error["safe_details"]) == ("not_found", ["artifact_id"])


def test_a_verified_program_reference_binds_the_server_state_as_the_caller_sees_it(
    runtime: S4Runtime,
) -> None:
    program, project = _program(runtime)
    overview = runtime.overview(program)
    cycle = runtime.cycle("verified")
    researcher = runtime.research(cycle, "verified")
    content = {**runtime.program_reference(overview, program), "summary_items": 2}
    synthesis = _synthesizer(runtime, cycle, researcher, "verified", content)
    manifest = runtime.manifest(synthesis["report_id"])
    section = _program_of(manifest)
    assert section["verification_state"] == "verified_at_commit"
    assert section["recompute_failure"] is None
    assert section["claimed_overview_sha256"] == overview["overview_sha256"]
    assert section["claimed_source_cutoff_at"] == overview["source_cutoff_at"]
    assert section["program_entity_ids"] == [program]
    server = section["server"]
    # The server's own state, as this (local) caller sees it: the overview it
    # would answer at that instant, with its own cutoff.
    expected = server_state(overview)
    assert {key: value for key, value in server.items() if key != "source_cutoff_at"} == {
        key: value for key, value in expected.items() if key != "source_cutoff_at"
    }
    assert server["source_cutoff_at"] >= overview["source_cutoff_at"]
    assert server["membership"][0]["project_ids"] == [project]
    assert server["portfolio_project_ids"] == [project]
    assert server["metric_schema_version"] == 1
    assert server["calculation_version"] == "program-overview-v1"
    assert len(server["totals"]) == 2 * 13
    assert section["families_seen"] == ["commitment", "constraint", "entity", "issue", "project"]
    # The projected columns are copies of the manifest's fields.
    row = runtime.stored_manifest(synthesis["report_id"])
    assert row is not None
    assert row["program_overview_sha256"] == overview["overview_sha256"]
    assert row["program_verification_state"] == "verified_at_commit"


def test_a_changed_program_source_is_recorded_with_the_server_state(runtime: S4Runtime) -> None:
    program, project = _program(runtime)
    overview = runtime.overview(program)
    # The Program's state moves between the producer's read and its commit.
    runtime.work_commitment("manifest-changed", project_id=project, accepted=False)
    cycle = runtime.cycle("changed")
    researcher = runtime.research(cycle, "changed")
    synthesis = _synthesizer(
        runtime, cycle, researcher, "changed", runtime.program_reference(overview, program)
    )
    section = _program_of(runtime.manifest(synthesis["report_id"]))
    assert section["verification_state"] == "changed_since_read"
    server = section["server"]
    assert server["overview_sha256"] != section["claimed_overview_sha256"]
    assert server["overview_sha256"] == runtime.overview(program)["overview_sha256"]
    proposed = {
        row["scope"]: row["value"]
        for row in server["totals"]
        if row["metric_id"] == "commitment_open_proposed"
    }
    assert proposed == {program: 1, "portfolio": 1}
    row = runtime.stored_manifest(synthesis["report_id"])
    assert row is not None
    assert row["program_verification_state"] == "changed_since_read"


@contextmanager
def _locked(engine: Engine, table: str) -> Iterator[None]:
    """Another connection holds `table` in `ACCESS EXCLUSIVE` mode meanwhile."""
    locked = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with engine.connect() as connection, connection.begin():
            connection.execute(text(f"LOCK TABLE knowledge.{table} IN ACCESS EXCLUSIVE MODE"))
            locked.set()
            release.wait(timeout=30)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert locked.wait(timeout=30)
        yield
    finally:
        release.set()
        holder.join(timeout=30)


def test_a_failed_recompute_is_recorded_and_never_refuses_the_commit(runtime: S4Runtime) -> None:
    program, _project = _program(runtime)
    overview = runtime.overview(program)
    cycle = runtime.cycle("failed")
    researcher = runtime.research(cycle, "failed")
    # A statement cancelled by its 2000 ms timeout.
    with _locked(runtime.engine, "entity_relationships"):
        timed_out = _synthesizer(
            runtime,
            cycle,
            researcher,
            "failed-timeout",
            runtime.program_reference(overview, program),
        )
    assert timed_out["created"] is True
    assert runtime.program_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    # A Program now absent, and an Entity that is not a Program.
    absent = "ent_manifestabsent0001"
    _project_id, project_entity = runtime.seeds.project("Manifest not a program")
    outcomes = {"failed-timeout": timed_out}
    for key, ids in (("failed-absent", (absent,)), ("failed-invalid", (project_entity,))):
        block = runtime.program_reference(overview, *ids)
        outcomes[key] = _synthesizer(runtime, cycle, researcher, key, block)
        assert outcomes[key]["created"] is True
    expected = {
        "failed-timeout": "statement_timeout",
        "failed-absent": "program_not_found",
        "failed-invalid": "program_invalid",
    }
    for key, answer in outcomes.items():
        section = _program_of(runtime.manifest(answer["report_id"]))
        assert (section["verification_state"], section["recompute_failure"]) == (
            "recompute_failed",
            expected[key],
        ), key
        assert section["server"] is None
        assert section["families_seen"] is None
        row = runtime.stored_manifest(answer["report_id"])
        assert row is not None
        assert row["program_verification_state"] == "recompute_failed"


def test_the_recompute_runs_before_the_first_write_on_the_program_pool(
    runtime: S4Runtime,
) -> None:
    program, _project = _program(runtime)
    overview = runtime.overview(program)
    cycle = runtime.cycle("order")
    researcher = runtime.research(cycle, "order")
    with _statements(("work", runtime.engine), ("program", runtime.program_engine)) as seen:
        _synthesizer(
            runtime, cycle, researcher, "order", runtime.program_reference(overview, program)
        )
    snapshot = next(
        index
        for index, (label, statement) in enumerate(seen)
        if label == "program" and SNAPSHOT_MARK in statement
    )
    first_write = next(
        index
        for index, (label, statement) in enumerate(seen)
        if label == "work"
        and statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        and "audit_events" not in statement
    )
    assert FIRST_WRITE_MARK in seen[first_write][1]
    assert snapshot < first_write
    # Every recompute statement ran on the Program pool, none on the work pool,
    # and every one of them before the commit's first write.
    program_indexes = [
        index for index, (label, _statement) in enumerate(seen) if label == "program"
    ]
    assert max(program_indexes) < first_write
    assert not any(SNAPSHOT_MARK in statement for label, statement in seen if label == "work")


def test_a_refused_commit_never_recomputes(runtime: S4Runtime) -> None:
    program, _project = _program(runtime)
    overview = runtime.overview(program)
    block = runtime.program_reference(overview, program)
    cycle = runtime.cycle("refused")
    researcher = runtime.research(cycle, "refused")
    first = _synthesizer(runtime, cycle, researcher, "refused-head", block)
    refusals = [
        # `get_cycle`: an unknown cycle.
        runtime.report(
            "micr_manifestnocycle01",
            SYNTH,
            "refused-cycle",
            dependencies=(researcher,),
            structured_content=block,
        ),
        # dependency validation: an absent upstream.
        runtime.report(
            cycle,
            SYNTH,
            "refused-dependency",
            dependencies=("rpt_manifestnodep0001",),
            structured_content=block,
        ),
        # the stale `supersedes_artifact_id` check against `current_head`.
        runtime.report(
            cycle,
            SYNTH,
            "refused-stale",
            dependencies=(researcher,),
            structured_content=block,
            supersedes="rpt_manifeststale00001",
        ),
    ]
    runtime.commit_report(
        runtime.report(
            cycle,
            SYNTH,
            "refused-run",
            dependencies=(researcher,),
            automation_run_id="run-1",
            supersedes=first["report_id"],
        )
    )
    # the `automation_run_id` conflict.
    refusals.append(
        runtime.report(
            cycle,
            SYNTH,
            "refused-run-again",
            dependencies=(researcher,),
            structured_content=block,
            automation_run_id="run-1",
        )
    )
    for command in refusals:
        with _statements(("program", runtime.program_engine)) as seen:
            runtime.refused(command)
        assert seen == [], command.idempotency_key
    # A replay returns the stored receipt and recomputes nothing either.
    with _statements(("program", runtime.program_engine)) as seen:
        replay = _synthesizer(runtime, cycle, researcher, "refused-head", block)
    assert replay["replayed"] is True
    assert seen == []


def test_the_recompute_respects_its_total_budget(
    runtime: S4Runtime, disposable_database: str
) -> None:
    program, _project = _program(runtime)
    overview = runtime.overview(program)
    block = runtime.program_reference(overview, program)
    cycle = runtime.cycle("budget")
    researcher = runtime.research(cycle, "budget")

    def slow_after_snapshot(seconds: float) -> Callable[..., None]:
        """Spend `seconds` right after the snapshot query (the earlier statements' cost).

        An `after_cursor_execute` hook, so the next statement's budget check
        (the unit of work's own `before_cursor_execute` hook) sees it spent.
        """
        fired = threading.Event()

        def delay(_connection: object, _cursor: object, statement: str, *_rest: object) -> None:
            if SNAPSHOT_MARK in statement and not fired.is_set():
                fired.set()
                time.sleep(seconds)

        return delay

    def commit_timed(
        key: str, seconds: float, table: str | None
    ) -> tuple[dict[str, Any], float, list[str]]:
        delay = slow_after_snapshot(seconds)
        event.listen(runtime.program_engine, "after_cursor_execute", delay)
        try:
            with _statements(("program", runtime.program_engine)) as seen:
                started = time.monotonic()
                if table is None:
                    answer = _synthesizer(runtime, cycle, researcher, key, block)
                else:
                    with _locked(runtime.engine, table):
                        answer = _synthesizer(runtime, cycle, researcher, key, block)
                elapsed = time.monotonic() - started
        finally:
            event.remove(runtime.program_engine, "after_cursor_execute", delay)
        return answer, elapsed, [statement for _label, statement in seen]

    # A statement started near the deadline is cancelled at the remaining
    # budget, not after a full 2000 ms: 3.6 s spent, then the Commitment
    # aggregate waits on a lock and gets about 1.4 s.
    near, elapsed, seen = commit_timed("budget-near", 3.6, "commitments")
    section = _program_of(runtime.manifest(near["report_id"]))
    assert (section["verification_state"], section["recompute_failure"]) == (
        "recompute_failed",
        "budget_exceeded",
    )
    assert "knowledge.commitments" in seen[-1]
    assert 4.8 <= elapsed < 5.0 + BUDGET_SLACK_SECONDS, elapsed
    # The budget spent before a statement: no later statement is sent.
    spent, elapsed, seen = commit_timed("budget-spent", 5.1, None)
    section = _program_of(runtime.manifest(spent["report_id"]))
    assert (section["verification_state"], section["recompute_failure"]) == (
        "recompute_failed",
        "budget_exceeded",
    )
    assert len(seen) == 1, seen
    assert SNAPSHOT_MARK in seen[0]
    assert elapsed < 5.1 + BUDGET_SLACK_SECONDS, elapsed
    # A checkout wait ends at the gateway's Program engine's 1 s checkout timeout.
    gateway = build_gateway_runtime(
        Settings(
            database_url=disposable_database,
            lineage_enabled=True,
            program_reporting_enabled=True,
            relationship_intelligence_enabled=True,
        )
    )
    try:
        engine = gateway.program_read_engine
        assert engine is not None
        held = [engine.connect() for _ in range(engine.pool.size())]  # type: ignore[attr-defined]
        try:
            started = time.monotonic()
            envelope = _gateway_commit(
                gateway,
                runtime.report(
                    cycle,
                    SYNTH,
                    "budget-checkout",
                    dependencies=(researcher,),
                    structured_content=block,
                ),
            )
            elapsed = time.monotonic() - started
        finally:
            for connection in held:
                connection.close()
        assert envelope.error is None, envelope.error
        result = envelope.to_canonical_dict()["result"]
        section = _program_of(runtime.manifest(result["report_id"]))
        assert (section["verification_state"], section["recompute_failure"]) == (
            "recompute_failed",
            "pool_unavailable",
        )
        assert 0.9 <= elapsed < 2.0, elapsed
        assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    finally:
        gateway.close()


def _gateway_commit(
    gateway: GatewayRuntime, command: CommitIntelligenceArtifact
) -> ResponseEnvelope:
    """`reports.commit` through the gateway's own service, as the local operator."""
    return gateway.service.invoke(
        RequestMetadata(
            request_id=issue_identifier(IdKind.CORRELATION),
            capability=Capability.REPORTS_COMMIT,
            purpose=Purpose.REPORT_AUTHORING,
            principal_id=PRINCIPAL,
            requested_at=datetime.now(UTC),
        ),
        command,
        principal=Principal(
            principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
        ),
    )


@pytest.mark.parametrize(
    "missing",
    ["entity_plane", "program_factory", "constraint_plane"],
)
def test_not_attempted_when_programs_overview_is_not_served(
    disposable_database: str, missing: str
) -> None:
    composed = S4Runtime(
        disposable_database,
        relationship_intelligence_enabled=missing != "entity_plane",
        compose_program_reads=missing != "program_factory",
        compose_constraints=missing != "constraint_plane",
    )
    try:
        program, _project = _program(composed)
        cycle = composed.cycle(f"unserved-{missing}")
        researcher = composed.research(cycle, f"unserved-{missing}")
        claim = {"overview_sha256": "a" * 64, "source_cutoff_at": "2026-10-24T06:30:00.000000Z"}
        with _statements(("program", composed.program_engine)) as seen:
            synthesis = _synthesizer(
                composed,
                cycle,
                researcher,
                f"unserved-{missing}",
                composed.program_reference(claim, program),
            )
        assert seen == []
        section = _program_of(composed.manifest(synthesis["report_id"]))
        assert section == {
            "block_schema_version": 1,
            "program_entity_ids": [program],
            "claimed_overview_sha256": "a" * 64,
            "claimed_source_cutoff_at": "2026-10-24T06:30:00.000000Z",
            "verification_state": "not_attempted",
            "recompute_failure": None,
            "families_seen": None,
            "server": None,
        }
        # The block is still interpreted (the switches are on): a malformed one is refused.
        error = composed.refused(
            composed.report(
                cycle,
                SYNTH,
                f"unserved-{missing}-bad",
                dependencies=(researcher,),
                structured_content={PROGRAM_REFERENCE_BLOCK_KEY: {"block_schema_version": 1}},
            )
        )
        assert (error["code"], error["safe_details"]) == ("invalid_request", ["structured_content"])
    finally:
        composed.close()


def test_a_collector_cannot_carry_a_program_reference(runtime: S4Runtime) -> None:
    program, _project = _program(runtime)
    block = runtime.program_reference(runtime.overview(program), program)
    cycle = runtime.cycle("collector-block")
    researcher = runtime.research(cycle, "collector-block")
    before = _artifact_count(runtime.engine)
    collector = runtime.report(
        cycle, IntelligenceStage.COLLECTOR, "collector-block", structured_content=block
    )
    research = runtime.report(
        cycle,
        IntelligenceStage.RESEARCHER,
        "researcher-block",
        dependencies=(),
        structured_content=block,
    )
    malformed = runtime.report(
        cycle,
        SYNTH,
        "malformed-block",
        dependencies=(researcher,),
        structured_content={
            PROGRAM_REFERENCE_BLOCK_KEY: {**block[PROGRAM_REFERENCE_BLOCK_KEY], "extra": True}
        },  # type: ignore[dict-item]
    )
    for command in (collector, research, malformed):
        error = runtime.refused(command)
        assert (error["code"], error["safe_details"]) == ("invalid_request", ["structured_content"])
    assert _artifact_count(runtime.engine) == before


def test_a_collector_candidate_is_never_typed(runtime: S4Runtime) -> None:
    cycle = runtime.cycle("typed")
    reference = {"source_system": "procore", "source_ref": "RFI-0042", "relation": "supports"}
    collector = runtime.commit_report(
        runtime.report(cycle, IntelligenceStage.COLLECTOR, "typed", provenance=(reference,))
    )
    researcher = runtime.commit_report(
        runtime.report(
            cycle,
            IntelligenceStage.RESEARCHER,
            "typed-researcher",
            dependencies=(collector["report_id"],),
            provenance=(reference,),
        )
    )
    for answer, status in ((collector, "unaccepted_candidate"), (researcher, "not_a_candidate")):
        decoded = json.loads(runtime.manifest(answer["report_id"])["manifest_canonical"])
        assert decoded["candidate_status"] == status
        assert [row["certification"] for row in decoded["provenance"]] == ["uncertified_reference"]
        assert decoded["provenance"][0]["source_ref"] == "RFI-0042"
        # No field types a candidate or a reference as an RFI, a financial
        # fact or an accepted record.
        keys = json.dumps(sorted(_keys(decoded)))
        for forbidden in ("rfi", "financial", "accepted", "record_type", "source_type"):
            assert forbidden not in keys


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def test_a_replayed_commit_writes_no_second_manifest(runtime: S4Runtime) -> None:
    program, _project = _program(runtime)
    block = runtime.program_reference(runtime.overview(program), program)
    cycle = runtime.cycle("replay")
    researcher = runtime.research(cycle, "replay")
    first = _synthesizer(runtime, cycle, researcher, "replay", block)
    count = _manifest_count(runtime.engine)
    manifest = runtime.manifest(first["report_id"])
    with _statements(("program", runtime.program_engine)) as seen:
        again = _synthesizer(runtime, cycle, researcher, "replay", block)
    assert (again["replayed"], again["report_id"]) == (True, first["report_id"])
    assert seen == []
    assert _manifest_count(runtime.engine) == count
    assert runtime.manifest(first["report_id"]) == manifest


@pytest.mark.parametrize(
    ("lineage", "program_reporting"),
    [(True, False), (False, True)],
    ids=["program-switch-off", "lineage-off"],
)
def test_the_program_reference_is_ordinary_content_with_the_switch_off(
    disposable_database: str, lineage: bool, program_reporting: bool
) -> None:
    off = S4Runtime(
        disposable_database, lineage_enabled=lineage, program_reporting_enabled=program_reporting
    )
    try:
        program, _project = _program(off)
        claim = {"overview_sha256": "a" * 64, "source_cutoff_at": "2026-10-24T06:30:00.000000Z"}
        block = off.program_reference(claim, program)
        cycle = off.cycle("switch-off")
        with _statements(("program", off.program_engine)) as seen:
            # Not interpreted: a collector may carry the key, and a malformed
            # block on a synthesizer is ordinary content.
            collector = off.commit_report(
                off.report(
                    cycle, IntelligenceStage.COLLECTOR, "switch-off", structured_content=block
                )
            )
            researcher = off.commit_report(
                off.report(
                    cycle,
                    IntelligenceStage.RESEARCHER,
                    "switch-off-r",
                    dependencies=(collector["report_id"],),
                )
            )
            malformed = _synthesizer(
                off,
                cycle,
                str(researcher["report_id"]),
                "switch-off-s",
                {PROGRAM_REFERENCE_BLOCK_KEY: "anything"},
            )
        assert seen == []
        for answer in (collector, malformed):
            row = off.stored_manifest(answer["report_id"])
            assert row is not None
            assert json.loads(row["manifest_canonical"])["program"] is None
            assert (row["program_overview_sha256"], row["program_verification_state"]) == (
                None,
                None,
            )
        # The answer is the S3 one.
        assert set(collector) >= {"receipt_id", "report_id", "content_sha256"}
        assert "manifest_sha256" not in collector
    finally:
        off.close()


def test_a_report_reproduces_its_overview_digest_from_an_unchanged_state(
    runtime: S4Runtime,
) -> None:
    program, _project = _program(runtime)
    overview = runtime.overview(program)
    cycle = runtime.cycle("reproduce")
    researcher = runtime.research(cycle, "reproduce")
    synthesis = _synthesizer(
        runtime, cycle, researcher, "reproduce", runtime.program_reference(overview, program)
    )
    section = _program_of(runtime.manifest(synthesis["report_id"]))
    assert section["verification_state"] == "verified_at_commit"
    # Nothing changed: a later overview reproduces the digest the report names.
    again = runtime.overview(program)
    assert again["overview_sha256"] == overview["overview_sha256"]
    assert section["server"]["overview_sha256"] == again["overview_sha256"]
    assert again["source_cutoff_at"] >= section["server"]["source_cutoff_at"]
    assert datetime.now(UTC) >= datetime.fromisoformat(again["source_cutoff_at"])
