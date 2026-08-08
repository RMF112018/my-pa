"""Process configuration.

Settings fail closed. An unknown `MY_PA_` variable, an unparseable value, or an
out-of-range value raises rather than falling back to a default, so a typo in a
security-relevant name cannot silently leave the safe setting in place.

No secret is committed. `database_url` is the one setting whose value may carry a
credential, and it has no default at all. Error messages never echo a setting's
value, so a URL with a password in it cannot leak through a failure.

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

from pydantic import Field, ValidationError, model_validator
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from my_pa.contracts.v1.base import StrictModel
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.domain.extraction.text import MAX_EXTRACTED_CHARACTERS
from my_pa.domain.source.enrollment import MAX_ENROLLMENT_DEPTH
from my_pa.infrastructure.database.engine import POOL_TIMEOUT_SECONDS

__all__ = [
    "DATABASE_URL_SCHEME",
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "ENV_PREFIX",
    "MAX_FETCH_BYTES_CEILING",
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

#: How long one statement may run before the server cancels it, in milliseconds,
#: on every engine whose statements are sized to a request. **Chosen, not
#: inherited: PostgreSQL's own default is `0`, which means no bound at all, and
#: no `statement_timeout` was configured anywhere in this repository until now.**
#:
#: The number is `POOL_TIMEOUT_SECONDS` expressed in milliseconds, and the
#: equality is the argument rather than a coincidence. One request can wait in
#: exactly two places: for a connection, bounded by `pool_timeout`, and then on
#: the server, bounded here. Two ceilings that differ would make the worse of
#: them the real one while the better one described the system, so there is one
#: number and a request's total exposure is twice it.
#:
#: **Computed rather than asserted.** The sentence above was true and written in
#: a comment beside a `30_000` literal that nothing derived, so the claim and the
#: value could part company in silence — the same shape `D-24` corrected and the
#: same one this module's own package was blocked for. The multiplication is the
#: control: change the pool timeout and this follows, or it does not compile.
#:
#: That it is *far* above a healthy statement is the other half, and it is what
#: keeps this a bound on a runaway rather than a limit on the work: the reads
#: this bounds are a keyset-paginated page over a functional GIN index, a
#: single-row lookup on a primary key, and two ungrouped aggregates. None of them
#: is within three orders of magnitude of thirty seconds on the corpus this
#: build serves.
#:
#: It is a default and not a constant, which is the whole of `D-24`'s shape: an
#: operator whose corpus outgrows it raises it without a code change. There is
#: deliberately **no upper bound** on the field — every positive value is a real
#: bound, and choosing a ceiling would be choosing for the operator — but there is
#: a lower one. `gt=0` refuses `0`, which is how PostgreSQL spells "no timeout":
#: the one value that would turn this setting into the absence of the thing it
#: configures cannot be reached through configuration. A caller that genuinely
#: must run unbounded is exempted in code, where the exemption is reviewable.
DEFAULT_STATEMENT_TIMEOUT_MS: Final = POOL_TIMEOUT_SECONDS * 1000


class Environment(StrEnum):
    """Deployment environment. There is no production value in Phase 01."""

    LOCAL = "local"
    TEST = "test"


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


#: The libpq connection parameter a URL may not carry, because
#: `create_database_engine` writes it. SQLAlchemy merges a URL's query string
#: into the driver's connect arguments and lets `connect_args` win, so a URL that
#: sets this would have it **discarded** rather than combined — measured, not
#: inferred: a URL carrying `options=-c search_path=mine` reaches psycopg as
#: `options='-c statement_timeout=30000'` and the operator's parameter is gone.
#:
#: Refused rather than merged, and merging is the tempting wrong answer. libpq
#: lets a later `-c` override an earlier one, so concatenating the two strings
#: would let `options=-c statement_timeout=0` in a URL configure the timeout away
#: — the exact value `statement_timeout_ms`'s `gt=0` exists to make unreachable,
#: reached through a different door.
#:
#: **Refused in every process, and deliberately wider than the override it
#: prevents.** The three callers that pass no timeout at all — `migrations/env.py`
#: and the two bulk-corpus CLIs — would have nothing overridden, so a narrower
#: rule could let them through. It does not, and the reason is that there is one
#: `MY_PA_DATABASE_URL` and many readers of it: a rule that fired only where the
#: override happens would make the same string legal in Alembic and illegal in
#: the gateway, so an operator's parameter would take effect in one process and
#: vanish in another. One variable means one thing everywhere. This is settled
#: rather than provisional, and it is the behaviour the three refusals above
#: already have — none of them asks which process is loading the settings.
_REFUSED_URL_PARAMETER: Final = "options"


def _validate_database_url(url: str) -> None:
    """Reject a URL the engine could not use, before anything tries to connect.

    Names the defect, never the URL: a supplied URL may embed a password.

    **Every rule below reads the URL through `make_url`, which is the parser the
    engine itself uses, and that is the rule rather than an implementation
    detail.** This function previously reasoned with `urlsplit`, and the two do
    not agree: `urlsplit` honours `#` as a fragment delimiter and SQLAlchemy's
    regex does not, so
    `…?x=1#&options=-c%20statement_timeout%3D0` presented `urlsplit` with a query
    of `x=1` and handed psycopg `options='-c statement_timeout=0'` — past the
    refusal below, and to the exact value `statement_timeout_ms`'s `gt=0` exists
    to forbid. Special-casing `#` would have closed that URL and left the class
    open, because the class is *a validator that parses the URL with a different
    parser than the engine does*, and every other divergence between the two is
    the same defect wearing different punctuation. Asking the engine's parser
    makes agreement structural: there is now one parse, and the rules are stated
    about its result.

    The `options` check fails at configuration time rather than at first connect,
    which is the difference between a process that refuses to start and one that
    starts, reports healthy, and silently runs without the parameter its operator
    set.
    """
    # `ArgumentError`'s own message names no credential today, but it is a
    # library message this module does not own, and the raise is placed outside
    # the handler for the reason `persistence.search._execute` gives at length:
    # leaving the handler first is what empties `__context__`, where a rendered
    # traceback would otherwise print whatever the original carried.
    unparseable = False
    try:
        parsed = make_url(url)
    except ArgumentError:
        unparseable = True
    if unparseable or parsed.drivername != DATABASE_URL_SCHEME:
        # A string SQLAlchemy cannot parse as a URL is reported as the scheme
        # failure it is, which is also the answer `urlsplit` gave for it.
        raise SettingsError(f"{ENV_PREFIX}DATABASE_URL must use the {DATABASE_URL_SCHEME} scheme")
    if not parsed.host:
        raise SettingsError(f"{ENV_PREFIX}DATABASE_URL must name a host")
    if not parsed.database:
        raise SettingsError(f"{ENV_PREFIX}DATABASE_URL must name a database")
    # Case-insensitive: SQLAlchemy passes a query key through unchanged, so
    # `OPTIONS=` would reach psycopg as an unknown keyword and fail there
    # instead. Refusing it here reports the real conflict rather than a driver
    # error three layers down.
    if any(name.lower() == _REFUSED_URL_PARAMETER for name in parsed.query):
        raise SettingsError(
            f"{ENV_PREFIX}DATABASE_URL must not set the libpq "
            f"{_REFUSED_URL_PARAMETER} parameter; the engine sets it and would "
            f"discard this one. The statement timeout is configured by "
            f"{ENV_PREFIX}STATEMENT_TIMEOUT_MS"
        )


class Settings(StrictModel):
    """Validated process settings.

    The four limit fields resolve `P00-OD-011` as `D-24` decided it: the values
    Phase 01 published as a module constant become configuration defaults, so an
    operator can change a limit without a code change, and the number published
    by `capabilities.get` is the one the enforcing path reads. They are ordinary
    integers with ordinary bounds; the interesting property is not their range
    but that there is exactly one of each.

    `statement_timeout_ms` is a fifth integer and deliberately **not** a fifth
    limit. `effective_limits` is what `capabilities.get` publishes to a caller,
    and this bounds the server rather than the answer: no request is refused for
    exceeding it, no response reports it, and a caller cannot plan around it. It
    reaches `create_database_engine` and nothing else.
    """

    environment: Environment = Environment.LOCAL
    log_level: LogLevel = LogLevel.INFO
    redaction_enabled: bool = True
    contract_strict_mode: bool = True
    max_page_size: int = Field(default=200, gt=0, le=1000)
    default_page_size: int = Field(default=50, gt=0, le=1000)
    max_fetch_bytes: int = Field(default=8 * 1024 * 1024, gt=0, le=MAX_FETCH_BYTES_CEILING)
    max_enrollment_depth: int = Field(default=0, ge=0, le=MAX_ENROLLMENT_DEPTH)
    statement_timeout_ms: int = Field(default=DEFAULT_STATEMENT_TIMEOUT_MS, gt=0)
    database_url: str

    @model_validator(mode="after")
    def _check(self) -> Settings:
        _validate_database_url(self.database_url)
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
        raise SettingsError(message) from exc
