"""KLP-WP-04: the causal lineage rule, the submit event attribution and the ledger SQLSTATEs.

FAST, unmarked (repository-checks / validate, dependency-floor).

* KLP-AC-049 (unit half) -- `resolve_causal_position` (WP-01's pure rule, which
  autonomous submit feeds with server-resolved parents only): no parent -> self
  at depth 0; one root -> inherit at 1 + max depth; two roots -> ambiguous;
  depth 5 -> exceeded; a repeated key anywhere in the ancestor set -> repeat,
  checked first; a client-chosen value (run id, candidate id) is not an input,
  so it cannot change the answer. The autonomous origin maps to actor
  `assistant` / authority `source_backed_assertion`, derived from the
  transport/client binding (the origin), never from the request.
* KLP-AC-042 (unit half) -- the submit mutation kinds map to the frozen events:
  create/supersede_successor `created`, supersede_predecessor and revalidation
  `state_changed(lifecycle)`, evidence_enrich `updated(evidence)`, classify
  `state_changed(classification)`.
* WP-02 DEV-01 (Manager ruling) -- `KNOWLEDGE_LEDGER_TRIGGERS` maps each
  submission / checkpoint-request trigger refusal (function, SQLSTATE) to
  `KnowledgeLedgerInvariantError`, which `_port_failure` answers
  `internal_error`; any other 23514/23001 is not a ledger refusal.
"""

from __future__ import annotations

from typing import Final

import pytest
from sqlalchemy.exc import IntegrityError

from my_pa.application.errors import InternalError
from my_pa.application.service import _port_failure
from my_pa.contracts.ports import KnowledgeLedgerInvariantError
from my_pa.domain.knowledge_assertion.provenance import (
    KNOWLEDGE_EVENT_ACTOR_CLASSES,
    KNOWLEDGE_EVENT_AUTHORITIES,
    KNOWLEDGE_MUTATION_EVENTS,
    MAX_CAUSAL_DEPTH,
    CausalKey,
    CausalParent,
    CausalPosition,
    CausalRefusal,
    KnowledgeEventOrigin,
    resolve_causal_position,
)
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeMutationKind,
    KnowledgeSubmissionReason,
)
from my_pa.domain.record_events import RecordEventActorClass, RecordEventAuthority
from my_pa.infrastructure.persistence.knowledge_assertions import (
    KNOWLEDGE_LEDGER_TRIGGERS,
    knowledge_ledger_failure,
)

OWN: Final = "kasub_ownsubmission0001"
KEY: Final = CausalKey("klp04-client", "entity", "ent_synthetic00000001", "policy.requirement")


def _resolve(
    parents: list[CausalParent], ancestors: list[CausalKey] | None = None
) -> CausalPosition | CausalRefusal:
    return resolve_causal_position(
        own_submission_id=OWN, own_key=KEY, parents=parents, ancestor_keys=ancestors or []
    )


def test_no_knowledge_parent_is_a_new_root() -> None:
    assert _resolve([]) == CausalPosition(root_submission_id=OWN, depth=0)


@pytest.mark.parametrize("depth", range(MAX_CAUSAL_DEPTH))
def test_one_root_is_inherited_at_one_plus_the_deepest_parent(depth: int) -> None:
    parents = [
        CausalParent("kasub_root000000000001", depth),
        CausalParent("kasub_root000000000001", 0),
    ]
    assert _resolve(parents) == CausalPosition("kasub_root000000000001", depth + 1)


def test_a_fifth_level_is_refused_depth_exceeded() -> None:
    refused = _resolve([CausalParent("kasub_root000000000001", MAX_CAUSAL_DEPTH)])
    assert refused == CausalRefusal(KnowledgeSubmissionReason.CAUSAL_DEPTH_EXCEEDED)


def test_two_roots_are_ambiguous() -> None:
    refused = _resolve(
        [CausalParent("kasub_root000000000001", 0), CausalParent("kasub_root000000000002", 0)]
    )
    assert refused == CausalRefusal(KnowledgeSubmissionReason.CAUSAL_ROOT_AMBIGUOUS)


def test_a_repeat_anywhere_in_the_lineage_wins_over_every_other_rule() -> None:
    other = CausalKey("klp04-client", "entity", "ent_synthetic00000002", "policy.requirement")
    refused = _resolve(
        [CausalParent("kasub_root000000000001", 0), CausalParent("kasub_root000000000002", 0)],
        [other, KEY],
    )
    assert refused == CausalRefusal(KnowledgeSubmissionReason.CAUSAL_REPEAT)


