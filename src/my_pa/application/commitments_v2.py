"""The `commitments.v2.*` reads' reference states and batched page reads (S4 section 7.3).

Record lineage S4 contract sections 6.2, 7.3 and 12 (D-16, D-22). The 4 v2
handlers in `application.service` answer exactly their v1 siblings' requests
and top-level keys; what this module adds is everything a v2 page reads
**once per page**, whatever its size:

* the reference check -- which stored `project_id` / `situation_id` values
  name this Principal's own records, with each Situation's kind -- in one
  statement (`reference_owners`), turned into `CommitmentReferences` by the
  pure rule of `project_reference` and `situation_reference`;
* the counterparty projections of a page (`counterparties`);
* the follow-up Tasks of a `waiting_on` page (`follow_ups_for_commitments`);
* the `project_ids` filter's ownership check, the same one statement.

The v1 siblings keep their per-row reads unchanged (D-22): nothing here is
called by a v1 handler. Every read is on the request's own unit of work and
names the caller's Principal; nothing here writes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from my_pa.application.errors import NotFoundError, SafeDetail
from my_pa.contracts.ports import CommitmentManagementRepository, TaskManagementRepository
from my_pa.contracts.v1.commitments_v2 import CommitmentReferences
from my_pa.domain.lineage.vocabulary import SituationKind
from my_pa.domain.program.vocabulary import (
    AcceptanceVerification,
    ProgramFamily,
    ReferenceState,
)
from my_pa.domain.situation.continuity import ContinuityEvidenceState
from my_pa.domain.task.commitment import Commitment
from my_pa.domain.task.task import Task

__all__ = [
    "CommitmentPageReads",
    "acceptance_verification",
    "page_follow_ups",
    "project_reference",
    "read_commitment_page",
    "require_owned_projects",
    "situation_reference",
]

type Counterparty = dict[str, str] | None


def acceptance_verification(commitment: Commitment) -> AcceptanceVerification:
    """`unverified_review_reference` for a natively accepted Commitment, else `not_accepted`.

    No capability-reachable route verifies a Commitment's acceptance (S2 D-05
    and D-17, S3 D-11), so a native `accepted` is never shown as proven.
    """
    if commitment.evidence_state is ContinuityEvidenceState.ACCEPTED:
        return AcceptanceVerification.UNVERIFIED_REVIEW_REFERENCE
    return AcceptanceVerification.NOT_ACCEPTED


def project_reference(
    stored: str | None, owned: frozenset[str], families: frozenset[ProgramFamily]
) -> tuple[str | None, ReferenceState]:
    """The shown `project_id` and its state (sections 6.2 and 7.3).

    `restricted` whenever the reader may not see the `project` family; else
    `none` when nothing is stored, `owned` (shown) for this Principal's
    Project, `not_owned` (never echoed) otherwise.
    """
    if ProgramFamily.PROJECT not in families:
        return None, ReferenceState.RESTRICTED
    if stored is None:
        return None, ReferenceState.NONE
    if stored in owned:
        return stored, ReferenceState.OWNED
    return None, ReferenceState.NOT_OWNED


def situation_reference(
    stored: str | None, kinds: Mapping[str, str], families: frozenset[ProgramFamily]
) -> tuple[str | None, ReferenceState]:
    """The shown `situation_id` and its state, gated by the referenced kind (R4-F17).

    An owned `issue_workstream` needs the `issue` family and an owned
    `context` Situation the `situation` family; a reader who sees neither gets
    `restricted` for any stored id, so a missing kind discloses nothing.
    `none` when nothing is stored; `not_owned` (never echoed) for an id that is
    not this Principal's Situation.
    """
    if stored is None:
        return None, ReferenceState.NONE
    if not families & {ProgramFamily.ISSUE, ProgramFamily.SITUATION}:
        return None, ReferenceState.RESTRICTED
    kind = kinds.get(stored)
    if kind is None:
        return None, ReferenceState.NOT_OWNED
    needed = (
        ProgramFamily.ISSUE if kind == SituationKind.ISSUE_WORKSTREAM else ProgramFamily.SITUATION
    )
    if needed not in families:
        return None, ReferenceState.RESTRICTED
    return stored, ReferenceState.OWNED


def require_owned_projects(
    repository: CommitmentManagementRepository,
    principal_id: str,
    project_ids: Sequence[str] | None,
    families: frozenset[ProgramFamily],
) -> None:
    """A `project_ids` filter names only this Principal's Projects, else `not_found`.

    One statement for the set; absent and foreign answer alike. A remote reader
    who may not see the `project` family sees no Project, so every id it names
    answers as an absent one (the section 6.2 invisible-root rule).
    """
    if project_ids is None:
        return
    if ProgramFamily.PROJECT not in families:
        raise NotFoundError(SafeDetail.PROJECT_IDS)
    owned = repository.reference_owners(principal_id, project_ids=project_ids, situation_ids=())
    if not set(project_ids) <= owned.projects:
        raise NotFoundError(SafeDetail.PROJECT_IDS)


@dataclass(frozen=True, slots=True)
class CommitmentPageReads:
    """What one v2 page read once: each Commitment's references and each counterparty."""

    references: Mapping[str, CommitmentReferences]
    counterparties: Mapping[str, Counterparty]

    def references_of(self, commitment: Commitment) -> CommitmentReferences:
        return self.references[commitment.commitment_id]

    def counterparty_of(self, commitment: Commitment) -> Counterparty:
        return self.counterparties.get(commitment.counterparty_entity_id)


