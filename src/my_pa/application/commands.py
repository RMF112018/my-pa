"""One command per capability: what a transport has to have decided already.

A command is the normalized form of a request, and it is where the request stops
being protocol. A transport parses JSON, a query string, or an MCP tool call and
produces one of these; from here on nothing knows which it was. That is what
makes the parity `SPEC-AC-001` asks for provable at all — two transports that
build equal commands have produced equal requests, and there is one validation
path rather than one per protocol.

**Bounded on construction, like every other request value in this system.**
`domain.source.enrollment.EnrollmentRequest` and `domain.search.query.SearchRequest`
both enforce their bounds in `__post_init__` so that no code path can hold an
unbounded request and check it later, and these follow that rule. What they
check is only what is decidable without configuration: identifier shape,
exactly-one-of selectors, and the sign of a count. A bound that comes from
validated `MY_PA_` settings — page size, fetch ceiling, enrollment depth — is
checked where the limits are, in `application.service`, because a command must
not be able to hold a copy of a configured limit that could disagree with the
one being enforced.

Failures here are `InvalidRequestError` rather than `ValueError`, so a transport
that builds a command from a caller's payload gets a classified public error at
the point of construction and does not have to invent one.

**The principal is not here.** Nothing in a command says who is asking or why.
Authority comes from authenticated context (`docs/specs` section 9.6), and a
command that carried a principal would be a caller-supplied identity one
`is_operator` away from being trusted. The purpose is separate for the same
reason: it is declared in the request metadata the composition root binds, not
inside the payload the caller controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.capture.proposal import MAX_NORMALIZED_VALUE_CHARACTERS
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import NaiveDatetimeError, ensure_utc
from my_pa.domain.documents.managed import (
    ManagedDocumentError,
    validate_managed_media_type,
    validate_managed_title,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.relationship.event import RelationshipEventType
from my_pa.domain.situation.continuity import ClosureEvidenceKind

__all__ = [
    "AddProjectCommand",
    "ArchiveManagedDocument",
    "ArchiveManagedDocumentCommand",
    "CloseSituationCommand",
    "Command",
    "CreateCapture",
    "CreateManagedDocument",
    "CreateManagedDocumentCommand",
    "CreateProject",
    "CreateSituation",
    "CreateTask",
    "DecideReviewCase",
    "EnrollSource",
    "EnterFrameCommand",
    "FetchSource",
    "GetCapabilities",
    "GetCorpusCoverage",
    "GetPulse",
    "GetSourceMetadata",
    "GetSourceStatus",
    "LinkSituationToProjectCommand",
    "ListCaptures",
    "ListManagedDocuments",
    "ListManagedDocumentsCommand",
    "ListProjects",
    "ListReviewCases",
    "ListSituations",
    "ListSources",
    "OpenSituationCommand",
    "ReadCapture",
    "ReadKnowledge",
    "ReadManagedDocument",
    "ReadManagedDocumentCommand",
    "RecordRelationshipEventCommand",
    "Representation",
    "RestoreManagedDocument",
    "RestoreManagedDocumentCommand",
    "RevealSubject",
    "ReviseCapture",
    "ReviseManagedDocument",
    "ReviseManagedDocumentCommand",
    "SearchCaptures",
    "SearchKnowledge",
    "TraceObjectCommand",
]


class Representation(StrEnum):
    """How `sources.fetch` should hand back an object.

    `docs/specs` section 9.4 names both. They are different disclosures rather
    than different encodings: `normalized_text` is what the extractor could read
    and is refused explicitly when it could not, while `raw_bytes` is the bytes
    themselves and says nothing about whether they are text.
    """

    RAW_BYTES = "raw_bytes"
    NORMALIZED_TEXT = "normalized_text"


def _identifier(value: str, kind: IdKind | None, detail: SafeDetail) -> str:
    """Validate one identifier, reporting the field rather than the value.

    `kind` may be `None`, which validates the *shape* — a known prefix and an
    8-64 character opaque suffix — without requiring one particular prefix. One
    command needs that: `RevealSubject` accepts more than one subject kind and
    answers about the kinds it does not traverse rather than refusing them, so
    pinning a kind here would turn a coverage answer into a validation error.
    """
    try:
        return validate_identifier(value, kind)
    except InvalidIdentifierError:
        pass
    # Raised outside the handler so the original — which renders the rejected
    # value — is not left in `__context__` for a traceback to print.
    raise InvalidRequestError(detail)


def _moment(value: datetime | None, detail: SafeDetail) -> datetime | None:
    """Validate one caller-supplied time, reporting the field rather than the value.

    A naive datetime is refused rather than assumed to be UTC, which is the rule
    `domain.common.time` states: guessing an offset would fabricate authority
    over a moment nobody stated. `None` is a real answer here and stays one — a
    transport may supply no device clock, and a note may be about no particular
    moment. Defaulting either to the request clock would invent a fact about the
    world out of a fact about this process, which is what `QC-AC-012` exists to
    prevent.
    """
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise InvalidRequestError(detail)
    try:
        ensure_utc(value)
    except NaiveDatetimeError:
        pass
    else:
        return value
    raise InvalidRequestError(detail)


def _text(value: str, detail: SafeDetail) -> str:
    """Check that a capture carries text, without reading it into a message.

    Only presence and type. The bound and the emptiness rule belong to
    `domain.capture.version.CaptureContent`, which the handler builds, for the
    reason this module's docstring gives: what a command checks is what is
    decidable without configuration, and refusing here as well would be a second
    place the same rule could drift.
    """
    if not isinstance(value, str):
        raise InvalidRequestError(detail)
    return value


def _positive(value: int | None, detail: SafeDetail) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(detail)
    if value < 1:
        raise InvalidRequestError(detail)
    return value


def _idempotency_key(value: str) -> str:
    """A write carries a non-empty idempotency key, and the key never reaches a message."""
    if not value:
        raise InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
    return value


def _managed_title(value: str) -> str:
    """The domain's own title rule, reported as a public refusal naming the field.

    The rule stays in `domain.documents.managed` — one place — and this converts
    its domain error into the transport-facing one, exactly as `_identifier`
    converts `InvalidIdentifierError`. The domain error's message renders the
    rejected title, so it is left behind rather than chained.
    """
    try:
        return validate_managed_title(value)
    except ManagedDocumentError:
        pass
    raise InvalidRequestError(SafeDetail.TITLE)


def _managed_media_type(value: str) -> str:
    """The closed managed media-type set, as a public refusal naming the field."""
    try:
        return validate_managed_media_type(value)
    except ManagedDocumentError:
        pass
    raise InvalidRequestError(SafeDetail.MEDIA_TYPE)


def _managed_content(value: bytes) -> bytes:
    """Check that a managed write carries bytes, without reading them into a message.

    Presence and type only. The size bound belongs to
    `domain.documents.managed.ManagedContent`, which the handler builds, for the
    reason `_text` gives: a bound checked twice is a bound that can drift. The
    transport's own `MAX_REQUEST_BYTES` refuses a larger document earlier still.
    """
    if not isinstance(value, bytes | bytearray):
        raise InvalidRequestError(SafeDetail.CONTENT)
    return bytes(value)


@dataclass(frozen=True, slots=True)
class GetCapabilities:
    """`capabilities.get`: what this build supports and under which limits."""

    capability: ClassVar[Capability] = Capability.CAPABILITIES_GET


@dataclass(frozen=True, slots=True)
class ListSources:
    """`sources.list`: the immediate children of one container.

    `parent_object_id` omitted means the source's configured logical root, which
    is not the host root and not a volume. `enrollment_id` disambiguates when a
    principal holds more than one grant over the source; with one grant it is
    unnecessary, and with several its absence is `ambiguous_request` rather than
    a guess about which coverage to disclose.
    """

    capability: ClassVar[Capability] = Capability.SOURCES_LIST

    source_id: str
    parent_object_id: str | None = None
    enrollment_id: str | None = None
    page_size: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.source_id, IdKind.SOURCE, SafeDetail.SOURCE_ID)
        if self.parent_object_id is not None:
            _identifier(self.parent_object_id, IdKind.SOURCE_OBJECT, SafeDetail.SOURCE_OBJECT_ID)
        if self.enrollment_id is not None:
            _identifier(self.enrollment_id, IdKind.ENROLLMENT, SafeDetail.ENROLLMENT_ID)
        _positive(self.page_size, SafeDetail.PAGE_SIZE)


@dataclass(frozen=True, slots=True)
class GetSourceMetadata:
    """`sources.metadata`: normalized metadata for one object."""

    capability: ClassVar[Capability] = Capability.SOURCES_METADATA

    source_id: str
    source_object_id: str
    enrollment_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.source_id, IdKind.SOURCE, SafeDetail.SOURCE_ID)
        _identifier(self.source_object_id, IdKind.SOURCE_OBJECT, SafeDetail.SOURCE_OBJECT_ID)
        if self.enrollment_id is not None:
            _identifier(self.enrollment_id, IdKind.ENROLLMENT, SafeDetail.ENROLLMENT_ID)


@dataclass(frozen=True, slots=True)
class FetchSource:
    """`sources.fetch`: bounded bytes, or the text they decode to.

    `max_bytes` is a request for *fewer* bytes than the configured ceiling. It
    can never raise it: the handler takes the smaller of the two, so a caller
    cannot widen a bound by asking.
    """

    capability: ClassVar[Capability] = Capability.SOURCES_FETCH

    source_id: str
    source_object_id: str
    representation: Representation = Representation.NORMALIZED_TEXT
    max_bytes: int | None = None
    enrollment_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.source_id, IdKind.SOURCE, SafeDetail.SOURCE_ID)
        _identifier(self.source_object_id, IdKind.SOURCE_OBJECT, SafeDetail.SOURCE_OBJECT_ID)
        if not isinstance(self.representation, Representation):
            raise InvalidRequestError(SafeDetail.REPRESENTATION)
        _positive(self.max_bytes, SafeDetail.MAX_BYTES)
        if self.enrollment_id is not None:
            _identifier(self.enrollment_id, IdKind.ENROLLMENT, SafeDetail.ENROLLMENT_ID)


@dataclass(frozen=True, slots=True)
class GetSourceStatus:
    """`sources.status`: exactly one subject, never a guess between two.

    Section 9.5 requires exactly one of the four, and the type refuses to exist
    otherwise rather than leaving a downstream reader to decide which won.
    """

    capability: ClassVar[Capability] = Capability.SOURCES_STATUS

    source_id: str | None = None
    enrollment_id: str | None = None
    operation_id: str | None = None
    source_object_id: str | None = None

    def __post_init__(self) -> None:
        named = [
            value
            for value in (
                self.source_id,
                self.enrollment_id,
                self.operation_id,
                self.source_object_id,
            )
            if value is not None
        ]
        if len(named) != 1:
            raise InvalidRequestError(SafeDetail.SUBJECT)
        if self.source_id is not None:
            _identifier(self.source_id, IdKind.SOURCE, SafeDetail.SOURCE_ID)
        if self.enrollment_id is not None:
            _identifier(self.enrollment_id, IdKind.ENROLLMENT, SafeDetail.ENROLLMENT_ID)
        if self.operation_id is not None:
            _identifier(self.operation_id, IdKind.OPERATION, SafeDetail.OPERATION_ID)
        if self.source_object_id is not None:
            _identifier(self.source_object_id, IdKind.SOURCE_OBJECT, SafeDetail.SOURCE_OBJECT_ID)


@dataclass(frozen=True, slots=True)
class EnrollSource:
    """`sources.enroll`: one explicit bounded grant. Operator only.

    The selector rules and the ceilings belong to
    `domain.source.enrollment.EnrollmentScope` and `EnrollmentRequest`, which
    already refuse to exist unbounded; this holds the request's raw fields so
    that building those values — and reporting which field a domain refusal was
    about — happens in one place in the handler.
    """

    capability: ClassVar[Capability] = Capability.SOURCES_ENROLL

    source_id: str
    media_types: tuple[str, ...]
    idempotency_key: str
    object_ids: tuple[str, ...] = ()
    root_object_id: str | None = None
    depth: int = 0
    max_items: int | None = None
    max_bytes: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.source_id, IdKind.SOURCE, SafeDetail.SOURCE_ID)
        if not self.media_types:
            raise InvalidRequestError(SafeDetail.MEDIA_TYPES)
        if not isinstance(self.idempotency_key, str):
            raise InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
        if not self.idempotency_key:
            raise InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
        if bool(self.object_ids) == (self.root_object_id is not None):
            raise InvalidRequestError(SafeDetail.SELECTOR)
        for object_id in self.object_ids:
            _identifier(object_id, IdKind.SOURCE_OBJECT, SafeDetail.SOURCE_OBJECT_ID)
        if self.root_object_id is not None:
            _identifier(self.root_object_id, IdKind.SOURCE_OBJECT, SafeDetail.SOURCE_OBJECT_ID)
        if isinstance(self.depth, bool) or not isinstance(self.depth, int):
            raise InvalidRequestError(SafeDetail.DEPTH)
        if self.depth < 0:
            raise InvalidRequestError(SafeDetail.DEPTH)
        _positive(self.max_items, SafeDetail.MAX_ITEMS)
        _positive(self.max_bytes, SafeDetail.MAX_BYTES)


@dataclass(frozen=True, slots=True)
class SearchKnowledge:
    """`knowledge.search`: lexical search inside one enrollment's grant.

    The query stays a bare string here and becomes a `SearchQuery` in the
    handler, where normalization and the refusal of control characters happen.
    Holding a normalized query in a command would put the one sensitive string
    in this system into a value a transport constructs.
    """

    capability: ClassVar[Capability] = Capability.KNOWLEDGE_SEARCH

    enrollment_id: str
    query: str = field(repr=False)
    page_size: int | None = None
    cursor: str | None = None
    snippet_words: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.enrollment_id, IdKind.ENROLLMENT, SafeDetail.ENROLLMENT_ID)
        if not isinstance(self.query, str):
            raise InvalidRequestError(SafeDetail.QUERY)
        _positive(self.page_size, SafeDetail.PAGE_SIZE)
        _positive(self.snippet_words, SafeDetail.SNIPPET_WORDS)
        if self.cursor is not None and not isinstance(self.cursor, str):
            raise InvalidRequestError(SafeDetail.CURSOR)


@dataclass(frozen=True, slots=True)
class ReadKnowledge:
    """`knowledge.read`: one stored record and its provenance.

    The enrollment is part of the request rather than derived from the record,
    so a record written under one grant cannot be read through another. A
    knowledge identifier that names nothing inside the stated grant is
    `not_found`, which is the same answer a caller gets for one that names
    nothing at all.
    """

    capability: ClassVar[Capability] = Capability.KNOWLEDGE_READ

    knowledge_id: str
    enrollment_id: str
    metadata_only: bool = False
    max_characters: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.knowledge_id, IdKind.KNOWLEDGE, SafeDetail.KNOWLEDGE_ID)
        _identifier(self.enrollment_id, IdKind.ENROLLMENT, SafeDetail.ENROLLMENT_ID)
        if not isinstance(self.metadata_only, bool):
            raise InvalidRequestError(SafeDetail.SUBJECT)
        _positive(self.max_characters, SafeDetail.MAX_CHARACTERS)


@dataclass(frozen=True, slots=True)
class RevealSubject:
    """`knowledge.reveal`: the evidence behind one subject identifier.

    **The subject is validated for shape and not for kind**, and the difference
    is the point. `_identifier(…, IdKind.CAPTURE, …)` would refuse an `asrt_…`
    here, and refusing an `enr_…` or a `kn_…` as *malformed* would tell a caller
    its request was wrong when what is actually true is that this build does not
    cover that plane. Shape is a request error; coverage is an answer, and
    `EvidenceGap.SUBJECT_KIND_NOT_COVERED` is where it is given.

    No page size and no cursor. A reveal is bounded by the subject rather than
    by a page: the evidence behind one capture is however many spans that
    capture's versions carry, and truncating it would be truncating the
    explanation of why something is on screen.
    """

    capability: ClassVar[Capability] = Capability.KNOWLEDGE_REVEAL

    subject_id: str

    def __post_init__(self) -> None:
        _identifier(self.subject_id, None, SafeDetail.SUBJECT)


@dataclass(frozen=True, slots=True)
class CreateCapture:
    """`capture.create`: store one user-authored note as the first version of a new capture.

    `text` is `repr=False` for the reason `SearchKnowledge.query` is: a dataclass
    `repr` reaches a traceback, a log record, and an assertion message without
    anyone deciding it should, and this is the one field in the request that
    carries content.

    **The two client times are optional and are never invented.** A transport
    with no device clock supplies neither, and the stored value is then null —
    honest absence rather than the request clock wearing a device's name
    (`QC-AC-012`).

    **There is no capture identifier here.** Creating names nothing that exists;
    revising does. That is the whole difference between this command and
    `ReviseCapture`, and it is a difference in the type rather than in a
    nullable field, so no request can be ambiguous about which it is.
    """

    capability: ClassVar[Capability] = Capability.CAPTURE_CREATE

    text: str = field(repr=False)
    idempotency_key: str
    capture_kind: CaptureKind = CaptureKind.QUICK_NOTE
    context_source_object_id: str | None = None
    context_source_version_id: str | None = None
    client_created_at: datetime | None = None
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.text, SafeDetail.TEXT)
        if not isinstance(self.idempotency_key, str):
            raise InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
        if not self.idempotency_key:
            raise InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
        if not isinstance(self.capture_kind, CaptureKind):
            raise InvalidRequestError(SafeDetail.CAPTURE_KIND)
        if (self.context_source_object_id is None) is not (self.context_source_version_id is None):
            raise InvalidRequestError(
                SafeDetail.CONTEXT_SOURCE_OBJECT_ID,
                SafeDetail.CONTEXT_SOURCE_VERSION_ID,
            )
        if self.context_source_object_id is not None:
            context_version_id = self.context_source_version_id
            if context_version_id is None:  # narrowed from the paired-field invariant above
                raise InvalidRequestError(SafeDetail.CONTEXT_SOURCE_VERSION_ID)
            _identifier(
                self.context_source_object_id,
                IdKind.SOURCE_OBJECT,
                SafeDetail.CONTEXT_SOURCE_OBJECT_ID,
            )
            _identifier(
                context_version_id,
                IdKind.VERSION,
                SafeDetail.CONTEXT_SOURCE_VERSION_ID,
            )
        _moment(self.client_created_at, SafeDetail.CLIENT_CREATED_AT)
        _moment(self.occurred_at, SafeDetail.OCCURRED_AT)


@dataclass(frozen=True, slots=True)
class ReviseCapture:
    """`capture.revise`: append a successor version to an existing capture.

    `revise` rather than `update`, and it is the name that says what happens:
    ADR-003 clause 3 makes an edit a new version, so nothing is overwritten and
    the predecessor stays retrievable. There is no field here that could name a
    version to replace, because replacing one is not an operation this system
    has.
    """

    capability: ClassVar[Capability] = Capability.CAPTURE_REVISE

    capture_id: str
    text: str = field(repr=False)
    idempotency_key: str
    client_created_at: datetime | None = None
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        _identifier(self.capture_id, IdKind.CAPTURE, SafeDetail.CAPTURE_ID)
        _text(self.text, SafeDetail.TEXT)
        if not isinstance(self.idempotency_key, str):
            raise InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
        if not self.idempotency_key:
            raise InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
        _moment(self.client_created_at, SafeDetail.CLIENT_CREATED_AT)
        _moment(self.occurred_at, SafeDetail.OCCURRED_AT)


@dataclass(frozen=True, slots=True)
class ReadCapture:
    """`capture.read`: one stored version of one capture, exactly as written.

    `version_id` omitted means the current version. Named, it means that
    version — including a superseded one, which is the "independently
    retrievable" half of `QC-AC-010` and the reason this command has the field
    at all.

    There is no truncation option, deliberately, and the absence is the point:
    the criterion is that the *original* text is retrievable, and a read that
    could silently return part of it would answer a weaker question.
    """

    capability: ClassVar[Capability] = Capability.CAPTURE_READ

    capture_id: str
    version_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.capture_id, IdKind.CAPTURE, SafeDetail.CAPTURE_ID)
        if self.version_id is not None:
            _identifier(self.version_id, IdKind.CAPTURE_VERSION, SafeDetail.VERSION_ID)


@dataclass(frozen=True, slots=True)
class ListCaptures:
    """`capture.list`: one page of stored captures, newest first.

    No content, and no filter. A filter on owner would be the owner-scoped
    lookup `D-72` refuses to build, and a filter on text would be search, which
    is WP-7's.
    """

    capability: ClassVar[Capability] = Capability.CAPTURE_LIST

    page_size: int | None = None

    def __post_init__(self) -> None:
        _positive(self.page_size, SafeDetail.PAGE_SIZE)


@dataclass(frozen=True, slots=True)
class SearchCaptures:
    """`capture.search`: exact lexical search over stored capture text.

    **No enrollment, and the absence is structural.** A capture belongs to no
    configured source and no enrollment — which is why the four capture
    capabilities sit in `domain.policy.decision._SCOPELESS` — so a field naming
    one here would be a scope this plane cannot hold and a grant nobody issued.
    `SearchKnowledge` requires one because the extraction plane's every row is
    keyed to an enrollment; this plane's rows are keyed to nothing but
    themselves.

    **No cursor either**, for the reason `ListCaptures` has none: this build
    issues no continuation token, truncation is disclosed rather than paged
    around, and a `SearchCursor` binds to an enrollment identifier and a
    `kn_…` that a capture has neither of.

    The query stays a bare string here and becomes a `SearchQuery` in the
    handler, exactly as `SearchKnowledge` does it: normalization and the refusal
    of control characters belong to the domain, and holding a normalized query
    in a command would put the one sensitive string in this system into a value
    a transport constructs. `repr=False` for the same reason.
    """

    capability: ClassVar[Capability] = Capability.CAPTURE_SEARCH

    query: str = field(repr=False)
    page_size: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.query, str):
            raise InvalidRequestError(SafeDetail.QUERY)
        _positive(self.page_size, SafeDetail.PAGE_SIZE)


@dataclass(frozen=True, slots=True)
class ListReviewCases:
    """`review.list`: one bounded page of consequential proposal cases."""

    capability: ClassVar[Capability] = Capability.REVIEW_LIST

    page_size: int | None = None

    def __post_init__(self) -> None:
        _positive(self.page_size, SafeDetail.PAGE_SIZE)


@dataclass(frozen=True, slots=True)
class DecideReviewCase:
    """`review.decide`: append one disposition under optimistic concurrency."""

    capability: ClassVar[Capability] = Capability.REVIEW_DECIDE

    review_case_id: str
    expected_review_version: int
    disposition: Disposition
    corrected_value: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _identifier(self.review_case_id, IdKind.REVIEW_CASE, SafeDetail.REVIEW_CASE_ID)
        if type(self.expected_review_version) is not int or self.expected_review_version < 0:
            raise InvalidRequestError(SafeDetail.EXPECTED_REVIEW_VERSION)
        if not isinstance(self.disposition, Disposition):
            raise InvalidRequestError(SafeDetail.DISPOSITION)
        corrected = self.disposition is Disposition.CORRECT_AND_ACCEPT
        if corrected is not (self.corrected_value is not None):
            raise InvalidRequestError(SafeDetail.CORRECTED_VALUE)
        if self.corrected_value is not None and (
            not self.corrected_value.strip()
            or len(self.corrected_value) > MAX_NORMALIZED_VALUE_CHARACTERS
        ):
            raise InvalidRequestError(SafeDetail.CORRECTED_VALUE)


@dataclass(frozen=True, slots=True)
class GetPulse:
    """`continuity.pulse`: the Principal's why-now list, derived at request time.

    **No payload at all, and that is the shape rather than an omission.** The
    Pulse is not a query: there is nothing for a caller to filter, page, or sort
    by, because the ranking is the answer. A `sort` parameter would be the first
    step back to an activity feed, and there is no field one could put it in.
    """

    capability: ClassVar[Capability] = Capability.CONTINUITY_PULSE


@dataclass(frozen=True, slots=True)
class ListSituations:
    """`continuity.situations`: one bounded page of the Principal's Situations."""

    capability: ClassVar[Capability] = Capability.CONTINUITY_SITUATIONS

    page_size: int | None = None

    def __post_init__(self) -> None:
        _positive(self.page_size, SafeDetail.PAGE_SIZE)


