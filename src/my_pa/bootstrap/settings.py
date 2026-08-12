"""Process configuration.

Settings fail closed. An unknown `MY_PA_` variable, an unparseable value, or an
out-of-range value raises rather than falling back to a default, so a typo in a
security-relevant name cannot silently leave the safe setting in place.

No secret is committed. `database_url` is the one setting whose value may carry a
credential, and it has no default at all. The messages this module composes never
echo a setting's value, and the field is `repr=False` so the value does not ride
out in `repr(settings)` either — the channel that mattered most, because pytest
prints the `repr` of a failing assertion's operands.

Two channels were open here and are named rather than left to be found. The first
is closed. Pydantic's own `ValidationError` renders `input_value=`, and for a
model validator that input is the whole settings mapping, so the rendered error
carries the URL; the rendering elides the middle of a long input, which is why
this looked closed when tested with a long URL and was not, since a short URL is
rendered whole. `load_settings` used to attach that error to the `SettingsError`
it raises, putting the URL within reach of anything that prints a traceback.
It now composes its message inside the handler and raises *outside* the `except`
block, so both `__cause__` and `__context__` are `None` and no rendering of the
chain — `traceback.format_exception`, `logging.exception`, an unhandled
traceback — reaches the value. `raise … from None` would not have sufficed: it
clears `__cause__` and sets `__suppress_context__`, which quiets those two
renderers, but leaves the `ValidationError` on `__context__` for anything that
walks the chain itself to read out of. Nothing diagnostic was
traded for this; the composed message still names every rejected field with its
reason. `infrastructure.persistence.search._execute` holds bound query text with
the same idiom, and `tests/unit/test_settings.py` walks the chain rather than
reading `str(exc)`, because reading only the top-level message is what let this
survive a review.

The second channel is open by design: `model_dump` and `model_dump_json` return
`database_url` with its password. They are asked for explicitly rather than
reached by accident, and callers must not log their output. `repr`, `str` and the
exception chain are the paths something reaches without meaning to, and those are
the ones closed.

`MY_PA_DATABASE_URL` is required rather than defaulted, which resolves
`P00-OD-008`. That decision's stated default was to fail closed when the URL is
absent; a default silently aimed every unconfigured process at the canonical
`my_pa` database. The convenience was illusory, because the canonical database
needs a password supplied out of band anyway — so an unset URL either failed to
connect, or, in the one configuration where it worked, pointed a destructive
operation at the migrated corpus. `apps/cli/migration.py` is that path, and it
now refuses to start rather than choosing a target.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from pydantic import Field, PrivateAttr, ValidationError, model_validator
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from my_pa.contracts.v1.base import StrictModel
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.domain.extraction.text import MAX_EXTRACTED_CHARACTERS
from my_pa.domain.source.enrollment import MAX_ENROLLMENT_DEPTH

__all__ = [
    "DATABASE_URL_SCHEME",
    "ENV_PREFIX",
    "MAX_FETCH_BYTES_CEILING",
    "AuthMode",
    "Environment",
    "LogLevel",
    "Settings",
    "SettingsError",
    "load_settings",
]

ENV_PREFIX: Final = "MY_PA_"

#: The only accepted driver. Pinning the scheme rather than accepting bare
#: `postgresql://` keeps a stray `psycopg2` or `asyncpg` install from silently
#: changing which driver the process talks to.
DATABASE_URL_SCHEME: Final = "postgresql+psycopg"

#: Most bytes `sources.fetch` may be configured to read from one object, derived
#: rather than chosen. `D-35` accepts a provider read inside the database
#: transaction *on the ground that the read is bounded*, so this number is also a
#: bound on how long a transaction stays open, and it has to be one a transaction
#: can survive. A ceiling of a gibibyte does not carry that argument.
#:
#: What the MCV extracts is text and Markdown, and `extract_text` quarantines
#: anything decoding to more than `MAX_EXTRACTED_CHARACTERS` as
#: `RESOURCE_LIMIT_EXCEEDED`. A UTF-8 character is at most four bytes, so four
#: bytes per permitted character is the point past which no additional byte can
#: belong to a document this build could ever extract: a larger fetch reads bytes
#: whose only possible outcome is a quarantine. That makes 16 MiB the widest
#: ceiling with a reason behind it rather than the largest round number.
#:
#: Deliberately expressed as the product and not as `16 * 1024 * 1024`. If the
#: extraction bound moves, this moves with it, and the two cannot drift into
#: disagreeing about what a readable document can be.
MAX_FETCH_BYTES_CEILING: Final = MAX_EXTRACTED_CHARACTERS * 4


class Environment(StrEnum):
    """Deployment environment. There is no production value in Phase 01."""

    LOCAL = "local"
    TEST = "test"


class AuthMode(StrEnum):
    """How the HTTP transport establishes the acting Principal.

    Two values, declared rather than inferred. `local_operator` is `D-30` as it
    has always run: loopback is the trust boundary, the composition root issues
    one durable local principal, and no credential is read. `entra` requires a
    bearer token on every request and derives the Principal from its validated
    `(tid, oid)` claims.

    There is no third value and no inference. A deployment that means to
    authenticate says so, and one that names `entra` without the configuration
    it needs does not start — see `Settings._check`. The failure mode this
    forecloses is the one that matters: a missing tenant ID quietly selecting
    the unauthenticated mode on a process an operator believed was
    authenticating.
    """

    LOCAL_OPERATOR = "local_operator"
    ENTRA = "entra"


class LogLevel(StrEnum):
    """Log verbosity."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SettingsError(ValueError):
    """Raised by `load_settings` when configuration is missing, unknown, or invalid.

    Constructing `Settings` directly raises Pydantic's `ValidationError` instead,
    because Pydantic wraps whatever a validator raises. `load_settings` is the
    supported entry point and normalises both cases to this type.
    """


