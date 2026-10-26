"""The public shapes of the `commitments.v2.*` answers (record lineage S4 contract section 7.3).

Each v2 read answers exactly its v1 sibling's top-level keys, with the
Commitment objects replaced by the views here: every key of the v1 view
(`contracts.v1.commitments`, which is not edited) plus the 5 reference keys
of `CommitmentReferences`, and for a list entry also `evidence_state`. The v1
views are composed, never copied, so a v2 view cannot drift from the v1 shape
it extends.

**Owned references only** (section 12, D-16): `commitments.project_id` and
`situation_id` carry plain global foreign keys and `commitments.create` checks
only their pattern, so a stored id may name another Principal's record. A
reference is shown with `owned` when it names a record of this Principal,
`null` with `none` when nothing is stored, `null` with `not_owned` otherwise,
and `null` with `restricted` when the reader may not see the family (section
6.2). Another Principal's identifier is never echoed.

Plain frozen dataclasses, as the v1 views are: every value is pre-serialised.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from my_pa.contracts.v1.commitments import CommitmentListEntry, CommitmentView, WaitingOnEntry
from my_pa.domain.program.vocabulary import AcceptanceVerification, ReferenceState

__all__ = [
    "CommitmentReferences",
    "CommitmentV2ListEntry",
    "CommitmentV2View",
    "WaitingOnV2Entry",
]


@dataclass(frozen=True, slots=True)
class CommitmentReferences:
    """The 5 keys every v2 Commitment object adds to its v1 view (section 7.3)."""

    project_id: str | None
    project_reference: str
    situation_id: str | None
    situation_reference: str
    acceptance_verification: str

    def __post_init__(self) -> None:
        for identifier, state in (
            (self.project_id, self.project_reference),
            (self.situation_id, self.situation_reference),
        ):
            # An identifier is shown exactly when it is owned.
            if (identifier is not None) != (ReferenceState(state) is ReferenceState.OWNED):
                raise ValueError("a v2 reference shows its identifier exactly when it is owned")
        AcceptanceVerification(self.acceptance_verification)

    def to_canonical_dict(self) -> dict[str, object]:
        return asdict(self)


def _extended(base: dict[str, object], extra: dict[str, object]) -> dict[str, object]:
    clash = sorted(set(base) & set(extra))
    if clash:  # pragma: no cover - the field sets are disjoint by construction
        raise ValueError(f"a v2 key would shadow a v1 key: {clash}")
    return {**base, **extra}


@dataclass(frozen=True, slots=True)
class CommitmentV2View:
    """`CommitmentView` + the 5 reference keys (`commitments.v2.read`)."""

    view: CommitmentView
    references: CommitmentReferences

    def to_canonical_dict(self) -> dict[str, object]:
        return _extended(self.view.to_canonical_dict(), self.references.to_canonical_dict())


@dataclass(frozen=True, slots=True)
class CommitmentV2ListEntry:
    """`CommitmentListEntry` + `evidence_state` + the 5 reference keys (v2 list and search)."""

    entry: CommitmentListEntry
    evidence_state: str
    references: CommitmentReferences

    def to_canonical_dict(self) -> dict[str, object]:
        return _extended(
            self.entry.to_canonical_dict(),
            {"evidence_state": self.evidence_state, **self.references.to_canonical_dict()},
        )


@dataclass(frozen=True, slots=True)
class WaitingOnV2Entry:
    """`WaitingOnEntry` + the 5 reference keys (`commitments.v2.waiting_on`)."""

    entry: WaitingOnEntry
    references: CommitmentReferences

    def to_canonical_dict(self) -> dict[str, object]:
        return _extended(self.entry.to_canonical_dict(), self.references.to_canonical_dict())
