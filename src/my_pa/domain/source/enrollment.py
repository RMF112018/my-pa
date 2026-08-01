"""Bounded enrollment: the one thing that authorizes a read, and its limits.

An enrollment is the operator's explicit, bounded grant (`docs/specs` section
9.6). Every bound it names is enforced when the value is *constructed*, not when
it is used, so there is no code path that holds an unbounded enrollment and
checks it later. In particular the default depth is zero and the maximum is
`MAX_ENROLLMENT_DEPTH`: recursion has to be asked for, by a number, inside a
ceiling.

The idempotency key is scoped to principal, purpose, source, normalized
enrollment, and policy version (`docs/specs` section 8.6). Three of those five
are columns of the key's uniqueness scope; the normalized enrollment is bound to
it by `fingerprint`, which is what makes reuse with a materially different
request detectable rather than silently accepted. Reuse with an identical
request is not a conflict — it is the retry the key exists to make safe.

Normalization is the whole reason the comparison means anything. Two requests
that differ only in the order of their object identifiers, in the case of a
media type, or in surrounding whitespace are the same request; if they were not
normalized before fingerprinting, an honest retry would look like a conflict.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.purpose import Purpose

__all__ = [
    "DEFAULT_ENROLLMENT_DEPTH",
    "MAX_ENROLLMENT_BYTES",
    "MAX_ENROLLMENT_DEPTH",
    "MAX_ENROLLMENT_ITEMS",
    "Enrollment",
    "EnrollmentBoundsError",
    "EnrollmentConflictError",
    "EnrollmentRequest",
    "EnrollmentScope",
]

#: Section 9.6: "Default depth zero; recursion explicit/bounded." Zero means the
#: named root itself and its immediate children — never a walk.
DEFAULT_ENROLLMENT_DEPTH: Final = 0

#: A bound has to be a number, and this is the number. Eight levels covers a
#: realistically nested document tree while keeping the worst case a reviewer
#: has to reason about finite: past this, an operator who genuinely wants more
#: enrolls a deeper root explicitly, which is a visible act rather than a
#: parameter nobody read.
MAX_ENROLLMENT_DEPTH: Final = 8

#: Depth alone does not bound work; a single directory can hold a million
#: entries. These are the other two ceilings section 9.6 requires, and they are
#: sized for one operator's document corpus rather than for a fileserver.
MAX_ENROLLMENT_ITEMS: Final = 10_000
MAX_ENROLLMENT_BYTES: Final = 1 << 30

#: An idempotency key is caller-supplied, which makes it the one field an
#: operator could paste a path or an address into. Restricting it to the
#: URL-safe token alphabet excludes `/`, `\`, `.`, `:`, and `@`, so a path, a
#: host, or an email address cannot be stored as one. Like the identifier suffix
#: rule this catches shape and not meaning, and for the same reason: the caller
#: is responsible for using a random key, and the schema is responsible for
#: making a reused one detectable.
_IDEMPOTENCY_KEY_PATTERN: Final = re.compile(r"\A[A-Za-z0-9_-]{8,128}\Z")

#: A policy profile version, as recorded for audit binding (section 9.6).
_POLICY_VERSION_PATTERN: Final = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")

#: A media type in the enrollment's allowlist, normalized to lower case with no
#: parameters. Parameters are rejected rather than dropped: silently discarding
#: `; charset=` would widen the allowlist the operator wrote.
_MEDIA_TYPE_PATTERN: Final = re.compile(r"\A[a-z]+/[a-z0-9][a-z0-9.+-]*\Z")

#: Most media types one enrollment can usefully allow.
_MAX_MEDIA_TYPES: Final = 32


class EnrollmentBoundsError(ValueError):
    """Raised when a request is unbounded, contradictory, or outside a ceiling.

    Names the field and the limit, never the value: an object identifier is
    opaque, but a media type or a key is caller-supplied text.
    """


class EnrollmentConflictError(Exception):
    """An idempotency key was reused with a materially different request.

    Carries the existing opaque enrollment identifier and nothing else, so a
    caller can look up what the key is already bound to (`docs/specs` section
    10: a conflict returns a safe current-state reference). It deliberately does
    not report *which* field differed, because that would describe the stored
    request to whoever guessed the key.
    """

    def __init__(self, enrollment_id: str) -> None:
        validate_identifier(enrollment_id, IdKind.ENROLLMENT)
        super().__init__(
            f"idempotency key is already bound to {enrollment_id} "
            "with a different normalized enrollment"
        )
        self.enrollment_id = enrollment_id


@dataclass(frozen=True, slots=True)
class EnrollmentScope:
    """Exactly one selector, and the depth that applies to it.

    Section 9.6 requires "exactly one selector (`object_ids` or `root_object_id`
    plus bounded depth)". Both or neither is `ambiguous_request` territory, so
    the type refuses to exist in either state rather than leaving a downstream
    reader to decide which one won.
    """

    object_ids: tuple[str, ...] = ()
    root_object_id: str | None = None
    depth: int = DEFAULT_ENROLLMENT_DEPTH

    def __post_init__(self) -> None:
        has_objects = len(self.object_ids) > 0
        has_root = self.root_object_id is not None
        if has_objects == has_root:
            raise EnrollmentBoundsError(
                "an enrollment names exactly one selector: object_ids or root_object_id"
            )
        # `bool` is an `int` subclass, so `depth=True` would otherwise pass as 1.
        if isinstance(self.depth, bool) or not isinstance(self.depth, int):
            raise EnrollmentBoundsError("depth must be an integer")
        if not DEFAULT_ENROLLMENT_DEPTH <= self.depth <= MAX_ENROLLMENT_DEPTH:
            raise EnrollmentBoundsError(
                f"depth must be between {DEFAULT_ENROLLMENT_DEPTH} and {MAX_ENROLLMENT_DEPTH}"
            )
        if has_objects:
            if self.depth != DEFAULT_ENROLLMENT_DEPTH:
                raise EnrollmentBoundsError(
                    "depth applies to a root selector; an explicit object list has no depth"
                )
            if len(self.object_ids) > MAX_ENROLLMENT_ITEMS:
                raise EnrollmentBoundsError(
                    f"an enrollment may name at most {MAX_ENROLLMENT_ITEMS} objects"
                )
            for object_id in self.object_ids:
                validate_identifier(object_id, IdKind.SOURCE_OBJECT)
            # Sorted and deduplicated so that two requests differing only in the
            # order they listed the same objects fingerprint identically.
            object.__setattr__(self, "object_ids", tuple(sorted(set(self.object_ids))))
        elif self.root_object_id is not None:
            validate_identifier(self.root_object_id, IdKind.SOURCE_OBJECT)

    @property
    def selector_kind(self) -> str:
        """Which selector this scope carries: `object_ids` or `root_object_id`."""
        return "root_object_id" if self.root_object_id is not None else "object_ids"


def _normalized_media_types(media_types: tuple[str, ...]) -> tuple[str, ...]:
    if not media_types:
        raise EnrollmentBoundsError("an enrollment requires a content-type allowlist")
    if len(media_types) > _MAX_MEDIA_TYPES:
        raise EnrollmentBoundsError(
            f"an enrollment may allow at most {_MAX_MEDIA_TYPES} content types"
        )
    normalized = tuple(sorted({value.strip().lower() for value in media_types}))
    for value in normalized:
        if not _MEDIA_TYPE_PATTERN.fullmatch(value):
            raise EnrollmentBoundsError(
                "each allowed content type must be a bare type/subtype with no parameters"
            )
    return normalized


@dataclass(frozen=True, slots=True)
class EnrollmentRequest:
    """One `sources.enroll` request, normalized on construction.

    Holding the normalized form is what lets `fingerprint` be compared against a
    stored one without either side re-deriving it. `idempotency_key` is
    deliberately absent from the fingerprint: the key labels the request, so
    including it would make every key trivially agree with itself and the
    conflict rule would never fire.
    """

    source_id: str
    principal_id: str
    purpose: Purpose
    scope: EnrollmentScope
    media_types: tuple[str, ...]
    policy_version: str
    idempotency_key: str
    max_items: int = MAX_ENROLLMENT_ITEMS
    max_bytes: int = MAX_ENROLLMENT_BYTES

    def __post_init__(self) -> None:
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        object.__setattr__(self, "media_types", _normalized_media_types(self.media_types))
        _check_ceiling("max_items", self.max_items, MAX_ENROLLMENT_ITEMS)
        _check_ceiling("max_bytes", self.max_bytes, MAX_ENROLLMENT_BYTES)
        if not _POLICY_VERSION_PATTERN.fullmatch(self.policy_version):
            raise EnrollmentBoundsError(
                "policy_version must be 1-32 characters of letters, digits, dots, "
                "hyphens, or underscores"
            )
        if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(self.idempotency_key):
            raise EnrollmentBoundsError(
                "idempotency_key must be 8-128 characters of letters, digits, "
                "hyphens, or underscores"
            )

    def normalized(self) -> dict[str, object]:
        """The canonical form of everything the key is scoped to except the key.

        A plain mapping of JSON-representable values, so `fingerprint` can be a
        stable function of it across processes and releases.
        """
        return {
            "source_id": self.source_id,
            "principal_id": self.principal_id,
            "purpose": self.purpose.value,
            "selector_kind": self.scope.selector_kind,
            "object_ids": list(self.scope.object_ids),
            "root_object_id": self.scope.root_object_id,
            "depth": self.scope.depth,
            "media_types": list(self.media_types),
            "max_items": self.max_items,
            "max_bytes": self.max_bytes,
            "policy_version": self.policy_version,
        }

    @property
    def fingerprint(self) -> str:
        """A stable digest of the normalized request.

        SHA-256 over canonical JSON: sorted keys and no incidental whitespace,
        so the digest depends on the values and not on how a dict happened to be
        built. Every input is either an opaque identifier or a bounded token, so
        the digest binds nothing private.
        """
        canonical = json.dumps(
            self.normalized(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_ceiling(field: str, value: int, ceiling: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EnrollmentBoundsError(f"{field} must be an integer")
    if not 1 <= value <= ceiling:
        raise EnrollmentBoundsError(f"{field} must be between 1 and {ceiling}")


@dataclass(frozen=True, slots=True)
class Enrollment:
    """An accepted enrollment, as persistence returns it.

    The row is the acceptance. It records the normalized grant and the policy
    version it was accepted under, which is what section 9.6 means by "accepted
    normalized enrollment and policy version are audit-bound"; progress against
    it belongs to the jobs that carry it out, not to this value.
    """

    enrollment_id: str
    source_id: str
    principal_id: str
    purpose: Purpose
    scope: EnrollmentScope
    media_types: tuple[str, ...]
    policy_version: str
    request_fingerprint: str
    max_items: int
    max_bytes: int
    accepted_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.enrollment_id, IdKind.ENROLLMENT)
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.media_types:
            raise EnrollmentBoundsError("an enrollment requires a content-type allowlist")
        object.__setattr__(self, "accepted_at", ensure_utc(self.accepted_at))