def _parse_database_url(url: str) -> URL:
    """Parse the URL once, reject one the engine could not use, and return the parse.

    The parser here is SQLAlchemy's, and that is the whole point. `create_engine`
    parses whatever string it is handed with `make_url`, so a check performed by
    any other parser is a check on a different reading of the same text: the
    scheme, host and database approved here would not have to be the scheme, host
    and database the process then connects to. Two parsers agreeing on ordinary
    input is not the same as there being one answer.

    So there is one parse. The `URL` this returns is the object the caller hands
    to `create_database_engine`, and `create_engine` returns a `URL` unchanged
    rather than parsing it again — which is what leaves no second reading to
    diverge from the first.

    Names the defect, never the URL: a supplied URL may embed a password.
    `ArgumentError` and `ValueError` are both reachable from `make_url` — a
    string it cannot match, and a match whose port is not a number — and the
    second carries the offending text, so neither is allowed to propagate.
    """
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError) as exc:
        raise SettingsError(
            f"{ENV_PREFIX}DATABASE_URL is not a URL the engine can parse; it "
            f"must use the {DATABASE_URL_SCHEME} scheme and name a host and a database"
        ) from exc
    if parsed.drivername != DATABASE_URL_SCHEME:
        raise SettingsError(f"{ENV_PREFIX}DATABASE_URL must use the {DATABASE_URL_SCHEME} scheme")
    if not parsed.host:
        raise SettingsError(f"{ENV_PREFIX}DATABASE_URL must name a host")
    if not parsed.database:
        raise SettingsError(f"{ENV_PREFIX}DATABASE_URL must name a database")
    return parsed


