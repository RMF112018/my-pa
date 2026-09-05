"""Opaque, server-issued identifiers.

Each identifier is a short type prefix joined to an opaque suffix by a single
underscore. `INV-PKL-005` requires that public identifiers not encode filesystem
paths, provider names, hosts, accounts, or database keys.

Validation here enforces *shape* only: the alphanumeric suffix rule rules out
path separators, dots, colons, and `@`, so a raw path or host cannot appear
verbatim. It cannot tell that `src_taxreturn2025` is semantic. Keeping suffixes
non-semantic is the issuer's responsibility, not something this module can check.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

__all__ = [
    "IdKind",
    "InvalidIdentifierError",
    "make_identifier",
    "parse_identifier",
    "validate_identifier",
]

_SUFFIX_PATTERN: Final = re.compile(r"\A[A-Za-z0-9]{8,64}\Z")
_MAX_LENGTH: Final = 72


class IdKind(StrEnum):
    """Identifier types defined by the v1 contract."""

    SOURCE = "src"
    SOURCE_OBJECT = "obj"
    VERSION = "ver"
    ENROLLMENT = "enr"
    #: The capture plane. `CAPTURE_VERSION` is deliberately not `VERSION`, which
    #: already denotes an observed *source object* version: one prefix for two
    #: unrelated things would make an audit row or a stored reference ambiguous
    #: about which plane it belongs to, and no later check could recover the
    #: distinction.
    CAPTURE = "cap"
    CAPTURE_VERSION = "capver"
    RECEIPT = "rcpt"
    SUBMISSION = "sub"
    #: A registered remote capture client (WP-10). Its own prefix rather than a
    #: reuse of `PRINCIPAL`, because a client is a credential bearer bound to a
    #: Principal and not a Principal: one prefix for both would make a stored
    #: reference ambiguous about which of the two it names, and the binding is
    #: exactly the distinction that must stay legible.
    CAPTURE_CLIENT = "cclt"
    #: The capture *processing* plane: what the pipeline derived from a stored
    #: version. Each is its own prefix rather than a shared `derived_` one,
    #: because an audit row or a stored reference has to say which record it
    #: names, and a single prefix would make a proposal and the span it cites
    #: indistinguishable to a reader of either.
    PROCESSING_TEXT = "ptext"
    STAGE_RESULT = "stage"
    SPAN = "span"
    PROPOSAL = "prop"
    CAPTURE_CLASSIFICATION = "ccls"
    CAPTURE_ENTITY_MENTION = "men"
    #: The capture *review and promotion* plane: what a reviewer decided and
    #: what the product now holds as canonical. Each is its own prefix, on the
    #: same argument the processing plane makes — a stored reference has to say
    #: which record it names, and `capture_proposals.accepted_record_id` in
    #: particular carries no foreign key, so its prefix is the only thing in the
    #: value that says what it points at.
    REVIEW_CASE = "rvw"
    REVIEW_DECISION = "rdec"
    ASSERTION = "asrt"
    CONTEXT_LINK = "clink"
    CONVERSATION = "conv"
    PERSON = "per"
    ORGANIZATION = "org"
    IDENTITY_OBSERVATION = "iobs"
    ALIAS = "alias"
    AFFILIATION = "aff"
    UNRESOLVED_MENTION = "umen"
    DUPLICATE_SET = "dups"
    IDENTITY_RESOLUTION = "ires"
    COVERAGE_SNAPSHOT = "cov"
    TIMELINE_ITEM = "tli"
    CONVERSATION_PARTICIPANT = "cpart"
    SOURCE_EVIDENCE = "sevd"
    SOURCE_OBSERVATION = "sobs"
    SOURCE_MEMBERSHIP = "smem"
    NATIVE_BRIDGE = "nbrg"
    APPLE_BRIDGE_CREDENTIAL = "abcred"
    NATIVE_ACCOUNT = "nacct"
    NATIVE_BUCKET = "nbkt"
    NATIVE_DISCOVERY = "ndisc"
    NATIVE_CONFIGURATION = "ncfg"
    NATIVE_RUN = "nrun"
    NATIVE_BUCKET_RUN = "nbrun"
    NATIVE_JOB = "njob"
    NATIVE_CHECKPOINT = "ncp"
    NATIVE_SIMULATION = "nsim"
    NATIVE_SIMULATION_RECEIPT = "nsimr"
    NATIVE_LIVE_GATE = "nlg"
    NATIVE_AUTHORITY = "nauth"
    OPERATION = "op"
    KNOWLEDGE = "kn"
    AUDIT = "audit"
    PRINCIPAL = "prn"
    CORRELATION = "corr"
    #: The R5 relationship / project *continuity* plane (WP-06). Each surface is
    #: its own prefix on the same argument the capture planes make — a stored
    #: reference or an audit row has to say which record it names, and a shared
    #: prefix would make a Situation and the Project that groups it, or a Trace
    #: and the relationship event it reconstructed, indistinguishable to a reader
    #: of either. `PROJECT_SITUATION` names the link row itself so that a
    #: reference to the binding is not confused with a reference to either end.
    SITUATION = "sit"
    FRAME = "frm"
    TRACE = "trc"
    PROJECT = "prj"
    PROJECT_SITUATION = "psit"
    RELATIONSHIP_EVENT = "revt"
    PULSE = "puls"
    #: The continuity objects WP-11 adds, and the one append-only record that
    #: carries their lifecycle. `CONTINUITY_DECISION` is deliberately not
    #: `REVIEW_DECISION`: `rdec` names a reviewer's disposition of one proposal
    #: and `cdec` names a decision the Principal holds and has to take, and a
    #: shared prefix would make a stored reference ambiguous about which of the
    #: two it points at — the same argument `CAPTURE_VERSION` makes against
    #: reusing `VERSION`. `LIFECYCLE_EVENT` is its own prefix rather than a reuse
    #: of `RELATIONSHIP_EVENT` for the same reason.
    COMMITMENT = "cmt"
    CONTINUITY_DECISION = "cdec"
    TASK = "tsk"
    LIFECYCLE_EVENT = "lce"
    #: WP-TM-01: the task-management foundation built natively on top of the
    #: minimal continuity `Task`. `TASK_RECURRENCE` names a durable series
    #: definition, not any one generated occurrence, and `TASK_HISTORY` names one
    #: append-only mutation receipt. Neither reuses `TASK` or `LIFECYCLE_EVENT`:
    #: a series is not a Task and outlives any one of its occurrences, and a
    #: mutation receipt records a request's outcome rather than a lifecycle
    #: transition, so the same argument `CAPTURE_VERSION` makes against reusing
    #: `VERSION` applies here — a stored reference has to say which of the three
    #: kinds it names.
    TASK_RECURRENCE = "trec"
    TASK_HISTORY = "thst"
    #: WP-TM-05: one append-only mutation receipt per Commitment write, the
    #: same shape `TASK_HISTORY` names for a Task. Its own prefix rather than a
    #: reuse of `TASK_HISTORY`, for the same reason `TASK_HISTORY` is not
    #: `LIFECYCLE_EVENT`: a stored reference has to say which of the two
    #: history rows it names.
    COMMITMENT_HISTORY = "cmthst"
    #: WP-TM-04: bulk task operations. `BULK_OPERATION` names a two-phase
    #: operation (preview and confirm) that applies multiple task mutations
    #: atomically. It is its own prefix rather than a reuse of `TASK` because
    #: a bulk operation is not a task and outlives any one of its constituent
    #: mutations.
    BULK_OPERATION = "bulk"
    #: The managed-document plane (WP-27): the one plane whose records name bytes
    #: this product wrote. Five prefixes rather than a reuse of the capture
    #: plane's four, on the argument `CAPTURE_VERSION` makes against reusing
    #: `VERSION`: a stored reference, a receipt and an audit row have to say which
    #: plane they belong to, and `rcpt`/`sub` already name a capture admission —
    #: one prefix for both would make a receipt ambiguous about whether the thing
    #: it acknowledges is a row of text or a file on disk. `MANAGED_LIFECYCLE` is
    #: its own prefix rather than a reuse of `LIFECYCLE_EVENT` for the same
    #: reason: that one names a continuity object's transition.
    #:
    #: A version suffix is also what the byte store derives a location from, so
    #: the shape rule these carry — 8-64 alphanumeric characters, no separator,
    #: no dot — is load-bearing rather than cosmetic.
    MANAGED_DOCUMENT = "mdoc"
    MANAGED_DOCUMENT_VERSION = "mdver"
    MANAGED_RECEIPT = "mdrcpt"
    MANAGED_SUBMISSION = "mdsub"
    MANAGED_LIFECYCLE = "mdlce"
    #: A prepared context package (`context.prepare`). Its own prefix rather than
    #: a reuse of `COVERAGE_SNAPSHOT` or `KNOWLEDGE`: a stored reference or an
    #: audit row has to say which record it names, and `cov` already names an
    #: extraction-plane coverage snapshot. `ctxm` names the retrieval contract's
    #: assembled package, which may cite capture and continuity evidence that
    #: a coverage snapshot cannot. Persistence of context runs is insert-only
    #: metadata: identifiers and digests, never the query or excerpt text.
    CONTEXT_MANIFEST = "ctxm"
    #: One append-only retrieval-preference event. Its own prefix rather than a
    #: reuse of `CONTEXT_MANIFEST`: a stored reference has to say whether it
    #: names a prepared package or a preference that ranked one, and `ctxm`
    #: already names the assembled packet.
    CONTEXT_PREFERENCE_EVENT = "cpref"
    #: The Intelligence Artifact / Report plane. Four prefixes rather than a
    #: reuse of capture `rcpt`/`cap`, managed `mdoc`, or context `ctxm`, on the
    #: same argument `CAPTURE_VERSION` makes against reusing `VERSION`: a stored
    #: reference, a receipt, and an audit row have to say which plane they name.
    #: `micr` is a cycle execution, not a producer attempt; `rrun` is one
    #: producer run, including a failure with no body; `rpt` is one immutable
    #: committed artifact; `rrc` is the admission receipt for a cycle begin,
    #: artifact commit, or run-state write.
    INTELLIGENCE_CYCLE_RUN = "micr"
    INTELLIGENCE_RUN = "rrun"
    INTELLIGENCE_ARTIFACT = "rpt"
    INTELLIGENCE_RECEIPT = "rrc"
    #: WP-RI-01: the relationship-intelligence entity plane. Each surface is its
    #: own prefix on the same argument the existing relationship-plane prefixes
    #: make — a stored reference or an audit row has to say which record it
    #: names. `ENTITY` names the generalized entity row (which may be a person,
    #: organization, program, project, work package, team, or location).
    #: `EXTERNAL_IDENTIFIER` names an entity's identity in an external namespace.
    #: `ASSIGNMENT` names a typed assignment of an entity to a scope entity —
    #: the spec's "role and affiliation" (section 12.5) and "project
    #: association" (section 12.6) under one record. `ENTITY_RELATIONSHIP`
    #: names a directed, typed relationship between two entities.
    #:
    #: `ENTITY_ALIAS` names one recorded alias of an entity, added by WP-RI-03
    #: because resolution matches on aliases (specification section 15.1) and a
    #: match has to be able to say which alias it matched.
    #:
    #: Three prefixes are *not* declared here, and their absence is the point:
    #: an observation, a proposal, and a context packet each belong to a later
    #: work package that has a table for them. A prefix is a contract this
    #: module promises is stable, and promising one before anything issues it is
    #: a promise about a record that does not exist.
    ENTITY = "ent"
    EXTERNAL_IDENTIFIER = "xid"
    ASSIGNMENT = "asn"
    ENTITY_RELATIONSHIP = "erel"
    ENTITY_ALIAS = "eals"
    #: RI-ENT-WP-02: one typed name form of an entity (`entity_names`), the
    #: audit's typed-name successor to `entity_aliases`. Its own prefix rather
    #: than a reuse of `ENTITY_ALIAS`, on the same argument every sibling
    #: surrogate ID here makes: a stored reference has to say which table it
    #: names, and `entity_names.superseded_by_entity_name_id` in particular
    #: would be ambiguous against an alias's own `superseded_by_alias_id` if
    #: both used one prefix. `entity_organization_profiles` needs none: its
    #: primary key is `entity_id` itself, already `IdKind.ENTITY`.
    ENTITY_NAME = "enam"
    #: RI-ENT-WP-03: one normalized address (`entity_addresses`) and one
    #: contact channel (`entity_communication_methods`) of an entity. Each is
    #: its own prefix on the same argument `ENTITY_NAME` makes against reusing
    #: `ENTITY_ALIAS`: `entity_addresses.superseded_by_entity_address_id` and
    #: `entity_communication_methods.superseded_by_communication_method_id`
    #: each have to say which table they point back into, and a shared prefix
    #: with any sibling surrogate id here would make that ambiguous. Neither
    #: prefix collides with an existing member of this enum (checked before
    #: use, per the campaign record).
    ENTITY_ADDRESS = "eadr"
    ENTITY_COMMUNICATION_METHOD = "ecmm"
    #: RI-ENT-WP-04: one project-participation row (`entity_project_participations`).
    #: `entity_role_types` and `entity_discipline_types` need no surrogate prefix —
    #: their primary keys are stable business codes (`role_code`/`discipline_code`),
    #: not generated ids, the same way `entity_organization_profiles` needed none.
    ENTITY_PROJECT_PARTICIPATION = "eppt"
    #: RI-ENT-WP-05: one temporal person-organization affiliation row
    #: (`entity_person_organization_affiliations`). Its own prefix rather than a
    #: reuse of `AFFILIATION` (`aff`, the WP-9 substrate's own per/org affiliation
    #: record): a stored reference -- in particular this table's own
    #: `superseded_by_affiliation_id` -- has to say which of the two tables it
    #: names, and a shared prefix would make that ambiguous, the same argument
    #: `ENTITY_NAME` makes against reusing `ENTITY_ALIAS`. Checked against every
    #: prior member of this enum before use: `poaf` collides with none.
    PERSON_ORGANIZATION_AFFILIATION = "poaf"
    #: WP-RI-06: the evidence and governance records. `ENTITY_OBSERVATION` names
    #: one source-bound observation that may refer to an entity and does not
    #: become one (specification section 12.2). `ENTITY_PROPOSAL` names a
    #: proposed mutation awaiting a decision. `ENTITY_MERGE` names the lineage
    #: record an accepted merge leaves behind, which is what makes a merge
    #: reversible rather than destructive (section 15.3).
    #:
    #: These three were deliberately absent until now: a prefix is a contract
    #: this module promises is stable, and until this work package there was no
    #: table for any of them to name.
    ENTITY_OBSERVATION = "eobs"
    ENTITY_PROPOSAL = "eprp"
    ENTITY_MERGE = "emrg"
    #: Relationship Memory: durable, entity-bound knowledge the user meant to
    #: keep. Seven prefixes rather than a reuse of the entity plane's or the
    #: capture plane's, on the argument `CAPTURE_VERSION` makes against reusing
    #: `VERSION`: a stored reference and an audit row have to say which record
    #: they name, and `eobs` already names a source-bound observation while
    #: `cap`/`capver` already name the user's unstructured text.
    #:
    #: `RELATIONSHIP_MEMORY` names the stable aggregate and
    #: `RELATIONSHIP_MEMORY_VERSION` one immutable statement of it — two rather
    #: than one because a correction appends rather than overwrites, so a
    #: reference has to say whether it means the memory or the wording it had.
    #: The two link prefixes are separate from `CONTEXT_LINK` (`clink`), which
    #: names the capture plane's own link record, and from each other because
    #: "where this applies" and "what this rests on" are different questions.
    #: The proposal pair is separate from `PROPOSAL` (`prop`) for the same
    #: reason: that one names a capture-plane extraction proposal.
    #:
    #: `RELATIONSHIP_MEMORY_SUBMISSION` names one admitted write, and its unique
    #: `(principal_id, idempotency_key)` is the idempotency mechanism — the
    #: shape `capture_submissions` and `managed_document_submissions` both use,
    #: reused here rather than reinvented.
    RELATIONSHIP_MEMORY = "mem"
    RELATIONSHIP_MEMORY_VERSION = "memver"
    RELATIONSHIP_MEMORY_CONTEXT_LINK = "mctx"
    RELATIONSHIP_MEMORY_EVIDENCE_LINK = "mevd"
    RELATIONSHIP_MEMORY_SUBMISSION = "memsub"
    RELATIONSHIP_MEMORY_PROPOSAL = "mprop"
    RELATIONSHIP_MEMORY_PROPOSAL_EVIDENCE = "mpev"
    #: WP-RI-A-01: the entity plane's lifecycle ledgers. Three prefixes rather
    #: than a reuse of `ENTITY_PROPOSAL` or `AUDIT`, on the argument
    #: `CAPTURE_VERSION` makes against reusing `VERSION`: a stored reference has
    #: to say which record it names, and each of them names a different act.
    #:
    #: `ENTITY_MUTATION_EVENT` names one append-only row in the ordinary
    #: mutation ledger -- what changed, under whose authority, and against which
    #: idempotency key. It is not `AUDIT`: an audit row records that a
    #: capability was invoked, and this one records what the invocation did to a
    #: canonical record, so a reference carrying one prefix for both could not
    #: say which half it meant.
    #:
    #: `ENTITY_FACT_EVIDENCE_LINK` names one binding between a canonical fact and
    #: the single record that evidences it. It is deliberately not
    #: `RELATIONSHIP_MEMORY_EVIDENCE_LINK`: that one binds a memory version, and
    #: a link table whose two planes shared a prefix would make an orphaned row
    #: unattributable to the plane that has to clean it up.
    #:
    #: `ENTITY_RESOLUTION_DECISION` names one append-only disposition of an
    #: observation. It is not `IDENTITY_RESOLUTION` (`ires`), which names the
    #: WP-9 substrate's person-merge resolution, and not `REVIEW_DECISION`
    #: (`rdec`), which names a reviewer's disposition of a capture proposal.
    ENTITY_MUTATION_EVENT = "emut"
    ENTITY_FACT_EVIDENCE_LINK = "efev"
    ENTITY_RESOLUTION_DECISION = "erdc"
    #: WP-RI-06: the three records a governed identity correction is bound by,
    #: performed under, and recorded in. Three prefixes rather than a reuse of
    #: `ENTITY_MERGE` (`emrg`), on the argument `CAPTURE_VERSION` makes against
    #: reusing `VERSION`: `emrg` names the redirect-lineage row an accepted merge
    #: proposal leaves behind, which is exactly the redirect-only lineage these
    #: three exist because it is insufficient for inverse recovery. A reference
    #: carrying one prefix for both could not say which of them it meant.
    #:
    #: `ENTITY_IDENTITY_PREVIEW` names the expiring binding between an operator's
    #: approval and the versions the preview read. `ENTITY_IDENTITY_OPERATION`
    #: names one admitted correction. `ENTITY_IDENTITY_EFFECT` names one
    #: append-only before/after row of what that correction did, and is
    #: deliberately not `ENTITY_MUTATION_EVENT` (`emut`): that ledger records one
    #: capability's change to one canonical record under an idempotency key, and
    #: this one records one step of an operation a later split has to reverse --
    #: and `entity_identity_effects.record_id` carries no foreign key, so its
    #: prefix is the only thing in the value that says what it points at.
    ENTITY_IDENTITY_PREVIEW = "eipv"
    ENTITY_IDENTITY_OPERATION = "eiop"
    ENTITY_IDENTITY_EFFECT = "eief"
    #: One record a preview could not attribute to a single identity, and the
    #: settlement of it. Its own prefix rather than a reuse of
    #: `ENTITY_IDENTITY_EFFECT` (`eief`): that one names a change the operation
    #: made, and this one names a question the preview could not answer -- a
    #: reference carrying one prefix for both could not say whether it points at
    #: something that happened or at something still open. The preview's
    #: ambiguity and the operation's settlement of it share this prefix because
    #: they are two records of one question, and the settlement is keyed on the
    #: ambiguity it settles.
    ENTITY_IDENTITY_AMBIGUITY = "eiam"
    #: RI-ENT-WP-07: fact-level assertion/provenance binding for the six
    #: Entity-bound record families RI-ENT-WP-02 through RI-ENT-WP-06 added
    #: (`entity_names`, `entity_organization_profiles`, `entity_addresses`,
    #: `entity_communication_methods`, `entity_project_participations`,
    #: `entity_person_organization_affiliations`). Deliberately not a reuse
    #: of `ASSERTION` (`asrt`, the capture-plane's own canonical-fact
    #: assertion, `my_pa.domain.capture.assertion`): a stored reference has
    #: to say which of the two unrelated "assertion" concepts it names, and
    #: a shared prefix would make that ambiguous, the same argument every
    #: other member of this enum already makes for its own table. Checked
    #: against every prior member of this enum before use: `east`/`easev`
    #: collide with none.
    ENTITY_ASSERTION = "east"
    ENTITY_ASSERTION_EVIDENCE = "easev"
    #: PC-CM-IMP-WP01: the two Project Controls aggregates that carry their own
    #: identity now (`my_pa.domain.project_controls`). A `ProjectConstraint` is
    #: deliberately not a `TASK` or a `COMMITMENT`: it is a first-class record
    #: bound to a continuity `PROJECT` (`prj_`), never a third Project identity,
    #: and a stored reference has to say which of the three it names. A
    #: `ConstraintCategory` is its own prefix rather than a reuse of the
    #: capture-plane `CAPTURE_CLIENT`/`CAPTURE_CLASSIFICATION` members it sits
    #: beside alphabetically, because the category is a Principal- and
    #: Project-scoped numbering scope and nothing else in this enum is. Party
    #: references, revisions, receipts, and sync records get no prefix here:
    #: WP01 issues no such record. Checked against every prior member of this
    #: enum before use (a grep of the quoted value over this file, and the
    #: uniqueness assertion in `tests/unit/test_identifiers.py`; nearest
    #: neighbours `cclt`/`ccls` differ): `cst`/`ccat` collide with none.
    PROJECT_CONSTRAINT = "cst"
    CONSTRAINT_CATEGORY = "ccat"
    #: PC-CM-IMP-WP02: the Project Controls persistence records that are
    #: addressed as rows of their own (party assignments, revisions, history
    #: receipts, relationships, evidence links, and the sync target/run/
    #: conflict records). Composite-keyed rows (settings, revision parties,
    #: sync baselines) get no prefix. Checked against every prior member of
    #: this enum before use (a grep of each quoted value over this file, and
    #: the uniqueness assertion in `tests/unit/test_identifiers.py`); none
    #: is a string prefix of, or prefixed by, any other value.
    CONSTRAINT_PARTY_ASSIGNMENT = "cpty"
    PROJECT_CONSTRAINT_REVISION = "crev"
    PROJECT_CONSTRAINT_HISTORY = "chst"
    CONSTRAINT_CATEGORY_HISTORY = "cchst"
    PROJECT_CONSTRAINT_RELATIONSHIP = "crel"
    PROJECT_CONSTRAINT_EVIDENCE_LINK = "cevd"
    CONSTRAINT_SYNC_TARGET = "csyt"
    CONSTRAINT_SYNC_RUN = "csyr"
    CONSTRAINT_SYNC_CONFLICT = "csyc"


class InvalidIdentifierError(ValueError):
    """Raised when a value is not a well-formed opaque identifier."""


def make_identifier(kind: IdKind, suffix: str) -> str:
    """Build an identifier of `kind` from an already-opaque `suffix`.

    The suffix must be generated by the caller from a non-semantic source. This
    function validates shape only; it cannot detect that a suffix leaks meaning.
    """
    candidate = f"{kind.value}_{suffix}"
    validate_identifier(candidate, kind)
    return candidate


def parse_identifier(value: str) -> tuple[IdKind, str]:
    """Return the kind and suffix of `value`, or raise `InvalidIdentifierError`."""
    validate_identifier(value)
    prefix, _, suffix = value.partition("_")
    return IdKind(prefix), suffix


def validate_identifier(value: str, expected: IdKind | None = None) -> str:
    """Validate `value` as an opaque identifier and return it unchanged.

    Fails closed: anything not matching the documented shape is rejected rather
    than normalised or guessed.
    """
    if not isinstance(value, str):
        # Domain models are plain dataclasses with no runtime type enforcement,
        # so a non-string reaching here must fail as a domain error rather than
        # as an incidental TypeError from len() or partition().
        raise InvalidIdentifierError(f"identifier must be a string, got {type(value).__name__}")
    if len(value) > _MAX_LENGTH:
        raise InvalidIdentifierError(f"identifier exceeds {_MAX_LENGTH} characters")
    prefix, separator, suffix = value.partition("_")
    if not separator:
        raise InvalidIdentifierError("identifier must contain a type prefix and suffix")
    try:
        kind = IdKind(prefix)
    except ValueError as exc:
        raise InvalidIdentifierError(f"unknown identifier prefix: {prefix!r}") from exc
    if not _SUFFIX_PATTERN.fullmatch(suffix):
        raise InvalidIdentifierError("identifier suffix must be 8-64 alphanumeric characters")
    if expected is not None and kind is not expected:
        raise InvalidIdentifierError(f"expected {expected.value!r} identifier, got {prefix!r}")
    return value