@dataclass(frozen=True, slots=True)
class ListProjects:
    """`continuity.projects`: one bounded page of the Principal's Projects."""

    capability: ClassVar[Capability] = Capability.CONTINUITY_PROJECTS

    page_size: int | None = None

    def __post_init__(self) -> None:
        _positive(self.page_size, SafeDetail.PAGE_SIZE)


@dataclass(frozen=True, slots=True)
class CreateProject:
    """Create a project the user explicitly asked to create. Requires name.

    An explicit user instruction. The authenticated Principal is the owner; this
    command does not carry a Principal field. `name` is the project title the
    user chose. `idempotency_key` is required on the canonical contract; the
    remote MCP adapter stamps it so a model does not invent one.
    """

    capability: ClassVar[Capability] = Capability.CONTINUITY_PROJECTS_CREATE

    name: str
    idempotency_key: str
    description: str | None = None

    def __post_init__(self) -> None:
        _text(self.name, SafeDetail.NAME)
        if not self.name.strip():
            raise InvalidRequestError(SafeDetail.NAME)
        _idempotency_key(self.idempotency_key)
        if self.description is not None and not isinstance(self.description, str):
            raise InvalidRequestError(SafeDetail.TEXT)


@dataclass(frozen=True, slots=True)
class CreateSituation:
    """Create a situation the user explicitly asked to open. Requires title.

    An explicit user instruction. The Situation references other objects and
    never owns them; this command creates the context itself.
    """

    capability: ClassVar[Capability] = Capability.CONTINUITY_SITUATIONS_CREATE

    title: str
    idempotency_key: str
    description: str | None = None

    def __post_init__(self) -> None:
        _text(self.title, SafeDetail.TITLE)
        if not self.title.strip():
            raise InvalidRequestError(SafeDetail.TITLE)
        _idempotency_key(self.idempotency_key)
        if self.description is not None and not isinstance(self.description, str):
            raise InvalidRequestError(SafeDetail.TEXT)


