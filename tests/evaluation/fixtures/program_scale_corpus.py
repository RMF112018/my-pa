"""A generated, program-scale synthetic entity corpus (`RI-AC-031`, WP-RI-12).

**Why a second corpus.** `resolution_corpus.py` is twenty-odd hand-labelled
entities chosen to make a wrong join likely, and its own frozen report says
plainly that it is small and is not a population estimate. That is the right
shape for proving a refusal holds and the wrong shape for proving anything about
scale: a resolver that reads every alias in the database answers a
twenty-entity corpus instantly, and a candidate cap that never binds at twenty
entities is a cap nothing has measured. The controlling plan (WP-RI-12) asks for
a fixture at program scale — 500 persons, 100 organizations, several
programs/projects/work packages, five thousand-plus combined
aliases/identifiers/assignments/relationships/observations, at least fifty
deliberate collision groups and at least fifty historical assignment changes —
and this module is that fixture. The hand-labelled corpus is untouched; the two
answer different questions and both are kept.

**Generated, and deterministic without a random number generator.** Every
selection here is index arithmetic over `SEED` and fixed pools, so the corpus is
byte-identical on every machine and every run, and a reader can follow *why* a
particular person collides with a particular other one rather than being told a
seed and asked to trust it. `random.Random(seed)` would have been reproducible
too, but only in the sense that a hash is: nobody could read the collision
structure off the source.

**Nothing here is real, and that is structural rather than promised.** Family
names are composed from a twelve-by-eight table of invented syllables
(`Brandmoor`, `Calderwick`), so no surname pool was copied from anywhere. Given
names are an invented list. Every mail domain is under `.test`, which RFC 2606
reserves precisely so a fixture cannot reach a real host. Every external
identifier is synthetic (`AGENTS.md` section 5). Any resemblance between a
generated pair and a living person is arithmetic.

**The name space is partitioned by index band, and the partition is what makes
the labels sound.** `_name_at(index)` maps an integer to a `(given, family)`
pair, and two indices below `len(GIVEN_NAMES) * len(FAMILY_NAMES)` collide only
when they are equal. So a case that must answer `NOT_FOUND` can be built from a
band no entity was drawn from and *be* absent, rather than being absent because
nobody checked:

* `0..59`      the deliberate same-name collision groups
* `100..469`   the uniquely named persons
* `700..739`   the merged-away duplicates
* `1200..1224` the second Principal's people, invisible to the first
* `2000..2039` names deliberately given to nobody

**Two Principals**, for the reason the hand-labelled corpus has two: a corpus
with one cannot detect the leak that matters most. The second Principal holds
people of its own *and* ten mailboxes spelled exactly like the first
Principal's, so the partition is tested where a `WHERE principal_id = ...` that
was forgotten would actually show.

This module writes nothing and opens no connection. It is data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from my_pa.domain.relationship.entity import (
    AliasType,
    Assignment,
    AssignmentType,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.governance import EntityObservation, ObservationKind
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name

__all__ = [
    "ACTIVE_PERSONS",
    "BUILT_AT",
    "COLLISION_GROUPS",
    "EARLY",
    "LATE",
    "MIDPOINT",
    "ORGANIZATIONS",
    "ORIGIN",
    "PRINCIPAL_A",
    "PRINCIPAL_B",
    "PROGRAM_SCALE_CORPUS",
    "SEED",
    "CollisionGroup",
    "ConflictedAddress",
    "MergedRedirect",
    "PersonRecord",
    "ProgramScaleCorpus",
    "RecycledMailbox",
    "absent_name",
]

#: The one number the whole corpus is derived from. It is a date rather than a
#: lucky integer so that "why this seed" has an answer, and changing it is a
#: visible change to every measurement taken over the corpus.
SEED: Final = 20260819

PRINCIPAL_A: Final = "prn_pscaleaaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_pscalebbbb0002bbbb0002"

#: The moment the corpus describes. Fixed rather than `utc_now()`, for the
#: reason the hand-labelled corpus fixes its own: a fixture whose answers depend
#: on the day it runs is a fixture that fails on a Tuesday.
BUILT_AT: Final = datetime(2026, 8, 19, 12, tzinfo=UTC)
#: Before everything. Every open-ended record begins here.
ORIGIN: Final = datetime(2022, 1, 1, tzinfo=UTC)
#: Inside the first holder's tenure of a recycled mailbox.
EARLY: Final = datetime(2023, 6, 1, tzinfo=UTC)
#: The changeover. Prior employments end here and successors begin here.
MIDPOINT: Final = datetime(2024, 6, 1, tzinfo=UTC)
#: Inside the second holder's tenure of a recycled mailbox.
LATE: Final = datetime(2025, 6, 1, tzinfo=UTC)

# --- population sizes, stated once ------------------------------------------
#
# Named constants rather than literals scattered through the builder, because
# `tests/evaluation/test_program_scale_acceptance.py` asserts the controlling
# minimums against the *built* corpus and a reader has to be able to check the
# intent against the requirement without reading the loops.

ACTIVE_PERSONS: Final = 500
MERGED_PERSONS: Final = 40
ORGANIZATIONS: Final = 100
PROGRAMS: Final = 6
PROJECTS: Final = 24
WORK_PACKAGES: Final = 48
OTHER_PRINCIPAL_PERSONS: Final = 25
OTHER_PRINCIPAL_ORGANIZATIONS: Final = 5

#: Groups of people who share one canonical name exactly. Forty pairs whose
#: members sit on *different* projects (so a scope can separate them), ten pairs
#: on the same project and ten triples on the same project (so a scope that fits
#: everyone can be shown to separate nobody).
DISCRIMINATING_PAIRS: Final = 40
UNDISCRIMINATING_PAIRS: Final = 10
UNDISCRIMINATING_TRIPLES: Final = 10
COLLISION_GROUP_COUNT: Final = (
    DISCRIMINATING_PAIRS + UNDISCRIMINATING_PAIRS + UNDISCRIMINATING_TRIPLES
)
COLLIDING_PERSONS: Final = (
    DISCRIMINATING_PAIRS * 2 + UNDISCRIMINATING_PAIRS * 2 + UNDISCRIMINATING_TRIPLES * 3
)

#: A person changed employer: the prior assignment is closed and a new one
#: opens. The plan asks for fifty of these; eighty are built, so losing a few to
#: a later edit does not silently drop the fixture under its own minimum.
HISTORICAL_EMPLOYMENT_CHANGES: Final = 80

RECYCLED_MAILBOXES_COUNT: Final = 30
CONFLICTED_ADDRESS_COUNT: Final = 25
#: The last few conflicted addresses are claimed by an organization as well as
#: two people. A shared mailbox spanning two entity *types* is the shape that
#: caught a real defect in the hand-labelled corpus — filtering by type before
#: counting claimants let each filtered view see one claimant and resolve.
CROSS_TYPE_CONFLICTS: Final = 5

SHARED_NICKNAME_GROUPS: Final = 40
SHARED_NICKNAME_MEMBERS: Final = 3
FIRST_NAME_GROUPS: Final = 40
FIRST_NAME_MEMBERS: Final = 3
FORMER_NAME_ALIASES: Final = 30
UNVERIFIED_IDENTIFIERS: Final = 40
VENDOR_IDENTIFIERS: Final = 120
STALE_ASSIGNMENT_CANDIDATES: Final = 40
STALE_RELATIONSHIP_CANDIDATES: Final = 20
UNRESOLVED_MENTIONS: Final = 200
#: Uniquely named people whose canonical name matches exactly one entity. A bare
#: name is still not evidence that a reference means them, so these must answer
#: `AMBIGUOUS` — uniqueness is a fact about the database, not about the person.
LONE_NAME_CANDIDATES: Final = 40

# --- name pools --------------------------------------------------------------

#: Invented given names. Long and uncommon on purpose: a pool of the hundred
#: most frequent given names in any real country would make an accidental match
#: against a real person likelier, not less likely.
GIVEN_NAMES: Final[tuple[str, ...]] = (
    "Adaeze",
    "Bartholomew",
    "Caterina",
    "Dashiell",
    "Eulalia",
    "Ferdinand",
    "Genoveva",
    "Hieronymus",
    "Isolde",
    "Jacinta",
    "Kwabena",
    "Ludmila",
    "Marisol",
    "Nikolina",
    "Orsolya",
    "Pascaline",
    "Quirino",
    "Rosalind",
    "Severin",
    "Thandiwe",
    "Ulrike",
    "Valentina",
    "Wilhelmina",
    "Xiomara",
    "Yevgenia",
    "Zoltan",
    "Anselm",
    "Brigitta",
    "Casimir",
    "Dorothea",
    "Eamon",
    "Fionnuala",
    "Gustav",
    "Hyacinth",
    "Ignatius",
    "Jolanta",
    "Katarzyna",
    "Leocadia",
    "Magnus",
    "Nadezhda",
    "Oswin",
    "Perpetua",
    "Quintina",
    "Radomir",
    "Solveig",
    "Tancredi",
    "Ursula",
    "Vasilisa",
    "Wendelin",
    "Ximena",
    "Yolanda",
    "Zbigniew",
    "Amadeus",
    "Bronwen",
    "Clemencia",
    "Desmond",
    "Eudora",
    "Florentina",
    "Gwendolyn",
    "Hallvard",
    "Ilinca",
    "Jeronimo",
    "Kristiane",
    "Lysander",
)

#: Family names are *composed*, not listed, so no surname pool was copied from
#: anywhere and disjointness from the given-name pool is a property of the
#: syllables rather than a claim about a list somebody proofread.
_FAMILY_STEMS: Final = (
    "Brand",
    "Calder",
    "Dun",
    "Ellin",
    "Fair",
    "Gow",
    "Hal",
    "Kest",
    "Mar",
    "Norr",
    "Pell",
    "Ver",
)
_FAMILY_ENDINGS: Final = (
    "moor",
    "wick",
    "ridge",
    "holt",
    "stead",
    "combe",
    "field",
    "ton",
)
FAMILY_NAMES: Final[tuple[str, ...]] = tuple(
    f"{stem}{ending}" for ending in _FAMILY_ENDINGS for stem in _FAMILY_STEMS
)

#: A disjoint ending set, so a former name can never collide with a canonical
#: one. The join a former name licenses is one the resolver is *supposed* to
#: make, and a pool that overlapped would turn a measured success into an
#: accident.
_FORMER_ENDINGS: Final = ("brook", "dale", "glen", "haven", "mere", "shaw", "thorpe", "vale")
FORMER_FAMILY_NAMES: Final[tuple[str, ...]] = tuple(
    f"{stem}{ending}" for ending in _FORMER_ENDINGS for stem in _FAMILY_STEMS[:4]
)

#: Diminutives, composed from syllables that appear in no other pool. A nickname
#: that accidentally equalled a given name would make an ambiguity case pass for
#: the wrong reason.
_NICKNAME_STEMS: Final = ("Bix", "Dob", "Fen", "Grix", "Hob", "Jax", "Kip", "Lom", "Mub", "Nax")
_NICKNAME_ENDINGS: Final = ("by", "zo", "ra", "ly")
NICKNAMES: Final[tuple[str, ...]] = tuple(
    f"{stem}{ending}" for ending in _NICKNAME_ENDINGS for stem in _NICKNAME_STEMS
)

_ORGANIZATION_STEMS: Final = (
    "Halloway",
    "Ironvale",
    "Junction",
    "Keelson",
    "Larkmead",
    "Meridian",
    "Nordhaven",
    "Oakbend",
    "Pinnacle",
    "Quarrystone",
)
_ORGANIZATION_TRADES: Final = (
    "Constructors",
    "Engineering",
    "Fabrication",
    "Geotechnics",
    "Interiors",
    "Joinery",
    "Mechanical",
    "Roofing",
    "Surveying",
    "Waterproofing",
)
ORGANIZATION_NAMES: Final[tuple[str, ...]] = tuple(
    f"{stem} {trade}" for trade in _ORGANIZATION_TRADES for stem in _ORGANIZATION_STEMS
)

_PROGRAM_TOKENS: Final = (
    "Northgate",
    "Southgate",
    "Eastgate",
    "Westgate",
    "Highgate",
    "Lowgate",
)
_PROJECT_STEMS: Final = ("Alder", "Basalt", "Cinder", "Dolomite", "Ember", "Flint")
_PROJECT_ENDINGS: Final = ("Quay", "Terrace", "Viaduct", "Yard")
PROJECT_TOKENS: Final[tuple[str, ...]] = tuple(
    f"{stem} {ending}" for ending in _PROJECT_ENDINGS for stem in _PROJECT_STEMS
)

_ROLES: Final = (
    "structural engineer",
    "commissioning manager",
    "site superintendent",
    "quantity surveyor",
    "mechanical coordinator",
    "document controller",
    "safety lead",
    "procurement manager",
)
_DISCIPLINES: Final = (
    "structural",
    "mechanical",
    "electrical",
    "civil",
    "architectural",
    "commercial",
)

#: How many distinct `(given, family)` pairs `_name_at` can issue before it
#: wraps. Every index band this module uses is below it, which is what makes
#: "different band, therefore different name" true rather than hoped.
NAME_SPACE: Final = len(GIVEN_NAMES) * len(FAMILY_NAMES)

_COLLISION_NAME_BASE: Final = 0
_UNIQUE_NAME_BASE: Final = 100
_MERGED_NAME_BASE: Final = 700
_OTHER_PRINCIPAL_NAME_BASE: Final = 1200
_ABSENT_NAME_BASE: Final = 2000


def _name_at(index: int) -> tuple[str, str]:
    """The `(given, family)` pair at `index`, injectively below `NAME_SPACE`.

    The given name cycles fastest so that consecutive indices share a family
    name rather than a given one: people who share a surname and an employer are
    the pair a resolver most often wrongly joins, and consecutive indices are
    exactly what the builder hands to siblings.
    """
    if not 0 <= index < NAME_SPACE:
        raise ValueError("a name index is inside the injective range of the pools")
    return GIVEN_NAMES[index % len(GIVEN_NAMES)], FAMILY_NAMES[index // len(GIVEN_NAMES)]


def _display_name(index: int) -> str:
    given, family = _name_at(index)
    return f"{given} {family}"


def absent_name(offset: int) -> str:
    """A display name drawn from the band no entity was built from.

    The `NOT_FOUND` cases resolve this rather than a hand-typed string, so
    "nothing in the corpus is called this" is a consequence of the partition
    above rather than something a reader has to verify by grepping.
    """
    if not 0 <= offset < 1000:
        raise ValueError("an absent-name offset stays inside the reserved band")
    return _display_name(_ABSENT_NAME_BASE + offset)


def _organization_domain(index: int) -> str:
    """The mail domain of one organization, always under RFC 2606's `.test`."""
    return f"{ORGANIZATION_NAMES[index].replace(' ', '').lower()}.test"


