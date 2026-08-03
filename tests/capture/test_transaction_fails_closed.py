"""`QC-AC-034`: an induced failure inside the save leaves no capture behind.

The criterion says an induced audit or receipt failure fails the whole request
closed and no capture exists afterwards. The plan's *test* is right; the plan's
*mechanism sentence* in section 12's WP-6 entry was not, and `D-75`
corrected it. The two
cases below are the two ends of that correction, and **they differ in what the
audit table holds afterwards**:

**(a) the audit fails.** `SqlAlchemyAuditSink.record` takes its own connection
and commits before returning, and `authorize` calls it before any handler runs.
A failure there stops the request before the capture is attempted, so nothing at
all is written — no capture and no audit row.

**(b) the receipt fails.** The audit event has already committed, on its own
connection, by the time the receipt insert runs. So the honest assertion is that
the capture is **absent** *and* the audit row is **present**. `D-34` records
that direction as the correct one: the audit exists to outlive the work it
describes, and a failed work transaction leaving an audit event describing an
authorization whose work never landed is the trade taken deliberately.

**A test asserting both are absent would be asserting `D-34` is false**, and
would go green on a build that had quietly made the audit atomic with the work —
which is the thing `D-34` forbids. That is the vacuity trap in this criterion
and it is why case (b) is written the way it is.

**The failures are induced in the server, not by a fake.** A `BEFORE INSERT`
trigger that raises is installed on exactly the table under test, for exactly
the duration of the case, on the disposable database. Nothing about the
production path is replaced: the same composition, the same sink, the same
transaction, and a real error arriving at the real statement. A fake sink would
have proven that the *fake* raises where the test told it to.

Every value here is synthetic. No source is opened and no path is reached.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

import pytest
from sqlalchemy import Engine, text
from tests.capture.conftest import counts, invoke, succeeded

from my_pa.application.commands import CreateCapture
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability

TEXT: Final = "a note that must not survive a failed save"

#: The names the induced failure is installed under. One function per case, so a
#: leaked trigger from one case cannot be mistaken for the other's.
_FUNCTION: Final = "refuse_every_insert_for_this_test"


@contextmanager
def _insert_refused(engine: Engine, table: str) -> Iterator[None]:
    """Make every `INSERT` into `table` raise, for the duration of the block.

    Installed and removed in the same fixture rather than left for teardown,
    because a trigger surviving this block would make every later test in the
    package fail for a reason that has nothing to do with what it asserts.
    """
    trigger = f"{_FUNCTION}_on_{table.split('.')[-1]}"
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE FUNCTION knowledge.{_FUNCTION}() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN "
                "RAISE EXCEPTION 'induced failure for QC-AC-034'; END; $$"
            )
        )
        connection.execute(
            text(
                f"CREATE TRIGGER {trigger} BEFORE INSERT ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION knowledge.{_FUNCTION}()"
            )
        )
    try:
        yield
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
            connection.execute(text(f"DROP FUNCTION IF EXISTS knowledge.{_FUNCTION}()"))


def _create(runtime: GatewayRuntime, key: str, tag: str) -> ResponseEnvelope:
    return invoke(
        runtime,
        Capability.CAPTURE_CREATE,
        CreateCapture(text=TEXT, idempotency_key=key),
        tag,
    )


def _audit_rows(engine: Engine) -> list[tuple[str, str]]:
    with engine.connect() as connection:
        return [
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                text("SELECT capability, outcome FROM knowledge.audit_events")
            )
        ]


@pytest.mark.database
def test_a_successful_save_writes_the_capture_and_the_audit_event(
    runtime: GatewayRuntime,
) -> None:
    """The control both failure cases are measured against.

    Without it, a build that stored nothing at all would satisfy "no capture
    exists afterwards" in both cases below, and the criterion would be proven by
    a product that does not work.
    """
    receipt = succeeded(_create(runtime, "atomic-control", "control"), "capture.create")
    assert receipt["version_number"] == 1

    stored = counts(runtime.work_engine)
    assert stored["knowledge.captures"] == 1
    assert stored["knowledge.capture_versions"] == 1
    assert stored["knowledge.capture_receipts"] == 1
    assert stored["knowledge.capture_submissions"] == 1
    assert stored["knowledge.capture_jobs"] == 1, "the outbox row is part of the save"
    assert _audit_rows(runtime.work_engine) == [(Capability.CAPTURE_CREATE.value, "allowed")]


@pytest.mark.database
def test_an_induced_audit_failure_leaves_no_capture_and_no_audit_row(
    runtime: GatewayRuntime,
) -> None:
    """Case (a): the audit commits first, so its failure stops everything.

    Nothing is written anywhere, and the caller is told the request did not
    complete without being told what the store said — the driver message never
    reaches the answer.
    """
    with _insert_refused(runtime.work_engine, "knowledge.audit_events"):
        refused = _create(runtime, "atomic-audit", "audit-fails")

    assert refused.error is not None, (
        "the request succeeded with its audit event refused. An audit failure "
        "that a handler swallows is a capture stored with no record that anyone "
        "was authorized to store it"
    )
    assert refused.error.code == ErrorCode.INTERNAL_ERROR
    assert refused.result is None

    after = counts(runtime.work_engine)
    assert after == dict.fromkeys(after, 0), (
        f"a failed audit left rows behind: {after}. The audit commits before the "
        "handler runs, so a failure there stops the request before any capture "
        "row is attempted"
    )

    # And nothing about the failure reached the caller beyond that it failed.
    rendered = repr(refused)
    assert "psycopg" not in rendered
    assert "induced failure" not in rendered
    assert TEXT not in rendered, "the refused capture's own text reached the error payload"


@pytest.mark.database
def test_an_induced_receipt_failure_leaves_no_capture_and_keeps_the_audit_row(
    runtime: GatewayRuntime,
) -> None:
    """Case (b): the capture is absent **and** the audit row is present.

    This is the end that differs, and asserting the audit row absent here would
    be asserting `D-34` is false — the audit sink writes on its own connection
    and commits before the work it describes, precisely so that an allowed
    request whose handler fails still leaves a record of the authorization.
    """
    with _insert_refused(runtime.work_engine, "knowledge.capture_receipts"):
        refused = _create(runtime, "atomic-receipt", "receipt-fails")

    assert refused.error is not None
    assert refused.error.code == ErrorCode.INTERNAL_ERROR
    assert refused.result is None

    after = counts(runtime.work_engine)
    capture_plane = {
        table: count for table, count in after.items() if table != "knowledge.audit_events"
    }
    assert capture_plane == dict.fromkeys(capture_plane, 0), (
        f"a failed receipt left a capture behind: {capture_plane}. The capture, "
        "its version, its submission, its receipt and its queued job commit "
        "together or not at all, on the work connection"
    )

    assert _audit_rows(runtime.work_engine) == [(Capability.CAPTURE_CREATE.value, "allowed")], (
        "the audit event describing the authorization is gone. It committed "
        "first and separately, on the audit connection, and `D-34` records that "
        "as the correct direction of the trade: the audit outlives the work it "
        "describes. Asserting it absent here would be asserting `D-34` is false"
    )

    rendered = repr(refused)
    assert "psycopg" not in rendered
    assert TEXT not in rendered
