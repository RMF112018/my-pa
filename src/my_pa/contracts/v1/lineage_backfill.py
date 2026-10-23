"""The public shapes of the backfill dry run (record lineage S3 contract section 8.3).

`BackfillRunView` is one run, `BackfillItemView` one ledger item. Kept beside
`contracts.v1.record_lineage` so the S1/S2 lineage shapes stay free of the
backfill vocabulary.

**What these models cannot carry is the point of them.** No body, title,
description or other narrative of a native record (the Constraint
legacy-import redaction precedent), no origin-reference text (a free-text or
unsupported reference is only its shape-and-digest token, R3-F22), no candidate
anchor and no `principal_id`. `candidate_relation` is derived from the stored
candidate, not a column.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.lineage.cursor import instant_token
from my_pa.domain.lineage.vocabulary import ExistingLinkState, RelationType
from my_pa.domain.lineage_backfill.vocabulary import (
    BackfillClass,
    BackfillReason,
    BackfillRunState,
    BackfillSourceKind,
)

__all__ = ["BackfillItemView", "BackfillRunView"]


class BackfillRunView(StrictModel):
    """One backfill run (S3 section 8.3): its state, counts, digest and times."""

    run_id: str
    state: BackfillRunState
    validator_version: int = Field(ge=1)
    population_count: int = Field(ge=0)
    classified_count: int = Field(ge=0)
    plan_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_cutoff_at: datetime
    created_at: datetime
    classified_at: datetime | None

    @model_validator(mode="after")
    def _check(self) -> BackfillRunView:
        validate_identifier(self.run_id, IdKind.LINEAGE_BACKFILL_RUN)
        classified = self.state is BackfillRunState.CLASSIFIED
        if classified is (self.plan_digest is None) or classified is (self.classified_at is None):
            raise ValueError("a run carries its digest and time exactly when classified")
        if self.classified_count > self.population_count:
            raise ValueError("a run classifies within its population")
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """Every key; instants RFC 3339 UTC with microseconds."""
        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "validator_version": self.validator_version,
            "population_count": self.population_count,
            "classified_count": self.classified_count,
            "plan_digest": self.plan_digest,
            "source_cutoff_at": instant_token(self.source_cutoff_at),
            "created_at": instant_token(self.created_at),
            "classified_at": instant_token(self.classified_at),
        }


class BackfillItemView(StrictModel):
    """One ledger item (S3 section 8.3). Every settled key is `null` until classified."""

    item_no: int = Field(ge=1)
    source_kind: BackfillSourceKind
    source_family: str
    source_id: str
    source_ref: str = Field(min_length=1, max_length=256, pattern=r"^[!-~]+$")
    classification: BackfillClass | None
    reason: BackfillReason | None
    quarantined: bool
    candidate_relation: RelationType | None
    existing_link_id: str | None
    existing_link_state: ExistingLinkState | None

    @model_validator(mode="after")
    def _check(self) -> BackfillItemView:
        if (self.classification is None) is not (self.reason is None):
            raise ValueError("an item is classified with its reason")
        if (self.existing_link_id is None) is not (
            self.existing_link_state in (None, ExistingLinkState.NONE)
        ):
            raise ValueError("an item names an existing link exactly when one exists")
        if self.existing_link_id is not None:
            validate_identifier(self.existing_link_id, IdKind.RECORD_LINK)
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """Every key, closed tokens as their values."""
        return {
            "item_no": self.item_no,
            "source_kind": self.source_kind.value,
            "source_family": self.source_family,
            "source_id": self.source_id,
            "source_ref": self.source_ref,
            "classification": None if self.classification is None else self.classification.value,
            "reason": None if self.reason is None else self.reason.value,
            "quarantined": self.quarantined,
            "candidate_relation": (
                None if self.candidate_relation is None else self.candidate_relation.value
            ),
            "existing_link_id": self.existing_link_id,
            "existing_link_state": (
                None if self.existing_link_state is None else self.existing_link_state.value
            ),
        }