def read_commitment_page(
    repository: CommitmentManagementRepository,
    principal_id: str,
    page: Sequence[Commitment],
    families: frozenset[ProgramFamily],
) -> CommitmentPageReads:
    """The page's reference check and counterparty projections: at most 2 statements.

    Only the ids a reader could be shown are looked up: none of a family it
    may not see.
    """
    project_ids = (
        tuple(dict.fromkeys(c.project_id for c in page if c.project_id is not None))
        if ProgramFamily.PROJECT in families
        else ()
    )
    situation_ids = (
        tuple(dict.fromkeys(c.situation_id for c in page if c.situation_id is not None))
        if families & {ProgramFamily.ISSUE, ProgramFamily.SITUATION}
        else ()
    )
    owned_projects: frozenset[str] = frozenset()
    kinds: Mapping[str, str] = {}
    if project_ids or situation_ids:
        owners = repository.reference_owners(
            principal_id, project_ids=project_ids, situation_ids=situation_ids
        )
        owned_projects, kinds = owners.projects, owners.situation_kinds
    references: dict[str, CommitmentReferences] = {}
    for commitment in page:
        shown_project, project_state = project_reference(
            commitment.project_id, owned_projects, families
        )
        shown_situation, situation_state = situation_reference(
            commitment.situation_id, kinds, families
        )
        references[commitment.commitment_id] = CommitmentReferences(
            project_id=shown_project,
            project_reference=project_state.value,
            situation_id=shown_situation,
            situation_reference=situation_state.value,
            acceptance_verification=acceptance_verification(commitment).value,
        )
    found = repository.counterparties(
        principal_id, tuple(dict.fromkeys(c.counterparty_entity_id for c in page))
    )
    counterparties: dict[str, Counterparty] = {
        entity_id: {"entity_id": option.entity_id, "display_name": option.display_name}
        for entity_id, option in found.items()
    }
    return CommitmentPageReads(references=references, counterparties=counterparties)


def page_follow_ups(
    repository: TaskManagementRepository, principal_id: str, page: Sequence[Commitment]
) -> Mapping[str, Task]:
    """The follow-up Task of each Commitment of a `waiting_on` page, in one statement."""
    return repository.follow_ups_for_commitments(
        principal_id, tuple(commitment.commitment_id for commitment in page)
    )