class Settings(StrictModel):
    """Validated process settings.

    The four limit fields resolve `P00-OD-011` as `D-24` decided it: the values
    Phase 01 published as a module constant become configuration defaults, so an
    operator can change a limit without a code change, and the number published
    by `capabilities.get` is the one the enforcing path reads. They are ordinary
    integers with ordinary bounds; the interesting property is not their range
    but that there is exactly one of each.
    """

    environment: Environment = Environment.LOCAL
    log_level: LogLevel = LogLevel.INFO
    #: Which authentication mode the transport composes. Defaults to the
    #: unauthenticated loopback mode this build has always run, because that is
    #: the behaviour every existing deployment has; selecting `entra` is a
    #: deliberate edit and carries the four fields below with it.
    auth_mode: AuthMode = AuthMode.LOCAL_OPERATOR
    #: The four values `entra` mode requires. Each defaults to empty rather than
    #: to a plausible-looking value, so "unset" and "set to something useless"
    #: are the same startup failure rather than two different ones.
    #:
    #: `repr=False` on all four for the reason `database_url` carries it: these
    #: are the live tenant's own identifiers, `SECURITY.md` treats a real tenant
    #: ID as a value that must not be committed or printed, and pytest renders
    #: the `repr` of a failing assertion's operands. None of them is a
    #: credential — a tenant ID, an application ID, an issuer URL and a JWKS URL
    #: are all public knowledge to anyone holding a token — so this closes a
    #: disclosure channel rather than protecting a secret.
    entra_tenant_id: str = Field(default="", repr=False)
    entra_client_id: str = Field(default="", repr=False)
    entra_issuer: str = Field(default="", repr=False)
    entra_jwks_uri: str = Field(default="", repr=False)
    redaction_enabled: bool = True
    contract_strict_mode: bool = True
    max_page_size: int = Field(default=200, gt=0, le=1000)
    default_page_size: int = Field(default=50, gt=0, le=1000)
    max_fetch_bytes: int = Field(default=8 * 1024 * 1024, gt=0, le=MAX_FETCH_BYTES_CEILING)
    max_enrollment_depth: int = Field(default=0, ge=0, le=MAX_ENROLLMENT_DEPTH)
    #: `repr=False` because this is the one field that can hold a password, and
    #: `repr` is where it escaped. Pydantic's generated `repr` — which `str` also
    #: uses — printed every field's value, so `Settings(… database_url='…')`
    #: appeared verbatim wherever a `Settings` object was rendered. The channel
    #: that made it more than theoretical is the test suite: pytest's assertion
    #: rewriting prints the `repr` of every operand in a failing comparison, so
    #: one unrelated failing assertion holding a `Settings` would have put a live
    #: DSN into CI output, which `SECURITY.md` treats as disclosure regardless of
    #: how it got there.
    #:
    #: Deliberately not `SecretStr`. That would change the field's type and every
    #: consumer would have to unwrap it — a far wider change than the disclosure
    #: warrants. `repr=False` closes `repr` and `str` and touches nothing else.
    #: It does **not** close `model_dump`/`model_dump_json`, which are asked for
    #: explicitly rather than reached by accident. Pydantic's own
    #: `ValidationError` rendering was the other way out and is closed in
    #: `load_settings`, which raises outside its `except` block; see the module
    #: docstring and the tests.
    database_url: str = Field(repr=False)

    #: The single parse of `database_url`, produced by validation and handed on
    #: unchanged. Private because it is not configuration an operator supplies
    #: and must not become a second place a URL can enter from.
    _parsed_database_url: URL = PrivateAttr()

    @model_validator(mode="after")
    def _check(self) -> Settings:
        self._parsed_database_url = _parse_database_url(self.database_url)
        self._check_auth_mode()
        if not self.redaction_enabled:
            raise SettingsError(
                "redaction cannot be disabled; debug mode does not bypass redaction"
            )
        if not self.contract_strict_mode:
            raise SettingsError("strict contract parsing cannot be disabled")
        # Built rather than checked field by field: `EffectiveLimits` already
        # holds the one cross-field rule these have, and constructing it here
        # means a configuration that cannot produce a publishable manifest fails
        # at startup instead of at the first `capabilities.get`.
        self.effective_limits()
        return self

    def _check_auth_mode(self) -> None:
        """`entra` mode without its configuration refuses to start.

        Fail closed, and closed in the direction that matters: the alternative
        an unconfigured `entra` could have taken is `local_operator`, which
        serves every request as the local operator with no credential at all.
        Downgrading silently would turn one missing environment variable into an
        open gateway, so a missing value ends the process instead.

        The message names the settings and never their values. It is also the
        whole diagnostic — an operator who sets three of four is told which one
        is missing, not merely that something is.
        """
        if self.auth_mode is not AuthMode.ENTRA:
            return
        required = {
            "entra_tenant_id": self.entra_tenant_id,
            "entra_client_id": self.entra_client_id,
            "entra_issuer": self.entra_issuer,
            "entra_jwks_uri": self.entra_jwks_uri,
        }
        missing = sorted(
            f"{ENV_PREFIX}{name.upper()}" for name, value in required.items() if not value.strip()
        )
        if missing:
            raise SettingsError(
                f"{ENV_PREFIX}AUTH_MODE is {AuthMode.ENTRA.value!r} and requires "
                f"{', '.join(missing)}, which {'is' if len(missing) == 1 else 'are'} "
                "unset or blank. There is no inference and no downgrade to "
                f"{AuthMode.LOCAL_OPERATOR.value!r}: an unconfigured authenticated "
                "mode would serve every request as the local operator"
            )

    def parsed_database_url(self) -> URL:
        """`database_url` as validation read it, for `create_database_engine`.

        Returns the stored parse rather than parsing again, so the URL the engine
        is configured with is the same object validation approved and not a
        second reading of the same string. Pass this, not `database_url`, to
        anything that opens a connection.

        Two Pydantic entry points bypass the validator that fills the parse and
        so break this accessor by design, neither of which anything calls:
        `model_copy(update={"database_url": …})` leaves the stored parse
        describing the *old* string, and `model_construct(…)` never sets it at
        all, so this raises `AttributeError`. Build settings with
        `load_settings` or `Settings(...)`.
        """
        return self._parsed_database_url

    def effective_limits(self) -> EffectiveLimits:
        """The configured limits, as the shape `capabilities.get` publishes.

        One object, built from validated configuration and handed to the
        application, which enforces it and publishes it. There is no second copy
        for the published number to drift from (`D-24`).
        """
        try:
            return EffectiveLimits(
                max_page_size=self.max_page_size,
                default_page_size=self.default_page_size,
                max_fetch_bytes=self.max_fetch_bytes,
                max_enrollment_depth=self.max_enrollment_depth,
            )
        except ValidationError as exc:
            # Names the rule, never the values: the message Pydantic produces for
            # this model states only which invariant failed.
            raise SettingsError(
                f"invalid configuration: {'; '.join(error['msg'] for error in exc.errors())}"
            ) from exc


