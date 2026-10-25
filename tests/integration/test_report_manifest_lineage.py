"""Record lineage S3.1: the `lineage_context_ref` block and the schema-2 manifest (database).

S3.1 contract section 7.9 through `ApplicationService.invoke` against
PostgreSQL (worker N4), on the S4 runtime (the Program-reporting switch and
the Intelligence pipeline) with the S3.1 client calls:

* a synthesizer, reporter or morning brief written from a
  `records.lineage.related` read cites it under `lineage_context_ref`; at
  commit the server recomputes the read with the committing caller's
  visibility and binds its own digest, counts and the families it saw beside
  the claim -- `verified_at_commit` or `changed_since_read`;
* a failed recompute (a missing seed, a cut after the horizon, a spent budget)
  is recorded as `recompute_failed` with its token and never refuses the
  commit; a replay never recomputes;
* a manifest with no interpreted block and no lineage-gated upstream stays
  schema 1, byte for byte as S4 builds it; a gated manifest -- and every
  downstream of one -- is schema 2 and is released to a remote reader only with
  a `records.lineage.related` grant and every family it names;
* with `records.lineage.related` not served the key is ordinary content, and a
  collector or researcher may not carry the block.

Every fixture writes at least 1 client fact with `user_directed: true`; the
manifest counts that claim and nothing reads it. Every identity and every body
here is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, text

import my_pa.application.record_lineage as lineage_module
import my_pa.application.service as service_module
from my_pa.application.commands import ReadRelatedRecords, ReadReportManifest
from my_pa.domain.intelligence.catalog import IntelligenceStage
from my_pa.domain.intelligence.source_manifest import manifest_digest
from my_pa.domain.lineage.vocabulary import LINEAGE_CONTEXT_BLOCK_KEY, RecordFamily
from tests.database.lineage_record_harness import NOTE_BODY, note_anchor
from tests.database.lineage_s2_harness import assertion
from tests.database.lineage_s3_read_harness import READS, Grants, grant, horizon
from tests.database.lineage_s31_harness import S31ReportRuntime, lineage_reference

pytestmark = pytest.mark.database

SYNTH: Final = IntelligenceStage.SYNTHESIZER
REPORTER: Final = IntelligenceStage.REPORTER
#: Every S3 section 6.4 family, as a local committer sees them.
ALL_FAMILIES: Final = sorted(family.value for family in RecordFamily)
#: A remote client that reads related records and commits reports, seeing every family.
FULL: Final[Grants] = grant("records.lineage.related", "reports.commit", *READS)
#: The same client without the Meeting reads: Meetings and note versions are hidden.
NO_MEETINGS: Final[Grants] = grant(
    "records.lineage.related",
    "reports.commit",
    *(read for read in READS if read != "meetings.read"),
)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31ReportRuntime]:
    composed = S31ReportRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _scene(runtime: S31ReportRuntime, key: str) -> dict[str, str]:
    """Issue I with an operator `work` member T; a client says, claimed, that note N discusses T."""
    issue = runtime.issue(f"{key}-issue")
    task = runtime.task(f"{key}-t")
    meeting_id, note_id = runtime.note(f"{key}-n")
    runtime.member(issue, "task", task, f"{key}-t", "work")
    runtime.client_ok(
        replace(
            assertion(
                "discusses",
                ("meeting_note_version", note_id),
                ("task", task),
                f"{key}-discusses",
                (note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion"),),
                context=issue,
            ),
            user_directed=True,
        )
    )
    return {"issue": issue, "task": task, "meeting": meeting_id, "note": note_id}


def _related(task: str, known_at: str) -> ReadRelatedRecords:
    return ReadRelatedRecords(
        seeds=({"family": "task", "record_id": task},),
        acceptance_bases=("user_confirmed", "client_identified"),
        known_at=known_at,
    )


def _read(runtime: S31ReportRuntime, task: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    """`records.lineage.related` from Task `task` at the current horizon, pinned."""
    return runtime.ok(_related(task, horizon(runtime.engine)), **kwargs)


def _commit(
    runtime: S31ReportRuntime,
    cycle: str,
    stage: IntelligenceStage,
    key: str,
    content: dict[str, object] | None,
    *,
    dependencies: tuple[str, ...] = (),
    **kwargs: Any,  # noqa: ANN401
) -> dict[str, Any]:
    return runtime.commit_report(
        runtime.report(cycle, stage, key, dependencies=dependencies, structured_content=content),
        **kwargs,
    )


def _decoded(runtime: S31ReportRuntime, report_id: str) -> dict[str, Any]:
    """The stored manifest of `report_id`, decoded (by SQL, so no release rule applies)."""
    row = runtime.stored_manifest(report_id)
    assert row is not None
    decoded = json.loads(row["manifest_canonical"])
    assert decoded["manifest_schema_version"] == row["manifest_schema_version"]
    assert manifest_digest(row["manifest_canonical"]) == row["manifest_sha256"]
    assert isinstance(decoded, dict)
    return decoded


def _manifest_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.intelligence_artifact_manifests")
            ).scalar_one()
        )


def _synthesis(
    runtime: S31ReportRuntime,
    key: str,
    content: dict[str, object] | None,
    **kwargs: Any,  # noqa: ANN401
) -> tuple[str, dict[str, Any]]:
    """A cycle, a researcher and a synthesizer carrying `content`: `(cycle, commit answer)`."""
    cycle = runtime.cycle(key)
    researcher = runtime.research(cycle, key)
    return cycle, _commit(
        runtime, cycle, SYNTH, f"{key}-synth", content, dependencies=(researcher,), **kwargs
    )


def test_a_lineage_reference_binds_the_server_state_and_provenance_counts(
    runtime: S31ReportRuntime,
) -> None:
    scene = _scene(runtime, "lmf-bind")
    answer = _read(runtime, scene["task"])
    block = lineage_reference(answer, (("task", scene["task"]),))
    _, synthesis = _synthesis(runtime, "lmf-bind", block)
    decoded = _decoded(runtime, synthesis["report_id"])
    assert decoded["manifest_schema_version"] == 2
    lineage = decoded["lineage"]
    claim = block[LINEAGE_CONTEXT_BLOCK_KEY]
    assert isinstance(claim, dict)
    assert lineage == {
        "block_schema_version": 1,
        "seeds": [{"family": "task", "record_id": scene["task"]}],
        "max_depth": 2,
        "acceptance_bases": ["user_confirmed", "client_identified"],
        "relation_types": claim["relation_types"],
        "claimed_known_at": answer["known_at"],
        "claimed_related_sha256": answer["related_sha256"],
        "verification_state": "verified_at_commit",
        "recompute_failure": None,
        "families_seen": ALL_FAMILIES,
        "server": {
            "related_sha256": answer["related_sha256"],
            "known_at": answer["known_at"],
            "complete_state": answer["complete_state"],
            "qualifiers": answer["qualifiers"],
            "record_count": len(answer["records"]),
            "link_count": 2,
            "links_by_acceptance_basis": {"client_identified": 1, "user_confirmed": 1},
            "user_directed_claims": 1,
        },
    }
    assert len(answer["links"]) == 2
    assert decoded["release_requirement"] == {
        "program_grant": False,
        "families": [],
        "lineage_grant": True,
        "lineage_families": ALL_FAMILIES,
    }
    # The block is the artifact's own content, unchanged; the manifest binds it.
    stored = runtime.stored_manifest(synthesis["report_id"])
    assert stored is not None
    assert stored["manifest_schema_version"] == 2
    assert stored["program_overview_sha256"] is None
    assert decoded["structured_content"]["present"] is True
    # Nothing about the recompute is in the commit answer.
    assert "lineage" not in synthesis and "verification_state" not in synthesis


def test_a_changed_lineage_source_is_recorded_changed_since_read(
    runtime: S31ReportRuntime,
) -> None:
    scene = _scene(runtime, "lmf-changed")
    seeds = (("task", scene["task"]),)
    # A remote client reads seeing every family, then commits without the
    # Meeting reads: the server recomputes with the visibility it has now.
    seen = runtime.client_ok(_related(scene["task"], horizon(runtime.engine)), grants=FULL)
    _, narrowed = _synthesis(
        runtime, "lmf-changed", lineage_reference(seen, seeds), grants=NO_MEETINGS
    )
    lineage = _decoded(runtime, narrowed["report_id"])["lineage"]
    assert lineage["verification_state"] == "changed_since_read"
    assert lineage["recompute_failure"] is None
    assert lineage["claimed_related_sha256"] == seen["related_sha256"]
    assert lineage["server"]["related_sha256"] != seen["related_sha256"]
    hidden = {RecordFamily.MEETING.value, RecordFamily.MEETING_NOTE_VERSION.value}
    assert lineage["families_seen"] == [family for family in ALL_FAMILIES if family not in hidden]
    # The client's discussion link names a hidden note: neither emitted nor counted.
    assert lineage["server"]["links_by_acceptance_basis"] == {
        "client_identified": 0,
        "user_confirmed": 1,
    }
    assert lineage["server"]["user_directed_claims"] == 0
    # The same visibility as the read reproduces it.
    _, same = _synthesis(runtime, "lmf-same", lineage_reference(seen, seeds), grants=FULL)
    assert _decoded(runtime, same["report_id"])["lineage"]["verification_state"] == (
        "verified_at_commit"
    )
    # A claimed digest the server does not compute is changed too.
    local = _read(runtime, scene["task"])
    _, claimed = _synthesis(
        runtime, "lmf-claimed", lineage_reference(local, seeds, related_sha256="0" * 64)
    )
    lineage = _decoded(runtime, claimed["report_id"])["lineage"]
    assert lineage["verification_state"] == "changed_since_read"
    assert lineage["server"]["related_sha256"] == local["related_sha256"]


def test_a_failed_lineage_recompute_never_refuses_the_commit(
    runtime: S31ReportRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = _scene(runtime, "lmf-fail")
    answer = _read(runtime, scene["task"])
    absent = "tsk_" + "Z" * 26
    # A seed that does not exist (absent and foreign alike).
    _, missing = _synthesis(runtime, "lmf-missing", lineage_reference(answer, (("task", absent),)))
    # A cut after the Principal's commit horizon.
    later = datetime.strptime(answer["known_at"], "%Y-%m-%dT%H:%M:%S.%fZ") + timedelta(
        microseconds=1
    )
    beyond = dict(answer, known_at=later.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    _, past = _synthesis(
        runtime, "lmf-horizon", lineage_reference(beyond, (("task", scene["task"]),))
    )
    # A spent budget: the first statement of the recompute is never sent.
    monkeypatch.setattr(lineage_module, "LINEAGE_RECOMPUTE_BUDGET_SECONDS", 0.0)
    _, spent = _synthesis(
        runtime, "lmf-budget", lineage_reference(answer, (("task", scene["task"]),))
    )
    for written, token, families in (
        (missing, "seed_not_found", ["task"]),
        (past, "cut_beyond_horizon", ["task"]),
        (spent, "budget_exceeded", ["task"]),
    ):
        decoded = _decoded(runtime, written["report_id"])
        lineage = decoded["lineage"]
        assert decoded["manifest_schema_version"] == 2
        assert lineage["verification_state"] == "recompute_failed", token
        assert lineage["recompute_failure"] == token
        assert lineage["server"] is None and lineage["families_seen"] is None
        # Still gated: the seeds' families, and the related grant.
        assert decoded["release_requirement"]["lineage_grant"] is True
        assert decoded["release_requirement"]["lineage_families"] == families
    # Each commit wrote its artifact and its manifest: nothing was refused.
    assert runtime.manifest(spent["report_id"])["manifest_state"] == "recorded"


def test_a_manifest_without_a_lineage_reference_stays_schema_1(
    runtime: S31ReportRuntime,
) -> None:
    scene = _scene(runtime, "lmf-plain")
    cycle, plain = _synthesis(runtime, "lmf-plain", {"metric": 1})
    decoded = _decoded(runtime, plain["report_id"])
    assert decoded["manifest_schema_version"] == 1
    assert "lineage" not in decoded
    assert decoded["release_requirement"] == {"program_grant": False, "families": []}
    # A not-attempted reference gates nothing, so its downstream stays schema 1.
    answer = _read(runtime, scene["task"])
    outside = runtime.client_ok(
        ReadReportManifest(report_id=plain["report_id"]), grants=grant("reports.manifest")
    )
    assert outside["manifest_state"] == "recorded"
    unadmitted = grant("reports.commit", *READS)
    researcher = runtime.research(cycle, "lmf-plain-2")
    unattempted = _commit(
        runtime,
        cycle,
        SYNTH,
        "lmf-plain-unattempted",
        lineage_reference(answer, (("task", scene["task"]),)),
        dependencies=(researcher,),
        grants=unadmitted,
    )
    section = _decoded(runtime, unattempted["report_id"])
    assert section["manifest_schema_version"] == 2
    assert section["lineage"]["verification_state"] == "not_attempted"
    assert section["lineage"]["server"] is None
    assert section["release_requirement"]["lineage_grant"] is False
    assert section["release_requirement"]["lineage_families"] == []
    reporter = _commit(
        runtime,
        cycle,
        REPORTER,
        "lmf-plain-reporter",
        None,
        dependencies=(unattempted["report_id"],),
    )
    downstream = _decoded(runtime, reporter["report_id"])
    assert downstream["manifest_schema_version"] == 1
    assert "lineage" not in downstream
    assert set(downstream["release_requirement"]) == {"program_grant", "families"}


def test_a_lineage_section_needs_the_related_grant_and_every_family(
    runtime: S31ReportRuntime,
) -> None:
    scene = _scene(runtime, "lmf-release")
    answer = _read(runtime, scene["task"])
    _, gated = _synthesis(
        runtime, "lmf-release", lineage_reference(answer, (("task", scene["task"]),))
    )
    report_id = gated["report_id"]
    command = ReadReportManifest(report_id=report_id)
    assert runtime.manifest(report_id)["manifest_state"] == "recorded"
    for grants in (
        grant("reports.manifest", *READS),
        grant("reports.manifest", "records.lineage.related"),
        grant(
            "reports.manifest",
            "records.lineage.related",
            *(read for read in READS if read != "capture.read"),
        ),
    ):
        withheld = runtime.client_ok(command, grants=grants)
        assert withheld == {
            "report_id": report_id,
            "manifest_state": "restricted_evidence",
            "manifest_schema_version": 2,
            "manifest_sha256": None,
            "manifest_canonical": None,
        }, sorted(capability.value for capability, _ in grants)
    released = runtime.client_ok(
        command, grants=grant("reports.manifest", "records.lineage.related", *READS)
    )
    assert released["manifest_state"] == "recorded"
    assert manifest_digest(released["manifest_canonical"]) == released["manifest_sha256"]


def test_a_downstream_inherits_a_lineage_gate(runtime: S31ReportRuntime) -> None:
    scene = _scene(runtime, "lmf-inherit")
    answer = _read(runtime, scene["task"])
    cycle, gated = _synthesis(
        runtime, "lmf-inherit", lineage_reference(answer, (("task", scene["task"]),))
    )
    reporter = _commit(
        runtime, cycle, REPORTER, "lmf-inherit-reporter", None, dependencies=(gated["report_id"],)
    )
    brief = _commit(
        runtime,
        cycle,
        IntelligenceStage.MORNING_BRIEF,
        "lmf-inherit-brief",
        None,
        dependencies=(reporter["report_id"],),
    )
    for report_id in (reporter["report_id"], brief["report_id"]):
        decoded = _decoded(runtime, report_id)
        assert decoded["manifest_schema_version"] == 2
        assert decoded["lineage"] is None
        assert decoded["release_requirement"] == {
            "program_grant": False,
            "families": [],
            "lineage_grant": True,
            "lineage_families": ALL_FAMILIES,
        }
        withheld = runtime.client_ok(
            ReadReportManifest(report_id=report_id), grants=grant("reports.manifest", *READS)
        )
        assert withheld["manifest_state"] == "restricted_evidence"
        assert withheld["manifest_sha256"] is None


def test_the_lineage_reference_is_ordinary_content_when_related_is_not_served(
    disposable_database: str,
) -> None:
    switched_off = S31ReportRuntime(disposable_database, lineage_enabled=False)
    try:
        cycle = switched_off.cycle("lmf-off")
        researcher = switched_off.research(cycle, "lmf-off")
        # Malformed as a block and on a researcher's downstream: ordinary content.
        content: dict[str, object] = {LINEAGE_CONTEXT_BLOCK_KEY: {"anything": [1, 2]}}
        written = _commit(
            switched_off, cycle, SYNTH, "lmf-off-synth", content, dependencies=(researcher,)
        )
        decoded = _decoded(switched_off, written["report_id"])
        assert decoded["manifest_schema_version"] == 1
        assert "lineage" not in decoded
        assert set(decoded["release_requirement"]) == {"program_grant", "families"}
    finally:
        switched_off.close()


def test_a_collector_cannot_carry_a_lineage_reference(runtime: S31ReportRuntime) -> None:
    scene = _scene(runtime, "lmf-collector")
    answer = _read(runtime, scene["task"])
    block = lineage_reference(answer, (("task", scene["task"]),))
    cycle = runtime.cycle("lmf-collector")
    before = _manifest_count(runtime.engine)
    collector = runtime.refused(
        runtime.report(
            cycle, IntelligenceStage.COLLECTOR, "lmf-collector-c", structured_content=block
        )
    )
    assert (collector["code"], collector["safe_details"]) == (
        "invalid_request",
        ["structured_content"],
    )
    researcher = runtime.refused(
        runtime.report(
            cycle, IntelligenceStage.RESEARCHER, "lmf-collector-r", structured_content=block
        )
    )
    assert researcher["code"] == "invalid_request"
    claim = block[LINEAGE_CONTEXT_BLOCK_KEY]
    assert isinstance(claim, dict)
    upstream = runtime.research(cycle, "lmf-collector")
    after_research = _manifest_count(runtime.engine)
    for malformed in (
        {**claim, "max_depth": 4},
        {**claim, "seeds": []},
        {**claim, "acceptance_bases": ["client_identified", "client_identified"]},
        {**claim, "known_at": "2026-10-25T00:00:00Z"},
        {**claim, "block_schema_version": True},
        {key: value for key, value in claim.items() if key != "related_sha256"},
    ):
        refused = runtime.refused(
            runtime.report(
                cycle,
                SYNTH,
                "lmf-collector-bad",
                dependencies=(upstream,),
                structured_content={LINEAGE_CONTEXT_BLOCK_KEY: malformed},
            )
        )
        assert (refused["code"], refused["safe_details"]) == (
            "invalid_request",
            ["structured_content"],
        ), malformed
    assert before + 2 == after_research == _manifest_count(runtime.engine)


def test_a_replayed_commit_never_recomputes_the_lineage_reference(
    runtime: S31ReportRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = _scene(runtime, "lmf-replay")
    answer = _read(runtime, scene["task"])
    block = lineage_reference(answer, (("task", scene["task"]),))
    calls: list[str] = []
    original = service_module.recompute_lineage_reference

    def counted(*args: Any, **kwargs: Any) -> dict[str, object]:  # noqa: ANN401
        calls.append("recompute")
        return original(*args, **kwargs)

    monkeypatch.setattr(service_module, "recompute_lineage_reference", counted)
    cycle = runtime.cycle("lmf-replay")
    researcher = runtime.research(cycle, "lmf-replay")
    command = runtime.report(
        cycle, SYNTH, "lmf-replay-synth", dependencies=(researcher,), structured_content=block
    )
    first = runtime.commit_report(command)
    count = _manifest_count(runtime.engine)
    seen: list[str] = []

    def record(_connection: object, _cursor: object, statement: str, *_rest: object) -> None:
        seen.append(statement)

    event.listen(runtime.engine, "before_cursor_execute", record)
    try:
        again = runtime.commit_report(command)
    finally:
        event.remove(runtime.engine, "before_cursor_execute", record)
    assert again["replayed"] is True and again["report_id"] == first["report_id"]
    assert calls == ["recompute"]
    assert _manifest_count(runtime.engine) == count
    assert not [statement for statement in seen if "record_link" in statement]
    assert _decoded(runtime, first["report_id"])["lineage"]["verification_state"] == (
        "verified_at_commit"
    )
