"""No composite relationship score can enter the durable relationship surface.

Operating brief §22 forbids a hidden relationship score, sentiment or
personality scoring, people ranking, and protected-trait inference. Today the
relationship surface contains none of them — but *absence today is not a
guarantee for tomorrow*, and the guard that already exists does not supply one.

`tests/relationship/test_relationship_domain.py` freezes the exact field
vocabulary of all twenty-three relationship tables and all twenty-five
relationship dataclasses as a **closed allow-list**. That makes any new field *visible*: a
column added without touching the constant reddens the build. It does not make a
scoring field *impossible*, because the constant and the schema are both source,
and one commit can widen both. `EXPECTED_TABLE_COLUMNS["relationship_people"] |
{"relationship_score"}` alongside the column itself is green under a closed
allow-list, and green is precisely the wrong answer.

This module supplies the missing half: a **semantic deny rule**, applied to four
surfaces, one of which is that allow-list itself.

* the live SQLAlchemy declaration for every `relationship_*` table and every
  table of the generalized entity plane (`entities`, `entity_*`);
* the live dataclass fields of `my_pa.domain.relationship`;
* the closed vocabularies those modules declare — a `StrEnum` member name *or*
  value is a channel too, and `RelationshipEventType.SENTIMENT_POSITIVE` would
  be a sentiment field wearing an event type's clothes;
* the declared allow-list constants, read out of the test module's source with
  `ast`. Widening the allow-list to admit `relationship_score` reddens *here*
  even though it makes the closed-vocabulary test green, so the two guards
  cannot be satisfied simultaneously by a scoring field.

## Matching is on snake_case tokens, not substrings

Every name is lowercased and split on non-alphanumeric characters, and each
token is `fullmatch`ed against the patterns below. Substring matching would be
unusable here: `trace` contains `race`, `identifier` and `frontier` contain
`tier`, `upgrade` contains `grade`, and `message`, `average` and `language` all
contain `age`. Token matching makes each of those a different token from the
denied one, which is asserted directly in
`test_the_rule_does_not_fire_on_names_the_surface_legitimately_uses`.

## What is deliberately *not* denied, and why

* **`disposition`** — a live column on `relationship_identity_review_decisions`
  holding `accept`/`defer`/`reject`. It is a human review outcome, which is the
  governance this package exists to require, not a personality disposition.
  Denying the stem would redden the surface it protects.
* **`priority`** is denied *here* but `pulse_items.attention_rank` (the domain
  field `PulseItem.attention_rank`) is untouched: that column is a bounded 1..10
  ordering of attention items on the Pulse plane, not a durable attribute of a
  person. This module scans the relationship surface only, so the two do not
  collide —
  and a `priority` on a *person* would be people ranking, which is why the stem
  is denied on this surface.
* **`index`**, **`fit`**, **`condition`**, **`spouse`**, **`urgency`** — each
  names a composite judgement in one reading and something ordinary in another
  (`index` an ordinal position, `condition` a state, `spouse` a
  source-observed relation). They are left out rather than denied loosely; the
  closed allow-list still makes any of them *visible* on arrival, which is the
  division of labour between the two guards.

Nothing here opens a connection or touches a database. It reads declarations.
"""

from __future__ import annotations

import ast
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from importlib import import_module
from pathlib import Path
from typing import Final

import pytest

from my_pa.infrastructure.persistence.tables import METADATA

ROOT: Final = Path(__file__).resolve().parents[2]
CLOSED_VOCABULARY_MODULE: Final = ROOT / "tests" / "relationship" / "test_relationship_domain.py"
ALLOW_LIST_CONSTANTS: Final = ("EXPECTED_MODEL_FIELDS", "EXPECTED_TABLE_COLUMNS")

