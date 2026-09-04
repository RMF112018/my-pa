"""The entity record families' security matrix, asserted structurally (RI-ENT-WP-13).

Everything here is read out of a live declaration -- the SQLAlchemy `MetaData`,
the live enums, the live `EntitiesRepository` port and the live command surface
of `my_pa.application.entity_record_families`. Nothing opens a connection, so
this module runs in the fast local loop; its database-backed sibling proves the
same acceptance criterion against a real migrated database. The two halves are
not redundant. A migration test sees what a database ended up with; this one
sees what the source *declares*, which is where a regression is introduced and
where it is cheapest to catch.

`tests/unit/test_entity_record_family_service.py` already freezes the seventeen
commands, and already proves that no command declares `principal_id`, `version`,
`state`, a `superseded_by_*`, `retired_at` or `updated_at`. None of that is
restated here. This module asserts what that one does not:

* **A caller never chooses the identifier of a row it is creating.** No
  `Record*` command declares its own family's primary key, and the identifier
  the service mints for that family is issued under that family's registered
  `IdKind`. A `Correct*` command *does* name a primary key, and that is not the
  same thing: it names the **predecessor**, a reference to a row that already
  exists, not a caller-chosen identifier for a new one. The distinction is the
  reason this rule is scoped to `Record*`, and the test asserts both sides of
  it so that a mistyped column would redden rather than pass vacuously.
* **No opaque JSON catch-all.** Not one column of the campaign's 11 tables is
  JSON or JSONB. The detector is not vacuous: the same predicate run over the
  rest of the schema finds plenty, and the test asserts that it does.
* **Partition discipline, by name in both directions.** 8 of the 11 carry
  `principal_id`; the 3 global seeded reference vocabularies deliberately do
  not, and are registered with their reasons in
  `tests/architecture/test_user_owned_tables_are_partitioned.py`. Asserting the
  split in both directions is what makes a new Principal-bearing table without
  `principal_id` red, and a `principal_id` grafted onto a global vocabulary red
  too.
* **Archive, end and supersede -- with no delete path even declared.** The
  existing suite proves supersession is non-destructive by exercising it. This
  proves the weaker-but-different claim that no delete verb exists to exercise.
  Note the gap it fills: the published surface is derived here from the command
  annotations of the service's own methods, not by filtering `__all__` on the
  four allowed prefixes the way the existing test does -- that filter would let
  a hypothetical `DeleteEntityName` through unnoticed if somebody ever widened
  the prefix list, because a name the filter drops is a name it stops checking.
* **Optimistic versions, on every path that can race.** Every supersession,
  retirement and revision on the port that names one of the 6 Entity-bound
  families takes a required `expected_version`, and so does every `Correct*`,
  `Retire*` and `Revise*` command. Both populations are derived by inspection
  and both are asserted by size, so a new family that quietly skipped the guard
  would change the size and redden.
* **Merge enumerates every family; split inverts every one.** All 6 appear in
  `IdentityEffectFamily` and in `MergeFamily`, and each admits at least one
  ambiguity disposition. The assertion plane's deliberate absence from
  `MergeFamily` is asserted as a *recorded decision*, not as an accident.
* **Merge and split stay operator-only**, derived exactly the way
  `tests/contract/test_capabilities_and_readiness.py` derives it.
* **The assertion plane's free text is bounded**, at `ENTITY_CHANGE_REASON_LIMIT`,
  in the schema and in the domain both.

## A disclosed open item this module does not paper over

`entity_project_participations.role_text`, `.discipline_text`, `.scope_text`
and `.project_display_name`, `entity_names.display_value`,
`entity_communication_methods.display_value` and `entity_addresses.raw_value`
are declared `text` carrying only a non-blank CHECK. Neither the migration nor
`EntityRecordFamilyService` applies any upper character bound to them. That is
a real gap, and it is named here rather than hidden behind a test that asserts
something weaker and reads as if the gap were closed. Closing it needs a
migration, which is outside this work package, so the bounded-text test below
asserts only the ceiling that genuinely exists.

Every identifier constructed here is minted by `issue_identifier` and is
synthetic.
"""