@dataclass(frozen=True, slots=True)
class CreateTask:
    """Create a task the user explicitly asked to record. Requires title.

    This is Principal authoring, not a model-inferred proposal. The resulting
    Task is accepted continuity because the user instructed the write. Optional
    `project_id` attaches it to a Project the same Principal already holds.
    """

    capability: ClassVar[Capability] = Capability.CONTINUITY_TASKS_CREATE

    title: str
    idempotency_key: str
    project_id: str | None = None
    situation_id: str | None = None
    due_at: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.title, SafeDetail.TITLE)
        if not self.title.strip():
            raise InvalidRequestError(SafeDetail.TITLE)
        _idempotency_key(self.idempotency_key)
        if self.project_id is not None:
            _identifier(self.project_id, IdKind.PROJECT, SafeDetail.PROJECT_ID)
        if self.situation_id is not None:
            _identifier(self.situation_id, IdKind.SITUATION, SafeDetail.SITUATION_ID)
        _moment(self.due_at, SafeDetail.DUE_AT)


@dataclass(frozen=True, slots=True)
class GetCorpusCoverage:
    """`knowledge.coverage`: how much of everything this Principal holds was covered.

    **No payload at all, and that is the shape rather than an omission.** The
    subject is the acting Principal, which the gateway established and no request
    may state; there is no enrollment to name, because naming one would produce
    the per-enrollment answer `sources.status` already gives, and no source to
    filter by, because a corpus answer filtered to one source is not a corpus
    answer. A field here would be a way to ask a narrower question under a name
    that promises a wider one.
    """

    capability: ClassVar[Capability] = Capability.KNOWLEDGE_COVERAGE