#: The denied token patterns, each with the prohibition it enforces. Every
#: pattern is `fullmatch`ed against one lowercased snake_case token.
#:
#: The two halves are the two prohibitions: a **composite judgement** that
#: stands in for a person (a score under any name), and a **protected trait**
#: whose storage or inference is forbidden outright.
DENIED: Final[tuple[tuple[str, str], ...]] = (
    # --- composite judgement: a number or band that stands in for a person ---
    (r"scor(e|es|ed|ing)", "a score"),
    (r"rating|ratings|rated", "a rating"),
    (r"rank|ranks|ranked|ranking|rankings", "a ranking of people"),
    (r"percentile|percentiles|quantile|quantiles|decile|deciles", "a distributional rank"),
    (r"tier|tiers", "a graded band"),
    (r"grade|grades|graded|grading", "a grade"),
    (r"weight|weights|weighted|weighting", "a weighting"),
    (r"confidence|certainty|probability|likelihood|propensity", "a model likelihood"),
    (r"priority|priorities|importance", "a ranking of people by importance"),
    (r"quality", "a quality judgement"),
    (r"strength|strengths", "relationship strength"),
    (r"closeness|intimacy|warmth|rapport|chemistry", "a closeness score"),
    (r"engagement|responsiveness|reciprocity", "an engagement score"),
    (r"influence|influencer|clout", "an influence score"),
    (r"health|wellbeing|wellness", "a relationship health score"),
    (r"risk|riskiness", "a risk score"),
    (r"trust|trusted|trustworthiness|trustworthy", "a trust score"),
    (r"reputation|standing|esteem", "a reputation score"),
    (r"loyalty|loyal", "a loyalty score"),
    (r"compatibility|compatible", "a compatibility score"),
    (r"affinity|affinities", "an affinity score"),
    (r"sentiment|sentiments|tone|mood|emotion|emotions|emotional|valence", "sentiment scoring"),
    (r"personality|psychometric|temperament|persona|archetype", "personality scoring"),
    (r"segment|segments|cohort|cohorts|cluster|clusters", "segmenting people"),
    # --- protected traits: inference or storage forbidden outright -----------
    (r"race|races|racial|ethnicity|ethnicities|ethnic", "a protected trait (race/ethnicity)"),
    (r"religion|religions|religious|faith|creed", "a protected trait (religion)"),
    (r"gender|genders|sex|sexes|sexual|orientation", "a protected trait (gender/orientation)"),
    (r"age|ages|birth|birthdate|birthday|dob", "a protected trait (age)"),
    (r"disability|disabilities|disabled|impairment|handicap", "a protected trait (disability)"),
    (r"medical|diagnosis|diagnoses|pregnancy|pregnant", "a protected trait (health)"),
    (r"citizenship|nationality|immigration|visa|veteran", "a protected trait (national origin)"),
    (r"marital|marriage|married", "a protected trait (marital status)"),
    (r"political|politics|ideology", "a protected trait (political opinion)"),
    (r"income|salary|wealth|credit|creditworthiness", "financial profiling of a person"),
    (r"biometric|biometrics|fingerprint|faceprint|voiceprint", "biometric tracking"),
    (r"latitude|longitude|geolocation|coordinates|whereabouts|tracking", "location tracking"),
)

_COMPILED: Final = tuple((re.compile(pattern), reason) for pattern, reason in DENIED)


def tokens(name: str) -> tuple[str, ...]:
    """`name` split into lowercased tokens, on separators *and* case boundaries.

    Both conventions, because the surface holds both: table columns and
    dataclass fields are snake_case, `StrEnum` member names are UPPER_SNAKE, and
    a camelCase `relationshipScore` must not slip past a snake_case-only split.
    """
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return tuple(token for token in re.split(r"[^a-z0-9]+", separated.lower()) if token)


def denials(name: str) -> tuple[str, ...]:
    """Every prohibition `name` violates, as readable reasons."""
    found: list[str] = []
    for token in tokens(name):
        for pattern, reason in _COMPILED:
            if pattern.fullmatch(token) and reason not in found:
                found.append(reason)
    return tuple(found)


def _violations(surface: dict[str, tuple[str, ...]]) -> list[str]:
    """Every `owner.name` in `surface` that names a prohibited construct."""
    return sorted(
        f"{owner}.{name} names {'; '.join(reasons)}"
        for owner, names in surface.items()
        for name in names
        if (reasons := denials(name))
    )


#: The table-name prefixes that make a table part of the relationship surface.
#: `relationship_` is the WP-9 substrate. `entities`/`entity_` is the
#: generalized entity plane, and it is named here rather than left out because a
#: prefix list is the whole population this rule sees: a plane that stores
#: people, organizations, their assignments and their typed edges is the
#: relationship surface whatever its tables are called, and a deny rule that
#: reached only the older half would pass perfectly while the newer half carried
#: exactly the field it exists to refuse.
RELATIONSHIP_TABLE_PREFIXES: Final = ("relationship_", "entities", "entity_")


def relationship_table_columns() -> dict[str, tuple[str, ...]]:
    return {
        table.name: tuple(column.name for column in table.columns)
        for table in METADATA.tables.values()
        if table.name.startswith(RELATIONSHIP_TABLE_PREFIXES)
    }


def _relationship_modules() -> tuple[object, ...]:
    package = import_module("my_pa.domain.relationship")
    assert package.__file__ is not None
    return tuple(
        import_module(f"my_pa.domain.relationship.{path.stem}")
        for path in sorted(Path(package.__file__).parent.glob("*.py"))
        if path.stem != "__init__"
    )


