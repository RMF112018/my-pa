"""Where a provider's opaque identifiers come from, and how they resolve back.

`FixtureSourceProvider` held three private dictionaries: path to `obj_…`,
`obj_…` to path, and fingerprint to `ver_…`. They are the reason an identifier
lived exactly as long as the provider instance, which `fixture.py`'s "Identifier
lifetime" section states plainly and which was correct for a provider that
persisted nothing. It is not correct for a provider that has to accept an
identifier read out of `knowledge.source_objects`.

The fix is not to derive an identifier from the locator. That would defeat
`INV-PKL-005` while still passing the shape validation
`domain.common.identifiers` performs, and `fixture.py`'s argument against it
stands unchanged. Nor is it to translate between two identifier spaces in the
application, which `D-41` forbids, or to open the filesystem somewhere else,
which would copy `resolve_within`, the hard-link refusal, `O_NOFOLLOW`, the
errno allowlist, and the denial-does-not-discriminate rule — a security boundary,
duplicated.

What changes instead is *who* holds the map. The provider keeps every syscall
and every containment proof it had; the two dictionaries that answered "which
`obj_…` is this path" and "which path is this `obj_…`" become a collaborator it
is handed. There are two answers to that question and both are needed today:
`EphemeralIdentity` for the provider-conformance suite, which is why the FAST
tier stays database-free, and `RegistryIdentity` for a build whose identifiers
have to survive the instance that issued them.

**Nothing here carries a locator outward.** `identify` takes one and `locate`
returns one, and both are called only from inside the provider. The value must
not reach a response, a log, or an error message — the same rule
`persistence.registry.resolve_native_locator` is written under.
"""

from __future__ import annotations

import secrets
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Final

from sqlalchemy import Connection

from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.source.provider import ObjectKind
from my_pa.infrastructure.persistence.registry import (
    UnknownSourceError,
    observe_object,
    resolve_native_locator,
    source_of_object,
)

__all__ = ["EphemeralIdentity", "ObjectIdentity", "RegistryIdentity"]


class ObjectIdentity(ABC):
    """Where a provider's opaque identifiers come from, and how they resolve back.

    Extracted from `FixtureSourceProvider` because there are two answers and
    both are needed today, which is what `AGENTS.md` section 2 requires of an
    abstraction: `EphemeralIdentity` and `RegistryIdentity` below are current
    implementations with current callers, not one implementation and a promise.

    **Not a registry and not a plugin point.** Two methods, two implementations,
    both in this module, and no way to add a third from outside it: nothing
    looks an implementation up by name, nothing reads one from configuration,
    and there is no entry point, no `register`, and no table of kinds. A third
    answer arrives by writing it here and by a reviewer seeing it, which is the
    only extension mechanism this package is allowed.

    The two methods are inverses over one source. `identify` is given the
    provider-native locator of an object the provider has just observed and
    answers with the pair the port speaks in; `locate` is given one of those
    identifiers back and answers with the locator, or with `None` when it names
    nothing this identity issued. `None` rather than an exception, because the
    provider's next act is a denial that must not discriminate between "no such
    identifier" and "not yours".
    """

    @abstractmethod
    def identify(
        self,
        native_locator: str,
        *,
        kind: ObjectKind,
        fingerprint: str,
        media_type: str | None,
        size_bytes: int | None,
        modified_at: datetime,
    ) -> tuple[str, str]:
        """Return `(source_object_id, version_id)` for one observation.

        Idempotent on the pair `(locator, fingerprint)`: the object identity is
        keyed on the locator and the version identity on the fingerprint, so an
        unchanged object keeps both and a rewritten one keeps its `obj_…` and
        gets a new `ver_…`. That is what makes a caller's comparison of two
        `version_id`s a statement about the bytes rather than about how many
        times it asked.
        """

    @abstractmethod
    def locate(self, source_object_id: str) -> str | None:
        """Return the native locator behind an identifier, or `None`.

        `None` is "this identity issued nothing under that identifier". The
        caller turns it into the same denial every other refusal uses; it must
        not be turned into a narrower one.
        """


