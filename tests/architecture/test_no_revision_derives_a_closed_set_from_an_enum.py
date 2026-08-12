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

**The allowlist must shrink.** `ALLOWED` is the fifteen sites carried by the
three revisions `D-81` deliberately does not edit (`D-92`; the count said "nine
sources" in `D-81` and in WP-7's brief, and the omitted tenth was
`my_pa.contracts.v1.errors.ErrorCode`, which reaches
`jobs.last_error_code_is_a_public_error_code` without being a `StrEnum` — the
same undercount `D-81` warns about, repeated inside the row that warns about
it). Ten of the fifteen were listed before the guard was widened; the last five
are `4b9f0d27ac31`'s, and the paragraph on the widening below says exactly what
listing them does and does not buy. Each entry pins the *exact* vocabulary that
site emits today, so the guard reddens three ways:

- a member added to any listed enum changes an emitted vocabulary — red;
- a new derived constraint appears in any revision — red, because it is not in
  the allowlist;
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
it does not close is the overclaim this campaign keeps catching (`D-86`).** This
module reads a constraint whose admitted vocabulary is a whole closed *set*. Nine
constraints instead embed a single enum **value**, and every one of them is
outside this guard's coverage:

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

**The blind spot `D-99` disclosed is closed, and closing it moved five sites out
of "unreachable" and into the allowlist.** Until now this module hard-coded one
declaration module name, so `migrations/versions/20260801_4b9f0d27ac31_create_
migration_control_plane.py` — which calls `METADATA.create_all(bind)` on
`my_pa.infrastructure.migration.control_plane`'s **separate** `MetaData`, never
imports the persistence declaration, and holds no `Table` in its namespace —
was invisible: `test_every_revision_declares_its_emission_readably` skipped it
and `_emitted` returned `None`. The fix is structural rather than a second
constant. `_declaration_modules` walks `my_pa` for every module that declares
`Table`s against its own module-level `MetaData`, and `_emitted` reads a
revision's `MetaData` when it exposes neither an emission callable nor
`_TABLES`. A *third* declaration module written tomorrow is therefore covered
with no edit here, and `_declared_metadata` — the predicate the walk applies —
is exercised on a synthetic namespace below so that "would find a third" is a
measurement rather than a hope.

**What widening it measured, stated because it is the point of widening it.**
The five constraints `control_plane.py` derives from `RunStatus`,
`PhaseStatus`, `TableState`, `QuarantineCode` and `AuditEvent` became visible
all at once, and `test_no_revision_derives_a_closed_set_outside_the_allowlist`
went red on all five. They are **allowlisted, not frozen**: freezing them means
editing a merged revision, which this package does not do. So the improvement is
exactly and only this — five sites that were *structurally unreachable* are now
*detected and pinned*, on the same terms as the ten that were already listed. A
member added to any of those five enums now reddens this file. Two of them,
`phase_status.status_is_known` and `table_progress.state_is_known`, are
attributed to `PhaseStatus` because `PhaseStatus` and `TableState` declare the
identical three values and `_live_closed_sets` is keyed by value set; the
attribution is the documented first-by-dotted-name tie-break, and the hazard it
records is the real one either way.

Nothing here opens a connection or a path. Every value is read out of the
repository's own declarations.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import re
from collections.abc import Iterator, Mapping
from enum import StrEnum
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from sqlalchemy import CheckConstraint, MetaData, Table

import my_pa

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "migrations" / "versions"

#: The two declaration modules that exist today, asserted as a **subset** of what
#: `_declaration_modules` finds rather than as an equality. A subset keeps the
#: discovery honest — a walk that returned nothing would fail here rather than
#: quietly reporting that no revision touches a declaration — while leaving a
#: third declaration module covered automatically instead of forcing an edit,
#: which is the whole reason the hard-coded name went away. Equality would be a
#: count of a current set, and those rot.
KNOWN_DECLARATIONS: Final = frozenset(
    {
        "my_pa.infrastructure.persistence.tables",
        "my_pa.infrastructure.migration.control_plane",
    }
)