# --- identifier minting ------------------------------------------------------
#
# Every identifier is `<prefix>_ps<kind><ordinal>`, which satisfies the
# `[A-Za-z0-9]{8,64}` suffix rule the domain and the migration's CHECK
# constraints both enforce, and carries no fact about the person it names
# (`INV-PKL-005`).


def _person_id(index: int) -> str:
    return f"ent_pspr{index:05d}"


def _merged_person_id(index: int) -> str:
    return f"ent_psmg{index:05d}"


def _organization_id(index: int) -> str:
    return f"ent_psog{index:05d}"


def _program_id(index: int) -> str:
    return f"ent_pspg{index:05d}"


def _project_id(index: int) -> str:
    return f"ent_pspj{index:05d}"


def _work_package_id(index: int) -> str:
    return f"ent_pswp{index:05d}"


def _other_person_id(index: int) -> str:
    return f"ent_psbp{index:05d}"


def _other_organization_id(index: int) -> str:
    return f"ent_psbo{index:05d}"


# --- the shapes the case builder reads --------------------------------------


@dataclass(frozen=True, slots=True)
class PersonRecord:
    """One generated person, and the handful of facts a case needs about them."""

    entity_id: str
    index: int
    display_name: str
    given_name: str
    family_name: str
    primary_address: str
    organization_id: str


