"""WP-9 identity and read-model invariants without persistence."""

from __future__ import annotations

import ast
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import pytest

from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.relationship import identity as identity_models
from my_pa.domain.relationship.identity import (
    IdentityObservation,
    IdentityResolutionError,
    UnresolvedMention,
)
from my_pa.domain.relationship.profile import (
    CoverageDomain,
    PersonProfile,
    ProfileIndicator,
    ProfileIndicatorBasis,
    ProfileIndicatorName,
    RelationshipFreshness,
)
from my_pa.infrastructure.persistence.tables import METADATA

WHEN = datetime(2026, 8, 4, 12, tzinfo=UTC)
OBSERVATION_ID = "iobs_0000000000000001"


def test_source_observation_has_no_canonical_person_link() -> None:
    observation = IdentityObservation(
        observation_id=OBSERVATION_ID,
        source_id="src_0000000000000001",
        source_object_id="obj_0000000000000001",
        source_version="ver_0000000000000001",
        observed_at=WHEN,
        display_name="Synthetic Person",
    )
    assert observation.display_name == "Synthetic Person"
    assert "person_id" not in {field.name for field in fields(IdentityObservation)}


def test_profile_coverage_fails_closed_unless_it_names_the_exact_observation_set() -> None:
    with pytest.raises(ValueError, match="exact observation set"):
        PersonProfile(
            person_id="per_0000000000000001",
            display_name="Synthetic Person",
            observation_ids=(OBSERVATION_ID,),
            coverage=(
                CoverageDomain(
                    domain="contacts",
                    state=CoverageState.UNAVAILABLE,
                    observation_ids=(),
                    observed_at=None,
                    as_of=WHEN,
                    freshness=RelationshipFreshness.UNAVAILABLE,
                    limitation="not supplied",
                ),
            ),
            evidence=(),
            timeline=(),
        )


def test_unavailable_is_never_an_empty_processed_domain() -> None:
    with pytest.raises(ValueError, match="search completed"):
        CoverageDomain(
            domain="calendar",
            state=CoverageState.PROCESSED,
            observation_ids=(),
            observed_at=None,
            as_of=WHEN,
            freshness=RelationshipFreshness.UNKNOWN,
        )


def test_successful_zero_result_is_explicit_and_does_not_claim_freshness() -> None:
    coverage = CoverageDomain(
        domain="calendar",
        state=CoverageState.PROCESSED,
        observation_ids=(),
        observed_at=WHEN,
        as_of=WHEN,
        freshness=RelationshipFreshness.UNKNOWN,
        zero_result_basis="synthetic fixture domain was searched successfully",
    )
    assert coverage.observation_ids == ()
    assert coverage.freshness is RelationshipFreshness.UNKNOWN


def test_indicator_requires_a_basis_and_time_window() -> None:
    with pytest.raises(ValueError, match="closed observable calculation basis"):
        ProfileIndicator(
            name=ProfileIndicatorName.INTERACTION_COUNT,
            value=2,
            calculation_basis="",  # type: ignore[arg-type]
            window_start=WHEN,
            window_end=WHEN,
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("relationship_health_score", 95),
        ("affinity_index", 8),
        ("protected_religion", "synthetic-faith"),
    ],
)
def test_indicator_generic_channel_rejects_scores_and_sensitive_traits(
    name: str, value: object
) -> None:
    with pytest.raises(ValueError, match="closed semantic name"):
        ProfileIndicator(
            name=name,  # type: ignore[arg-type]
            value=value,  # type: ignore[arg-type]
            calculation_basis=ProfileIndicatorBasis.SOURCE_OBSERVATION_COUNT,
            window_start=WHEN,
            window_end=WHEN,
        )


@pytest.mark.parametrize("value", [-1, 2_147_483_648, True, "3", "protected_religion"])
def test_interaction_count_has_a_typed_bounded_value(value: object) -> None:
    with pytest.raises(ValueError, match="bounded non-negative integer"):
        ProfileIndicator(
            name=ProfileIndicatorName.INTERACTION_COUNT,
            value=value,  # type: ignore[arg-type]
            calculation_basis=ProfileIndicatorBasis.SOURCE_OBSERVATION_COUNT,
            window_start=WHEN,
            window_end=WHEN,
        )


