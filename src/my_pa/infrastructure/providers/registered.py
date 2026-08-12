"""The `SourceProviders` lookup of a build whose sources are rows.

`bootstrap.gateway` used to answer `None` for every source, because nothing
registered one and it would not wire a fixture root it had invented. This module
is what replaced that: once an operator has registered a source by exact path,
the lookup that serves it is a read of `knowledge.sources` and not a constant,
and `None` now means only that no row names the source asked for.

**There is no default root and no configured path anywhere in this module.** A
source is served exactly when a row says so, and the row exists exactly when an
operator created it. `P00-OD-009` is open, so which roots are legitimate is the
operator's decision and not this class's; what this class contributes is that
the decision is recorded in one place and read from it, rather than being spread
across a settings default, a constant, and a fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, assert_never

from sqlalchemy import Connection, select

from my_pa.contracts.ports import SourceProviders
from my_pa.domain.source.provider import SourceProvider
from my_pa.domain.source.registry import SourceProviderKind
from my_pa.infrastructure.persistence.tables import sources
from my_pa.infrastructure.providers.fixture import FixtureSourceProvider
from my_pa.infrastructure.providers.identity import RegistryIdentity

__all__ = ["NativeSourceAdapterUnavailableError", "RegisteredSourceProviders"]


class NativeSourceAdapterUnavailableError(RuntimeError):
    """A native-source vocabulary row has no live adapter in this slice."""


class RegisteredSourceProviders(SourceProviders):
    """The adapters the `knowledge.sources` rows name, built on one connection.

    `for_source` reads the row and builds the adapter it names, with a
    `RegistryIdentity` bound to the same connection the read used. That binding
    is the reason this takes a `Connection` rather than an `Engine`: the
    identifiers a provider issues belong to the caller's transaction, so work
    that rolls back issues none, and a provider drawing its own connection while
    a use case holds a work connection is the pool cycle `bootstrap.gateway`
    derives -- a cycle that forms at exactly five concurrent requests and ends in
    `pool_timeout` rather than in a bound.

    A fresh adapter per call, deliberately. It costs one `SELECT` and one
    `stat`, and it is what makes the identifiers durable rather than the
    instance: two lookups over the same source produce two objects that answer
    with the same `obj_…` for the same file, because neither of them is where
    the answer is kept.

    Native Apple kinds are persistence vocabulary in WP-12B, not live adapters.
    They raise an explicit generic error rather than returning `None`, which is
    reserved for an absent source, and without disclosing the stored locator.

    **Not a plugin framework.** There is no table of kinds, nothing is looked up
    by name, and nothing is read from configuration. The one arm names the one
    adapter, and a second arrives by writing it here.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection: Final = connection

    def for_source(self, source_id: str) -> SourceProvider | None:
        """The provider serving `source_id`, or `None` when no row configures one.

        `None` means "not configured", and nothing else. A configured source
        whose root has gone is a different fact and is *not* flattened into it:
        `FixtureSourceProvider.__init__` raises `ValueError` for a root that is
        not an existing directory and that is allowed to propagate, because
        answering `None` would report "there is no such source" for a source the
        operator registered and can see in `sources.list`. Reporting a defect as
        an absence is how a corpus goes missing quietly.

        The row's `native_root` is read here and used here. It is the second
        place a physical locator leaves persistence -- `resolve_native_locator`
        is the first -- and it goes straight into the adapter's constructor
        without being returned, logged, or put in a message.
        """
        row = self._connection.execute(
            select(sources.c.provider_kind, sources.c.native_root).where(
                sources.c.source_id == source_id
            )
        ).one_or_none()
        if row is None:
            return None

        kind = SourceProviderKind(row[0])
        match kind:
            case SourceProviderKind.FIXTURE:
                return FixtureSourceProvider(
                    Path(row[1]),
                    source_id,
                    RegistryIdentity(self._connection, source_id),
                )
            case (
                SourceProviderKind.APPLE_MAIL
                | SourceProviderKind.APPLE_CALENDAR
                | SourceProviderKind.APPLE_CONTACTS
                | SourceProviderKind.APPLE_TASKS
            ):
                raise NativeSourceAdapterUnavailableError(
                    "native source adapters are not composed in WP-12B"
                )
            case _:  # pragma: no cover - exhaustiveness is checked statically
                assert_never(kind)
