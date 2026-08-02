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
from enum import StrEnum
from typing import ClassVar

from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.identity.operation import Capability

__all__ = [
    "Command",
    "EnrollSource",
    "FetchSource",
    "GetCapabilities",
    "GetSourceMetadata",
    "GetSourceStatus",
    "ListSources",
    "ReadKnowledge",
    "Representation",
    "SearchKnowledge",
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


def _identifier(value: str, kind: IdKind, detail: SafeDetail) -> str:
    """Validate one identifier, reporting the field rather than the value."""
    try:
        return validate_identifier(value, kind)
    except InvalidIdentifierError:
        pass
    # Raised outside the handler so the original — which renders the rejected
    # value — is not left in `__context__` for a traceback to print.
    raise InvalidRequestError(detail)


def _positive(value: int | None, detail: SafeDetail) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(detail)
    if value < 1:
        raise InvalidRequestError(detail)
    return value


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
)