@dataclass(frozen=True, slots=True)
class CollisionGroup:
    """People who share one canonical name exactly, and what separates them.

    `discriminating_project_id` is the project exactly *one* member is assigned
    to, and is `None` for the groups whose members all sit on the same project.
    The distinction is the difference between a scope that resolves and a scope
    that must be reported as having distinguished nobody, and it is recorded
    here rather than recomputed in the case builder so that the two cannot drift.
    """

    display_name: str
    member_ids: tuple[str, ...]
    discriminating_project_id: str | None
    discriminating_member_id: str | None
    discriminating_organization_id: str | None
    shared_project_id: str | None


@dataclass(frozen=True, slots=True)
class RecycledMailbox:
    """One address held by one person and then reissued to another.

    Both records are true; only one is true at any given moment. Without a
    moment the address is a stop, and with one it is a resolution — which is the
    single clearest statement this corpus makes about temporal truth.
    """

    address: str
    first_holder_id: str
    second_holder_id: str


@dataclass(frozen=True, slots=True)
class ConflictedAddress:
    """One address recorded against several entities with no effective dating.

    A data defect rather than a person. Choosing any claimant would perform the
    merge specification section 15.2 refuses.
    """

    address: str
    claimant_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MergedRedirect:
    """A duplicate folded into a survivor, still reachable as history."""

    merged_entity_id: str
    survivor_entity_id: str
    #: The canonical name on the merged-away row itself. Asking for it by name
    #: is a *weaker* question than asking for the alias, and the two must answer
    #: differently: a bare name never resolves, however unique, so this one is
    #: `AMBIGUOUS` while the alias below is a `HISTORICAL_MATCH`.
    display_name: str
    alias_display_value: str


