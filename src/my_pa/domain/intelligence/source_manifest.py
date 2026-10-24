"""The canonical report manifest of an Intelligence artifact (S4 contract sections 5.2-5.3).

Record lineage S4, WP-04C (ADR-015; CR-013). An artifact's Markdown digest
(`content_sha256`) is unchanged; the manifest binds, separately hashed,
everything that digest does not: the structured content as stored, the
dependencies' own digests and manifests, the provenance references and the
Program section (section 5.4). Pure: the caller hands in what it read back from
the committing transaction.

`J` is the one canonical encoding: sorted keys, compact separators, ASCII
escapes, no NaN. `ensure_ascii` escapes every character outside `0x20`-`0x7e`
-- the C0 controls, DEL (`0x7f`, as `\u007f`) and everything non-ASCII -- so a
manifest is always printable ASCII (`a_manifest_is_printable_ascii`), whatever
a provenance reference holds; a golden vector pins it. Every instant is UTC
with 6 fractional digits and a literal `Z` (the S3 `_lineage_instant` format).
The database CHECK `a_report_manifest_digest_is_its_canonical_text` recomputes
the digest from the stored canonical text.

Section 5.4: `program_reference_block` validates the reserved
`program_overview_ref` block of a synthesizer, reporter or morning-brief
artifact, and `program_section` / `server_state` build the manifest's
`ProgramManifestSection` from the claim and, when the commit-time recompute
ran, the server's overview as the committing caller saw it. `program_released`
is section 6.2's `reports.manifest` gate over a stored manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, cast

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.intelligence.catalog import IntelligenceStage
from my_pa.domain.intelligence.models import (
    IntelligenceArtifact,
    IntelligenceProvenanceRef,
)
from my_pa.domain.program.vocabulary import (
    MAX_PROGRAMS_PER_REQUEST,
    PROGRAM_OVERVIEW_FAMILIES,
    PROGRAM_REFERENCE_BLOCK_KEY,
    REPORT_MANIFEST_SCHEMA_VERSION,
    CandidateStatus,
    ManifestState,
    ProgramFamily,
    ProgramVerificationState,
    RecomputeFailure,
)

__all__ = [
    "MANIFEST_DIGEST_PREFIX",
    "PROGRAM_REFERENCE_STAGES",
    "STRUCTURED_CONTENT_DIGEST_PREFIX",
    "BuiltManifest",
    "DependencyDigests",
    "ProgramReferenceBlock",
    "ProgramReferenceError",
    "RecordedManifest",
    "build_manifest",
    "canonical",
    "manifest_digest",
    "manifest_instant",
    "program_reference_block",
    "program_released",
    "program_section",
    "recorded_release_requirement",
    "release_requirement",
    "server_state",
    "structured_content_sha256",
]

#: Section 5.2: the domain separator of the structured-content digest.
STRUCTURED_CONTENT_DIGEST_PREFIX: Final = b"report-structured-content-v1\n"
#: Section 5.3: the domain separator of the manifest digest (the CHECK's text).
MANIFEST_DIGEST_PREFIX: Final = b"report-manifest-v1\n"
#: Section 5.3: every provenance reference is uncertified.
_UNCERTIFIED_REFERENCE: Final = "uncertified_reference"


def canonical(value: object) -> bytes:
    """`J(x)` of section 5.2: sorted keys, compact, ASCII-escaped, no NaN."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def manifest_instant(value: datetime) -> str:
    """Section 5.3: `%Y-%m-%dT%H:%M:%S.%fZ` in UTC, never `+00:00`."""
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _optional_instant(value: datetime | None) -> str | None:
    return None if value is None else manifest_instant(value)


def manifest_digest(manifest_canonical: str) -> str:
    """Section 7.4: what a client recomputes, `sha256(b"report-manifest-v1\\n" + text)`."""
    return hashlib.sha256(MANIFEST_DIGEST_PREFIX + manifest_canonical.encode("ascii")).hexdigest()