from __future__ import annotations

import ast
import inspect
import re
from dataclasses import fields
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import JSON, CheckConstraint, Table
from sqlalchemy.dialects.postgresql import JSONB

from my_pa.application import entity_record_families as service_module
from my_pa.application.capabilities import build_capability_manifest
from my_pa.application.entity_record_families import (
    EntityRecordFamily,
    EntityRecordFamilyService,
    RecordAffiliation,
    RecordCommunicationMethod,
    RecordEntityAddress,
    RecordEntityName,
    RecordProjectParticipation,
    RetireAffiliation,
    RetireCommunicationMethod,
    RetireEntityAddress,
    RetireEntityName,
    RetireProjectParticipation,
)
from my_pa.application.identity_correction import MergeFamily
from my_pa.contracts.ports import EntitiesRepository
from my_pa.contracts.v1 import EffectiveLimits
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, is_operator_only
from my_pa.domain.relationship.governance import (
    ENTITY_CHANGE_REASON_LIMIT,
    AssertionStatus,
    EntityAssertion,
    EntityAssertionEvidence,
    EvidenceRole,
    MutationAuthority,
)
from my_pa.domain.relationship.identity_correction import (
    IdentityEffectFamily,
    dispositions_for,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import METADATA, SCHEMA

WHEN: Final = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)

#: Every table this campaign created, in the order the audit's section N lists
#: them. Written out rather than derived from an `entity_` prefix scan: the
#: prefix also matches the pre-campaign entity plane, and a rule that widened
#: itself as the schema grew would stop being the claim this module is making.
CAMPAIGN_TABLES: Final = (
    "entity_names",
    "entity_organization_profiles",
    "entity_addresses",
    "entity_communication_methods",
    "entity_role_types",
    "entity_discipline_types",
    "entity_project_participations",
    "entity_person_organization_affiliations",
    "entity_relationship_types",
    "entity_assertions",
    "entity_assertion_evidence",
)

#: The deliberately global, Principal-independent seeded reference vocabularies.
#: Every row of each is written by its own migration; no write path lets a
#: Principal add, change, or read one row as if it were their own. Registered
#: with those reasons in `tests/architecture/test_user_owned_tables_are_partitioned.py`.
GLOBAL_TAXONOMIES: Final = frozenset(
    {"entity_role_types", "entity_discipline_types", "entity_relationship_types"}
)

#: For each family whose rows carry a minted surrogate key: the service method
#: that creates one, the command a caller sends it, the local the method binds
#: the fresh identifier to, and the prefix that identifier must carry.
#:
#: `RecordOrganizationProfile` is absent on purpose and is asserted absent
#: below: a profile is keyed by the entity it describes, so there is no new
#: identifier for anybody -- caller or service -- to choose.
SERVER_ISSUED: Final = (
    ("record_name", RecordEntityName, RetireEntityName, "entity_name_id", "enam"),
    ("record_address", RecordEntityAddress, RetireEntityAddress, "entity_address_id", "eadr"),
    (
        "record_communication_method",
        RecordCommunicationMethod,
        RetireCommunicationMethod,
        "communication_method_id",
        "ecmm",
    ),
    (
        "record_project_participation",
        RecordProjectParticipation,
        RetireProjectParticipation,
        "participation_id",
        "eppt",
    ),
    ("record_affiliation", RecordAffiliation, RetireAffiliation, "affiliation_id", "poaf"),
)

#: Verbs that destroy rather than close. Matched on snake_case and CamelCase
#: word boundaries rather than as substrings, so `records_bound_to_entity_outside`
#: is not read as a `record` verb and `redirect_entity` is not read as `direct`.
DELETE_VERBS: Final = frozenset(
    {"delete", "purge", "drop", "remove", "destroy", "erase", "expunge"}
)

#: The prefixes the published authoring surface is allowed to use. Every one
#: closes a row or opens a new one; none of them ends a row's existence.
ALLOWED_COMMAND_PREFIXES: Final = ("Record", "Correct", "Retire", "Revise")