@dataclass(frozen=True, slots=True)
class ProgramScaleCorpus:
    """The whole generated fixture, and the indexes the case builder reads.

    Frozen and built once at import. The record collections are what a
    repository is loaded from; everything below them is structure a labelled
    case needs in order to state its expectation without re-deriving the
    generator's arithmetic.
    """

    entities: tuple[Entity, ...]
    aliases: tuple[EntityAlias, ...]
    identifiers: tuple[ExternalIdentifier, ...]
    assignments: tuple[Assignment, ...]
    relationships: tuple[EntityRelationship, ...]
    observations: tuple[EntityObservation, ...]

    persons: tuple[PersonRecord, ...]
    organization_ids: tuple[str, ...]
    program_ids: tuple[str, ...]
    project_ids: tuple[str, ...]
    work_package_ids: tuple[str, ...]

    collision_groups: tuple[CollisionGroup, ...]
    recycled_mailboxes: tuple[RecycledMailbox, ...]
    conflicted_addresses: tuple[ConflictedAddress, ...]
    merged_redirects: tuple[MergedRedirect, ...]

    document_reference_aliases: tuple[tuple[str, str], ...]
    former_name_aliases: tuple[tuple[str, str], ...]
    shared_nickname_groups: tuple[tuple[str, tuple[str, ...]], ...]
    first_name_groups: tuple[tuple[str, tuple[str, ...]], ...]
    lone_name_person_ids: tuple[str, ...]
    stale_assignment_scopes: tuple[tuple[str, str], ...]
    stale_relationship_scopes: tuple[tuple[str, str], ...]
    unverified_addresses: tuple[tuple[str, str], ...]
    vendor_identifiers: tuple[tuple[str, str], ...]
    organization_addresses: tuple[tuple[str, str], ...]
    historical_employment_person_ids: tuple[str, ...]

    other_principal_person_ids: tuple[str, ...]
    other_principal_names: tuple[str, ...]
    other_principal_addresses: tuple[str, ...]
    shared_addresses: tuple[tuple[str, str, str], ...]

    @property
    def composition(self) -> dict[str, int]:
        """The counts `RI-AC-031` is asserted against, computed from the records.

        Computed rather than declared: a constant that says five hundred and a
        loop that built four hundred and ninety would agree with each other and
        with nothing else, and the whole value of a minimum is that it is
        checked against what was actually built.
        """
        by_type: dict[str, int] = {}
        for entity in self.entities:
            if entity.principal_id != PRINCIPAL_A:
                continue
            key = entity.entity_type.value
            by_type[key] = by_type.get(key, 0) + 1
        combined = (
            len(self.aliases)
            + len(self.identifiers)
            + len(self.assignments)
            + len(self.relationships)
            + len(self.observations)
        )
        return {
            "entities": len(self.entities),
            "persons": by_type.get(EntityType.PERSON.value, 0),
            "active_persons": sum(
                1
                for entity in self.entities
                if entity.principal_id == PRINCIPAL_A
                and entity.entity_type is EntityType.PERSON
                and entity.status is EntityStatus.ACTIVE
            ),
            "organizations": by_type.get(EntityType.ORGANIZATION.value, 0),
            "programs": by_type.get(EntityType.PROGRAM.value, 0),
            "projects": by_type.get(EntityType.PROJECT.value, 0),
            "work_packages": by_type.get(EntityType.WORK_PACKAGE.value, 0),
            "aliases": len(self.aliases),
            "identifiers": len(self.identifiers),
            "assignments": len(self.assignments),
            "relationships": len(self.relationships),
            "observations": len(self.observations),
            "combined_records": combined,
            "collision_groups": len(self.collision_groups),
            "historical_assignment_changes": len(self.historical_employment_person_ids),
            "merge_redirects": len(self.merged_redirects),
            "conflicted_identifiers": len(self.conflicted_addresses),
            "recycled_mailboxes": len(self.recycled_mailboxes),
            "ambiguous_nickname_groups": len(self.shared_nickname_groups),
            "ambiguous_first_name_groups": len(self.first_name_groups),
            "stale_role_candidates": (
                len(self.stale_assignment_scopes) + len(self.stale_relationship_scopes)
            ),
            "second_principal_entities": sum(
                1 for entity in self.entities if entity.principal_id == PRINCIPAL_B
            ),
        }


# --- record constructors -----------------------------------------------------


def _entity(
    entity_id: str,
    display_name: str,
    *,
    entity_type: EntityType,
    principal_id: str = PRINCIPAL_A,
    status: EntityStatus = EntityStatus.ACTIVE,
    superseded_by: str | None = None,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=status,
        created_at=ORIGIN,
        updated_at=BUILT_AT,
        version=1,
        superseded_by_entity_id=superseded_by,
    )