#: A revision that emits shared-declaration tables exposes them as one of these.
#: A callable is what a revision uses when it freezes something — it returns
#: copies with the derived constraints replaced. `_TABLES` is the plain case.
_EMISSION_CALLABLES: Final = (
    "_historical_knowledge_tables",
    "_historical_audit_events",
    "_historical_capture_tables",
    "_historical_wp7_tables",
    "_historical_wp8_tables",
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
#: `ARRAY[…]` literal before that one. `ALLOWED` below is the whole residual set,
#: and `test_the_allowlist_names_only_revisions_this_package_does_not_edit` holds
#: it to the revisions listed there rather than to a count restated here — a
#: spelled figure in a comment is the defect this package exists to remove, and
#: this one had already gone stale.
_CLOSED_SET = re.compile(r"IN \(([^)]*)\)|<@ ARRAY\[([^\]]*)\]")
_LITERAL = re.compile(r"'([^']*)'")

#: Every still-derived site, with the revision that emits it, the closed set it
#: tracks, and the exact vocabulary it emits today. WP-12 freezes the five sites
#: in the knowledge-schema revision because it expands two of their vocabularies;
#: the five extraction sites remain derived and unchanged.
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
            "extraction_status_is_known",
            "my_pa.domain.extraction.text.ExtractionStatus",
            ("extracted", "quarantined", "unsupported"),
        ),
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
        (
            "4b9f0d27ac31",
            "migration_runs",
            "status_is_known",
            "my_pa.infrastructure.migration.control_plane.RunStatus",
            (
                "CANCELLED",
                "COMPLETED",
                "FAILED",
                "PAUSED",
                "PENDING",
                "ROLLED_BACK",
                "RUNNING",
            ),
        ),
        (
            "4b9f0d27ac31",
            "phase_status",
            "status_is_known",
            "my_pa.infrastructure.migration.control_plane.PhaseStatus",
            ("COMPLETED", "FAILED", "RUNNING"),
        ),
        # `TableState`, not `PhaseStatus`. The attribution is `_live_closed_sets`'
        # first-by-dotted-name tie-break between two enums that declare the same
        # three values, and it is left as the reflection reports it rather than
        # corrected by hand: a hand-written source name here would be the one
        # value in the row that no measurement produced.
        (
            "4b9f0d27ac31",
            "table_progress",
            "state_is_known",
            "my_pa.infrastructure.migration.control_plane.PhaseStatus",
            ("COMPLETED", "FAILED", "RUNNING"),
        ),
        (
            "4b9f0d27ac31",
            "quarantine_records",
            "error_code_is_known",
            "my_pa.infrastructure.migration.control_plane.QuarantineCode",
            (
                "DUPLICATE_NATURAL_KEY",
                "NULL_PRIMARY_KEY",
                "TARGET_REJECTED_ROW",
                "TYPE_CAST_FAILURE",
                "UNSUPPORTED_TEXT_NUL",
            ),
        ),
        (
            "4b9f0d27ac31",
            "audit_events",
            "event_type_is_known",
            "my_pa.infrastructure.migration.control_plane.AuditEvent",
            (
                "IDENTITY_DRIFT_DETECTED",
                "PHASE_COMPLETED",
                "PHASE_STARTED",
                "RUN_COMPLETED",
                "RUN_CREATED",
                "RUN_FAILED",
                "SEQUENCE_RESET",
                "TABLE_COMPLETED",
                "TABLE_QUARANTINED_ROWS",
                "TABLE_STARTED",
            ),
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
}


def _declared_metadata(namespace: Mapping[str, object]) -> frozenset[MetaData]:
    """The `MetaData` objects a namespace declares `Table`s against.

    The structural signature of a declaration module, and the whole of it: a
    module-level `MetaData`, and at least one module-level `Table` bound to that
    same object. Nothing here names a module, so a third declaration module is
    found by the same rule that finds the two that exist.

    Taken as a namespace rather than a module so the rule can be exercised on a
    synthetic one — `test_the_declaration_predicate_finds_a_module_it_has_never
    _seen` is what makes "would find a third" a measurement.
    """
    metadata = {value for value in namespace.values() if isinstance(value, MetaData)}
    return frozenset(
        value.metadata
        for value in namespace.values()
        if isinstance(value, Table) and value.metadata in metadata
    )


@cache
def _declaration_modules() -> dict[str, frozenset[MetaData]]:
    """Every module of `my_pa` that declares tables, by dotted name.

    Cached because the walk imports the whole package and three callers want it;
    the result is read and never mutated. Deliberately unguarded for the same
    reason `_live_closed_sets` is: a module of `my_pa` that cannot be imported is
    a defect, and swallowing it here would silently shrink this guard's universe.
    """
    found: dict[str, frozenset[MetaData]] = {}
    for module in pkgutil.walk_packages(my_pa.__path__, f"{my_pa.__name__}."):
        declared = _declared_metadata(vars(importlib.import_module(module.name)))
        if declared:
            found[module.name] = declared
    return found


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

    **A `MetaData` in the revision's namespace is an emission too**, and reading
    it is what closes `D-99`'s first blind spot. `4b9f0d27ac31` calls
    `METADATA.create_all(bind)` unqualified: it holds no `Table` and no
    `_TABLES`, so before this branch existed it returned `None` and the five
    closed sets `control_plane.py` derives were unreachable. The branch sits
    last, after `_TABLES`, because every revision that creates a *subset* of a
    shared declaration holds both — reading the `MetaData` first would report the
    whole declaration for revisions that emit five tables out of forty-six.

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
    metadata = [value for value in vars(module).values() if isinstance(value, MetaData)]
    if metadata:
        return [table for held in metadata for table in held.tables.values()]
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
    assert len(revisions) == 21
    assert len({revision for revision, _ in revisions}) == 21
    assert {"9c6b4a18ed72", "1a4c9e77b2d5", "2b7e9f4c1a83", "7e5a1fb93d62", "8b3f5c17d904"} <= {
        revision for revision, _ in revisions
    }


