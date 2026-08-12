"""The read-only source provider port.

A provider translates authorized reads of logical objects. It is the boundary
adapter of `docs/specs` section 4, `ACT-PKL-005`: untrusted, read-only, and with
its physical identity kept internal.

The port is read-only by omission, not by a flag. There is no `write`, `move`,
`rename`, or `delete` method to call, and no `read_only=True` to misconfigure, so
`INV-PKL-001` holds structurally rather than by runtime check. Adding a mutating
method here would be the visible, reviewable act it should be.

Provider-native identity — a path, a URI, an inode, a host — never crosses this
boundary. The port speaks in the opaque `obj_…` identifiers of
`domain.common.identifiers`; mapping them to physical locations is the
implementation's private business (`INV-PKL-005`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "ENUMERABLE_KINDS",
    "ObjectKind",
    "ProviderError",
    "SourceObject",
    "SourceObjectContent",
    "SourceProvider",
    "TraversalDeniedError",
    "VersionChangedError",
]


class ObjectKind(StrEnum):
    """What a logical object is, without saying what it is stored on."""

    FILE = "file"
    CONTAINER = "container"
    MAIL_MESSAGE = "mail_message"
    CALENDAR_EVENT = "calendar_event"
    CONTACT = "contact"
    TASK = "task"


#: The kinds an enrollment's enumeration records as authorized objects.
#:
#: **One definition with two callers, rather than a rule written twice.**
#: `ApplicationService._enumerate` descends into a container and records
#: everything else; the corpus coverage read has to subtract exactly the same
#: kinds when it counts what lies *outside* every enrollment, because a container
#: is structure no enumeration was ever going to enroll and reporting one as
#: uncovered territory would be a permanent gap nothing could close. Written as
#: the complement so that a new kind is enumerable — and therefore countable —
#: unless something decides otherwise, which is the direction that fails towards
#: disclosing more rather than less.
ENUMERABLE_KINDS: Final[frozenset[ObjectKind]] = frozenset(ObjectKind) - {ObjectKind.CONTAINER}


class ProviderError(Exception):
    """Base class for a boundary failure the application must classify.

    A provider raises these rather than returning sentinels, so a caller cannot
    mistake a denial for an empty result.
    """


class TraversalDeniedError(ProviderError):
    """A request resolved outside the configured root, or could not be proven inside it.

    Carries no path. The message names the opaque object, because an error text
    that echoed the resolved location would defeat the containment it reports
    (`docs/specs` section 10: denial must not leak existence or location).
    """


class VersionChangedError(ProviderError):
    """The object changed between observation and read.

    Distinct from a generic failure: the correct response is `conflict` and a
    re-observation, never stale bytes labelled current (`docs/specs` section 9.4).
    """


@dataclass(frozen=True, slots=True)
class SourceObject:
    """Normalised metadata for one logical object.

    Deliberately without a size field for containers and without any physical
    locator. `version_id` binds the observation: two reads that return the same
    `version_id` observed the same bytes.
    """

    source_id: str
    source_object_id: str
    version_id: str
    kind: ObjectKind
    media_type: str | None
    size_bytes: int | None
    modified_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.version_id, IdKind.VERSION)
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")
        if self.kind is ObjectKind.CONTAINER and self.size_bytes is not None:
            raise ValueError("a container has no meaningful size")
        object.__setattr__(self, "modified_at", ensure_utc(self.modified_at))


@dataclass(frozen=True, slots=True)
class SourceObjectContent:
    """Bytes read from one object, bound to the version they came from.

    The `version_id` is the version observed at read time, not the one requested.
    A caller comparing it against what it asked for is how a mid-read change is
    caught.
    """

    source_object_id: str
    version_id: str
    media_type: str | None
    content: bytes
    is_truncated: bool

    def __post_init__(self) -> None:
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.version_id, IdKind.VERSION)


class SourceProvider(ABC):
    """Read-only access to one configured source.

    Implementations must revalidate containment immediately before opening an
    object, not only when the identifier was issued. The gap between the two is
    where a symlink swap lands.
    """

    @property
    @abstractmethod
    def source_id(self) -> str:
        """The opaque `src_…` identity of the configured source."""

    @abstractmethod
    def list_children(self, parent_object_id: str | None = None) -> Iterator[SourceObject]:
        """Yield the immediate children of `parent_object_id`, root when omitted.

        Immediate children only. Recursive traversal is the caller's decision to
        make explicitly and boundedly, so that no single call can walk a volume
        (`docs/specs` section 9.2).
        """

    @abstractmethod
    def metadata(self, source_object_id: str) -> SourceObject:
        """Return current metadata for one object.

        Raises `TraversalDeniedError` when containment cannot be proven, and the same
        error whether the object is absent or refused, so the caller cannot use
        the difference to probe for existence.
        """

    @abstractmethod
    def fetch(self, source_object_id: str, *, max_bytes: int) -> SourceObjectContent:
        """Read at most `max_bytes` from one object.

        Truncation is reported, never silent. `max_bytes` is a hard ceiling: an
        implementation stops reading rather than buffering a large object to
        discover its size.
        """
