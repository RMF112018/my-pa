"""Settings load safely and fail closed."""

from __future__ import annotations

import traceback
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import URL

from my_pa.bootstrap.settings import (
    DATABASE_URL_SCHEME,
    ENV_PREFIX,
    MAX_FETCH_BYTES_CEILING,
    Environment,
    GatewayBindMode,
    LogLevel,
    Settings,
    SettingsError,
    load_settings,
)
from my_pa.domain.extraction.text import MAX_EXTRACTED_CHARACTERS

DATABASE_URL = f"{ENV_PREFIX}DATABASE_URL"

#: A syntactically valid URL for tests that are not about the URL itself.
#: Deliberately unreachable: no test should connect by accident, and a host that
#: cannot resolve makes that structural rather than a convention.
_A_URL = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere"


def test_defaults_are_safe() -> None:
    settings = load_settings({DATABASE_URL: _A_URL})
    assert settings.environment is Environment.LOCAL
    assert settings.log_level is LogLevel.INFO
    assert settings.redaction_enabled is True
    assert settings.contract_strict_mode is True
    assert settings.gateway_bind_mode is GatewayBindMode.LOOPBACK
    assert settings.gateway_bind_host() == "127.0.0.1"


def test_container_gateway_bind_is_explicit_and_closed() -> None:
    settings = load_settings({DATABASE_URL: _A_URL, f"{ENV_PREFIX}GATEWAY_BIND_MODE": "container"})
    assert settings.gateway_bind_host() == "0.0.0.0"  # noqa: S104
    with pytest.raises(SettingsError, match="GATEWAY_BIND_MODE"):
        load_settings({DATABASE_URL: _A_URL, f"{ENV_PREFIX}GATEWAY_BIND_MODE": "lan"})


def test_remote_oauth_is_one_exact_non_entra_public_origin() -> None:
    values = {
        DATABASE_URL: _A_URL,
        f"{ENV_PREFIX}REMOTE_MCP_ENABLED": "true",
        f"{ENV_PREFIX}REMOTE_MCP_PUBLIC_HOST": "mcp.example.invalid",
        f"{ENV_PREFIX}OAUTH_AUTHORIZATION_SERVER": "https://mcp.example.invalid",
        f"{ENV_PREFIX}OAUTH_AUDIENCE": "https://mcp.example.invalid/mcp",
        f"{ENV_PREFIX}OAUTH_SCOPES": "my-pa.read",
        f"{ENV_PREFIX}OAUTH_OPERATOR_SECRET": "s" * 43,
    }
    assert load_settings(values).auth_mode.value == "local_operator"
    for name, invalid in (
        ("OAUTH_AUTHORIZATION_SERVER", "http://mcp.example.invalid"),
        ("OAUTH_AUDIENCE", "https://other.example.invalid/mcp"),
        ("REMOTE_MCP_PUBLIC_HOST", "other.example.invalid"),
    ):
        with pytest.raises(SettingsError, match="exact HTTPS public origin"):
            load_settings({**values, f"{ENV_PREFIX}{name}": invalid})


def test_checked_in_remote_environment_cannot_start_unchanged() -> None:
    example = (
        Path(__file__).resolve().parents[2] / "ops/nas/remote/remote.env.example"
    ).read_text()
    environment = dict(
        line.split("=", 1) for line in example.splitlines() if line and not line.startswith("#")
    )
    with pytest.raises(SettingsError, match="generated operator secret"):
        load_settings(environment)


def test_unrelated_environment_variables_are_ignored() -> None:
    environment = {"PATH": "/usr/bin", "HOME": "/root", DATABASE_URL: _A_URL}
    assert load_settings(environment) == Settings(database_url=_A_URL)


