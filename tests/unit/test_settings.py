"""Settings load safely and fail closed."""

from __future__ import annotations

import pytest

from my_pa.bootstrap.settings import (
    DATABASE_URL_SCHEME,
    ENV_PREFIX,
    MAX_FETCH_BYTES_CEILING,
    Environment,
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


def test_only_the_database_url_may_be_credential_bearing() -> None:
    """One setting can carry a credential; a second one arriving is a decision.

    `database_url` is exempt because a PostgreSQL URL is where a password
    belongs when the environment supplies one. Every other field must stay
    plainly non-secret, so a `MY_PA_API_TOKEN` cannot appear as an ordinary
    setting and inherit this module's handling by accident.
    """
    tokens = ("password", "secret", "token", "key", "credential", "dsn", "url", "path")
    for name in Settings.model_fields:
        if name == "database_url":
            continue
        for token in tokens:
            assert token not in name, f"settings field {name!r} looks secret-bearing"


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


def test_settings_parses_the_database_url_exactly_once() -> None:
    """One parse, kept — not one parser, re-run.

    Object identity is the assertion because it is the only one that
    distinguishes a stored parse from a fresh parse that happens to agree.
    """
    settings = load_settings({DATABASE_URL: _A_URL})
    assert settings.parsed_database_url() is settings.parsed_database_url()


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