def test_unresolved_source_binding_is_bounded_without_storing_raw_mention_text() -> None:
    with pytest.raises(IdentityResolutionError, match="bounded"):
        UnresolvedMention(
            unresolved_mention_id="umen_0000000000000001",
            source_object_id="obj_0000000000000001",
            source_version="x" * 73,
            observed_at=WHEN,
        )
    assert "raw_text" not in {field.name for field in fields(UnresolvedMention)}


EXPECTED_MODEL_FIELDS = {
    "my_pa.domain.relationship.identity.Affiliation": frozenset(
        {
            "affiliation_id",
            "person_id",
            "organization_id",
            "observation_id",
            "role",
            "effective_from",
            "effective_to",
        }
    ),
    "my_pa.domain.relationship.identity.Alias": frozenset(
        {"alias_id", "person_id", "value", "observation_id"}
    ),
    "my_pa.domain.relationship.identity.DuplicateCandidateSet": frozenset(
        {"candidate_set_id", "person_ids", "observation_ids", "created_at"}
    ),
    "my_pa.domain.relationship.identity.IdentityCandidateSet": frozenset(
        {"candidate_set_id", "person_ids", "observation_ids", "created_at"}
    ),
    "my_pa.domain.relationship.identity.IdentityObservation": frozenset(
        {
            "observation_id",
            "source_id",
            "source_object_id",
            "source_version",
            "observed_at",
            "display_name",
        }
    ),
    "my_pa.domain.relationship.identity.IdentityResolution": frozenset(
        {
            "resolution_id",
            "action",
            "review_case_id",
            "decision_id",
            "retained_person_id",
            "prior_person_id",
            "observation_ids",
            "decided_at",
        }
    ),
    "my_pa.domain.relationship.identity.Organization": frozenset(
        {"organization_id", "display_name", "created_at"}
    ),
    "my_pa.domain.relationship.identity.Person": frozenset(
        {"person_id", "display_name", "created_at", "superseded_by_person_id"}
    ),
    "my_pa.domain.relationship.identity.UnresolvedMention": frozenset(
        {"unresolved_mention_id", "source_object_id", "source_version", "observed_at"}
    ),
    "my_pa.domain.relationship.profile.CoverageDomain": frozenset(
        {
            "domain",
            "state",
            "observation_ids",
            "observed_at",
            "as_of",
            "freshness",
            "limitation",
            "zero_result_basis",
        }
    ),
    "my_pa.domain.relationship.profile.EvidenceItem": frozenset(
        {"evidence_id", "authority", "observation_ids", "effective_at", "recorded_at"}
    ),
    "my_pa.domain.relationship.profile.OrganizationProfile": frozenset(
        {"organization_id", "display_name", "affiliations", "observation_ids"}
    ),
    "my_pa.domain.relationship.profile.PersonProfile": frozenset(
        {
            "person_id",
            "display_name",
            "observation_ids",
            "coverage",
            "evidence",
            "timeline",
            "aliases",
            "indicators",
            "completeness_claimed",
        }
    ),
    "my_pa.domain.relationship.profile.ProfileIndicator": frozenset(
        {"name", "value", "calculation_basis", "window_start", "window_end"}
    ),
    "my_pa.domain.relationship.profile.TimelineItem": frozenset(
        {"timeline_item_id", "person_id", "occurred_at", "observation_ids", "authority"}
    ),
    "my_pa.domain.relationship.provider.PersonalSourceBatch": frozenset(
        {"domain", "state", "observations", "limitation"}
    ),
}