def test_known_values_are_parsed() -> None:
    settings = load_settings(
        {
            f"{ENV_PREFIX}ENVIRONMENT": "test",
            f"{ENV_PREFIX}LOG_LEVEL": "debug",
            f"{ENV_PREFIX}MAX_PAGE_SIZE": "10",
            f"{ENV_PREFIX}DEFAULT_PAGE_SIZE": "5",
            DATABASE_URL: _A_URL,
        }
    )
    assert settings.environment is Environment.TEST
    assert settings.log_level is LogLevel.DEBUG
    assert settings.max_page_size == 10
    assert settings.default_page_size == 5


def test_the_phase_01_limits_are_the_configuration_defaults() -> None:
    """`D-24`: the values that were a module constant are now the defaults."""
    limits = load_settings({DATABASE_URL: _A_URL}).effective_limits()
    assert limits.max_page_size == 200
    assert limits.default_page_size == 50
    assert limits.max_fetch_bytes == 8 * 1024 * 1024
    assert limits.max_enrollment_depth == 0


def test_every_limit_is_configurable() -> None:
    limits = load_settings(
        {
            f"{ENV_PREFIX}MAX_PAGE_SIZE": "40",
            f"{ENV_PREFIX}DEFAULT_PAGE_SIZE": "7",
            f"{ENV_PREFIX}MAX_FETCH_BYTES": "4096",
            f"{ENV_PREFIX}MAX_ENROLLMENT_DEPTH": "3",
            DATABASE_URL: _A_URL,
        }
    ).effective_limits()
    assert (
        limits.max_page_size,
        limits.default_page_size,
        limits.max_fetch_bytes,
        limits.max_enrollment_depth,
    ) == (40, 7, 4096, 3)


def test_a_contradictory_pair_of_page_limits_fails_at_startup() -> None:
    """Fail closed rather than clamping: a limit nobody meant is not a default."""
    with pytest.raises(SettingsError, match="default_page_size cannot exceed max_page_size"):
        load_settings(
            {
                f"{ENV_PREFIX}MAX_PAGE_SIZE": "10",
                f"{ENV_PREFIX}DEFAULT_PAGE_SIZE": "50",
                DATABASE_URL: _A_URL,
            }
        )


def test_the_fetch_ceiling_is_derived_from_what_the_extractor_can_read() -> None:
    """`D-35` accepts a provider read inside a transaction because it is bounded.

    So the bound has to be one a transaction can survive, and it has to have a
    reason: four bytes per extractable character is the point past which no byte
    can belong to a document this build could extract.
    """
    assert MAX_FETCH_BYTES_CEILING == MAX_EXTRACTED_CHARACTERS * 4 == 16 * 1024 * 1024
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings(
            {
                f"{ENV_PREFIX}MAX_FETCH_BYTES": str(MAX_FETCH_BYTES_CEILING + 1),
                DATABASE_URL: _A_URL,
            }
        )
    at_ceiling = load_settings(
        {f"{ENV_PREFIX}MAX_FETCH_BYTES": str(MAX_FETCH_BYTES_CEILING), DATABASE_URL: _A_URL}
    )
    assert at_ceiling.effective_limits().max_fetch_bytes == MAX_FETCH_BYTES_CEILING


def test_an_enrollment_depth_beyond_the_domain_ceiling_is_refused() -> None:
    """Configuration may lower a domain bound and may not raise one."""
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings({f"{ENV_PREFIX}MAX_ENROLLMENT_DEPTH": "99", DATABASE_URL: _A_URL})


def test_unknown_prefixed_variable_fails_closed() -> None:
    # A typo must not look accepted while the real setting keeps its default.
    with pytest.raises(SettingsError, match="unknown MY_PA_ settings"):
        load_settings({f"{ENV_PREFIX}REDACTION_ENABLE": "false"})


def test_redaction_cannot_be_disabled() -> None:
    with pytest.raises(SettingsError, match="redaction cannot be disabled"):
        load_settings({f"{ENV_PREFIX}REDACTION_ENABLED": "false", DATABASE_URL: _A_URL})