def relationship_model_fields() -> dict[str, tuple[str, ...]]:
    return {
        f"{value.__module__}.{value.__name__}": tuple(field.name for field in fields(value))
        for module in _relationship_modules()
        for value in vars(module).values()
        if isinstance(value, type)
        and is_dataclass(value)
        and value.__module__.startswith("my_pa.domain.relationship")
    }


def relationship_vocabularies() -> dict[str, tuple[str, ...]]:
    """Every closed vocabulary the relationship domain declares, names and values.

    Both halves: a member *name* and its stored *value* are each a place a
    scoring vocabulary could be introduced without adding a single column.
    """
    return {
        f"{value.__module__}.{value.__name__}": tuple(
            term for member in value for term in (member.name, str(member.value))
        )
        for module in _relationship_modules()
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, Enum)
        and value.__module__.startswith("my_pa.domain.relationship")
    }


def declared_allow_list() -> dict[str, tuple[str, ...]]:
    """The frozen field vocabularies, read out of the closed-vocabulary module.

    Read with `ast` rather than imported: this asserts a property of the source
    a reviewer reads, and it keeps the guard from depending on one test module
    being importable from another.
    """
    tree = ast.parse(CLOSED_VOCABULARY_MODULE.read_text(encoding="utf-8"))
    declared: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        for constant in names & set(ALLOW_LIST_CONSTANTS):
            declared[constant] = tuple(
                literal.value
                for literal in ast.walk(node.value)
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str)
            )
    return declared


# --- the scan reaches what it claims to scan --------------------------------


def test_the_scan_reaches_the_whole_relationship_surface() -> None:
    """Guards every assertion below against a scan that quietly found nothing.

    A deny rule over an empty surface passes perfectly, which is the failure
    mode this file would otherwise have.
    """
    columns = relationship_table_columns()
    models = relationship_model_fields()
    vocabularies = relationship_vocabularies()
    declared = declared_allow_list()

    assert len(columns) == 23, f"{len(columns)} relationship tables reached, not twenty-three"
    assert len(models) == 25, f"{len(models)} relationship models reached, not twenty-five"
    assert vocabularies, "no closed relationship vocabulary was reached"
    assert set(declared) == set(ALLOW_LIST_CONSTANTS), (
        f"{sorted(declared)} allow-list constants were read from "
        f"{CLOSED_VOCABULARY_MODULE.name}, not {list(ALLOW_LIST_CONSTANTS)}. The "
        "closed-vocabulary guard has been renamed or removed, and this deny rule "
        "is no longer reading it"
    )
    for constant, names in declared.items():
        assert len(names) > 40, f"{constant} yielded {len(names)} names; the ast read is broken"


# --- the deny rule, on each surface -----------------------------------------


def test_no_relationship_column_names_a_score_or_a_protected_trait() -> None:
    """The durable schema surface. A stored score is the one that outlives review."""
    violations = _violations(relationship_table_columns())
    assert violations == [], (
        f"{violations}. Operating brief §22 forbids a hidden relationship score, "
        "sentiment or personality scoring, people ranking, and protected-trait "
        "inference. A column is the durable form of exactly that. This is a "
        "BLOCKER, not a field to rename"
    )


def test_no_relationship_model_field_names_a_score_or_a_protected_trait() -> None:
    """The domain surface, where such a field would be computed before it is stored."""
    violations = _violations(relationship_model_fields())
    assert violations == [], (
        f"{violations}. Model output proposes; it never promotes state, and it "
        "never carries a composite judgement about a person"
    )


def test_no_closed_relationship_vocabulary_admits_a_score_or_a_protected_trait() -> None:
    """An enum member is a field that needed no migration."""
    violations = _violations(relationship_vocabularies())
    assert violations == [], (
        f"{violations}. A closed vocabulary is still a durable surface: a "
        "sentiment or trait term admitted here is stored in an existing column"
    )


def test_the_declared_allow_list_cannot_be_widened_to_admit_a_score() -> None:
    """The laundering path the closed allow-list leaves open, closed.

    The allow-list is source. Adding a scoring column *and* the matching entry
    keeps `test_relationship_models_and_tables_have_a_closed_field_vocabulary`
    green — so the deny rule is applied to the allow-list itself, and the two
    guards cannot both be satisfied by a scoring field.
    """
    violations = _violations(declared_allow_list())
    assert violations == [], (
        f"{violations}. A prohibited field was added to the frozen relationship "
        "vocabulary. Widening the allow-list is what makes the closed-vocabulary "
        "guard go green; it does not make the field permissible"
    )


