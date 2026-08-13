"""The kill switch, its default, and the Principal a minted client binds to.

WP-10. Two settings claims that decide security outcomes, and they are asserted
here rather than inferred from the composition:

* **off by default and fail closed when unconfigured** — an unset variable, a
  misspelled one, and an unloaded `.env` must all produce a process that serves
  no remote ingress;
* **`admissible_client_principal_id` agrees with the process principal** — the
  two are derived from the same namespace, and a drift between them would mean a
  client minted for the local operator could not authenticate as it, or worse,
  that one of the two silently named somebody else.

No database, no socket, no process. Every value is synthetic.
"""

from __future__ import annotations

from typing import Final

import pytest

from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.settings import ENV_PREFIX, AuthMode, Settings, SettingsError, load_settings

#: A synthetic DSN. It names a host that does not resolve and carries no
#: credential, and nothing in this module opens a connection.
DSN: Final = "postgresql+psycopg://my_pa@localhost:5433/my_pa_settings_probe"


def _environment(**overrides: str) -> dict[str, str]:
    return {f"{ENV_PREFIX}DATABASE_URL": DSN, **overrides}


def test_the_remote_ingress_is_off_when_nothing_says_otherwise() -> None:
    """The unconfigured default, which is the state of every process by default."""
    assert load_settings(_environment()).remote_ingress_enabled is False
    assert Settings(database_url=DSN).remote_ingress_enabled is False
    assert load_settings(_environment()).apple_ingress_enabled is False
    assert Settings(database_url=DSN).apple_ingress_enabled is False


def test_a_misspelled_switch_refuses_to_start_rather_than_leaving_it_off() -> None:
    """Fail closed *loudly*, which is stronger than failing closed quietly.

    An unknown `MY_PA_` variable is a startup error, so `MY_PA_REMOTE_INGRESS=1`
    does not silently leave the ingress off while an operator believes it is on.
    The direction that would have been dangerous is the reverse — a typo that
    turned it *on* — and the settings loader admits no such spelling at all.
    """
    with pytest.raises(SettingsError, match="unknown"):
        load_settings(_environment(**{f"{ENV_PREFIX}REMOTE_INGRESS": "1"}))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("1", True), ("on", True), ("false", False), ("0", False), ("off", False)],
    ids=lambda value: str(value),
)
def test_the_switch_reads_the_booleans_the_loader_declares(raw: str, expected: bool) -> None:
    settings = load_settings(_environment(**{f"{ENV_PREFIX}REMOTE_INGRESS_ENABLED": raw}))
    assert settings.remote_ingress_enabled is expected


def test_an_unreadable_switch_value_refuses_rather_than_defaulting() -> None:
    """ "Yes-ish" is not a value. There is no coercion and no fallback to off.

    Falling back to off would be the safe direction and is still wrong: an
    operator who wrote something the loader could not read would be told nothing
    and would believe the ingress was serving.
    """
    with pytest.raises(SettingsError, match="REMOTE_INGRESS_ENABLED"):
        load_settings(_environment(**{f"{ENV_PREFIX}REMOTE_INGRESS_ENABLED": "maybe"}))


def test_a_local_operator_process_binds_clients_to_its_own_principal() -> None:
    """The pin, and it is the same identifier the process itself acts as.

    Derived twice from `domain.identity.binding` — once by `local_principal` for
    the process, once by the settings for the client plane — and asserted equal
    here so the two cannot drift. A drift either way is a security outcome: too
    narrow and a minted client can never authenticate; too wide and the pin does
    not pin.
    """
    settings = load_settings(_environment())
    assert settings.auth_mode is AuthMode.LOCAL_OPERATOR
    assert settings.admissible_client_principal_id() == local_principal().principal_id


def test_an_entra_process_names_no_single_admissible_principal() -> None:
    """`None` is "the caller this process authenticated", not "any principal".

    Two real Principals in that mode are two real datasets, so there is no one
    identifier for the binding rule to compare against — and the operator command
    refuses to mint there for exactly that reason.
    """
    settings = load_settings(
        _environment(
            **{
                f"{ENV_PREFIX}AUTH_MODE": AuthMode.ENTRA.value,
                f"{ENV_PREFIX}ENTRA_TENANT_ID": "synthetic-tenant",
                f"{ENV_PREFIX}ENTRA_CLIENT_ID": "synthetic-client",
                f"{ENV_PREFIX}ENTRA_ISSUER": "https://example.invalid/synthetic/v2.0",
                f"{ENV_PREFIX}ENTRA_JWKS_URI": "https://example.invalid/synthetic/keys",
            }
        )
    )
    assert settings.admissible_client_principal_id() is None


def test_the_switch_never_reaches_a_rendered_settings_object() -> None:
    """Not a secret, and not hidden — asserted so the claim is not overstated.

    `remote_ingress_enabled` is deliberately *not* `repr=False`: it is a boolean
    about a build, not a value about a deployment, and hiding it would make an
    operator's diagnostic worse for no gain. What must not appear is the DSN,
    which is unchanged, and this is where a new field could quietly have
    reopened that.
    """
    rendered = repr(load_settings(_environment()))
    assert "remote_ingress_enabled" in rendered
    assert "my_pa_settings_probe" not in rendered
