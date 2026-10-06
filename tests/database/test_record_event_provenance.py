"""KLP-WP-05: `record_events.provenance` -- cross-run provenance on a real database.

KLP-AC-046, 047, 048, 049, 111, 119 (provenance-read half), 138 (WP-05 half)
and 143. Marked `database` (auto `database_clone`), routed to
`database-current-head`.

Every Knowledge write here is a production write: explicit create, the bound
discovery client's autonomous submit, `review.decide`, and the availability
ingress. Every provenance read goes through `ApplicationService.invoke` as
`record_events.provenance`, from the caller the test names. Direct SQL only
reads ids back and applies the R6 section 5.2 restriction terms where the plane
has no production writer (the shared disclosure helpers).

* **KLP-AC-046 / 143** -- the provenance of a `direct_created` event names its
  `kasub_` submission, causal depth and root, and the visible cited triggers;
  `external_run_id` / `external_candidate_id` go only to the client that
  supplied them or to a local caller, and are `null` for every other granted
  client and for a grant-ceilinged composition with no client (one pinned
  shape: the keys are always present).
* **KLP-AC-047** -- a Review-promoted event names the origin submission, the
  proposal (`kaprp_`), the review case (`rvw_`) and the accepting decision
  (`kadec_`) with its stored `authenticated_client_id` and server-derived
  `decision_channel`, plus the run (to the supplier) and visible triggers.
  DEV-13 (Manager ruling 2026-10-06): every OAuth client id in the answer goes
  to a remote caller only when it is that caller's own; otherwise the key is
  `null`. The local Principal sees every id, which is where AC-047 is met.
* **KLP-AC-048 / 111 / 138** -- remote provenance *and* remote
  `record_events.list` never disclose a Knowledge event withheld by any single
  section 5.2 term (stored class, linked evidence raised, cross-profile same
  origin sibling, capture version, memory version, permission lost, deleted,
  revalidation pending, capture root archived) in any lifecycle; the withheld
  provenance answer is byte-identical to an unknown event's; the feed filter
  applies before LIMIT; a cited trigger withheld (or of a family the caller
  cannot see) is absent from the visible trigger list.
* **KLP-AC-049** -- `self_caused` is computed from the persisted submission and
  causal-root client lineage, never from the request; the event's actor class
  is the stored transport/client-derived one.
* **KLP-AC-119 (read half)** -- depth and root are the server-derived values
  reached event -> mutation -> submission even when every hop used a fresh run
  id. The `causal_rate_exceeded` bound is WP-04's test
  (`tests/database/test_knowledge_causal_depth.py`).

A maintenance mutation (no submission) answers `submission: null` with no
triggers. The restricted runtime role executes the provenance statements.

**Bounded / unproven.** The provenance read is two statements (lineage, then
visible triggers); a restriction committed between them is not injectable
without a seam, so that interleaving is argued (visibility is monotonic, so it
can only *omit* a trigger) rather than proved. The multi-connection test below
proves the read neither blocks on nor sees an uncommitted restriction, and is
withheld once it commits.

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select, text

from my_pa.application.commands import (
    GetRecordEventProvenance,
    ListRecordEvents,
)
from my_pa.domain.capture.review import Disposition
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeEvidenceAvailability
from my_pa.domain.record_events import RecordEventFamily
from my_pa.infrastructure.database.record_event_roles import RUNTIME_ROLE
from my_pa.infrastructure.persistence.record_events import SqlRecordEventReader
from my_pa.infrastructure.persistence.tables import knowledge_evidence_refs, record_events
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction
from tests.database.test_knowledge_assertion_repository import WHEN, new_principal
from tests.database.test_knowledge_assertion_review import (
    CHATLLM_CLIENT,
    CLI,
    OPERATOR_CLIENT,
    PAYMENT,
    ReviewRuntime,
    remote,
    without_correlation,
)
from tests.database.test_knowledge_assertion_submissions import CLIENT, OTHER_CLIENT, external
from tests.database.test_record_event_role_privileges import (  # noqa: F401 - fixtures
    _drop_canonical_roles,
    provisioned,
)
from tests.security.test_knowledge_assertion_disclosure import (
    LIFECYCLES,
    RESTRICTIONS,
    _target,
    restrict_assertion,
    set_lifecycle,
)

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

#: A remote reader's grants: provenance, the feed, and the Knowledge read that
#: makes the `knowledge_assertion` family visible (the feed's own rule).
PROVENANCE_GRANTS: Final = frozenset(
    {
        (Capability.RECORD_EVENTS_PROVENANCE, Purpose.RECORD_EVENT_PROVENANCE_READ),
        (Capability.RECORD_EVENTS_LIST, Purpose.RECORD_EVENT_READ),
        (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ),
    }
)
#: The local owning Principal: no transport, no client, no grant ceiling.
LOCAL: Final[dict[str, object]] = {}
#: The discovery client that supplied the submissions below.
SUPPLIER: Final = remote(CLIENT, PROVENANCE_GRANTS)
#: Another granted discovery client of the same Principal.
OTHER: Final = remote(OTHER_CLIENT, PROVENANCE_GRANTS)
#: An ordinary granted remote client.
CHATLLM: Final = remote(CHATLLM_CLIENT, PROVENANCE_GRANTS)
#: A grant-ceilinged composition over LOCAL transport with no client (gsqs-like).
CEILINGED: Final[dict[str, object]] = {"grants": PROVENANCE_GRANTS}
#: The keys of the pinned public shape.
PROVENANCE_KEYS: Final = frozenset(
    {
        "event_id",
        "record_family",
        "record_id",
        "source_receipt_id",
        "mutation_kind",
        "actor_class",
        "submission",
        "trigger_event_ids",
        "review",
    }
)
SUBMISSION_KEYS: Final = frozenset(
    {
        "submission_id",
        "origin",
        "causal_depth",
        "causal_root_submission_id",
        "external_run_id",
        "external_candidate_id",
        "self_caused",
    }
)


class ProvenanceRuntime(ReviewRuntime):
    """`ReviewRuntime` (discovery + operator-review clients bound) with provenance reads."""

    def provenance(self, principal_id: str, event_id: str, via: dict[str, object]) -> Any:  # noqa: ANN401
        return self.ok(
            GetRecordEventProvenance(event_id=event_id), principal_id=principal_id, **via
        )["provenance"]

    def provenance_error(
        self, principal_id: str, event_id: str, via: dict[str, object]
    ) -> dict[str, Any]:
        return without_correlation(
            self.error(
                GetRecordEventProvenance(event_id=event_id), principal_id=principal_id, **via
            )
        )

    def listed(self, principal_id: str, via: dict[str, object], page_size: int = 100) -> Any:  # noqa: ANN401
        return self.ok(
            ListRecordEvents(
                page_size=page_size, record_families=(RecordEventFamily.KNOWLEDGE_ASSERTION,)
            ),
            principal_id=principal_id,
            **via,
        )

    def hop(
        self,
        principal: str,
        profile: str,
        subject: str,
        key: str,
        *,
        triggers: tuple[str, ...] = (),
        run: str = "run-1",
        client: str = CLIENT,
    ) -> dict[str, Any]:
        result = self.submit(
            principal,
            profile,
            client=client,
            subject_id=subject,
            candidate=f"cand-{key}",
            run=run,
            value=f"Synthetic requirement {key}",
            evidence=(external(f"obj-{key}"),),
            triggers=triggers,
        )
        assert result["outcome"] == "direct_created", result
        return result


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[ProvenanceRuntime]:
    composed = ProvenanceRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def event_of(engine: Engine, mutation_id: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                select(record_events.c.event_id).where(
                    record_events.c.source_receipt_id == mutation_id
                )
            ).scalar_one()
        )


def record_event_of(engine: Engine, family: str, record_id: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                select(record_events.c.event_id)
                .where(
                    record_events.c.record_family == family,
                    record_events.c.record_id == record_id,
                )
                .order_by(record_events.c.sequence_number)
                .limit(1)
            ).scalar_one()
        )


UNKNOWN_EVENT: Final = "rcev_klp05unknown0000001"


# ---- KLP-AC-046 / KLP-AC-143 -------------------------------------------------------


def test_a_direct_created_event_names_its_submission_root_depth_and_triggers(
    runtime: ProvenanceRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    first = runtime.hop(principal, profile, runtime.entity(principal, "p0"), "p0", run="run-a")
    first_event = event_of(runtime.engine, first["mutation_id"])
    second = runtime.hop(
        principal,
        profile,
        runtime.entity(principal, "p1"),
        "p1",
        triggers=(first_event,),
        run="run-b",
    )
    event = event_of(runtime.engine, second["mutation_id"])
    local = runtime.provenance(principal, event, LOCAL)
    assert set(local) == PROVENANCE_KEYS
    assert set(local["submission"]) == SUBMISSION_KEYS
    assert local["event_id"] == event
    assert local["record_family"] == "knowledge_assertion"
    assert local["record_id"] == second["assertion_id"]
    assert local["source_receipt_id"] == second["mutation_id"]
    assert local["mutation_kind"] == "create"
    assert local["actor_class"] == "assistant"
    assert local["review"] is None
    assert local["trigger_event_ids"] == [first_event]
    assert local["submission"] == {
        "submission_id": second["submission_id"],
        "origin": "autonomous_submit",
        "causal_depth": 1,
        "causal_root_submission_id": first["submission_id"],
        "external_run_id": "run-b",
        "external_candidate_id": "cand-p1",
        "self_caused": False,
    }


def test_external_ids_go_only_to_the_supplying_client_or_the_local_principal(
    runtime: ProvenanceRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    created = runtime.hop(principal, profile, runtime.entity(principal, "x"), "x", run="run-x")
    event = event_of(runtime.engine, created["mutation_id"])
    answers = {
        name: runtime.provenance(principal, event, via)
        for name, via in (
            ("local", LOCAL),
            ("supplier", SUPPLIER),
            ("other", OTHER),
            ("chatllm", CHATLLM),
            ("ceilinged", CEILINGED),
        )
    }
    disclosed = {
        name: (
            answer["submission"]["external_run_id"],
            answer["submission"]["external_candidate_id"],
        )
        for name, answer in answers.items()
    }
    assert disclosed == {
        "local": ("run-x", "cand-x"),
        "supplier": ("run-x", "cand-x"),
        "other": (None, None),
        "chatllm": (None, None),
        "ceilinged": (None, None),
    }
    # One pinned shape: every caller gets the same keys, and apart from the two
    # external ids and the caller-relative `self_caused` the answers are equal.
    for answer in answers.values():
        assert set(answer) == PROVENANCE_KEYS
        assert set(answer["submission"]) == SUBMISSION_KEYS

    def stripped(answer: dict[str, Any]) -> dict[str, Any]:
        submission = {
            key: value
            for key, value in answer["submission"].items()
            if key not in {"external_run_id", "external_candidate_id", "self_caused"}
        }
        return {**answer, "submission": submission}

    assert len({repr(stripped(answer)) for answer in answers.values()}) == 1


def test_an_explicit_create_event_is_a_root_with_no_external_ids(
    runtime: ProvenanceRuntime,
) -> None:
    principal = new_principal()
    created = runtime.create(principal, "klp05-explicit")
    event = event_of(runtime.engine, created["mutation_id"])
    local = runtime.provenance(principal, event, LOCAL)
    assert local["actor_class"] == "principal"
    assert local["trigger_event_ids"] == []
    assert local["submission"] == {
        "submission_id": created["submission_id"],
        "origin": "explicit_create",
        "causal_depth": 0,
        "causal_root_submission_id": created["submission_id"],
        "external_run_id": None,
        "external_candidate_id": None,
        "self_caused": False,
    }


# ---- KLP-AC-047 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("via", "channel", "client"),
    [
        (CLI, "local_cli", None),
        (remote(OPERATOR_CLIENT), "remote_operator_review", OPERATOR_CLIENT),
    ],
    ids=["cli_operator", "remote_operator_review"],
)
def test_a_review_promoted_event_names_proposal_case_and_accepting_decision(
    runtime: ProvenanceRuntime, via: dict[str, object], channel: str, client: str | None
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    trigger_source = runtime.hop(
        principal, profile, runtime.entity(principal, "t"), "t", run="run-t"
    )
    trigger = event_of(runtime.engine, trigger_source["mutation_id"])
    queued = runtime.submit(
        principal,
        profile,
        subject_id=runtime.org(principal, "acme"),
        predicate=PAYMENT,
        candidate="cand-review",
        run="run-review",
        value="Synthetic net 30 terms",
        triggers=(trigger,),
    )
    assert queued["outcome"] == "review_queued", queued
    decided = runtime.decide(principal, str(queued["review_case_id"]), Disposition.ACCEPT, via=via)
    event = event_of(runtime.engine, str(decided["receipt_id"]))
    for caller, ids in (
        (LOCAL, ("run-review", "cand-review")),
        (SUPPLIER, ("run-review", "cand-review")),
        (CHATLLM, (None, None)),
    ):
        answer = runtime.provenance(principal, event, caller)
        assert answer["actor_class"] == "review_promotion"
        assert answer["mutation_kind"] == "review_accept"
        assert answer["record_id"] == decided["assertion_id"]
        assert answer["trigger_event_ids"] == [trigger]
        review = answer["review"]
        assert review == {
            "proposal_id": queued["proposal_id"],
            "review_case_id": queued["review_case_id"],
            "decision_id": decided["decision_id"],
            # DEV-13: only the local Principal sees another client's id.
            "authenticated_client_id": client if caller is LOCAL else None,
            "decision_channel": channel,
        }
        assert review["proposal_id"].startswith("kaprp_")
        assert review["review_case_id"].startswith("rvw_")
        assert review["decision_id"].startswith("kadec_")
        submission = answer["submission"]
        # Review promotion inherits the proposal's origin submission (R6 9.1):
        # depth 1 under the cited trigger's root, never reset by the decision.
        assert submission["submission_id"] == queued["submission_id"]
        assert submission["causal_depth"] == 1
        assert submission["causal_root_submission_id"] == trigger_source["submission_id"]
        assert (submission["external_run_id"], submission["external_candidate_id"]) == ids


# ---- DEV-13 (Manager ruling 2026-10-06): client ids are caller-private -------------

#: The operator-review client reading provenance with the same grants.
REVIEWER: Final = remote(OPERATOR_CLIENT, PROVENANCE_GRANTS)


def _operator_promoted_event(runtime: ProvenanceRuntime) -> tuple[str, str]:
    """(principal, event) of a Review promotion decided by the operator-review client."""
    principal = new_principal()
    profile = runtime.profile(principal)
    queued = runtime.submit(
        principal,
        profile,
        subject_id=runtime.org(principal, "dev13"),
        predicate=PAYMENT,
        candidate="cand-dev13",
        run="run-dev13",
        value="Synthetic net 45 terms",
    )
    assert queued["outcome"] == "review_queued", queued
    decided = runtime.decide(
        principal,
        str(queued["review_case_id"]),
        Disposition.ACCEPT,
        via=remote(OPERATOR_CLIENT),
    )
    return principal, event_of(runtime.engine, str(decided["receipt_id"]))


def _decision_client(runtime: ProvenanceRuntime, principal: str, event: str, via: Any) -> Any:  # noqa: ANN401
    return runtime.provenance(principal, event, via)["review"]["authenticated_client_id"]


def test_the_caller_sees_its_own_decision_client_id(runtime: ProvenanceRuntime) -> None:
    principal, event = _operator_promoted_event(runtime)
    assert _decision_client(runtime, principal, event, REVIEWER) == OPERATOR_CLIENT


def test_another_clients_decision_id_is_null_for_every_other_remote_caller(
    runtime: ProvenanceRuntime,
) -> None:
    """An operator-review decision seen by an ordinary client, a discovery client and a ceiling."""
    principal, event = _operator_promoted_event(runtime)
    for via in (CHATLLM, SUPPLIER, CEILINGED):
        answer = runtime.provenance(principal, event, via)
        assert "authenticated_client_id" in answer["review"]
        assert answer["review"]["authenticated_client_id"] is None, via
        # The channel stays: it is the server-derived class, not an identity.
        assert answer["review"]["decision_channel"] == "remote_operator_review"


def test_a_local_caller_sees_every_client_id(runtime: ProvenanceRuntime) -> None:
    principal, event = _operator_promoted_event(runtime)
    assert _decision_client(runtime, principal, event, LOCAL) == OPERATOR_CLIENT


def test_self_caused_uses_the_persisted_ids_before_redaction(runtime: ProvenanceRuntime) -> None:
    """The submitting client is self-caused although no client id is in its answer."""
    principal = new_principal()
    profile = runtime.profile(principal)
    created = runtime.hop(principal, profile, runtime.entity(principal, "sc"), "sc")
    event = event_of(runtime.engine, created["mutation_id"])
    answer = runtime.provenance(principal, event, SUPPLIER)
    assert answer["submission"]["self_caused"] is True
    assert CLIENT not in repr(answer)
    assert runtime.provenance(principal, event, OTHER)["submission"]["self_caused"] is False


# ---- KLP-AC-049 ------------------------------------------------------------------


def test_self_caused_is_computed_from_the_persisted_client_lineage(
    runtime: ProvenanceRuntime,
) -> None:
    principal = new_principal()
    mine = runtime.profile(principal)
    theirs = runtime.profile(principal, client=OTHER_CLIENT, scope="scope-b")
    root = runtime.hop(principal, mine, runtime.entity(principal, "r"), "r", run="run-r")
    root_event = event_of(runtime.engine, root["mutation_id"])
    child = runtime.hop(
        principal,
        theirs,
        runtime.entity(principal, "c"),
        "c",
        triggers=(root_event,),
        run="run-c",
        client=OTHER_CLIENT,
    )
    child_event = event_of(runtime.engine, child["mutation_id"])

    def caused(event: str, via: dict[str, object]) -> tuple[bool, str | None]:
        submission = runtime.provenance(principal, event, via)["submission"]
        return submission["self_caused"], submission["external_run_id"]

    # The root's own client; the child's client, whose lineage the root is not.
    assert caused(root_event, SUPPLIER) == (True, "run-r")
    assert caused(root_event, OTHER) == (False, None)
    # The child's client submitted it; the root's client is its causal root.
    assert caused(child_event, OTHER) == (True, "run-c")
    assert caused(child_event, SUPPLIER) == (True, None)
    assert caused(child_event, CHATLLM) == (False, None)
    # No client is nobody's lineage, locally or under a ceiling.
    assert caused(child_event, LOCAL) == (False, "run-c")
    assert caused(child_event, CEILINGED) == (False, None)
    # The actor class is the stored, transport-derived one.
    assert runtime.provenance(principal, child_event, LOCAL)["actor_class"] == "assistant"


# ---- KLP-AC-119 (provenance-read half) ---------------------------------------------


def test_fresh_run_ids_do_not_reset_the_depth_and_root_provenance_shows(
    runtime: ProvenanceRuntime,
) -> None:
    """Each hop uses a new run id; depth and root still follow the cited events."""
    principal = new_principal()
    profile = runtime.profile(principal)
    triggers: tuple[str, ...] = ()
    hops: list[tuple[dict[str, Any], str]] = []
    for index in range(3):
        result = runtime.hop(
            principal,
            profile,
            runtime.entity(principal, f"f{index}"),
            f"f{index}",
            triggers=triggers,
            run=f"fresh-run-{index}",
        )
        event = event_of(runtime.engine, result["mutation_id"])
        hops.append((result, event))
        triggers = (event,)
    root_id = hops[0][0]["submission_id"]
    for depth, (result, event) in enumerate(hops):
        submission = runtime.provenance(principal, event, SUPPLIER)["submission"]
        assert submission["submission_id"] == result["submission_id"]
        assert submission["causal_depth"] == depth
        assert submission["causal_root_submission_id"] == root_id
        assert submission["external_run_id"] == f"fresh-run-{depth}"


# ---- maintenance (NULL submission) -------------------------------------------------


def test_a_maintenance_event_has_no_submission_and_no_triggers(
    runtime: ProvenanceRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    created = runtime.hop(principal, profile, runtime.entity(principal, "m"), "m")
    with runtime.engine.connect() as connection:
        evidence = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).scalar_one()
    with knowledge_maintenance_transaction(runtime.engine) as repository:
        repository.record_evidence_availability(
            principal, evidence, KnowledgeEvidenceAvailability.PERMISSION_LOST, at=WHEN
        )
    with runtime.engine.connect() as connection:
        maintenance = connection.execute(
            select(record_events.c.event_id)
            .where(
                record_events.c.principal_id == principal,
                record_events.c.record_id == created["assertion_id"],
                record_events.c.actor_class == "system",
            )
            .order_by(record_events.c.sequence_number)
        ).scalar_one()
    local = runtime.provenance(principal, maintenance, LOCAL)
    assert local["actor_class"] == "system"
    assert local["mutation_kind"] == "revalidation_required"
    assert local["submission"] is None
    assert local["trigger_event_ids"] == []
    assert local["review"] is None
    # Permission lost withholds the assertion remotely (section 5.2 (f)).
    assert runtime.provenance_error(principal, maintenance, SUPPLIER) == (
        runtime.provenance_error(principal, UNKNOWN_EVENT, SUPPLIER)
    )


# ---- KLP-AC-048 / 111 / 138: remote withholding ------------------------------------


@pytest.mark.parametrize("lifecycle", LIFECYCLES)
@pytest.mark.parametrize("restriction", RESTRICTIONS)
def test_a_single_restriction_term_withholds_provenance_and_the_feed_remotely(
    runtime: ProvenanceRuntime, restriction: str, lifecycle: str
) -> None:
    principal = new_principal()
    query = f"klp05q{restriction.replace('_', '')}{lifecycle}"
    control = runtime.create(principal, f"{query}-control", value=f"Control {query}")
    target = _target(runtime, principal, restriction, query)
    set_lifecycle(runtime.engine, principal, target, lifecycle)
    set_lifecycle(runtime.engine, principal, control, lifecycle)
    event = event_of(runtime.engine, target["mutation_id"])
    control_event = event_of(runtime.engine, control["mutation_id"])
    # Local: the owning Principal sees the provenance and the event.
    assert runtime.provenance(principal, event, LOCAL)["record_id"] == target["assertion_id"]
    assert event in {item["event_id"] for item in runtime.listed(principal, LOCAL)["events"]}
    unknown = runtime.provenance_error(principal, UNKNOWN_EVENT, SUPPLIER)
    assert unknown["code"] == "not_found"
    for caller in (SUPPLIER, CEILINGED):
        # Withheld answers byte-identically to unknown, and the feed omits it.
        assert runtime.provenance_error(principal, event, caller) == unknown
        listed = {item["event_id"] for item in runtime.listed(principal, caller)["events"]}
        assert event not in listed
        # The unrestricted control stays visible, so the withholding is the term's.
        assert control_event in listed
        assert (
            runtime.provenance(principal, control_event, caller)["record_id"]
            == (control["assertion_id"])
        )


def test_unknown_foreign_withheld_and_non_knowledge_events_answer_alike(
    runtime: ProvenanceRuntime,
) -> None:
    principal = new_principal()
    stranger = new_principal()
    foreign = runtime.create(stranger, "klp05-foreign")
    foreign_event = event_of(runtime.engine, foreign["mutation_id"])
    withheld = runtime.create(principal, "klp05-withheld", value="Withheld value")
    restrict_assertion(runtime.engine, principal, withheld["assertion_id"])
    withheld_event = event_of(runtime.engine, withheld["mutation_id"])
    capture_id, _digest = runtime.capture(principal, "klp05-capture")
    capture_event = record_event_of(runtime.engine, "capture", capture_id)
    remote_unknown = runtime.provenance_error(principal, UNKNOWN_EVENT, SUPPLIER)
    assert remote_unknown["code"] == "not_found"
    for event in (foreign_event, withheld_event, capture_event):
        assert runtime.provenance_error(principal, event, SUPPLIER) == remote_unknown
    # Locally the withheld event is the Principal's own; the foreign and the
    # non-Knowledge (WP-05 DEV-01) ones still answer exactly as unknown.
    local_unknown = runtime.provenance_error(principal, UNKNOWN_EVENT, LOCAL)
    assert local_unknown == remote_unknown
    for event in (foreign_event, capture_event):
        assert runtime.provenance_error(principal, event, LOCAL) == local_unknown
    assert runtime.provenance(principal, withheld_event, LOCAL)["event_id"] == withheld_event


def test_a_remote_feed_page_of_n_is_filled_with_visible_events_before_limit(
    runtime: ProvenanceRuntime,
) -> None:
    """The withheld events are the *oldest*: a filter after LIMIT would return none."""
    principal = new_principal()
    withheld = [
        runtime.create(principal, f"klp05-w{index}", value=f"Withheld {index}")
        for index in range(3)
    ]
    for created in withheld:
        restrict_assertion(runtime.engine, principal, created["assertion_id"])
    visible = [
        runtime.create(principal, f"klp05-v{index}", value=f"Visible {index}") for index in range(4)
    ]
    page = runtime.listed(principal, SUPPLIER, page_size=3)
    events = [item["event_id"] for item in page["events"]]
    assert events == [event_of(runtime.engine, created["mutation_id"]) for created in visible[:3]]
    assert page["next_cursor"] is not None
    rest = runtime.ok(
        ListRecordEvents(
            page_size=3,
            record_families=(RecordEventFamily.KNOWLEDGE_ASSERTION,),
            cursor=page["next_cursor"],
        ),
        principal_id=principal,
        **SUPPLIER,
    )
    assert [item["event_id"] for item in rest["events"]] == [
        event_of(runtime.engine, visible[3]["mutation_id"])
    ]
    assert rest["next_cursor"] is None


def test_the_visible_trigger_list_omits_withheld_and_invisible_family_triggers(
    runtime: ProvenanceRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    cited = runtime.create(principal, "klp05-cited", value="Cited value")
    cited_event = event_of(runtime.engine, cited["mutation_id"])
    # The second cited event descends from the first, so both share one root
    # (two independent roots would be `causal_root_ambiguous`).
    kept = runtime.hop(
        principal, profile, runtime.entity(principal, "kept"), "kept", triggers=(cited_event,)
    )
    kept_event = event_of(runtime.engine, kept["mutation_id"])
    capture_id, _digest = runtime.capture(principal, "klp05-trigger-capture")
    capture_event = record_event_of(runtime.engine, "capture", capture_id)
    result = runtime.hop(
        principal,
        profile,
        runtime.entity(principal, "tv"),
        "tv",
        triggers=(cited_event, kept_event, capture_event),
    )
    event = event_of(runtime.engine, result["mutation_id"])
    every = sorted([cited_event, kept_event, capture_event])
    assert runtime.provenance(principal, event, LOCAL)["trigger_event_ids"] == every
    # The remote grants make only the Knowledge family visible: the capture
    # trigger is outside the caller's families.
    assert runtime.provenance(principal, event, SUPPLIER)["trigger_event_ids"] == sorted(
        [cited_event, kept_event]
    )
    restrict_assertion(runtime.engine, principal, cited["assertion_id"])
    assert runtime.provenance(principal, event, LOCAL)["trigger_event_ids"] == every
    assert runtime.provenance(principal, event, SUPPLIER)["trigger_event_ids"] == [kept_event]
    assert runtime.provenance(principal, event, CEILINGED)["trigger_event_ids"] == [kept_event]


def test_a_remote_caller_without_the_provenance_grant_is_refused(
    runtime: ProvenanceRuntime,
) -> None:
    principal = new_principal()
    created = runtime.create(principal, "klp05-grant")
    event = event_of(runtime.engine, created["mutation_id"])
    feed_only = remote(
        CLIENT,
        frozenset(
            {
                (Capability.RECORD_EVENTS_LIST, Purpose.RECORD_EVENT_READ),
                (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ),
            }
        ),
    )
    assert runtime.provenance_error(principal, event, feed_only)["code"] == "unsupported"


# ---- concurrency: an uncommitted restriction ---------------------------------------


def test_an_uncommitted_restriction_neither_blocks_nor_leaks_then_withholds(
    runtime: ProvenanceRuntime,
) -> None:
    """Two connections: a restriction held open does not block the read, then withholds.

    The restricting transaction holds the assertion row lock (UPDATE) while the
    provenance read runs on another pooled connection: the read returns the
    committed state without waiting (no lock wait is observed in `pg_locks`),
    and once the restriction commits the same remote read is `not_found`.
    """
    principal = new_principal()
    created = runtime.create(principal, "klp05-race")
    event = event_of(runtime.engine, created["mutation_id"])
    with runtime.engine.connect() as holder:
        transaction = holder.begin()
        holder.execute(
            text(
                "UPDATE knowledge.knowledge_assertions SET classification = 'restricted_local', "
                "version = version + 1, updated_at = now() WHERE assertion_id = :a"
            ),
            {"a": created["assertion_id"]},
        )
        holder.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertion_mutations (principal_id, mutation_id, "
                "assertion_id, mutation_kind, prior_version, new_version, created_at) "
                "VALUES (:p, :m, :a, 'classify', 1, 2, now())"
            ),
            {"p": principal, "m": "kamut_klp05race00000001", "a": created["assertion_id"]},
        )
        answer = runtime.provenance(principal, event, SUPPLIER)
        assert answer["record_id"] == created["assertion_id"]
        with runtime.engine.connect() as observer:
            waiting = observer.execute(
                text("SELECT count(*) FROM pg_locks WHERE NOT granted")
            ).scalar_one()
        assert waiting == 0
        transaction.commit()
    unknown = runtime.provenance_error(principal, UNKNOWN_EVENT, SUPPLIER)
    assert runtime.provenance_error(principal, event, SUPPLIER) == unknown


# ---- the restricted runtime role ----------------------------------------------------


def test_the_runtime_role_executes_the_provenance_statements(
    provisioned: Engine,  # noqa: F811 - the imported fixture
    cloned_database_url: str,
) -> None:
    """The feed role's SELECT set covers the lineage joins and the trigger listing."""
    composed = ProvenanceRuntime(cloned_database_url)
    try:
        principal = new_principal()
        profile = composed.profile(principal)
        first = composed.hop(principal, profile, composed.entity(principal, "rr0"), "rr0")
        first_event = event_of(composed.engine, first["mutation_id"])
        second = composed.hop(
            principal,
            profile,
            composed.entity(principal, "rr1"),
            "rr1",
            triggers=(first_event,),
        )
        event = event_of(composed.engine, second["mutation_id"])
    finally:
        composed.close()
    families = frozenset({RecordEventFamily.KNOWLEDGE_ASSERTION})
    with provisioned.connect() as connection:
        connection.execute(text(f"SET SESSION AUTHORIZATION {RUNTIME_ROLE}"))
        connection.commit()
        try:
            assert connection.execute(text("SELECT session_user")).scalar_one() == RUNTIME_ROLE
            reader = SqlRecordEventReader(connection)
            found = [
                reader.event_provenance(
                    principal_id=principal,
                    event_id=event,
                    event_families=families,
                    trigger_families=families,
                    include_restricted_memory=include,
                )
                for include in (True, False)
            ]
            connection.rollback()
        finally:
            connection.execute(text("RESET SESSION AUTHORIZATION"))
            connection.commit()
    for provenance in found:
        assert provenance is not None
        assert provenance.submission is not None
        assert provenance.submission.causal_root_submission_id == first["submission_id"]
        assert provenance.trigger_event_ids == (first_event,)