#: The limits `D-24` makes the configuration defaults, exactly as
#: `tests/contract/test_capabilities_and_readiness.py` states them.
LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)

#: The identity-correction pair whose preview and apply are both reserved.
IDENTITY_CORRECTION_CAPABILITIES: Final = frozenset(
    {
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
    }
)


def _table(name: str) -> Table:
    """The live `Table` for one campaign table, or a failure naming it.

    A `KeyError` here would mean the table was renamed or dropped, which is a
    result this module wants stated rather than raised.
    """
    qualified = f"{SCHEMA}.{name}"
    assert qualified in METADATA.tables, f"{qualified} is not declared in the live metadata"
    return METADATA.tables[qualified]


def _words(name: str) -> frozenset[str]:
    """`name` lowercased and split into words on case and separator boundaries."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return frozenset(part for part in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if part)


def _destroys(name: str) -> bool:
    """Whether `name` reads as a delete verb rather than a lifecycle transition."""
    return bool(_words(name) & DELETE_VERBS)


def _is_json(column_type: object) -> bool:
    """Whether a column's declared type is an opaque JSON document."""
    return isinstance(column_type, JSON | JSONB) or "JSON" in type(column_type).__name__.upper()


def _public_methods(owner: type) -> dict[str, object]:
    """The public callables declared directly on `owner`."""
    return {
        name: member
        for name, member in vars(owner).items()
        if not name.startswith("_") and callable(member)
    }


def _service_method_nodes() -> dict[str, ast.FunctionDef]:
    """The `EntityRecordFamilyService` method bodies, as syntax.

    Read as source rather than run: "the service mints this family's identifier
    under this kind" is a claim about what the code says, and exercising one
    call would prove it for one call rather than for the declaration.
    """
    tree = ast.parse(inspect.getsource(service_module))
    declared = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "EntityRecordFamilyService"
    ]
    assert len(declared) == 1
    return {node.name: node for node in declared[0].body if isinstance(node, ast.FunctionDef)}


