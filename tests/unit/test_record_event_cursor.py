"""WP-RE-06: the Record Event cursor codec, binding and page size (RE-AC-059..063).

FAST. The cursor is `{"b", "e", "v"}` canonical JSON in unpadded base64url
(OD-1), bound to a digest of the request's visibility (plan section 6.2), and
decoded in the U-002 order that makes the binding the guard:

1. shape -- malformed is `invalid_request(cursor)` and **nothing is looked up**;
2. binding -- a readable token under another binding, including another
   Principal's, is `conflict(cursor)`, **before `e` is resolved**;
3. position -- only then is `e` resolved; not found is `invalid_request(cursor)`.

Also pinned: the dedicated 512-character token cap (D-03), every binding key
(D-04), `grant_digest`, and the page-size bounds (D-02).
"""

from __future__ import annotations

import base64
import json
from typing import Final

import pytest

from my_pa.application.errors import ConflictError, InvalidRequestError, SafeDetail
from my_pa.application.record_events import (
    DEFAULT_RECORD_EVENT_PAGE_SIZE,
    MAX_RECORD_EVENT_CURSOR_CHARACTERS,
    MAX_RECORD_EVENT_PAGE_SIZE,
    MemoryDisclosure,
    cursor_binding,
    decode_cursor,
    encode_cursor,
    grant_digest,
    read_cursor,
    record_event_page_size,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import RecordEventFamily

PRINCIPAL_A: Final = "prn_cursorunit00000a"
PRINCIPAL_B: Final = "prn_cursorunit00000b"
EVENT: Final = "rcev_cursorunit0000001"
TASKS: Final = frozenset({RecordEventFamily.TASK})


def binding(**overrides: object) -> str:
    fields: dict[str, object] = {
        "principal_id": PRINCIPAL_A,
        "visible": TASKS,
        "requested": None,
        "page_size": 50,
        "disclosure": MemoryDisclosure.INCLUDE_RESTRICTED,
        "grants_digest": None,
    }
    fields.update(overrides)
    return cursor_binding(**fields)  # type: ignore[arg-type]


def token_of(document: object, *, pad: bool = False) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(document).encode("ascii")).decode("ascii")
    return raw if pad else raw.rstrip("=")


class Resolver:
    """A spy for step 3: records every `e` it is asked to resolve."""

    def __init__(self, answer: int | None = 7) -> None:
        self.answer = answer
        self.calls: list[str] = []

    def __call__(self, event_id: str) -> int | None:
        self.calls.append(event_id)
        return self.answer


# ---- encoding ----------------------------------------------------------------


def test_a_token_is_unpadded_base64url_canonical_json_with_three_keys() -> None:
    bound = binding()
    token = encode_cursor(bound, EVENT)
    assert "=" not in token and "+" not in token and "/" not in token
    decoded = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    assert decoded == {"b": bound, "e": EVENT, "v": 1}
    assert read_cursor(token) == (bound, EVENT)
    assert read_cursor(encode_cursor(bound, None)) == (bound, None)


# ---- RE-AC-059: shape ----------------------------------------------------------

B: Final = "a" * 64

MALFORMED: Final[dict[str, object]] = {
    "empty": "",
    "not a string": 17,
    "outside the alphabet": "abc+def/",
    "padding": token_of({"b": B, "e": None, "v": 1}, pad=True) + "==",
    "not base64": "!!!!",
    "not json": base64.urlsafe_b64encode(b"not json").decode().rstrip("="),
    "a json list": token_of([B, None, 1]),
    "an extra key": token_of({"b": B, "e": None, "v": 1, "s": 3}),
    "a missing key": token_of({"b": B, "v": 1}),
    "the package-literal s key": token_of({"b": B, "s": 3, "v": 1}),
    "v two": token_of({"b": B, "e": None, "v": 2}),
    "v true": token_of({"b": B, "e": None, "v": True}),
    "v text": token_of({"b": B, "e": None, "v": "1"}),
    "b short": token_of({"b": "a" * 63, "e": None, "v": 1}),
    "b uppercase": token_of({"b": "A" * 64, "e": None, "v": 1}),
    "b not text": token_of({"b": 5, "e": None, "v": 1}),
    "e wrong kind": token_of({"b": B, "e": "task_0123456789", "v": 1}),
    "e a number": token_of({"b": B, "e": 3, "v": 1}),
}


@pytest.mark.parametrize("token", list(MALFORMED.values()), ids=list(MALFORMED))
def test_a_malformed_token_is_unreadable(token: object) -> None:
    assert read_cursor(token) is None


@pytest.mark.parametrize("token", list(MALFORMED.values()), ids=list(MALFORMED))
def test_a_malformed_token_is_an_invalid_request_and_resolves_nothing(token: object) -> None:
    resolver = Resolver()
    with pytest.raises(InvalidRequestError) as refused:
        decode_cursor(token, B, resolver)  # type: ignore[arg-type]
    assert refused.value.safe_details == (SafeDetail.CURSOR,)
    assert resolver.calls == []


def test_the_token_cap_is_the_dedicated_512() -> None:
    bound = binding()

    def spaced(width: int) -> str:
        document = f'{{"b": "{bound}", "e": null, "v": 1}}'
        return (
            base64.urlsafe_b64encode((document + " " * width).encode("ascii"))
            .decode("ascii")
            .rstrip("=")
        )

    fits = next(spaced(w) for w in range(400) if len(spaced(w)) in (511, 512))
    over = next(spaced(w) for w in range(400) if len(spaced(w)) > 512)
    assert read_cursor(over) is None
    assert read_cursor(fits) == (bound, None)
    assert MAX_RECORD_EVENT_CURSOR_CHARACTERS == 512


