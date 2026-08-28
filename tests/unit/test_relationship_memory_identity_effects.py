"""Direct, content-blind Relationship Memory identity-effect behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from my_pa.application.identity_correction import _inverse_drafts
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.relationship.identity_correction import (
    IdentityEffectDraft,
    IdentityEffectFamily,
    IdentityEffectKind,
    sequence_effects,
)
from my_pa.infrastructure.persistence.relationship_memory import (
    SqlRelationshipMemoryRepository,
)

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
MERGED = "ent_bbbb0002bbbb0002"
SURVIVOR = "ent_aaaa0001aaaa0001"


def _rows(*rows: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(all=lambda: list(rows))


def test_memory_merge_plan_records_only_reversible_opaque_bindings() -> None:
    connection = MagicMock()
    connection.execute.side_effect = [
        _rows(
            SimpleNamespace(
                memory_id="mem_aaaa0001aaaa01",
                subject_entity_id=MERGED,
                origin_subject_entity_id=MERGED,
                version=2,
            )
        ),
        _rows(
            SimpleNamespace(
                memory_proposal_id="mprop_aaaa0001aaaa01",
                subject_entity_id=MERGED,
                origin_subject_entity_id=MERGED,
                expected_subject_version=2,
                context_links=[{"target_type": "entity", "target_id": MERGED}],
            )
        ),
        _rows(
            SimpleNamespace(
                context_link_id="mctx_aaaa0001aaaa01",
                target_id=MERGED,
                origin_subject_entity_id=MERGED,
            )
        ),
    ]
    repository = SqlRelationshipMemoryRepository(connection)

    drafts = repository.plan_identity_merge(PRINCIPAL, frozenset({MERGED}), SURVIVOR, 5)

    assert [draft.family for draft in drafts] == [
        IdentityEffectFamily.RELATIONSHIP_MEMORY,
        IdentityEffectFamily.MEMORY_PROPOSAL,
        IdentityEffectFamily.MEMORY_CONTEXT_LINK,
    ]
    assert all(draft.kind is IdentityEffectKind.OWNER_REPARENTED for draft in drafts)
    assert drafts[0].after_state["subject_entity_id"] == SURVIVOR
    assert drafts[1].after_state["subject_entity_id"] == SURVIVOR
    assert drafts[1].before_state["expected_subject_version"] == 2
    assert drafts[1].after_state["expected_subject_version"] == 5
    assert drafts[1].after_state["context_links"] == [
        {
            "target_type": "entity",
            "target_id": SURVIVOR,
            "origin_subject_entity_id": MERGED,
        }
    ]
    assert drafts[1].before_state["context_links"] == [
        {"target_type": "entity", "target_id": MERGED}
    ]
    assert drafts[2].after_state["target_id"] == SURVIVOR
    field_names = {
        name for draft in drafts for name in (*draft.before_state.keys(), *draft.after_state.keys())
    }
    assert not ({"statement", "classification"} & field_names)

    stale_connection = MagicMock()
    stale_connection.execute.return_value = SimpleNamespace(rowcount=0)
    with pytest.raises(UnknownScopeError):
        SqlRelationshipMemoryRepository(stale_connection).apply_identity_effect(
            PRINCIPAL, drafts[1]
        )
    compiled = stale_connection.execute.call_args.args[0].compile()
    assert "expected_subject_version" in str(compiled)
    assert 2 in compiled.params.values()


def test_context_only_proposal_move_retains_its_subject_token() -> None:
    connection = MagicMock()
    connection.execute.side_effect = [
        _rows(),
        _rows(
            SimpleNamespace(
                memory_proposal_id="mprop_aaaa0001aaaa01",
                subject_entity_id=SURVIVOR,
                origin_subject_entity_id=SURVIVOR,
                expected_subject_version=5,
                context_links=[
                    {
                        "target_type": "entity",
                        "target_id": MERGED,
                        "origin_subject_entity_id": MERGED,
                    }
                ],
            )
        ),
        _rows(),
    ]

    draft = SqlRelationshipMemoryRepository(connection).plan_identity_merge(
        PRINCIPAL, frozenset({MERGED}), SURVIVOR, 5
    )[0]

    assert draft.before_state["subject_entity_id"] == SURVIVOR
    assert draft.after_state["subject_entity_id"] == SURVIVOR
    assert draft.before_state["expected_subject_version"] == 5
    assert draft.after_state["expected_subject_version"] == 5


def test_memory_restore_requires_the_exact_after_state_and_writes_the_before_state() -> None:
    connection = MagicMock()
    connection.execute.return_value = SimpleNamespace(rowcount=1)
    repository = SqlRelationshipMemoryRepository(connection)
    draft_connection = MagicMock()
    draft_connection.execute.side_effect = [
        _rows(
            SimpleNamespace(
                memory_id="mem_aaaa0001aaaa01",
                subject_entity_id=MERGED,
                origin_subject_entity_id=MERGED,
                version=2,
            )
        ),
        _rows(),
        _rows(),
    ]
    draft = SqlRelationshipMemoryRepository(draft_connection).plan_identity_merge(
        PRINCIPAL, frozenset({MERGED}), SURVIVOR, 5
    )[0]
    effect = sequence_effects(
        (draft,),
        identity_operation_id="eiop_aaaa0001aaaa01",
        principal_id=PRINCIPAL,
        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
    )[0]

    inverse = _inverse_drafts((effect,))[0]
    repository.restore_identity_effect(PRINCIPAL, effect, restored_state=inverse.after_state)

    statement = connection.execute.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "principal_id" in compiled
    assert "subject_entity_id" in compiled
    assert "origin_subject_entity_id" in compiled
    assert "version" in compiled
    assert SURVIVOR in compiled
    assert statement._values["subject_entity_id"].value == MERGED

    connection.execute.return_value = SimpleNamespace(rowcount=0)
    with pytest.raises(UnknownScopeError):
        repository.restore_identity_effect(PRINCIPAL, effect, restored_state=inverse.after_state)


def test_proposal_split_restores_target_without_removing_legacy_origin() -> None:
    draft_connection = MagicMock()
    draft_connection.execute.side_effect = [
        _rows(),
        _rows(
            SimpleNamespace(
                memory_proposal_id="mprop_aaaa0001aaaa01",
                subject_entity_id=MERGED,
                origin_subject_entity_id=MERGED,
                expected_subject_version=7,
                context_links=[{"target_type": "entity", "target_id": MERGED}],
            )
        ),
        _rows(),
    ]
    draft = SqlRelationshipMemoryRepository(draft_connection).plan_identity_merge(
        PRINCIPAL, frozenset({MERGED}), SURVIVOR, 5
    )[0]
    entity_draft = IdentityEffectDraft(
        family=IdentityEffectFamily.ENTITY,
        record_id=MERGED,
        kind=IdentityEffectKind.ENTITY_REDIRECTED,
        before_state={"status": "active", "superseded_by_entity_id": None, "version": 7},
        after_state={
            "status": "merged_redirect",
            "superseded_by_entity_id": SURVIVOR,
            "version": 8,
        },
    )
    effects = sequence_effects(
        (entity_draft, draft),
        identity_operation_id="eiop_aaaa0001aaaa01",
        principal_id=PRINCIPAL,
        recorded_at=datetime(2026, 8, 28, tzinfo=UTC),
    )
    effect = effects[1]
    assert effect.before_state["expected_subject_version"] == 7
    assert effect.after_state["expected_subject_version"] == 5
    inverse = _inverse_drafts(effects)[0]
    assert inverse.after_state["expected_subject_version"] == 9
    assert inverse.after_state["context_links"] == [
        {
            "target_type": "entity",
            "target_id": MERGED,
            "origin_subject_entity_id": MERGED,
        }
    ]
    connection = MagicMock()
    connection.execute.return_value = SimpleNamespace(rowcount=1)

    SqlRelationshipMemoryRepository(connection).restore_identity_effect(
        PRINCIPAL, effect, restored_state=inverse.after_state
    )

    statement = connection.execute.call_args.args[0]
    assert statement._values["context_links"].value == [
        {
            "target_type": "entity",
            "target_id": MERGED,
            "origin_subject_entity_id": MERGED,
        }
    ]
    assert statement._values["expected_subject_version"].value == 9
