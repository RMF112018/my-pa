"""The canonical report manifest of an Intelligence artifact (S4 contract sections 5.2-5.3).

Record lineage S4, WP-04C (ADR-015; CR-013). An artifact's Markdown digest
(`content_sha256`) is unchanged; the manifest binds, separately hashed,
everything that digest does not: the structured content as stored, the
dependencies' own digests and manifests, the provenance references and the
Program section (section 5.4). Pure: the caller hands in what it read back from
the committing transaction.

`J` is the one canonical encoding: sorted keys, compact separators, ASCII
escapes, no NaN. Every instant is UTC with 6 fractional digits and a literal
`Z` (the S3 `_lineage_instant` format). The database CHECK
`a_report_manifest_digest_is_its_canonical_text` recomputes the digest from the
stored canonical text.

This module carries the part worker M1 needs so every artifact committed after
the S4 revision has its manifest (the deferred `an_artifact_has_its_manifest`);
the Program reference block's validation and the commit-time recompute are
worker M5's (S4 contract section 9).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.intelligence.catalog import IntelligenceStage
from my_pa.domain.intelligence.models import (
    IntelligenceArtifact,
    IntelligenceProvenanceRef,
)
from my_pa.domain.program.vocabulary import (
    REPORT_MANIFEST_SCHEMA_VERSION,
    CandidateStatus,
    ManifestState,
)

__all__ = [
    "MANIFEST_DIGEST_PREFIX",
    "STRUCTURED_CONTENT_DIGEST_PREFIX",
    "BuiltManifest",
    "DependencyDigests",
    "build_manifest",
    "canonical",
    "manifest_instant",
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
