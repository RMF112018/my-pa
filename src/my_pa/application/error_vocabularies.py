"""Which closed vocabulary a rejected field accepts, by the detail that names it.

`problem_detail` lists the acceptable values of a rejected closed-vocabulary
field (`ProblemDetail.allowed_values`). Most raise sites hand the vocabulary
over themselves -- the shared helpers that check a value against an enum build
their refusal with `errors.invalid_choice` -- and this table is the fallback
for a refusal that names only its detail.

**A detail is in this table only when it is unambiguous.** Every raise site of
the detail, across the whole of `src/`, refuses the same field against the same
closed vocabulary: a member outside it, the wrong type, a missing required
member, or a malformed list of members. A detail that also names another
vocabulary (`selector`, `lifecycle_state`, `status`, `disposition`, `subject`,
`role`, `states`, ...) or a refusal that is not about membership (a valid member
that contradicts another field, or one the subject does not permit) is left
out: listing a vocabulary there would answer a question the caller did not
ask. Those sites list their vocabulary explicitly or not at all.

**Never tenant data.** Every value here is a member of a domain enum, so the
table cannot list an identifier, a name, or free text. No detail naming an
identifier, a key, a reference or a free-text field is mapped (a guard test
holds both rules), and the report-kind detail `ARTIFACT_KIND` is deliberately
absent: the kinds a Principal may use are a per-Principal registry, so its
raise sites pass the acting Principal's kinds explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.application.errors import SafeDetail
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.context.prepared import ContextPlane
from my_pa.domain.intelligence.catalog import SourceLaneId
from my_pa.domain.record_events import RecordEventFamily
from my_pa.domain.relationship.authoring import CallerNamespace
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    AffiliationTypeCode,
    AliasType,
    AssignmentType,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    EntityRelationshipType,
    NameTypeCode,
    ParticipationStatusCode,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
)
from my_pa.domain.relationship.governance import ObservationKind
from my_pa.domain.relationship.normalization import ExternalIdentifierNamespace
from my_pa.domain.relationship.proposal_payload import EntityProposalKind
from my_pa.domain.task.lifecycle import TaskOriginKind, TaskPriority

__all__ = ["STATIC_VOCABULARIES", "VOCABULARY_SOURCES"]

#: The domain enum each unambiguous detail is bound to, grouped by plane.
VOCABULARY_SOURCES: Final[Mapping[SafeDetail, type[StrEnum]]] = MappingProxyType(
    {
        # Captures and prepared context.
        SafeDetail.CAPTURE_KIND: CaptureKind,
        SafeDetail.REQUESTED_PLANES: ContextPlane,
        # Tasks.
        SafeDetail.PRIORITY: TaskPriority,
        SafeDetail.ORIGIN_KIND: TaskOriginKind,
        # Record Event feed.
        SafeDetail.RECORD_FAMILIES: RecordEventFamily,
        # Reports.
        SafeDetail.SOURCE_LANE: SourceLaneId,
        # Entities and the relationship plane.
        SafeDetail.ADDRESS_TYPE_CODE: AddressTypeCode,
        SafeDetail.AFFILIATION_TYPE_CODE: AffiliationTypeCode,
        SafeDetail.ALIAS_TYPE: AliasType,
        SafeDetail.ALIAS_TYPES: AliasType,
        SafeDetail.ASSIGNMENT_TYPE: AssignmentType,
        SafeDetail.METHOD_TYPE_CODE: CommunicationMethodTypeCode,
        SafeDetail.NAME_TYPE_CODE: NameTypeCode,
        SafeDetail.NAMESPACE: CallerNamespace,
        SafeDetail.NAMESPACES: ExternalIdentifierNamespace,
        SafeDetail.OBSERVATION_KIND: ObservationKind,
        SafeDetail.PROPOSAL_KIND: EntityProposalKind,
        SafeDetail.RELATIONSHIP_STATUS_CODE: ParticipationStatusCode,
        SafeDetail.RELATIONSHIP_TYPE: EntityRelationshipType,
        SafeDetail.RELATIONSHIP_TYPES: EntityRelationshipType,
        SafeDetail.ROLE_BASIS_CODE: RoleBasisCode,
        SafeDetail.STAKEHOLDER_CLASS_CODE: StakeholderClassCode,
        SafeDetail.STAKEHOLDER_SIDE_CODE: StakeholderSideCode,
        SafeDetail.USAGE_CONTEXT_CODE: CommunicationUsageContextCode,
        SafeDetail.VERIFICATION_STATUS_CODE: CommunicationVerificationStatusCode,
    }
)

#: Each detail's acceptable values, in the enum's declaration order.
STATIC_VOCABULARIES: Final[Mapping[SafeDetail, tuple[str, ...]]] = MappingProxyType(
    {
        detail: tuple(member.value for member in vocabulary)
        for detail, vocabulary in VOCABULARY_SOURCES.items()
    }
)