def test_strict_contract_parsing_cannot_be_disabled() -> None:
    with pytest.raises(SettingsError, match="strict contract parsing"):
        load_settings({f"{ENV_PREFIX}CONTRACT_STRICT_MODE": "0", DATABASE_URL: _A_URL})


def test_debug_log_level_does_not_disable_redaction() -> None:
    assert (
        load_settings({f"{ENV_PREFIX}LOG_LEVEL": "debug", DATABASE_URL: _A_URL}).redaction_enabled
        is True
    )


@pytest.mark.parametrize("raw", ["maybe", "", "2", "yes please"])
def test_unparseable_boolean_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="must be a boolean"):
        load_settings({f"{ENV_PREFIX}REDACTION_ENABLED": raw})


@pytest.mark.parametrize("raw", ["ten", "", "1.5"])
def test_unparseable_integer_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="must be an integer"):
        load_settings({f"{ENV_PREFIX}MAX_PAGE_SIZE": raw})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (f"{ENV_PREFIX}REDACTION_ENABLED", "SUPERSECRETVALUE"),
        (f"{ENV_PREFIX}CONTRACT_STRICT_MODE", "SUPERSECRETVALUE"),
        (f"{ENV_PREFIX}MAX_PAGE_SIZE", "SUPERSECRETVALUE"),
        (f"{ENV_PREFIX}MAX_PAGE_SIZE", "99999"),
        (f"{ENV_PREFIX}ENVIRONMENT", "SUPERSECRETVALUE"),
    ],
)
def test_error_messages_never_echo_the_supplied_value(key: str, value: str) -> None:
    """Settings are non-secret today; echoing input would make this a leak later.

    Both the coercion path and the validation path must stay quiet about values,
    so re-introducing an echo in either fails here.
    """
    with pytest.raises(SettingsError) as caught:
        load_settings({key: value})
    assert value not in str(caught.value)
    assert key in str(caught.value)


@pytest.mark.parametrize("raw", ["0", "-1", "1001"])
def test_out_of_range_page_size_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings({f"{ENV_PREFIX}MAX_PAGE_SIZE": raw})


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(SettingsError, match="invalid configuration"):
        load_settings({f"{ENV_PREFIX}ENVIRONMENT": "production"})


def test_only_explicitly_admitted_settings_may_be_credential_bearing() -> None:
    """One setting can carry a credential; a second one arriving is a decision.

    `database_url` is exempt because a PostgreSQL URL is where a password
    belongs when the environment supplies one. The origin OAuth operator secrets
    are the deliberately admitted approval credentials (production remote MCP
    and isolated GSQS remote-eval); those fields are hidden from repr. Every
    other field must stay plainly non-secret.
    """
    tokens = ("password", "secret", "token", "key", "credential", "dsn", "url", "path")
    admitted = {"database_url", "oauth_operator_secret", "gsqs_remote_eval_oauth_operator_secret"}
    for name in Settings.model_fields:
        if name in admitted:
            continue
        for token in tokens:
            assert token not in name, f"settings field {name!r} looks secret-bearing"
    assert Settings.model_fields["oauth_operator_secret"].repr is False
    assert Settings.model_fields["gsqs_remote_eval_oauth_operator_secret"].repr is False


def test_an_absent_database_url_is_refused_rather_than_defaulted() -> None:
    """The whole point of `P00-OD-008`: absence must not pick a target.

    A default here aimed every unconfigured process at the canonical `my_pa`
    database, including `apps/cli/migration.py`, which can run destructive
    migration operations. Failing closed is what that decision asked for.
    """
    with pytest.raises(SettingsError) as caught:
        load_settings({})
    assert f"{ENV_PREFIX}DATABASE_URL has no default" in str(caught.value)


