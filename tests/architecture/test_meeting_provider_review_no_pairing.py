"""The reconciliation pass never pairs, ranks or compares (WP3b-S4, Manager ruling D2).

Spec section 12.7: the pass "may list candidates for review, but it never binds
on title or time similarity, and nothing is bound without the operator's
choice". `meetings.provider.review` answers two side-by-side lists and
`meetings.provider.reconcile` binds only what an item names. This guard reads
the code that builds them:

* the pass application (`application/meeting_provider_reconcile.py`) and its
  pure values (`domain/meeting_sync/reconcile.py`) import no similarity or
  text-matching module, name no pairing, ranking, scoring or similarity
  identifier, and the application never reads a title or a time -- it hands the
  repository's records through untouched;
* the review answer (`service._meeting_provider_review_payload`) builds its two
  lists independently: no `zip`, no comparison, and neither list's
  comprehension reads the other's records.

A FAST behavioural check closes it: a Meeting titled and timed exactly like a
staged event changes neither list.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from tests.conftest import FakeUnitOfWork, World

from my_pa.application import service
from my_pa.application.meeting_provider_reconcile import MeetingProviderReconciliation
from my_pa.application.meetings import MeetingApplication
from my_pa.contracts.ports import MeetingSyncEventRecord, MeetingSyncPublicationRecord
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.meeting.model import MeetingCreateRequest
from my_pa.domain.meeting_sync.model import EventStatus, ProviderEventIdFormat
from my_pa.domain.source.registry import issue_identifier

PACKAGE: Final = Path(__file__).resolve().parents[2] / "src" / "my_pa"
PASS_MODULES: Final = (
    PACKAGE / "application" / "meeting_provider_reconcile.py",
    PACKAGE / "domain" / "meeting_sync" / "reconcile.py",
)
#: Modules whose only use here would be comparing text or ranking candidates.
FORBIDDEN_IMPORTS: Final = frozenset(
    {"difflib", "re", "unicodedata", "heapq", "statistics", "math", "jellyfish", "rapidfuzz"}
)
#: Identifier fragments a pairing, ranking or similarity step would need.
FORBIDDEN_FRAGMENTS: Final = (
    "pair",
    "rank",
    "score",
    "similar",
    "match",
    "fuzzy",
    "distance",
    "candidate",
    "closest",
    "nearest",
)
#: What the pass application must never read off a Meeting or an event.
CONTENT_ATTRIBUTES: Final = frozenset(
    {"title", "start_at", "end_at", "start_utc", "end_utc", "timezone_name", "location_text"}
)


def _identifiers(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            names.append(node.name)
        elif isinstance(node, (ast.arg, ast.keyword)) and node.arg is not None:
            names.append(node.arg)
    return names


@pytest.mark.parametrize("path", PASS_MODULES, ids=lambda p: p.name)
def test_the_pass_imports_no_matching_module(path: Path) -> None:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots = {node.module.split(".")[0]}
        else:
            continue
        assert not roots & FORBIDDEN_IMPORTS, (path.name, roots)


@pytest.mark.parametrize("path", PASS_MODULES, ids=lambda p: p.name)
def test_the_pass_names_no_pairing_or_ranking(path: Path) -> None:
    for name in _identifiers(ast.parse(path.read_text(encoding="utf-8"))):
        lowered = name.lower()
        assert not any(fragment in lowered for fragment in FORBIDDEN_FRAGMENTS), (path.name, name)


def test_the_pass_application_reads_no_title_or_time() -> None:
    tree = ast.parse(PASS_MODULES[0].read_text(encoding="utf-8"))
    read = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in CONTENT_ATTRIBUTES
    }
    assert read == set(), read


def test_the_review_answer_builds_its_two_lists_independently() -> None:
    source = textwrap.dedent(inspect.getsource(service._meeting_provider_review_payload))
    tree = ast.parse(source)
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "zip" not in calls
    assert "sorted" not in calls
    assert not any(isinstance(node, ast.Compare) for node in ast.walk(tree))
    comprehensions = [node for node in ast.walk(tree) if isinstance(node, ast.ListComp)]
    assert len(comprehensions) == 2
    meetings, events = comprehensions
    assert "staged" not in _identifiers(meetings)
    assert "meeting" not in _identifiers(events)


def test_a_look_alike_meeting_changes_neither_list() -> None:
    principal = "prn_nopairingguard01"
    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    start = now + timedelta(days=1)
    world = World()
    uow = FakeUnitOfWork(world)
    snapshot_id = issue_identifier(IdKind.INGEST_SNAPSHOT)
    uow.meeting_sync.insert_publication(
        principal,
        MeetingSyncPublicationRecord(
            snapshot_id=snapshot_id,
            ingest_source_id="isrc_nopairingguard1",
            generated_at_utc=now,
            record_count=2,
            accepted_count=2,
            quarantined_count=0,
            staged_at=now,
        ),
    )
    uow.meeting_sync.insert_events(
        principal,
        [
            MeetingSyncEventRecord(
                event_id=issue_identifier(IdKind.MEETING_SYNC_EVENT),
                snapshot_id=snapshot_id,
                record_ordinal=ordinal,
                calendar_ref="cal-synthetic",
                ical_uid=uid,
                series_ical_uid=None,
                occurrence_original_start_utc=None,
                start_utc=start,
                end_utc=start + timedelta(hours=1),
                timezone_name="UTC",
                status=EventStatus.CONFIRMED,
                title=title,
                location_text=None,
                virtual_meeting_url=None,
                provider_event_id=None,
                provider_event_id_format=ProviderEventIdFormat.UNKNOWN,
                staged_at=now,
            )
            for ordinal, (uid, title) in enumerate((("uid-a", "Zeta"), ("uid-b", "Alpha")))
        ],
    )
    review = MeetingProviderReconciliation()
    before = review.review(uow, principal, now=now)
    MeetingApplication().create_meeting(
        uow,
        principal,
        MeetingCreateRequest(title="Alpha", start_at=start, timezone_name="UTC"),
        "lookalike-0001",
        now,
    )
    after = review.review(uow, principal, now=now)
    assert after.unbound_provider_events == before.unbound_provider_events
    assert [e.event.ical_uid for e in after.unbound_provider_events] == ["uid-a", "uid-b"]
    assert len(after.unreviewed_meetings) == 1