# --- WP-28 the managed-document plane, over a transport ----------------------
#
# Six commands, one per `documents.` capability, and **not one of them carries a
# `principal_id`**. That is the whole of how this family differs from the six
# `…ManagedDocumentCommand` dataclasses further down, and the difference is the
# reason both exist rather than one being folded into the other:
#
# * these are *requests* — built by `adapters.normalization` from a caller's
#   payload, published field by field in the MCP tool input schema, and holding
#   only what a caller is allowed to say;
# * those are *resolved instructions* — built inside
#   `ApplicationService`'s handlers with
#   `principal_id=authorization.principal.principal_id`, and consumed by
#   `application.managed_documents.ManagedDocumentService`.
#
# Folding them together would put `principal_id` on the wire. The tool schema is
# derived from the command dataclass, so a field here is a field a client may
# send; a required `principal_id` would be a caller naming the partition its
# write lands in, which is exactly the cross-Principal write `docs/specs`
# section 8.2 and operating-brief section 18 forbid. Keeping it off the type
# makes it unspellable rather than merely ignored, and
# `tests/architecture/test_principal_is_never_caller_supplied.py` claim 3 —
# written by WP-27 against the day this family was wired — now has real
# constructions to quantify over.
#
# **`content` is `bytes` and `repr=False`**, for the reason `CreateCapture.text`
# carries it: a document body reaches a traceback, a log record and a pytest
# assertion message through a dataclass `repr` without anyone deciding it should.
# On the wire it is base64 text, which `adapters.normalization` decodes and
# `adapters.mcp.tools` publishes as `contentEncoding: base64`.
#
# **No command carries a path, a filename, or a location**, and neither does the
# port beneath them. `title` is metadata bound for a text column.


