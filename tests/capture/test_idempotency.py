"""`QC-AC-031` and `QC-AC-032`: the same key replays, a reused key with new content fails closed.

The two criteria are one mechanism seen from its two sides — the `NOT NULL
UNIQUE` index on `knowledge.capture_submissions.idempotency_key` — and they are
in one module because `QC-AC-032`'s subject is a **zero** and a zero is only
meaningful beside a non-zero produced by the same mechanism.

**`QC-AC-031` — replay.** The same key with byte-identical content, submitted
twice, stores one version and returns the same receipt. Asserted with a
**non-zero control in the same test**: a *different* key carrying the *same*
text creates a second capture. Without that control a build that stored nothing
at all would satisfy "one version exists after two requests" by having zero, and
would satisfy "the same receipt came back twice" by failing both times
identically. The control is what makes the first half a claim about idempotency
rather than about emptiness.

**`QC-AC-032` — conflict.** The same key with *different* content is refused
with `conflict` and `safe_details: ["idempotency_key"]`. Not
`idempotency_conflict`: `contracts/v1/errors.py` is a closed set of **eleven**
public codes, that is not one of them, and inventing a twelfth would be an
unauthorised expansion of `v1` (`D-75`). The refusal writes **nothing** — no
capture, no version, no receipt, no submission, no queued job — and that zero is
measured as a difference against counts taken immediately before, which are
themselves required to be non-zero.

**The refusal is a property of the transaction, not of a cleanup path.** The
submission row is written *first*, under `ON CONFLICT DO NOTHING`; a key already
taken means nothing was written at all, and the stored payload digest decides
which of the two answers the caller gets. Nothing is inserted and then removed,
so there is no window in which a partially admitted capture exists.

Every value here is synthetic. No source is opened and no path is reached.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from tests.capture.conftest import counts, invoke, succeeded

from my_pa.application.commands import CreateCapture, ListCaptures
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability

#: One key, submitted more than once. Held as a constant because "the same key"
#: is the whole subject and a formatted string could differ by a character.
KEY: Final = "shortcut-2026-08-03-0001"

#: A second key. Same content, different key — the control that says the store
#: is capable of holding two captures at all.
OTHER_KEY: Final = "shortcut-2026-08-03-0002"

TEXT: Final = "the blue widget has three flanges"
DIFFERENT_TEXT: Final = "the blue widget has four flanges"

#: The one table in `counts` that is not the capture plane, and the one a
#: refused-but-authorized request legitimately grows.
AUDIT: Final = "knowledge.audit_events"


def _create(runtime: GatewayRuntime, text: str, key: str, tag: str) -> ResponseEnvelope:
    return invoke(
        runtime,
        Capability.CAPTURE_CREATE,
        CreateCapture(text=text, idempotency_key=key),
        tag,
    )


def _listed(runtime: GatewayRuntime) -> list[dict[str, Any]]:
    listing = succeeded(
        invoke(runtime, Capability.CAPTURE_LIST, ListCaptures(), "list"), "capture.list"
    )
    return list(listing["captures"])


@pytest.mark.database
def test_the_same_key_and_the_same_content_stores_once_and_returns_one_receipt(
    runtime: GatewayRuntime,
) -> None:
    """`QC-AC-031`, with the non-zero control that keeps it from being vacuous.

    Three requests: two under one key with identical text, one under a second
    key with the *same* text. The first two are one capture and one receipt; the
    third is a second capture. A build that stored nothing would fail the
    control, and a build that stored everything would fail the replay.
    """
    first = succeeded(_create(runtime, TEXT, KEY, "replay-1"), "capture.create")
    second = succeeded(_create(runtime, TEXT, KEY, "replay-2"), "capture.create (replay)")

    assert first["created"] is True
    assert second["created"] is False, (
        "the second submission of one key reported that it created something. "
        "A caller retrying after a lost response has to be able to tell that its "
        "retry stored nothing new"
    )
    # Everything except that flag is the same answer, which is what "the same
    # receipt" means for a caller holding it.
    assert {key: value for key, value in second.items() if key != "created"} == {
        key: value for key, value in first.items() if key != "created"
    }
    assert second["receipt_id"] == first["receipt_id"]
    assert second["version_id"] == first["version_id"]
    assert second["content_sha256"] == first["content_sha256"]

    after_replay = counts(runtime.work_engine)
    assert after_replay["knowledge.captures"] == 1
    assert after_replay["knowledge.capture_versions"] == 1, (
        "two submissions of one key stored two versions; the unique index on "
        "`capture_submissions.idempotency_key` is what makes the second a replay"
    )
    assert after_replay["knowledge.capture_receipts"] == 1
    assert after_replay["knowledge.capture_submissions"] == 1
    assert after_replay["knowledge.capture_jobs"] == 1, (
        "the outbox row is part of the admission; one admitted capture owes one "
        "unit of processing, and a replay owes none"
    )

    # --- the non-zero control: a different key, the same text -------------------
    third = succeeded(_create(runtime, TEXT, OTHER_KEY, "replay-3"), "capture.create (other key)")
    assert third["created"] is True
    assert third["capture_id"] != first["capture_id"], (
        "a different idempotency key carrying the same text was answered as a "
        "replay. Idempotency is keyed on the key, not on the content, and "
        "without this a build that stored nothing at all would pass the "
        "assertions above"
    )
    assert third["content_sha256"] == first["content_sha256"], (
        "the same text produced two different digests, so the control is not "
        "holding the content constant"
    )

    after_control = counts(runtime.work_engine)
    assert after_control["knowledge.captures"] == 2
    assert after_control["knowledge.capture_versions"] == 2
    assert after_control["knowledge.capture_receipts"] == 2

    listed = _listed(runtime)
    assert len(listed) == 2, f"the listing reports {len(listed)} captures, not two"
    assert {entry["capture_id"] for entry in listed} == {
        first["capture_id"],
        third["capture_id"],
    }


@pytest.mark.database
def test_the_same_key_with_different_content_is_a_conflict_that_stores_nothing(
    runtime: GatewayRuntime,
) -> None:
    """`QC-AC-032`: `conflict`, one safe detail, and not one row written.

    The zero is measured as a difference against counts taken immediately before
    the refused request, and those counts are asserted non-zero first — so
    "nothing was written" is a statement about *this* request rather than about
    an empty database. The `QC-AC-031` control lives in the module beside this,
    which is the other half of the same requirement.

    **The zero is over the capture plane and deliberately not over the audit
    table.** The refused request was *authorized* — its refusal is about the
    caller's key, not about its authority — and `authorize` records that
    decision on the audit sink's own connection before the handler runs
    (`D-34`). So the audit table gains exactly one row while the capture plane
    gains none, and asserting the audit row absent here would be asserting
    `D-34` is false.
    """
    stored = succeeded(_create(runtime, TEXT, KEY, "conflict-1"), "capture.create")
    before = counts(runtime.work_engine)
    assert before["knowledge.captures"] == 1, (
        "the conflict below is measured as a difference, and a difference from "
        "zero would be satisfied by a build that never stores anything"
    )
    assert before["knowledge.capture_versions"] == 1
    assert before["knowledge.capture_receipts"] == 1
    assert before["knowledge.capture_jobs"] == 1

    refused = _create(runtime, DIFFERENT_TEXT, KEY, "conflict-2")

    assert refused.error is not None, (
        "an idempotency key bound to one payload accepted a different one. That "
        "is the request `QC-AC-032` requires to fail closed"
    )
    assert refused.error.code == ErrorCode.CONFLICT, (
        f"the refusal reported {refused.error.code}. `contracts/v1/errors.py` is "
        "a closed set of eleven public codes and `idempotency_conflict` is not "
        "one of them; inventing a twelfth would be an unauthorised v1 expansion"
    )
    assert list(refused.error.safe_details) == ["idempotency_key"], (
        f"the refusal named {list(refused.error.safe_details)}. It names the key "
        "and nothing else — naming which field differed would describe the "
        "stored request to whoever guessed the key"
    )
    assert refused.result is None

    # --- the zero, as a difference ---------------------------------------------
    after = counts(runtime.work_engine)
    plane = {table: count for table, count in after.items() if table != AUDIT}
    assert plane == {table: count for table, count in before.items() if table != AUDIT}, (
        "the refused request left rows behind. Fails closed is a property of the "
        "transaction here: the submission row is written first under `ON CONFLICT "
        "DO NOTHING`, so a taken key means nothing was written rather than "
        "something written and then removed"
    )
    assert after[AUDIT] == before[AUDIT] + 1, (
        "the refused request left no audit event. It was authorized — the refusal "
        "is about the caller's key, not its authority — and the record of that "
        "decision commits first and separately, per `D-34`"
    )

    # And the stored capture is untouched and still readable, so the refusal
    # protected the earlier request rather than damaging it.
    listed = _listed(runtime)
    assert len(listed) == 1
    assert listed[0]["capture_id"] == stored["capture_id"]
    assert listed[0]["version_count"] == 1
