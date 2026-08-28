"""Database contract for the authoritative identity-history projection.

This focused module is completed by the integration owner once WP-01's migration
and shared repository wiring land.  The tests are intentionally stated against
the public query rather than by scraping review records.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from my_pa.infrastructure.persistence.entity_identity_history import SqlIdentityHistoryQuery


def test_every_history_union_branch_carries_its_own_principal_predicate() -> None:
    """Deleting a branch predicate must redden before a database is contacted."""
    query = object.__new__(SqlIdentityHistoryQuery)
    statement = query._history("prn_aaaa0001aaaa0001aaaa0001", "ent_aaaa0001aaaa0001")
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()

    assert sql.count("principal_id =") == 3
    assert "entity_mutation_events" in sql
    assert "entity_identity_operations" in sql
    assert "entity_merge_records" in sql
    assert "union all" in sql


def test_history_is_not_derived_from_preview_proposal_or_review_tables() -> None:
    query = object.__new__(SqlIdentityHistoryQuery)
    statement = query._history("prn_aaaa0001aaaa0001aaaa0001", "ent_aaaa0001aaaa0001")
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()

    assert "entity_identity_previews" not in sql
    assert "entity_proposals" not in sql
    assert "entity_proposal_review" not in sql