def _minted(method: ast.FunctionDef) -> list[tuple[str, str]]:
    """Every `<local> = issue_identifier(IdKind.<MEMBER>)` in `method`."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        call = node.value
        if not isinstance(target, ast.Name) or not isinstance(call, ast.Call):
            continue
        if not (isinstance(call.func, ast.Name) and call.func.id == "issue_identifier"):
            continue
        assert len(call.args) == 1
        kind = call.args[0]
        assert isinstance(kind, ast.Attribute)
        assert isinstance(kind.value, ast.Name) and kind.value.id == "IdKind"
        found.append((target.id, kind.attr))
    return found


def _published_commands() -> dict[str, type]:
    """The command surface, derived from what the service's methods accept.

    Deliberately *not* `__all__` filtered on the allowed prefixes: that filter
    answers "which exported names look like commands", and a name it does not
    match is a name it stops looking at. This derivation answers "which payloads
    can actually be sent", so a `delete_name(..., command: DeleteEntityName)`
    lands inside the population instead of outside it.
    """
    commands: dict[str, type] = {}
    for name, method in _public_methods(EntityRecordFamilyService).items():
        hints = inspect.get_annotations(method, eval_str=True)
        command = hints.get("command")
        assert command is not None, f"{name} takes no command"
        assert isinstance(command, type)
        commands[command.__name__] = command
    return commands


def _record_id_field_names() -> frozenset[str]:
    """The parameter a caller uses to name an existing row of each family.

    Taken from the leading field of every `Correct*`, `Retire*` and `Revise*`
    command, so the set follows the command surface rather than a list kept by
    hand beside it.
    """
    names = {
        fields(command)[0].name
        for name, command in _published_commands().items()
        if name.startswith(("Correct", "Retire", "Revise"))
    }
    return frozenset(names)


# --- 1. A caller never names the row it is creating --------------------------


@pytest.mark.parametrize(
    ("method_name", "record_command", "retire_command", "record_id", "prefix"),
    SERVER_ISSUED,
    ids=[case[0] for case in SERVER_ISSUED],
)
def test_no_record_command_lets_a_caller_choose_the_identifier_of_a_new_row(
    method_name: str,
    record_command: type,
    retire_command: type,
    record_id: str,
    prefix: str,
) -> None:
    """A caller may reference an existing row; it may not name a new one.

    Scoped to `Record*` on purpose. A `Correct*` command legitimately declares
    `record_id`, because there it names the **predecessor** -- a reference to a
    row that already exists and whose version the caller is guarding -- rather
    than a caller-chosen identifier for the row about to be written. Retiring
    is the same reference in its plainest form, and this test uses the `Retire*`
    command to prove the field name it is asserting absent from `Record*` is the
    real one: a typo would make the absence trivially true, and the paired
    presence assertion is what stops that from passing.
    """
    assert record_id not in {declared.name for declared in fields(record_command)}
    assert record_id in {declared.name for declared in fields(retire_command)}
    assert method_name in _public_methods(EntityRecordFamilyService)
    assert prefix


def test_each_family_mints_its_new_identifier_under_its_own_registered_kind() -> None:
    """The identifier the service issues carries that family's registered prefix.

    Two failure modes, both real. A `record_*` that reached for a neighbouring
    `IdKind` would issue identifiers a later `parse_identifier` resolves to the
    wrong family; a change to a kind's own value would silently restamp every
    identifier the family issues from then on. The first is caught by reading
    the call, the second by issuing one and parsing it back.
    """
    methods = _service_method_nodes()
    seen: dict[str, str] = {}
    for method_name, _record, _retire, record_id, prefix in SERVER_ISSUED:
        mints = [pair for pair in _minted(methods[method_name]) if pair[0] == record_id]
        assert len(mints) == 1, f"{method_name} mints {record_id} {len(mints)} times"
        _, kind_member = mints[0]
        kind = IdKind[kind_member]
        assert kind.value == prefix
        issued = issue_identifier(kind)
        assert issued.startswith(f"{prefix}_")
        seen[method_name] = kind_member

    assert len(seen) == len(SERVER_ISSUED)
    assert len(set(seen.values())) == len(SERVER_ISSUED)
    # The profile family is keyed by the entity it describes, so it mints
    # nothing and there is no identifier for anyone to choose.
    assert _minted(methods["record_organization_profile"]) == []


# --- 2. No opaque JSON catch-all ---------------------------------------------


def test_no_new_campaign_table_carries_an_opaque_json_catch_all() -> None:
    """Every field of these tables is a declared column with a declared type.

    This is the structural half of RI-ENT-WP-13's acceptance criterion: no
    fixture case needs an opaque JSON catch-all because there is nowhere to put
    one. A database sibling proves the same against a migrated database.

    The scan is checked against the rest of the schema rather than trusted. The
    same predicate finds JSONB columns on other tables in the same metadata, so
    a green result here is the absence of a JSON column and not the absence of a
    working detector.
    """
    reached: list[str] = []
    offenders: list[str] = []
    for name in CAMPAIGN_TABLES:
        table = _table(name)
        reached.append(name)
        assert len(table.c) > 0
        offenders.extend(f"{name}.{column.name}" for column in table.c if _is_json(column.type))

    assert offenders == []
    assert reached == list(CAMPAIGN_TABLES)
    assert len(reached) == 11

    elsewhere = [
        f"{table.name}.{column.name}"
        for table in METADATA.tables.values()
        if table.name not in CAMPAIGN_TABLES
        for column in table.c
        if _is_json(column.type)
    ]
    assert elsewhere, "the JSON detector found nothing anywhere, so it proves nothing here"


# --- 3. Partition discipline -------------------------------------------------


def test_only_the_global_seeded_vocabularies_stand_outside_the_partition() -> None:
    """The split is asserted by name in both directions.

    One direction alone is half a guard. Asserting only that the taxonomies lack
    `principal_id` would stay green if a new Principal-bearing table were added
    without one; asserting only that the other 8 carry it would stay green if
    `principal_id` were grafted onto a global vocabulary, which would turn a
    shared lookup into per-Principal data that no seeding path writes.
    """
    partitioned = {name for name in CAMPAIGN_TABLES if "principal_id" in _table(name).c}
    unpartitioned = {name for name in CAMPAIGN_TABLES if "principal_id" not in _table(name).c}

    assert unpartitioned == set(GLOBAL_TAXONOMIES)
    assert partitioned == set(CAMPAIGN_TABLES) - GLOBAL_TAXONOMIES
    assert len(partitioned) == 8
    assert len(unpartitioned) == 3
    assert partitioned | unpartitioned == set(CAMPAIGN_TABLES)


# --- 4. Archive, end and supersede; no delete path declared ------------------


def test_the_delete_verb_rule_fires_on_a_delete_and_not_on_a_lifecycle_verb() -> None:
    """The rule the two tests below apply, checked before they apply it.

    A deny rule that matched nothing would make both of them green for the wrong
    reason, and word matching is exactly where that goes wrong: a substring rule
    would read `drop` out of `dropped_at` but also `remove` out of nothing and
    `delete` out of nothing, while missing `DeleteEntityName` if it only ever
    looked at snake_case.
    """
    assert _destroys("delete_entity_name")
    assert _destroys("DeleteEntityName")
    assert _destroys("purge_assertions")
    assert _destroys("RemoveEntityAddress")
    assert not _destroys("retire_entity_name")
    assert not _destroys("supersede_person_organization_affiliation")
    assert not _destroys("records_bound_to_entity_outside")
    assert not _destroys("redirect_entity")


def test_the_published_command_surface_declares_no_way_to_delete_a_record() -> None:
    """Every payload a caller can send opens a row or closes one; none erases one.

    The population is derived from the `command` annotation of each service
    method rather than by filtering `__all__` on the allowed prefixes. That
    filter is how `test_the_command_surface_is_exactly_these_seventeen` finds
    the commands, and it is the right derivation for the question that test
    asks -- but it would let a hypothetical `DeleteEntityName` through if the
    prefix list ever grew, because a name it stops matching is a name it stops
    checking. Deriving from what the methods accept has no such blind spot: a
    payload with no method to receive it is not a command anybody can send.
    """
    commands = _published_commands()
    assert len(commands) == 17

    assert [name for name in commands if _destroys(name)] == []
    for name in commands:
        assert name.startswith(ALLOWED_COMMAND_PREFIXES), name

    # The exported surface and the module's own public attributes, so a delete
    # payload that exists but is not yet wired to a method is caught too.
    exported = list(service_module.__all__)
    assert len(exported) >= len(commands)
    assert [name for name in exported if _destroys(name)] == []
    public = [name for name in dir(service_module) if not name.startswith("_")]
    assert [name for name in public if _destroys(name)] == []

    methods = _public_methods(EntityRecordFamilyService)
    assert len(methods) == 17
    assert [name for name in methods if _destroys(name)] == []


def test_no_repository_method_for_these_families_declares_a_delete_path() -> None:
    """`EntitiesRepository` grants no caller a way to make a row stop existing.

    The existing suite proves supersession is non-destructive by performing one
    and finding the predecessor still there. This is the different, weaker, and
    independently useful claim that there is no destructive call to perform:
    absence in the port is what stops a future repository from acquiring one
    quietly, because a method nobody declared is a method nobody implements.
    """
    declared = _public_methods(EntitiesRepository)
    assert len(declared) >= 100

    family_named = {
        name
        for name in declared
        if _words(name)
        & {
            "assertion",
            "assertions",
            "evidence",
            "names",
            "addresses",
            "affiliation",
            "affiliations",
            "participation",
            "participations",
            "profile",
        }
    }
    assert len(family_named) >= 10
    assert "record_entity_name" in declared
    assert "supersede_person_organization_affiliation" in declared

    assert [name for name in declared if _destroys(name)] == []


# --- 5. Optimistic versions on every path that can race ----------------------


def test_every_transition_on_these_families_is_guarded_by_an_expected_version() -> None:
    """Concurrent reconciliation is the case these families exist to survive.

    Two records of the same fact arriving from two reconciliations at once is
    ordinary, not exotic, and the only thing standing between that and a lost
    correction is that each transition states the version it believes it is
    replacing. Both populations are derived rather than listed -- the port side
    from `inspect.signature`, the command side from `dataclasses.fields` -- and
    both are asserted by size, so a seventh family that skipped the guard would
    change a size rather than slip past a list nobody updated.
    """
    record_ids = _record_id_field_names()
    assert len(record_ids) == 6

    port = {}
    for name, method in _public_methods(EntitiesRepository).items():
        if not name.startswith(("supersede_", "retire_", "revise_")):
            continue
        parameters = inspect.signature(method).parameters
        if not record_ids & set(parameters):
            continue
        port[name] = parameters

    assert set(port) == {
        "supersede_entity_name",
        "retire_entity_name",
        "revise_organization_profile",
        "supersede_entity_address",
        "retire_entity_address",
        "supersede_communication_method",
        "retire_communication_method",
        "supersede_project_participation",
        "retire_project_participation",
        "supersede_person_organization_affiliation",
        "retire_person_organization_affiliation",
    }
    assert len(port) == 11

    for name, parameters in port.items():
        guard = parameters.get("expected_version")
        assert guard is not None, f"{name} declares no expected_version"
        assert guard.default is inspect.Parameter.empty, f"{name} makes its guard optional"
        assert guard.kind is inspect.Parameter.KEYWORD_ONLY, f"{name} takes its guard positionally"

    guarded = {
        name: command
        for name, command in _published_commands().items()
        if name.startswith(("Correct", "Retire", "Revise"))
    }
    assert len(guarded) == 11
    for name, command in guarded.items():
        assert "expected_version" in {declared.name for declared in fields(command)}, name


# --- 6. Merge enumerates every family; split inverts every one ---------------


def test_merge_and_split_enumerate_every_entity_bound_record_family() -> None:
    """Each of the 6 is a family the correction plane knows how to move.

    A family missing from `IdentityEffectFamily` would have its rows left
    pointing at a merged-away entity with nothing recording that they were; a
    family missing from `MergeFamily` would not be moved at all; a family with
    no disposition would reach the ambiguity settlement with no legal answer,
    which is a merge that cannot be completed rather than one that completes
    wrongly.
    """
    families = [member.value for member in EntityRecordFamily]
    assert len(families) == 6

    effect_values = {member.value for member in IdentityEffectFamily}
    merge_values = {member.value for member in MergeFamily}
    for family in families:
        assert family in effect_values, family
        assert family in merge_values, family
        assert dispositions_for(IdentityEffectFamily(family)), family


def test_the_assertion_plane_is_a_recorded_exclusion_from_the_merge_surface() -> None:
    """The assertion families are absent from `MergeFamily` on purpose.

    The reason is recorded in the campaign record: 5 of the 6 `target_*` columns
    on `entity_assertions` reference a sibling row by a stable surrogate key
    that a merge never rewrites, and the 6th rides `ON UPDATE CASCADE`, so an
    assertion follows its subject without the merge having to carry it. That is
    a decision, not an omission.

    Asserted as the decision rather than as the absence, so that adding an
    assertion family to `MergeFamily` reddens here and forces the campaign
    record to be updated with the reason it was added. A reasoned exclusion that
    nothing checks decays into an exclusion nobody remembers making.
    """
    assertion_words = {"assertion", "assertions", "evidence"}
    for member in MergeFamily:
        assert not _words(member.name) & assertion_words, member.name
        assert not _words(member.value) & assertion_words, member.value

    assert len(list(MergeFamily)) >= len(list(EntityRecordFamily))
    # And the families that *are* carried are still carried, so this is an
    # assertion about the assertion plane rather than about an empty enum.
    assert MergeFamily.NAME.value == EntityRecordFamily.NAME.value


# --- 7. Merge and split stay operator-only -----------------------------------


def test_merge_and_split_stay_reserved_to_the_operator() -> None:
    """Derived the way `tests/contract/test_capabilities_and_readiness.py` derives it.

    That module asserts the reserved set exactly and checks that no capture,
    review or memory name joined it. The claim added here is the neighbouring
    one it does not make: within `entities.*` itself, the reserved set is the
    merge and split preview/apply pair and nothing else, so the ordinary
    entity-authoring surface cannot acquire an operator gate -- or lose one --
    without reddening.
    """
    manifest = build_capability_manifest(implemented=frozenset(Capability), limits=LIMITS)
    reserved = {status.name for status in manifest.capabilities if status.operator_only}

    entity_capabilities = {
        capability for capability in Capability if capability.value.startswith("entities.")
    }
    assert len(entity_capabilities) >= 30

    assert reserved >= IDENTITY_CORRECTION_CAPABILITIES
    assert reserved & entity_capabilities == IDENTITY_CORRECTION_CAPABILITIES
    for capability in IDENTITY_CORRECTION_CAPABILITIES:
        assert is_operator_only(capability)
    for capability in entity_capabilities - IDENTITY_CORRECTION_CAPABILITIES:
        assert not is_operator_only(capability), capability


# --- 8. The ceiling on the assertion plane's free text -----------------------


def _bounded_check(table_name: str, column: str) -> CheckConstraint:
    """The CHECK on `table_name` that bounds `column`'s length."""
    matches = [
        constraint
        for constraint in _table(table_name).constraints
        if isinstance(constraint, CheckConstraint)
        and f"length({column})" in str(constraint.sqltext)
        and "<=" in str(constraint.sqltext)
    ]
    assert len(matches) == 1, f"{table_name}.{column} has {len(matches)} length bounds"
    return matches[0]


