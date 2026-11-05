"""Reports Modernization WP04, contract C2-C8: the catalog read queries on PostgreSQL.

The `database` tier, one disposable head-migrated clone per test
(`migrated_engine`). What it proves, for `GeneralReportRepository.catalog_page`
and the legacy `SqlIntelligenceStore.catalog_page`:

* every filter alone and combined: type, topics and tags (all-of, `@>` on the
  head), `associated_with` (an association of the HEAD version; a foreign or
  nonexistent target matches nothing), lifecycle states (default `active`
  only), the half-open created range and the inclusive report-date range
  (a NULL report date never matches a bound);
* isolation: another Principal's reports are never returned, in a list or a
  search, and a forged cursor position copied from another Principal's row
  only narrows the caller's own rows;
* search over title, summary, topics, tags and body; never a JSON key or the
  Base64 spelling of a word; only the HEAD version is searched; the rank and
  its tie-breaks;
* the keyset: page sizes 1..3 over rows with identical `created_at`
  (`committed_at`) and ids that differ only by letter case walk the exact
  `COLLATE "C"` order with no skip and no duplicate;
* the legacy plane: current artifacts only, the exclusion rules, the order,
  ties, search and the mapped filters.

Report ids are forced, where a test needs them, by replacing the repository
module's `issue_identifier` for the report kind only. Every identifier, title
and byte is synthetic.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Connection, Engine

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    STAGE_FOR_KIND,
    ArtifactKind,
    ArtifactState,
    CycleState,
    FocusAreaId,
    ProducerRunState,
)
from my_pa.domain.intelligence.models import (
    IntelligenceArtifact,
    IntelligenceCycleRun,
    IntelligenceProducerRun,
    content_digest,
)
from my_pa.domain.reports.catalog import (
    AssociationFilter,
    CatalogCursor,
    CatalogCursorError,
    CatalogFilters,
)
from my_pa.domain.reports.content import validate_content
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.publication import PublicationRequest, RequestedAssociation
from my_pa.domain.reports.records import CatalogEntry
from my_pa.domain.reports.revision import LifecycleRequest, ReportPatch, UpdateRequest
from my_pa.domain.reports.vocabulary import (
    AssociationTargetKind,
    LifecycleOperation,
    LifecycleState,
)
from my_pa.domain.search.query import SearchQuery
from my_pa.domain.source import registry
from my_pa.infrastructure.persistence.intelligence import SqlIntelligenceStore
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from tests.database.test_reports_general_persistence import PRINCIPAL_A, PRINCIPAL_B

pytestmark = pytest.mark.database

T0: Final = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
BINDING: Final = "0" * 64
ALL_STATES: Final = CatalogFilters(
    lifecycle_states=frozenset(
        {LifecycleState.ACTIVE, LifecycleState.ARCHIVED, LifecycleState.TRASHED}
    )
)
STANDALONE: Final = AssociationTargetKind.STANDALONE_REPORT
_REPORTS_MODULE: Final = "my_pa.infrastructure.persistence.reports"

_KEYS: dict[str, int] = {"n": 0}


def _key(prefix: str) -> str:
    _KEYS["n"] += 1
    return f"{prefix}-{_KEYS['n']}"


@contextmanager
def _forced_report_id(report_id: str | None) -> Iterator[None]:
    """Make the next report id `report_id`; every other kind stays random."""
    if report_id is None:
        yield
        return
    original = registry.issue_identifier

    def issue(kind: IdKind) -> str:
        return report_id if kind is IdKind.REPORT else original(kind)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(f"{_REPORTS_MODULE}.issue_identifier", issue)
        yield


def _publish(
    engine: Engine,
    *,
    created_at: datetime = T0,
    principal_id: str = PRINCIPAL_A,
    report_id: str | None = None,
    title: str = "Plain catalog title",
    body: str = "plain body",
    content: dict[str, object] | None = None,
    report_type: str | None = "synthetic_note",
    topics: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    summary: str | None = None,
    report_date: date | None = None,
    associations: tuple[RequestedAssociation, ...] = (),
) -> str:
    request = PublicationRequest(
        title=title,
        content=validate_content(content or {"format": "markdown", "body": body}),
        report_type=report_type,
        topics=topics,
        tags=tags,
        summary=summary,
        report_date=report_date,
        associations=associations,
    )
    with _forced_report_id(report_id), engine.begin() as connection:
        result = SqlGeneralReportRepository(connection).publish(
            request,
            principal_id=principal_id,
            idempotency_key=_key("pub"),
            recorded_at=created_at,
            correlation_id=registry.issue_identifier(IdKind.CORRELATION),
            audit_id=registry.issue_identifier(IdKind.AUDIT),
        )
    return result.receipt.report_id


def _update(engine: Engine, report_id: str, expected: int, patch: ReportPatch) -> None:
    with engine.begin() as connection:
        SqlGeneralReportRepository(connection).update(
            UpdateRequest(
                report_id=report_id,
                expected_version=expected,
                patch=patch,
                change_reason="Synthetic change.",
            ),
            principal_id=PRINCIPAL_A,
            idempotency_key=_key("upd"),
            recorded_at=T0 + timedelta(days=1),
            correlation_id=registry.issue_identifier(IdKind.CORRELATION),
            audit_id=registry.issue_identifier(IdKind.AUDIT),
        )


def _transition(engine: Engine, report_id: str, operation: LifecycleOperation) -> None:
    with engine.begin() as connection:
        SqlGeneralReportRepository(connection).transition(
            LifecycleRequest(operation, report_id, 0),
            principal_id=PRINCIPAL_A,
            idempotency_key=_key("life"),
            recorded_at=T0 + timedelta(days=1),
            correlation_id=registry.issue_identifier(IdKind.CORRELATION),
            audit_id=registry.issue_identifier(IdKind.AUDIT),
        )


def _page(
    engine: Engine,
    filters: CatalogFilters | None = None,
    *,
    query: str | None = None,
    after: CatalogCursor | None = None,
    limit: int = 50,
    principal_id: str = PRINCIPAL_A,
) -> tuple[CatalogEntry, ...]:
    with engine.connect() as connection:
        return SqlGeneralReportRepository(connection).catalog_page(
            principal_id=principal_id,
            filters=filters or CatalogFilters(),
            query=None if query is None else SearchQuery(query),
            after=after,
            limit=limit,
        )


def _ids(entries: Sequence[CatalogEntry]) -> list[str]:
    return [entry.report_id for entry in entries]


def _cursor_after(entry: CatalogEntry) -> CatalogCursor:
    return CatalogCursor(
        binding=BINDING, sort_time=entry.created_at, report_id=entry.report_id, rank=entry.rank
    )


def _walk(
    engine: Engine, size: int, filters: CatalogFilters | None = None, *, query: str | None = None
) -> list[str]:
    """Every row, page by page (`limit` = size + 1, as the service asks)."""
    seen: list[str] = []
    after: CatalogCursor | None = None
    for _ in range(100):
        rows = _page(engine, filters, query=query, after=after, limit=size + 1)
        page = rows[:size]
        seen.extend(_ids(page))
        if len(rows) <= size:
            return seen
        after = _cursor_after(page[-1])
    raise AssertionError("the walk did not end")


# ---- list order and fields --------------------------------------------------------


def test_list_is_newest_first_with_head_fields_and_no_rank(migrated_engine: Engine) -> None:
    old = _publish(migrated_engine, created_at=T0, title="Oldest")
    mid = _publish(migrated_engine, created_at=T0 + timedelta(hours=1), title="Middle")
    new = _publish(
        migrated_engine,
        created_at=T0 + timedelta(hours=2),
        title="Newest",
        topics=("alpha",),
        tags=("t1",),
        summary="A summary.",
        report_date=date(2026, 11, 1),
    )
    _update(migrated_engine, old, 1, ReportPatch(title="Oldest retitled"))
    entries = _page(migrated_engine)
    assert _ids(entries) == [new, mid, old]
    newest, _middle, oldest = entries
    assert (newest.title, newest.report_type, newest.topics, newest.tags) == (
        "Newest",
        "synthetic_note",
        ("alpha",),
        ("t1",),
    )
    assert (newest.summary, newest.report_date) == ("A summary.", date(2026, 11, 1))
    assert (newest.rank, newest.snippet) == (None, None)
    assert newest.lifecycle_state is LifecycleState.ACTIVE and newest.lifecycle_revision == 0
    # The head version's metadata; created_at stays the root's, updated_at moves.
    assert oldest.title == "Oldest retitled" and oldest.head_version_number == 2
    assert oldest.created_at == T0
    assert oldest.updated_at == T0 + timedelta(days=1)


def test_limit_and_cursor_shape_are_checked(migrated_engine: Engine) -> None:
    _publish(migrated_engine)
    for limit in (0, 102, True):
        with pytest.raises(ReportValidationError):
            _page(migrated_engine, limit=limit)
    assert len(_page(migrated_engine, limit=101)) == 1
    search_cursor = CatalogCursor(binding=BINDING, sort_time=T0, report_id="grpt_zzzzzzzz", rank=5)
    list_cursor = CatalogCursor(binding=BINDING, sort_time=T0, report_id="grpt_zzzzzzzz")
    with pytest.raises(CatalogCursorError):
        _page(migrated_engine, after=search_cursor)
    with pytest.raises(CatalogCursorError):
        _page(migrated_engine, query="plain", after=list_cursor)


# ---- filters --------------------------------------------------------------------


def _filter_corpus(engine: Engine) -> dict[str, str]:
    return {
        "a": _publish(
            engine,
            created_at=T0,
            report_type="meeting_note",
            topics=("alpha", "beta"),
            tags=("red", "blue"),
            report_date=date(2026, 11, 1),
        ),
        "b": _publish(
            engine,
            created_at=T0 + timedelta(hours=1),
            report_type="meeting_note",
            topics=("alpha",),
            tags=("red",),
            report_date=date(2026, 11, 2),
        ),
        "c": _publish(
            engine,
            created_at=T0 + timedelta(hours=2),
            report_type="weekly_digest",
            topics=("beta",),
            tags=("blue",),
            report_date=None,
        ),
        "d": _publish(
            engine,
            created_at=T0 + timedelta(hours=3),
            report_type=None,
            topics=(),
            tags=(),
            report_date=date(2026, 11, 3),
        ),
    }


def test_each_filter_alone_and_combined(migrated_engine: Engine) -> None:
    r = _filter_corpus(migrated_engine)
    a, b, c, d = r["a"], r["b"], r["c"], r["d"]

    def ids(**fields: object) -> list[str]:
        return _ids(_page(migrated_engine, CatalogFilters(**fields)))  # type: ignore[arg-type]

    assert ids() == [d, c, b, a]
    assert ids(report_type="meeting_note") == [b, a]
    assert ids(report_type="unknown_kind") == []
    # topics/tags: all of the listed terms.
    assert ids(topics=("alpha",)) == [b, a]
    assert ids(topics=("alpha", "beta")) == [a]
    assert ids(topics=("beta",)) == [c, a]
    assert ids(tags=("red", "blue")) == [a]
    assert ids(tags=("blue",)) == [c, a]
    assert ids(topics=("gamma",)) == []
    # created: half-open [from, to).
    assert ids(created_from=T0 + timedelta(hours=1)) == [d, c, b]
    assert ids(created_to=T0 + timedelta(hours=1)) == [a]
    assert ids(created_from=T0 + timedelta(hours=1), created_to=T0 + timedelta(hours=3)) == [c, b]
    # report date: inclusive; NULL never matches a bound.
    assert ids(report_date_from=date(2026, 11, 2)) == [d, b]
    assert ids(report_date_to=date(2026, 11, 2)) == [b, a]
    assert ids(report_date_from=date(2026, 11, 2), report_date_to=date(2026, 11, 2)) == [b]
    assert c not in ids(report_date_from=date(2000, 1, 1))
    assert c not in ids(report_date_to=date(2100, 1, 1))
    # combined
    assert ids(report_type="meeting_note", topics=("alpha",), tags=("blue",)) == [a]
    assert (
        ids(
            topics=("beta",),
            created_from=T0 + timedelta(hours=1),
            report_date_to=date(2026, 12, 31),
        )
        == []
    )
    assert ids(report_type="meeting_note", report_date_from=date(2026, 11, 2)) == [b]


def test_default_lifecycle_is_active_and_withdrawn_appear_only_when_listed(
    migrated_engine: Engine,
) -> None:
    active = _publish(migrated_engine, created_at=T0)
    archived = _publish(migrated_engine, created_at=T0 + timedelta(hours=1))
    trashed = _publish(migrated_engine, created_at=T0 + timedelta(hours=2))
    _transition(migrated_engine, archived, LifecycleOperation.ARCHIVE)
    _transition(migrated_engine, trashed, LifecycleOperation.DELETE)

    def ids(*states: LifecycleState, query: str | None = None) -> list[str]:
        filters = CatalogFilters(lifecycle_states=frozenset(states)) if states else None
        return _ids(_page(migrated_engine, filters, query=query))

    assert ids() == [active]
    assert ids(query="plain") == [active]
    assert ids(LifecycleState.ARCHIVED) == [archived]
    assert ids(LifecycleState.TRASHED) == [trashed]
    assert ids(LifecycleState.ARCHIVED, LifecycleState.TRASHED, query="plain") == [
        trashed,
        archived,
    ]
    entries = _page(migrated_engine, ALL_STATES)
    assert _ids(entries) == [trashed, archived, active]
    assert [entry.lifecycle_state for entry in entries] == [
        LifecycleState.TRASHED,
        LifecycleState.ARCHIVED,
        LifecycleState.ACTIVE,
    ]
    assert [entry.lifecycle_revision for entry in entries] == [1, 1, 0]


def test_association_filter_reads_the_head_version_in_the_callers_scope(
    migrated_engine: Engine,
) -> None:
    target_y = _publish(migrated_engine, created_at=T0, title="Target Y")
    target_z = _publish(migrated_engine, created_at=T0 + timedelta(minutes=1), title="Target Z")
    linked = _publish(
        migrated_engine,
        created_at=T0 + timedelta(hours=1),
        associations=(RequestedAssociation(STANDALONE, target_y, "about"),),
    )
    foreign_target = _publish(migrated_engine, principal_id=PRINCIPAL_B, title="Foreign")
    _publish(
        migrated_engine,
        principal_id=PRINCIPAL_B,
        associations=(RequestedAssociation(STANDALONE, foreign_target, "about"),),
    )

    def ids(ref: str, *, principal_id: str = PRINCIPAL_A) -> list[str]:
        filters = CatalogFilters(associated_with=AssociationFilter(STANDALONE, ref))
        return _ids(_page(migrated_engine, filters, principal_id=principal_id))

    assert ids(target_y) == [linked]
    assert ids(target_z) == []
    # A foreign target, and one that does not exist, simply match nothing.
    assert ids(foreign_target) == []
    assert ids("grpt_doesnotexist0001") == []
    # The other Principal sees its own association, and never A's.
    assert len(ids(foreign_target, principal_id=PRINCIPAL_B)) == 1
    assert ids(target_y, principal_id=PRINCIPAL_B) == []
    # Only the HEAD version's associations count.
    _update(
        migrated_engine,
        linked,
        1,
        ReportPatch(associations=(RequestedAssociation(STANDALONE, target_z, "about"),)),
    )
    assert ids(target_y) == []
    assert ids(target_z) == [linked]


# ---- isolation ------------------------------------------------------------------


def test_another_principals_reports_are_never_returned(migrated_engine: Engine) -> None:
    mine = _publish(migrated_engine, title="Shared word kestrel")
    theirs = _publish(migrated_engine, principal_id=PRINCIPAL_B, title="Shared word kestrel")
    assert _ids(_page(migrated_engine, ALL_STATES)) == [mine]
    assert _ids(_page(migrated_engine, query="kestrel")) == [mine]
    assert _ids(_page(migrated_engine, query="kestrel", principal_id=PRINCIPAL_B)) == [theirs]


def test_a_forged_foreign_cursor_position_only_narrows_the_callers_rows(
    migrated_engine: Engine,
) -> None:
    mine = [
        _publish(migrated_engine, created_at=T0 + timedelta(hours=hour), title="Heron")
        for hour in range(4)
    ]
    theirs = _publish(
        migrated_engine,
        principal_id=PRINCIPAL_B,
        created_at=T0 + timedelta(hours=1, minutes=30),
        title="Heron",
    )
    (foreign_entry,) = _page(migrated_engine, principal_id=PRINCIPAL_B)
    assert foreign_entry.report_id == theirs
    listed = _page(migrated_engine, after=_cursor_after(foreign_entry))
    assert _ids(listed) == [mine[1], mine[0]]
    (foreign_hit,) = _page(migrated_engine, query="heron", principal_id=PRINCIPAL_B)
    searched = _page(migrated_engine, query="heron", after=_cursor_after(foreign_hit))
    assert theirs not in _ids(searched)
    assert set(_ids(searched)) <= set(mine)
    assert _ids(searched) == [mine[1], mine[0]]


# ---- search ---------------------------------------------------------------------


def test_search_reaches_title_summary_topics_tags_and_body(migrated_engine: Engine) -> None:
    by_title = _publish(migrated_engine, title="Albatross migration")
    by_summary = _publish(migrated_engine, summary="Notes about the pelican colony.")
    by_topic = _publish(migrated_engine, topics=("cormorant",))
    by_tag = _publish(migrated_engine, tags=("puffin",))
    by_body = _publish(migrated_engine, body="# Heading\n\nThe gannet dives.")
    by_json = _publish(
        migrated_engine,
        content={"format": "json", "data": {"hiddenkeyword": "visibleshearwater", "n": 98765}},
    )
    assert _ids(_page(migrated_engine, query="albatross")) == [by_title]
    assert _ids(_page(migrated_engine, query="pelican")) == [by_summary]
    assert _ids(_page(migrated_engine, query="cormorant")) == [by_topic]
    assert _ids(_page(migrated_engine, query="puffin")) == [by_tag]
    assert _ids(_page(migrated_engine, query="gannet")) == [by_body]
    assert _ids(_page(migrated_engine, query="visibleshearwater")) == [by_json]
    assert _page(migrated_engine, query="hiddenkeyword") == ()
    assert _page(migrated_engine, query="98765") == ()
    # Never the Base64 spelling of a word.
    encoded = base64.b64encode(b"The gannet dives.").decode("ascii")
    assert _page(migrated_engine, query=encoded) == ()
    assert _page(migrated_engine, query=base64.b64encode(b"gannet").decode("ascii")) == ()
    # websearch syntax: a phrase and an exclusion.
    assert _ids(_page(migrated_engine, query='"albatross migration"')) == [by_title]
    assert _page(migrated_engine, query="albatross -migration") == ()
    (hit,) = _page(migrated_engine, query="pelican")
    assert hit.rank is not None and hit.rank > 0
    assert hit.snippet is not None and "<b>pelican</b>" in hit.snippet
    (titled,) = _page(migrated_engine, query="albatross")
    # No summary: the headline is over the title.
    assert titled.snippet == "<b>Albatross</b> migration"


def test_only_the_head_version_is_searched(migrated_engine: Engine) -> None:
    report = _publish(migrated_engine, body="The wandering oldlexeme.", title="Versioned")
    assert _ids(_page(migrated_engine, query="oldlexeme")) == [report]
    _update(
        migrated_engine,
        report,
        1,
        ReportPatch(content=validate_content({"format": "text", "body": "A fresh newlexeme."})),
    )
    assert _page(migrated_engine, query="oldlexeme") == ()
    assert _ids(_page(migrated_engine, query="newlexeme")) == [report]
    _update(migrated_engine, report, 2, ReportPatch(title="Retitled skylark"))
    assert _page(migrated_engine, query="versioned") == ()
    assert _ids(_page(migrated_engine, query="skylark")) == [report]


def test_rank_orders_a_search_and_ties_fall_to_time_then_id(migrated_engine: Engine) -> None:
    in_body = _publish(migrated_engine, created_at=T0 + timedelta(hours=5), body="osprey")
    in_title = _publish(migrated_engine, created_at=T0, title="Osprey survey")
    tie_old = _publish(
        migrated_engine,
        created_at=T0 + timedelta(hours=1),
        report_id="grpt_tieaaaaa",
        body="osprey",
    )
    tie_low = _publish(
        migrated_engine,
        created_at=T0 + timedelta(hours=2),
        report_id="grpt_tieBBBBB",
        body="osprey",
    )
    tie_high = _publish(
        migrated_engine,
        created_at=T0 + timedelta(hours=2),
        report_id="grpt_tiebbbbb",
        body="osprey",
    )
    entries = _page(migrated_engine, query="osprey")
    assert entries[0].report_id == in_title
    ranks = [entry.rank for entry in entries]
    assert all(rank is not None for rank in ranks)
    assert ranks[0] is not None and ranks[1] is not None and ranks[0] > ranks[1]
    assert len(set(ranks[1:])) == 1  # the four body hits tie on rank
    # Equal rank: newest first, then id in code-point order ("b" > "B").
    assert _ids(entries) == [in_title, in_body, tie_high, tie_low, tie_old]


# ---- the keyset -----------------------------------------------------------------

#: Ids that differ only by letter case, so code-point order ("C") and the
#: cluster's en_US order disagree about them.
CASE_IDS: Final = (
    "grpt_keysetAa01",
    "grpt_keysetaa01",
    "grpt_keysetAB01",
    "grpt_keysetab01",
    "grpt_keysetZz01",
    "grpt_keysetzz01",
    "grpt_keyset0001",
)


def _same_instant_corpus(engine: Engine) -> list[str]:
    for report_id in CASE_IDS:
        _publish(engine, created_at=T0, report_id=report_id, title="Keyset tern")
    # One row before and one after the tied instant.
    _publish(engine, created_at=T0 - timedelta(microseconds=1), report_id="grpt_keysetzzzz")
    _publish(engine, created_at=T0 + timedelta(microseconds=1), report_id="grpt_keyset0000")
    return [
        "grpt_keyset0000",
        *sorted(CASE_IDS, reverse=True),
        "grpt_keysetzzzz",
    ]


def test_list_keyset_walks_identical_timestamps_in_code_point_order(
    migrated_engine: Engine,
) -> None:
    expected = _same_instant_corpus(migrated_engine)
    assert _ids(_page(migrated_engine)) == expected
    for size in (1, 2, 3):
        walked = _walk(migrated_engine, size)
        assert walked == expected, size
        assert len(set(walked)) == len(walked)


def test_search_keyset_walks_identical_rank_and_time_in_code_point_order(
    migrated_engine: Engine,
) -> None:
    _same_instant_corpus(migrated_engine)
    expected = sorted(CASE_IDS, reverse=True)  # only the tied rows say "tern"
    entries = _page(migrated_engine, query="tern")
    assert _ids(entries) == expected
    assert len({entry.rank for entry in entries}) == 1
    for size in (1, 2, 3):
        assert _walk(migrated_engine, size, query="tern") == expected, size


def test_a_filtered_walk_neither_skips_nor_repeats(migrated_engine: Engine) -> None:
    expected = _same_instant_corpus(migrated_engine)
    _transition(migrated_engine, "grpt_keysetab01", LifecycleOperation.ARCHIVE)
    filters = CatalogFilters(created_from=T0, created_to=T0 + timedelta(microseconds=1))
    tied = [report_id for report_id in expected if report_id in CASE_IDS]
    active = [report_id for report_id in tied if report_id != "grpt_keysetab01"]
    for size in (1, 2, 3):
        assert _walk(migrated_engine, size, filters) == active, size
        assert (
            _walk(
                migrated_engine,
                size,
                replace(ALL_STATES, created_from=T0, created_to=T0 + timedelta(microseconds=1)),
            )
            == tied
        ), size


# ---- the legacy plane -------------------------------------------------------------

_SEEDED: dict[str, int] = {"n": 0}


def _artifact(
    connection: Connection,
    *,
    artifact_id: str,
    principal_id: str = PRINCIPAL_A,
    committed_at: datetime = T0,
    title: str = "Legacy title",
    body: str = "legacy body",
    kind: ArtifactKind = ArtifactKind.COLLECTOR_CANDIDATES,
    report_date: date = date(2026, 11, 1),
    is_current: bool = True,
) -> None:
    """One artifact in a cycle and run of its own (one current head per coordinate)."""
    _SEEDED["n"] += 1
    suffix = f"{_SEEDED['n']:08d}"
    store = SqlIntelligenceStore(connection, principal_id)
    cycle = IntelligenceCycleRun(
        cycle_run_id=f"micr_{suffix}",
        principal_id=principal_id,
        cycle_id=CYCLE_MORNING_INTELLIGENCE,
        business_date=report_date,
        state=CycleState.RUNNING,
        version=1,
        created_at=committed_at,
    )
    store.put_cycle(cycle)
    stage = STAGE_FOR_KIND[kind]
    run = IntelligenceProducerRun(
        run_id=f"rrun_{suffix}",
        principal_id=principal_id,
        cycle_run_id=cycle.cycle_run_id,
        stage=stage,
        artifact_kind=kind.value,
        state=ProducerRunState.SUCCEEDED,
        version=1,
        producer_task_id="catalog-test",
        producer_task_name="catalog test",
        automation_platform="abacus_chatllm",
        report_date=report_date,
        created_at=committed_at,
        focus_area_id=FocusAreaId.COMMUNICATIONS,
    )
    store.put_run(run)
    store.put_artifact(
        IntelligenceArtifact(
            artifact_id=artifact_id,
            principal_id=principal_id,
            cycle_run_id=cycle.cycle_run_id,
            producer_run_id=run.run_id,
            stage=stage,
            artifact_kind=kind.value,
            report_date=report_date,
            title=title,
            body_markdown=body,
            content_sha256=content_digest(body),
            content_bytes=len(body.encode("utf-8")),
            artifact_state=ArtifactState.FINAL if is_current else ArtifactState.SUPERSEDED,
            schema_version="1",
            generated_at=committed_at,
            committed_at=committed_at,
            version=1,
            is_current=is_current,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        )
    )


def _legacy(
    engine: Engine,
    filters: CatalogFilters | None = None,
    *,
    query: str | None = None,
    after: CatalogCursor | None = None,
    limit: int = 50,
    principal_id: str = PRINCIPAL_A,
) -> list[tuple[str, int | None, str | None]]:
    with engine.connect() as connection:
        rows = SqlIntelligenceStore(connection, principal_id).catalog_page(
            principal_id,
            filters=filters or CatalogFilters(),
            query=None if query is None else SearchQuery(query),
            after=after,
            limit=limit,
        )
    return [(artifact.artifact_id, rank, snippet) for artifact, rank, snippet in rows]


def _legacy_ids(
    engine: Engine, filters: CatalogFilters | None = None, **kwargs: object
) -> list[str]:
    return [row[0] for row in _legacy(engine, filters, **kwargs)]  # type: ignore[arg-type]


def test_legacy_catalog_reads_current_artifacts_only_and_maps_the_filters(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        _artifact(connection, artifact_id="rpt_legacy0001", committed_at=T0)
        _artifact(
            connection,
            artifact_id="rpt_legacy0002",
            committed_at=T0 + timedelta(hours=1),
            kind=ArtifactKind.FOCUS_REPORT,
            report_date=date(2026, 11, 2),
        )
        _artifact(
            connection,
            artifact_id="rpt_legacy0003",
            committed_at=T0 + timedelta(hours=2),
            is_current=False,
        )
        _artifact(
            connection,
            artifact_id="rpt_foreign001",
            principal_id=PRINCIPAL_B,
            committed_at=T0 + timedelta(hours=3),
        )
    assert _legacy_ids(migrated_engine) == ["rpt_legacy0002", "rpt_legacy0001"]
    assert _legacy_ids(migrated_engine, principal_id=PRINCIPAL_B) == ["rpt_foreign001"]
    assert _legacy_ids(migrated_engine, CatalogFilters(report_type="focus_report")) == [
        "rpt_legacy0002"
    ]
    # Any kind token: an unregistered one simply matches nothing.
    assert _legacy_ids(migrated_engine, CatalogFilters(report_type="never_registered")) == []
    assert _legacy_ids(migrated_engine, CatalogFilters(created_from=T0 + timedelta(hours=1))) == [
        "rpt_legacy0002"
    ]
    assert _legacy_ids(migrated_engine, CatalogFilters(created_to=T0 + timedelta(hours=1))) == [
        "rpt_legacy0001"
    ]
    assert _legacy_ids(
        migrated_engine,
        CatalogFilters(report_date_from=date(2026, 11, 1), report_date_to=date(2026, 11, 1)),
    ) == ["rpt_legacy0001"]
    # Legacy rows count as active: included iff "active" is listed.
    assert _legacy_ids(migrated_engine, ALL_STATES) == ["rpt_legacy0002", "rpt_legacy0001"]
    excluded = (
        CatalogFilters(lifecycle_states=frozenset({LifecycleState.ARCHIVED})),
        CatalogFilters(lifecycle_states=frozenset({LifecycleState.TRASHED})),
        CatalogFilters(topics=("alpha",)),
        CatalogFilters(tags=("red",)),
        CatalogFilters(associated_with=AssociationFilter(STANDALONE, "grpt_anything01")),
    )
    for filters in excluded:
        assert _legacy(migrated_engine, filters) == []
        assert _legacy(migrated_engine, filters, query="legacy") == []
    rows = _legacy(migrated_engine)
    assert all(rank is None and snippet is None for _id, rank, snippet in rows)


def test_legacy_catalog_search_rank_order_and_snippet(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _artifact(connection, artifact_id="rpt_inbody001", body="the curlew calls", title="Plain")
        _artifact(
            connection,
            artifact_id="rpt_intitle01",
            committed_at=T0 - timedelta(days=1),
            title="Curlew report",
        )
        _artifact(
            connection,
            artifact_id="rpt_stale0001",
            title="Curlew stale",
            committed_at=T0 + timedelta(hours=1),
            is_current=False,
        )
        _artifact(
            connection,
            artifact_id="rpt_foreign02",
            principal_id=PRINCIPAL_B,
            title="Curlew foreign",
        )
    rows = _legacy(migrated_engine, query="curlew")
    assert [row[0] for row in rows] == ["rpt_intitle01", "rpt_inbody001"]
    (_first, title_rank, title_snippet), (_second, body_rank, body_snippet) = rows
    assert title_rank is not None and body_rank is not None and title_rank > body_rank
    assert title_snippet == "<b>Curlew</b> report"
    assert body_snippet == "Plain"
    # The keyset continues after the first hit.
    cursor = CatalogCursor(
        binding=BINDING,
        sort_time=T0 - timedelta(days=1),
        report_id="rpt_intitle01",
        rank=title_rank,
    )
    assert _legacy_ids(migrated_engine, query="curlew", after=cursor) == ["rpt_inbody001"]


def test_legacy_keyset_walks_ties_in_code_point_order(migrated_engine: Engine) -> None:
    tied = ("rpt_tieAAAA01", "rpt_tieaaaa01", "rpt_tieBbbb01", "rpt_tiebbbb01", "rpt_tie0000001")
    with migrated_engine.begin() as connection:
        for artifact_id in tied:
            _artifact(connection, artifact_id=artifact_id, committed_at=T0, title="Tied dunlin")
    expected = sorted(tied, reverse=True)
    for query in (None, "dunlin"):
        rows = _legacy(migrated_engine, query=query)
        assert [row[0] for row in rows] == expected
        for size in (1, 2, 3):
            seen: list[str] = []
            after: CatalogCursor | None = None
            while True:
                page = _legacy(migrated_engine, query=query, after=after, limit=size + 1)
                seen.extend(row[0] for row in page[:size])
                if len(page) <= size:
                    break
                last = page[size - 1]
                after = CatalogCursor(
                    binding=BINDING, sort_time=T0, report_id=last[0], rank=last[1]
                )
            assert seen == expected, (query, size)


def test_one_cursor_orders_both_planes_together(migrated_engine: Engine) -> None:
    """A standalone and a legacy row at one instant: one total order across planes."""
    standalone = _publish(migrated_engine, created_at=T0, report_id="grpt_together1")
    with migrated_engine.begin() as connection:
        _artifact(connection, artifact_id="rpt_together01", committed_at=T0)
    # "rpt_" > "grpt_" in code-point order, so the legacy row comes first.
    legacy_position = CatalogCursor(binding=BINDING, sort_time=T0, report_id="rpt_together01")
    assert _ids(_page(migrated_engine, after=legacy_position)) == [standalone]
    standalone_position = CatalogCursor(binding=BINDING, sort_time=T0, report_id=standalone)
    assert _legacy_ids(migrated_engine, after=standalone_position) == []
    assert _legacy_ids(migrated_engine, after=legacy_position) == []
