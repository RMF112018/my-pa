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

**The allowlist must shrink.** `ALLOWED` is the ten sites in the three revisions
`D-81` deliberately does not edit. Each entry pins the *exact* vocabulary that
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
module reads a constraint whose admitted vocabulary is a whole closed *set*. Six
constraints instead embed a single enum **value**, and every one of them is
outside this guard's coverage:

- `a_job_is_running_exactly_while_leased` and
  `a_capture_job_is_running_exactly_while_leased`, from `JobState.RUNNING`;
- `derived_text_is_never_source_original`, from
  `TrustLevel.SOURCE_BOUND_DERIVED`;
- `text_exists_exactly_when_something_was_extracted` and
  `only_a_supported_media_type_is_extracted`, from `ExtractionStatus.EXTRACTED`;
- `a_denial_records_its_reason_and_nothing_else_does`, from
  `AuditOutcome.DENIED`.

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
from sqlalchemy import CheckConstraint, Table

import my_pa

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "migrations" / "versions"

#: The module a revision must import from before it can derive anything: the one
#: place every table in the `knowledge` schema is declared.
DECLARATION = "my_pa.infrastructure.persistence.tables"

#: A revision that emits shared-declaration tables exposes them as one of these.
#: A callable is what a revision uses when it freezes something — it returns
#: copies with the derived constraints replaced. `_TABLES` is the plain case.
_EMISSION_CALLABLES: Final = ("_historical_audit_events", "_historical_capture_tables")
_EMISSION_LIST: Final = "_TABLES"

#: `column IN ('a', 'b')`, wherever it sits in a larger expression — the two
#: error-code constraints wrap theirs in `... IS NULL OR ...`.
_CLOSED_SET = re.compile(r"IN \(([^)]*)\)")
_LITERAL = re.compile(r"'([^']*)'")

#: Every still-derived site, with the revision that emits it, the closed set it
#: tracks, and the exact vocabulary it emits today. Ten sites in three revisions,
#: none of which WP-6 edits — freezing them is a separate package (`D-81`), and
#: WP-6 changes the membership of none of these sets, so none of them fires.
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
            "7e5a1fb93d62",
            "sources",
            "classification_is_known",
            "my_pa.domain.common.classification.Classification",
            ("private_local", "restricted_local", "synthetic_test"),
        ),
        (
            "7e5a1fb93d62",
            "sources",
            "provider_kind_is_known",
            "my_pa.domain.source.registry.SourceProviderKind",
            ("fixture",),
        ),
        (
            "7e5a1fb93d62",
            "source_objects",
            "kind_is_known",
            "my_pa.domain.source.provider.ObjectKind",
            ("container", "file"),
        ),
        (
            "7e5a1fb93d62",
            "jobs",
            "state_is_known",
            "my_pa.infrastructure.persistence.tables.JobState",
            ("failed", "queued", "running", "succeeded"),
        ),
        (
            "7e5a1fb93d62",
            "jobs",
            "last_error_code_is_a_public_error_code",
            "my_pa.contracts.v1.errors.ErrorCode",
            (
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
        ),
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
    }
)

#: The revisions that carry frozen literals, and the vocabulary each freezes.
#: Restated here rather than imported from the revision, for the reason
#: `test_capture_schema_migration.py:92-95` gives: a test that read the
#: revision's own literal would pass however that literal changed.
FROZEN: Final[dict[str, dict[str, tuple[str, ...]]]] = {
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
    """
    for name in _EMISSION_CALLABLES:
        emitter = getattr(module, name, None)
        if callable(emitter):
            produced = emitter()
            return list(produced) if isinstance(produced, list) else [produced]
    declared = getattr(module, _EMISSION_LIST, None)
    if isinstance(declared, list):
        return declared
    return None


def _closed_sets(table: Table) -> Iterator[tuple[str, frozenset[str]]]:
    for constraint in table.constraints:
        if not isinstance(constraint, CheckConstraint) or constraint.name is None:
            continue
        for match in _CLOSED_SET.finditer(str(constraint.sqltext)):
            values = frozenset(_LITERAL.findall(match.group(1)))
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
    assert len(revisions) == 11
    assert len({revision for revision, _ in revisions}) == 11
    assert {"9c6b4a18ed72", "1a4c9e77b2d5", "7e5a1fb93d62", "8b3f5c17d904"} <= {
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
    assert live[frozenset({"container", "file"})] == "my_pa.domain.source.provider.ObjectKind"
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

    The two revisions WP-6 writes or edits carry no derived constraint at all.
    If one appears in the allowlist, the freeze that closed it has been undone
    and the residual class has grown rather than shrunk.
    """
    assert {revision for revision, *_ in ALLOWED} == {"7e5a1fb93d62", "8b3f5c17d904"}
    assert len(ALLOWED) == 10
    assert not {revision for revision, *_ in ALLOWED} & set(FROZEN)


@pytest.mark.parametrize("revision", sorted(FROZEN))
def test_a_frozen_revision_emits_its_recorded_vocabulary(revision: str) -> None:
    """The other end of the property, so a plant proves something.

    A member added to `Capability`, `DenialReason`, `JobState` or any of the six
    capture sets must leave these twelve constraint texts exactly where they are.
    That is what "the revision goes on denoting one schema" means, and it is the
    half the reviewer measured as broken for `denial_reason`.
    """
    module = dict(_revisions())[revision]
    tables = _emitted(module)
    assert tables is not None
    emitted = {
        name: tuple(sorted(values)) for table in tables for name, values in _closed_sets(table)
    }
    for name, expected in FROZEN[revision].items():
        assert emitted[name] == tuple(sorted(expected)), name


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
