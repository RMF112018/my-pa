"""KLP-WP-06: the Knowledge Assertion context plane on a real database.

KLP-AC-052 (persistence and the A6 CHECK), 056 (lifecycle exclusion), and the
real-SQL halves of KLP-AC-057, 060 and 138. Marked `database` (auto
`database_clone`), routed to `database-current-head`.

Every `context.prepare` here goes through `ApplicationService.invoke` over the
production SQL unit of work with the Knowledge plane composed. Assertions come
from the production writers (explicit create, the bound discovery client's
submit, `review.decide`, the availability ingress); direct SQL applies only the
R6 section 5.2 terms the plane has no production writer for, through the shared
helpers of `tests/security/test_knowledge_assertion_disclosure.py`.

* **KLP-AC-052** -- an accepted assertion is persisted as one
  `context_run_items` row with `plane='knowledge_assertion'`,
  `authority_class='product_owned_knowledge_assertion'`, its `kasr_` and no
  other identity; the A6 CHECK accepts that row and refuses every mismatched
  shape.
* **KLP-AC-056** -- superseded and archived assertions never reach context,
  locally or remotely, even when named by their exact id.
* **KLP-AC-060 / 138** -- a remote caller holding the exact grant pair never
  receives an assertion withheld by any single section 5.2 term (stored class,
  linked evidence raised, cross-profile same-origin sibling, capture version,
  memory version, permission lost, deleted, revalidation pending, capture root
  archived, restricted predecessor, restricted counterevidence), in either live
  lifecycle; a local caller does, labelled with its effective class; a page
  whose newest rows are all withheld is still filled with visible rows (the
  filter runs before LIMIT).
* **KLP-AC-057** -- revalidation (lifecycle, or locally an unavailable linked
  row) and counterevidence (a counterevidence link) codes reach the item and
  the package end to end.
* **WP-05 review-1 N2** -- a Review-promoted assertion's links are exactly its
  origin submission's evidence rows, so a restriction of an origin-submission
  row (or of its cross-profile sibling) after promotion withholds the
  assertion from remote `record_events.list`, `record_events.provenance` and
  context alike: the section 5.3 proposal class adds no disclosure gap.

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.application.commands import (
    GetRecordEventProvenance,
    ListRecordEvents,
    PrepareContext,
)
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeEvidenceAvailability
from my_pa.domain.record_events import RecordEventFamily
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction
from tests.database.test_knowledge_assertion_repository import (
    WHEN,
    KnowledgeRuntime,
    new_principal,
)
from tests.database.test_knowledge_assertion_review import PAYMENT, ReviewRuntime
from tests.database.test_knowledge_assertion_submissions import external
from tests.database.test_record_event_provenance import PROVENANCE_GRANTS, event_of
from tests.security.test_knowledge_assertion_disclosure import (
    RESTRICTIONS,
    _bump,
    _superseded_pair,
    _target,
    link,
    raise_evidence,
    restrict_assertion,
    seed_external,
    seed_profile,
    set_lifecycle,
)

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

KA: Final = "knowledge_assertion"
REVALIDATION: Final = "knowledge_revalidation_required"
COUNTEREVIDENCE: Final = "knowledge_counterevidence"
#: The exact pair (KLP-AC-055) plus `context.prepare` itself.
CONTEXT_GRANTS: Final = frozenset(
    {
        (Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION),
        (Capability.KNOWLEDGE_ASSERTIONS_SEARCH, Purpose.KNOWLEDGE_ASSERTION_READ),
    }
)
REMOTE: Final[dict[str, Any]] = {
    "transport": CaptureTransport.REMOTE_CLIENT,
    "grants": CONTEXT_GRANTS,
    "client_id": "klp06-synthetic-context-client",
}
#: A grant-ceilinged composition over LOCAL transport (remote by R6 5.2).
CEILINGED: Final[dict[str, Any]] = {"grants": CONTEXT_GRANTS}
#: The section 5.2 availability terms: locally they add the revalidation code.
AVAILABILITY_TERMS: Final = frozenset(
    {"f_permission_lost", "f_deleted", "f_revalidation_pending", "g_capture_archived"}
)
#: The class terms: locally the item is labelled `restricted_local`.
CLASS_TERMS: Final = frozenset(RESTRICTIONS) - AVAILABILITY_TERMS


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[KnowledgeRuntime]:
    composed = KnowledgeRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


@pytest.fixture
def review_runtime(disposable_database: str) -> Iterator[ReviewRuntime]:
    composed = ReviewRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def prepare(
    runtime: KnowledgeRuntime | ReviewRuntime,
    principal: str,
    query: str,
    via: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return runtime.ok(PrepareContext(query=query), principal_id=principal, **(via or {}))


def items(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["knowledge_assertion_id"]: item for item in result["evidence"] if item["plane"] == KA
    }


def mark_revalidation(engine: Engine, principal: str, assertion_id: str) -> None:
    with engine.begin() as connection:
        _bump(
            connection,
            principal,
            assertion_id,
            kind="revalidation_required",
            assignment="lifecycle = 'revalidation_required'",
        )


def stored_items(engine: Engine, manifest: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT position, plane, authority_class, classification, knowledge_assertion_id, "
                "source_id, source_object_id, source_version_id, knowledge_id, capture_id, "
                "capture_version_id, product_id, managed_document_id, "
                "managed_document_version_id FROM knowledge.context_run_items "
                "WHERE context_manifest_id = :m ORDER BY position"
            ),
            {"m": manifest},
        ).mappings()
        return [dict(row) for row in rows]


# ---- KLP-AC-052: persistence and the A6 CHECK -----------------------------------------


def test_an_accepted_assertion_is_persisted_with_the_a6_identity(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    created = runtime.create(principal, "klp06-persist", value="Requirement klp06persist")
    result = prepare(runtime, principal, "klp06persist")
    (item,) = items(result).values()
    assert item["knowledge_assertion_id"] == created["assertion_id"]
    rows = stored_items(runtime.engine, result["context_manifest_id"])
    (row,) = [row for row in rows if row["plane"] == KA]
    assert row["authority_class"] == "product_owned_knowledge_assertion"
    assert row["knowledge_assertion_id"] == created["assertion_id"]
    for name in (
        "source_id",
        "source_object_id",
        "source_version_id",
        "knowledge_id",
        "capture_id",
        "capture_version_id",
        "product_id",
        "managed_document_id",
        "managed_document_version_id",
    ):
        assert row[name] is None, name


_ITEM_INSERT: Final = text(
    "INSERT INTO knowledge.context_run_items (context_manifest_id, position, principal_id, "
    "reference_id, plane, authority_class, lifecycle, classification, excerpt_sha256, "
    "reason_codes, knowledge_assertion_id, capture_id, source_id) VALUES (:m, :pos, :p, :r, "
    ":plane, :authority, 'accepted', 'private_local', :digest, '', :kasr, :capture, :source)"
)


@pytest.mark.parametrize(
    "shape",
    [
        "plane_without_authority",
        "authority_without_kasr",
        "kasr_on_another_plane",
        "kasr_with_capture_id",
        "kasr_with_source_id",
    ],
)
def test_the_a6_check_refuses_every_mismatched_knowledge_shape(
    runtime: KnowledgeRuntime, shape: str
) -> None:
    principal = new_principal()
    created = runtime.create(principal, f"klp06-a6-{shape}", value="Requirement klp06a6")
    manifest = prepare(runtime, principal, "klp06a6")["context_manifest_id"]
    kasr = created["assertion_id"]
    good = {
        "m": manifest,
        "pos": 900,
        "p": principal,
        "r": kasr,
        "plane": KA,
        "authority": "product_owned_knowledge_assertion",
        "digest": "c" * 64,
        "kasr": kasr,
        "capture": None,
        "source": None,
    }
    with runtime.engine.begin() as connection:
        connection.execute(_ITEM_INSERT, good)
    bad = {
        "plane_without_authority": {"authority": "product_owned_capture"},
        "authority_without_kasr": {"kasr": None},
        "kasr_on_another_plane": {"plane": "capture", "authority": "product_owned_capture"},
        "kasr_with_capture_id": {"capture": "cap_klp06synthetic0001"},
        "kasr_with_source_id": {"source": "src_klp06synthetic0001"},
    }[shape]
    refused = pytest.raises(IntegrityError, match="context_run_item_knowledge_assertion_identity")
    with refused, runtime.engine.begin() as connection:
        connection.execute(_ITEM_INSERT, {**good, "pos": 901, **bad})


# ---- KLP-AC-056: only live assertions --------------------------------------------------


@pytest.mark.parametrize("lifecycle", ["superseded", "archived"])
def test_superseded_and_archived_assertions_never_reach_context(
    runtime: KnowledgeRuntime, lifecycle: str
) -> None:
    principal = new_principal()
    gone = runtime.create(principal, f"klp06-gone-{lifecycle}", value="Requirement klp06life g")
    live = runtime.create(principal, f"klp06-live-{lifecycle}", value="Requirement klp06life l")
    reval = runtime.create(principal, f"klp06-rev-{lifecycle}", value="Requirement klp06life r")
    assert len({gone["assertion_id"], live["assertion_id"], reval["assertion_id"]}) == 3
    set_lifecycle(runtime.engine, principal, gone, lifecycle)
    mark_revalidation(runtime.engine, principal, reval["assertion_id"])
    for via in ({}, REMOTE, CEILINGED):
        found = items(prepare(runtime, principal, "klp06life", via))
        assert set(found) == {live["assertion_id"], reval["assertion_id"]}, via
        named = items(prepare(runtime, principal, gone["assertion_id"], via))
        assert gone["assertion_id"] not in named, via


# ---- KLP-AC-060 / 138: every section 5.2 term withholds remotely ------------------------


@pytest.mark.parametrize("lifecycle", ["active", "revalidation_required"])
@pytest.mark.parametrize("restriction", RESTRICTIONS)
def test_a_single_restriction_term_withholds_the_item_remotely(
    runtime: KnowledgeRuntime, restriction: str, lifecycle: str
) -> None:
    principal = new_principal()
    query = f"klp06q{restriction.replace('_', '')}{lifecycle.replace('_', '')}"
    control = runtime.create(principal, f"{query}-control", value=f"Control {query}")
    target = _target(runtime, principal, restriction, query)
    if lifecycle == "revalidation_required":
        mark_revalidation(runtime.engine, principal, target["assertion_id"])
        mark_revalidation(runtime.engine, principal, control["assertion_id"])
    local = items(prepare(runtime, principal, query))
    assert target["assertion_id"] in local
    item = local[target["assertion_id"]]
    if restriction in CLASS_TERMS:
        assert item["classification"] == "restricted_local"
    if restriction in AVAILABILITY_TERMS or lifecycle == "revalidation_required":
        assert item["limitations"] == [REVALIDATION]
    for via in (REMOTE, CEILINGED):
        remote = prepare(runtime, principal, query, via)
        assert target["assertion_id"] not in items(remote), via
        assert target["assertion_id"] not in str(remote), via
        assert control["assertion_id"] in items(remote), via
        named = prepare(runtime, principal, target["assertion_id"], via)
        assert target["assertion_id"] not in items(named), via


def test_a_restricted_predecessor_withholds_its_successor_remotely(
    review_runtime: ReviewRuntime,
) -> None:
    """The predecessor term alone: a production supersession, then the older class raised.

    Only the predecessor's stored class is restricted; the successor's own class
    and evidence stay permitted, so the withholding is the predecessor term's.
    """
    runtime = review_runtime
    principal, _other, older, newer = _superseded_pair(runtime)
    assert items(prepare(runtime, principal, "Net 45", REMOTE)).keys() == {newer}
    # Fixture-only: a superseded row is terminal to every writer and its class
    # is copied up at supersession, so the predecessor term alone is
    # unreachable in production (defence in depth). Isolate it with triggers off.
    with runtime.engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_assertions SET classification = 'restricted_local' "
                "WHERE assertion_id = :a"
            ),
            {"a": older},
        )
    local = items(prepare(runtime, principal, "Net 45"))
    assert local[newer]["classification"] == "restricted_local"
    for via in (REMOTE, CEILINGED):
        assert newer not in items(prepare(runtime, principal, "Net 45", via))


def test_a_restricted_counterevidence_row_withholds_remotely(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    created = runtime.create(principal, "klp06-cnt-r", value="Requirement klp06cntr")
    profile = seed_profile(runtime.engine, principal, origin_system="outlook_mail", key="cnt-r")
    counter = seed_external(
        runtime.engine, principal, profile, object_id="m-cnt-r", classification="restricted_local"
    )
    link_counterevidence(runtime.engine, principal, created, counter)
    local = items(prepare(runtime, principal, "klp06cntr"))
    assert local[created["assertion_id"]]["contradictions"] == [COUNTEREVIDENCE]
    assert created["assertion_id"] not in items(prepare(runtime, principal, "klp06cntr", REMOTE))


def test_a_remote_context_page_is_filled_with_visible_rows_before_limit(
    runtime: KnowledgeRuntime,
) -> None:
    """KLP-AC-060: 3 older visible rows survive 35 newer withheld ones (LIMIT is 32)."""
    principal = new_principal()
    visible = [
        runtime.create(principal, f"klp06-lim-v{index}", value=f"Limit klp06lim v{index}")[
            "assertion_id"
        ]
        for index in range(3)
    ]
    withheld = []
    for index in range(35):
        created = runtime.create(principal, f"klp06-lim-w{index}", value=f"Limit klp06lim w{index}")
        restrict_assertion(runtime.engine, principal, created["assertion_id"])
        withheld.append(created["assertion_id"])
    remote = prepare(runtime, principal, "klp06lim", REMOTE)
    assert set(items(remote)) == set(visible)
    coverage = [row for row in remote["coverage"] if row["plane"] == KA]
    assert [row["state"] for row in coverage] == ["searched_complete"]
    local = prepare(runtime, principal, "klp06lim")
    assert set(items(local)) <= set(withheld) | set(visible)
    assert [row["state"] for row in local["coverage"] if row["plane"] == KA] == ["incomplete"]


# ---- KLP-AC-057: codes end to end ------------------------------------------------------


def link_counterevidence(
    engine: Engine, principal: str, created: dict[str, Any], evidence: str
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertion_evidence_links (principal_id, "
                "assertion_id, evidence_ref_id, evidence_role, linked_by_mutation_id, "
                "created_at) VALUES (:p, :a, :e, 'counterevidence', :m, now())"
            ),
            {
                "p": principal,
                "a": created["assertion_id"],
                "e": evidence,
                "m": created["mutation_id"],
            },
        )


def test_counterevidence_and_revalidation_codes_reach_item_and_package(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    engine = runtime.engine
    countered = runtime.create(principal, "klp06-code-c", value="Requirement klp06code c")
    revalidating = runtime.create(principal, "klp06-code-r", value="Requirement klp06code r")
    lost = runtime.create(principal, "klp06-code-l", value="Requirement klp06code l")
    plain = runtime.create(principal, "klp06-code-p", value="Requirement klp06code p")
    profile = seed_profile(engine, principal, origin_system="outlook_mail", key="code")
    link_counterevidence(
        engine, principal, countered, seed_external(engine, principal, profile, object_id="m-c")
    )
    mark_revalidation(engine, principal, revalidating["assertion_id"])
    lost_row = seed_external(engine, principal, profile, object_id="m-l")
    link(engine, principal, lost, lost_row)
    # The production availability ingress: marks the linked live assertion.
    with knowledge_maintenance_transaction(engine) as repository:
        repository.record_evidence_availability(
            principal, lost_row, KnowledgeEvidenceAvailability.PERMISSION_LOST, at=WHEN
        )
    local = prepare(runtime, principal, "klp06code")
    found = items(local)
    assert found[countered["assertion_id"]]["contradictions"] == [COUNTEREVIDENCE]
    assert found[countered["assertion_id"]]["limitations"] == []
    assert found[revalidating["assertion_id"]]["limitations"] == [REVALIDATION]
    assert found[lost["assertion_id"]]["limitations"] == [REVALIDATION]
    assert found[plain["assertion_id"]]["limitations"] == []
    assert found[plain["assertion_id"]]["contradictions"] == []
    assert REVALIDATION in local["limitations"]
    assert COUNTEREVIDENCE in local["contradictions_or_conflicts"]
    remote = prepare(runtime, principal, "klp06code", REMOTE)
    shown = items(remote)
    assert lost["assertion_id"] not in shown
    assert shown[countered["assertion_id"]]["contradictions"] == [COUNTEREVIDENCE]
    assert shown[revalidating["assertion_id"]]["limitations"] == [REVALIDATION]
    assert REVALIDATION in remote["limitations"]
    assert COUNTEREVIDENCE in remote["contradictions_or_conflicts"]


def test_a_remote_caller_without_the_pair_never_reaches_the_plane(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    runtime.create(principal, "klp06-nopair", value="Requirement klp06nopair")
    for grants in (
        frozenset({(Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION)}),
        frozenset(
            {
                (Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION),
                (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ),
            }
        ),
    ):
        result = prepare(
            runtime,
            principal,
            "klp06nopair",
            {"transport": CaptureTransport.REMOTE_CLIENT, "grants": grants, "client_id": "c"},
        )
        assert KA not in str(result)


# ---- WP-05 review-1 N2: Review-promoted provenance under AC-060 ------------------------


N2_GRANTS: Final = PROVENANCE_GRANTS | CONTEXT_GRANTS
N2_REMOTE: Final[dict[str, Any]] = {
    "transport": CaptureTransport.REMOTE_CLIENT,
    "grants": N2_GRANTS,
    "client_id": "klp06-synthetic-n2-reader",
}


def _promoted(runtime: ReviewRuntime, key: str) -> tuple[str, str, dict[str, Any]]:
    principal = new_principal()
    profile = runtime.profile(principal)
    queued = runtime.submit(
        principal,
        profile,
        subject_id=runtime.org(principal, key),
        predicate=PAYMENT,
        candidate=f"cand-{key}",
        run=f"run-{key}",
        value=f"Synthetic net 30 terms {key}",
        evidence=(external(f"obj-{key}-a"), external(f"obj-{key}-b")),
    )
    assert queued["outcome"] == "review_queued", queued
    decided = runtime.decide(principal, str(queued["review_case_id"]), Disposition.ACCEPT)
    return principal, profile, {**decided, "submission_id": queued["submission_id"]}


def _surfaces(
    runtime: ReviewRuntime, principal: str, assertion_id: str, event: str, query: str
) -> dict[str, bool]:
    listed = runtime.ok(
        ListRecordEvents(page_size=100, record_families=(RecordEventFamily.KNOWLEDGE_ASSERTION,)),
        principal_id=principal,
        **N2_REMOTE,
    )
    provenance = runtime.invoke(
        GetRecordEventProvenance(event_id=event), principal_id=principal, **N2_REMOTE
    )
    context = runtime.ok(PrepareContext(query=query), principal_id=principal, **N2_REMOTE)
    return {
        "list": assertion_id in {item["record_id"] for item in listed["events"]},
        "provenance": provenance.error is None,
        "context": assertion_id in items(context),
    }


@pytest.mark.parametrize("term", ["origin_row_raised", "origin_row_sibling"])
def test_a_review_promoted_assertion_follows_its_origin_submission_evidence(
    review_runtime: ReviewRuntime, term: str
) -> None:
    runtime = review_runtime
    key = f"klp06n2{term.replace('_', '')}"
    principal, _profile, decided = _promoted(runtime, key)
    assertion_id = str(decided["assertion_id"])
    event = event_of(runtime.engine, str(decided["receipt_id"]))
    with runtime.engine.connect() as connection:
        submitted = set(
            connection.execute(
                text(
                    "SELECT evidence_ref_id FROM knowledge.knowledge_submission_evidence "
                    "WHERE submission_id = :s"
                ),
                {"s": decided["submission_id"]},
            ).scalars()
        )
        linked = set(
            connection.execute(
                text(
                    "SELECT evidence_ref_id FROM knowledge.knowledge_assertion_evidence_links "
                    "WHERE assertion_id = :a"
                ),
                {"a": assertion_id},
            ).scalars()
        )
    # WP-04 DEV-68: the promoted links are exactly the origin submission's rows,
    # so the proposal's section 5.3 evidence terms are the assertion's 5.2 terms.
    assert submitted == linked
    assert len(linked) == 2
    assert _surfaces(runtime, principal, assertion_id, event, key) == dict.fromkeys(
        ("list", "provenance", "context"), True
    )
    origin = sorted(linked)[0]
    if term == "origin_row_raised":
        raise_evidence(runtime.engine, origin, "source_classification = 'restricted_local'")
    else:
        with runtime.engine.connect() as connection:
            object_id = connection.execute(
                text(
                    "SELECT external_object_id FROM knowledge.knowledge_evidence_refs "
                    "WHERE evidence_ref_id = :e"
                ),
                {"e": origin},
            ).scalar_one()
        other = seed_profile(runtime.engine, principal, origin_system="outlook_mail", key=key)
        seed_external(
            runtime.engine,
            principal,
            other,
            object_id=object_id,
            classification="restricted_local",
            version="v9",
        )
    assert _surfaces(runtime, principal, assertion_id, event, key) == dict.fromkeys(
        ("list", "provenance", "context"), False
    )
    local = runtime.ok(PrepareContext(query=key), principal_id=principal)
    assert items(local)[assertion_id]["classification"] == "restricted_local"
