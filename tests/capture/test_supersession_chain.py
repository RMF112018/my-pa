"""`QC-AC-013`: editing appends a version, and `QC-AC-010`: the predecessor stays readable.

Two criteria, one chain, and they are separable claims about it.

**`QC-AC-013` — "editing a capture creates a new version and does not overwrite
the original."** Proven on the *count* and on the *content*: three requests
produce three rows numbered 1, 2, 3, each superseding the one before, and version
one still holds the text version one was written with. A build that overwrote
would fail both halves, and a build that appended a row while also rewriting the
first would fail only the second — which is why the content is asserted and not
only the shape.

**`QC-AC-010` — "original text is immutable by version and independently
retrievable."** The immutability half is proven twice elsewhere, statically in
`tests/architecture/test_capture_has_no_update_path.py` and against the server
in `tests/schema/test_capture_immutability.py`. The half proven **here** is the
one the plan's paraphrase dropped and `D-75` restored: *independently
retrievable*. A superseded version is asked for **by its own identifier** and has
to come back with its own text — not the current version's, and not a refusal.
A build that resolved every read to the head of the chain would satisfy
"immutable" and fail the criterion.

**Why the application path and not the schema.** The trigger refuses an `UPDATE`
whatever the writer intended, so a test run against a live trigger cannot tell
"the writer appends" from "the writer tried to overwrite and the server said
no". The `QC-AC-013` plant is therefore run with the trigger **dropped**, which
isolates the claim to the application path; with the trigger in place the same
plant reddens too, for the other reason, and both runs are recorded in the
implementation evidence.

Everything here goes through `ApplicationService.invoke` over a real database.
Every value is synthetic, and no source is opened.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from sqlalchemy import text
from tests.capture.conftest import invoke, succeeded

from my_pa.application.commands import CreateCapture, ReadCapture, ReviseCapture
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability

#: Three texts, each identifying its own version. Distinct tokens rather than
#: "v1"/"v2"/"v3" substrings of one another, so an assertion cannot pass on a
#: prefix of the wrong answer.
FIRST: Final = "a note about flanges, as first written"
SECOND: Final = "a note about widgets, revised once"
THIRD: Final = "a note about gaskets, revised twice"


def _create(runtime: GatewayRuntime, text_: str, key: str) -> dict[str, Any]:
    return succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_CREATE,
            CreateCapture(text=text_, idempotency_key=key),
            f"create-{key}",
        ),
        "capture.create",
    )


def _revise(runtime: GatewayRuntime, capture_id: str, text_: str, key: str) -> dict[str, Any]:
    return succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_REVISE,
            ReviseCapture(capture_id=capture_id, text=text_, idempotency_key=key),
            f"revise-{key}",
        ),
        "capture.revise",
    )


def _read(
    runtime: GatewayRuntime, capture_id: str, version_id: str | None, tag: str
) -> ResponseEnvelope:
    return invoke(
        runtime,
        Capability.CAPTURE_READ,
        ReadCapture(capture_id=capture_id, version_id=version_id),
        tag,
    )


def _chain(runtime: GatewayRuntime, capture_id: str) -> list[tuple[str, int, str | None, str]]:
    """The stored chain, straight from the table, ordered by version number."""
    with runtime.work_engine.connect() as connection:
        return [
            (str(row[0]), int(row[1]), row[2], str(row[3]))
            for row in connection.execute(
                text(
                    "SELECT version_id, version_number, supersedes_version_id, content "
                    "FROM knowledge.capture_versions WHERE capture_id = :id "
                    "ORDER BY version_number"
                ),
                {"id": capture_id},
            )
        ]


@pytest.mark.database
def test_revising_twice_appends_two_versions_and_rewrites_neither(
    runtime: GatewayRuntime,
) -> None:
    """`QC-AC-013`, on the count, the chain, and the text each version was written with.

    The count alone would pass on a build that appended a row and *also*
    overwrote the first, so the original content is required back out of the
    store. The chain is asserted link by link rather than as "three rows exist",
    because three unlinked versions are three captures wearing one identifier.
    """
    created = _create(runtime, FIRST, "chain-1")
    capture_id = created["capture_id"]
    assert created["version_number"] == 1
    assert created["created"] is True

    second = _revise(runtime, capture_id, SECOND, "chain-2")
    third = _revise(runtime, capture_id, THIRD, "chain-3")
    assert (second["version_number"], third["version_number"]) == (2, 3)
    assert second["capture_id"] == capture_id, "a revise created a second capture"
    assert third["capture_id"] == capture_id

    stored = _chain(runtime, capture_id)
    assert len(stored) == 3, (
        f"three requests produced {len(stored)} versions. One would mean the "
        "second and third requests overwrote the first, which is the overwrite "
        "ADR-003 clause 3 replaces with a successor"
    )
    assert [number for _, number, _, _ in stored] == [1, 2, 3]

    # The chain, link by link. v1 supersedes nothing; each later one supersedes
    # exactly its predecessor.
    identifiers = [version_id for version_id, _, _, _ in stored]
    assert [supersedes for _, _, supersedes, _ in stored] == [None, *identifiers[:2]]

    # And the text each version was written with is the text it still holds.
    assert [content for _, _, _, content in stored] == [FIRST, SECOND, THIRD], (
        "a stored version no longer holds the text it was written with"
    )

    # The receipts name three distinct versions of one capture, so the chain the
    # caller was told about is the chain the store holds.
    assert len({created["version_id"], second["version_id"], third["version_id"]}) == 3
    assert [created["version_id"], second["version_id"], third["version_id"]] == identifiers


@pytest.mark.database
def test_a_superseded_version_is_retrievable_by_its_own_identifier(
    runtime: GatewayRuntime,
) -> None:
    """`QC-AC-010`'s "independently retrievable", which the plan's paraphrase dropped.

    Each of the three versions is asked for by **its own** identifier and has to
    answer with **its own** text. The current version is asked for as well, with
    no identifier, and the two answers have to differ — otherwise a build that
    resolved every read to the head of the chain would satisfy every assertion
    here by returning the same row three times.
    """
    created = _create(runtime, FIRST, "retrieve-1")
    capture_id = created["capture_id"]
    second = _revise(runtime, capture_id, SECOND, "retrieve-2")
    third = _revise(runtime, capture_id, THIRD, "retrieve-3")

    for expected, receipt in ((FIRST, created), (SECOND, second), (THIRD, third)):
        answer = succeeded(
            _read(runtime, capture_id, receipt["version_id"], f"read-{receipt['version_number']}"),
            f"capture.read of version {receipt['version_number']}",
        )
        assert answer["text"] == expected, (
            f"reading version {receipt['version_number']} by its own identifier "
            f"returned {answer['text']!r}. A superseded version stays retrievable "
            "at its own identifier; resolving every read to the head of the chain "
            "is the failure this asserts against"
        )
        assert answer["version_id"] == receipt["version_id"]
        assert answer["is_current"] is (receipt["version_number"] == 3)

    # The control that makes the three above a measurement rather than three
    # readings of one row: the same capture, read with no version named, is the
    # third version and not the first.
    current = succeeded(_read(runtime, capture_id, None, "read-current"), "capture.read (current)")
    assert current["text"] == THIRD
    assert current["version_id"] == third["version_id"]
    assert current["is_current"] is True
    assert current["text"] != FIRST, (
        "the current version and the first are the same row, so 'by its own "
        "identifier' has not been distinguished from 'whatever is current'"
    )

    # A version identifier belonging to no capture is `not_found` rather than a
    # silent fall back to the current version, which is the same failure wearing
    # a success.
    other = _create(runtime, "an unrelated note", "retrieve-other")
    refused = _read(runtime, capture_id, other["version_id"], "read-foreign")
    assert refused.error is not None and refused.error.code == ErrorCode.NOT_FOUND, (
        "a version identifier issued under a different capture was answered rather than refused"
    )
