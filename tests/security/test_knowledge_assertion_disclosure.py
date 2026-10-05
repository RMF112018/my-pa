"""KLP-WP-03: remote Knowledge disclosure withholds `withheld_remote` before LIMIT (DB).

KLP-AC-048 / 060 / 111 / 138 (WP-03 slices). Marked `database` (auto
`database_clone`), routed to `database-current-head`.

For every remote surface WP-03 serves -- `knowledge.assertions.read`, `.list`,
`.search`, `.history`, `.reveal` and `record_events.list` -- an assertion is
withheld when its restriction comes *only* from one R6 section 5.2 term:

* (a) its stored class;
* (b) a linked evidence row raised to `restricted_local` after linking;
* (c) an external row of the same `external_object_id` under a *different*
  source profile of the same `origin_system` (and not under another origin);
* (d) a later restricted version of a cited Capture;
* (e) a later restricted version of a cited Relationship Memory;
* (f) a linked external row's availability: `permission_lost`, `deleted`, or
  `availability_revalidation_pending`;
* (g) a cited Capture root archived;

in the `active`, `superseded` and `archived` lifecycles. A local caller still
sees each one (Principal partitioning only). With a page of N whose newest N
rows are withheld, a remote page still returns N permitted rows, and no cursor
or count discloses a withheld row.

**Direct SQL, where the plane offers no WP-03 writer:** source profiles and
external evidence rows (submit is WP-04), evidence-link inserts for external
evidence, evidence classification/availability changes (the ingress command is
WP-04), a restricted capture version (no production path writes one), and the
assertion lifecycle/classification control updates (WP-04 maintenance). The
assertions themselves, capture/memory evidence, the restricted memory version
(`relationship_memory.revise` to `sensitivity`) and the archived capture root
(`capture.archive`) all come from the production writers.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.database.test_knowledge_assertion_repository import (
    KnowledgeRuntime,
    capture_evidence,
    memory_evidence,
    new_principal,
)

from my_pa.application.commands import (
    ArchiveCapture,
    GetKnowledgeAssertionHistory,
    ListKnowledgeAssertions,
    ListRecordEvents,
    ReadKnowledgeAssertion,
    RevealKnowledgeAssertion,
    ReviseRelationshipMemory,
    SearchKnowledgeAssertions,
)
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeAssertionLifecycle
from my_pa.domain.relationship.memory import MemoryKind
from my_pa.domain.source.registry import issue_identifier

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

REMOTE_GRANTS: Final = frozenset(
    {
        (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ),
        (Capability.KNOWLEDGE_ASSERTIONS_LIST, Purpose.KNOWLEDGE_ASSERTION_READ),
        (Capability.KNOWLEDGE_ASSERTIONS_SEARCH, Purpose.KNOWLEDGE_ASSERTION_READ),
        (Capability.KNOWLEDGE_ASSERTIONS_HISTORY, Purpose.KNOWLEDGE_ASSERTION_READ),
        (Capability.KNOWLEDGE_ASSERTIONS_REVEAL, Purpose.KNOWLEDGE_ASSERTION_READ),
        (Capability.RECORD_EVENTS_LIST, Purpose.RECORD_EVENT_READ),
    }
)
REMOTE: Final[dict[str, Any]] = {
    "transport": CaptureTransport.REMOTE_CLIENT,
    "grants": REMOTE_GRANTS,
    "client_id": "klp03-remote-client",
}
SURFACES: Final = ("read", "list", "search", "history", "reveal", "record_events")


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[KnowledgeRuntime]:
    composed = KnowledgeRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


# ---- direct-SQL seeding (no WP-03 writer) ----------------------------------------


def seed_profile(engine: Engine, principal: str, *, origin_system: str, key: str) -> str:
    profile = issue_identifier(IdKind.KNOWLEDGE_DISCOVERY_SOURCE_PROFILE)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_discovery_source_profiles (principal_id, "
                "source_profile_id, authenticated_client_id, origin_system, scope_digest, "
                "authority_ceiling, direct_admission_enabled, read_only_proof_state, "
                "is_synthetic, profile_version, created_at, updated_at) VALUES (:p, :s, :c, "
                ":o, :d, 'observed_source', false, 'unproven', false, 1, now(), now())"
            ),
            {
                "p": principal,
                "s": profile,
                "c": f"klp03-client-{key}",
                "o": origin_system,
                "d": hashlib.sha256(key.encode()).hexdigest(),
            },
        )
    return profile


def seed_external(
    engine: Engine,
    principal: str,
    profile: str,
    *,
    object_id: str,
    classification: str = "private_local",
    version: str | None = None,
) -> str:
    evidence = issue_identifier(IdKind.KNOWLEDGE_EVIDENCE_REF)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_evidence_refs (principal_id, evidence_ref_id, "
                "identity_kind, source_profile_id, source_is_synthetic, external_object_id, "
                "external_version_id, content_hash, content_origin, source_classification, "
                "created_at, updated_at) VALUES (:p, :e, 'external_object', :s, false, :o, :v, "
                ":h, 'external_source', :c, now(), now())"
            ),
            {
                "p": principal,
                "e": evidence,
                "s": profile,
                "o": object_id,
                "v": version,
                "h": hashlib.sha256(f"{object_id}{version}{profile}".encode()).hexdigest(),
                "c": classification,
            },
        )
    return evidence


def link(engine: Engine, principal: str, created: dict[str, Any], evidence: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertion_evidence_links (principal_id, "
                "assertion_id, evidence_ref_id, evidence_role, linked_by_mutation_id, "
                "created_at) VALUES (:p, :a, :e, 'supporting', :m, now())"
            ),
            {
                "p": principal,
                "a": created["assertion_id"],
                "e": evidence,
                "m": created["mutation_id"],
            },
        )


def _bump(
    connection: Any,  # noqa: ANN401 - a SQLAlchemy connection
    principal: str,
    assertion_id: str,
    *,
    kind: str,
    assignment: str,
    submission: str | None = None,
) -> None:
    version = connection.execute(
        text("SELECT version FROM knowledge.knowledge_assertions WHERE assertion_id = :a"),
        {"a": assertion_id},
    ).scalar_one()
    connection.execute(
        text(
            f"UPDATE knowledge.knowledge_assertions SET {assignment}, version = version + 1, "  # noqa: S608
            "updated_at = now() WHERE assertion_id = :a"
        ),
        {"a": assertion_id},
    )
    connection.execute(
        text(
            "INSERT INTO knowledge.knowledge_assertion_mutations (principal_id, mutation_id, "
            "assertion_id, mutation_kind, prior_version, new_version, submission_id, "
            "created_at) VALUES (:p, :m, :a, :k, :v, :v + 1, :s, now())"
        ),
        {
            "p": principal,
            "m": issue_identifier(IdKind.KNOWLEDGE_ASSERTION_MUTATION),
            "a": assertion_id,
            "k": kind,
            "v": version,
            "s": submission,
        },
    )


def restrict_assertion(engine: Engine, principal: str, assertion_id: str) -> None:
    with engine.begin() as connection:
        _bump(
            connection,
            principal,
            assertion_id,
            kind="classify",
            assignment="classification = 'restricted_local'",
        )


def set_lifecycle(engine: Engine, principal: str, created: dict[str, Any], lifecycle: str) -> None:
    if lifecycle == "active":
        return
    kind = "archive" if lifecycle == "archived" else "supersede_predecessor"
    with engine.begin() as connection:
        _bump(
            connection,
            principal,
            created["assertion_id"],
            kind=kind,
            assignment=f"lifecycle = '{lifecycle}'",
            submission=None if lifecycle == "archived" else created["submission_id"],
        )


def raise_evidence(engine: Engine, evidence_ref_id: str, assignment: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE knowledge.knowledge_evidence_refs SET {assignment}, "  # noqa: S608
                "updated_at = now() WHERE evidence_ref_id = :e"
            ),
            {"e": evidence_ref_id},
        )


def restricted_capture_version(engine: Engine, principal: str, capture_id: str) -> None:
    """Fixture-only writer: a restricted version 2, as no production path can write one."""
    with engine.begin() as connection:
        first = connection.execute(
            text(
                "SELECT version_id FROM knowledge.capture_versions WHERE capture_id = :c "
                "AND version_number = 1"
            ),
            {"c": capture_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO knowledge.capture_versions (version_id, capture_id, version_number, "
                "supersedes_version_id, content, content_sha256, owner_principal_id, "
                "classification, processing_policy, idempotency_key, correlation_id, audit_id, "
                "server_received_at, accepted_at, recorded_at) VALUES (:v, :c, 2, :s, "
                "'Synthetic restricted text', :d, :p, 'restricted_local', 'local_only', :k, "
                ":corr, :a, now(), now(), now())"
            ),
            {
                "v": issue_identifier(IdKind.CAPTURE_VERSION),
                "c": capture_id,
                "s": first,
                "d": "0" * 64,
                "p": principal,
                "k": f"klp03-restricted-{capture_id}",
                "corr": issue_identifier(IdKind.CORRELATION),
                "a": issue_identifier(IdKind.AUDIT),
            },
        )


def evidence_of(engine: Engine, assertion_id: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT evidence_ref_id FROM knowledge.knowledge_assertion_evidence_links "
                    "WHERE assertion_id = :a ORDER BY evidence_ref_id LIMIT 1"
                ),
                {"a": assertion_id},
            ).scalar_one()
        )


# ---- the surfaces ------------------------------------------------------------------


def surfaces(
    runtime: KnowledgeRuntime,
    principal: str,
    assertion_id: str,
    lifecycle: str,
    query: str,
    *,
    remote: bool,
) -> dict[str, bool]:
    """Which of the six surfaces disclose `assertion_id` to this caller."""
    extra = REMOTE if remote else {}
    state = KnowledgeAssertionLifecycle(lifecycle)

    def answered(command: Any) -> dict[str, Any] | None:  # noqa: ANN401 - a command
        response = runtime.invoke(command, principal_id=principal, **extra)
        if response.error is not None:
            assert response.error.code.value == "not_found", response.error
            return None
        return dict(response.result or {})

    listed = answered(ListKnowledgeAssertions(lifecycle=state, page_size=100)) or {}
    searched = answered(SearchKnowledgeAssertions(query=query, lifecycle=state)) or {}
    events = answered(ListRecordEvents(page_size=100)) or {}
    return {
        "read": answered(ReadKnowledgeAssertion(assertion_id=assertion_id)) is not None,
        "list": assertion_id in {row["assertion_id"] for row in listed.get("assertions", [])},
        "search": assertion_id in {row["assertion_id"] for row in searched.get("assertions", [])},
        "history": answered(GetKnowledgeAssertionHistory(assertion_id=assertion_id)) is not None,
        "reveal": answered(RevealKnowledgeAssertion(assertion_id=assertion_id)) is not None,
        "record_events": assertion_id in {item["record_id"] for item in events.get("events", [])},
    }


RESTRICTIONS: Final = (
    "a_stored_class",
    "b_linked_evidence_raised",
    "c_cross_profile_sibling",
    "d_capture_version",
    "e_memory_version",
    "f_permission_lost",
    "f_deleted",
    "f_revalidation_pending",
    "g_capture_archived",
)
LIFECYCLES: Final = ("active", "superseded", "archived")


def _target(
    runtime: KnowledgeRuntime, principal: str, restriction: str, query: str
) -> dict[str, Any]:
    """Create the target through the production writer and apply exactly one term."""
    engine = runtime.engine
    value = f"Requirement {query}"
    if restriction in {"b_linked_evidence_raised", "d_capture_version", "g_capture_archived"}:
        capture_id, digest = runtime.capture(principal, query)
        created = runtime.create(
            principal, query, value=value, evidence=(capture_evidence(capture_id, digest),)
        )
        if restriction == "b_linked_evidence_raised":
            raise_evidence(
                engine,
                evidence_of(engine, created["assertion_id"]),
                "source_classification = 'restricted_local'",
            )
        elif restriction == "d_capture_version":
            restricted_capture_version(engine, principal, capture_id)
        else:
            runtime.ok(
                ArchiveCapture(
                    capture_id=capture_id,
                    expected_lifecycle_revision=0,
                    idempotency_key=f"archive-{query}",
                    reason="Synthetic knowledge archive",
                ),
                principal_id=principal,
            )
        return created
    if restriction == "e_memory_version":
        organization = runtime.entity(principal, query)
        memory_id, digest = runtime.memory(principal, organization, query)
        created = runtime.create(
            principal, query, value=value, evidence=(memory_evidence(memory_id, digest),)
        )
        runtime.ok(
            ReviseRelationshipMemory(
                memory_id=memory_id,
                expected_version=1,
                statement=f"Synthetic sensitive statement {query}",
                idempotency_key=f"mem-revise-{query}",
                kind=MemoryKind.SENSITIVITY,
            ),
            principal_id=principal,
        )
        return created
    created = runtime.create(principal, query, value=value)
    if restriction == "a_stored_class":
        restrict_assertion(engine, principal, created["assertion_id"])
        return created
    profile = seed_profile(engine, principal, origin_system="outlook_mail", key=f"{query}-1")
    linked = seed_external(engine, principal, profile, object_id=f"msg-{query}")
    link(engine, principal, created, linked)
    if restriction == "c_cross_profile_sibling":
        other = seed_profile(engine, principal, origin_system="outlook_mail", key=f"{query}-2")
        seed_external(
            engine,
            principal,
            other,
            object_id=f"msg-{query}",
            classification="restricted_local",
            version="v2",
        )
    elif restriction == "f_permission_lost":
        raise_evidence(engine, linked, "availability_state = 'permission_lost'")
    elif restriction == "f_deleted":
        raise_evidence(engine, linked, "availability_state = 'deleted'")
    else:
        raise_evidence(engine, linked, "availability_revalidation_pending = true")
    return created


@pytest.mark.parametrize("lifecycle", LIFECYCLES)
@pytest.mark.parametrize("restriction", RESTRICTIONS)
def test_a_single_restriction_term_withholds_on_every_remote_surface(
    runtime: KnowledgeRuntime, restriction: str, lifecycle: str
) -> None:
    principal = new_principal()
    query = f"klp03q{restriction.replace('_', '')}{lifecycle}"
    control = runtime.create(principal, f"{query}-control", value=f"Control {query}")
    target = _target(runtime, principal, restriction, query)
    set_lifecycle(runtime.engine, principal, target, lifecycle)
    set_lifecycle(runtime.engine, principal, control, lifecycle)
    local = surfaces(runtime, principal, target["assertion_id"], lifecycle, query, remote=False)
    remote = surfaces(runtime, principal, target["assertion_id"], lifecycle, query, remote=True)
    assert local == dict.fromkeys(SURFACES, True), local
    assert remote == dict.fromkeys(SURFACES, False), remote
    # The unrestricted control stays visible remotely, so the withholding is the term's.
    permitted = surfaces(
        runtime, principal, control["assertion_id"], lifecycle, "Control", remote=True
    )
    assert permitted == dict.fromkeys(SURFACES, True), permitted


def test_a_sibling_under_another_origin_system_does_not_withhold(
    runtime: KnowledgeRuntime,
) -> None:
    """KLP-AC-138: the sibling term is scoped to the same `origin_system`."""
    principal = new_principal()
    created = runtime.create(principal, "klp03-origin", value="Requirement originscoped")
    engine = runtime.engine
    profile = seed_profile(engine, principal, origin_system="outlook_mail", key="origin-1")
    link(engine, principal, created, seed_external(engine, principal, profile, object_id="m-1"))
    teams = seed_profile(engine, principal, origin_system="teams_messages", key="origin-2")
    seed_external(engine, principal, teams, object_id="m-1", classification="restricted_local")
    remote = surfaces(
        runtime, principal, created["assertion_id"], "active", "originscoped", remote=True
    )
    assert remote == dict.fromkeys(SURFACES, True)


def test_another_principals_restriction_never_withholds_mine(runtime: KnowledgeRuntime) -> None:
    """The sibling and version terms are partitioned: a foreign row is never consulted."""
    mine, theirs = new_principal(), new_principal()
    created = runtime.create(mine, "klp03-partition", value="Requirement partitioned")
    engine = runtime.engine
    profile = seed_profile(engine, mine, origin_system="outlook_mail", key="part-1")
    link(engine, mine, created, seed_external(engine, mine, profile, object_id="shared-object"))
    foreign = seed_profile(engine, theirs, origin_system="outlook_mail", key="part-2")
    seed_external(
        engine, theirs, foreign, object_id="shared-object", classification="restricted_local"
    )
    remote = surfaces(runtime, mine, created["assertion_id"], "active", "partitioned", remote=True)
    assert remote == dict.fromkeys(SURFACES, True)


# ---- withholding before LIMIT --------------------------------------------------------


def test_a_remote_page_of_n_is_n_permitted_rows_when_the_newest_are_withheld(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    permitted = [
        runtime.create(principal, f"klp03-limit-p{index}", value=f"Limit row p{index}")[
            "assertion_id"
        ]
        for index in range(4)
    ]
    withheld = [
        runtime.create(principal, f"klp03-limit-w{index}", value=f"Limit row w{index}")[
            "assertion_id"
        ]
        for index in range(3)
    ]
    for assertion_id in withheld:
        restrict_assertion(runtime.engine, principal, assertion_id)
    # Newest first: the three withheld rows are the first three by order.
    local = runtime.ok(ListKnowledgeAssertions(page_size=3), principal_id=principal)
    assert {row["assertion_id"] for row in local["assertions"]} <= set(withheld) | set(permitted)
    first = runtime.ok(ListKnowledgeAssertions(page_size=3), principal_id=principal, **REMOTE)
    assert len(first["assertions"]) == 3
    assert not {row["assertion_id"] for row in first["assertions"]} & set(withheld)
    assert first["next_cursor"] is not None
    second = runtime.ok(
        ListKnowledgeAssertions(page_size=3, cursor=first["next_cursor"]),
        principal_id=principal,
        **REMOTE,
    )
    seen = [row["assertion_id"] for row in [*first["assertions"], *second["assertions"]]]
    assert sorted(seen) == sorted(permitted)
    assert second["next_cursor"] is None
    searched = runtime.ok(
        SearchKnowledgeAssertions(query="Limit row", page_size=3), principal_id=principal, **REMOTE
    )
    assert len(searched["assertions"]) == 3
    assert not {row["assertion_id"] for row in searched["assertions"]} & set(withheld)


def test_a_remote_feed_page_of_n_is_n_permitted_events(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    withheld = [
        runtime.create(principal, f"klp03-feed-w{index}", value=f"Feed row w{index}")[
            "assertion_id"
        ]
        for index in range(3)
    ]
    permitted = [
        runtime.create(principal, f"klp03-feed-p{index}", value=f"Feed row p{index}")[
            "assertion_id"
        ]
        for index in range(3)
    ]
    for assertion_id in withheld:
        restrict_assertion(runtime.engine, principal, assertion_id)
    # Oldest first: the three withheld events are the first three by sequence.
    page = runtime.ok(ListRecordEvents(page_size=3), principal_id=principal, **REMOTE)
    assert [item["record_id"] for item in page["events"]] == permitted
    assert page["next_cursor"] is None
    local = runtime.ok(ListRecordEvents(page_size=3), principal_id=principal)
    assert [item["record_id"] for item in local["events"]] == withheld