def test_no_module_constant_supplies_a_database_url() -> None:
    """No default may creep back in under another name.

    Asserting the absence of a value rather than the behaviour of one, because
    a reintroduced constant would be wired up before anyone noticed the
    behaviour changed.
    """
    import my_pa.bootstrap.settings as settings_module

    offenders = [
        name
        for name in dir(settings_module)
        if name.isupper()
        and isinstance(getattr(settings_module, name), str)
        and "://" in getattr(settings_module, name)
    ]
    assert not offenders, f"a database URL constant is back: {offenders}"
    assert Settings.model_fields["database_url"].is_required()


def test_a_supplied_database_url_is_used() -> None:
    supplied = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/other"
    assert load_settings({DATABASE_URL: supplied}).database_url == supplied


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not a url",
        "postgresql://my_pa@localhost:5433/my_pa",  # unpinned driver
        "postgresql+psycopg2://my_pa@localhost:5433/my_pa",  # wrong driver
        "postgresql+asyncpg://my_pa@localhost:5433/my_pa",  # wrong driver
        "sqlite:///my_pa.sqlite",  # not the canonical store
    ],
)
def test_a_database_url_with_the_wrong_scheme_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="must use the postgresql\\+psycopg scheme"):
        load_settings({DATABASE_URL: raw})


def test_a_database_url_without_a_host_is_rejected() -> None:
    with pytest.raises(SettingsError, match="must name a host"):
        load_settings({DATABASE_URL: f"{DATABASE_URL_SCHEME}:///my_pa"})


@pytest.mark.parametrize("raw", ["://localhost:5433", "://localhost:5433/"])
def test_a_database_url_without_a_database_is_rejected(raw: str) -> None:
    with pytest.raises(SettingsError, match="must name a database"):
        load_settings({DATABASE_URL: DATABASE_URL_SCHEME + raw})


def test_an_invalid_database_url_error_never_echoes_the_url() -> None:
    """A rejected URL is the one setting value most likely to hold a password."""
    url = "postgresql+psycopg2://my_pa:SUPERSECRETVALUE@localhost:5433/my_pa"
    with pytest.raises(SettingsError) as caught:
        load_settings({DATABASE_URL: url})
    assert "SUPERSECRETVALUE" not in str(caught.value)
    assert url not in str(caught.value)


def test_a_rejected_database_url_is_absent_from_the_whole_exception_chain() -> None:
    """The message was quiet; the chain behind it was not.

    Every other disclosure test here reads `str(exc)`, and reading only the
    top-level message is exactly what let this survive. `load_settings` used to
    raise `SettingsError(…) from exc`, and `exc` is Pydantic's `ValidationError`,
    which renders `input_value=` — for a model validator, the whole settings
    mapping. So the DSN was one `logging.exception` or one unhandled traceback
    away, on `__cause__`, while `str` stayed clean.

    A *short* URL is what makes this visible, and the first assertion below is
    what keeps that true. Pydantic elides the middle of a long input and keeps the
    head and the tail, so a long DSN renders with the password cut out — which is
    how this channel passed for closed. Length is therefore load-bearing, and a
    later pydantic that elides more aggressively would quietly turn every
    assertion here green against unfixed code. So the leak is proved renderable
    for this exact input before it is asserted absent.

    `raise … from None` is not sufficient either, though not for the reason it is
    usually given: it sets `__suppress_context__`, so `traceback.format_exception`
    and `logging.exception` do *not* print the context. It leaves the
    `ValidationError` reachable on `__context__`, where anything that walks the
    chain itself — a structured-log serializer, an error reporter, a debugger, the
    explicit walk below — still reads the DSN out of it. Only leaving the handler
    before raising empties both links, so this fails if the `raise` moves back
    inside the `except` under either spelling.

    The URL is built into a local rather than written inline in the call below,
    because a rendered traceback prints the *source line* of each frame: an
    inline literal would appear in the chain by way of this test's own text and
    make the assertions unfalsifiable.
    """
    synthetic_credential = "NOTAREALPW"
    url = f"mysql://u:{synthetic_credential}@h/d"

    # Non-vacuity, asserted rather than assumed: pydantic must render this input
    # whole. `Settings(...)` raises the same `ValidationError` `load_settings`
    # used to attach, so this is the exact text the chain would have carried.
    with pytest.raises(ValidationError) as raw:
        Settings(database_url=url)
    assert synthetic_credential in str(raw.value), (
        "pydantic elided the password out of this input, so the assertions below "
        "would hold against the unfixed code too — shorten the URL"
    )

    with pytest.raises(SettingsError) as caught:
        load_settings({DATABASE_URL: url})
    error = caught.value

    # The chain is severed at both links, not just the one `from None` clears.
    assert error.__cause__ is None, "the ValidationError is still on __cause__"
    assert error.__context__ is None, "the ValidationError is still on __context__"

    # Walk the links explicitly as well as rendering, so a future chain that is
    # non-empty but happens to render harmlessly is still caught.
    walked: list[str] = [str(error)]
    seen: set[int] = {id(error)}
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        for link in (current.__cause__, current.__context__):
            if link is not None and id(link) not in seen:
                seen.add(id(link))
                walked.append(str(link))
                pending.append(link)

    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))

    for text, where in ((rendered, "the rendered traceback"), ("\n".join(walked), "the chain")):
        assert synthetic_credential not in text, f"the password reached {where}"
        assert url not in text, f"the URL reached {where}"

    # Bought with severance, not with silence: the top-level message must still
    # say which setting was rejected and why, or this test would pass against a
    # `SettingsError("")`.
    assert DATABASE_URL in str(error)
    assert DATABASE_URL_SCHEME in str(error)


