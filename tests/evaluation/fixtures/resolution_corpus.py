"""A synthetic entity corpus built to make wrong joins likely.

**Why the corpus looks like this.** A resolver measured against a corpus of
distinct, well-separated people scores perfectly and tells you nothing. Every
person here exists to collide with another one: two women with the same full
name, a brother and sister who share a surname and an employer and reduce to the
same initials, a mailbox reissued from one holder to the next, a local-part
recycled across two domains, a married name and a maiden name, an organization
named after the person who founded it.

Nothing here is real. Every name is invented, every address is under `.test` or
`.invalid` (RFC 2606 reserves both precisely so a fixture cannot reach a real
host; `.invalid` is the form the entity plane's other synthetic fixtures already
use, e.g. `tests/database/test_ri_ent_wp06b_merge_split.py`), and every
identifier is synthetic (`AGENTS.md` section 5: "Tests use small synthetic
fixtures").

**Two Principals**, because a corpus with one cannot detect the leak that
matters most. `PRINCIPAL_B` holds a person whose name collides with
`PRINCIPAL_A`'s deliberately.

The collisions, and what each is for:

* `ALICE_CHEN_ENGINEER` / `ALICE_CHEN_LAWYER` — identical full name, different
  people, different employers. The plain same-name case.
* `ROBERT_CHEN` / `ROBERTA_CHEN` — siblings at one employer. Both reduce to
  "R Chen" and both answer to "Rob"; their addresses share a local-part shape
  and a domain.
* `RECYCLED_MAILBOX` — `r.chen@acme.test` belonged to Robert until he left, then
  was reissued to Roberta. Effective-dated on both. Resolving it without a
  moment is ambiguous; resolving it *at* a moment is not.
* `ALICE_NAKAMURA` — married name of `ALICE_CHEN_ENGINEER`, recorded as a former
  name alias. Same person, two names: the case where refusing to join is the
  *wrong* answer, so the corpus can catch a resolver that is merely timid.
* `JOSE_ALVAREZ` — recorded with and without diacritics. Same person.
* `CHEN_PARTNERS` — an organization named for a person. Type filtering must
  separate them.
* `CONFLICTED_ADDRESS` — one address recorded against three entities, spanning
  two entity types, which is a data defect rather than a person. Must stop,
  never pick — including when a caller supplies an `entity_type` that would
  leave one claimant standing.
* `DEPARTED_CONTRACTOR` — merged away into a survivor. Must answer historically.
* `BOB_CHEN_OTHER_PRINCIPAL` — same surname, different Principal. Must be
  invisible.
* `HALVARD_STUDIO` / `HALVARD_HOLDINGS` / `MERIDEL_LEGAL` / `HALVARD_BRAND` —
  four **distinct juristic organizations** in one corporate family, with
  deliberately overlapping typed names and a shared switchboard. Audit section M
  requires that this family "must not silently mint four unrelated organizations
  or automatically collapse distinct juristic entities solely because names
  resemble each other", and until now that rule was exercised only by
  `tests/database/test_entity_names_tbr_gs4_studios_fixture.py`, a
  database-tier test. The cluster here puts it on the fast tier. It is
  synthetic in the sense that file's header states: the *structure* of the case
  (an operating studio, a holdings company, a differently-named legal entity,
  and a brand) is the audit's description of a class of record, and not one
  character of any real register is imported, transcribed, or paraphrased.

**Four record families arrived ahead of the cases that measure them, and are
measured now.** `CORPUS_NAMES`, `CORPUS_COMMUNICATION_METHODS`,
`CORPUS_AFFILIATIONS` and `CORPUS_PARTICIPATIONS` were written before the
resolver read them, because the alternative is worse: a corpus that carries no
rows for what resolution reads measures a resolver against an empty world and
reports precision held for one that had stopped working. That ordering left a
second gap of the same kind — the rows existed, the resolver read them, and no
labelled case reached them, so the reads were exercised and their answers were
never the difference between a resolution and a refusal. `resolution_cases.py`
closes it: the typed-name, communication-value, affiliation and participation
families each now carry cases that resolve *and* cases that refuse, in both
directions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from my_pa.domain.relationship.entity import (
    AffiliationTypeCode,
    AliasType,
    Assignment,
    AssignmentState,
    AssignmentType,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    Entity,
    EntityAlias,
    EntityCommunicationMethod,
    EntityCommunicationMethodState,
    EntityName,
    EntityNameState,
    EntityProjectParticipation,
    EntityProjectParticipationState,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    NameTypeCode,
    ParticipationStatusCode,
    PersonOrganizationAffiliation,
    PersonOrganizationAffiliationState,
    RelationshipState,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
    normalize_communication_value,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name

__all__ = [
    "ACME",
    "AFTER",
    "ALICE_CHEN_ENGINEER",
    "ALICE_CHEN_LAWYER",
    "CHEN_PARTNERS",
    "CORPUS_AFFILIATIONS",
    "CORPUS_ALIASES",
    "CORPUS_ASSIGNMENTS",
    "CORPUS_COMMUNICATION_METHODS",
    "CORPUS_ENTITIES",
    "CORPUS_IDENTIFIERS",
    "CORPUS_NAMES",
    "CORPUS_PARTICIPATIONS",
    "CORPUS_RELATIONSHIPS",
    "DEPARTED_CONTRACTOR",
    "HALVARD_BRAND",
    "HALVARD_HOLDINGS",
    "HALVARD_STUDIO",
    "IRIS_BELL_CANCELLED",
    "IRIS_BELL_OTHER",
    "JOSE_ALVAREZ",
    "LEO_MARCHETTI",
    "MAYA_OSEI",
    "MERIDEL_LEGAL",
    "NADIA_OKONKWO_INCOMING",
    "NADIA_OKONKWO_OTHER",
    "NORTHWIND",
    "OMAR_DIALLO_ENDED",
    "OMAR_DIALLO_OTHER",
    "PRINCIPAL_A",
    "PRINCIPAL_B",
    "PRIYA_RAO",
    "ROBERTA_CHEN",
    "ROBERT_CHEN",
    "SURVIVING_CONTRACTOR",
    "TOMAS_HALL_CURRENT",
    "TOMAS_HALL_OTHER",
    "TOWER_PROJECT",
    "WHEN",
]

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

#: The moment every "as of" question in the cases is asked about. Fixed rather
#: than `utc_now()`, because a corpus whose answers depend on when it runs is a
#: corpus that fails on a Tuesday.
WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)
BEFORE: Final = datetime(2024, 1, 1, tzinfo=UTC)
MIDPOINT: Final = datetime(2025, 6, 1, tzinfo=UTC)
#: After `WHEN`, so a window can be *not yet begun* or *still running*. The
#: corpus had neither shape until now: every dated row was open, open-from-past,
#: or closed-in-past, so both halves of the currency defect -- a role starting
#: later read as in force, and a contract running later read as over -- were
#: measured by nothing and a rule inverting them scored identically.
AFTER: Final = datetime(2030, 1, 1, tzinfo=UTC)

ALICE_CHEN_ENGINEER: Final = "ent_alice0001engineer01"
ALICE_CHEN_LAWYER: Final = "ent_alice0002lawyer0002"
ROBERT_CHEN: Final = "ent_robert0003chen0003"
ROBERTA_CHEN: Final = "ent_roberta0004chen004"
JOSE_ALVAREZ: Final = "ent_jose0005alvarez005"
DEPARTED_CONTRACTOR: Final = "ent_departed0006contra"
SURVIVING_CONTRACTOR: Final = "ent_surviving0007cont7"
BOB_CHEN_OTHER_PRINCIPAL: Final = "ent_bob0008otherprin08"
MAYA_OSEI: Final = "ent_maya0013osei00013"
LEO_MARCHETTI: Final = "ent_leo0014marchetti1"
PRIYA_RAO: Final = "ent_priya0015rao00015"
NADIA_OKONKWO_INCOMING: Final = "ent_nadia0016incoming1"
NADIA_OKONKWO_OTHER: Final = "ent_nadia0017other0017"
TOMAS_HALL_CURRENT: Final = "ent_tomas0018current18"
TOMAS_HALL_OTHER: Final = "ent_tomas0019other0019"
IRIS_BELL_CANCELLED: Final = "ent_iris0020cancelled"
IRIS_BELL_OTHER: Final = "ent_iris0021other0021"
OMAR_DIALLO_ENDED: Final = "ent_omar0022ended0022"
OMAR_DIALLO_OTHER: Final = "ent_omar0023other0023"

ACME: Final = "ent_acme0009org000009a"
NORTHWIND: Final = "ent_northwind0010org10"
CHEN_PARTNERS: Final = "ent_chenpartners011org"
TOWER_PROJECT: Final = "ent_tower0012project12"

#: The GS4-shaped corporate family: four separate juristic persons whose names
#: overlap the way a real corporate family's names overlap. They are four
#: `Entity` rows and not one, and not one row with four name forms, because the
#: audit is explicit that a change of juristic identity is two entities linked
#: by a relationship rather than a name row on one of them (see `EntityName`'s
#: own docstring, "A historical juristic entity is its own `Entity` row").
HALVARD_STUDIO: Final = "ent_halvard0024studio"
HALVARD_HOLDINGS: Final = "ent_halvard0025holdng"
MERIDEL_LEGAL: Final = "ent_meridel0026legal0"
HALVARD_BRAND: Final = "ent_halvard0027brand0"


def _entity(
    entity_id: str,
    display_name: str,
    *,
    principal_id: str = PRINCIPAL_A,
    entity_type: EntityType = EntityType.PERSON,
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
        created_at=BEFORE,
        updated_at=WHEN,
        version=1,
        superseded_by_entity_id=superseded_by,
    )


CORPUS_ENTITIES: Final[tuple[Entity, ...]] = (
    # Two different people, one name. Neither may ever be chosen for the other.
    _entity(ALICE_CHEN_ENGINEER, "Alice Chen"),
    _entity(ALICE_CHEN_LAWYER, "Alice Chen"),
    # Siblings at one employer. Same surname, same initials, same mail domain.
    _entity(ROBERT_CHEN, "Robert Chen"),
    _entity(ROBERTA_CHEN, "Roberta Chen"),
    # Diacritics recorded inconsistently across sources; one person.
    _entity(JOSE_ALVAREZ, "José Álvarez"),
    # Merged away, with the survivor it points at.
    _entity(SURVIVING_CONTRACTOR, "Dana Okonkwo"),
    _entity(
        DEPARTED_CONTRACTOR,
        "Dana Okonkwo",
        status=EntityStatus.MERGED_REDIRECT,
        superseded_by=SURVIVING_CONTRACTOR,
    ),
    # Organizations and a project, so a type filter has something to separate.
    _entity(ACME, "Acme Construction", entity_type=EntityType.ORGANIZATION),
    _entity(NORTHWIND, "Northwind Partners", entity_type=EntityType.ORGANIZATION),
    _entity(CHEN_PARTNERS, "Alice Chen", entity_type=EntityType.ORGANIZATION),
    _entity(TOWER_PROJECT, "Harbour Tower", entity_type=EntityType.PROJECT),
    # The GS4-shaped family: four juristic persons, deliberately confusable.
    # `HALVARD_STUDIO` operates, `HALVARD_HOLDINGS` owns it, `MERIDEL_LEGAL` is
    # the differently-named legal entity that actually signs, and
    # `HALVARD_BRAND` holds the brand. Note that no two canonical names here are
    # equal, so `entities_by_canonical_name` separates all four today: every
    # collision in this cluster lives in the typed-name and communication-value
    # families below, which is the point -- the collapse the audit warns about
    # is reachable only through those reads.
    _entity(HALVARD_STUDIO, "Halvard Studio Four", entity_type=EntityType.ORGANIZATION),
    _entity(HALVARD_HOLDINGS, "Halvard Studio Holdings", entity_type=EntityType.ORGANIZATION),
    _entity(MERIDEL_LEGAL, "Meridel Design Works", entity_type=EntityType.ORGANIZATION),
    _entity(HALVARD_BRAND, "Halvard Four Licensing", entity_type=EntityType.ORGANIZATION),
    # Two Nadias and two Tomases, each pair sharing a canonical name so that a
    # scope signal is the only thing that could lift either above `AMBIGUOUS`.
    # Their assignments below carry the two future shapes.
    _entity(NADIA_OKONKWO_INCOMING, "Nadia Okonkwo"),
    _entity(NADIA_OKONKWO_OTHER, "Nadia Okonkwo"),
    _entity(TOMAS_HALL_CURRENT, "Tomas Hall"),
    _entity(TOMAS_HALL_OTHER, "Tomas Hall"),
    # Two more shared-name pairs, for the axis the four above do not test: a tie
    # whose *dates are live* and whose status or state says it is over. Without
    # them the liveness flags were deletable with the calibration gate green.
    _entity(IRIS_BELL_CANCELLED, "Iris Bell"),
    _entity(IRIS_BELL_OTHER, "Iris Bell"),
    _entity(OMAR_DIALLO_ENDED, "Omar Diallo"),
    _entity(OMAR_DIALLO_OTHER, "Omar Diallo"),
    # Another Principal's person, whose surname collides on purpose.
    _entity(BOB_CHEN_OTHER_PRINCIPAL, "Bob Chen", principal_id=PRINCIPAL_B),
    # Three uniquely named people whose *only* evidence is a bare canonical name
    # and a tie to the tower project. Uniquely named on purpose: the corpus's
    # other contextual case has a rival for the scope to exclude, which meant
    # the path where corroboration resolves a *lone* candidate -- the one where
    # the caller's own hint is the entire difference between a refusal and a
    # confident answer -- had no case at all. Their ties differ only in how
    # current each one is, which is the axis being measured.
    _entity(MAYA_OSEI, "Maya Osei"),
    _entity(LEO_MARCHETTI, "Leo Marchetti"),
    _entity(PRIYA_RAO, "Priya Rao"),
)


def _alias(
    alias_id: str,
    entity_id: str,
    name: str,
    alias_type: AliasType = AliasType.NICKNAME,
    *,
    principal_id: str = PRINCIPAL_A,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> EntityAlias:
    return EntityAlias(
        alias_id=alias_id,
        entity_id=entity_id,
        alias_type=alias_type,
        normalized_value=normalize_name(name),
        display_value=name,
        principal_id=principal_id,
        effective_from=effective_from,
        effective_to=effective_to,
    )


CORPUS_ALIASES: Final[tuple[EntityAlias, ...]] = (
    # A married name, so the corpus contains a join that *should* happen.
    _alias(
        "eals_nakamura0001alias",
        ALICE_CHEN_ENGINEER,
        "Alice Nakamura",
        AliasType.FORMER_NAME,
    ),
    # "Rob" is answered to by both siblings. A nickname is a recorded fact and
    # would resolve if it were unique; here it is not, and must not.
    _alias("eals_rob0002aliasrobt", ROBERT_CHEN, "Rob"),
    _alias("eals_rob0003aliasrobta", ROBERTA_CHEN, "Rob"),
    # Initials that both reduce to. Same trap, one step more abbreviated.
    _alias("eals_rc0004initialsrb", ROBERT_CHEN, "R Chen", AliasType.INITIALS),
    _alias("eals_rc0005initialsrt", ROBERTA_CHEN, "R Chen", AliasType.INITIALS),
    # The same person spelled without diacritics by a second source.
    _alias("eals_jose0006aliasnod", JOSE_ALVAREZ, "Jose Alvarez", AliasType.FULL_NAME),
    # A nickname unique to one person: the corpus must contain a case the
    # resolver is *supposed* to answer, or "never resolve" would score perfectly.
    _alias("eals_dana0007aliasdano", SURVIVING_CONTRACTOR, "Dana O", AliasType.PREFERRED_NAME),
    # An alias on the merged-away record, so a historical match is reachable.
    _alias("eals_dana0008aliasdept", DEPARTED_CONTRACTOR, "Danny Okonkwo"),
    # The other Principal's person, reachable only to them.
    _alias(
        "eals_bob0009aliasotherp",
        BOB_CHEN_OTHER_PRINCIPAL,
        "Bobby",
        principal_id=PRINCIPAL_B,
    ),
    # The project, so a scope can be named by name as well as by identifier.
    _alias("eals_tower0010aliasprj", TOWER_PROJECT, "Harbour Tower", AliasType.FULL_NAME),
)


def _email(
    identifier_id: str,
    entity_id: str,
    address: str,
    *,
    verified: bool = True,
    principal_id: str = PRINCIPAL_A,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> ExternalIdentifier:
    return ExternalIdentifier(
        identifier_id=identifier_id,
        entity_id=entity_id,
        namespace=ExternalIdentifierNamespace.EMAIL,
        normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, address),
        display_value=address,
        principal_id=principal_id,
        verified=verified,
        effective_from=effective_from,
        effective_to=effective_to,
    )


CORPUS_IDENTIFIERS: Final[tuple[ExternalIdentifier, ...]] = (
    # Distinct addresses for the two Alices: an identifier separates people a
    # name cannot.
    _email("xid_alice0001engineer", ALICE_CHEN_ENGINEER, "a.chen@acme.test"),
    _email("xid_alice0002lawyer00", ALICE_CHEN_LAWYER, "alice.chen@northwind.test"),
    # The recycled mailbox. Robert held it, then Roberta was given it. Both
    # records are true; only one is true at any given moment.
    _email(
        "xid_recycled0003robert",
        ROBERT_CHEN,
        "r.chen@acme.test",
        effective_from=BEFORE,
        effective_to=MIDPOINT,
    ),
    _email(
        "xid_recycled0004robert",
        ROBERTA_CHEN,
        "r.chen@acme.test",
        effective_from=MIDPOINT,
    ),
    # A local-part recycled across two domains by two unrelated people.
    _email("xid_local0005acmejose", JOSE_ALVAREZ, "j.alvarez@acme.test"),
    _email("xid_local0006northwnd", ALICE_CHEN_LAWYER, "j.alvarez@northwind.test"),
    # One address recorded against three entities, and deliberately across two
    # entity *types*: a shared mailbox is the ordinary way this happens, and the
    # cross-type case is the one that caught a real defect — filtering by type
    # before counting claimants let each filtered view see a single claimant and
    # resolve exactly, to a different entity per caller.
    _email("xid_conflict0007first", ALICE_CHEN_ENGINEER, "shared.inbox@acme.test"),
    _email("xid_conflict0008second", ROBERT_CHEN, "shared.inbox@acme.test"),
    _email("xid_conflict0011third", CHEN_PARTNERS, "shared.inbox@acme.test"),
    # An unverified address, so the corpus can tell verified from not.
    _email(
        "xid_unverified0009dana",
        SURVIVING_CONTRACTOR,
        "dana@northwind.test",
        verified=False,
    ),
    # The other Principal's address.
    _email(
        "xid_other0010principal",
        BOB_CHEN_OTHER_PRINCIPAL,
        "b.chen@acme.test",
        principal_id=PRINCIPAL_B,
    ),
)


CORPUS_ASSIGNMENTS: Final[tuple[Assignment, ...]] = (
    # Only the engineer is on the tower project, so a scope can separate the two
    # Alices -- the one case where contextual resolution earns its name.
    Assignment(
        assignment_id="asn_alice0001ontower0",
        entity_id=ALICE_CHEN_ENGINEER,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=TOWER_PROJECT,
        role="structural engineer",
    ),
    # Both siblings are on the same project, so a scope naming it corroborates
    # both and separates neither.
    Assignment(
        assignment_id="asn_robert0002ontower",
        entity_id=ROBERT_CHEN,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=TOWER_PROJECT,
    ),
    Assignment(
        assignment_id="asn_roberta0003ontowr",
        entity_id=ROBERTA_CHEN,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=TOWER_PROJECT,
    ),
    # Maya is on the project and nobody has closed the row. The one case where a
    # lone bare name is *supposed* to resolve on corroboration alone, so that
    # tightening the currency rule cannot be mistaken for refusing everything.
    Assignment(
        assignment_id="asn_maya0004ontower00",
        entity_id=MAYA_OSEI,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=TOWER_PROJECT,
        effective_from=BEFORE,
        role="commissioning manager",
    ),
    # Priya's assignment ended at the midpoint. `status` still says active,
    # because a status nobody updated is the ordinary way a row goes stale --
    # which is why `active_only` alone was not enough to catch it.
    Assignment(
        assignment_id="asn_priya0005offtower",
        entity_id=PRIYA_RAO,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=TOWER_PROJECT,
        effective_from=BEFORE,
        effective_to=MIDPOINT,
    ),
    # Nadia starts on the project in 2030. Nothing has ended, so the rule that
    # read currency off "nobody wrote an end date" called this in force and let
    # it corroborate a bare shared name into a confident answer -- a person
    # named as being somewhere they have not arrived.
    Assignment(
        assignment_id="asn_nadia0006incoming",
        entity_id=NADIA_OKONKWO_INCOMING,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=TOWER_PROJECT,
        effective_from=AFTER,
    ),
    # Tomas is on the project now under a contract that runs to 2030. The same
    # rule read the recorded end date as "over" and refused to corroborate at
    # all, which is the ordinary dated employment and the half that made the
    # rule wrong in the safe-looking direction.
    Assignment(
        assignment_id="asn_tomas0007current0",
        entity_id=TOMAS_HALL_CURRENT,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=TOWER_PROJECT,
        effective_from=BEFORE,
        effective_to=AFTER,
    ),
    # **Liveness is the only thing excluding this row.** Its window is open and
    # began in the past, so every date rule admits it; only `state` says it is
    # over. Priya's row above is `AssignmentState.ACTIVE` with expired dates,
    # which is the mirror — so before this one, deleting the liveness flag
    # changed no measurement and the corpus could not see the guard it was cited
    # for.
    #
    # `ENDED` rather than the free-text `"cancelled"` this row carried until
    # WP-RI-A-01 closed the vocabulary. The corpus is measuring that a
    # not-live assignment does not corroborate, and the *specific* string was
    # never what it measured; a value outside the closed set is now refused by
    # both the record and the server, so the fixture states the member that
    # means what the row meant.
    Assignment(
        assignment_id="asn_iris0008cancelled",
        entity_id=IRIS_BELL_CANCELLED,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=TOWER_PROJECT,
        effective_from=BEFORE,
        state=AssignmentState.ENDED,
    ),
)


CORPUS_RELATIONSHIPS: Final[tuple[EntityRelationship, ...]] = (
    EntityRelationship(
        relationship_id="erel_alice0001atacme0",
        from_entity_id=ALICE_CHEN_ENGINEER,
        relationship_type=EntityRelationshipType.WORKS_FOR,
        to_entity_id=ACME,
        principal_id=PRINCIPAL_A,
    ),
    EntityRelationship(
        relationship_id="erel_alice0002atnorth",
        from_entity_id=ALICE_CHEN_LAWYER,
        relationship_type=EntityRelationshipType.WORKS_FOR,
        to_entity_id=NORTHWIND,
        principal_id=PRINCIPAL_A,
    ),
    EntityRelationship(
        relationship_id="erel_robert0003atacme",
        from_entity_id=ROBERT_CHEN,
        relationship_type=EntityRelationshipType.WORKS_FOR,
        to_entity_id=ACME,
        principal_id=PRINCIPAL_A,
    ),
    EntityRelationship(
        relationship_id="erel_roberta0004atacm",
        from_entity_id=ROBERTA_CHEN,
        relationship_type=EntityRelationshipType.WORKS_FOR,
        to_entity_id=ACME,
        principal_id=PRINCIPAL_A,
    ),
    # Leo contracted on the tower and does not any more. The edge is kept as
    # lineage, which is what makes it dangerous: `relationships()` takes no
    # `active_only`, so an ended edge came back indistinguishable from a live one
    # and corroborated exactly as strongly.
    #
    # This row does **not** isolate the state filter, and an earlier version of
    # this comment claimed it did. Leo's dates are expired as well as his state,
    # so the date rule excludes him first and deleting the state flag changes no
    # measurement. `erel_omar0006endedopen` below is the row that isolates it.
    EntityRelationship(
        relationship_id="erel_leo0005offtower0",
        from_entity_id=LEO_MARCHETTI,
        relationship_type=EntityRelationshipType.CONTRACTOR_ON,
        to_entity_id=TOWER_PROJECT,
        principal_id=PRINCIPAL_A,
        effective_from=BEFORE,
        effective_to=MIDPOINT,
        state=RelationshipState.ENDED,
        version=2,
    ),
    # The edge equivalent of Iris's assignment, and the reason Leo's row above
    # was not enough: Leo's dates are expired *as well as* his state, so the
    # date rule excluded him before the state filter was consulted. This one is
    # open-ended and in force by every date, and only `state` says otherwise.
    EntityRelationship(
        relationship_id="erel_omar0006endedopen",
        from_entity_id=OMAR_DIALLO_ENDED,
        relationship_type=EntityRelationshipType.CONTRACTOR_ON,
        to_entity_id=TOWER_PROJECT,
        principal_id=PRINCIPAL_A,
        effective_from=BEFORE,
        state=RelationshipState.ENDED,
        version=2,
    ),
)


def _name(
    entity_name_id: str,
    entity_id: str,
    name: str,
    name_type_code: NameTypeCode,
    *,
    principal_id: str = PRINCIPAL_A,
    state: EntityNameState = EntityNameState.ACTIVE,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    retired_at: datetime | None = None,
    superseded_by: str | None = None,
) -> EntityName:
    return EntityName(
        entity_name_id=entity_name_id,
        entity_id=entity_id,
        principal_id=principal_id,
        name_type_code=name_type_code,
        display_value=name,
        normalized_value=normalize_name(name),
        effective_from=effective_from,
        effective_to=effective_to,
        state=state,
        retired_at=retired_at,
        superseded_by_entity_name_id=superseded_by,
    )


CORPUS_NAMES: Final[tuple[EntityName, ...]] = (
    # --- the GS4 cluster's typed names ------------------------------------
    # The operating studio's own legal name. Nothing matches it but itself; it
    # exists so the cluster has a row that is *not* a collision, or a resolver
    # that refused every typed name would score the same as one that read them.
    _name("enam_halvard0001legal", HALVARD_STUDIO, "Halvard Studio Four, LLC", NameTypeCode.LEGAL),
    # **The same typed name claimed by two different juristic entities.** The
    # operating company and the holding company both trade as "Halvard Studio",
    # which is the ordinary shape of a corporate family and not a data defect.
    # A typed-name match here must be AMBIGUOUS: audit section M's rule is that
    # four similarly-named organizations are never silently collapsed, and two
    # claimants of one operating name is the smallest case that can break it.
    _name("enam_halvard0002operat", HALVARD_STUDIO, "Halvard Studio", NameTypeCode.OPERATING),
    _name("enam_halvard0003holdop", HALVARD_HOLDINGS, "Halvard Studio", NameTypeCode.OPERATING),
    # The holding company's legal name, which no other row claims. Recorded so
    # the cluster can be told apart by a *legal* name even where the operating
    # name cannot tell it apart at all.
    _name(
        "enam_halvard0004holdlg",
        HALVARD_HOLDINGS,
        "Halvard Studio Holdings, LLC",
        NameTypeCode.LEGAL,
    ),
    # **A legal name and a brand name on one organization, so a typed name finds
    # an entity its canonical name never could.** `MERIDEL_LEGAL`'s canonical
    # name is "meridel design works" and shares not one token with the brand it
    # trades under; a resolver reading only `entities_by_canonical_name` cannot
    # reach it from "Halvard Four" at all.
    _name(
        "enam_meridel0005legal",
        MERIDEL_LEGAL,
        "Meridel Design Works, LLC",
        NameTypeCode.LEGAL,
    ),
    _name("enam_meridel0006brand", MERIDEL_LEGAL, "Halvard Four", NameTypeCode.BRAND),
    # ...and the brand-holding company claims the identical brand name, so the
    # brand axis is contested exactly as the operating axis is. Two juristic
    # entities, one brand: candidates, never a merge.
    _name("enam_halvard0007brand", HALVARD_BRAND, "Halvard Four", NameTypeCode.BRAND),
    _name(
        "enam_halvard0008brndlg",
        HALVARD_BRAND,
        "Halvard Four Licensing, LLC",
        NameTypeCode.LEGAL,
    ),
    # **A superseded name row, which must never match.** The studio traded as
    # "Halvard Studio Three" until the correction that replaced it with
    # `enam_halvard0002operat`. A superseded row holds the spelling the
    # Principal has already corrected away, so matching it hands back the very
    # value the correction removed.
    _name(
        "enam_halvard0009supers",
        HALVARD_STUDIO,
        "Halvard Studio Three",
        NameTypeCode.OPERATING,
        state=EntityNameState.SUPERSEDED,
        superseded_by="enam_halvard0002operat",
    ),
    # **A retired name row, which must never match.** Withdrawn rather than
    # corrected: the Principal said to stop using it and named no successor.
    _name(
        "enam_halvard0010retird",
        HALVARD_BRAND,
        "Halvard Signage",
        NameTypeCode.BRAND,
        state=EntityNameState.RETIRED,
        retired_at=MIDPOINT,
    ),
    # --- typed names outside the cluster -----------------------------------
    # Acme's registered name, which its canonical trading name is not. The
    # person-and-project half of the corpus needs at least one organization
    # reachable by a legal name it is not canonically called, or the
    # brand/legal split would be measured only inside the GS4 cluster.
    _name("enam_acme0011legal000", ACME, "Acme Construction Group, LLC", NameTypeCode.LEGAL),
    # The engineer's former name, recorded *again* as a typed name beside the
    # `FORMER_NAME` alias `eals_nakamura0001alias` already carries. Two families
    # holding one fact is the ordinary state of this plane, and the collision
    # this creates is the benign one: both rows name the same entity, so a
    # resolver reading both must still answer one candidate and not two.
    _name(
        "enam_nakamura0012hist",
        ALICE_CHEN_ENGINEER,
        "Alice Nakamura",
        NameTypeCode.HISTORICAL_NAME,
    ),
    # The other Principal's typed name, colliding on purpose with the most
    # contested name in this corpus. Reachable to `PRINCIPAL_B` and to nobody
    # else: the partition case for this family.
    _name(
        "enam_bob0013otherprin",
        BOB_CHEN_OTHER_PRINCIPAL,
        "Alice Chen",
        NameTypeCode.LEGAL,
        principal_id=PRINCIPAL_B,
    ),
)


def _communication(
    communication_method_id: str,
    entity_id: str,
    value: str,
    method_type_code: CommunicationMethodTypeCode,
    *,
    principal_id: str = PRINCIPAL_A,
    usage: CommunicationUsageContextCode = CommunicationUsageContextCode.CORPORATE,
    state: EntityCommunicationMethodState = EntityCommunicationMethodState.ACTIVE,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    retired_at: datetime | None = None,
    linked_external_identifier_id: str | None = None,
) -> EntityCommunicationMethod:
    return EntityCommunicationMethod(
        communication_method_id=communication_method_id,
        entity_id=entity_id,
        principal_id=principal_id,
        method_type_code=method_type_code,
        usage_context_code=usage,
        normalized_value=normalize_communication_value(method_type_code, value),
        display_value=value,
        verification_status_code=CommunicationVerificationStatusCode.UNRESOLVED,
        effective_from=effective_from,
        effective_to=effective_to,
        state=state,
        retired_at=retired_at,
        superseded_by_communication_method_id=None,
        linked_external_identifier_id=linked_external_identifier_id,
    )


CORPUS_COMMUNICATION_METHODS: Final[tuple[EntityCommunicationMethod, ...]] = (
    # **One communication value claimed by two entities.** A corporate family
    # answers one switchboard, so the operating company and the holding company
    # hold the identical number. Two claimants of one value is a refusal to
    # make, never a merge to perform -- the communication-value axis of the same
    # rule the shared operating name above states for the typed-name axis.
    _communication(
        "ecmm_halvard0001phone",
        HALVARD_STUDIO,
        "+1 555 0100 200",
        CommunicationMethodTypeCode.PHONE,
    ),
    _communication(
        "ecmm_halvard0002phone",
        HALVARD_HOLDINGS,
        "+1 555 0100 200",
        CommunicationMethodTypeCode.PHONE,
    ),
    # **A value whose entity is reachable, and reachable by nothing else.** The
    # signing legal entity answers the brand's mailbox, so this address finds
    # `MERIDEL_LEGAL` -- an entity neither its canonical name nor any name in
    # the reference would have reached. Exactly one claimant, so this is the row
    # that proves a communication value can produce a candidate at all.
    _communication(
        "ecmm_meridel0003email",
        MERIDEL_LEGAL,
        "studio@halvard.example.invalid",
        CommunicationMethodTypeCode.EMAIL,
    ),
    # The brand company's public site, a third form of the same family name on a
    # third juristic entity. Present so the family's overlap is not only in the
    # two families a resolver reads by value.
    _communication(
        "ecmm_halvard0004websit",
        HALVARD_BRAND,
        "https://halvard.example.invalid",
        CommunicationMethodTypeCode.WEBSITE,
    ),
    # **A retired value, which must never match.** The studio's pre-rename
    # mailbox, withdrawn rather than corrected. This row is what makes the
    # ACTIVE filter measurable: delete the filter and this address starts
    # producing a candidate.
    _communication(
        "ecmm_halvard0005retird",
        HALVARD_STUDIO,
        "info@halvardthree.example.invalid",
        CommunicationMethodTypeCode.EMAIL,
        state=EntityCommunicationMethodState.RETIRED,
        retired_at=MIDPOINT,
    ),
    # The same mailbox recorded twice: once as the identity binding
    # `xid_alice0001engineer` and once here as a way to reach her, cross-
    # referenced rather than duplicated. This is the row that must *not* change
    # an answer: `entities_by_identifier` already matches this value, so the
    # fall-through to the communication-value read is never reached for it.
    _communication(
        "ecmm_alice0006email00",
        ALICE_CHEN_ENGINEER,
        "a.chen@acme.test",
        CommunicationMethodTypeCode.EMAIL,
        usage=CommunicationUsageContextCode.OFFICE,
        linked_external_identifier_id="xid_alice0001engineer",
    ),
    # A number that is no entity's external identifier anywhere in this corpus,
    # held by exactly one person. The mirror of the row above: the fall-through
    # is the *only* path that reaches this value, so if the fall-through is
    # dropped this row silently stops mattering.
    _communication(
        "ecmm_roberta0007phone",
        ROBERTA_CHEN,
        "+1 555 0100 311",
        CommunicationMethodTypeCode.PHONE,
        usage=CommunicationUsageContextCode.PERSONAL,
    ),
    # **The partition case.** The other Principal holds the address
    # `PRINCIPAL_A` already carries as an external identifier for their own Bob
    # Chen. Reachable to `PRINCIPAL_B` and to nobody else.
    _communication(
        "ecmm_bob0008otherprin",
        BOB_CHEN_OTHER_PRINCIPAL,
        "b.chen@acme.test",
        CommunicationMethodTypeCode.EMAIL,
        principal_id=PRINCIPAL_B,
        usage=CommunicationUsageContextCode.PERSONAL,
    ),
    # **One mailbox claimed by two juristic entities of the family**, on the axis
    # a resolution request can actually reach. The switchboard number at the top
    # of this collection states the identical collision and nothing can ask
    # about it: a request carries an `ExternalIdentifierNamespace`, that enum has
    # no `PHONE` member, and the communication-value read is entered only from
    # `_by_identifier`'s fall-through — so the only contested value the resolver
    # could ever be handed is an email one, and until these two rows the corpus
    # held none. Two claimants of one value is a refusal to make and never a
    # merge to perform, which is the communication-value axis of the rule the
    # shared operating name states for the typed-name axis.
    _communication(
        "ecmm_halvard0009share",
        HALVARD_STUDIO,
        "hello@halvard.example.invalid",
        CommunicationMethodTypeCode.EMAIL,
    ),
    _communication(
        "ecmm_halvard0010share",
        HALVARD_HOLDINGS,
        "hello@halvard.example.invalid",
        CommunicationMethodTypeCode.EMAIL,
    ),
    # **The partition case in its strong form.** The other Principal's contact
    # card carries the identical shared mailbox, colliding on purpose with the
    # most contested communication value `PRINCIPAL_A` can reach. Every other
    # cross-Principal row in this corpus is reachable only through a reference
    # that finds `PRINCIPAL_A` nothing at all, so a leak there turns a silence
    # into a name; a leak here is a third candidate on an answer that already
    # carries two, which is the shape a partition defect actually takes once
    # both Principals hold a row about one value.
    _communication(
        "ecmm_bob0011otherprin",
        BOB_CHEN_OTHER_PRINCIPAL,
        "hello@halvard.example.invalid",
        CommunicationMethodTypeCode.EMAIL,
        principal_id=PRINCIPAL_B,
    ),
    # **The engineer's address on somebody else's contact card**, which is what a
    # mail connector writing to the wrong row leaves behind. Recorded rather than
    # corrected, because the whole value of the row is that
    # `entities_by_identifier` matches this address for the engineer, so the
    # fall-through to the channel plane is never reached and Roberta can never be
    # offered for it. `ecmm_alice0006email00` states the same rule with both rows
    # on one entity, where widening the fall-through would change nothing
    # visible; this one puts a *second* entity behind the same gate, so widening
    # it offers her beside the engineer and turns an exact resolution into an
    # ambiguous one.
    _communication(
        "ecmm_roberta0012alice",
        ROBERTA_CHEN,
        "a.chen@acme.test",
        CommunicationMethodTypeCode.EMAIL,
        usage=CommunicationUsageContextCode.OFFICE,
    ),
)


def _affiliation(
    affiliation_id: str,
    person_entity_id: str,
    organization_entity_id: str | None,
    *,
    principal_id: str = PRINCIPAL_A,
    affiliation_type_code: AffiliationTypeCode = AffiliationTypeCode.EMPLOYMENT,
    job_title: str | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    state: PersonOrganizationAffiliationState = PersonOrganizationAffiliationState.ACTIVE,
    superseded_by: str | None = None,
) -> PersonOrganizationAffiliation:
    return PersonOrganizationAffiliation(
        affiliation_id=affiliation_id,
        principal_id=principal_id,
        person_entity_id=person_entity_id,
        affiliation_type_code=affiliation_type_code,
        organization_entity_id=organization_entity_id,
        job_title=job_title,
        effective_from=effective_from,
        effective_to=effective_to,
        state=state,
        superseded_by_affiliation_id=superseded_by,
    )


CORPUS_AFFILIATIONS: Final[tuple[PersonOrganizationAffiliation, ...]] = (
    # **In force at `WHEN`, and the only thing separating the two Alices by
    # employer.** Open-ended and active, begun in the past: every rule that
    # judges currency admits it, so a scope naming `ACME` corroborates the
    # engineer and nobody else.
    _affiliation(
        "poaf_alice0001atacme0",
        ALICE_CHEN_ENGINEER,
        ACME,
        job_title="structural engineer",
        effective_from=BEFORE,
    ),
    # The rival, so corroboration has something to *exclude* rather than merely
    # something to confirm. A scope naming `ACME` must leave this one out.
    _affiliation(
        "poaf_alice0002atnorth",
        ALICE_CHEN_LAWYER,
        NORTHWIND,
        job_title="counsel",
        effective_from=BEFORE,
    ),
    # **Ended by date, and must not corroborate.** `state` is still ACTIVE,
    # because an active row recording a *past* affiliation is the ordinary case
    # for this family and not a contradiction -- see
    # `PersonOrganizationAffiliationState`'s docstring. The mirror of Priya's
    # stale assignment, on the family a resolver reads for the same question.
    _affiliation(
        "poaf_priya0003ended00",
        PRIYA_RAO,
        ACME,
        effective_from=BEFORE,
        effective_to=MIDPOINT,
    ),
    # **Superseded, and must not corroborate**, even though its dates are wide
    # open and every date rule admits it. This row isolates the state filter the
    # way `erel_omar0006endedopen` isolates it for relationships: delete the
    # state filter and a corrected-away employer starts corroborating again.
    _affiliation(
        "poaf_leo0004superseded",
        LEO_MARCHETTI,
        ACME,
        effective_from=BEFORE,
        state=PersonOrganizationAffiliationState.SUPERSEDED,
        superseded_by="poaf_leo0005corrected",
    ),
    # The correction that replaced it: the employer the record now states.
    _affiliation(
        "poaf_leo0005corrected",
        LEO_MARCHETTI,
        NORTHWIND,
        affiliation_type_code=AffiliationTypeCode.CONTRACTOR,
        effective_from=BEFORE,
    ),
    # A person with no employer at all, which is a fact and not a gap (the
    # audit's independent-consultant case). `organization_entity_id` is NULL, so
    # this row can corroborate no scope whatsoever -- the null branch is
    # exercised rather than assumed to be unreachable.
    _affiliation(
        "poaf_omar0006independ",
        OMAR_DIALLO_ENDED,
        None,
        affiliation_type_code=AffiliationTypeCode.INDEPENDENT_CONSULTANT,
        effective_from=BEFORE,
    ),
    # The partition case for this family: the other Principal's affiliation,
    # reachable to them alone.
    _affiliation(
        "poaf_bob0007otherprin",
        BOB_CHEN_OTHER_PRINCIPAL,
        None,
        principal_id=PRINCIPAL_B,
        affiliation_type_code=AffiliationTypeCode.INDEPENDENT_CONSULTANT,
        effective_from=BEFORE,
    ),
)


def _participation(
    participation_id: str,
    participant_entity_id: str,
    *,
    principal_id: str = PRINCIPAL_A,
    role_basis_code: RoleBasisCode = RoleBasisCode.CONTRACTUAL,
    stakeholder_side_code: StakeholderSideCode = StakeholderSideCode.DESIGN,
    stakeholder_class_code: StakeholderClassCode = StakeholderClassCode.CORE,
    relationship_status_code: ParticipationStatusCode = ParticipationStatusCode.ACTIVE,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
    state: EntityProjectParticipationState = EntityProjectParticipationState.ACTIVE,
    superseded_by: str | None = None,
) -> EntityProjectParticipation:
    return EntityProjectParticipation(
        participation_id=participation_id,
        principal_id=principal_id,
        project_entity_id=TOWER_PROJECT,
        participant_entity_id=participant_entity_id,
        project_display_name="Harbour Tower",
        role_basis_code=role_basis_code,
        stakeholder_side_code=stakeholder_side_code,
        stakeholder_class_code=stakeholder_class_code,
        relationship_status_code=relationship_status_code,
        effective_from=effective_from,
        effective_to=effective_to,
        state=state,
        superseded_by_participation_id=superseded_by,
    )


CORPUS_PARTICIPATIONS: Final[tuple[EntityProjectParticipation, ...]] = (
    # **In force at `WHEN`.** Open-ended, active, begun in the past: the
    # engineer participates in the tower and the lawyer does not, so a scope
    # naming the tower corroborates one of the two identical names.
    _participation("eppt_alice0001ontower", ALICE_CHEN_ENGINEER, effective_from=BEFORE),
    # **Ended by date, and must not corroborate.** Priya's tie to the tower is
    # over; `state` is still ACTIVE because this row is the authoritative record
    # of a participation that ended, which is the family's ordinary shape.
    _participation(
        "eppt_priya0002ended00",
        PRIYA_RAO,
        relationship_status_code=ParticipationStatusCode.COMPLETED,
        effective_from=BEFORE,
        effective_to=MIDPOINT,
    ),
    # **Superseded, and must not corroborate.** Open-ended, so every date rule
    # admits it and only `state` excludes it: the row that isolates the state
    # filter for this family.
    _participation(
        "eppt_leo0003superseded",
        LEO_MARCHETTI,
        stakeholder_side_code=StakeholderSideCode.CONTRACTOR,
        effective_from=BEFORE,
        state=EntityProjectParticipationState.SUPERSEDED,
        superseded_by="eppt_leo0004corrected",
    ),
    # The correction that replaced it, recording the engagement as the closed
    # thing it actually was. It exists so the superseded row above points at a
    # real successor, and it corroborates nothing either -- its dates are spent.
    _participation(
        "eppt_leo0004corrected",
        LEO_MARCHETTI,
        role_basis_code=RoleBasisCode.SOURCE_VERIFIED,
        stakeholder_side_code=StakeholderSideCode.CONTRACTOR,
        relationship_status_code=ParticipationStatusCode.COMPLETED,
        effective_from=BEFORE,
        effective_to=MIDPOINT,
    ),
    # **The GS4 cluster's discriminator.** Exactly one of the four juristic
    # entities is actually on this project. A scope naming the tower must
    # therefore separate the operating studio from three lookalikes -- which is
    # the constructive half of audit section M's rule: the family is neither
    # collapsed into one organization nor left permanently unresolvable.
    _participation(
        "eppt_halvard0005tower",
        HALVARD_STUDIO,
        stakeholder_side_code=StakeholderSideCode.DESIGN,
        effective_from=BEFORE,
    ),
    # Not yet begun, and must not corroborate. The participation mirror of
    # `asn_nadia0006incoming`: nothing has ended, so a rule reading currency off
    # "nobody wrote an end date" calls this in force and names a person as being
    # somewhere they have not arrived.
    _participation("eppt_nadia0006future0", NADIA_OKONKWO_INCOMING, effective_from=AFTER),
)