def test_the_assertion_planes_free_text_carries_an_explicit_character_ceiling() -> None:
    """`rationale` and `source_locator` are bounded, in the schema and the domain.

    Both halves matter and neither substitutes for the other. The CHECK is what
    a direct writer meets; the dataclass is what every caller through the domain
    meets, and it meets it before a connection is ever opened. A ceiling stated
    in only one of the two is a ceiling one path does not have.

    This is the *only* free-text ceiling this module asserts, because it is the
    only one that exists. The module docstring names the columns that carry no
    upper bound; that gap is disclosed rather than papered over, and closing it
    needs a migration.
    """
    assert ENTITY_CHANGE_REASON_LIMIT == 500

    ceiling = str(ENTITY_CHANGE_REASON_LIMIT)
    assert ceiling in str(_bounded_check("entity_assertions", "rationale").sqltext)
    assert ceiling in str(_bounded_check("entity_assertion_evidence", "source_locator").sqltext)

    principal_id = issue_identifier(IdKind.PRINCIPAL)
    assertion_id = issue_identifier(IdKind.ENTITY_ASSERTION)
    target = issue_identifier(IdKind.ENTITY_NAME)

    def _assertion(rationale: str) -> EntityAssertion:
        return EntityAssertion(
            assertion_id=assertion_id,
            principal_id=principal_id,
            assertion_status=AssertionStatus.VERIFIED,
            asserted_by=MutationAuthority.USER_CONFIRMED_ASSERTION,
            created_at=WHEN,
            target_entity_name_id=target,
            rationale=rationale,
        )

    assert _assertion("r" * ENTITY_CHANGE_REASON_LIMIT).rationale is not None
    with pytest.raises(ValueError, match="rationale"):
        _assertion("r" * (ENTITY_CHANGE_REASON_LIMIT + 1))

    def _evidence(locator: str) -> EntityAssertionEvidence:
        return EntityAssertionEvidence(
            evidence_id=issue_identifier(IdKind.ENTITY_ASSERTION_EVIDENCE),
            principal_id=principal_id,
            assertion_id=assertion_id,
            role=EvidenceRole.DIRECT,
            created_at=WHEN,
            entity_observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
            source_locator=locator,
        )

    assert _evidence("l" * ENTITY_CHANGE_REASON_LIMIT).source_locator is not None
    with pytest.raises(ValueError, match="source locator"):
        _evidence("l" * (ENTITY_CHANGE_REASON_LIMIT + 1))