# --- the rule is non-vacuous, permanently -----------------------------------


@pytest.mark.parametrize(
    "planted",
    [
        "relationship_score",
        "relationshipScore",
        "health_score",
        "trust_level",
        "reputation_points",
        "loyalty_band",
        "compatibility_pct",
        "affinity_index",
        "closeness",
        "rapport_level",
        "engagement_rate",
        "influence_weight",
        "sentiment",
        "sentiment_label",
        "overall_tone",
        "emotional_valence",
        "personality_type",
        "archetype",
        "temperament_summary",
        "contact_rank",
        "importance_tier",
        "relationship_grade",
        "priority_score",
        "percentile_of_contacts",
        "match_probability",
        "model_confidence",
        "vip_segment",
        "cohort_label",
        "inferred_ethnicity",
        "race",
        "religion_guess",
        "faith",
        "gender_inferred",
        "sexual_orientation",
        "age_band",
        "date_of_birth",
        "disability_status",
        "medical_notes",
        "pregnancy_status",
        "nationality",
        "veteran_status",
        "marital_status",
        "political_leaning",
        "estimated_income",
        "credit_band",
        "biometric_hash",
        "last_known_coordinates",
        "location_tracking_enabled",
    ],
)
def test_the_rule_fires_on_every_prohibited_construct(planted: str) -> None:
    """The controlled violation, permanent and parametrized.

    A deny rule is worth exactly what it catches. Each name below is a form the
    prohibition has actually taken in the wild, and each must be detected — so
    a future edit that narrows a pattern into uselessness reddens here rather
    than passing quietly.
    """
    assert denials(planted), f"{planted} passed the deny rule; the rule does not cover it"


def test_a_planted_column_would_redden_the_column_guard() -> None:
    """The reversion, executed rather than described.

    The live surface is clean, so `test_no_relationship_column_names_...` is
    green for a reason that is indistinguishable from a broken scan. This runs
    the same detector over the same surface *plus* one planted column and
    requires the failure, which is what makes the green above meaningful.
    """
    surface = relationship_table_columns()
    surface["relationship_people"] = (*surface["relationship_people"], "relationship_score")
    violations = _violations(surface)
    assert violations == ["relationship_people.relationship_score names a score"], violations


# --- and it does not fire on the surface as it legitimately stands -----------


@pytest.mark.parametrize(
    "legitimate",
    [
        # Live relationship names whose stems sit next to a denied one.
        "disposition",
        "sequence",
        "resolution_sequence",
        "role",
        "value",
        "display_name",
        "source_version",
        "candidate_kind",
        "requested_action",
        "superseded_by_person_id",
        "state_resolution_id",
        "observed_at",
        "authority",
        "accepted",
        "context",
        "source_ref",
        # Substring near-misses. Each contains a denied stem and must survive,
        # which is the property token matching buys over substring matching.
        "trace_id",  # contains "race"
        "identifier",  # contains "tier"
        "frontier_note",  # contains "tier"
        "upgrade_path",  # contains "grade"
        "message",  # contains "age"
        "average_gap",  # contains "age"
        "language",  # contains "age"
        "page_token",  # contains "age"
        "storage_key",  # contains "age"
        "sexagenary_cycle",  # begins "sex" without being it
        "confidential_flag",  # begins "confide" without being "confidence"
        "brisk_note",  # contains "risk"
        "AFFILIATION_CHANGE",  # an UPPER_SNAKE vocabulary member
        "sourceObjectId",  # a camelCase name, split but not denied
    ],
)
def test_the_rule_does_not_fire_on_names_the_surface_legitimately_uses(legitimate: str) -> None:
    """No substring false positives, asserted rather than assumed.

    A deny rule that reddens on `trace_id` gets weakened by the first person it
    inconveniences, and a weakened rule protects nothing. These are the exact
    collisions the token split exists to avoid.
    """
    assert denials(legitimate) == (), (
        f"{legitimate} was denied. The rule is matching substrings rather than "
        "snake_case tokens, and a false positive here is how a deny rule gets "
        "loosened into uselessness"
    )


def test_every_live_name_on_the_relationship_surface_passes_the_rule() -> None:
    """The whole live surface as one assertion, so the rule is calibrated to it."""
    surface = {
        **relationship_table_columns(),
        **relationship_model_fields(),
        **relationship_vocabularies(),
    }
    assert _violations(surface) == []
    # And the surface is not empty, so the line above measured something.
    assert sum(len(names) for names in surface.values()) > 150