@dataclass(frozen=True, slots=True)
class CreateManagedDocument:
    """`documents.create`: write the first immutable version of a new document.

    Names no document, because creating names nothing that exists. That is the
    whole difference from `ReviseManagedDocument`, and it is a difference in the
    type rather than in a nullable field.
    """

    capability: ClassVar[Capability] = Capability.DOCUMENTS_CREATE

    title: str
    media_type: str
    content: bytes = field(repr=False)
    idempotency_key: str

    def __post_init__(self) -> None:
        _managed_title(self.title)
        _managed_media_type(self.media_type)
        _managed_content(self.content)
        _idempotency_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class ReviseManagedDocument:
    """`documents.revise`: append a successor version to a document.

    `expected_version_number` is required and has no default. A revision that did
    not state what it was revising would be a blind write, and WP-27's whole
    expected-version control is that a writer says which version it read.
    """

    capability: ClassVar[Capability] = Capability.DOCUMENTS_REVISE

    document_id: str
    expected_version_number: int
    title: str
    media_type: str
    content: bytes = field(repr=False)
    idempotency_key: str

    def __post_init__(self) -> None:
        _identifier(self.document_id, IdKind.MANAGED_DOCUMENT, SafeDetail.DOCUMENT_ID)
        if type(self.expected_version_number) is not int or self.expected_version_number < 1:
            raise InvalidRequestError(SafeDetail.EXPECTED_VERSION_NUMBER)
        _managed_title(self.title)
        _managed_media_type(self.media_type)
        _managed_content(self.content)
        _idempotency_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class ReadManagedDocument:
    """`documents.read`: one stored version of one managed document.

    `version_id` omitted means the current version. Named, it means that version —
    including a superseded one, which is what makes an immutable chain worth
    keeping. `include_bytes` is false by default so that reading metadata is not
    silently a read of a document body.
    """

    capability: ClassVar[Capability] = Capability.DOCUMENTS_READ

    document_id: str
    version_id: str | None = None
    include_bytes: bool = False

    def __post_init__(self) -> None:
        _identifier(self.document_id, IdKind.MANAGED_DOCUMENT, SafeDetail.DOCUMENT_ID)
        if self.version_id is not None:
            _identifier(self.version_id, IdKind.MANAGED_DOCUMENT_VERSION, SafeDetail.VERSION_ID)
        if not isinstance(self.include_bytes, bool):
            raise InvalidRequestError(SafeDetail.SELECTOR)