def test_the_live_closed_sets_are_discovered() -> None:
    """The reflection finds the sets, so a non-match means non-match.

    Without this, a broken walk would report zero live closed sets, every site
    would look undetected, and the allowlist assertion below would fail in a way
    that reads like a fix.
    """
    live = _live_closed_sets()
    assert len(live) > 40
    assert (
        live[frozenset({"calendar_event", "contact", "container", "file", "mail_message"})]
        == "my_pa.domain.source.provider.ObjectKind"
    )
    assert (
        live[frozenset({"pending_review"})]
        == "my_pa.domain.extraction.quarantine.QuarantineReviewState"
    )


def test_the_declaration_modules_are_discovered_structurally() -> None:
    """The walk finds both declaration modules, by shape rather than by name.

    Guards everything below that depends on the discovery: a walk that returned
    nothing would make `test_every_revision_declares_its_emission_readably`
    `continue` past every revision and stay green while checking nothing, which
    is the vacuous-guard shape this module exists to refuse.

    Subset, not equality. A third declaration module must be *covered* without
    an edit here; asserting the exact set would turn coverage into a chore and
    would be a count of a current set, which rots.
    """
    modules = _declaration_modules()
    assert set(modules) >= KNOWN_DECLARATIONS
    for name in KNOWN_DECLARATIONS:
        assert len(modules[name]) == 1, name


def test_the_declaration_predicate_finds_a_module_it_has_never_seen() -> None:
    """A third declaration module, found on a namespace with no name at all.

    Three cases, so the rule is neither blind nor indiscriminate:

    - a namespace holding a `MetaData` and a `Table` bound to it is a
      declaration, which is the third module nobody has written yet;
    - a `Table` bound to some *other* `MetaData` that the namespace does not hold
      is not — that is a revision importing tables, not declaring them, and
      calling it a declaration module would make `_emitted` read the importer;
    - a `MetaData` with no table of its own is not, which is the throwaway a
      revision might hold for reflection.
    """
    own = MetaData()
    foreign = MetaData()
    third = Table("third", own)

    assert _declared_metadata({"METADATA": own, "third": third}) == frozenset({own})
    assert _declared_metadata({"borrowed": Table("borrowed", foreign)}) == frozenset()
    assert _declared_metadata({"METADATA": own}) == frozenset()


def test_every_revision_declares_its_emission_readably() -> None:
    """A revision that reaches any declaration module must be readable here.

    Without this the guard has a hole shaped like a revision written in a new
    style: it would emit derived constraints, `_emitted` would return `None`,
    and the allowlist would stay green. `D-80` records the same shape arriving
    through a fixture rather than an assertion, and `D-99`'s first item was this
    same hole arriving through a second `MetaData`, which is why the module names
    below are discovered rather than written down.
    """
    declarations = _declaration_modules()
    held = {metadata for group in declarations.values() for metadata in group}
    for revision, module in _revisions():
        touches_declaration = any(
            isinstance(value, Table)
            or (isinstance(value, MetaData) and value in held)
            or (
                isinstance(value, list) and value and all(isinstance(item, Table) for item in value)
            )
            for value in vars(module).values()
        )
        source = (VERSIONS / f"{module.__name__.removeprefix('_revision_')}.py").read_text(
            encoding="utf-8"
        )
        if not touches_declaration and not any(name in source for name in declarations):
            continue
        assert _emitted(module) is not None, (
            f"{revision} reaches a declaration module but exposes no readable emission; "
            f"add {_EMISSION_LIST}, one of {_EMISSION_CALLABLES}, or the `MetaData` it creates"
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

    The revisions this campaign writes or edits carry no derived constraint at
    all. If one appears in the allowlist, the freeze that closed it has been
    undone and the residual class has grown rather than shrunk.

    Three revisions rather than two since the guard was widened, and the third
    is the disclosure `D-99` item (1) named: `4b9f0d27ac31` was always deriving,
    and is listed here for the first time because it is reachable for the first
    time. Every one of the three is a revision no package in this campaign edits,
    which is the property the assertion is actually about.
    """
    assert {revision for revision, *_ in ALLOWED} == {"8b3f5c17d904"}
    assert len(ALLOWED) == 5
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

    The last two cases are `D-99` item (1)'s: a revision holding only a
    `MetaData` is read through it, and a revision holding *both* is still read
    through `_TABLES`. The second is the control that keeps the first honest —
    without it, `4b9f0d27ac31` would be visible at the price of reporting all
    forty-six declared tables for the revisions that create five.
    """
    declaration = MetaData()
    live = Table("live", declaration, CheckConstraint("a IN ('x')", name="a_is_known"))
    frozen_copy = Table("frozen", MetaData(), CheckConstraint("a IN ('y')", name="a_is_known"))
    other = Table("other", declaration, CheckConstraint("b IN ('z')", name="b_is_known"))

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

    assert _emitted(_module(METADATA=declaration)) == [live, other]
    assert _emitted(_module(METADATA=declaration, _TABLES=[live])) == [live]


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
