"""WP-RE-04 stop N9: every versioned identity-effect state carries `version`.

The merge/split Record Events (Phase 4B) take a versioned family's
`record_version` from its effect state (`after_state["version"]`, and a split
restore's `after_state["version"] + 1`, G1-EM-017). That is only sound if every
versioned `IdentityEffectFamily`'s state admits exactly a `version` key -- which
the two repositories enforce, because each refuses an effect whose state keys
differ from its family's admitted set. This module reads those admitted sets
from the source and pins them:

* every family whose table has a `version` column admits `version`;
* the families that admit none are exactly the ones without one: OBSERVATION
  (`resolution_version`, OD-2 (a)/(d)), PROPOSAL, MEMORY_PROPOSAL and
  MEMORY_CONTEXT_LINK (OD-2 (b));
* REVIEW_CASE and DERIVED_CONTEXT are written by neither repository.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from my_pa.domain.relationship.identity_correction import IdentityEffectFamily

ROOT: Final = Path(__file__).resolve().parents[2]
PERSISTENCE: Final = ROOT / "src" / "my_pa" / "infrastructure" / "persistence"
VERSIONED: Final = frozenset(
    {
        IdentityEffectFamily.ENTITY,
        IdentityEffectFamily.IDENTIFIER,
        IdentityEffectFamily.ALIAS,
        IdentityEffectFamily.ASSIGNMENT,
        IdentityEffectFamily.RELATIONSHIP,
        IdentityEffectFamily.NAME,
        IdentityEffectFamily.ORGANIZATION_PROFILE,
        IdentityEffectFamily.ADDRESS,
        IdentityEffectFamily.COMMUNICATION_METHOD,
        IdentityEffectFamily.PROJECT_PARTICIPATION,
        IdentityEffectFamily.PERSON_ORGANIZATION_AFFILIATION,
        IdentityEffectFamily.RELATIONSHIP_MEMORY,
    }
)
UNVERSIONED: Final = frozenset(
    {
        IdentityEffectFamily.OBSERVATION,
        IdentityEffectFamily.PROPOSAL,
        IdentityEffectFamily.MEMORY_PROPOSAL,
        IdentityEffectFamily.MEMORY_CONTEXT_LINK,
    }
)


def _admitted(path: Path, function: str) -> dict[IdentityEffectFamily, frozenset[str]]:
    """`{family: admitted state keys}` from the dict literal inside `function`.

    Each value is either a set literal or a tuple whose last element is one
    (the memory repository's `(table, id_column, keys)`).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    (node,) = (
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == function
    )
    found: dict[IdentityEffectFamily, frozenset[str]] = {}
    for dictionary in (item for item in ast.walk(node) if isinstance(item, ast.Dict)):
        for key, value in zip(dictionary.keys, dictionary.values, strict=True):
            if not (
                isinstance(key, ast.Attribute)
                and isinstance(key.value, ast.Name)
                and key.value.id == "IdentityEffectFamily"
            ):
                continue
            keys = value.elts[-1] if isinstance(value, ast.Tuple) else value
            assert isinstance(keys, ast.Set), (function, key.attr)
            found[IdentityEffectFamily[key.attr]] = frozenset(
                str(element.value) for element in keys.elts if isinstance(element, ast.Constant)
            )
    return found


def _all_admitted() -> dict[IdentityEffectFamily, frozenset[str]]:
    entity = _admitted(PERSISTENCE / "entity.py", "_identity_effect_values")
    memory = _admitted(
        PERSISTENCE / "relationship_memory.py", "_memory_identity_effect_write_subject"
    )
    assert not set(entity) & set(memory), "one family is admitted by two repositories"
    return {**entity, **memory}


def test_every_versioned_effect_family_admits_a_version_key() -> None:
    admitted = _all_admitted()
    missing = {family for family in VERSIONED if "version" not in admitted.get(family, frozenset())}
    assert not missing, f"STOP N9: versioned effect states without `version`: {sorted(missing)}"


def test_the_families_without_a_version_are_exactly_the_unversioned_ones() -> None:
    admitted = _all_admitted()
    assert {family for family, keys in admitted.items() if "version" not in keys} == UNVERSIONED
    assert set(admitted) == VERSIONED | UNVERSIONED
    assert set(IdentityEffectFamily) - set(admitted) == {
        IdentityEffectFamily.REVIEW_CASE,
        IdentityEffectFamily.DERIVED_CONTEXT,
    }