def test_severing_the_chain_keeps_every_field_named_with_its_reason() -> None:
    """Diagnostics survive the fix, including for settings that are not the URL.

    The chain was severed to keep a password out of a traceback. If that had cost
    the other fields their diagnosis, the trade would be a bad one and this is
    where it would show: two unrelated bad values plus the credential-bearing one,
    and all three still named in the single top-level message.
    """
    with pytest.raises(SettingsError) as caught:
        load_settings(
            {
                DATABASE_URL: f"{DATABASE_URL_SCHEME}://someone@db.invalid/somewhere",
                f"{ENV_PREFIX}MAX_PAGE_SIZE": "0",
                f"{ENV_PREFIX}MAX_ENROLLMENT_DEPTH": "-1",
            }
        )
    message = str(caught.value)

    assert f"{ENV_PREFIX}MAX_PAGE_SIZE" in message
    assert f"{ENV_PREFIX}MAX_ENROLLMENT_DEPTH" in message
    assert "greater than 0" in message
    assert "greater than or equal to 0" in message


def test_an_accepted_database_url_is_absent_from_the_settings_repr() -> None:
    """The rejected URL was guarded. The accepted one is the one that has a password.

    Every test above is about a URL that failed validation, and each asserts the
    error message stays quiet. Nothing asserted anything about the URL that
    *succeeded*, and Pydantic's generated `repr` printed it — so a `Settings`
    built from a real environment carried a live DSN into anything that rendered
    it. `str` is the same rendering, which is why both are asserted here.

    The channel that makes this more than theoretical is this suite. Pytest's
    assertion rewriting prints the `repr` of the operands of a failing
    comparison, so any unrelated failing assertion holding a `Settings` object
    would publish the credential in CI output.

    `SUPERSECRETVALUE` is an obviously synthetic password and `db.invalid` is a
    reserved name that cannot resolve, so nothing here can connect anywhere.
    Removing `repr=False` from the field fails this test.
    """
    synthetic_credential = "SUPERSECRETVALUE"
    url = f"{DATABASE_URL_SCHEME}://someone:{synthetic_credential}@db.invalid:5432/somewhere"
    settings = load_settings({DATABASE_URL: url})

    assert settings.database_url == url, "the value is kept; only its rendering is suppressed"
    for rendering, name in ((repr(settings), "repr"), (str(settings), "str")):
        assert synthetic_credential not in rendering, f"the password reached {name}(Settings)"
        assert url not in rendering, f"the URL reached {name}(Settings)"
        # The other fields must still render, or this bought secrecy with
        # silence: a `repr` that showed nothing would pass the two assertions
        # above and destroy every unrelated diagnostic that uses one.
        assert "max_page_size=200" in rendering
        assert "redaction_enabled=True" in rendering