def structured_content_sha256(value: Mapping[str, object] | None) -> str | None:
    """Section 5.2, over the structured content **as read back from the store**."""
    if value is None:
        return None
    return hashlib.sha256(STRUCTURED_CONTENT_DIGEST_PREFIX + canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class DependencyDigests:
    """One upstream artifact's stored digests, read in the committing transaction."""

    report_id: str
    dependency_role: str
    required: bool
    content_sha256: str
    structured_content_sha256: str | None
    #: `None` exactly when the upstream is a legacy artifact with no manifest.
    manifest_sha256: str | None
    #: The upstream manifest's recorded `release_requirement` (FR4-F01); `None`
    #: for a legacy upstream, which contributes nothing.
    release_requirement: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class BuiltManifest:
    """The section 4.1 row values of one manifest."""

    manifest_canonical: str
    manifest_sha256: str
    structured_content_sha256: str | None
    program_overview_sha256: str | None
    program_verification_state: str | None


def _date(value: date) -> str:
    return value.isoformat()


def _provenance(position: int, ref: IntelligenceProvenanceRef) -> dict[str, object]:
    return {
        "position": position,
        "source_system": ref.source_system,
        "source_ref": ref.source_ref,
        "relation": ref.relation.value,
        "source_url": ref.source_url,
        "observed_at": _optional_instant(ref.observed_at),
        "retrieved_at": _optional_instant(ref.retrieved_at),
        "evidence_subject_id": ref.evidence_subject_id,
        "certification": _UNCERTIFIED_REFERENCE,
    }


def _own_requirement(program: Mapping[str, object] | None) -> tuple[bool, set[str]]:
    """Section 6.2 for this manifest's own Program section alone."""
    if program is None or program.get("verification_state") in (
        None,
        ProgramVerificationState.NOT_ATTEMPTED.value,
    ):
        return False, set()
    families = {ProgramFamily.ENTITY.value, ProgramFamily.PROJECT.value}
    if program.get("server") is not None:
        families |= set(cast(Sequence[str], program.get("families_seen") or ()))
    return True, families


def release_requirement(
    program: Mapping[str, object] | None,
    upstream: Sequence[Mapping[str, object] | None],
) -> dict[str, object]:
    """Section 5.3 `release_requirement` (FR4-F01): this manifest's gate and its upstreams'.

    The union of the manifest's own section 6.2 requirement (nothing when
    `program` is null or `not_attempted`; else a `programs.overview` grant for
    `program_reporting_read`, the `entity` and `project` families and, with a
    server state, every family in `families_seen`) and every upstream's
    *recorded* requirement -- transitive by construction, since each upstream
    recorded its own upstreams'. A legacy upstream contributes nothing. Bound
    inside `M`, so it is hashed with everything else; `reports.manifest`
    releases a manifest to a remote reader only when the reader satisfies it,
    so no downstream text carries a withheld upstream digest to a reader who
    may not see that upstream.
    """
    grant, families = _own_requirement(program)
    for recorded in upstream:
        if recorded is None:
            continue
        grant = grant or bool(recorded["program_grant"])
        families |= set(cast(Sequence[str], recorded["families"]))
    return {"program_grant": grant, "families": sorted(families)}


def recorded_release_requirement(manifest_canonical: str) -> dict[str, object]:
    """A stored manifest's `release_requirement`, read back from its canonical text."""
    found = json.loads(manifest_canonical)["release_requirement"]
    return {"program_grant": bool(found["program_grant"]), "families": list(found["families"])}


def build_manifest(
    artifact: IntelligenceArtifact,
    *,
    stored_structured_content: Mapping[str, object] | None,
    dependencies: Sequence[DependencyDigests],
    program: Mapping[str, object] | None = None,
) -> BuiltManifest:
    """Section 5.3: the canonical manifest `M`, every key present, and its digest.

    `stored_structured_content` is the artifact's `structured_content` as read
    back from `intelligence_artifacts` in the committing transaction (section
    5.2). `program` is the section 5.3 `ProgramManifestSection`, or `None`.
    """
    structured_digest = structured_content_sha256(stored_structured_content)
    manifest: dict[str, object] = {
        "manifest_schema_version": REPORT_MANIFEST_SCHEMA_VERSION,
        "report": {
            "report_id": artifact.artifact_id,
            "cycle_run_id": artifact.cycle_run_id,
            "producer_run_id": artifact.producer_run_id,
            "stage": artifact.stage.value,
            "artifact_kind": str(artifact.artifact_kind),
            "focus_area_id": None
            if artifact.focus_area_id is None
            else artifact.focus_area_id.value,
            "source_lane": None if artifact.source_lane is None else artifact.source_lane.value,
            "report_date": _date(artifact.report_date),
            "version": artifact.version,
            "supersedes_report_id": artifact.supersedes_artifact_id,
            "schema_version": artifact.schema_version,
            "producer_prompt_version": artifact.producer_prompt_version,
            "title_sha256": hashlib.sha256(artifact.title.encode("utf-8")).hexdigest(),
            "content_sha256": artifact.content_sha256,
            "content_bytes": artifact.content_bytes,
            "committed_at": manifest_instant(artifact.committed_at),
            "artifact_state_at_commit": artifact.artifact_state.value,
            "producer_completeness": artifact.completeness,
        },
        "structured_content": {
            "present": stored_structured_content is not None,
            "sha256": structured_digest,
        },
        "candidate_status": (
            CandidateStatus.UNACCEPTED_CANDIDATE.value
            if artifact.stage is IntelligenceStage.COLLECTOR
            else CandidateStatus.NOT_A_CANDIDATE.value
        ),
        "dependencies": [
            {
                "report_id": dependency.report_id,
                "dependency_role": dependency.dependency_role,
                "required": dependency.required,
                "content_sha256": dependency.content_sha256,
                "structured_content_sha256": dependency.structured_content_sha256,
                "manifest_sha256": dependency.manifest_sha256,
                "manifest_state": (
                    ManifestState.MANIFEST_UNAVAILABLE_LEGACY.value
                    if dependency.manifest_sha256 is None
                    else ManifestState.RECORDED.value
                ),
            }
            # `COLLATE "C"` order: identifiers are ASCII, so code-point order.
            for dependency in sorted(dependencies, key=lambda item: item.report_id)
        ],
        "provenance": [
            _provenance(position, ref) for position, ref in enumerate(artifact.provenance, start=1)
        ],
        "program": None if program is None else dict(program),
        "release_requirement": release_requirement(
            program,
            [dependency.release_requirement for dependency in dependencies],
        ),
    }
    encoded = canonical(manifest)
    claimed = None if program is None else program.get("claimed_overview_sha256")
    state = None if program is None else program.get("verification_state")
    return BuiltManifest(
        manifest_canonical=encoded.decode("ascii"),
        manifest_sha256=hashlib.sha256(MANIFEST_DIGEST_PREFIX + encoded).hexdigest(),
        structured_content_sha256=structured_digest,
        program_overview_sha256=None if claimed is None else str(claimed),
        program_verification_state=None if state is None else str(state),
    )


# ---- section 5.4: the Program reference block and the manifest's Program section ----

#: Section 7.4: the stages that may carry a Program reference block; a
#: collector or researcher artifact is refused one.
PROGRAM_REFERENCE_STAGES: Final = frozenset(
    {
        IntelligenceStage.SYNTHESIZER,
        IntelligenceStage.REPORTER,
        IntelligenceStage.MORNING_BRIEF,
    }
)
#: Section 5.4: the version of the block's shape.
_BLOCK_SCHEMA_VERSION: Final = 1
_BLOCK_KEYS: Final = frozenset(
    {"block_schema_version", "program_entity_ids", "overview_sha256", "source_cutoff_at"}
)
_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_INSTANT_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"


class ProgramReferenceError(ValueError):
    """A `program_overview_ref` block that is malformed or on a stage that may not carry one.

    The application answers `invalid_request` / `structured_content` (section 7.5).
    """


@dataclass(frozen=True, slots=True)
class ProgramReferenceBlock:
    """Section 5.4: the Programs an overview was read for, and what the producer says it read."""

    program_entity_ids: tuple[str, ...]
    overview_sha256: str
    source_cutoff_at: str


def _is_instant_token(value: object) -> bool:
    """Exactly the section 5.3 instant format: it parses and re-renders unchanged."""
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.strptime(value, _INSTANT_FORMAT)
    except ValueError:
        return False
    return parsed.strftime(_INSTANT_FORMAT) == value


def _entity_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_PROGRAMS_PER_REQUEST:
        raise ProgramReferenceError("program_entity_ids holds 1..10 Entity ids")
    ids: list[str] = []
    for item in value:
        try:
            ids.append(validate_identifier(cast(str, item), IdKind.ENTITY))
        except InvalidIdentifierError:
            raise ProgramReferenceError("program_entity_ids holds Entity ids") from None
    if len(set(ids)) != len(ids):
        raise ProgramReferenceError("program_entity_ids are distinct")
    return tuple(ids)


def program_reference_block(
    structured_content: Mapping[str, object] | None, *, stage: IntelligenceStage
) -> ProgramReferenceBlock | None:
    """Section 5.4 / 7.4: the artifact's Program reference block, or `None` when it has none.

    Pure. A block must have exactly the 4 keys -- `block_schema_version` the
    integer 1, `program_entity_ids` 1..10 distinct `ent_` ids, `overview_sha256`
    64 lowercase hex, `source_cutoff_at` in the section 5.3 instant format --
    and the stage must be a synthesizer, reporter or morning brief; anything
    else is `ProgramReferenceError`.
    """
    if structured_content is None or PROGRAM_REFERENCE_BLOCK_KEY not in structured_content:
        return None
    if stage not in PROGRAM_REFERENCE_STAGES:
        raise ProgramReferenceError("a collector or researcher carries no Program reference")
    block = structured_content[PROGRAM_REFERENCE_BLOCK_KEY]
    if not isinstance(block, Mapping) or set(block) != _BLOCK_KEYS:
        raise ProgramReferenceError("a Program reference block has exactly its 4 keys")
    version = block["block_schema_version"]
    # `True == 1` in Python; a boolean is not the integer 1.
    if type(version) is not int or version != _BLOCK_SCHEMA_VERSION:
        raise ProgramReferenceError("block_schema_version is 1")
    digest = block["overview_sha256"]
    if not isinstance(digest, str) or _SHA256_HEX.match(digest) is None:
        raise ProgramReferenceError("overview_sha256 is 64 lowercase hex")
    cutoff = block["source_cutoff_at"]
    if not _is_instant_token(cutoff):
        raise ProgramReferenceError("source_cutoff_at is a section 5.3 instant")
    return ProgramReferenceBlock(
        program_entity_ids=_entity_ids(block["program_entity_ids"]),
        overview_sha256=digest,
        source_cutoff_at=cast(str, cutoff),
    )


def server_state(overview: Mapping[str, object]) -> dict[str, object]:
    """Section 5.3 `server`: the recomputed `programs.overview` answer, as served.

    `overview` is that answer's canonical form (`ProgramOverviewView`), already
    restricted to the committing caller's families: a `restricted` value stays
    `restricted` and a `not_reportable` one stays `null`. `scope` is the
    requested Program id, or `"portfolio"`; totals keep the answer's order
    (requested Programs, then the portfolio, each in catalogue order).
    """
    programs = cast(Sequence[Mapping[str, object]], overview["programs"])
    portfolio = cast(Mapping[str, object], overview["portfolio"])

    def totals(scope: str, rows: object) -> list[dict[str, object]]:
        return [
            {
                "scope": scope,
                "metric_id": row["metric_id"],
                "value": row["value"],
                "value_state": row["value_state"],
                "reasons": list(cast(Sequence[str], row["reasons"])),
            }
            for row in cast(Sequence[Mapping[str, object]], rows)
        ]

    return {
        "overview_sha256": overview["overview_sha256"],
        "source_cutoff_at": overview["source_cutoff_at"],
        "lineage_known_at": overview["lineage_known_at"],
        "metric_schema_version": overview["metric_schema_version"],
        "calculation_version": overview["calculation_version"],
        "complete_state": overview["complete_state"],
        "qualifiers": list(cast(Sequence[str], overview["qualifiers"])),
        "membership": [
            {
                "program_entity_id": program["program_entity_id"],
                "resolved_program_entity_id": program["resolved_program_entity_id"],
                "membership_state": program["membership_state"],
                "project_ids": list(cast(Sequence[str], program["project_ids"])),
            }
            for program in programs
        ],
        "portfolio_project_ids": list(cast(Sequence[str], portfolio["project_ids"])),
        "totals": [
            *(
                row
                for program in programs
                for row in totals(cast(str, program["program_entity_id"]), program["totals"])
            ),
            *totals("portfolio", portfolio["totals"]),
        ],
    }


def program_section(
    block: ProgramReferenceBlock,
    *,
    server: Mapping[str, object] | None = None,
    families_seen: Collection[ProgramFamily] | None = None,
    failure: RecomputeFailure | None = None,
) -> dict[str, object]:
    """Section 5.3 `ProgramManifestSection`: the claim beside what the server found.

    With `server` (and `families_seen`) the recompute ran: `verified_at_commit`
    exactly when the server's `overview_sha256` equals the claimed one, else
    `changed_since_read`. With `failure` it was attempted and failed:
    `recompute_failed`. With neither it was not attempted: only the claim.
    """
    if (server is None) != (families_seen is None):
        raise ValueError("a server state is bound together with the families it was read with")
    if server is not None and failure is not None:
        raise ValueError("a recompute either produced a server state or failed")
    seen: list[str] | None = None
    if server is None:
        state = (
            ProgramVerificationState.NOT_ATTEMPTED
            if failure is None
            else ProgramVerificationState.RECOMPUTE_FAILED
        )
    else:
        state = (
            ProgramVerificationState.VERIFIED_AT_COMMIT
            if server["overview_sha256"] == block.overview_sha256
            else ProgramVerificationState.CHANGED_SINCE_READ
        )
        # R4-F23: only the overview's 5 families, never `situation`.
        seen = sorted(
            family.value
            for family in set(cast(Collection[ProgramFamily], families_seen))
            if family in PROGRAM_OVERVIEW_FAMILIES
        )
    return {
        "block_schema_version": _BLOCK_SCHEMA_VERSION,
        "program_entity_ids": list(block.program_entity_ids),
        "claimed_overview_sha256": block.overview_sha256,
        "claimed_source_cutoff_at": block.source_cutoff_at,
        "verification_state": state.value,
        "recompute_failure": None if failure is None else failure.value,
        "families_seen": seen,
        "server": None if server is None else dict(server),
    }


@dataclass(frozen=True, slots=True)
class RecordedManifest:
    """One stored `intelligence_artifact_manifests` row, as `reports.manifest` reads it."""

    manifest_schema_version: int
    manifest_canonical: str
    manifest_sha256: str
    structured_content_sha256: str | None
    program_overview_sha256: str | None
    program_verification_state: str | None


def program_released(
    manifest: RecordedManifest,
    *,
    families: Collection[ProgramFamily],
    holds_program_grant: bool,
) -> bool:
    """Section 6.2 as amended by FR4-F01: whether a **remote** reader may read this manifest.

    The reader must satisfy the manifest's recorded `release_requirement`: the
    union of its own Program gate (ungated when its Program section is null or
    `not_attempted`; otherwise -- verified, changed or `recompute_failed`
    (R4-F27) -- a `programs.overview` grant for `program_reporting_read`
    (R4-F21), the `entity` and `project` families and, with a server state,
    every family in `families_seen` (R4-F14)) and every upstream manifest's,
    transitively, because the text binds each upstream's digest.
    """
    requirement = recorded_release_requirement(manifest.manifest_canonical)
    if requirement["program_grant"] and not holds_program_grant:
        return False
    visible = {ProgramFamily(family).value for family in families}
    return set(cast(Sequence[str], requirement["families"])) <= visible
