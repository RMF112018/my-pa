"""The public shape of the `reports.manifest` answer (record lineage S4 contract section 7.4).

`{report_id, manifest_state, manifest_schema_version|null, manifest_sha256|null,
manifest_canonical|null}`:

* `recorded` -- the stored row unchanged; a client verifies it by recomputing
  `sha256(b"report-manifest-v1\\n" + manifest_canonical)`;
* `manifest_unavailable_legacy` -- an artifact committed before the S4
  revision: 3 nulls, and nothing is written (no legacy manifest is ever
  backfilled);
* `restricted_evidence` -- section 6.2's grant and family rule withholds a
  manifest whose Program state is not `not_attempted` from this remote reader:
  `manifest_sha256` **and** `manifest_canonical` are both `null` (R4-F20), so
  no digest of the withheld text is returned; `manifest_schema_version` is
  kept (it discloses nothing beyond the artifact's existence, which
  `reports.read` already discloses).

A plain frozen dataclass, as the v1 views are: every value is pre-serialised.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from my_pa.domain.intelligence.source_manifest import RecordedManifest
from my_pa.domain.program.vocabulary import ManifestState

__all__ = ["ReportManifestView"]


@dataclass(frozen=True, slots=True)
class ReportManifestView:
    """One artifact's `reports.manifest` answer."""

    report_id: str
    manifest_state: str
    manifest_schema_version: int | None
    manifest_sha256: str | None
    manifest_canonical: str | None

    def __post_init__(self) -> None:
        state = ManifestState(self.manifest_state)
        digests = (self.manifest_sha256, self.manifest_canonical)
        if state is ManifestState.RECORDED:
            if None in digests or self.manifest_schema_version is None:
                raise ValueError("a recorded manifest carries its text and digest")
        elif digests != (None, None):
            raise ValueError("a legacy or restricted manifest carries no text and no digest")
        if state is ManifestState.MANIFEST_UNAVAILABLE_LEGACY and (
            self.manifest_schema_version is not None
        ):
            raise ValueError("a legacy artifact has no manifest version")

    @classmethod
    def of(
        cls, report_id: str, manifest: RecordedManifest | None, *, released: bool
    ) -> ReportManifestView:
        """The answer for `manifest` (`None`: legacy), as section 6.2 releases it."""
        if manifest is None:
            return cls(
                report_id=report_id,
                manifest_state=ManifestState.MANIFEST_UNAVAILABLE_LEGACY.value,
                manifest_schema_version=None,
                manifest_sha256=None,
                manifest_canonical=None,
            )
        if not released:
            return cls(
                report_id=report_id,
                manifest_state=ManifestState.RESTRICTED_EVIDENCE.value,
                manifest_schema_version=manifest.manifest_schema_version,
                manifest_sha256=None,
                manifest_canonical=None,
            )
        return cls(
            report_id=report_id,
            manifest_state=ManifestState.RECORDED.value,
            manifest_schema_version=manifest.manifest_schema_version,
            manifest_sha256=manifest.manifest_sha256,
            manifest_canonical=manifest.manifest_canonical,
        )

    def to_canonical_dict(self) -> dict[str, object]:
        return asdict(self)
