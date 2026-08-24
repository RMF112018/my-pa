"""A synthetic entity corpus built to make wrong joins likely.

**Why the corpus looks like this.** A resolver measured against a corpus of
distinct, well-separated people scores perfectly and tells you nothing. Every
person here exists to collide with another one: two women with the same full
name, a brother and sister who share a surname and an employer and reduce to the
same initials, a mailbox reissued from one holder to the next, a local-part
recycled across two domains, a married name and a maiden name, an organization
named after the person who founded it.

Nothing here is real. Every name is invented, every address is under `.test`
(RFC 2606, which reserves it precisely so a fixture cannot reach a real host),
and every identifier is synthetic (`AGENTS.md` section 5: "Tests use small
synthetic fixtures").

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
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from my_pa.domain.relationship.entity import (
    AliasType,
    Assignment,
    AssignmentState,
    AssignmentType,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    RelationshipState,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name

__all__ = [
    "ACME",
    "AFTER",
    "ALICE_CHEN_ENGINEER",
    "ALICE_CHEN_LAWYER",
    "CHEN_PARTNERS",
    "CORPUS_ALIASES",
    "CORPUS_ASSIGNMENTS",
    "CORPUS_ENTITIES",
    "CORPUS_IDENTIFIERS",
    "CORPUS_RELATIONSHIPS",
    "DEPARTED_CONTRACTOR",
    "IRIS_BELL_CANCELLED",
    "IRIS_BELL_OTHER",
    "JOSE_ALVAREZ",
    "LEO_MARCHETTI",
    "MAYA_OSEI",
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
