"""The standing rule in `9c6b4a18ed72`, enforced instead of stated.

`D-69` wrote a rule into a merged migration — **no Alembic revision may derive a
closed-set constraint from a domain enum** — and left it as prose. The
independent reviewer measured what that is worth: an in-place
`DenialReason.ZZ_REVIEWER_PROBE` made that same already-merged revision emit
`denial_reason IN (…, 'zz_reviewer_probe')` and **nothing in the repository went
red**. The rule was true of two constraints in the file that states it and false
of the other two, and no test could tell the difference. `D-81` records that; this
module is the control that replaces the prose.

**What it detects.** For every revision in the chain, every closed-set `CHECK` it
emits, whose admitted vocabulary is *exactly* some live domain closed set. That
equality is the signature of a derivation: a hand-written literal that happens to
agree today is indistinguishable from a derived one *and carries the identical
hazard*, because the next member added to that enum is the moment they stop
agreeing — and one of the two will change silently. So the test does not care how
the constraint was written; it cares whether the revision still tracks the domain.

**The allowlist must shrink.** `ALLOWED` is the residual set of still-derived
sites: those carried by the revisions `D-81` deliberately does not edit. Its
size, and the revisions it names, are asserted in
`test_the_allowlist_names_only_revisions_this_package_does_not_edit` and are
deliberately not spelled here — a count of a current set belongs next to an
assertion that fails when it moves, or nowhere, which is the rule the comment on
the constant itself now follows. `D-92` is why it is put that way: the count was
restated by hand, and wrong, until it was derived from this ledger instead. Each
entry pins the *exact* vocabulary that site emits today, so the guard reddens
three ways:

- a member added to any listed enum changes an emitted vocabulary — red;
- a new derived constraint appears in a revision **through a shape `_emitted`
  reads** — red, because it is not in the allowlist. That qualifier is load
  bearing and was absent until it was measured: `_emitted` reads a revision's
  `Table` objects, so a constraint written as raw SQL is outside it. Measured,
  not reasoned — see the paragraph below;
- a listed site is frozen — red, because the allowlist must then lose a row.

A guard whose allowlist can be widened silently is the vacuous-guard shape this
campaign has now caught three times (`D-26`, `D-44`, `D-80`), so widening it
requires editing this file, which is the point.

**Why the discovery is reflective rather than a hand-kept list.** The live closed
sets are found by walking `my_pa` for every `StrEnum` and every module-level
`frozenset[str]`. A domain enum added next week is covered without anyone
remembering this file exists — which is the failure mode the campaign's earlier
guards had, where a name list "could never fire".

Reading the emission, not the source text: each revision hands a concrete set of
`Table` objects to `create_all`, and it is those objects' constraints that become
DDL. `_emitted` therefore asks the module for its tables rather than parsing it,
and `test_every_revision_declares_its_emission_readably` refuses a revision that
touches the shared declaration through a shape this module cannot read — without
which a later revision could derive freely simply by being written differently.

**What it does NOT detect, stated because a control described as closing a class
it does not close is the overclaim this campaign keeps catching (`D-86`).**

**It cannot see a closed set built in raw SQL.** `_emitted` reads the `Table`
objects a revision hands to `create_all`, so a constraint that never becomes a
`Table` object is not read at all. A revision writing
`op.execute("… ADD CONSTRAINT … CHECK (status IN (…))")` with the vocabulary
joined out of a live `StrEnum` derives exactly as freely as `D-69` forbids, and
this module goes on passing. Replayed on this chain rather than reasoned about:
`9d4e7a3b1c62`'s `_STATUS_VOCABULARY` was rewritten to join `ExtractionStatus`'s
members, which put `CHECK (status IN ('extracted', 'quarantined',
'unsupported'))` verbatim into the rendered DDL and left this module at **16
passed**, its unplanted count.
`test_every_revision_declares_its_emission_readably` does not reach it either:
that test refuses a revision whose *emission* is unreadable, and a revision with
a readable emission plus an `op.execute` beside it satisfies it — which is
exactly the shape `9d4e7a3b1c62` has, since it declares an empty `_TABLES` and
does all its work in `op.execute`.

**And the gap is already occupied by a merged revision, which the plant only
made visible.** `7f2a9d6c4e18` builds all seventeen of its tables in raw SQL: it
imports `alembic.op` and nothing else, holds no `Table` and names no declaration
module, so `_emitted` returns `None` for it and the readability test above skips
it rather than failing it. It appears in neither `ALLOWED` nor `FROZEN`. Counted
with this module's own `_CLOSED_SET` and `_LITERAL` over its rendered DDL, its
emitted SQL carries fifteen closed-set expressions in seven distinct
vocabularies, and **three of those seven are exactly equal to a live closed set**
(`my_pa.domain.relationship.identity.ResolutionAction`,
`my_pa.domain.relationship.profile.EvidenceAuthority`, and
`my_pa.infrastructure.providers.personal_fixture._ALLOWED_DOMAINS`). By the
doctrine stated at the top of this file, that equality is the signature this
module exists to find, and here it finds nothing.

**What that does and does not mean, stated at measurement rather than above it.**
Read by hand, `7f2a9d6c4e18` writes literals; it imports no enum and derives
nothing, so it complies with `D-69` today. What is missing is not compliance but
*verification*: that compliance rests on someone having read the file, and a
later edit joining one of those three vocabularies out of its enum would restore
the exact `D-69` defect with this module still green. **Closing it belongs to a
package that owns this module**: it needs a rule that reads each revision's
emitted SQL text and attributes vocabularies to live closed sets, which is a
different parse from the object-graph read below and not an extension of it.

**It reads sets, not single values.** This module reads a constraint whose
admitted vocabulary is a whole closed *set*. Nine constraints instead embed a
single enum **value**, and every one of them is outside this guard's coverage:

- `a_job_is_running_exactly_while_leased` and
  `a_capture_job_is_running_exactly_while_leased`, from `JobState.RUNNING`;
- `derived_text_is_never_source_original`, from
  `TrustLevel.SOURCE_BOUND_DERIVED`;
- `text_exists_exactly_when_something_was_extracted` and
  `only_a_supported_media_type_is_extracted`, from `ExtractionStatus.EXTRACTED`;
- `a_denial_records_its_reason_and_nothing_else_does`, from
  `AuditOutcome.DENIED`;
- `an_invalidated_proposal_records_its_reason`, from
  `ProposalState.INVALIDATED` — the seventh, added by WP-7 and named here rather
  than left for a later sweep to find, because `D-86`'s second half is
  "implemented, not promised". It sits inside `2b7e9f4c1a83`, whose closed sets
  are frozen, so the *set* is safe; the embedded single value is not, on exactly
  the terms the six above are not;
- `a_revalidating_assertion_records_when_it_was_asked`, from
  `AssertionState.REVALIDATION_REQUIRED`, and
  `a_superseded_link_records_when_it_was`, from
  `ContextLinkAuthority.SUPERSEDED` — the eighth and ninth, added by WP-8 and
  counted here for the same reason the seventh was. Both sit inside
  `3c8f1e2a5b74`, whose closed sets are frozen.

The list is maintained by counting, not by memory: a revision adding a
constraint that embeds one enum value adds a line here, and the number in the
paragraph above moves with it.

The reviewer measured the gap rather than inferring it: renaming
`AuditOutcome.DENIED` moves the DDL an already-merged revision emits and this
module **stays green**. So it is the same family as `D-69` and `D-81`, and it is
recorded as ledger rather than fixed here for one reason, which `D-86` states:
**adding an enum member is silent, whereas renaming a value breaks loudly** at
the constant, the persistence mapping, every fixture and every assertion that
names the string. `D-81`'s hazard is silent drift; this one announces itself.
What would close it is a rule reading each revision's emitted `CHECK` text for
any enum value it can attribute to a live member — which is a different parse
from the set equality below, not an extension of it.

**One revision is structurally invisible to this module, and it is disclosed
rather than fixed** (`D-99`). `migrations/versions/20260801_4b9f0d27ac31_
create_migration_control_plane.py` calls `METADATA.create_all(bind)` on
`my_pa.infrastructure.migration.control_plane`'s **separate** `MetaData`, never
imports `DECLARATION`, and holds no `Table` in its namespace — so
`test_every_revision_declares_its_emission_readably` skips it and `_emitted`
returns `None` for it. `control_plane.py` derives five further closed-set
constraints from live enums (`RunStatus`, `PhaseStatus`, `TableState`,
`QuarantineCode`, `AuditEvent`), and not one of them is reachable from here,
because `DECLARATION` above hard-codes a single declaration module. That is a
larger hole than the single-value class named just above: those six are
detected-and-allowlisted, and this one is unreachable. Closing it means teaching
this module a second `MetaData`, which is its own package with its own review.
A control that names its own blind spot beats one that implies totality.

Nothing here opens a connection or a path. Every value is read out of the
repository's own declarations.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import re
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from sqlalchemy import CheckConstraint, MetaData, Table

import my_pa

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "migrations" / "versions"

#: The module a revision must import from before it can derive anything: the one
#: place every table in the `knowledge` schema is declared.
DECLARATION = "my_pa.infrastructure.persistence.tables"

#: A revision that emits shared-declaration tables exposes them as one of these.
#: A callable is what a revision uses when it freezes something — it returns
#: copies with the derived constraints replaced. `_TABLES` is the plain case.
_EMISSION_CALLABLES: Final = (
    "_historical_knowledge_tables",
    "_historical_audit_events",
    "_historical_capture_tables",
    "_historical_wp7_tables",
    "_historical_wp8_tables",
    "_historical_wp27_tables",
)
_EMISSION_LIST: Final = "_TABLES"

#: `column IN ('a', 'b')` or `column <@ ARRAY['a', 'b']`, wherever either sits in
#: a larger expression — the two error-code constraints wrap theirs in `... IS
#: NULL OR ...`.
#:
#: The array form is read because a closed set over an array column cannot be
#: written as `IN`, and a shape this module could not parse would be a derived
#: site nobody could see — which is this module's entire subject. It was added
#: with `capture_proposals.a_missing_required_field_is_a_required_field`, and it
#: names no site that was previously hidden: no revision in the chain emitted an
#: `ARRAY[…]` literal before that one, which `test_the_allowlist_names_only_
#: revisions_this_package_does_not_edit` holds at ten.
_CLOSED_SET = re.compile(r"IN \(([^)]*)\)|<@ ARRAY\[([^\]]*)\]")
_LITERAL = re.compile(r"'([^']*)'")

#: Every still-derived site, with the revision that emits it, the closed set it
#: tracks, and the exact vocabulary it emits today. WP-12 freezes the sites in
#: the knowledge-schema revision because it expands two of their vocabularies;
#: the extraction sites listed here remain derived and unchanged.
#:
#: **Its size is asserted in
#: `test_the_allowlist_names_only_revisions_this_package_does_not_edit` and is
#: not restated here.** It lost `extractions.extraction_status_is_known` when
#: WP-03 narrowed that constraint to an inline literal, and a spelled count of a
#: shrinking set beside the set itself is the next stale claim — inside the guard
#: whose whole subject is a written-down vocabulary drifting from the thing it
#: describes. A count of a current set belongs next to an assertion that fails
#: when it moves, or nowhere.
#:
#: The independent reviewer's list named nine sites and eight sources. Both
#: numbers were low: `quarantine_review_state_is_known` derives from
#: `QuarantineReviewState`, which the list omits, and
#: `jobs.last_error_code_is_a_public_error_code` derives from the public
#: error-code set rather than from a `StrEnum`, which is why a sweep for the
#: declarative enum helper alone does not see it. It is the same hazard: an
#: error code added to `v1` changes what `7e5a1fb93d62` emits.
ALLOWED: Final[frozenset[tuple[str, str, str, str, tuple[str, ...]]]] = frozenset(
    {
        (
            "8b3f5c17d904",
            "extractions",
            "only_a_supported_media_type_is_extracted",
            "my_pa.application.capabilities.SUPPORTED_MEDIA_TYPES",
            ("text/markdown", "text/plain"),
        ),
        (
            "8b3f5c17d904",
            "quarantine_records",
            "quarantine_reason_is_known",
            "my_pa.domain.extraction.quarantine.QuarantineReason",
            (
                "containment_unproven",
                "malformed_input",
                "media_type_conflicts_with_signature",
                "output_not_attributable_to_version",
                "parser_failed",
                "parser_timed_out",
                "resource_limit_exceeded",
                "source_version_changed",
            ),
        ),
        (
            "8b3f5c17d904",
            "quarantine_records",
            "quarantine_review_state_is_known",
            "my_pa.domain.extraction.quarantine.QuarantineReviewState",
            ("pending_review",),
        ),
        (
            "8b3f5c17d904",
            "coverage_limitations",
            "limitation_reason_is_known",
            "my_pa.domain.extraction.coverage.LimitationReason",
            ("objects_omitted_containment_unproven",),
        ),
    }
)

#: The revisions that carry frozen literals, and the vocabulary each freezes.
#: Restated here rather than imported from the revision, for the reason
#: `FROZEN_CAPABILITIES` in `test_capture_schema_migration.py` gives: a test that
#: read the revision's own literal would pass however that literal changed.
FROZEN: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "7e5a1fb93d62": {
        "provider_kind_is_known": ("fixture",),
        "classification_is_known": (
            "private_local",
            "restricted_local",
            "synthetic_test",
        ),
        "kind_is_known": ("container", "file"),
        "state_is_known": ("failed", "queued", "running", "succeeded"),
        "last_error_code_is_a_public_error_code": (
            "ambiguous_request",
            "cancelled",
            "conflict",
            "denied",
            "internal_error",
            "invalid_request",
            "not_found",
            "quarantined",
            "rate_limited",
            "unavailable",
            "unsupported",
        ),
    },
    "9c6b4a18ed72": {
        "capability_is_known": (
            "capabilities.get",
            "knowledge.read",
            "knowledge.search",
            "sources.enroll",
            "sources.fetch",
            "sources.list",
            "sources.metadata",
            "sources.status",
        ),
        "purpose_is_known": (
            "bounded_enrollment",
            "content_extraction",
            "knowledge_read",
            "knowledge_search",
            "security_validation",
            "source_inspection",
            "status_observation",
        ),
        "audit_outcome_is_known": ("allowed", "denied", "failed"),
        "denial_reason_is_known": (
            "destination_not_eligible",
            "operator_required",
            "principal_may_not_hold_authority",
            "principal_not_authenticated",
            "purpose_not_permitted_for_capability",
            "scope_not_authorized",
        ),
    },
    "1a4c9e77b2d5": {
        "capture_classification_is_known": (
            "private_local",
            "restricted_local",
            "synthetic_test",
        ),
        "processing_policy_is_known": ("local_only",),
        "capture_transport_is_known": ("local",),
        "capture_method_is_known": ("typed_text",),
        "capture_trust_state_is_known": ("local_principal",),
        "admission_result_is_known": ("accepted",),
        "capture_job_state_is_known": ("failed", "queued", "running", "succeeded"),
        "capture_job_error_code_is_a_public_error_code": (
            "invalid_request",
            "ambiguous_request",
            "denied",
            "unavailable",
            "unsupported",
            "not_found",
            "conflict",
            "rate_limited",
            "quarantined",
            "cancelled",
            "internal_error",
        ),
    },
    "2b7e9f4c1a83": {
        "capture_stage_is_known": (
            "datetime_normalization",
            "detect_language",
            "deterministic_extraction",
            "index_capture_text",
            "normalize",
            "persist_proposals",
            "segment",
            "validate",
            "work_object_extraction",
        ),
        "capture_processing_state_is_known": (
            "complete",
            "partial",
            "permanent_failure",
            "policy_denied",
            "retryable_failure",
            "running",
            "waiting",
        ),
        "span_offset_basis_is_known": ("unicode_code_point_v1",),
        "span_role_is_known": ("context", "counterevidence", "direct"),
        "proposal_type_is_known": (
            "commitment",
            "decision",
            "follow_up",
            "issue",
            "open_question",
            "risk",
            "task",
        ),
        "proposal_state_is_known": (
            "accepted",
            "corrected_accepted",
            "deferred",
            "invalidated",
            "needs_review",
            "proposed",
            "rejected",
            "superseded",
            "unresolved",
        ),
        "proposal_risk_class_is_known": ("critical", "high", "low", "moderate"),
        "proposal_method_is_known": ("deterministic_rule",),
        "proposal_quarantine_reason_is_known": (
            "span_cites_another_version",
            "span_outside_version_text",
            "span_text_does_not_re_derive",
        ),
        "a_missing_required_field_is_a_required_field": (
            "action",
            "actor",
            "counterparty",
            "due_condition",
            "status",
        ),
        "capture_label_is_known": (
            "commitment_mention",
            "date_mention",
            "external_reference",
            "financial_mention",
            "identifier_mention",
        ),
        "mention_entity_type_is_known": ("document", "project", "url"),
        "mention_resolution_state_is_known": ("unresolved",),
    },
    "3c8f1e2a5b74": {
        "review_disposition_is_known": (
            "accept",
            "correct_and_accept",
            "defer",
            "escalate",
            "mark_unresolved",
            "reject",
            "reprocess",
        ),
        # Not `ProposalType`'s constraint under another name: this one is on
        # `capture_assertions` and is emitted by this revision, and it happens to
        # admit the same seven because an assertion carries its proposal's type
        # forward. Both are frozen, in the revision that emits each, so neither
        # tracks the enum.
        "assertion_type_is_known": (
            "commitment",
            "decision",
            "follow_up",
            "issue",
            "open_question",
            "risk",
            "task",
        ),
        "assertion_state_is_known": (
            "accepted",
            "contradicted",
            "proposed",
            "revalidation_required",
            "stale",
            "superseded",
            "withdrawn",
        ),
        "context_link_target_type_is_known": ("source_object",),
        "context_link_role_is_known": ("launch_context",),
        "context_link_authority_state_is_known": (
            "deterministic",
            "proposed",
            "rejected",
            "superseded",
            "user_confirmed",
        ),
        "conversation_event_state_is_known": (
            "accepted",
            "archived",
            "proposed",
            "skeletal",
            "superseded",
        ),
        "conversation_channel_is_known": ("unknown",),
    },
    # WP-27's managed-document plane. Two closed sets, both frozen in the
    # revision: the media types a managed document may declare, and the two
    # lifecycle transitions. A member added to `MANAGED_MEDIA_TYPES` or to
    # `domain.documents.managed.LifecycleTransition` must leave both texts here.
    "4c7b2e91d8a5": {
        "a_managed_media_type_is_known": (
            "application/json",
            "application/octet-stream",
            "application/pdf",
            "text/markdown",
            "text/plain",
        ),
        "a_managed_document_transition_is_known": ("archived", "restored"),
    },
}


def _live_closed_sets() -> dict[frozenset[str], str]:
    """Every closed set of strings the package declares, by its values.

    Keyed by value set because that is what a constraint exposes — the emitted
    DDL carries no trace of which enum produced it. Two declarations with the
    same values are indistinguishable to a reader of the schema too, so the
    first by dotted name wins and the choice is deterministic.
    """
    found: dict[frozenset[str], set[str]] = {}
    for module in pkgutil.walk_packages(my_pa.__path__, f"{my_pa.__name__}."):
        # Deliberately not guarded. A module of `my_pa` that cannot be imported
        # is a defect, and swallowing it here would silently shrink the universe
        # this guard compares against — the "guard that could never fire" shape.
        imported = importlib.import_module(module.name)
        for name, value in vars(imported).items():
            if isinstance(value, type) and issubclass(value, StrEnum) and value is not StrEnum:
                key = frozenset(member.value for member in value)
                found.setdefault(key, set()).add(f"{value.__module__}.{value.__qualname__}")
            elif isinstance(value, frozenset) and value and all(isinstance(v, str) for v in value):
                found.setdefault(frozenset(value), set()).add(f"{imported.__name__}.{name}")
    return {values: sorted(names)[0] for values, names in found.items()}


def _revisions() -> Iterator[tuple[str, ModuleType]]:
    for path in sorted(VERSIONS.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"_revision_{path.stem}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield str(module.revision), module


def _emitted(module: ModuleType) -> list[Table] | None:
    """The tables a revision hands to `create_all`, or `None` if it emits none.

    `None` is the raw-SQL revisions of the migration target, which read `.sql`
    files and cannot derive from a Python enum at all.

    **A revision that declares `_FROZEN` may not fall through to `_TABLES`**, and
    that refusal is the whole of ledger item 1. Every freezing revision in this
    chain also holds a module-level `_TABLES` list of the *live* declarations —
    the input its `_historical_*` callable copies — so deleting the callable's
    name from `_EMISSION_CALLABLES`, or renaming the callable, left this function
    returning those live tables instead. The constraints on them still agreed
    with the domain, so `test_a_frozen_revision_emits_its_recorded_vocabulary`
    passed, `_derived_sites` saw a frozen name and excused it, and all eleven
    tests here stayed green while the guard read the declaration it exists to
    stop reading. The step that makes this module real for a new revision was
    therefore a silent no-op if forgotten, in the module whose subject is checks
    that silently stop checking.

    Raising rather than returning `None` is deliberate: `None` is a legitimate
    answer that `test_every_revision_declares_its_emission_readably` `continue`s
    past for the raw-SQL revisions, so a missing entry would have gone on being
    invisible in a second way.
    """
    for name in _EMISSION_CALLABLES:
        emitter = getattr(module, name, None)
        if callable(emitter):
            produced = emitter()
            return list(produced) if isinstance(produced, list) else [produced]
    if isinstance(getattr(module, "_FROZEN", None), dict):
        raise AssertionError(
            f"{module.__name__} declares _FROZEN but exposes no emission callable this "
            f"module knows; add its name to _EMISSION_CALLABLES {_EMISSION_CALLABLES}. "
            f"Falling through to {_EMISSION_LIST} would read the live declaration the "
            "freeze exists to stop reading, and would do it without failing."
        )
    declared = getattr(module, _EMISSION_LIST, None)
    if isinstance(declared, list):
        return declared
    return None


def _closed_sets(table: Table) -> Iterator[tuple[str, frozenset[str]]]:
    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint) or constraint.name is None:
            continue
        for match in _CLOSED_SET.finditer(str(constraint.sqltext)):
            # One alternation, two groups: whichever branch matched is the one
            # that is not `None`. Reading `group(1)` alone would silently see
            # nothing in every array-form constraint, which is the shape of hole
            # this module exists to refuse.
            values = frozenset(_LITERAL.findall(match.group(1) or match.group(2) or ""))
            if values:
                yield str(constraint.name), values


def _derived_sites() -> set[tuple[str, str, str, str, tuple[str, ...]]]:
    """Every emitted closed set whose vocabulary is exactly a live closed set.

    Frozen sites are excluded **structurally**, by the revision declaring them in
    its own `_FROZEN` constant, not by their values — a freshly frozen literal
    still equals the enum it was copied from, so value equality cannot tell the
    two apart on the day of the freeze. That the declaration is real, and that
    what it declares is what gets emitted, is
    `test_a_frozen_revision_freezes_structurally` below; separating the two is
    what stops a re-coupling from hiding behind "the values still agree".
    """
    live = _live_closed_sets()
    sites: set[tuple[str, str, str, str, tuple[str, ...]]] = set()
    for revision, module in _revisions():
        frozen = set(FROZEN.get(revision, {}))
        for table in _emitted(module) or []:
            for name, values in _closed_sets(table):
                if name not in frozen and values in live:
                    sites.add((revision, table.name, name, live[values], tuple(sorted(values))))
    return sites


def _declared_frozen(module: ModuleType) -> dict[str, str]:
    """The constraint texts a revision declares frozen, flattened by name.

    A revision freezing one table keys `_FROZEN` by constraint name; one freezing
    several keys it by table first. Both shapes are read here so that neither
    revision has to carry the other's structure.
    """
    declared = getattr(module, "_FROZEN", None)
    if not isinstance(declared, dict):
        return {}
    flat: dict[str, str] = {}
    for key, value in declared.items():
        if isinstance(value, dict):
            flat.update({str(name): str(text) for name, text in value.items()})
        else:
            flat[str(key)] = str(value)
    return flat


def test_the_chain_is_readable_and_non_empty() -> None:
    """Guards every other test here: an empty chain would make them all vacuous."""
    revisions = list(_revisions())
    assert len(revisions) == 42
    assert len({revision for revision, _ in revisions}) == 42
    assert {
        "9c6b4a18ed72",
        "1a4c9e77b2d5",
        "2b7e9f4c1a83",
        "7e5a1fb93d62",
        "8b3f5c17d904",
        # WP-28's widening of both `audit_events` closed sets. Named here for the
        # reason the five above are: this module's whole subject is revisions that
        # install a closed set, and one that installs two must be one this scan
        # actually opened.
        "6b3d9a2f8c14",
    } <= {revision for revision, _ in revisions}


def test_the_live_closed_sets_are_discovered() -> None:
    """The reflection finds the sets, so a non-match means non-match.

    Without this, a broken walk would report zero live closed sets, every site
    would look undetected, and the allowlist assertion below would fail in a way
    that reads like a fix.
    """
    live = _live_closed_sets()
    assert len(live) > 40
    assert (
        live[frozenset({"calendar_event", "contact", "container", "file", "mail_message", "task"})]
        == "my_pa.domain.source.provider.ObjectKind"
    )
    assert (
        live[frozenset({"pending_review"})]
        == "my_pa.domain.extraction.quarantine.QuarantineReviewState"
    )


def test_every_revision_declares_its_emission_readably() -> None:
    """A revision that reaches the shared declaration must be readable here.

    Without this the guard has a hole shaped like a revision written in a new
    style: it would emit derived constraints, `_emitted` would return `None`,
    and the allowlist would stay green. `D-80` records the same shape arriving
    through a fixture rather than an assertion.
    """
    for revision, module in _revisions():
        touches_declaration = any(
            getattr(value, "__module__", None) == DECLARATION or value is not None
            for name, value in vars(module).items()
            if isinstance(value, Table)
        ) or any(
            isinstance(value, list) and value and all(isinstance(item, Table) for item in value)
            for value in vars(module).values()
        )
        source = (VERSIONS / f"{module.__name__.removeprefix('_revision_')}.py").read_text(
            encoding="utf-8"
        )
        if DECLARATION not in source and not touches_declaration:
            continue
        assert _emitted(module) is not None, (
            f"{revision} imports {DECLARATION} but exposes no readable emission; "
            f"add {_EMISSION_LIST} or one of {_EMISSION_CALLABLES}"
        )


def test_no_revision_derives_a_closed_set_outside_the_allowlist() -> None:
    """The rule `9c6b4a18ed72` states, as a check rather than a sentence.

    Reddening means one of three things, and the diff says which: an enum gained
    a member and some revision's emitted DDL moved with it; a new derived
    constraint was written; or a listed site was frozen and this list has to lose
    a row. All three want a human.
    """
    assert _derived_sites() == ALLOWED


def test_the_allowlist_names_only_revisions_this_package_does_not_edit() -> None:
    """`D-81`'s boundary, held to.

    The revisions WP-6 and WP-7 write or edit carry no derived constraint at
    all. If one appears in the allowlist, the freeze that closed it has been
    undone and the residual class has grown rather than shrunk.
    """
    assert {revision for revision, *_ in ALLOWED} == {"8b3f5c17d904"}
    assert len(ALLOWED) == 4
    assert not {revision for revision, *_ in ALLOWED} & set(FROZEN)


@pytest.mark.parametrize("revision", sorted(FROZEN))
def test_a_frozen_revision_emits_its_recorded_vocabulary(revision: str) -> None:
    """The other end of the property, so a plant proves something.

    A member added to `Capability`, `DenialReason`, `JobState`, any of the six
    capture sets, or any of the thirteen the proposal revision freezes must
    leave all twenty-five constraint texts exactly where they are. That is what
    "the revision goes on denoting one schema" means, and it is the half the
    reviewer measured as broken for `denial_reason`.
    """
    module = dict(_revisions())[revision]
    tables = _emitted(module)
    assert tables is not None
    emitted = {
        name: tuple(sorted(values)) for table in tables for name, values in _closed_sets(table)
    }
    for name, expected in FROZEN[revision].items():
        assert emitted[name] == tuple(sorted(expected)), name


def _module(**namespace: object) -> ModuleType:
    """A stand-in revision, so the rule below is exercised on a real lookup."""
    module = ModuleType("_revision_synthetic")
    for name, value in namespace.items():
        setattr(module, name, value)
    return module


def test_a_freezing_revision_may_not_fall_through_to_the_live_declaration() -> None:
    """Ledger item 1, closed, with the control that says the refusal is narrow.

    The defect: `_EMISSION_CALLABLES` is a name list, and a revision whose
    callable is not in it falls back to `_TABLES` — which every freezing revision
    in this chain also holds, pointing at the *live* declarations its callable
    copies. So the entry that makes this module read a freeze at all could be
    forgotten, and nothing anywhere would say so. `2b7e9f4c1a83` names the hazard
    in its own docstring and could not enforce it.

    Three cases, because a rule that refused everything would be no better than
    one that refused nothing:

    - a freezing revision this module cannot read raises, naming the fix;
    - the same revision with a recognised callable is read from the callable, so
      the refusal is about the lookup and not about `_FROZEN` existing;
    - a revision with no `_FROZEN` still falls back to `_TABLES`, which is the
      legitimate case the fallback was written for and which the raise must not
      take with it.
    """
    live = Table("live", MetaData(), CheckConstraint("a IN ('x')", name="a_is_known"))
    frozen_copy = Table("frozen", MetaData(), CheckConstraint("a IN ('y')", name="a_is_known"))

    with pytest.raises(AssertionError, match="_EMISSION_CALLABLES"):
        _emitted(_module(_FROZEN={"live": {"a_is_known": "a IN ('y')"}}, _TABLES=[live]))

    readable = _module(
        _FROZEN={"live": {"a_is_known": "a IN ('y')"}},
        _TABLES=[live],
        _historical_wp8_tables=lambda: [frozen_copy],
    )
    assert _emitted(readable) == [frozen_copy]

    assert _emitted(_module(_TABLES=[live])) == [live]
    assert _emitted(_module()) is None


@pytest.mark.parametrize("revision", sorted(FROZEN))
def test_a_frozen_revision_freezes_structurally(revision: str) -> None:
    """The freeze is a declaration in the revision, not an accident of agreement.

    `_derived_sites` excuses these constraints on the strength of this
    declaration, so this is the assertion that keeps that excuse honest. Delete
    a `_FROZEN` entry and re-derive it and the constraint reappears in
    `_derived_sites` — red on the allowlist — **even though its values have not
    moved yet**, which is the window in which a re-coupling would otherwise sit
    invisible until the next member was added.
    """
    module = dict(_revisions())[revision]
    declared = _declared_frozen(module)
    assert set(declared) == set(FROZEN[revision]), revision
    for name, expected in FROZEN[revision].items():
        assert frozenset(_LITERAL.findall(declared[name])) == frozenset(expected), name