EXPECTED_TABLE_COLUMNS = {
    "relationship_affiliations": frozenset(
        {
            "affiliation_id",
            "person_id",
            "organization_id",
            "observation_id",
            "role",
            "effective_from",
            "effective_to",
        }
    ),
    "relationship_aliases": frozenset({"alias_id", "person_id", "observation_id", "value"}),
    "relationship_conversation_observations": frozenset({"participant_id", "observation_id"}),
    "relationship_conversation_participants": frozenset(
        {"participant_id", "conversation_id", "person_id", "unresolved_mention_id"}
    ),
    "relationship_duplicate_members": frozenset(
        {"duplicate_set_id", "person_id", "observation_id"}
    ),
    "relationship_duplicate_sets": frozenset({"duplicate_set_id", "candidate_kind", "created_at"}),
    "relationship_evidence": frozenset(
        {"evidence_id", "person_id", "authority", "effective_at", "recorded_at"}
    ),
    "relationship_evidence_observations": frozenset({"evidence_id", "observation_id"}),
    "relationship_identity_observations": frozenset(
        {
            "observation_id",
            "source_id",
            "source_object_id",
            "source_version",
            "source_domain",
            "display_name",
            "observed_at",
        }
    ),
    "relationship_identity_resolutions": frozenset(
        {
            "resolution_id",
            "resolution_sequence",
            "action",
            "review_case_id",
            "decision_id",
            "retained_person_id",
            "prior_person_id",
            "decided_at",
        }
    ),
    "relationship_identity_review_cases": frozenset(
        {
            "review_case_id",
            "duplicate_set_id",
            "requested_action",
            "retained_person_id",
            "prior_person_id",
            "opened_at",
        }
    ),
    "relationship_identity_review_decisions": frozenset(
        {"decision_id", "review_case_id", "sequence", "disposition", "principal_id", "decided_at"}
    ),
    "relationship_observation_links": frozenset({"observation_id", "person_id", "resolution_id"}),
    "relationship_organizations": frozenset({"organization_id", "display_name", "created_at"}),
    "relationship_people": frozenset(
        {
            "person_id",
            "display_name",
            "created_at",
            "superseded_by_person_id",
            "state_resolution_id",
        }
    ),
    "relationship_resolution_observations": frozenset({"resolution_id", "observation_id"}),
    "relationship_unresolved_mentions": frozenset(
        {"unresolved_mention_id", "source_object_id", "source_version", "observed_at"}
    ),
}


def _assert_closed_vocabulary(
    actual: dict[str, frozenset[str]], expected: dict[str, frozenset[str]]
) -> None:
    assert actual == expected, "unexpected relationship fields or undiscovered relationship surface"


def test_relationship_models_and_tables_have_a_closed_field_vocabulary() -> None:
    assert identity_models.__file__ is not None
    relationship_package = Path(identity_models.__file__).parent
    modules = tuple(
        import_module(f"my_pa.domain.relationship.{path.stem}")
        for path in sorted(relationship_package.glob("*.py"))
        if path.stem != "__init__"
    )
    models = {
        f"{value.__module__}.{value.__name__}": value
        for module in modules
        for value in vars(module).values()
        if isinstance(value, type)
        and is_dataclass(value)
        and value.__module__.startswith("my_pa.domain.relationship")
    }
    actual_model_fields = {
        name: frozenset(field.name for field in fields(model)) for name, model in models.items()
    }
    actual_table_columns = {
        table.name: frozenset(column.name for column in table.columns)
        for table in METADATA.tables.values()
        if table.name.startswith("relationship_")
    }
    assert len(actual_model_fields) == 16
    assert len(actual_table_columns) == 17
    ast_dataclasses = {
        f"my_pa.domain.relationship.{path.stem}.{node.name}"
        for path in sorted(relationship_package.glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(decorator, ast.Name) and decorator.id == "dataclass")
            or (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "dataclass"
            )
            for decorator in node.decorator_list
        )
    }
    assert ast_dataclasses == set(actual_model_fields)
    tables_module = import_module("my_pa.infrastructure.persistence.tables")
    assert tables_module.__file__ is not None
    table_tree = ast.parse(Path(tables_module.__file__).read_text())
    ast_relationship_tables = {
        target.id
        for node in ast.walk(table_tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "Table"
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.startswith("relationship_")
    }
    assert ast_relationship_tables == set(actual_table_columns)
    _assert_closed_vocabulary(actual_model_fields, EXPECTED_MODEL_FIELDS)
    _assert_closed_vocabulary(actual_table_columns, EXPECTED_TABLE_COLUMNS)


@pytest.mark.parametrize("surface", ["model", "table"])
def test_a_new_euphemistic_relationship_field_reddens_the_closed_vocabulary(
    surface: str,
) -> None:
    expected = EXPECTED_MODEL_FIELDS if surface == "model" else EXPECTED_TABLE_COLUMNS
    actual = dict(expected)
    target = next(iter(actual))
    actual[target] = actual[target] | {"affinity_index"}
    with pytest.raises(AssertionError, match="unexpected relationship fields"):
        _assert_closed_vocabulary(actual, expected)