@dataclass(frozen=True, slots=True)
class ListManagedDocuments:
    """`documents.list`: one bounded page of this Principal's documents, newest first.

    Carries no bytes at all, which is the line between this capability and
    `documents.read`: one reaches a body and the other cannot.
    """

    capability: ClassVar[Capability] = Capability.DOCUMENTS_LIST

    limit: int | None = None
    include_archived: bool = False

    def __post_init__(self) -> None:
        _positive(self.limit, SafeDetail.LIMIT)
        if not isinstance(self.include_archived, bool):
            raise InvalidRequestError(SafeDetail.SELECTOR)


@dataclass(frozen=True, slots=True)
class ArchiveManagedDocument:
    """`documents.archive`: withdraw one document from the active set. Destroys nothing."""

    capability: ClassVar[Capability] = Capability.DOCUMENTS_ARCHIVE

    document_id: str

    def __post_init__(self) -> None:
        _identifier(self.document_id, IdKind.MANAGED_DOCUMENT, SafeDetail.DOCUMENT_ID)


@dataclass(frozen=True, slots=True)
class RestoreManagedDocument:
    """`documents.restore`: return one archived document to the active set."""

    capability: ClassVar[Capability] = Capability.DOCUMENTS_RESTORE

    document_id: str

    def __post_init__(self) -> None:
        _identifier(self.document_id, IdKind.MANAGED_DOCUMENT, SafeDetail.DOCUMENT_ID)


