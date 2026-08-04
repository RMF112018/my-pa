"""What a capture's text contains, and which mentions it makes.

Two record types, and the boundary between them is the thing
`docs/plans/mcv-completion-plan.md:1688` says outright it does not answer. The
canonical gloss is "versioned multi-label interpretation without relocating or
overwriting the Capture" (`docs/specs/canonical-product-definition/
09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:146`), and the boundary falls out of its
own words:

* **`CaptureClassification` is evidence-bound and about the text.** One row per
  `(version, scheme, scheme_version, label)`, each carrying the deterministic
  rule that produced it and **at least one span**. It answers "what does this
  text contain", and it can be cited.
* **`CaptureDomainAssignment` is interpretation and about placement.** It would
  carry no span, because there is no phrase in a note that means "this belongs
  to the Riverside project" — only a rule over the whole capture, a launch
  context, or a model. **It is not built here** (`D-94`): its only deterministic
  input is a context link, `capture_context_links` is WP-8's, and a table this
  package could never write a row into is what `AGENTS.md` section 2 rules out.

**`CaptureEntityMention` is built, and restricted** (`D-93`). The plan puts
`P-06` named-entity extraction out of scope and assigns `CaptureEntityMention`
— the object `P-06` produces — to this package, which is a real contradiction.
It is resolved by building the deterministic subset: document and project
identifiers and URLs, all of which `P-05` already produces
(`11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:75-77`), each with a span and each
always `unresolved`. People and organisations need an alias table that does not
exist, and resolution is `P-07`, which is excluded.

**The surface text is not stored.** `09_CANONICAL_…:147` asks a mention to carry
"exact surface text"; the span beside it already points at exactly that, in the
immutable version, and re-derives on read. A second copy would be a fourth place
capture content sits and would make the mention's "exact" a claim about the copy
rather than about the capture.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from my_pa.domain.capture.errors import CaptureError
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "CLASSIFICATION_SCHEME",
    "CLASSIFICATION_SCHEME_VERSION",
    "MAX_SCHEME_CHARACTERS",
    "CaptureClassification",
    "CaptureEntityMention",
    "CaptureLabel",
    "ClassificationError",
    "EntityType",
    "ResolutionState",
]

#: Scheme and rule names are bounded tokens for the same reason every other
#: writer-supplied token in this schema is.
MAX_SCHEME_CHARACTERS: Final = 64

#: The one labelling scheme this build has. Named and versioned rather than
#: implicit, because `09_CANONICAL_…:146` calls the interpretation *versioned*:
#: a later scheme adds rows beside these rather than reinterpreting them.
CLASSIFICATION_SCHEME: Final = "deterministic_cues"
CLASSIFICATION_SCHEME_VERSION: Final = "v1"


class ClassificationError(CaptureError):
    """A classification or mention refused to exist. Names the rule, never the text."""


class CaptureLabel(StrEnum):
    """What a deterministic `P-05` match says the text contains.

    Five labels, one per kind of match `11_…:71-79` names that this build can
    make without a resolver or a model. `11_…:81` is why they exist at all:
    "Deterministic matches still require **authority classification** and
    spans" — a match with no classification is a fact with no statement of what
    kind of fact it is.
    """

    #: A currency or amount pattern.
    FINANCIAL_MENTION = "financial_mention"
    #: A date or time expression, before `P-08` normalizes it.
    DATE_MENTION = "date_mention"
    #: A project or document identifier.
    IDENTIFIER_MENTION = "identifier_mention"
    #: A URL. Recorded, never fetched — `tests/architecture/
    #: test_capture_reaches_no_source.py` is what keeps that structural.
    EXTERNAL_REFERENCE = "external_reference"
    #: An explicit task or commitment language cue.
    COMMITMENT_MENTION = "commitment_mention"


class EntityType(StrEnum):
    """The entity kinds a deterministic mention can name (`D-93`).

    Three of `P-06`'s six. People, organizations, locations and topics are
    absent rather than declared-and-unreachable: the first two need an alias
    table that does not exist and the last two have no deterministic source at
    all.
    """

    DOCUMENT = "document"
    PROJECT = "project"
    URL = "url"


class ResolutionState(StrEnum):
    """How far a mention got towards an identity.

    One member. The ladder is `09_CANONICAL_…:96`'s `Identity` set — `resolved`,
    `candidate`, `unresolved`, `merge_proposed`, `split_proposed`, `superseded`
    — and **not** the `Proposal` set, which contains neither `candidate` nor
    `resolved`; `docs/plans/mcv-completion-plan.md:1689` names the wrong one.
    Resolution is `P-07` and `P-07` is excluded, so `unresolved` is the only
    state this build can reach, and the `D-78` precedent applies: one value now,
    a forward `ALTER` when a resolver arrives.
    """

    UNRESOLVED = "unresolved"


def _validated_token(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ClassificationError(f"{field_name} must be a bounded token")
    if not value or len(value) > MAX_SCHEME_CHARACTERS:
        raise ClassificationError(f"{field_name} must be a bounded token")
    return value


@dataclass(frozen=True, slots=True)
class CaptureClassification:
    """One label a deterministic rule attached to one capture version.

    Carries the span it was derived from, which is what makes it citable and
    what distinguishes it from a domain assignment.
    """

    classification_id: str
    version_id: str
    span_id: str
    scheme: str
    scheme_version: str
    label: CaptureLabel
    rule: str
    rule_version: str

    def __post_init__(self) -> None:
        validate_identifier(self.classification_id, IdKind.CAPTURE_CLASSIFICATION)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.span_id, IdKind.SPAN)
        if not isinstance(self.label, CaptureLabel):
            raise ClassificationError("a classification carries one known label")
        _validated_token(self.scheme, field_name="scheme")
        _validated_token(self.scheme_version, field_name="scheme version")
        _validated_token(self.rule, field_name="rule")
        _validated_token(self.rule_version, field_name="rule version")


@dataclass(frozen=True, slots=True)
class CaptureEntityMention:
    """One deterministic mention of an entity, bound to the span that names it."""

    mention_id: str
    version_id: str
    span_id: str
    entity_type: EntityType
    resolution_state: ResolutionState = ResolutionState.UNRESOLVED

    def __post_init__(self) -> None:
        validate_identifier(self.mention_id, IdKind.CAPTURE_ENTITY_MENTION)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.span_id, IdKind.SPAN)
        if not isinstance(self.entity_type, EntityType):
            raise ClassificationError("a mention names one known entity type")
        if self.resolution_state is not ResolutionState.UNRESOLVED:
            raise ClassificationError("this build resolves no mention")