# ---- RE-AC-060 / 061: the decode order -------------------------------------------


def test_a_readable_token_under_another_binding_is_a_conflict_before_any_lookup() -> None:
    resolver = Resolver()
    with pytest.raises(ConflictError) as refused:
        decode_cursor(encode_cursor(binding(page_size=10), EVENT), binding(), resolver)
    assert refused.value.safe_details == (SafeDetail.CURSOR,)
    assert resolver.calls == []


def test_a_token_issued_to_another_principal_is_a_conflict_before_any_lookup() -> None:
    """U-002: Principal A's token, presented by Principal B, never reaches step 3."""
    issued_to_a = encode_cursor(binding(principal_id=PRINCIPAL_A), EVENT)
    resolver = Resolver()
    with pytest.raises(ConflictError):
        decode_cursor(issued_to_a, binding(principal_id=PRINCIPAL_B), resolver)
    assert resolver.calls == []


def test_a_cursor_bound_to_the_twenty_family_set_conflicts() -> None:
    """WP-RE-08 RE-AC-102: a token issued before the two new families existed.

    A local caller's visible set was the twenty pre-WP-RE-08 families; after
    WP-RE-08 it is twenty-two, so the old token's binding mismatches at step 2
    and is `conflict(cursor)` before its event is resolved. A fresh list from
    the start (no token) is the designed recovery and returns full history.
    """
    new_families = {
        RecordEventFamily.CAPTURE,
        RecordEventFamily.TASK_COMMENT,
        # KLP-WP-03 added a third family after WP-RE-08.
        RecordEventFamily.KNOWLEDGE_ASSERTION,
    }
    twenty = frozenset(RecordEventFamily) - new_families
    assert len(twenty) == 20
    old_token = encode_cursor(
        binding(visible=twenty, disclosure=MemoryDisclosure.INCLUDE_RESTRICTED), EVENT
    )
    current = binding(
        visible=frozenset(RecordEventFamily), disclosure=MemoryDisclosure.INCLUDE_RESTRICTED
    )
    resolver = Resolver()
    with pytest.raises(ConflictError) as refused:
        decode_cursor(old_token, current, resolver)
    assert refused.value.safe_details == (SafeDetail.CURSOR,)
    assert resolver.calls == []
    assert decode_cursor(None, current, resolver) == 0


def test_an_event_that_does_not_resolve_after_a_binding_match_is_invalid() -> None:
    bound = binding()
    resolver = Resolver(answer=None)
    with pytest.raises(InvalidRequestError):
        decode_cursor(encode_cursor(bound, EVENT), bound, resolver)
    assert resolver.calls == [EVENT]


def test_a_resolved_event_is_the_position_and_a_null_one_is_the_start() -> None:
    bound = binding()
    resolver = Resolver(answer=41)
    assert decode_cursor(encode_cursor(bound, EVENT), bound, resolver) == 41
    assert decode_cursor(encode_cursor(bound, None), bound, resolver) == 0
    assert decode_cursor(None, bound, resolver) == 0
    assert resolver.calls == [EVENT]


# ---- RE-AC-062 / 063: every binding key --------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"principal_id": PRINCIPAL_B},
        {"visible": frozenset({RecordEventFamily.TASK, RecordEventFamily.MEETING})},
        {"requested": (RecordEventFamily.TASK,)},
        {"page_size": 49},
        {"disclosure": MemoryDisclosure.EXCLUDE_RESTRICTED},
        {"grants_digest": "b" * 64},
    ],
    ids=["principal", "visible", "requested", "page_size", "disclosure", "grant_digest"],
)
def test_every_binding_key_changes_the_digest(change: dict[str, object]) -> None:
    assert binding(**change) != binding()


def test_the_binding_is_order_insensitive_over_family_sets() -> None:
    forward = (RecordEventFamily.TASK, RecordEventFamily.MEETING)
    assert binding(requested=forward) == binding(requested=tuple(reversed(forward)))
    assert len(binding()) == 64


def test_grant_digest_is_null_locally_and_tracks_every_visibility_grant() -> None:
    assert grant_digest(None) is None
    tasks = frozenset({(Capability.TASKS_READ, Purpose.TASK_READ)})
    both = tasks | {(Capability.TASKS_LIST, Purpose.TASK_READ)}
    assert grant_digest(tasks) != grant_digest(both)
    assert grant_digest(tasks) != grant_digest(tasks | {(Capability.ENTITIES_GET, None)})
    # A grant no family read depends on does not move it.
    unrelated = tasks | {(Capability.TASKS_CREATE, Purpose.TASK_AUTHORING)}
    assert grant_digest(tasks) == grant_digest(unrelated)
    assert grant_digest(frozenset()) != grant_digest(tasks)


# ---- page size -----------------------------------------------------------------------


def test_page_size_defaults_to_fifty_and_never_exceeds_one_hundred() -> None:
    assert record_event_page_size(150, published_max=200) == 100
    assert record_event_page_size(None, published_max=200) == 50
    assert record_event_page_size(None, published_max=20) == 20
    assert DEFAULT_RECORD_EVENT_PAGE_SIZE == 50
    assert MAX_RECORD_EVENT_PAGE_SIZE == 100
    assert record_event_page_size(80, published_max=60) == 60
    assert record_event_page_size(1, published_max=200) == 1


@pytest.mark.parametrize("requested", [0, -1, True, "5", 2.5])
def test_a_page_size_that_is_not_a_positive_integer_is_refused(requested: object) -> None:
    with pytest.raises(InvalidRequestError) as refused:
        record_event_page_size(requested, published_max=100)
    assert refused.value.safe_details == (SafeDetail.PAGE_SIZE,)