#: Every command there is. A union rather than a base class, so adding a
#: capability is a type error at every dispatch site until it is handled.
type Command = (
    GetCapabilities
    | ListSources
    | GetSourceMetadata
    | FetchSource
    | GetSourceStatus
    | EnrollSource
    | SearchKnowledge
    | ReadKnowledge
    | RevealSubject
    | CreateCapture
    | ReviseCapture
    | ReadCapture
    | ListCaptures
    | SearchCaptures
    | ListReviewCases
    | DecideReviewCase
    | GetPulse
    | ListSituations
    | ListProjects
    | CreateProject
    | CreateSituation
    | CreateTask
    | GetCorpusCoverage
    | CreateManagedDocument
    | ReviseManagedDocument
    | ReadManagedDocument
    | ListManagedDocuments
    | ArchiveManagedDocument
    | RestoreManagedDocument
)


# --- WP-06 R5 continuity commands ------------------------------------------
#
# These are a separate command family from the `Command` union above, and the
# difference is deliberate. The union's members flow through a transport parse
# into `ApplicationService.invoke`, whose one authorization path derives the
# Principal from authenticated context — which is why "the principal is not
# here" holds for them and why they carry a `Capability` ClassVar.
#
# The continuity commands below are consumed by the standalone `SituationService`
# (`application.situation_service`), the same shape the fixture-only
# `RelationshipService` uses: a caller resolves the authenticated Principal and
# passes it in explicitly, and the repository stamps and filters every row by it.
# So these carry `principal_id` as their first field — not as a caller-supplied
# identity a transport controls, but as the resolved partition the service was
# asked to act within. They are not part of `Command`, hold no `Capability`, and
# never reach `invoke`; keeping them out of the union is what stops a continuity
# command from ever being dispatched as if it were an authorized capability.
#
# Validation raises `InvalidIdentifierError`/`ValueError` at construction, the
# same way `contracts.ports.ReviewDecisionRequest` does, rather than the
# transport-facing `InvalidRequestError`/`SafeDetail` machinery, because these
# are built inside the application layer and not from a raw caller payload.


@dataclass(frozen=True, slots=True)
class OpenSituationCommand:
    """Open one purposeful operational context for a Principal.

    `object_refs` are opaque references the Situation is about; the Situation
    references them and never owns them.
    """

    principal_id: str
    title: str
    description: str | None = None
    object_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.title.strip():
            raise ValueError("a situation carries a non-blank title")
        if any(not ref.strip() for ref in self.object_refs):
            raise ValueError("object references are non-empty strings")


@dataclass(frozen=True, slots=True)
class CloseSituationCommand:
    """Close one Situation with its outcome and its evidence. Deletes nothing.

    **`evidence_kind` and `evidence_ref` are required (WP-11)** and have no
    default, because a default would be this command supplying the evidence its
    caller did not. An outcome sentence with nothing under it is a status field
    changing with no trace; the pair is what the append-only `closed` lifecycle
    row is built from.
    """

    principal_id: str
    situation_id: str
    outcome: str
    evidence_kind: ClosureEvidenceKind
    evidence_ref: str

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.situation_id, IdKind.SITUATION)
        if not self.outcome.strip():
            raise ValueError("closing a situation records a non-blank outcome")
        if not isinstance(self.evidence_kind, ClosureEvidenceKind):
            raise ValueError("closing a situation names one kind of closure evidence")
        if not self.evidence_ref.strip():
            raise ValueError("closing a situation cites the evidence that closed it")


@dataclass(frozen=True, slots=True)
class EnterFrameCommand:
    """Enter the current view within one Situation of what matters."""

    principal_id: str
    situation_id: str
    label: str
    evidence_refs: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    uncertainty: str | None = None
    next_authority: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.situation_id, IdKind.SITUATION)
        if not self.label.strip():
            raise ValueError("a frame carries a non-blank label")
        for name, refs in (
            ("evidence", self.evidence_refs),
            ("alternatives", self.alternatives),
            ("obligations", self.obligations),
        ):
            if any(not ref.strip() for ref in refs):
                raise ValueError(f"{name} references are non-empty strings")


@dataclass(frozen=True, slots=True)
class AddProjectCommand:
    """Create one durable work context with participants for a Principal."""

    principal_id: str
    name: str
    description: str | None = None
    participants: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.name.strip():
            raise ValueError("a project carries a non-blank name")
        if any(not p.strip() for p in self.participants):
            raise ValueError("participants are non-empty strings")


@dataclass(frozen=True, slots=True)
class LinkSituationToProjectCommand:
    """Bind one Situation into one Project, citing what justified the binding.

    Unique per (project, situation). The evidence pair is required for the reason
    `CloseSituationCommand`'s is: an association with no recorded justification is
    one a later reader can only infer.
    """

    principal_id: str
    project_id: str
    situation_id: str
    evidence_kind: ClosureEvidenceKind
    evidence_ref: str

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.project_id, IdKind.PROJECT)
        validate_identifier(self.situation_id, IdKind.SITUATION)
        if not isinstance(self.evidence_kind, ClosureEvidenceKind):
            raise ValueError("an association names one kind of evidence")
        if not self.evidence_ref.strip():
            raise ValueError("an association cites the evidence that justifies it")


