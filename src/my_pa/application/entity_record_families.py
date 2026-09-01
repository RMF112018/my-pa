"""The six Entity-bound record families' write path: what the caller states, and what it may not.

One service over the six record families RI-ENT-WP-02 through RI-ENT-WP-06
added and RI-ENT-WP-08 gave a write path -- `entity_names`,
`entity_organization_profiles`, `entity_addresses`,
`entity_communication_methods`, `entity_project_participations` and
`entity_person_organization_affiliations` -- plus the optional
RI-ENT-WP-07 assertion an individual write may carry. It calls the
`EntitiesRepository` write block those work packages declared and nothing
else.

**This service is deliberately unwired.** No `Capability` names it, no MCP
tool, HTTP route or CLI command reaches it, and `ApplicationService` does not
hold it. Transport exposure is RI-ENT-WP-10/WP-11's, and WP-11 additionally
owns the capability and purpose CHECK migrations that would have to land
before any of this could be published. Declaring the service now is the same
deliberate half-step `contracts.ports` took when it declared the write block
abstract: the caller-facing shape is fixed and reviewable before anything can
invoke it.

**Principal scoping is absence, not validation.** Every method takes the
resolved `principal_id` as a keyword-only argument, supplied by the
composition root from `Authorization.principal.principal_id`, exactly as
`EntityDirectedService` takes it. No command dataclass in this module declares
`principal_id`, `version`, `state`, `superseded_by_*`, `retired_at` or
`updated_at`, so a payload naming one is refused by the constructor before any
of this runs. There is nothing here that reads such a field and decides to
ignore it, because a field that can be sent is a field a later change can
start honouring.

**Lifecycle: three verbs, and a correction is never an in-place rewrite.**
`record_*` mints an identifier and inserts. `correct_*` mints a *second*
identifier, writes the successor row, and only then supersedes the predecessor
under the caller's `expected_version` -- the order the port's own
`supersede_assertion` docstring fixes as the convention for its family, and
the order every `correct_*` below follows: the successor exists before any row
names it. `retire_*` retires under `expected_version`. So what a record said
before a correction survives the correction, which is the property the whole
temporal shape exists to keep.

**Atomicity, stated rather than claimed.** A correction is two statements, not
one. `SqlEntityRepository` takes the connection rather than opening one -- "the
caller owns the transaction, this class only issues statements on it" -- and
`SqlUnitOfWork.entities` hands out a repository bound to the open transaction's
connection, so a correction issued through a unit of work commits or rolls back
whole. This service does not open, commit or roll back anything, and it holds
no compensating write: called with a repository that is *not* inside a
transaction, a `record_*` that succeeds followed by a `supersede_*` that raises
leaves the successor row written and the predecessor still ACTIVE, and both
rows are then visible and correctable by their own identifiers. The guarantee
belongs to the caller's transaction, and this module will not describe it as
its own.

**`EntityOrganizationProfile` is the one asymmetry, and it is not hidden.** It
is a singleton -- one row per entity, `entity_id` both primary key and foreign
key -- with no `state` and no `superseded_by_*`, so it has nowhere to retire to
and nothing a supersession could name. It gets `record_organization_profile`
and `revise_organization_profile` and no retirement verb, because this module
declares no verb the port has none of. Its revision passes every mutable
column, including the two nullable ones, so a revision cannot silently carry
forward a jurisdiction or a registration identifier the caller believes it
cleared.

**Optimistic versions are the caller's, and are never re-read.**
`expected_version` is a required field on every correction and every
retirement. Nothing here reads the row first to discover its version -- a
service that did would guard against a value it had just fetched, which is no
guard at all. The repository's own classification is what surfaces:
`UnknownScopeError` when this Principal cannot reach the row (the same answer
an absent row gets, so the refusal discloses nothing about another partition)
and `StaleDirectedVersionError` when the row is reachable at a different
version. **Neither is translated here**, for the reason `EntityDirectedService`
does not translate them either: the classification into the public error family
happens at the transport edge in `application.service`, where
`_directed_translated` maps `UnknownScopeError` to `not_found` naming
`SUBJECT` and `StaleDirectedVersionError` to `conflict` naming
`EXPECTED_VERSION`. A second translation here would be a second place those
answers are decided, free to disagree with the first.

**Normalization is allowed; inference is not, and the line is exact.**
Computing a normalized key from a display value the caller stated is
normalization: the caller says what the value is, and the service says what
form two such values are compared in. Inferring a *different fact* -- a name
type, a taxonomy code, an organization, a structured address field, a status
-- is guessing, and nothing here does it. So this service computes
`EntityName.normalized_value` with `normalize_name`,
`EntityAddress.normalized_address_value` with `normalize_address` over
whichever structured fields the caller populated, and
`EntityCommunicationMethod.normalized_value` with
`normalize_communication_value` for the method type the caller stated -- and it
never splits `raw_value` into `line1`/`city`/`postal_code`, never decides from
a string's shape that it is an email, and never folds a display name into a
legal one.

**The four no-guess rules, each as a refusal a caller can reach:**

* **A legal name is stated, never promoted.** `RecordEntityName` and
  `CorrectEntityName` carry `name_type_code` as an explicitly optional field
  and `_stated_name_type` refuses `None`. There is no code path in this module
  that chooses a `NameTypeCode`, and in particular none that turns a display
  form into `NameTypeCode.LEGAL`; a legal name row exists only because a caller
  said `LEGAL`.
* **A nullable organization stays null.** `RecordAffiliation` and
  `CorrectAffiliation` pass `organization_entity_id` through untouched, and
  `_stated_identifier` refuses a present-but-blank one rather than reading it as
  "work out who". Nothing here creates an organization entity, selects one by
  name, or substitutes a placeholder to satisfy the foreign key RI-ENT-WP-05
  made nullable precisely so an independent consultant needs none.
* **A taxonomy code is stated or absent, never derived from text.**
  `RecordProjectParticipation` and `CorrectProjectParticipation` carry
  `role_code`/`role_text` and `discipline_code`/`discipline_text` as
  independent fields; `_stated_code` refuses a blank code, naming the taxonomy
  the caller should quote instead. A command carrying only `role_text` records
  `role_code=None` and keeps the text, which is the honest record of what was
  known.
* **Unknown stays unresolved.** No command field in this module defaults to a
  substantive code, and no method substitutes one for a value a caller left
  absent. Every closed vocabulary a caller must decide -- `address_type_code`,
  `method_type_code`, `usage_context_code`, `role_basis_code`,
  `stakeholder_side_code`, `stakeholder_class_code`,
  `relationship_status_code`, `organization_kind_code`,
  `legal_identity_status_code`, `affiliation_type_code`, `assertion_status` --
  is a field with no default on every command that writes it, so omitting one
  is refused by the constructor rather than filled in here. `name_type_code` is
  optional in the type and required in fact, which is the one place the two
  differ deliberately: it is the field the legal-name rule turns on, so its
  absence is answered by a refusal a caller can read and act on rather than by
  a `TypeError` from a constructor.
  `verification_status_code` is the single exception that keeps a default, and
  it defaults to
  `CommunicationVerificationStatusCode.UNRESOLVED`, which is that vocabulary's
  own name for "not yet known" and is the same default
  `EntityCommunicationMethod` itself declares -- an unknown recorded as
  unknown, never an affirmative value nobody stated.

**Assertions are optional and explicit.** A create or a correction may carry a
`StatedAssertion`, and when it does the service records an `EntityAssertion`
naming the row it has just written, plus one `EntityAssertionEvidence` row per
`StatedEvidence`. When it does not, no assertion row is written and no
`assertion_status` is invented. `assertion_status` is `AssertionStatus`, a set
of unordered epistemic categories; nothing here sorts, compares or combines
them, and `asserted_by` is a keyword-only `MutationAuthority` on the method --
absent from every command -- on `EntityDirectedService`'s own argument that a
payload able to name its own authority could name any of them.

**No idempotency key, and no mutation ledger row.** The port's write block for
these six families takes neither, unlike the directed writes, so this service
has no replay to consult and writes no `entity_mutation_events` row. Retrying a
`record_*` mints a fresh identifier and writes a second row; the active partial
uniques those tables carry are what refuse a genuine duplicate. Both are
RI-ENT-WP-08's stated shape rather than an omission here, and a transport that
publishes these methods will have to say what it does about a retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    AffiliationTypeCode,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    EntityAddress,
    EntityCommunicationMethod,
    EntityName,
    EntityOrganizationProfile,
    EntityProjectParticipation,
    LegalIdentityStatusCode,
    NameTypeCode,
    OrganizationKindCode,
    ParticipationStatusCode,
    PersonOrganizationAffiliation,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
    normalize_address,
    normalize_communication_value,
)
from my_pa.domain.relationship.governance import (
    DEFAULT_MUTATION_AUTHORITY,
    AssertionStatus,
    EntityAssertion,
    EntityAssertionEvidence,
    EvidenceRole,
    MutationAuthority,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "CorrectAffiliation",
    "CorrectCommunicationMethod",
    "CorrectEntityAddress",
    "CorrectEntityName",
    "CorrectProjectParticipation",
    "CorrectedFact",
    "EntityRecordFamily",
    "EntityRecordFamilyService",
    "RecordAffiliation",
    "RecordCommunicationMethod",
    "RecordEntityAddress",
    "RecordEntityName",
    "RecordOrganizationProfile",
    "RecordProjectParticipation",
    "RecordedFact",
    "RetireAffiliation",
    "RetireCommunicationMethod",
    "RetireEntityAddress",
    "RetireEntityName",
    "RetireProjectParticipation",
    "RetiredFact",
    "ReviseOrganizationProfile",
    "RevisedFact",
    "StatedAssertion",
    "StatedEvidence",
]


class EntityRecordFamily(StrEnum):
    """Which of the six record families one receipt is about.

    A receipt carries an opaque identifier, and an identifier alone does not
    say which table it names. Declared here rather than reusing
    `MutationRecordFamily`, whose members are the entity, identifier, alias,
    assignment, relationship and observation families the mutation ledger
    covers -- a different set of tables answering a different question, and one
    enum spanning both would make widening either a silent widening of the
    other, which is the argument `MutationRecordFamily`'s own docstring already
    makes against a shared vocabulary.

    Categorical and unordered. No member ranks, grades, or scores anything.
    """

    NAME = "name"
    ORGANIZATION_PROFILE = "organization_profile"
    ADDRESS = "address"
    COMMUNICATION_METHOD = "communication_method"
    PROJECT_PARTICIPATION = "project_participation"
    PERSON_ORGANIZATION_AFFILIATION = "person_organization_affiliation"


# --- What a caller may attach to a fact it writes ---------------------------


@dataclass(frozen=True, slots=True)
class StatedEvidence:
    """One record a caller cites for or against the assertion it is making.

    Exactly one of `entity_observation_id`, `capture_span_id` and
    `knowledge_id` is expected; `EntityAssertionEvidence` refuses any other
    count, and this module does not restate that check.

    `role` is stated, never derived. `EvidenceRole.COUNTEREVIDENCE` is recorded
    as readily as `DIRECT`, and recording it changes no assertion's
    `assertion_status` -- a status is a claim its own writer makes, and nothing
    here recomputes one from the evidence that accumulates against it.
    """

    role: EvidenceRole
    entity_observation_id: str | None = None
    capture_span_id: str | None = None
    knowledge_id: str | None = None
    source_locator: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class StatedAssertion:
    """The optional fact-level claim a create or a correction may carry.

    Optional and explicit: a command that carries none writes no assertion row,
    and the service never manufactures one to describe a write it performed.

    No `asserted_by` field. That is `MutationAuthority`, and it is a keyword-only
    argument on every method here for the reason `EntityDirectedService` gives
    for its own `authority` parameter: a command able to name its own authority
    could name any of them, including the one that would claim a person
    confirmed what a rule produced.

    No `target_*` field either. The subject of the assertion is the row the
    service has just written, so a caller that could name a target could file a
    claim against a record it did not touch.
    """

    assertion_status: AssertionStatus
    predicate_code: str | None = None
    rationale: str | None = field(default=None, repr=False)
    observed_at: datetime | None = None
    verified_at: datetime | None = None
    evidence: tuple[StatedEvidence, ...] = ()


# --- Commands: names --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordEntityName:
    """One typed name form to record.

    `normalized_value` is absent: the caller states the display form and the
    service computes the key two names are compared in. `name_type_code` is
    present but optional so that its absence is a refusal rather than a
    default -- see `_stated_name_type`.
    """

    entity_id: str
    display_value: str = field(repr=False)
    name_type_code: NameTypeCode | None = None
    is_preferred: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class CorrectEntityName:
    """A replacement name row for `entity_name_id`, and the supersession of it.

    The successor's full content is stated rather than read off the predecessor:
    this service performs no read, so a field the caller does not restate is a
    field that would otherwise have to be guessed. `entity_id` is the entity the
    successor belongs to; this service does not verify that the superseded row
    belongs to the same entity, and the limitation is recorded rather than
    implied -- both identifiers come from the caller, and both writes are
    Principal-scoped by the repository.
    """

    entity_name_id: str
    expected_version: int
    entity_id: str
    display_value: str = field(repr=False)
    name_type_code: NameTypeCode | None = None
    is_preferred: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class RetireEntityName:
    """One name row to withdraw from service, keeping the row and its history."""

    entity_name_id: str
    expected_version: int


# --- Commands: organization profile -----------------------------------------


@dataclass(frozen=True, slots=True)
class RecordOrganizationProfile:
    """The one profile row an organization entity holds.

    Both classification vocabularies are stated. Neither is inferred from the
    entity's name, its addresses, or its registration identifier: an
    organization whose legal identity is not established is recorded as
    `LegalIdentityStatusCode.UNRESOLVED` by a caller who says so, never by a
    service that could not tell.
    """

    entity_id: str
    organization_kind_code: OrganizationKindCode
    legal_identity_status_code: LegalIdentityStatusCode
    jurisdiction_code: str | None = None
    registration_identifier: str | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class ReviseOrganizationProfile:
    """A replacement classification for one profile, in place, under its version.

    Every mutable column is a field with no default, the two nullable ones
    included, so a revision states what the jurisdiction and the registration
    identifier now are -- including that they are now nothing. A revision that
    could omit them would silently preserve values the caller believes it
    cleared.
    """

    entity_id: str
    expected_version: int
    organization_kind_code: OrganizationKindCode
    legal_identity_status_code: LegalIdentityStatusCode
    jurisdiction_code: str | None
    registration_identifier: str | None


# --- Commands: addresses ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordEntityAddress:
    """One typed address to record.

    `raw_value` is the verbatim string a source gave and is always required.
    The structured fields are populated only where the caller already knows
    that structure; this service never splits `raw_value` to invent one.
    `normalized_address_value` is absent because the service computes it from
    exactly the fields that are present.
    """

    entity_id: str
    address_type_code: AddressTypeCode
    raw_value: str = field(repr=False)
    line1: str | None = field(default=None, repr=False)
    line2: str | None = field(default=None, repr=False)
    city: str | None = field(default=None, repr=False)
    region: str | None = field(default=None, repr=False)
    postal_code: str | None = field(default=None, repr=False)
    country: str | None = None
    label: str | None = None
    is_preferred: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class CorrectEntityAddress:
    """A replacement address row for `entity_address_id`, and the supersession of it."""

    entity_address_id: str
    expected_version: int
    entity_id: str
    address_type_code: AddressTypeCode
    raw_value: str = field(repr=False)
    line1: str | None = field(default=None, repr=False)
    line2: str | None = field(default=None, repr=False)
    city: str | None = field(default=None, repr=False)
    region: str | None = field(default=None, repr=False)
    postal_code: str | None = field(default=None, repr=False)
    country: str | None = None
    label: str | None = None
    is_preferred: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class RetireEntityAddress:
    """One address row to withdraw from service, releasing any preferred slot."""

    entity_address_id: str
    expected_version: int


# --- Commands: communication methods ----------------------------------------


@dataclass(frozen=True, slots=True)
class RecordCommunicationMethod:
    """One contact channel to record.

    `method_type_code` is stated by the caller and the value is then normalized
    *for* that stated type. Nothing here reads a string's shape and concludes it
    is an email or a phone number, which is the narrower thing
    `normalize_communication_value` exists to do.

    `verification_status_code` defaults to the vocabulary's own `UNRESOLVED`
    member, which is what "not yet known" is called here -- never an
    affirmative value a caller did not state.
    """

    entity_id: str
    method_type_code: CommunicationMethodTypeCode
    usage_context_code: CommunicationUsageContextCode
    display_value: str = field(repr=False)
    verification_status_code: CommunicationVerificationStatusCode = (
        CommunicationVerificationStatusCode.UNRESOLVED
    )
    is_preferred: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    linked_external_identifier_id: str | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class CorrectCommunicationMethod:
    """A replacement channel row for `communication_method_id`, and its supersession."""

    communication_method_id: str
    expected_version: int
    entity_id: str
    method_type_code: CommunicationMethodTypeCode
    usage_context_code: CommunicationUsageContextCode
    display_value: str = field(repr=False)
    verification_status_code: CommunicationVerificationStatusCode = (
        CommunicationVerificationStatusCode.UNRESOLVED
    )
    is_preferred: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    linked_external_identifier_id: str | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class RetireCommunicationMethod:
    """One contact channel to withdraw from service."""

    communication_method_id: str
    expected_version: int


# --- Commands: project participations ---------------------------------------


@dataclass(frozen=True, slots=True)
class RecordProjectParticipation:
    """One participant's participation on one project.

    `role_code` and `role_text` are independent, and so are `discipline_code`
    and `discipline_text`. A caller that knows only the words a source used
    supplies the text and leaves the code absent; this service does not map one
    onto the other in either direction.
    """

    project_entity_id: str
    participant_entity_id: str
    project_display_name: str = field(repr=False)
    role_basis_code: RoleBasisCode
    stakeholder_side_code: StakeholderSideCode
    stakeholder_class_code: StakeholderClassCode
    relationship_status_code: ParticipationStatusCode
    role_code: str | None = None
    role_text: str | None = field(default=None, repr=False)
    discipline_code: str | None = None
    discipline_text: str | None = field(default=None, repr=False)
    scope_text: str | None = field(default=None, repr=False)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class CorrectProjectParticipation:
    """A replacement participation row for `participation_id`, and its supersession."""

    participation_id: str
    expected_version: int
    project_entity_id: str
    participant_entity_id: str
    project_display_name: str = field(repr=False)
    role_basis_code: RoleBasisCode
    stakeholder_side_code: StakeholderSideCode
    stakeholder_class_code: StakeholderClassCode
    relationship_status_code: ParticipationStatusCode
    role_code: str | None = None
    role_text: str | None = field(default=None, repr=False)
    discipline_code: str | None = None
    discipline_text: str | None = field(default=None, repr=False)
    scope_text: str | None = field(default=None, repr=False)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class RetireProjectParticipation:
    """One participation to withdraw from service."""

    participation_id: str
    expected_version: int


# --- Commands: person-organization affiliations -----------------------------


@dataclass(frozen=True, slots=True)
class RecordAffiliation:
    """One person's affiliation with an organization, or with none.

    `organization_entity_id` is genuinely optional and `None` is a complete
    answer: RI-ENT-WP-05 made the column nullable so an independent consultant
    needs no placeholder organization. A caller that does not know which
    organization a person is affiliated with leaves it absent and this service
    records that; it never creates, selects, or substitutes an organization to
    fill the foreign key.
    """

    person_entity_id: str
    affiliation_type_code: AffiliationTypeCode
    organization_entity_id: str | None = None
    job_title: str | None = field(default=None, repr=False)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class CorrectAffiliation:
    """A replacement affiliation row for `affiliation_id`, and the supersession of it.

    `organization_entity_id` is a field with no default here, unlike on
    `RecordAffiliation`, on `ReviseOrganizationProfile`'s own argument: a
    correction states what the affiliation now says, and a correction that could
    omit the organization would leave the caller unable to tell "unchanged" from
    "cleared" when neither this service nor the repository reads the old row.
    """

    affiliation_id: str
    expected_version: int
    person_entity_id: str
    affiliation_type_code: AffiliationTypeCode
    organization_entity_id: str | None
    job_title: str | None = field(default=None, repr=False)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    assertion: StatedAssertion | None = None


@dataclass(frozen=True, slots=True)
class RetireAffiliation:
    """One affiliation to withdraw from service.

    `effective_to` is written only when supplied. Retirement already releases
    the open-ended slot through `state`; *when* an affiliation ended is a
    separate fact the caller states or leaves unstated, never one this service
    invents.
    """

    affiliation_id: str
    expected_version: int
    effective_to: datetime | None = None


# --- Receipts ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordedFact:
    """What one create wrote, without the value it recorded.

    No display value, no normalized value and no address. A receipt
    acknowledges that a record is durable; one that echoed the fact would put a
    name, an address or a phone number on a second surface for no gain -- the
    posture `ObservationAdmission` already takes for the observation plane.
    """

    family: EntityRecordFamily
    record_id: str
    recorded_at: datetime
    assertion_id: str | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CorrectedFact:
    """What one correction wrote, and which row it superseded.

    Two identifiers, because a correction is two rows: `record_id` is the
    successor this call minted and wrote, and `superseded_record_id` is the
    predecessor it then marked SUPERSEDED. Both are the caller's to read back;
    neither row was deleted or blanked.
    """

    family: EntityRecordFamily
    record_id: str
    superseded_record_id: str
    recorded_at: datetime
    assertion_id: str | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetiredFact:
    """What one retirement withdrew. The row and its history survive it."""

    family: EntityRecordFamily
    record_id: str
    retired_at: datetime


@dataclass(frozen=True, slots=True)
class RevisedFact:
    """What one in-place revision replaced.

    The organization profile's own receipt, and deliberately not a
    `CorrectedFact`: there is no superseded row to name, because this is the one
    family corrected in place. A receipt that carried a null
    `superseded_record_id` would describe a supersession that did not happen.
    """

    family: EntityRecordFamily
    record_id: str
    revised_at: datetime


# --- The stated-or-refused helpers ------------------------------------------


def _stated_name_type(value: NameTypeCode | None) -> NameTypeCode:
    """The name type the caller stated, or a refusal naming what to supply.

    The whole of the "never infer a legal name" rule on the write side. There is
    no branch here that picks a `NameTypeCode`, and none anywhere else in this
    module: a `LEGAL` row exists because a caller said `LEGAL`, and a display
    form is never promoted into one by a service that had to choose something.
    """
    if value is None:
        raise InvalidRequestError(SafeDetail.NAME)
    return value


def _stated_code(value: str | None, detail: SafeDetail) -> str | None:
    """A taxonomy code the caller stated, absent, or a refusal -- never derived.

    A blank code is refused rather than read as "work it out from the text
    beside it". A caller that knows only the words a source used leaves the code
    absent and keeps the text; a caller that knows the code quotes it from
    `entity_role_types`/`entity_discipline_types`. This service maps neither
    onto the other.
    """
    if value is None:
        return None
    if not value.strip():
        raise InvalidRequestError(detail)
    return value


def _stated_identifier(value: str | None) -> str | None:
    """An entity identifier the caller stated, absent, or a refusal.

    `None` is a complete answer and is passed through untouched. A blank string
    is refused rather than read as a request to find the entity that belongs
    there: nothing here creates an organization, selects one by name, or
    substitutes a placeholder to satisfy a nullable foreign key.
    """
    if value is None:
        return None
    if not value.strip():
        raise InvalidRequestError(SafeDetail.ENTITY_ID)
    return value


def _normalized_name(display_value: str) -> str:
    """`display_value` as the form two names are compared in.

    Normalization, not inference: the caller states what the name is and this
    computes the key it matches on. A value that normalizes to nothing matchable
    is refused as the malformed request it is, rather than reaching the domain
    as an unclassified `ValueError`.
    """
    try:
        return normalize_name(display_value)
    except ValueError as error:
        raise InvalidRequestError(SafeDetail.DISPLAY_VALUE) from error


def _normalized_channel(method_type_code: CommunicationMethodTypeCode, display_value: str) -> str:
    """`display_value` as the canonical form of the *stated* method type."""
    try:
        return normalize_communication_value(method_type_code, display_value)
    except ValueError as error:
        raise InvalidRequestError(SafeDetail.DISPLAY_VALUE) from error


class EntityRecordFamilyService:
    """Write the six Entity-bound record families, and refuse to fill their gaps.

    Every method has one shape: refuse what the caller left for this service to
    decide, normalize the display form it did state, mint the identifier, build
    the domain record, call the port, and attach the assertion the command asked
    for. No rule the schema, the domain record or the repository already
    enforces is restated -- the active partial uniques live in the schema, the
    field invariants live in each domain class's `__post_init__`, and the
    version guard lives in the repository's guarded `UPDATE`, so a second copy
    here could not disagree with them.
    """

    # --- entity_names ------------------------------------------------------

    def record_name(
        self,
        repository: EntitiesRepository,
        command: RecordEntityName,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> RecordedFact:
        """Record one typed name form. Refuses a command that states no name type."""
        entity_name_id = issue_identifier(IdKind.ENTITY_NAME)
        repository.record_entity_name(
            principal_id,
            EntityName(
                entity_name_id=entity_name_id,
                entity_id=command.entity_id,
                principal_id=principal_id,
                name_type_code=_stated_name_type(command.name_type_code),
                display_value=command.display_value,
                normalized_value=_normalized_name(command.display_value),
                is_preferred=command.is_preferred,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
            ),
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_entity_name_id=entity_name_id,
        )
        return RecordedFact(
            family=EntityRecordFamily.NAME,
            record_id=entity_name_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def correct_name(
        self,
        repository: EntitiesRepository,
        command: CorrectEntityName,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> CorrectedFact:
        """Write the corrected name and supersede the row it replaces, in that order."""
        entity_name_id = issue_identifier(IdKind.ENTITY_NAME)
        repository.record_entity_name(
            principal_id,
            EntityName(
                entity_name_id=entity_name_id,
                entity_id=command.entity_id,
                principal_id=principal_id,
                name_type_code=_stated_name_type(command.name_type_code),
                display_value=command.display_value,
                normalized_value=_normalized_name(command.display_value),
                is_preferred=command.is_preferred,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
            ),
        )
        repository.supersede_entity_name(
            principal_id,
            entity_name_id=command.entity_name_id,
            superseded_by_entity_name_id=entity_name_id,
            expected_version=command.expected_version,
            at=at,
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_entity_name_id=entity_name_id,
        )
        return CorrectedFact(
            family=EntityRecordFamily.NAME,
            record_id=entity_name_id,
            superseded_record_id=command.entity_name_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def retire_name(
        self,
        repository: EntitiesRepository,
        command: RetireEntityName,
        *,
        principal_id: str,
        at: datetime,
    ) -> RetiredFact:
        """Retire one name under its expected version, releasing any preferred slot."""
        repository.retire_entity_name(
            principal_id,
            entity_name_id=command.entity_name_id,
            expected_version=command.expected_version,
            at=at,
        )
        return RetiredFact(
            family=EntityRecordFamily.NAME, record_id=command.entity_name_id, retired_at=at
        )

    # --- entity_organization_profiles --------------------------------------

    def record_organization_profile(
        self,
        repository: EntitiesRepository,
        command: RecordOrganizationProfile,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> RecordedFact:
        """Record the one profile row an organization entity holds.

        Both timestamps are stamped with `at` because this family's columns are
        the only ones on the plane that are `NOT NULL`; the five temporal
        families leave `updated_at` null on a create, since nothing has updated
        them yet.
        """
        repository.record_organization_profile(
            principal_id,
            EntityOrganizationProfile(
                entity_id=command.entity_id,
                principal_id=principal_id,
                organization_kind_code=command.organization_kind_code,
                legal_identity_status_code=command.legal_identity_status_code,
                jurisdiction_code=command.jurisdiction_code,
                registration_identifier=command.registration_identifier,
                created_at=at,
                updated_at=at,
            ),
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_organization_profile_entity_id=command.entity_id,
        )
        return RecordedFact(
            family=EntityRecordFamily.ORGANIZATION_PROFILE,
            record_id=command.entity_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def revise_organization_profile(
        self,
        repository: EntitiesRepository,
        command: ReviseOrganizationProfile,
        *,
        principal_id: str,
        at: datetime,
    ) -> RevisedFact:
        """Replace the profile's classification in place, under its version.

        The one family revised rather than superseded, and the one method here
        that returns a `RevisedFact`. Every mutable column is passed, the two
        nullable ones included, so a revision cannot silently carry forward a
        jurisdiction or a registration identifier the caller cleared.
        """
        repository.revise_organization_profile(
            principal_id,
            entity_id=command.entity_id,
            organization_kind_code=command.organization_kind_code,
            legal_identity_status_code=command.legal_identity_status_code,
            jurisdiction_code=command.jurisdiction_code,
            registration_identifier=command.registration_identifier,
            expected_version=command.expected_version,
            at=at,
        )
        return RevisedFact(
            family=EntityRecordFamily.ORGANIZATION_PROFILE,
            record_id=command.entity_id,
            revised_at=at,
        )

    # --- entity_addresses --------------------------------------------------

    def record_address(
        self,
        repository: EntitiesRepository,
        command: RecordEntityAddress,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> RecordedFact:
        """Record one typed address, normalizing whichever structure the caller stated."""
        entity_address_id = issue_identifier(IdKind.ENTITY_ADDRESS)
        repository.record_entity_address(
            principal_id, self._address(command, entity_address_id, principal_id)
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_entity_address_id=entity_address_id,
        )
        return RecordedFact(
            family=EntityRecordFamily.ADDRESS,
            record_id=entity_address_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def correct_address(
        self,
        repository: EntitiesRepository,
        command: CorrectEntityAddress,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> CorrectedFact:
        """Write the corrected address and supersede the row it replaces, in that order."""
        entity_address_id = issue_identifier(IdKind.ENTITY_ADDRESS)
        repository.record_entity_address(
            principal_id, self._address(command, entity_address_id, principal_id)
        )
        repository.supersede_entity_address(
            principal_id,
            entity_address_id=command.entity_address_id,
            superseded_by_entity_address_id=entity_address_id,
            expected_version=command.expected_version,
            at=at,
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_entity_address_id=entity_address_id,
        )
        return CorrectedFact(
            family=EntityRecordFamily.ADDRESS,
            record_id=entity_address_id,
            superseded_record_id=command.entity_address_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def retire_address(
        self,
        repository: EntitiesRepository,
        command: RetireEntityAddress,
        *,
        principal_id: str,
        at: datetime,
    ) -> RetiredFact:
        """Retire one address under its expected version."""
        repository.retire_entity_address(
            principal_id,
            entity_address_id=command.entity_address_id,
            expected_version=command.expected_version,
            at=at,
        )
        return RetiredFact(
            family=EntityRecordFamily.ADDRESS,
            record_id=command.entity_address_id,
            retired_at=at,
        )

    # --- entity_communication_methods --------------------------------------

    def record_communication_method(
        self,
        repository: EntitiesRepository,
        command: RecordCommunicationMethod,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> RecordedFact:
        """Record one contact channel, at the verification status the caller stated."""
        communication_method_id = issue_identifier(IdKind.ENTITY_COMMUNICATION_METHOD)
        repository.record_communication_method(
            principal_id, self._channel(command, communication_method_id, principal_id)
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_communication_method_id=communication_method_id,
        )
        return RecordedFact(
            family=EntityRecordFamily.COMMUNICATION_METHOD,
            record_id=communication_method_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def correct_communication_method(
        self,
        repository: EntitiesRepository,
        command: CorrectCommunicationMethod,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> CorrectedFact:
        """Write the corrected channel and supersede the row it replaces, in that order."""
        communication_method_id = issue_identifier(IdKind.ENTITY_COMMUNICATION_METHOD)
        repository.record_communication_method(
            principal_id, self._channel(command, communication_method_id, principal_id)
        )
        repository.supersede_communication_method(
            principal_id,
            communication_method_id=command.communication_method_id,
            superseded_by_communication_method_id=communication_method_id,
            expected_version=command.expected_version,
            at=at,
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_communication_method_id=communication_method_id,
        )
        return CorrectedFact(
            family=EntityRecordFamily.COMMUNICATION_METHOD,
            record_id=communication_method_id,
            superseded_record_id=command.communication_method_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def retire_communication_method(
        self,
        repository: EntitiesRepository,
        command: RetireCommunicationMethod,
        *,
        principal_id: str,
        at: datetime,
    ) -> RetiredFact:
        """Retire one contact channel under its expected version."""
        repository.retire_communication_method(
            principal_id,
            communication_method_id=command.communication_method_id,
            expected_version=command.expected_version,
            at=at,
        )
        return RetiredFact(
            family=EntityRecordFamily.COMMUNICATION_METHOD,
            record_id=command.communication_method_id,
            retired_at=at,
        )

    # --- entity_project_participations -------------------------------------

    def record_project_participation(
        self,
        repository: EntitiesRepository,
        command: RecordProjectParticipation,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> RecordedFact:
        """Record one participation. Refuses a blank taxonomy code rather than deriving one."""
        participation_id = issue_identifier(IdKind.ENTITY_PROJECT_PARTICIPATION)
        repository.record_project_participation(
            principal_id, self._participation(command, participation_id, principal_id)
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_participation_id=participation_id,
        )
        return RecordedFact(
            family=EntityRecordFamily.PROJECT_PARTICIPATION,
            record_id=participation_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def correct_project_participation(
        self,
        repository: EntitiesRepository,
        command: CorrectProjectParticipation,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> CorrectedFact:
        """Write the corrected participation and supersede the row it replaces."""
        participation_id = issue_identifier(IdKind.ENTITY_PROJECT_PARTICIPATION)
        repository.record_project_participation(
            principal_id, self._participation(command, participation_id, principal_id)
        )
        repository.supersede_project_participation(
            principal_id,
            participation_id=command.participation_id,
            superseded_by_participation_id=participation_id,
            expected_version=command.expected_version,
            at=at,
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_participation_id=participation_id,
        )
        return CorrectedFact(
            family=EntityRecordFamily.PROJECT_PARTICIPATION,
            record_id=participation_id,
            superseded_record_id=command.participation_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def retire_project_participation(
        self,
        repository: EntitiesRepository,
        command: RetireProjectParticipation,
        *,
        principal_id: str,
        at: datetime,
    ) -> RetiredFact:
        """Retire one participation under its expected version."""
        repository.retire_project_participation(
            principal_id,
            participation_id=command.participation_id,
            expected_version=command.expected_version,
            at=at,
        )
        return RetiredFact(
            family=EntityRecordFamily.PROJECT_PARTICIPATION,
            record_id=command.participation_id,
            retired_at=at,
        )

    # --- entity_person_organization_affiliations ---------------------------

    def record_affiliation(
        self,
        repository: EntitiesRepository,
        command: RecordAffiliation,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> RecordedFact:
        """Record one affiliation. A null organization stays null."""
        affiliation_id = issue_identifier(IdKind.PERSON_ORGANIZATION_AFFILIATION)
        repository.record_person_organization_affiliation(
            principal_id, self._affiliation(command, affiliation_id, principal_id)
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_affiliation_id=affiliation_id,
        )
        return RecordedFact(
            family=EntityRecordFamily.PERSON_ORGANIZATION_AFFILIATION,
            record_id=affiliation_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def correct_affiliation(
        self,
        repository: EntitiesRepository,
        command: CorrectAffiliation,
        *,
        principal_id: str,
        at: datetime,
        authority: MutationAuthority = DEFAULT_MUTATION_AUTHORITY,
    ) -> CorrectedFact:
        """Write the corrected affiliation and supersede the row it replaces."""
        affiliation_id = issue_identifier(IdKind.PERSON_ORGANIZATION_AFFILIATION)
        repository.record_person_organization_affiliation(
            principal_id, self._affiliation(command, affiliation_id, principal_id)
        )
        repository.supersede_person_organization_affiliation(
            principal_id,
            affiliation_id=command.affiliation_id,
            superseded_by_affiliation_id=affiliation_id,
            expected_version=command.expected_version,
            at=at,
        )
        assertion_id, evidence_ids = self._attach(
            repository,
            command.assertion,
            principal_id=principal_id,
            authority=authority,
            at=at,
            target_affiliation_id=affiliation_id,
        )
        return CorrectedFact(
            family=EntityRecordFamily.PERSON_ORGANIZATION_AFFILIATION,
            record_id=affiliation_id,
            superseded_record_id=command.affiliation_id,
            recorded_at=at,
            assertion_id=assertion_id,
            evidence_ids=evidence_ids,
        )

    def retire_affiliation(
        self,
        repository: EntitiesRepository,
        command: RetireAffiliation,
        *,
        principal_id: str,
        at: datetime,
    ) -> RetiredFact:
        """Retire one affiliation, closing its window only when the caller said to."""
        repository.retire_person_organization_affiliation(
            principal_id,
            affiliation_id=command.affiliation_id,
            expected_version=command.expected_version,
            at=at,
            effective_to=command.effective_to,
        )
        return RetiredFact(
            family=EntityRecordFamily.PERSON_ORGANIZATION_AFFILIATION,
            record_id=command.affiliation_id,
            retired_at=at,
        )

    # --- Record builders shared by a family's create and its correction -----
    #
    # One builder per family whose create and correction write the identical
    # row shape, because the two commands differ only in the predecessor they
    # name and duplicating the construction is duplicating the place a field
    # could be forgotten. `entity_names` has no builder: its two commands are
    # the two shortest, and inlining them keeps `_stated_name_type` visible at
    # the call site where the refusal it makes is the point.

    @staticmethod
    def _address(
        command: RecordEntityAddress | CorrectEntityAddress,
        entity_address_id: str,
        principal_id: str,
    ) -> EntityAddress:
        """One address row, with the normalized key computed from the stated structure."""
        return EntityAddress(
            entity_address_id=entity_address_id,
            entity_id=command.entity_id,
            principal_id=principal_id,
            address_type_code=command.address_type_code,
            raw_value=command.raw_value,
            normalized_address_value=normalize_address(
                line1=command.line1,
                line2=command.line2,
                city=command.city,
                region=command.region,
                postal_code=command.postal_code,
                country=command.country,
                raw_value=command.raw_value,
            ),
            line1=command.line1,
            line2=command.line2,
            city=command.city,
            region=command.region,
            postal_code=command.postal_code,
            country=command.country,
            label=command.label,
            is_preferred=command.is_preferred,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
        )

    @staticmethod
    def _channel(
        command: RecordCommunicationMethod | CorrectCommunicationMethod,
        communication_method_id: str,
        principal_id: str,
    ) -> EntityCommunicationMethod:
        """One contact channel, normalized for the method type the caller stated."""
        return EntityCommunicationMethod(
            communication_method_id=communication_method_id,
            entity_id=command.entity_id,
            principal_id=principal_id,
            method_type_code=command.method_type_code,
            usage_context_code=command.usage_context_code,
            normalized_value=_normalized_channel(command.method_type_code, command.display_value),
            display_value=command.display_value,
            verification_status_code=command.verification_status_code,
            is_preferred=command.is_preferred,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            linked_external_identifier_id=command.linked_external_identifier_id,
        )

    @staticmethod
    def _participation(
        command: RecordProjectParticipation | CorrectProjectParticipation,
        participation_id: str,
        principal_id: str,
    ) -> EntityProjectParticipation:
        """One participation row, with codes stated or absent and never derived from text."""
        return EntityProjectParticipation(
            participation_id=participation_id,
            principal_id=principal_id,
            project_entity_id=command.project_entity_id,
            participant_entity_id=command.participant_entity_id,
            project_display_name=command.project_display_name,
            role_basis_code=command.role_basis_code,
            stakeholder_side_code=command.stakeholder_side_code,
            stakeholder_class_code=command.stakeholder_class_code,
            relationship_status_code=command.relationship_status_code,
            role_code=_stated_code(command.role_code, SafeDetail.ROLE),
            role_text=command.role_text,
            discipline_code=_stated_code(command.discipline_code, SafeDetail.DISCIPLINE),
            discipline_text=command.discipline_text,
            scope_text=command.scope_text,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
        )

    @staticmethod
    def _affiliation(
        command: RecordAffiliation | CorrectAffiliation,
        affiliation_id: str,
        principal_id: str,
    ) -> PersonOrganizationAffiliation:
        """One affiliation row, with a null organization left null."""
        return PersonOrganizationAffiliation(
            affiliation_id=affiliation_id,
            principal_id=principal_id,
            person_entity_id=command.person_entity_id,
            affiliation_type_code=command.affiliation_type_code,
            organization_entity_id=_stated_identifier(command.organization_entity_id),
            job_title=command.job_title,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
        )

    # --- The optional assertion --------------------------------------------

    @staticmethod
    def _attach(
        repository: EntitiesRepository,
        stated: StatedAssertion | None,
        *,
        principal_id: str,
        authority: MutationAuthority,
        at: datetime,
        target_entity_name_id: str | None = None,
        target_entity_address_id: str | None = None,
        target_communication_method_id: str | None = None,
        target_participation_id: str | None = None,
        target_affiliation_id: str | None = None,
        target_organization_profile_entity_id: str | None = None,
    ) -> tuple[str | None, tuple[str, ...]]:
        """Record the assertion the command carried, or write nothing at all.

        `None` in, nothing out: a write whose command stated no assertion leaves
        `entity_assertions` untouched, rather than filing a claim describing
        what this service just did. The caller's `assertion_status` is written
        exactly as given -- nothing here derives one from the evidence cited,
        from the target row, or from the absence of either -- and `asserted_by`
        is the method's own `authority`, which no command can reach.

        The target is the row this call has just written, and exactly one of the
        six keywords is non-`None` at every call site. `EntityAssertion` refuses
        any other count, and that refusal is not restated here.
        """
        if stated is None:
            return None, ()
        assertion_id = issue_identifier(IdKind.ENTITY_ASSERTION)
        repository.record_assertion(
            principal_id,
            EntityAssertion(
                assertion_id=assertion_id,
                principal_id=principal_id,
                assertion_status=stated.assertion_status,
                asserted_by=authority,
                created_at=at,
                target_entity_name_id=target_entity_name_id,
                target_entity_address_id=target_entity_address_id,
                target_communication_method_id=target_communication_method_id,
                target_participation_id=target_participation_id,
                target_affiliation_id=target_affiliation_id,
                target_organization_profile_entity_id=target_organization_profile_entity_id,
                predicate_code=stated.predicate_code,
                rationale=stated.rationale,
                observed_at=stated.observed_at,
                verified_at=stated.verified_at,
            ),
        )
        evidence_ids: list[str] = []
        for cited in stated.evidence:
            evidence_id = issue_identifier(IdKind.ENTITY_ASSERTION_EVIDENCE)
            repository.record_assertion_evidence(
                principal_id,
                EntityAssertionEvidence(
                    evidence_id=evidence_id,
                    principal_id=principal_id,
                    assertion_id=assertion_id,
                    role=cited.role,
                    created_at=at,
                    entity_observation_id=cited.entity_observation_id,
                    capture_span_id=cited.capture_span_id,
                    knowledge_id=cited.knowledge_id,
                    source_locator=cited.source_locator,
                ),
            )
            evidence_ids.append(evidence_id)
        return assertion_id, tuple(evidence_ids)
