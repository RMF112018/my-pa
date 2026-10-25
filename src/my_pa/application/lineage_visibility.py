"""Per-family lineage visibility for remote readers (record lineage S3 section 6.4).

A **local** caller holds no capability grants and sees every family. A
**remote** caller sees a record family only while it holds a grant, for one of
that read's permitted purposes, on one of the family's reads
(`LINEAGE_FAMILY_READS`, precedent `RECORD_EVENT_FAMILY_READS`); an evidence
anchor is visible iff its source family is (a note version through the Meeting
reads, a Capture version and a legacy Capture root through the Capture reads).

**The grant re-check (R3-F13).** `invoke` does not consult the grant set
(G1-RD-008), so every lineage read handler asks `require_read_grant` first: a
remote caller without a grant on the called capability, for one of its
permitted purposes, is answered `unsupported` -- the capability is hidden from a
client that was never granted it, exactly as `_record_events_list` and
`_knowledge_plane` do.

Nothing here reads a row. The rules every read applies with it: an invisible
root is `not_found` / `origin`; an invisible Issue is never a candidate; an
invisible node is not emitted, expanded or counted; a typed edge is emitted
only when both endpoints are visible; an invisible anchor is dropped; and the
answer says `restricted_evidence` (or `restricted: true`) -- never a count --
whenever anything was withheld.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from my_pa.application.errors import UnsupportedError
from my_pa.domain.identity.operation import Capability, granted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.lineage.cursor import grant_digest
from my_pa.domain.lineage.model import EvidenceAnchor, RecordRef
from my_pa.domain.lineage.vocabulary import (
    LINEAGE_FAMILY_READS,
    EvidenceSourceFamily,
    RecordFamily,
)

__all__ = [
    "ANCHOR_FAMILIES",
    "LineageVisibility",
    "lineage_visibility",
    "require_read_grant",
    "require_write_grant",
]

type Grants = frozenset[tuple[Capability, Purpose | None]]

#: Section 6.4: the record family whose reads make an anchor's source visible.
ANCHOR_FAMILIES: Final = {
    EvidenceSourceFamily.MEETING_NOTE_VERSION: RecordFamily.MEETING_NOTE_VERSION,
    EvidenceSourceFamily.CAPTURE_VERSION: RecordFamily.CAPTURE_VERSION,
    EvidenceSourceFamily.CAPTURE: RecordFamily.CAPTURE_VERSION,
}


@dataclass(frozen=True, slots=True)
class LineageVisibility:
    """What one caller may see of the lineage plane, and the digest that binds it.

    `families` is every family for a local caller. `grant_digest` is the
    section 6.4 digest a cursor's scope carries (`None` locally).
    """

    families: frozenset[RecordFamily]
    remote: bool
    grant_digest: str | None

    def sees(self, ref: RecordRef) -> bool:
        """Whether a record of this family may be shown, expanded or counted."""
        return ref.family in self.families

    def sees_family(self, family: RecordFamily) -> bool:
        return family in self.families

    def sees_anchor(self, anchor: EvidenceAnchor) -> bool:
        """Whether an anchor's source family is visible."""
        return ANCHOR_FAMILIES[anchor.source_family] in self.families


def require_read_grant(grants: Grants | None, capability: Capability) -> None:
    """R3-F13: a remote caller without a grant on `capability` is `unsupported`.

    `None` (a local caller) always passes. A grant for a purpose the
    capability does not permit admits nothing, as at the remote boundary.
    """
    if grants is not None and not granted_purposes(capability, grants):
        raise UnsupportedError()


def require_write_grant(grants: Grants | None, capability: Capability) -> None:
    """S3.1 section 6.4 step 1: the write analogue of `require_read_grant` (R31-F01).

    A remote caller without a grant on the open write it called, for one of
    that write's permitted purposes, is `unsupported`: `invoke` does not consult
    the grant set (G1-RD-008), so the handler re-checks it as defence in depth.
    `None` (a local caller) always passes.
    """
    if grants is not None and not granted_purposes(capability, grants):
        raise UnsupportedError()


def _family_visible(family: RecordFamily, grants: Grants) -> bool:
    return any(
        granted_purposes(Capability(read), grants) for read in sorted(LINEAGE_FAMILY_READS[family])
    )


def _pairs(grants: Iterable[tuple[Capability, Purpose | None]]) -> list[tuple[str, str | None]]:
    return [
        (capability.value, None if purpose is None else purpose.value)
        for capability, purpose in grants
    ]


def lineage_visibility(grants: Grants | None, capability: Capability) -> LineageVisibility:
    """The caller's visible families and grant digest for a read of `capability`."""
    if grants is None:
        return LineageVisibility(families=frozenset(RecordFamily), remote=False, grant_digest=None)
    return LineageVisibility(
        families=frozenset(family for family in RecordFamily if _family_visible(family, grants)),
        remote=True,
        grant_digest=grant_digest(_pairs(grants), capability.value),
    )
