"""One non-empty text field saves; nothing else is a precondition.

The acceptance control is "a single non-empty text field is sufficient to save"
with "no mandatory title, tags, or type before save", and it has two halves that
fail in opposite directions:

* **Sufficiency.** A save with nothing but text and an idempotency key succeeds
  and is durable. Proved against the request the product actually takes, so a
  field made mandatory later — a title, a tag list, a required kind — turns this
  red rather than passing review as a small addition.
* **Emptiness.** Whitespace-only is *not* text. `"   "` and `"\\n\\t"` are the
  shapes an accidental save takes when a person opens the sheet and closes it,
  and a build that stored them would fill Review with blank evidence.

**Kind is a default, not a precondition.** `CaptureKind.QUICK_NOTE` is the value
`CreateCapture` uses when the caller names none, and `CONVERSATION_LOG` is
selectable — so mode selection is *allowed* without being a step before saving.
Both are asserted, because a build that required the kind and a build that
ignored it would each pass only one of them.

Every value here is synthetic. No source is opened and no path is reached.
"""

from __future__ import annotations

from typing import Final

import pytest
from tests.capture.conftest import counts, invoke, succeeded

from my_pa.application.commands import CreateCapture
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.capture.version import MAX_CAPTURE_CHARACTERS
from my_pa.domain.identity.operation import Capability

NOTE: Final = "synthetic note beta — one field is enough"

#: The shapes that look like text and are not. The last two are the ones worth
#: having: `U+00A0` and `U+2003` are invisible, are not ASCII whitespace, and
#: `str.strip()` does remove them - so this asserts the rule is Unicode-aware
#: rather than assuming it. Written as escapes so the source cannot be read as
#: an ordinary space.
BLANK: Final = ("", " ", "   ", "\n", "\t\n ", "\u00a0", " \u2003\n")


def _create(
    runtime: GatewayRuntime,
    text: str,
    key: str,
    *,
    capture_kind: CaptureKind = CaptureKind.QUICK_NOTE,
) -> ResponseEnvelope:
    return invoke(
        runtime,
        Capability.CAPTURE_CREATE,
        CreateCapture(text=text, idempotency_key=key, capture_kind=capture_kind),
        key,
    )


@pytest.mark.database
def test_a_single_non_empty_text_field_is_sufficient_to_save(runtime: GatewayRuntime) -> None:
    """Text and a key, and nothing else. No title, no tags, no kind."""
    receipt = succeeded(_create(runtime, NOTE, "one-field-0001"), "capture.create")

    assert receipt["created"] is True
    assert receipt["version_number"] == 1
    assert receipt["receipt_id"]
    stored = counts(runtime.work_engine)
    assert stored["knowledge.captures"] == 1, (
        "a save carrying only text was acknowledged without being stored"
    )
    assert stored["knowledge.capture_versions"] == 1


@pytest.mark.database
def test_whitespace_only_text_is_refused_and_stores_nothing(runtime: GatewayRuntime) -> None:
    """Every blank shape is `invalid_request` naming the field, and writes no row.

    The zero is measured over the capture plane rather than the whole database,
    for the reason `test_idempotency.py` gives: the refusals here are *authorized*
    requests, so each one legitimately adds an audit row.
    """
    for index, blank in enumerate(BLANK):
        refused = _create(runtime, blank, f"one-field-blank-{index}")
        assert refused.error is not None, (
            f"a capture carrying {blank!r} was accepted. Whitespace is not evidence, "
            "and a build that stores it fills Review with blank sources"
        )
        assert refused.error.code == ErrorCode.INVALID_REQUEST
        assert list(refused.error.safe_details) == ["text"]

    stored = counts(runtime.work_engine)
    assert stored["knowledge.captures"] == 0
    assert stored["knowledge.capture_versions"] == 0
    assert stored["knowledge.capture_submissions"] == 0
    assert stored["knowledge.capture_jobs"] == 0


@pytest.mark.database
def test_text_past_the_bound_is_refused_honestly_and_names_the_bound(
    runtime: GatewayRuntime,
) -> None:
    """Oversized input is refused, and the refusal says which bound it broke.

    One character past the bound rather than a wildly large value, so the
    assertion is about the boundary rather than about a size that any limit would
    reject. The control beside it is the same text one character shorter, which
    is accepted — without it, this would pass against a build that refused
    everything.
    """
    oversized = "x" * (MAX_CAPTURE_CHARACTERS + 1)
    refused = _create(runtime, oversized, "one-field-oversized")
    assert refused.error is not None
    assert refused.error.code == ErrorCode.INVALID_REQUEST
    assert list(refused.error.safe_details) == ["text", "max_capture_characters"], (
        "the refusal did not name the bound it broke, so a caller cannot tell an "
        "oversized note from a malformed one"
    )
    assert counts(runtime.work_engine)["knowledge.captures"] == 0

    accepted = succeeded(
        _create(runtime, oversized[:-1], "one-field-at-the-bound"),
        "capture.create",
    )
    assert accepted["created"] is True, (
        "text exactly at the bound was refused, so the refusal above is not about the bound"
    )


@pytest.mark.database
def test_the_kind_defaults_and_is_selectable_without_being_a_precondition(
    runtime: GatewayRuntime,
) -> None:
    """A quick note needs no kind; a conversation log may name one."""
    assert CreateCapture(text=NOTE, idempotency_key="k").capture_kind is CaptureKind.QUICK_NOTE, (
        "the default kind is not quick note, so a caller who names none is having a "
        "type chosen for them"
    )

    logged = succeeded(
        _create(
            runtime,
            "synthetic note gamma — call with the widget vendor",
            "one-field-conversation",
            capture_kind=CaptureKind.CONVERSATION_LOG,
        ),
        "capture.create",
    )
    assert logged["created"] is True
    assert logged["version_number"] == 1
