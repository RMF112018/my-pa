"""Process configuration.

Settings fail closed. An unknown `MY_PA_` variable, an unparseable value, or an
out-of-range value raises rather than falling back to a default, so a typo in a
security-relevant name cannot silently leave the safe setting in place.

No secret is committed. `database_url` and the origin OAuth operator approval
secrets (production remote MCP and isolated GSQS remote-eval) are the settings
whose values may carry credentials; none has a usable default. The messages this
module composes never echo those values, and the fields are `repr=False` so they
do not ride out in `repr(settings)` either — the channel that mattered most,
because pytest prints the `repr` of a failing assertion's operands.

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
those credential-bearing fields. They are asked for explicitly rather than
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
from urllib.parse import urlsplit

from pydantic import Field, PrivateAttr, ValidationError, model_validator
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from my_pa.contracts.oauth import valid_operator_secret
from my_pa.contracts.v1.base import StrictModel
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.domain.extraction.text import MAX_EXTRACTED_CHARACTERS
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.domain.source.enrollment import MAX_ENROLLMENT_DEPTH

__all__ = [
    "DATABASE_URL_SCHEME",
    "ENV_PREFIX",
    "MAX_FETCH_BYTES_CEILING",
    "AuthMode",
    "Environment",
    "GatewayBindMode",
    "GoodNotesRolloutStage",
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


class GatewayBindMode(StrEnum):
    """Where the gateway listens: local host or explicitly inside a container."""

    LOOPBACK = "loopback"
    CONTAINER = "container"


class LogLevel(StrEnum):
    """Log verbosity."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class GoodNotesRolloutStage(StrEnum):
    """One current GoodNotes Durable Note rollout stage. Default is observe-only.

    Unknown values fail closed at parse. The optional TBR bridge value is
    representable so the combination can be named, and resolving or enabling it
    still fails closed. Boolean capability gates must be a consistent prefix
    for the selected stage; mismatch fails closed rather than dropping down.
    """

    OBSERVE_ONLY = "observe-only"
    PAGE_IDENTITY_DRY_RUN = "page-identity-dry-run"
    SEMANTIC_PROPOSALS_WITHOUT_CANONICAL_NOTE_WRITES = (
        "semantic-proposals-without-canonical-note-writes"
    )
    CANONICAL_WRITES_WITH_DELIVERY_DISABLED = "canonical-writes-with-delivery-disabled"
    NEW_ONLY_SUMMARY_PREVIEW = "new-only-summary-preview"
    OPERATOR_REVIEWED_DELIVERY_CANARY = "operator-reviewed-delivery-canary"
    BOUNDED_SCHEDULED_OPERATION = "bounded-scheduled-operation"
    OPTIONAL_TBR_BRIDGE = "optional-tbr-bridge"


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


def _is_https_origin(value: str) -> bool:
    """True when `value` is an HTTPS origin with no extra path, query, or userinfo."""
    parsed = urlsplit(value.strip())
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )


def _is_https_mcp_resource(value: str) -> bool:
    """True when `value` is an HTTPS origin plus the exact `/mcp` resource path."""
    parsed = urlsplit(value.strip())
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.path == "/mcp"
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )


