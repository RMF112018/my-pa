"""PC-CM-RUN01-WP05: the settings-configure receipt and the timezone validator.

The `fast` tier, no database. Every invariant `ConstraintProjectSettingsHistoryEntry`
enforces restates a landed CHECK of `knowledge.constraint_project_settings_history`
(revision `e6a4c2f91b73`), and that duplication is the point of this module: the
outcome/version pairing is what makes a stored receipt replayable, and a rule
provable only against PostgreSQL is a rule the configure service cannot be held
to here.

`validate_project_timezone_name` is tested for what it *refuses to repair* as
much as for what it refuses outright. A validator that trimmed, case-folded or
fell back would store a timezone the caller never named, silently moving every
Due Soon and Overdue boundary on the Project.

Every identifier, key, digest and label here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Final

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.project_controls.business_time import (
    ProjectTimezoneError,
    project_today,
    validate_project_timezone_name,
)
from my_pa.domain.project_controls.history import (
    CONSTRAINT_PROJECT_SETTINGS_ACTION,
    MAX_SETTINGS_FAILURE_DETAIL_CHARACTERS,
    ConstraintMutationActor,
    ConstraintProjectSettingsHistoryEntry,
    ConstraintProjectSettingsHistoryError,
    ConstraintProjectSettingsHistoryKeyConflictError,
    ConstraintProjectSettingsOutcome,
    issue_settings_history_id,
)
from my_pa.domain.project_controls.settings import MAX_PROJECT_TIMEZONE_NAME_CHARACTERS

PRINCIPAL: Final = "prn_wp05aaaa0001aaaa0001"
PROJECT: Final = "prj_wp05aaaa0001aaaa"
CORRELATION: Final = "corr_wp05aaaa0001aaaa"
KEY: Final = "wp05-settings-key-0001"
DIGEST: Final = "a" * 64
ZONE: Final = "America/Chicago"

T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)


def _entry(**overrides: object) -> ConstraintProjectSettingsHistoryEntry:
    """An applied first-configure receipt, with `overrides` applied.

    Applied-with-no-prior-row is the shape every other case is a deviation
    from: no settings version before, version 1 after, and the snapshot the
    replay will be answered from.
    """
    fields: dict[str, object] = {
        "history_id": issue_settings_history_id(),
        "principal_id": PRINCIPAL,
        "project_id": PROJECT,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "outcome": ConstraintProjectSettingsOutcome.APPLIED,
        "idempotency_key": KEY,
        "request_digest": DIGEST,
        "occurred_at": T0,
        "recorded_at": T0,
        "before_settings_version": None,
        "after_settings_version": 1,
        "resulting_timezone_name": ZONE,
        "resulting_settings_updated_at": T0,
    }
    fields.update(overrides)
    return ConstraintProjectSettingsHistoryEntry(**fields)


def _code(raised: pytest.ExceptionInfo[ConstraintProjectSettingsHistoryError]) -> str:
    return raised.value.code


# --- The receipt's identity and shape -------------------------------------


def test_a_first_configure_receipt_records_version_one_over_no_prior_row() -> None:
    entry = _entry()

    assert entry.action == CONSTRAINT_PROJECT_SETTINGS_ACTION == "configure"
    assert entry.before_settings_version is None
    assert entry.after_settings_version == 1
    assert entry.resulting_timezone_name == ZONE
    assert entry.failure_code is None


def test_a_receipt_identifier_is_an_opaque_cpsh_value() -> None:
    issued = issue_settings_history_id()

    assert issued.startswith("cpsh_")
    assert issued != issue_settings_history_id()
    assert _entry(history_id=issued).history_id == issued


@pytest.mark.parametrize(
    "history_id",
    ["", "cpsh_", "cpsh_short", "chst_wp05aaaa0001aaaa", "cpsh_has-a-dash-0001"],
)
def test_a_malformed_receipt_identifier_is_refused(history_id: str) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(history_id=history_id)

    assert _code(raised) == "constraint_settings_history_id_malformed"


@pytest.mark.parametrize("field", ["principal_id", "project_id", "correlation_id"])
def test_a_receipt_refuses_an_identifier_of_the_wrong_kind(field: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        _entry(**{field: "src_wp05aaaa0001aaaa"})


def test_a_receipt_records_only_the_configure_action() -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(action="reconfigure")

    assert _code(raised) == "constraint_settings_history_action_unknown"


def test_a_receipt_names_one_known_actor_and_one_known_outcome() -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as actor:
        _entry(actor="principal")
    with pytest.raises(ConstraintProjectSettingsHistoryError) as outcome:
        _entry(outcome="applied")

    assert _code(actor) == "constraint_settings_history_actor_unknown"
    assert _code(outcome) == "constraint_settings_history_outcome_unknown"


@pytest.mark.parametrize("actor", list(ConstraintMutationActor))
def test_every_actor_the_stored_check_admits_is_constructible(
    actor: ConstraintMutationActor,
) -> None:
    assert _entry(actor=actor).actor is actor


@pytest.mark.parametrize("key", ["", "short", "k" * 129, "has a space", "has/a/slash"])
def test_a_malformed_idempotency_key_is_refused(key: str) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(idempotency_key=key)

    assert _code(raised) == "constraint_settings_history_idempotency_key_malformed"


@pytest.mark.parametrize("digest", ["", "A" * 64, "a" * 63, "a" * 65, "z" * 64])
def test_a_malformed_request_digest_is_refused(digest: str) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(request_digest=digest)

    assert _code(raised) == "constraint_settings_history_request_digest_malformed"


@pytest.mark.parametrize(
    ("context", "code"),
    [
        ("   ", "constraint_settings_history_client_context_blank"),
        ("c" * 129, "constraint_settings_history_client_context_too_long"),
    ],
)
def test_client_context_is_bounded_and_non_blank(context: str, code: str) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(client_context=context)

    assert _code(raised) == code


def test_a_receipt_carries_its_correlation_and_context_when_given() -> None:
    entry = _entry(client_context="browser", correlation_id=CORRELATION)

    assert entry.client_context == "browser"
    assert entry.correlation_id == CORRELATION


# --- Outcome/version pairing ----------------------------------------------


def test_an_applied_reconfigure_advances_the_version_by_exactly_one() -> None:
    entry = _entry(before_settings_version=3, after_settings_version=4)

    assert (entry.before_settings_version, entry.after_settings_version) == (3, 4)


@pytest.mark.parametrize(
    ("before", "after"),
    [(None, None), (None, 2), (1, 1), (1, 3), (3, 2), (2, None)],
)
def test_an_applied_receipt_that_does_not_advance_by_one_is_refused(
    before: int | None, after: int | None
) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(before_settings_version=before, after_settings_version=after)

    assert _code(raised) == "constraint_settings_history_applied_without_advance"


def test_a_no_op_preserves_the_version_it_read() -> None:
    entry = _entry(
        outcome=ConstraintProjectSettingsOutcome.NO_OP,
        before_settings_version=2,
        after_settings_version=2,
    )

    assert entry.after_settings_version == entry.before_settings_version == 2


@pytest.mark.parametrize(
    ("before", "after"),
    [(None, None), (2, 3), (2, None), (None, 2)],
)
def test_a_no_op_that_moves_or_omits_a_version_is_refused(
    before: int | None, after: int | None
) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(
            outcome=ConstraintProjectSettingsOutcome.NO_OP,
            before_settings_version=before,
            after_settings_version=after,
        )

    assert _code(raised) == "constraint_settings_history_no_op_changed_version"


@pytest.mark.parametrize(("before", "after"), [(None, None), (4, 4)])
def test_a_rejection_writes_no_new_version_with_or_without_a_settings_row(
    before: int | None, after: int | None
) -> None:
    entry = _entry(
        outcome=ConstraintProjectSettingsOutcome.REJECTED,
        before_settings_version=before,
        after_settings_version=after,
        resulting_timezone_name=None,
        resulting_settings_updated_at=None,
        failure_code="settings_version_stale",
    )

    assert entry.after_settings_version == entry.before_settings_version


@pytest.mark.parametrize(("before", "after"), [(None, 1), (4, 5), (4, None)])
def test_a_rejection_that_moved_a_version_is_refused(before: int | None, after: int | None) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(
            outcome=ConstraintProjectSettingsOutcome.REJECTED,
            before_settings_version=before,
            after_settings_version=after,
            resulting_timezone_name=None,
            resulting_settings_updated_at=None,
            failure_code="settings_version_stale",
        )

    assert _code(raised) == "constraint_settings_history_rejected_advanced"


@pytest.mark.parametrize("field", ["before_settings_version", "after_settings_version"])
@pytest.mark.parametrize("value", [0, -1])
def test_a_recorded_version_is_null_or_positive(field: str, value: int) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(**{field: value})

    assert _code(raised).endswith("_version_not_positive")


# --- The replay snapshot ---------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [ConstraintProjectSettingsOutcome.APPLIED, ConstraintProjectSettingsOutcome.NO_OP],
)
@pytest.mark.parametrize(
    ("timezone_name", "updated_at"),
    [(None, T0), (ZONE, None), (None, None)],
)
def test_a_succeeded_configure_without_a_full_snapshot_is_refused(
    outcome: ConstraintProjectSettingsOutcome,
    timezone_name: str | None,
    updated_at: datetime | None,
) -> None:
    versions: dict[str, object] = (
        {"before_settings_version": None, "after_settings_version": 1}
        if outcome is ConstraintProjectSettingsOutcome.APPLIED
        else {"before_settings_version": 1, "after_settings_version": 1}
    )

    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(
            outcome=outcome,
            resulting_timezone_name=timezone_name,
            resulting_settings_updated_at=updated_at,
            **versions,
        )

    assert _code(raised) == "constraint_settings_history_snapshot_pairing"


@pytest.mark.parametrize(("timezone_name", "updated_at"), [(ZONE, None), (None, T0), (ZONE, T0)])
def test_a_rejection_records_no_snapshot(
    timezone_name: str | None, updated_at: datetime | None
) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(
            outcome=ConstraintProjectSettingsOutcome.REJECTED,
            before_settings_version=None,
            after_settings_version=None,
            resulting_timezone_name=timezone_name,
            resulting_settings_updated_at=updated_at,
            failure_code="project_timezone_invalid",
        )

    assert _code(raised) == "constraint_settings_history_snapshot_pairing"


@pytest.mark.parametrize(
    ("timezone_name", "code"),
    [
        ("   ", "constraint_settings_history_timezone_blank"),
        (
            "z" * (MAX_PROJECT_TIMEZONE_NAME_CHARACTERS + 1),
            "constraint_settings_history_timezone_too_long",
        ),
        ("America/New York", "constraint_settings_history_timezone_has_whitespace"),
    ],
)
def test_a_recorded_snapshot_timezone_is_bounded_and_whitespace_free(
    timezone_name: str, code: str
) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(resulting_timezone_name=timezone_name)

    assert _code(raised) == code


# --- Failure evidence ------------------------------------------------------


def test_a_rejection_names_its_failure_code_and_may_detail_it() -> None:
    entry = _entry(
        outcome=ConstraintProjectSettingsOutcome.REJECTED,
        before_settings_version=None,
        after_settings_version=None,
        resulting_timezone_name=None,
        resulting_settings_updated_at=None,
        failure_code="project_timezone_invalid",
        failure_detail="the supplied name is not a known IANA zone",
    )

    assert entry.failure_code == "project_timezone_invalid"
    assert entry.failure_detail is not None


def test_a_rejection_without_a_failure_code_is_refused() -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(
            outcome=ConstraintProjectSettingsOutcome.REJECTED,
            before_settings_version=None,
            after_settings_version=None,
            resulting_timezone_name=None,
            resulting_settings_updated_at=None,
        )

    assert _code(raised) == "constraint_settings_history_failure_code_pairing"


def test_a_succeeded_configure_with_a_failure_code_is_refused() -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(failure_code="project_timezone_invalid")

    assert _code(raised) == "constraint_settings_history_failure_code_pairing"


@pytest.mark.parametrize("failure_code", ["", "Uppercase", "1leading", "has-a-dash", "x" * 65])
def test_a_malformed_failure_code_is_refused(failure_code: str) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(
            outcome=ConstraintProjectSettingsOutcome.REJECTED,
            before_settings_version=None,
            after_settings_version=None,
            resulting_timezone_name=None,
            resulting_settings_updated_at=None,
            failure_code=failure_code,
        )

    assert _code(raised) in {
        "constraint_settings_history_failure_code_pairing",
        "constraint_settings_history_failure_code_malformed",
    }


def test_a_succeeded_configure_carries_no_failure_detail() -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(failure_detail="something went wrong")

    assert _code(raised) == "constraint_settings_history_detail_without_rejection"


@pytest.mark.parametrize(
    ("detail", "code"),
    [
        ("   ", "constraint_settings_history_detail_blank"),
        (
            "d" * (MAX_SETTINGS_FAILURE_DETAIL_CHARACTERS + 1),
            "constraint_settings_history_detail_too_long",
        ),
    ],
)
def test_a_failure_detail_is_bounded_and_non_blank(detail: str, code: str) -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(
            outcome=ConstraintProjectSettingsOutcome.REJECTED,
            before_settings_version=None,
            after_settings_version=None,
            resulting_timezone_name=None,
            resulting_settings_updated_at=None,
            failure_code="project_timezone_invalid",
            failure_detail=detail,
        )

    assert _code(raised) == code


# --- Time ------------------------------------------------------------------


def test_a_receipt_normalises_its_instants_to_utc() -> None:
    elsewhere = T0.astimezone(timezone(timedelta(hours=-5)))
    entry = _entry(
        occurred_at=elsewhere,
        recorded_at=elsewhere,
        resulting_settings_updated_at=elsewhere,
    )

    assert entry.occurred_at.tzinfo is UTC
    assert entry.recorded_at.tzinfo is UTC
    assert entry.resulting_settings_updated_at is not None
    assert entry.resulting_settings_updated_at.tzinfo is UTC
    assert entry.occurred_at == T0


def test_a_receipt_is_recorded_no_earlier_than_it_occurred() -> None:
    with pytest.raises(ConstraintProjectSettingsHistoryError) as raised:
        _entry(recorded_at=T0 - timedelta(microseconds=1))

    assert _code(raised) == "constraint_settings_history_recorded_before_occurred"


def test_a_receipt_recorded_after_it_occurred_is_accepted() -> None:
    entry = _entry(recorded_at=T0 + timedelta(seconds=2))

    assert entry.recorded_at > entry.occurred_at


def test_a_receipt_is_frozen() -> None:
    entry = _entry()

    with pytest.raises(AttributeError):
        entry.outcome = ConstraintProjectSettingsOutcome.NO_OP  # type: ignore[misc]


# --- The typed key conflict ------------------------------------------------


def test_the_key_conflict_carries_a_stable_code_and_is_not_an_integrity_error() -> None:
    error = ConstraintProjectSettingsHistoryKeyConflictError("already bound")

    assert error.code == "constraint_settings_history_idempotency_key_taken"
    assert ConstraintProjectSettingsHistoryKeyConflictError.code == (
        "constraint_settings_history_idempotency_key_taken"
    )
    assert isinstance(error, Exception)


# --- The timezone validator ------------------------------------------------


@pytest.mark.parametrize(
    "timezone_name", ["UTC", "America/Chicago", "Europe/London", "Etc/GMT+5", "Asia/Kolkata"]
)
def test_a_real_iana_name_is_returned_byte_for_byte(timezone_name: str) -> None:
    assert validate_project_timezone_name(timezone_name) is timezone_name


@pytest.mark.parametrize("timezone_name", ["", "   ", "\t", "\n"])
def test_a_blank_or_whitespace_only_name_is_refused_before_zoneinfo(timezone_name: str) -> None:
    with pytest.raises(ProjectTimezoneError) as raised:
        validate_project_timezone_name(timezone_name)

    assert raised.value.code == "project_timezone_blank"


def test_an_over_length_name_is_refused_against_the_stored_bound() -> None:
    too_long = "A" * (MAX_PROJECT_TIMEZONE_NAME_CHARACTERS + 1)

    with pytest.raises(ProjectTimezoneError) as raised:
        validate_project_timezone_name(too_long)

    assert raised.value.code == "project_timezone_too_long"


@pytest.mark.parametrize(
    "timezone_name",
    [" UTC", "UTC ", "America/New York", "America/\tChicago", "UTC\n"],
)
def test_a_name_carrying_whitespace_is_refused_and_never_trimmed(timezone_name: str) -> None:
    """The no-trim proof: `" UTC"` is a refusal, not `"UTC"`.

    A validator that stripped would accept this and store a name the caller
    never sent. `ZoneInfo` would refuse `" UTC"` too, but only after a
    filesystem lookup, and only for the leading-space case — the shape check
    is what makes the refusal uniform and cheap.
    """
    with pytest.raises(ProjectTimezoneError) as raised:
        validate_project_timezone_name(timezone_name)

    assert raised.value.code == "project_timezone_has_whitespace"


@pytest.mark.parametrize(
    "timezone_name",
    [
        "Nowhere/Zone",
        "America/Chicagoo",
        ".",
        "..",
        "../etc/passwd",
        "/etc/passwd",
        "/usr/share/zoneinfo/UTC",
        "UTC/../UTC",
    ],
)
def test_an_unknown_or_structurally_illegal_key_is_refused_as_invalid(
    timezone_name: str,
) -> None:
    """`ZoneInfoNotFoundError` and `ValueError` alike become one stable code.

    `.`, `..` and the absolute paths are `ValueError` out of `ZoneInfo`, not
    `ZoneInfoNotFoundError`; catching only the latter would let a path traversal
    escape as an uncaught `ValueError` from the domain.
    """
    with pytest.raises(ProjectTimezoneError) as raised:
        validate_project_timezone_name(timezone_name)

    assert raised.value.code == "project_timezone_invalid"


def test_the_validator_offers_no_fallback_for_an_unknown_name() -> None:
    """No `except: return "UTC"`. The refusal is the whole behaviour."""
    with pytest.raises(ProjectTimezoneError):
        validate_project_timezone_name("Not/AZone")


def test_the_validator_does_not_canonicalise_a_link_to_its_target() -> None:
    """`US/Central` is a tzdata link to `America/Chicago` and stays spelled as sent."""
    assert validate_project_timezone_name("US/Central") == "US/Central"


def test_the_validator_leaves_project_today_untouched() -> None:
    """`project_today`'s two stable codes are unchanged by the new validator."""
    assert project_today(T0, ZONE).isoformat() == "2026-09-02"

    with pytest.raises(ProjectTimezoneError) as unconfigured:
        project_today(T0, None)
    with pytest.raises(ProjectTimezoneError) as invalid:
        project_today(T0, "Nowhere/Zone")

    assert unconfigured.value.code == "project_timezone_unconfigured"
    assert invalid.value.code == "project_timezone_invalid"