# The URL a process connects to is decided once
# ---------------------------------------------
#
# `create_engine` reads a URL string with SQLAlchemy's own parser. If settings
# validated the same string with a different parser, the scheme, host and
# database that were approved would be one reading of the text and the ones
# connected to would be another, and nothing would hold the two together — two
# parsers that agree on ordinary input have still each answered separately.
#
# These are invariants rather than examples, and deliberately so: they assert
# that there is exactly one answer and that it is the one used, which does not
# depend on knowing an input for which two answers would differ. The other half
# — that the composition root hands that answer to the engine rather than
# handing over the text — is asserted in `test_gateway_composition.py`, where
# the engines are.


def test_settings_parses_the_database_url_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """One parse, kept — not one parser, re-run.

    Two assertions, because the name needs both and for a while it only had the
    second. Object identity across accessor calls says the accessor is stable,
    which is necessary but is not what "exactly once" claims: an implementation
    that parsed twice during validation and stored the second parse would satisfy
    it, and the name would still read as a guarantee nobody was checking. So the
    parser is counted directly. `make_url` is the only reading of the string that
    happens anywhere — `_parse_database_url` calls it and `create_engine` returns
    a `URL` untouched — so one call to it over a whole `load_settings`, accessor
    included, is the claim stated as a number rather than as a name.
    """
    import my_pa.bootstrap.settings as settings_module

    real_make_url = settings_module.make_url
    readings: list[str] = []

    def counting_make_url(value: str) -> URL:
        readings.append(value)
        return real_make_url(value)

    monkeypatch.setattr(settings_module, "make_url", counting_make_url)

    settings = load_settings({DATABASE_URL: _A_URL})
    assert readings == [_A_URL], f"the URL was read {len(readings)} times, not once"

    assert settings.parsed_database_url() is settings.parsed_database_url()
    assert readings == [_A_URL], "the accessor re-read the string instead of returning the parse"


def test_a_url_the_engine_cannot_parse_is_refused_without_naming_it() -> None:
    """Well-formedness is decided by the parser that has to use the URL.

    A port that is not a number is the plain case: whatever the engine's parser
    refuses is refused at startup, and it is refused in this repository's own
    error type with a message that names the defect. Letting the parser's own
    exception out would put a fragment of the URL in the traceback of a value
    that can carry a password.
    """
    url = f"{DATABASE_URL_SCHEME}://someone:SUPERSECRETVALUE@db.invalid:not-a-port/somewhere"
    with pytest.raises(SettingsError) as caught:
        load_settings({DATABASE_URL: url})
    assert "SUPERSECRETVALUE" not in str(caught.value)
    assert "not-a-port" not in str(caught.value)
    assert url not in str(caught.value)


# ---- the entity plane's two switches ---------------------------------------


def test_the_entity_plane_and_its_write_half_are_both_off_by_default() -> None:
    """Two switches, and neither is inferred from the other.

    Stated as a default rather than as a rule, because the default is what a
    process that was never configured gets: no entity plane, and no writes over
    identity, without an operator having decided anything.
    """
    settings = load_settings({DATABASE_URL: _A_URL})
    assert settings.relationship_intelligence_enabled is False
    assert settings.relationship_intelligence_writes_enabled is False