class _Mint:
    """Sequential opaque identifiers, one counter per record kind.

    A counter rather than a hash of the record's own fields: an identifier
    derived from the values it names would encode them, which `INV-PKL-005`
    forbids, and would silently change every downstream identifier when a
    display name was edited.
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        ordinal = self._counters.get(prefix, 0)
        self._counters[prefix] = ordinal + 1
        return f"{prefix}_ps{ordinal:07d}"


def _build() -> ProgramScaleCorpus:
    """Construct the whole fixture. Called once, at import.

    One long linear function on purpose. Splitting it into a dozen helpers would
    hide the thing a reader most needs to check — that the index bands do not
    overlap — behind a dozen signatures, and the bands are the reason every
    label further downstream is sound.
    """
    mint = _Mint()
    entities: list[Entity] = []
    aliases: list[EntityAlias] = []
    identifiers: list[ExternalIdentifier] = []
    assignments: list[Assignment] = []
    relationships: list[EntityRelationship] = []
    observations: list[EntityObservation] = []

    # --- scope entities, created first so every assignment has a target -----

    program_ids = tuple(_program_id(index) for index in range(PROGRAMS))
    for index, program in enumerate(program_ids):
        entities.append(
            _entity(
                program,
                f"Programme {_PROGRAM_TOKENS[index]}",
                entity_type=EntityType.PROGRAM,
            )
        )

    project_ids = tuple(_project_id(index) for index in range(PROJECTS))
    for index, project in enumerate(project_ids):
        entities.append(
            _entity(
                project,
                f"Project {PROJECT_TOKENS[index]}",
                entity_type=EntityType.PROJECT,
            )
        )

    work_package_ids = tuple(_work_package_id(index) for index in range(WORK_PACKAGES))
    for index, work_package in enumerate(work_package_ids):
        entities.append(
            _entity(
                work_package,
                f"Work Package {index:02d}",
                entity_type=EntityType.WORK_PACKAGE,
            )
        )

    organization_ids = tuple(_organization_id(index) for index in range(ORGANIZATIONS))
    organization_addresses: list[tuple[str, str]] = []
    for index, organization in enumerate(organization_ids):
        entities.append(
            _entity(
                organization,
                ORGANIZATION_NAMES[index],
                entity_type=EntityType.ORGANIZATION,
            )
        )
        address = f"contact@{_organization_domain(index)}"
        organization_addresses.append((organization, address))
        identifiers.append(
            ExternalIdentifier(
                identifier_id=mint.next("xid"),
                entity_id=organization,
                namespace=ExternalIdentifierNamespace.EMAIL,
                normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, address),
                display_value=address,
                principal_id=PRINCIPAL_A,
                verified=True,
            )
        )

    # Scope lineage: a project belongs to a programme and a work package to a
    # project. Present so the bounded traversal benchmark has more than one hop
    # to make, and so a card assembled for a project carries something.
    for index, project in enumerate(project_ids):
        relationships.append(
            EntityRelationship(
                relationship_id=mint.next("erel"),
                from_entity_id=project,
                relationship_type=EntityRelationshipType.MEMBER_OF,
                to_entity_id=program_ids[index % PROGRAMS],
                principal_id=PRINCIPAL_A,
                effective_from=ORIGIN,
            )
        )
    for index, work_package in enumerate(work_package_ids):
        relationships.append(
            EntityRelationship(
                relationship_id=mint.next("erel"),
                from_entity_id=work_package,
                relationship_type=EntityRelationshipType.MEMBER_OF,
                to_entity_id=project_ids[index % PROJECTS],
                principal_id=PRINCIPAL_A,
                effective_from=ORIGIN,
            )
        )

    # --- the persons --------------------------------------------------------
    #
    # Person `p` takes its name from a band decided by where `p` falls: the
    # first `COLLIDING_PERSONS` share names in groups, and the rest are unique.

    def _name_index_for(person_index: int) -> int:
        if person_index < DISCRIMINATING_PAIRS * 2:
            return _COLLISION_NAME_BASE + person_index // 2
        if person_index < COLLIDING_PERSONS - UNDISCRIMINATING_TRIPLES * 3:
            offset = person_index - DISCRIMINATING_PAIRS * 2
            return _COLLISION_NAME_BASE + DISCRIMINATING_PAIRS + offset // 2
        if person_index < COLLIDING_PERSONS:
            offset = person_index - (COLLIDING_PERSONS - UNDISCRIMINATING_TRIPLES * 3)
            return (
                _COLLISION_NAME_BASE + DISCRIMINATING_PAIRS + UNDISCRIMINATING_PAIRS + offset // 3
            )
        return _UNIQUE_NAME_BASE + (person_index - COLLIDING_PERSONS)

    persons: list[PersonRecord] = []
    for index in range(ACTIVE_PERSONS):
        given, family = _name_at(_name_index_for(index))
        organization_index = index % ORGANIZATIONS
        address = f"{given}.{family}{index:03d}@{_organization_domain(organization_index)}".lower()
        persons.append(
            PersonRecord(
                entity_id=_person_id(index),
                index=index,
                display_name=f"{given} {family}",
                given_name=given,
                family_name=family,
                primary_address=address,
                organization_id=organization_ids[organization_index],
            )
        )
        entities.append(
            _entity(
                _person_id(index),
                f"{given} {family}",
                entity_type=EntityType.PERSON,
            )
        )
        identifiers.append(
            ExternalIdentifier(
                identifier_id=mint.next("xid"),
                entity_id=_person_id(index),
                namespace=ExternalIdentifierNamespace.EMAIL,
                normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, address),
                display_value=address,
                principal_id=PRINCIPAL_A,
                verified=True,
            )
        )

    person_by_index = {person.index: person for person in persons}

    # --- collision groups, and what separates their members ------------------

    collision_groups: list[CollisionGroup] = []
    members: tuple[PersonRecord, ...]
    for group in range(COLLISION_GROUP_COUNT):
        if group < DISCRIMINATING_PAIRS:
            members = (person_by_index[group * 2], person_by_index[group * 2 + 1])
            first_project = project_ids[group % PROJECTS]
            second_project = project_ids[(group + 7) % PROJECTS]
            for person, project in zip(members, (first_project, second_project), strict=True):
                assignments.append(
                    Assignment(
                        assignment_id=mint.next("asn"),
                        entity_id=person.entity_id,
                        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                        principal_id=PRINCIPAL_A,
                        scope_entity_id=project,
                        role=_ROLES[person.index % len(_ROLES)],
                        discipline=_DISCIPLINES[person.index % len(_DISCIPLINES)],
                        effective_from=ORIGIN,
                    )
                )
            collision_groups.append(
                CollisionGroup(
                    display_name=members[0].display_name,
                    member_ids=tuple(person.entity_id for person in members),
                    discriminating_project_id=first_project,
                    discriminating_member_id=members[0].entity_id,
                    discriminating_organization_id=members[0].organization_id,
                    shared_project_id=None,
                )
            )
            continue

        if group < DISCRIMINATING_PAIRS + UNDISCRIMINATING_PAIRS:
            offset = group - DISCRIMINATING_PAIRS
            base = DISCRIMINATING_PAIRS * 2 + offset * 2
            members = tuple(person_by_index[base + seat] for seat in range(2))
        else:
            offset = group - DISCRIMINATING_PAIRS - UNDISCRIMINATING_PAIRS
            base = COLLIDING_PERSONS - UNDISCRIMINATING_TRIPLES * 3 + offset * 3
            members = tuple(person_by_index[base + seat] for seat in range(3))

        shared_project = project_ids[group % PROJECTS]
        for person in members:
            assignments.append(
                Assignment(
                    assignment_id=mint.next("asn"),
                    entity_id=person.entity_id,
                    assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                    principal_id=PRINCIPAL_A,
                    scope_entity_id=shared_project,
                    role=_ROLES[person.index % len(_ROLES)],
                    effective_from=ORIGIN,
                )
            )
        collision_groups.append(
            CollisionGroup(
                display_name=members[0].display_name,
                member_ids=tuple(person.entity_id for person in members),
                discriminating_project_id=None,
                discriminating_member_id=None,
                discriminating_organization_id=None,
                shared_project_id=shared_project,
            )
        )

    # --- employment, past and present ---------------------------------------

    historical_employment_person_ids: list[str] = []
    employer_change_band = range(
        COLLIDING_PERSONS + 70, COLLIDING_PERSONS + 70 + HISTORICAL_EMPLOYMENT_CHANGES
    )
    for person in persons:
        changed = person.index in employer_change_band
        if changed:
            prior_index = (person.index + 37) % ORGANIZATIONS
            assignments.append(
                Assignment(
                    assignment_id=mint.next("asn"),
                    entity_id=person.entity_id,
                    assignment_type=AssignmentType.EMPLOYMENT,
                    principal_id=PRINCIPAL_A,
                    scope_entity_id=organization_ids[prior_index],
                    role=_ROLES[(person.index + 3) % len(_ROLES)],
                    effective_from=ORIGIN,
                    effective_to=MIDPOINT,
                    status="ended",
                )
            )
            historical_employment_person_ids.append(person.entity_id)
        assignments.append(
            Assignment(
                assignment_id=mint.next("asn"),
                entity_id=person.entity_id,
                assignment_type=AssignmentType.EMPLOYMENT,
                principal_id=PRINCIPAL_A,
                scope_entity_id=person.organization_id,
                role=_ROLES[person.index % len(_ROLES)],
                discipline=_DISCIPLINES[person.index % len(_DISCIPLINES)],
                effective_from=MIDPOINT if changed else ORIGIN,
            )
        )
        relationships.append(
            EntityRelationship(
                relationship_id=mint.next("erel"),
                from_entity_id=person.entity_id,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=person.organization_id,
                principal_id=PRINCIPAL_A,
                effective_from=MIDPOINT if changed else ORIGIN,
            )
        )

    # --- project and work-package assignments for the uniquely named ---------

    current_project_band = range(COLLIDING_PERSONS, COLLIDING_PERSONS + 300)
    stale_assignment_band = range(
        COLLIDING_PERSONS + 300, COLLIDING_PERSONS + 300 + STALE_ASSIGNMENT_CANDIDATES
    )
    stale_relationship_band = range(
        COLLIDING_PERSONS + 340, COLLIDING_PERSONS + 340 + STALE_RELATIONSHIP_CANDIDATES
    )
    work_package_band = range(COLLIDING_PERSONS, COLLIDING_PERSONS + 200)
    contractor_band = range(COLLIDING_PERSONS + 170, COLLIDING_PERSONS + 300)

    stale_assignment_scopes: list[tuple[str, str]] = []
    stale_relationship_scopes: list[tuple[str, str]] = []

    for person in persons:
        if person.index in current_project_band:
            assignments.append(
                Assignment(
                    assignment_id=mint.next("asn"),
                    entity_id=person.entity_id,
                    assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                    principal_id=PRINCIPAL_A,
                    scope_entity_id=project_ids[person.index % PROJECTS],
                    role=_ROLES[person.index % len(_ROLES)],
                    effective_from=ORIGIN,
                )
            )
        if person.index in work_package_band:
            assignments.append(
                Assignment(
                    assignment_id=mint.next("asn"),
                    entity_id=person.entity_id,
                    assignment_type=AssignmentType.WORK_PACKAGE_ASSIGNMENT,
                    principal_id=PRINCIPAL_A,
                    scope_entity_id=work_package_ids[person.index % WORK_PACKAGES],
                    effective_from=ORIGIN,
                )
            )
        if person.index in stale_assignment_band:
            # `status` still says active and the dates say it is over. A status
            # nobody updated is the ordinary way a row goes stale, which is why
            # `active_only` alone never caught it.
            project = project_ids[person.index % PROJECTS]
            assignments.append(
                Assignment(
                    assignment_id=mint.next("asn"),
                    entity_id=person.entity_id,
                    assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                    principal_id=PRINCIPAL_A,
                    scope_entity_id=project,
                    role=_ROLES[person.index % len(_ROLES)],
                    effective_from=ORIGIN,
                    effective_to=MIDPOINT,
                )
            )
            stale_assignment_scopes.append((person.entity_id, project))
        if person.index in stale_relationship_band:
            # The same staleness written to the other table. An ended edge came
            # back from `relationships()` indistinguishable from a live one
            # before the state filter, and corroborated exactly as strongly.
            project = project_ids[person.index % PROJECTS]
            relationships.append(
                EntityRelationship(
                    relationship_id=mint.next("erel"),
                    from_entity_id=person.entity_id,
                    relationship_type=EntityRelationshipType.CONTRACTOR_ON,
                    to_entity_id=project,
                    principal_id=PRINCIPAL_A,
                    effective_from=ORIGIN,
                    effective_to=MIDPOINT,
                    state="ended",
                    version=2,
                )
            )
            stale_relationship_scopes.append((person.entity_id, project))
        if person.index in contractor_band:
            relationships.append(
                EntityRelationship(
                    relationship_id=mint.next("erel"),
                    from_entity_id=person.entity_id,
                    relationship_type=EntityRelationshipType.CONTRACTOR_ON,
                    to_entity_id=project_ids[(person.index + 5) % PROJECTS],
                    principal_id=PRINCIPAL_A,
                    effective_from=ORIGIN,
                )
            )
        if person.index < 200:
            relationships.append(
                EntityRelationship(
                    relationship_id=mint.next("erel"),
                    from_entity_id=person.entity_id,
                    relationship_type=EntityRelationshipType.REPORTS_TO,
                    to_entity_id=_person_id(person.index + 1),
                    principal_id=PRINCIPAL_A,
                    effective_from=ORIGIN,
                )
            )

    # --- aliases -------------------------------------------------------------
    #
    # Four kinds, and each answers a different question. A document reference is
    # unique and therefore *must* resolve; a shared nickname and a bare first
    # name are shared and therefore must not; a former name is the join that
    # ought to happen, and without it a resolver that never answers would score
    # perfectly on the refusals alone.

    document_reference_aliases: list[tuple[str, str]] = []
    for person in persons:
        if person.index < COLLIDING_PERSONS:
            continue
        display = f"{person.family_name}, {person.given_name}"
        aliases.append(
            EntityAlias(
                alias_id=mint.next("eals"),
                entity_id=person.entity_id,
                alias_type=AliasType.DOCUMENT_REFERENCE,
                normalized_value=normalize_name(display),
                display_value=display,
                principal_id=PRINCIPAL_A,
            )
        )
        document_reference_aliases.append((person.entity_id, display))

    shared_nickname_groups: list[tuple[str, tuple[str, ...]]] = []
    for group in range(SHARED_NICKNAME_GROUPS):
        nickname = NICKNAMES[group]
        members = tuple(
            person_by_index[COLLIDING_PERSONS + (group * SHARED_NICKNAME_MEMBERS) + seat]
            for seat in range(SHARED_NICKNAME_MEMBERS)
        )
        for person in members:
            aliases.append(
                EntityAlias(
                    alias_id=mint.next("eals"),
                    entity_id=person.entity_id,
                    alias_type=AliasType.NICKNAME,
                    normalized_value=normalize_name(nickname),
                    display_value=nickname,
                    principal_id=PRINCIPAL_A,
                )
            )
        shared_nickname_groups.append((nickname, tuple(person.entity_id for person in members)))

    first_name_groups: list[tuple[str, tuple[str, ...]]] = []
    # Members are one given-name pool apart rather than adjacent, and that stride
    # is the whole construction: `_name_at` cycles the given name fastest, so
    # `index` and `index + len(GIVEN_NAMES)` land on two people who genuinely
    # *share* a given name and differ in surname. Adjacent members would have
    # carried an alias spelling somebody else's first name, which is a different
    # and much less honest fixture.
    first_name_base = COLLIDING_PERSONS + 130
    for group in range(FIRST_NAME_GROUPS):
        members = tuple(
            person_by_index[first_name_base + group + seat * len(GIVEN_NAMES)]
            for seat in range(FIRST_NAME_MEMBERS)
        )
        given = members[0].given_name
        for person in members:
            aliases.append(
                EntityAlias(
                    alias_id=mint.next("eals"),
                    entity_id=person.entity_id,
                    alias_type=AliasType.PREFERRED_NAME,
                    normalized_value=normalize_name(given),
                    display_value=given,
                    principal_id=PRINCIPAL_A,
                )
            )
        first_name_groups.append((given, tuple(person.entity_id for person in members)))

    former_name_aliases: list[tuple[str, str]] = []
    for offset in range(FORMER_NAME_ALIASES):
        person = person_by_index[COLLIDING_PERSONS + 120 + offset]
        # One distinct former surname per alias, from a pool whose endings appear
        # in no canonical name. The whole alias string is therefore unique, so a
        # former name is a join the resolver is *supposed* to make and a miss is
        # a real miss rather than a collision somebody introduced by accident.
        display = f"{person.given_name} {FORMER_FAMILY_NAMES[offset]}"
        aliases.append(
            EntityAlias(
                alias_id=mint.next("eals"),
                entity_id=person.entity_id,
                alias_type=AliasType.FORMER_NAME,
                normalized_value=normalize_name(display),
                display_value=display,
                principal_id=PRINCIPAL_A,
            )
        )
        former_name_aliases.append((person.entity_id, display))

    # --- the remaining identifiers -------------------------------------------

    unverified_addresses: list[tuple[str, str]] = []
    for offset in range(UNVERIFIED_IDENTIFIERS):
        person = person_by_index[COLLIDING_PERSONS + offset]
        address = f"alt.{person.index:03d}@unverified.test"
        identifiers.append(
            ExternalIdentifier(
                identifier_id=mint.next("xid"),
                entity_id=person.entity_id,
                namespace=ExternalIdentifierNamespace.EMAIL,
                normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, address),
                display_value=address,
                principal_id=PRINCIPAL_A,
                verified=False,
            )
        )
        unverified_addresses.append((person.entity_id, address))

    vendor_identifiers: list[tuple[str, str]] = []
    for offset in range(VENDOR_IDENTIFIERS):
        person = person_by_index[COLLIDING_PERSONS + 40 + offset]
        value = f"VND-{person.index:05d}"
        identifiers.append(
            ExternalIdentifier(
                identifier_id=mint.next("xid"),
                entity_id=person.entity_id,
                namespace=ExternalIdentifierNamespace.VENDOR_SYSTEM_ID,
                normalized_value=normalize_identifier(
                    ExternalIdentifierNamespace.VENDOR_SYSTEM_ID, value
                ),
                display_value=value,
                principal_id=PRINCIPAL_A,
                verified=True,
            )
        )
        vendor_identifiers.append((person.entity_id, value))

    recycled_mailboxes: list[RecycledMailbox] = []
    recycled_base = COLLIDING_PERSONS + 200
    for offset in range(RECYCLED_MAILBOXES_COUNT):
        first = person_by_index[recycled_base + offset * 2]
        second = person_by_index[recycled_base + offset * 2 + 1]
        address = f"rotation.{offset:03d}@reissued.test"
        normalized = normalize_identifier(ExternalIdentifierNamespace.EMAIL, address)
        identifiers.append(
            ExternalIdentifier(
                identifier_id=mint.next("xid"),
                entity_id=first.entity_id,
                namespace=ExternalIdentifierNamespace.EMAIL,
                normalized_value=normalized,
                display_value=address,
                principal_id=PRINCIPAL_A,
                verified=True,
                effective_from=ORIGIN,
                effective_to=MIDPOINT,
            )
        )
        identifiers.append(
            ExternalIdentifier(
                identifier_id=mint.next("xid"),
                entity_id=second.entity_id,
                namespace=ExternalIdentifierNamespace.EMAIL,
                normalized_value=normalized,
                display_value=address,
                principal_id=PRINCIPAL_A,
                verified=True,
                effective_from=MIDPOINT,
            )
        )
        recycled_mailboxes.append(
            RecycledMailbox(
                address=address,
                first_holder_id=first.entity_id,
                second_holder_id=second.entity_id,
            )
        )

    conflicted_addresses: list[ConflictedAddress] = []
    conflict_base = COLLIDING_PERSONS + 260
    for offset in range(CONFLICTED_ADDRESS_COUNT):
        claimants = [
            person_by_index[conflict_base + offset * 2].entity_id,
            person_by_index[conflict_base + offset * 2 + 1].entity_id,
        ]
        address = f"shared.inbox.{offset:03d}@conflict.test"
        normalized = normalize_identifier(ExternalIdentifierNamespace.EMAIL, address)
        if offset >= CONFLICTED_ADDRESS_COUNT - CROSS_TYPE_CONFLICTS:
            claimants.append(organization_ids[offset % ORGANIZATIONS])
        for claimant in claimants:
            identifiers.append(
                ExternalIdentifier(
                    identifier_id=mint.next("xid"),
                    entity_id=claimant,
                    namespace=ExternalIdentifierNamespace.EMAIL,
                    normalized_value=normalized,
                    display_value=address,
                    principal_id=PRINCIPAL_A,
                    verified=True,
                )
            )
        conflicted_addresses.append(
            ConflictedAddress(address=address, claimant_ids=tuple(claimants))
        )

    # --- merged-away duplicates ---------------------------------------------

    merged_redirects: list[MergedRedirect] = []
    for offset in range(MERGED_PERSONS):
        survivor = person_by_index[COLLIDING_PERSONS + offset * 9]
        merged_id = _merged_person_id(offset)
        given, family = _name_at(_MERGED_NAME_BASE + offset)
        entities.append(
            _entity(
                merged_id,
                f"{given} {family}",
                entity_type=EntityType.PERSON,
                status=EntityStatus.MERGED_REDIRECT,
                superseded_by=survivor.entity_id,
            )
        )
        display = f"{family}, {given}"
        aliases.append(
            EntityAlias(
                alias_id=mint.next("eals"),
                entity_id=merged_id,
                alias_type=AliasType.DOCUMENT_REFERENCE,
                normalized_value=normalize_name(display),
                display_value=display,
                principal_id=PRINCIPAL_A,
            )
        )
        merged_redirects.append(
            MergedRedirect(
                merged_entity_id=merged_id,
                survivor_entity_id=survivor.entity_id,
                display_name=f"{given} {family}",
                alias_display_value=display,
            )
        )

    # --- observations --------------------------------------------------------
    #
    # Two linked observations per person from two different sources, so a
    # context card's coverage has something to count, plus a backlog of mentions
    # nothing has linked -- which section 13.1 makes a *state* rather than a
    # failed write, and which is the queue the review plane exists to drain.

    def _observation(
        *,
        kind: ObservationKind,
        value: str,
        source: int,
        ordinal: int,
        entity_id: str | None,
    ) -> EntityObservation:
        return EntityObservation(
            observation_id=mint.next("eobs"),
            principal_id=PRINCIPAL_A,
            kind=kind,
            observed_value=value,
            normalized_value=normalize_name(value),
            source_id=f"src_pssource{source:04d}",
            source_object_id=f"obj_psobject{ordinal:06d}",
            source_version_id=f"ver_psversion{ordinal:06d}",
            observed_at=ORIGIN,
            recorded_at=BUILT_AT,
            entity_id=entity_id,
        )

    ordinal = 0
    for person in persons:
        for slot, kind in enumerate(
            (ObservationKind.CONTACT_RECORD, ObservationKind.MESSAGE_PARTICIPANT)
        ):
            observations.append(
                _observation(
                    kind=kind,
                    value=person.display_name,
                    source=slot,
                    ordinal=ordinal,
                    entity_id=person.entity_id,
                )
            )
            ordinal += 1
        if person.index < 300:
            observations.append(
                _observation(
                    kind=ObservationKind.DOCUMENT_MENTION,
                    value=person.display_name,
                    source=2,
                    ordinal=ordinal,
                    entity_id=person.entity_id,
                )
            )
            ordinal += 1

    for offset in range(UNRESOLVED_MENTIONS):
        observations.append(
            _observation(
                kind=ObservationKind.DOCUMENT_MENTION,
                value=absent_name(offset % 40),
                source=3,
                ordinal=ordinal,
                entity_id=None,
            )
        )
        ordinal += 1

    # --- the second Principal ------------------------------------------------

    other_principal_person_ids: list[str] = []
    other_principal_names: list[str] = []
    other_principal_addresses: list[str] = []
    shared_addresses: list[tuple[str, str, str]] = []
    for offset in range(OTHER_PRINCIPAL_PERSONS):
        entity_id = _other_person_id(offset)
        given, family = _name_at(_OTHER_PRINCIPAL_NAME_BASE + offset)
        display = f"{given} {family}"
        entities.append(
            _entity(
                entity_id,
                display,
                entity_type=EntityType.PERSON,
                principal_id=PRINCIPAL_B,
            )
        )
        address = f"{given}.{family}{offset:03d}@othertenant.test".lower()
        identifiers.append(
            ExternalIdentifier(
                identifier_id=mint.next("xid"),
                entity_id=entity_id,
                namespace=ExternalIdentifierNamespace.EMAIL,
                normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, address),
                display_value=address,
                principal_id=PRINCIPAL_B,
                verified=True,
            )
        )
        other_principal_person_ids.append(entity_id)
        other_principal_names.append(display)
        other_principal_addresses.append(address)

        if offset < 10:
            # The same mailbox string in both partitions. Not a conflict: they
            # are two records in two partitions, and each Principal must see
            # exactly one claimant -- their own. A partition predicate left out
            # of one WHERE clause turns this into a `CONFLICTED_IDENTIFIER` for
            # both, which is the loudest possible way for the leak to show.
            shared = person_by_index[COLLIDING_PERSONS + 360 + offset]
            identifiers.append(
                ExternalIdentifier(
                    identifier_id=mint.next("xid"),
                    entity_id=entity_id,
                    namespace=ExternalIdentifierNamespace.EMAIL,
                    normalized_value=normalize_identifier(
                        ExternalIdentifierNamespace.EMAIL, shared.primary_address
                    ),
                    display_value=shared.primary_address,
                    principal_id=PRINCIPAL_B,
                    verified=True,
                )
            )
            shared_addresses.append((shared.primary_address, shared.entity_id, entity_id))

    for offset in range(OTHER_PRINCIPAL_ORGANIZATIONS):
        entities.append(
            _entity(
                _other_organization_id(offset),
                f"{_ORGANIZATION_STEMS[offset]} Holdings",
                entity_type=EntityType.ORGANIZATION,
                principal_id=PRINCIPAL_B,
            )
        )

    lone_name_person_ids = tuple(
        person_by_index[COLLIDING_PERSONS + 170 + offset].entity_id
        for offset in range(LONE_NAME_CANDIDATES)
    )

    return ProgramScaleCorpus(
        entities=tuple(entities),
        aliases=tuple(aliases),
        identifiers=tuple(identifiers),
        assignments=tuple(assignments),
        relationships=tuple(relationships),
        observations=tuple(observations),
        persons=tuple(persons),
        organization_ids=organization_ids,
        program_ids=program_ids,
        project_ids=project_ids,
        work_package_ids=work_package_ids,
        collision_groups=tuple(collision_groups),
        recycled_mailboxes=tuple(recycled_mailboxes),
        conflicted_addresses=tuple(conflicted_addresses),
        merged_redirects=tuple(merged_redirects),
        document_reference_aliases=tuple(document_reference_aliases),
        former_name_aliases=tuple(former_name_aliases),
        shared_nickname_groups=tuple(shared_nickname_groups),
        first_name_groups=tuple(first_name_groups),
        lone_name_person_ids=lone_name_person_ids,
        stale_assignment_scopes=tuple(stale_assignment_scopes),
        stale_relationship_scopes=tuple(stale_relationship_scopes),
        unverified_addresses=tuple(unverified_addresses),
        vendor_identifiers=tuple(vendor_identifiers),
        organization_addresses=tuple(organization_addresses),
        historical_employment_person_ids=tuple(historical_employment_person_ids),
        other_principal_person_ids=tuple(other_principal_person_ids),
        other_principal_names=tuple(other_principal_names),
        other_principal_addresses=tuple(other_principal_addresses),
        shared_addresses=tuple(shared_addresses),
    )


#: The corpus, built once. Every module that measures anything reads this one.
PROGRAM_SCALE_CORPUS: Final = _build()

#: Re-exported for the case builder, which asks about groups far more than it
#: asks about anything else.
COLLISION_GROUPS: Final = PROGRAM_SCALE_CORPUS.collision_groups