class EphemeralIdentity(ObjectIdentity):
    """Per-instance identifiers, minted from `secrets.token_hex(16)`.

    The three dictionaries `FixtureSourceProvider` held until now, moved rather
    than rewritten: identifiers are random, are memoised on the locator and on
    the fingerprint respectively, and live exactly as long as this object. Two
    of these over the same tree issue different identifiers for the same file,
    and nothing here persists them, so an identifier does not survive a process
    restart. That consequence was stated in `fixture.py` and is stated here,
    because it moved with the code.

    It is what `tests/provider_conformance` runs against, which is why the FAST
    tier needs no database, and it is what keeps `fixture.py`'s "a suffix
    derived from the path would defeat `INV-PKL-005`" argument true where
    nothing persists anything.
    """

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}
        self._locators: dict[str, str] = {}
        self._versions: dict[str, str] = {}

    def identify(
        self,
        native_locator: str,
        *,
        kind: ObjectKind,
        fingerprint: str,
        media_type: str | None,
        size_bytes: int | None,
        modified_at: datetime,
    ) -> tuple[str, str]:
        """Mint once per locator and once per fingerprint, then memoise.

        `kind`, `media_type`, `size_bytes`, and `modified_at` are accepted and
        not stored. They are what a durable identity records; an in-memory one
        has nowhere to record them and no reader for them, and inventing a
        structure to hold them would be a second copy of `source_objects` with
        no writer behind it.
        """
        object_id = self._ids.get(native_locator)
        if object_id is None:
            object_id = make_identifier(IdKind.SOURCE_OBJECT, secrets.token_hex(16))
            self._ids[native_locator] = object_id
            self._locators[object_id] = native_locator
        version_id = self._versions.get(fingerprint)
        if version_id is None:
            version_id = make_identifier(IdKind.VERSION, secrets.token_hex(16))
            self._versions[fingerprint] = version_id
        return object_id, version_id

    def locate(self, source_object_id: str) -> str | None:
        return self._locators.get(source_object_id)


class RegistryIdentity(ObjectIdentity):
    """Identifiers issued and resolved through `knowledge.source_objects`.

    `identify` is `registry.observe_object`, so an identifier is issued once per
    `(source_id, native_locator)` and looked up thereafter — which is what makes
    it survive a new provider instance and a process restart, and which is the
    whole reason this seam exists. `locate` is `registry.resolve_native_locator`,
    whose result is a bare string precisely so it cannot be passed onward by
    accident.

    **Bound to a `Connection` rather than an `Engine`.** Identity is issued
    inside the caller's transaction, so an enrollment that rolls back issues no
    identifiers and leaves no half-registered object behind. A second connection
    would be the pool cycle `bootstrap.gateway` derives: a caller holding a work
    connection and waiting for a provider connection, at a pool of five, is the
    circular wait that ends in `pool_timeout` rather than in a bound.

    The connection is used and not owned. Opening, committing, closing, and
    disposing are the caller's, which is the same division
    `persistence.registry`'s free functions are written under.
    """

    def __init__(self, connection: Connection, source_id: str) -> None:
        self._connection: Final = connection
        self._source_id: Final = source_id

    def identify(
        self,
        native_locator: str,
        *,
        kind: ObjectKind,
        fingerprint: str,
        media_type: str | None,
        size_bytes: int | None,
        modified_at: datetime,
    ) -> tuple[str, str]:
        observed = observe_object(
            self._connection,
            source_id=self._source_id,
            native_locator=native_locator,
            kind=kind,
            fingerprint=fingerprint,
            modified_at=modified_at,
            media_type=media_type,
            size_bytes=size_bytes,
        )
        return observed.source_object_id, observed.version_id

    def locate(self, source_object_id: str) -> str | None:
        """The locator behind an identifier *this source* issued, or `None`.

        The ownership test is first and is not decoration. `source_objects` is
        one table across every configured source and `resolve_native_locator`
        keys on the object alone, so without it an identifier issued under
        another source would resolve here to that source's locator — and one
        registered root nested inside another would then let a provider serve an
        object it was never given. The provider re-proves containment on what
        this returns, so the leak needs two conditions rather than one; a
        boundary that holds only because a second one also holds is not one this
        module is willing to state.

        Both failures are the same `None`. An identifier that names no row and
        one that names a row under another source are indistinguishable to the
        caller, which is what keeps `fixture.py`'s "denial does not
        discriminate" rule true through this seam rather than only above it.
        """
        owner = source_of_object(self._connection, source_object_id)
        if owner != self._source_id:
            return None
        try:
            locator = resolve_native_locator(self._connection, source_object_id)
        except UnknownSourceError:
            # Deleted between the two statements. READ COMMITTED takes a fresh
            # snapshot per statement, so the window is real; it is the same
            # `None` as never having existed.
            return None
        return locator