_FIELD_NAMES: Final = frozenset(Settings.model_fields)

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _coerce(name: str, raw: str) -> object:
    """Convert one environment string to the type its field expects."""
    # Typed as `object` so identity checks below are plain comparisons rather
    # than type narrowing, which would make the second branch look unreachable.
    annotation: object = Settings.model_fields[name].annotation
    if annotation is bool:
        lowered = raw.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        # Name the setting and the expected type, never the supplied value.
        # `database_url` can carry a password, so echoing input here would be a
        # disclosure channel.
        raise SettingsError(f"{ENV_PREFIX}{name.upper()} must be a boolean")
    if annotation is int:
        try:
            return int(raw)
        except ValueError as exc:
            raise SettingsError(f"{ENV_PREFIX}{name.upper()} must be an integer") from exc
    return raw


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Build `Settings` from `environ`, defaulting to the process environment.

    Any `MY_PA_`-prefixed variable that does not name a field is an error.
    Ignoring it would let `MY_PA_REDACTION_ENABLE=false` look accepted while
    redaction stayed on under a different name — or, worse, the reverse.
    """
    source = os.environ if environ is None else environ
    values: dict[str, object] = {}
    unknown: list[str] = []

    for key, raw in source.items():
        if not key.startswith(ENV_PREFIX):
            continue
        name = key[len(ENV_PREFIX) :].lower()
        if name not in _FIELD_NAMES:
            unknown.append(key)
            continue
        values[name] = _coerce(name, raw)

    if unknown:
        raise SettingsError(f"unknown {ENV_PREFIX} settings: {sorted(unknown)}")

    # Composed inside the handler, raised outside it. See the `raise` below.
    message = ""
    try:
        return Settings(**values)  # type: ignore[arg-type]
    except ValidationError as exc:
        # Report which setting failed and why, but not the offending value.
        # `database_url` can carry a password, so echoing inputs here would turn
        # this into a disclosure channel.
        problems = "; ".join(
            f"{ENV_PREFIX}{'.'.join(str(part) for part in error['loc']).upper()}: {error['msg']}"
            for error in exc.errors()
        )
        message = f"invalid configuration: {problems}"
        if any(
            error["type"] == "missing" and error["loc"] == ("database_url",)
            for error in exc.errors()
        ):
            # Appended rather than raised early, so a run that is missing the URL
            # *and* has another bad value reports both. "Field required" alone
            # does not tell an operator what to do, and this is the one they meet
            # at startup. It has no default on purpose; see the module docstring
            # and `P00-OD-008`.
            message += (
                f". {ENV_PREFIX}DATABASE_URL has no default: set it to a "
                f"{DATABASE_URL_SCHEME} URL naming a host and a database, and "
                "supply the password out of band through PGPASSWORD or "
                "~/.pgpass rather than committing one"
            )
    # Outside the `except` block on purpose, and this is the whole disclosure
    # control — the same idiom `infrastructure.persistence.search._execute` uses
    # for bound query text. Pydantic's `ValidationError` renders `input_value=`,
    # and for a model validator that input is the entire settings mapping, so the
    # rendered error contains the DSN verbatim. `raise … from exc` published it on
    # `__cause__`, where `traceback.format_exception` and `logging.exception` both
    # printed it. `raise … from None` is not the fix: it sets
    # `__suppress_context__`, which stops those two printing, but leaves the
    # `ValidationError` on `__context__` for anything that walks the chain itself
    # to read. Leaving the handler before raising is what empties both links.
    # Nothing diagnostic is lost: `message` above already names every rejected
    # field with its reason.
    raise SettingsError(message)