def test_the_write_switch_without_the_plane_refuses_to_start() -> None:
    """Fail closed, and closed in the direction that says what was meant.

    The two alternatives were serving the writes anyway — eighteen identity
    writes on a process whose operator turned the plane off — or ignoring the
    variable, which is the shape where an operator sets a switch, sees no error,
    and believes a surface is gated when it is not. The message names both
    settings and neither of their values.
    """
    with pytest.raises(SettingsError) as refused:
        load_settings(
            {
                DATABASE_URL: _A_URL,
                f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED": "true",
            }
        )
    message = str(refused.value)
    assert f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED" in message
    assert f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_ENABLED" in message


def test_the_plane_without_the_write_switch_starts_and_stays_read_only() -> None:
    """The composition an operator most likely wants, and the control for the two above."""
    settings = load_settings(
        {
            DATABASE_URL: _A_URL,
            f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_ENABLED": "true",
        }
    )
    assert settings.relationship_intelligence_enabled is True
    assert settings.relationship_intelligence_writes_enabled is False


def test_both_switches_together_are_admitted() -> None:
    """Non-vacuity: the refusal above is about one combination, not about the flag."""
    settings = load_settings(
        {
            DATABASE_URL: _A_URL,
            f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_ENABLED": "true",
            f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED": "true",
        }
    )
    assert settings.relationship_intelligence_enabled is True
    assert settings.relationship_intelligence_writes_enabled is True


def test_identity_correction_defaults_off_like_every_gate_below_it() -> None:
    """`MY_PA_RELATIONSHIP_IDENTITY_CORRECTION_ENABLED`, unset (operator section 18).

    Default `False`, on the same argument the two switches above it default
    `False`: the remote MCP profile and the manifest are both derived from the
    capability set with no per-capability exclusion list, so "available" and
    "reachable" are one decision, and this is where it is made. A governed merge
    is the most consequential act this product can perform on identity; a build
    that served it because nobody said not to would be serving it by accident.
    """
    settings = load_settings({DATABASE_URL: _A_URL})
    assert settings.relationship_identity_correction_enabled is False


def test_identity_correction_without_the_write_switch_refuses_to_start() -> None:
    """The second half of section 18's ordering, and it is checked against *writes*.

    Checking the plane switch alone would admit a process serving governed merges
    while refusing every ordinary entity write -- a build where an operator may
    collapse two identities and may not correct a misspelled name. The write
    switch already requires the plane switch, so this one rule makes the whole
    chain transitive: identity correction is unavailable unless every lower gate
    is enabled.
    """
    with pytest.raises(SettingsError) as refused:
        load_settings(
            {
                DATABASE_URL: _A_URL,
                f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_ENABLED": "true",
                f"{ENV_PREFIX}RELATIONSHIP_IDENTITY_CORRECTION_ENABLED": "true",
            }
        )
    message = str(refused.value)
    assert f"{ENV_PREFIX}RELATIONSHIP_IDENTITY_CORRECTION_ENABLED" in message
    assert f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED" in message


def test_identity_correction_without_the_plane_at_all_refuses_to_start() -> None:
    """The transitive case, asserted rather than inferred from the two rules.

    An operator who sets only this switch has set the highest gate and none of
    the ones below it. Which of the two refusals fires is not the claim -- that
    the process does not start is.
    """
    with pytest.raises(SettingsError):
        load_settings(
            {
                DATABASE_URL: _A_URL,
                f"{ENV_PREFIX}RELATIONSHIP_IDENTITY_CORRECTION_ENABLED": "true",
            }
        )


def test_all_three_switches_together_are_admitted() -> None:
    """Non-vacuity: the refusals above are about combinations, not about the flag."""
    settings = load_settings(
        {
            DATABASE_URL: _A_URL,
            f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_ENABLED": "true",
            f"{ENV_PREFIX}RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED": "true",
            f"{ENV_PREFIX}RELATIONSHIP_IDENTITY_CORRECTION_ENABLED": "true",
        }
    )
    assert settings.relationship_identity_correction_enabled is True