def _split_allowlist(raw: str) -> tuple[str, ...]:
    """Split a comma- or space-separated allowlist. Empty input is an empty tuple."""
    return tuple(token for token in raw.replace(",", " ").split() if token)


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
    #: Whether the authenticated remote capture ingress serves at all (WP-10).
    #:
    #: **Off by default, and the default is the fail-closed one.** An
    #: unconfigured process — no variable set, a typo in the name, a `.env` that
    #: was not loaded — serves no remote ingress, because `False` is what the
    #: absent value produces. There is no third state and no inference: the
    #: alternative default would mean a deployment acquires a credential-bearing
    #: ingress by forgetting something, which is the direction `AGENTS.md`
    #: section 5 forbids.
    #:
    #: **It is not the only gate, and it is not the one that reaches a network.**
    #: `apps/gateway.py` binds `127.0.0.1` as a constant with no flag (`D-30`),
    #: so turning this on exposes the ingress to the loopback interface and to
    #: nothing else. Publishing it — a TLS-terminating reverse proxy, a tunnel,
    #: a port forward — is an operator act outside this repository and is
    #: reserved to them under `AGENTS.md` section 8.2.
    #: Where the managed-document write plane stores bytes (WP-27).
    #:
    #: **Empty by default, and empty means there is no managed plane.** A process
    #: that has not been told where managed bytes go composes no byte store, so
    #: an unconfigured or mistyped deployment cannot write a managed document at
    #: all — the fail-closed direction, and the same one `remote_ingress_enabled`
    #: takes. There is no default location and no inference: choosing where a
    #: user's documents live is an operator decision, and a default would put one
    #: in the working directory of whichever process started first.
    #:
    #: **Separate from every source root, and separate by construction rather
    #: than by comparison.** A source root is a `knowledge.sources.native_root`
    #: row an operator registered through `apps/cli/sources.py`; this is process
    #: configuration. Two different channels, so there is no single value that
    #: could be read as both. The overlap check is still made, after full path
    #: resolution, when the store is constructed —
    #: `infrastructure.managed_document_stores.filesystem.store` refuses a
    #: managed root that is, contains, or lies inside a configured source root,
    #: including through a symbolic link.
    #:
    #: **It holds no credential, and that is stated rather than left as an
    #: absence.** The managed store in this build is a local filesystem reached
    #: with the process's own identity, so there is nothing to hold; a remote
    #: managed store is an EXT-10 operator-gated seam and would carry its own
    #: `MY_PA_MANAGED_DOCUMENT_*` credential setting rather than reuse any source
    #: one. Adding an unused credential field today would be the speculative
    #: configuration `AGENTS.md` section 2 rules out.
    managed_document_root: str = ""
    #: The Frontier MCP surface's kill switch (WP-28).
    #:
    #: **The switch is off by default and the surface serves**, which is the
    #: opposite default from `remote_ingress_enabled` and is the right one for a
    #: different reason. The remote ingress reaches a *network*, so an
    #: unconfigured process must not serve it. This surface reaches a **pipe**:
    #: `apps/gateway.py mcp` is a process an operator starts deliberately, on
    #: stdio, with no socket and no credential (`D-26`, `D-30`), so "serving" is
    #: already an act rather than an accident and a second flag to turn it on
    #: would only mean the operator who started it has to say so twice.
    #:
    #: What this is for is the other direction: **withdrawing** the surface from a
    #: client that is already using it, without stopping the gateway, changing a
    #: source root or touching the database. Engaging it makes `tools/list`
    #: publish nothing *and* `tools/call` refuse — a switch that only hid the
    #: tools would leave every name a client already knows reachable, and a client
    #: that has spoken to this server before knows all of them.
    #:
    #: **A malformed value fails closed by refusing to start.** `_coerce` accepts
    #: only the boolean spellings and raises `SettingsError` for anything else, so
    #: `MY_PA_MCP_SURFACE_DISABLED=maybe` is a process that does not run rather
    #: than a switch silently read as `False`.
    mcp_surface_disabled: bool = False
    remote_mcp_enabled: bool = False
    remote_writes_enabled: bool = False
    #: Process-local gates for GoodNotes Durable Note Ingestion rollout (WP-15).
    #: All default off. True does not ingest, write canonical notes, deliver,
    #: call Abacus, mutate NAS, or change the existing TBR Task.
    #: `bootstrap.goodnotes_rollout` reads the six booleans and the ordered
    #: stage; `bootstrap.goodnotes_durable_note` still reads the intelligence
    #: gate and composes the orchestrator against the resolved stage.
    #: `bootstrap.goodnotes` (bounded OCR/review) and `bootstrap.goodnotes_tbr`
    #: (GN-09 contract) do not. Semantic Agent work dispatch reuses the
    #: existing intelligence gate. The stage defaults to observe-only; unknown
    #: values fail closed. Selecting the TBR bridge stage remains unauthorized.
    goodnotes_durable_note_ingestion_enabled: bool = False
    goodnotes_durable_note_intelligence_enabled: bool = False
    goodnotes_canonical_semantic_writes_enabled: bool = False
    goodnotes_user_facing_summary_delivery_enabled: bool = False
    goodnotes_tbr_bridge_enabled: bool = False
    #: Process-local gate for the relationship-intelligence entity plane
    #: (WP-RI-05). Default off. True publishes six read capabilities over the
    #: acting Principal's own entities; it enables no write, no observation, and
    #: no source traversal, because none exists. Off by default because the
    #: remote MCP profile is derived from the capability set with no
    #: per-capability exclusion list, so "available" and "remotely reachable"
    #: are one decision and this is where it is made.
    relationship_intelligence_enabled: bool = False
    #: Process-local gate for the Relationship Memory plane. Default off, and it
    #: requires `relationship_intelligence_enabled` as well: a memory binds a
    #: generalized Entity as its subject and the repository proves ownership of
    #: that subject by reading the entity tables, so serving memories without the
    #: plane that owns their subjects would be serving writes it cannot validate.
    #:
    #: A switch of its own rather than a reuse of the entity flag, because the
    #: two admit different things. The entity flag publishes six *read*
    #: capabilities over identity. This one publishes four reads and four
    #: **writes** over the most private records this product holds, and the
    #: remote MCP profile is derived from the capability set with no
    #: per-capability exclusion list — so "available" and "remotely reachable"
    #: are one decision, and an operator who wants entity reads should not have
    #: to accept memory authoring to get them.
    relationship_memory_enabled: bool = False
    goodnotes_self_improving_optimizer_enabled: bool = False
    goodnotes_rollout_stage: GoodNotesRolloutStage = GoodNotesRolloutStage.OBSERVE_ONLY
    remote_mcp_public_host: str = ""
    #: Isolated GSQS ChatLLM remote-eval MCP process. Not production MCP.
    #:
    #: **Off by default.** An unconfigured process serves `/healthz` only; `/mcp`
    #: is 404 and `/readyz` is 503. Enabling it is an operator act on a separate
    #: process (`apps/gsqs_remote_eval.py`) and does not publish production MCP,
    #: mutate source systems, or admit Phase C.
    #:
    #: **`state_root` is empty by default on purpose.** The intended NAS path is
    #: `/srv/my-pa/gsqs-remote-eval` and is documented on the entrypoint, not
    #: implicit here. Tests must override to a temporary directory and must never
    #: use `/srv`. When the switch is on, an empty root fails closed.
    #:
    #: **Live OAuth secrets are not required to parse Settings while disabled.**
    #: The evaluation audience defaults to the public resource URL; it is not a
    #: credential. Production `oauth_operator_secret` remains the remote-MCP
    #: secret and is not reused here. Enabling requires a dedicated
    #: `gsqs_remote_eval_oauth_operator_secret`; it must not equal the
    #: production secret when both are set.
    gsqs_remote_eval_enabled: bool = False
    gsqs_remote_eval_public_origin: str = ""
    gsqs_remote_eval_port: int = Field(default=8767, ge=1, le=65535)
    gsqs_remote_eval_state_root: str = ""
    gsqs_remote_eval_session_ttl_seconds: int = Field(default=259200, ge=3600, le=259200)
    gsqs_remote_eval_retention_seconds: int = Field(default=1_209_600, gt=0)
    gsqs_remote_eval_max_image_bytes: int = Field(default=8_388_608, gt=0)
    gsqs_remote_eval_max_result_bytes: int = Field(default=1_048_576, gt=0)
    gsqs_remote_eval_max_concurrency: int = Field(default=1, ge=1, le=1)
    gsqs_remote_eval_oauth_scope: str = "my-pa.gsqs.evaluate"
    gsqs_remote_eval_allowed_origins: str = ""
    gsqs_remote_eval_oauth_audience: str = "https://my-pa-gsqs.bobby-fetting.me/mcp"
    gsqs_remote_eval_oauth_operator_secret: str = Field(default="", repr=False)
    #: Legacy Entra verifier inputs remain available only to the dormant
    #: `auth_mode=entra` path. Remote MCP never reads them.
    oauth_issuer: str = Field(default="", repr=False)
    oauth_audience: str = Field(default="", repr=False)
    oauth_jwks_uri: str = Field(default="", repr=False)
    oauth_tenant_id: str = Field(default="", repr=False)
    oauth_authorization_server: str = Field(default="", repr=False)
    oauth_scopes: str = ""
    oauth_operator_secret: str = Field(default="", repr=False)
    #: Which registered capture client this MCP process serves as, or empty for
    #: none (WP-28).
    #:
    #: **Empty is the default and means what it says: no client is bound**, which
    #: is every process this build has ever run. Setting it binds the surface to a
    #: row in `knowledge.capture_clients` — the registry WP-10 built and the same
    #: one `revoke_client` writes to — and the composition root refuses to serve
    #: when that row is absent or revoked. So revoking a client through the
    #: existing operator path withdraws this surface at the next start, with no
    #: second registry and no second revocation vocabulary.
    #:
    #: **It is an identifier and never a secret.** A client identifier is public
    #: to whoever holds it; the secret digest stays in the database and this
    #: process neither reads nor presents one, because stdio carries no
    #: credential (`D-30`). Binding is therefore *identification* and not
    #: authentication, and the module docstring of `bootstrap.gateway` says so
    #: where an operator reads it. Authenticating an external MCP client requires
    #: an ingress that does not exist (EXT-07/EXT-08).
    mcp_client_id: str = ""
    gateway_bind_mode: GatewayBindMode = GatewayBindMode.LOOPBACK
    remote_ingress_enabled: bool = False
    apple_ingress_enabled: bool = False
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

    def gateway_bind_host(self) -> str:
        """Return the only address admitted for the selected deployment boundary."""
        return (
            "0.0.0.0"  # noqa: S104 - container namespace only; no host publication
            if self.gateway_bind_mode is GatewayBindMode.CONTAINER
            else "127.0.0.1"
        )

    #: The single parse of `database_url`, produced by validation and handed on
    #: unchanged. Private because it is not configuration an operator supplies
    #: and must not become a second place a URL can enter from.
    _parsed_database_url: URL = PrivateAttr()

    @model_validator(mode="after")
    def _check(self) -> Settings:
        self._parsed_database_url = _parse_database_url(self.database_url)
        self._check_auth_mode()
        if self.remote_mcp_enabled and not all(
            (
                self.oauth_audience.strip(),
                self.oauth_authorization_server.strip(),
                self.oauth_scopes.strip(),
                valid_operator_secret(self.oauth_operator_secret),
                self.remote_mcp_public_host.strip(),
            )
        ):
            raise SettingsError(
                "remote MCP requires its origin OAuth authorization server, audience, scopes, "
                "generated operator secret, and public host"
            )
        if self.remote_mcp_enabled and self.auth_mode is not AuthMode.LOCAL_OPERATOR:
            raise SettingsError("remote MCP requires the canonical local_operator identity mode")
        if self.remote_mcp_enabled:
            issuer = urlsplit(self.oauth_authorization_server)
            resource = urlsplit(self.oauth_audience)
            if (
                issuer.scheme != "https"
                or not issuer.hostname
                or issuer.path not in ("", "/")
                or issuer.query
                or issuer.fragment
                or issuer.username is not None
                or issuer.password is not None
                or resource.scheme != "https"
                or resource.netloc != issuer.netloc
                or resource.path != "/mcp"
                or resource.query
                or resource.fragment
                or self.remote_mcp_public_host != issuer.hostname
            ):
                raise SettingsError(
                    "remote MCP OAuth requires one exact HTTPS public origin and its /mcp resource"
                )
        self._check_gsqs_remote_eval()
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

    def _check_gsqs_remote_eval(self) -> None:
        """Fail closed for the isolated eval process. Independent of remote MCP."""
        if self.gsqs_remote_eval_max_concurrency != 1:
            raise SettingsError("GSQS remote-eval max concurrency must equal 1")
        origins = self.gsqs_remote_eval_origin_allowlist()
        if any(origin == "*" or "*" in origin for origin in origins):
            raise SettingsError("GSQS remote-eval allowed origins must not contain a wildcard")
        audience = self.gsqs_remote_eval_oauth_audience.strip()
        if not _is_https_mcp_resource(audience):
            raise SettingsError(
                "GSQS remote-eval OAuth audience must be an HTTPS origin with path /mcp"
            )
        public_origin = self.gsqs_remote_eval_public_origin.strip()
        if public_origin and not _is_https_origin(public_origin):
            raise SettingsError(
                "GSQS remote-eval public origin must be an HTTPS origin without "
                "path, query, or fragment"
            )
        if not self.gsqs_remote_eval_oauth_scope.strip():
            raise SettingsError("GSQS remote-eval OAuth scope is required")
        eval_secret = self.gsqs_remote_eval_oauth_operator_secret
        production_secret = self.oauth_operator_secret
        if eval_secret and production_secret and eval_secret == production_secret:
            raise SettingsError(
                "GSQS remote-eval OAuth operator secret must not equal the "
                "production OAuth operator secret"
            )
        if not self.gsqs_remote_eval_enabled:
            return
        if not valid_operator_secret(eval_secret):
            raise SettingsError(
                "GSQS remote-eval requires MY_PA_GSQS_REMOTE_EVAL_OAUTH_OPERATOR_SECRET "
                "as a generated URL-safe operator secret"
            )
        if not public_origin:
            raise SettingsError(
                "GSQS remote-eval requires MY_PA_GSQS_REMOTE_EVAL_PUBLIC_ORIGIN as an "
                "HTTPS origin without path, query, or fragment"
            )
        if not self.gsqs_remote_eval_state_root.strip():
            raise SettingsError(
                "GSQS remote-eval requires MY_PA_GSQS_REMOTE_EVAL_STATE_ROOT; the "
                "intended runtime path is /srv/my-pa/gsqs-remote-eval and tests "
                "must override it"
            )
        origin = urlsplit(public_origin)
        resource = urlsplit(audience)
        if resource.netloc != origin.netloc:
            raise SettingsError(
                "GSQS remote-eval OAuth audience must be the public HTTPS origin with path /mcp"
            )

    def gsqs_remote_eval_origin_allowlist(self) -> tuple[str, ...]:
        """Exact allowed Origin values. Empty means no browser Origin is admitted."""
        return _split_allowlist(self.gsqs_remote_eval_allowed_origins)

    def gsqs_remote_eval_transport_hosts(self, *, bind_host: str, port: int) -> tuple[str, ...]:
        """Exact Host values for DNS-rebinding protection. No wildcards."""
        hosts: list[str] = [bind_host, f"{bind_host}:{port}"]
        hostname = urlsplit(self.gsqs_remote_eval_public_origin.strip()).hostname
        if hostname:
            hosts.append(hostname)
            hosts.append(f"{hostname}:{port}")
        return tuple(dict.fromkeys(hosts))

    def admissible_client_principal_id(self) -> str | None:
        """The single Principal this process may bind a capture client to, or `None`.

        `local_operator` is the mode that has an answer: the process serves one
        fixed Principal, so a client minted here belongs to that Principal and a
        client row naming any other one is refused — at minting *and* at every
        authentication. That refusal is what keeps a remote credential from
        introducing a **second** Principal holding real data on a web tier that
        `D-15` pins to exactly one, which is the condition WP-08's NOTE 1 names
        as its release blocker. This package's decision is to not create it.

        `entra` has no answer *here*, and `None` says so rather than guessing:
        that mode authenticates real people per request, two real Principals are
        two real datasets, and a client binds to whichever Principal was
        authenticated when it was minted. `domain.capture.client.admit_client_binding`
        reads `None` as "any authenticated Principal", which is the only reading
        that does not either forbid the mode outright or pin it to a Principal
        it never established.

        Derived rather than stored, from the same `domain.identity.binding`
        namespace `bootstrap.gateway.local_principal` derives the process
        principal from — so the two cannot disagree about who the local operator
        is. `tests/unit/test_remote_ingress_settings.py` asserts the equality
        rather than leaving it to this sentence.
        """
        if self.auth_mode is not AuthMode.LOCAL_OPERATOR:
            return None
        return capture_principal_id(LOCAL_OPERATOR_UUID)

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