@dataclass(frozen=True, slots=True)
class RecordRelationshipEventCommand:
    """Record one dated event on a Person's relationship timeline.

    `accepted` gates whether Today/Pulse and the briefing read the event as an
    accepted timeline fact; it defaults false so a proposed event never surfaces
    as accepted (invariant 5).
    """

    principal_id: str
    person_id: str
    event_type: RelationshipEventType
    occurred_at: datetime
    context: str | None = None
    accepted: bool = False
    source_ref: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.person_id, IdKind.PERSON)
        if not isinstance(self.event_type, RelationshipEventType):
            raise ValueError("a relationship event names one event type")
        if not isinstance(self.occurred_at, datetime):
            raise ValueError("a relationship event records when it occurred")
        ensure_utc(self.occurred_at)
        if not isinstance(self.accepted, bool):
            raise ValueError("acceptance is a boolean gate")
        if self.context is not None and not isinstance(self.context, str):
            raise ValueError("event context is text or absent")


@dataclass(frozen=True, slots=True)
class TraceObjectCommand:
    """Reconstruct one object over a time range from the source events it cites."""

    principal_id: str
    object_id: str
    object_type: str
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.object_id.strip():
            raise ValueError("a trace names the object it reconstructs")
        if not self.object_type.strip():
            raise ValueError("a trace records the kind of object it reconstructs")
        if self.time_range_start is not None:
            ensure_utc(self.time_range_start)
        if self.time_range_end is not None:
            ensure_utc(self.time_range_end)
        if (
            self.time_range_start is not None
            and self.time_range_end is not None
            and self.time_range_end < self.time_range_start
        ):
            raise ValueError("a trace range ends no earlier than it starts")


# --- WP-27 managed-document commands ----------------------------------------
#
# A third command family, and it sits beside the WP-06 continuity family for the
# same reason and with the same shape: these are consumed by the standalone
# `application.managed_documents.ManagedDocumentService`, a caller resolves the
# authenticated Principal and passes it in explicitly, and the repository stamps
# and filters every row by it. They are not part of `Command`, hold no
# `Capability`, and never reach `invoke`.
#
# **That is a scope boundary rather than an oversight, and it is written down
# here so nobody has to infer it.** WP-27 builds the canonical managed-document
# application service; exposing managed writes over a transport is WP-28's, which
# the completion plan states as "managed writes use WP-27 only". A capability seat
# added here with no transport behind it would publish a name `capabilities.get`
# reports as available and nothing can reach.
#
# **`content` is `bytes` and is `repr=False`**, for the reason `CreateCapture.text`
# carries it and more so: this is a document body, and a dataclass `repr` reaches
# a traceback, a log record and a pytest assertion message without anyone deciding
# it should.
#
# **No command carries a path, a filename, or a location.** `title` is metadata,
# bounded and stored in the database, and the byte store accepts no path
# parameter at all — so there is nothing on this surface for a traversal to
# travel in.


@dataclass(frozen=True, slots=True)
class CreateManagedDocumentCommand:
    """Write the first immutable version of a new managed document.

    Names no document, because creating names nothing that exists. That is the
    whole difference from `ReviseManagedDocumentCommand`, and it is a difference
    in the type rather than in a nullable field, so no request can be ambiguous
    about which it is.
    """

    principal_id: str
    title: str
    media_type: str
    content: bytes = field(repr=False)
    idempotency_key: str

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_managed_title(self.title)
        validate_managed_media_type(self.media_type)
        if not isinstance(self.content, bytes | bytearray):
            raise ValueError("a managed document version carries bytes")
        if not self.idempotency_key:
            raise ValueError("a managed write carries an idempotency key")


@dataclass(frozen=True, slots=True)
class ReviseManagedDocumentCommand:
    """Append a successor version to a managed document the Principal owns.

    `expected_version_number` is required and has no default. A revision that did
    not state what it was revising would be a blind write, and the whole of
    WP-27's expected-version control is that a writer says which version it read
    before it says what should follow.
    """

    principal_id: str
    document_id: str
    expected_version_number: int
    title: str
    media_type: str
    content: bytes = field(repr=False)
    idempotency_key: str

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        if type(self.expected_version_number) is not int or self.expected_version_number < 1:
            raise ValueError("an expected managed version number starts at one")
        validate_managed_title(self.title)
        validate_managed_media_type(self.media_type)
        if not isinstance(self.content, bytes | bytearray):
            raise ValueError("a managed document version carries bytes")
        if not self.idempotency_key:
            raise ValueError("a managed write carries an idempotency key")


@dataclass(frozen=True, slots=True)
class ReadManagedDocumentCommand:
    """Read one stored version of a managed document the Principal owns.

    `version_id` omitted means the current version. Named, it means that version —
    including a superseded one, which is what makes an immutable chain worth
    keeping. `include_bytes` is false by default so that reading metadata is not
    silently a read of a document body.
    """

    principal_id: str
    document_id: str
    version_id: str | None = None
    include_bytes: bool = False

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        if self.version_id is not None:
            validate_identifier(self.version_id, IdKind.MANAGED_DOCUMENT_VERSION)


@dataclass(frozen=True, slots=True)
class ListManagedDocumentsCommand:
    """One bounded page of the Principal's managed documents, newest first."""

    principal_id: str
    limit: int = 50
    include_archived: bool = False

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if type(self.limit) is not int or self.limit < 1:
            raise ValueError("a page holds at least one managed document")


@dataclass(frozen=True, slots=True)
class ArchiveManagedDocumentCommand:
    """Withdraw one managed document from the active set. Destroys nothing."""

    principal_id: str
    document_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)


@dataclass(frozen=True, slots=True)
class RestoreManagedDocumentCommand:
    """Return one archived managed document to the active set."""

    principal_id: str
    document_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