def test_another_client_on_the_same_subject_is_not_a_repeat() -> None:
    peer = CausalKey("klp04-other", KEY.subject_kind, KEY.subject_id, KEY.predicate_code)
    assert _resolve([CausalParent(OWN, 0)], [peer]) == CausalPosition(OWN, 1)


def test_the_autonomous_origin_is_assistant_and_source_backed() -> None:
    origin = KnowledgeEventOrigin.AUTONOMOUS_SUBMIT
    assert KNOWLEDGE_EVENT_ACTOR_CLASSES[origin] is RecordEventActorClass.ASSISTANT
    assert KNOWLEDGE_EVENT_AUTHORITIES[origin] is RecordEventAuthority.SOURCE_BACKED_ASSERTION


@pytest.mark.parametrize(
    ("kind", "event", "fields"),
    [
        (KnowledgeMutationKind.CREATE, "created", None),
        (KnowledgeMutationKind.SUPERSEDE_SUCCESSOR, "created", None),
        (KnowledgeMutationKind.SUPERSEDE_PREDECESSOR, "state_changed", ("lifecycle",)),
        (KnowledgeMutationKind.EVIDENCE_ENRICH, "updated", ("evidence",)),
        (KnowledgeMutationKind.CLASSIFY, "state_changed", ("classification",)),
        (KnowledgeMutationKind.REVALIDATION_REQUIRED, "state_changed", ("lifecycle",)),
    ],
)
def test_the_submit_mutation_kinds_map_to_the_frozen_events(
    kind: KnowledgeMutationKind, event: str, fields: tuple[str, ...] | None
) -> None:
    mapped = KNOWLEDGE_MUTATION_EVENTS[kind]
    assert mapped.kind.value == event
    if fields is not None:
        assert mapped.changed_fields == fields


# ---- the ledger SQLSTATE table (WP-02 DEV-01) ----------------------------------------


class _Diag:
    def __init__(self, context: str | None) -> None:
        self.context = context


class _DriverError(Exception):
    def __init__(self, sqlstate: str, context: str | None) -> None:
        super().__init__("synthetic driver message")
        self.sqlstate = sqlstate
        self.diag = _Diag(context)


def _wrapped(sqlstate: str, function: str | None) -> IntegrityError:
    context = (
        None if function is None else f"PL/pgSQL function knowledge.{function}() line 9 at RAISE"
    )
    return IntegrityError("UPDATE ...", {}, _DriverError(sqlstate, context))


def test_the_table_names_both_ledgers_and_only_their_documented_states() -> None:
    assert set(KNOWLEDGE_LEDGER_TRIGGERS) == {
        ("knowledge_submission_lifecycle_guard", "23514"),
        ("knowledge_submission_lifecycle_guard", "23001"),
        ("knowledge_submission_reserved_at_commit", "23514"),
        ("knowledge_checkpoint_request_lifecycle_guard", "23001"),
        ("knowledge_checkpoint_request_reserved_at_commit", "23001"),
    }
    assert set(KNOWLEDGE_LEDGER_TRIGGERS.values()) == {KnowledgeLedgerInvariantError}


@pytest.mark.parametrize(("function", "sqlstate"), sorted(KNOWLEDGE_LEDGER_TRIGGERS))
def test_each_ledger_refusal_maps_to_the_invariant_error(function: str, sqlstate: str) -> None:
    assert knowledge_ledger_failure(_wrapped(sqlstate, function)) is KnowledgeLedgerInvariantError


@pytest.mark.parametrize(
    ("function", "sqlstate"),
    [
        ("knowledge_assertion_head_guard", "23514"),  # race 19: not a ledger refusal
        ("knowledge_row_is_append_only", "23001"),
        ("knowledge_checkpoint_request_lifecycle_guard", "23514"),  # undocumented state
        (None, "23514"),  # a plain CHECK has no PL/pgSQL context
    ],
)
def test_other_refusals_are_not_ledger_refusals(function: str | None, sqlstate: str) -> None:
    assert knowledge_ledger_failure(_wrapped(sqlstate, function)) is None


def test_the_invariant_error_is_internal_error() -> None:
    assert isinstance(_port_failure(KnowledgeLedgerInvariantError("x")), InternalError)
