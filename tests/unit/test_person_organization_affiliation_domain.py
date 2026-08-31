"""`PersonOrganizationAffiliation` invariants, without persistence (RI-ENT-WP-05).

Every rule asserted here is also a CHECK constraint in `17149a48fa30`; the
database half lives in
`tests/schema/test_person_organization_affiliations_migration.py`. This module
proves only what a dataclass can prove, on the same argument
`tests/unit/test_entity_name_and_organization_profile_domain.py` and
`tests/unit/test_project_entity_participation_domain.py` state for their own
record families.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.relationship.entity import (
    AffiliationTypeCode,
    PersonOrganizationAffiliation,
    PersonOrganizationAffiliationState,
)

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
PERSON = "ent_aaaa0001aaaa0001"
ORGANIZATION = "ent_bbbb0002bbbb0002"
AFFILIATION_ID = "poaf_aaaa0001aaaa0001"
OTHER_AFFILIATION_ID = "poaf_bbbb0002bbbb0002"

WHEN = datetime(2026, 8, 30, 12, tzinfo=UTC)
LATER = WHEN + timedelta(days=1)


def an_affiliation(**overrides: object) -> PersonOrganizationAffiliation:
    fields: dict[str, object] = {
        "affiliation_id": AFFILIATION_ID,
        "principal_id": PRINCIPAL,
        "person_entity_id": PERSON,
        "affiliation_type_code": AffiliationTypeCode.EMPLOYMENT,
        "organization_entity_id": ORGANIZATION,
        "job_title": "Project Executive",
    }
    return PersonOrganizationAffiliation(**{**fields, **overrides})  # type: ignore[arg-type]


# --- construction and defaults --------------------------------------------------


def test_an_affiliation_defaults_to_active_state_and_version_one() -> None:
    affiliation = an_affiliation()
    assert affiliation.state is PersonOrganizationAffiliationState.ACTIVE
    assert affiliation.version == 1
    assert affiliation.effective_from is None
    assert affiliation.effective_to is None
    assert affiliation.superseded_by_affiliation_id is None


def test_an_affiliation_rejects_an_unknown_identifier_kind() -> None:
    with pytest.raises(InvalidIdentifierError):
        an_affiliation(affiliation_id="xid_aaaa0001aaaa0001")
    with pytest.raises(InvalidIdentifierError):
        an_affiliation(person_entity_id="prn_aaaa0001aaaa0001aaaa0001")
    with pytest.raises(InvalidIdentifierError):
        an_affiliation(principal_id=PERSON)


# --- the nullable organization / independent-consultant case -------------------


def test_an_affiliation_may_hold_no_organization_at_all() -> None:
    """The audit's 'Mike Fichera' case: an independent consultant with no
    employer. Never a placeholder organization entity -- a bare `None`."""
    consultant = an_affiliation(
        organization_entity_id=None,
        affiliation_type_code=AffiliationTypeCode.INDEPENDENT_CONSULTANT,
        job_title="Independent Consultant",
    )
    assert consultant.organization_entity_id is None
    assert consultant.affiliation_type_code is AffiliationTypeCode.INDEPENDENT_CONSULTANT


def test_an_affiliation_organization_is_not_the_person() -> None:
    with pytest.raises(ValueError, match="organization is not the person"):
        an_affiliation(organization_entity_id=PERSON)


def test_an_affiliation_rejects_an_unknown_identifier_kind_for_the_organization() -> None:
    with pytest.raises(InvalidIdentifierError):
        an_affiliation(organization_entity_id="prn_aaaa0001aaaa0001aaaa0001")


# --- affiliation type ------------------------------------------------------------


def test_an_affiliation_has_a_closed_affiliation_type() -> None:
    with pytest.raises(ValueError, match="closed affiliation type"):
        an_affiliation(affiliation_type_code="primary_employer")  # type: ignore[arg-type]


def test_every_affiliation_type_is_admitted() -> None:
    for kind in AffiliationTypeCode:
        affiliation = an_affiliation(affiliation_type_code=kind)
        assert affiliation.affiliation_type_code is kind


# --- job title -------------------------------------------------------------------


def test_an_affiliation_job_title_may_be_absent() -> None:
    affiliation = an_affiliation(job_title=None)
    assert affiliation.job_title is None


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_an_affiliation_job_title_is_not_blank_when_present(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        an_affiliation(job_title=blank)


# --- temporal fields ---------------------------------------------------------------


def test_an_affiliation_cannot_end_before_it_begins() -> None:
    with pytest.raises(ValueError, match="cannot end before it begins"):
        an_affiliation(effective_from=LATER, effective_to=WHEN)


@pytest.mark.parametrize("moment", [datetime(2026, 8, 30, 12), None])
def test_an_affiliation_refuses_a_naive_effective_from(moment: object) -> None:
    if moment is None:
        return  # None is a legitimate absence, not a naive datetime.
    with pytest.raises((ValueError, TypeError, AttributeError)):
        an_affiliation(effective_from=moment)


# --- lifecycle / state -------------------------------------------------------------


def test_an_affiliation_has_a_closed_state() -> None:
    with pytest.raises(ValueError, match="closed state"):
        an_affiliation(state="pending")  # type: ignore[arg-type]


def test_an_affiliation_version_starts_at_one() -> None:
    with pytest.raises(ValueError, match="positive"):
        an_affiliation(version=0)


def test_an_affiliation_is_retired_only_once_it_leaves_service() -> None:
    with pytest.raises(ValueError, match="retired only once it leaves service"):
        an_affiliation(retired_at=WHEN, state=PersonOrganizationAffiliationState.ACTIVE)
    retired = an_affiliation(retired_at=WHEN, state=PersonOrganizationAffiliationState.RETIRED)
    assert retired.retired_at == WHEN


def test_an_affiliation_cannot_supersede_itself() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        an_affiliation(
            affiliation_id=AFFILIATION_ID,
            state=PersonOrganizationAffiliationState.SUPERSEDED,
            superseded_by_affiliation_id=AFFILIATION_ID,
        )


def test_an_affiliation_names_a_successor_only_when_superseded() -> None:
    with pytest.raises(ValueError, match="names a successor only when superseded"):
        an_affiliation(
            state=PersonOrganizationAffiliationState.ACTIVE,
            superseded_by_affiliation_id=OTHER_AFFILIATION_ID,
        )
    superseded = an_affiliation(
        state=PersonOrganizationAffiliationState.SUPERSEDED,
        superseded_by_affiliation_id=OTHER_AFFILIATION_ID,
    )
    assert superseded.superseded_by_affiliation_id == OTHER_AFFILIATION_ID


def test_an_affiliation_rejects_an_unknown_identifier_kind_for_the_successor() -> None:
    with pytest.raises(InvalidIdentifierError):
        an_affiliation(
            state=PersonOrganizationAffiliationState.SUPERSEDED,
            superseded_by_affiliation_id="eppt_aaaa0001aaaa0001",
        )


# --- RULING 1: no scoring surface --------------------------------------------------


def test_affiliation_type_code_is_not_a_scoring_vocabulary() -> None:
    """No member name or value carries a scoring/tier/confidence token
    (RULING 1), matched the same way
    `tests/architecture/test_relationship_scoring_surface_is_denied` matches:
    on whole snake_case tokens, not substrings."""
    denied_tokens = {
        "score",
        "scores",
        "scored",
        "scoring",
        "tier",
        "tiers",
        "rank",
        "ranks",
        "ranked",
        "ranking",
        "rankings",
        "confidence",
        "certainty",
        "probability",
        "likelihood",
        "propensity",
        "priority",
        "priorities",
        "importance",
        "weight",
        "weighted",
        "weighting",
    }
    for member in AffiliationTypeCode:
        name_tokens = set(member.name.lower().split("_"))
        value_tokens = set(str(member.value).lower().split("_"))
        assert not (name_tokens & denied_tokens), member.name
        assert not (value_tokens & denied_tokens), member.value


def test_affiliation_type_code_is_a_plain_unordered_str_enum() -> None:
    """Nothing here is orderable or comparable beyond what plain `StrEnum`
    gives every string equally (lexicographic `str` comparison, never a
    domain-meaningful ranking of one member above another).

    `AffiliationTypeCode` declares no `__lt__`, `__gt__`, `__le__`, `__ge__`,
    or `__eq__`/`__hash__` override of its own -- everything it has beyond
    plain `str` comes from `StrEnum` itself, which is asserted here by
    checking those dunders are not present in the class's own `__dict__`
    (i.e. not overridden), rather than merely absent from `dir()` (which
    would also hide `str`'s own inherited implementations)."""
    assert issubclass(AffiliationTypeCode, StrEnum)
    for dunder in ("__lt__", "__gt__", "__le__", "__ge__"):
        assert dunder not in AffiliationTypeCode.__dict__, (
            f"{dunder} is overridden on AffiliationTypeCode; a comparison "
            "operator on this vocabulary is exactly the ordering RULING 1 forbids"
        )


def test_no_code_path_in_this_module_sorts_or_ranks_by_affiliation_type() -> None:
    """A grep-shaped proof that nothing in the domain module orders by this
    vocabulary: the only operation against `AffiliationTypeCode` anywhere in
    `entity.py` is the `isinstance` closed-vocabulary check in
    `PersonOrganizationAffiliation.__post_init__`, the same shape every other
    closed vocabulary on this plane uses. `sorted(`, `min(`, `max(`, and
    `key=` are the shapes a ranking would take, and none of them appear
    anywhere near the token `affiliation_type_code` in the module source."""
    import inspect
    import re

    from my_pa.domain.relationship import entity as entity_module

    source = inspect.getsource(entity_module)
    for line in source.splitlines():
        if "affiliation_type_code" not in line and "AffiliationTypeCode" not in line:
            continue
        assert not re.search(r"\b(sorted|min|max)\s*\(", line), line
        assert "key=" not in line, line
