"""Reports Modernization WP06 (W3c): publish/update consume a finalized transfer session (T10).

Canonical FAST tests, in process, over the `FakeUnitOfWork` with a temporary
`FilesystemReportContentStore` and `FilesystemReportTransferStaging` on one
root, through `normalize` and `invoke` exactly as a transport calls them
(the rig and helpers are W3b's, `tests/unit/test_reports_transfer_application.py`):

* publish and update consume a transfer (new content; the head's content
  reused, also by a `no_op`), the session naming the content the version
  references, its staging discarded after the commit;
* the receipt replay runs FIRST: a publish/update retried after its token was
  consumed replays the original receipt; another key with the consumed token
  is the bare `not_found`; the same key with another source is `conflict`;
* every unusable session or token (unknown, foreign Principal, other client,
  local vs remote, open, aborted, expired, consumed, wrong token) is one
  rendered bare `not_found`, with zero mutation;
* a refusal of the update path after the claim leaves the session finalized;
  tampered staging is `internal_error`; no staging composed is `unsupported`;
* the token is in no receipt, row, audit event or intent digest input;
  `search_text` is the decoded content's only;
* the decode permit is taken by a transfer-sourced publish;
* a 600 KiB markdown transfer and (slow) a 16 MiB identity random-ASCII text
  transfer through the service, read back byte-exact through read_chunk, with
  tracemalloc peaks per operation printed and bounded.

All bytes are synthetic.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import re
import threading
import time
import tracemalloc
from collections.abc import Callable, Iterator
from enum import Enum
from pathlib import Path
from typing import Any, Final

import pytest

import my_pa.application.service as service_module
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.application.commands import (
    TRANSFER_CONTENT_DEFERRED,
    PublishGeneralReport,
    UpdateGeneralReport,
    publication_request,
    update_request,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.reports.content import content_from_staged
from my_pa.domain.reports.transfer import content_token_digest
from my_pa.domain.reports.vocabulary import (
    MAX_DECODED_CONTENT_BYTES,
    ContentEncoding,
    ContentFormat,
    TransferState,
)
from my_pa.infrastructure.report_content_stores.staging import FilesystemReportTransferStaging
from tests.conftest import Scene, operator
from tests.unit.test_reports_transfer_application import (
    CHUNK,
    CLIENT_A,
    CLIENT_B,
    NOT_FOUND,
    Rig,
    _abort,
    _b64,
    _begin,
    _details,
    _error,
    _expire,
    _finalize,
    _gz,
    _invoke,
    _ok,
    _pieces,
    _rig,
    _sha,
    _text,
    _uploaded,
)

MIB: Final = 1024 * 1024
#: Generous ceilings (contract C5): per-chunk operations and whole-content ones.
CHUNK_PEAK_CEILING: Final = 4 * MIB
WHOLE_PEAK_CEILING: Final = 160 * MIB


@pytest.fixture
def rig(scene: Scene, tmp_path: Path) -> Rig:
    return _rig(scene, tmp_path)


def _staging_tree(root: Path) -> list[str]:
    transfer = root / "transfer"
    if not transfer.exists():
        return []
    return sorted(str(path.relative_to(root)) for path in transfer.rglob("*"))


def _snapshot(rig: Rig) -> tuple[object, ...]:
    world = rig.scene.world
    return (
        dict(world.report_transfer_sessions),
        {key: list(value) for key, value in world.report_transfer_chunks.items()},
        _staging_tree(rig.root),
        dict(world.general_report_versions),
        dict(world.general_report_receipts),
        dict(world.general_report_update_receipts),
        () if rig.store is None else rig.store.stored_object_ids(),
    )


def _finalized(
    rig: Rig,
    staged: bytes,
    *,
    key: str,
    client: str | None = None,
    **begin: Any,  # noqa: ANN401
) -> tuple[str, str]:
    session_id = _uploaded(rig, staged, key=key, client=client, **begin)
    token = str(_ok(_finalize(rig, session_id, client=client))["content_token"])
    return session_id, token


def _reference(session_id: str, token: str) -> dict[str, Any]:
    return {"transfer": {"session_id": session_id, "content_token": token}}


def _publish(
    rig: Rig,
    content: dict[str, Any],
    *,
    key: str,
    client: str | None = None,
    principal: Any = None,  # noqa: ANN401
    title: str = "Synthetic transfer report",
) -> dict[str, Any]:
    return _invoke(
        rig,
        Capability.REPORTS_PUBLISH,
        {"title": title, "content": content, "idempotency_key": key},
        client=client,
        principal=principal,
    )


def _update(
    rig: Rig,
    report_id: str,
    patch: dict[str, Any],
    *,
    key: str,
    expected_version: int = 1,
    client: str | None = None,
) -> dict[str, Any]:
    return _invoke(
        rig,
        Capability.REPORTS_UPDATE,
        {
            "report_id": report_id,
            "expected_version": expected_version,
            "patch": patch,
            "change_reason": "Synthetic transfer update.",
            "idempotency_key": key,
        },
        client=client,
    )


def _read_back(rig: Rig, report_id: str, version_number: int, part: str = "decoded") -> bytes:
    out = bytearray()
    offset: int | None = 0
    while offset is not None:
        answer = _ok(
            _invoke(
                rig,
                Capability.REPORTS_TRANSFER_READ_CHUNK,
                {
                    "report_id": report_id,
                    "version_number": version_number,
                    "part": part,
                    "offset": offset,
                },
            )
        )
        chunk = base64.b64decode(answer["chunk"])
        assert _sha(chunk) == answer["chunk_sha256"]
        out += chunk
        offset = answer["next_offset"]
    return bytes(out)


def _strings(value: object, seen: set[int] | None = None) -> Iterator[str]:
    """Every string reachable in `value` (dataclass fields included, `repr=False` too)."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, str):
        yield value
    elif isinstance(value, bytes | bytearray):
        yield bytes(value).decode("latin-1")
    elif isinstance(value, Enum):
        yield str(value.value)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key, seen)
            yield from _strings(item, seen)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            yield from _strings(item, seen)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            yield from _strings(getattr(value, item.name, None), seen)


def _consumed_row(rig: Rig, session_id: str) -> Any:  # noqa: ANN401
    return rig.scene.world.report_transfer_sessions[session_id]


# ---- publish consumes a transfer (T10) ---------------------------------------


def test_publish_consumes_a_finalized_transfer_and_discards_its_staging(rig: Rig) -> None:
    staged = _text(CHUNK + 999)
    session_id, token = _finalized(rig, staged, key="p", fmt="markdown")
    assert rig.staging is not None and rig.staging.has_session(session_id)
    answer = _ok(_publish(rig, _reference(session_id, token), key="pub-1"))
    print("TRANSFER_PUBLISH_JSON", answer)
    assert answer["content"]["format"] == "markdown"
    assert answer["content"]["decoded_sha256"] == _sha(staged)
    assert answer["content"]["decoded_byte_count"] == len(staged)
    assert answer["replayed"] is False
    row = _consumed_row(rig, session_id)
    assert row.state is TransferState.CONSUMED
    assert row.consumed_content_id == answer["content"]["content_id"]
    assert row.consumed_at is not None
    # Discarded after the commit; the ledger is append-only and stays.
    assert not rig.staging.has_session(session_id)
    assert rig.scene.world.report_transfer_chunks[session_id]
    assert _read_back(rig, answer["report_id"], 1) == staged
    # Above the inline threshold (512 KiB is not reached here): stored inline
    # or as a blob by the WP05 rule; either way the read is byte-exact.


def test_a_publish_retry_after_consumption_replays_the_original_receipt(rig: Rig) -> None:
    staged = _text(5000)
    session_id, token = _finalized(rig, staged, key="p")
    first = _ok(_publish(rig, _reference(session_id, token), key="pub-1"))
    before = _snapshot(rig)
    again = _ok(_publish(rig, _reference(session_id, token), key="pub-1"))
    assert again == {**first, "replayed": True}
    assert _snapshot(rig) == before
    # Another key with the consumed token: the one bare not_found.
    assert _error(_publish(rig, _reference(session_id, token), key="pub-2")) == NOT_FOUND
    assert _snapshot(rig) == before
    # The same key with another source (or inline content) is the key's conflict.
    other_id, other_token = _finalized(rig, staged, key="q")
    before = _snapshot(rig)
    conflict = _publish(rig, _reference(other_id, other_token), key="pub-1")
    assert _details(conflict, ErrorCode.CONFLICT) == ["idempotency_key"]
    inline = _publish(rig, {"format": "text", "body": staged.decode()}, key="pub-1")
    assert _details(inline, ErrorCode.CONFLICT) == ["idempotency_key"]
    assert _snapshot(rig) == before
    assert _consumed_row(rig, other_id).state is TransferState.FINALIZED


def test_a_local_caller_reusing_a_key_under_another_intent_gets_the_conflict(rig: Rig) -> None:
    """WP08 C-WP06 (R1 #7): the keyed consume looks the receipt up by key and Principal only.

    A local caller's key is used as given (no client-bound derivation), so the
    intent digest is what tells two requests under one key apart: a publish or
    update whose key is already bound to another intent -- another title, an
    inline first use, another session -- is the key's `conflict`, nothing is
    written, and the named session stays finalized (its token unconsumed).
    """
    staged = _text(4096, seed=5)
    # Publish: first use transfer-sourced, then the same reference under another title.
    session_id, token = _finalized(rig, staged, key="p")
    _ok(_publish(rig, _reference(session_id, token), key="shared", client=None))
    second_id, second_token = _finalized(rig, staged, key="p2")
    before = _snapshot(rig)
    retitled = _publish(
        rig, _reference(second_id, second_token), key="shared", client=None, title="Other title"
    )
    assert _details(retitled, ErrorCode.CONFLICT) == ["idempotency_key"]
    assert _snapshot(rig) == before
    # First use inline, then a transfer reference under the same key.
    _ok(_publish(rig, {"format": "text", "body": "synthetic inline"}, key="inline-first"))
    before = _snapshot(rig)
    after_inline = _publish(rig, _reference(second_id, second_token), key="inline-first")
    assert _details(after_inline, ErrorCode.CONFLICT) == ["idempotency_key"]
    assert _snapshot(rig) == before
    assert _consumed_row(rig, second_id).state is TransferState.FINALIZED
    # Update: the key bound to one session's update, reused naming another session.
    head = _ok(_publish(rig, {"format": "text", "body": "synthetic head"}, key="head"))
    first_id, first_token = _finalized(rig, _text(4096, seed=6), key="u")
    _ok(_update(rig, head["report_id"], {"content": _reference(first_id, first_token)}, key="uk"))
    before = _snapshot(rig)
    reused = _update(
        rig, head["report_id"], {"content": _reference(second_id, second_token)}, key="uk"
    )
    assert _details(reused, ErrorCode.CONFLICT) == ["idempotency_key"]
    assert _snapshot(rig) == before
    assert _consumed_row(rig, second_id).state is TransferState.FINALIZED
    # The session is still consumable under a fresh key.
    _ok(_publish(rig, _reference(second_id, second_token), key="fresh"))
    assert _consumed_row(rig, second_id).state is TransferState.CONSUMED


def test_every_unusable_session_or_token_is_one_not_found_with_zero_mutation(rig: Rig) -> None:
    staged = _text(300)
    stranger = operator()
    cases: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    unknown = "grxfr_" + "u" * 24
    some_token = "grxtk_" + "0" * 64
    cases["unknown"] = (_reference(unknown, some_token), {})
    sid, tok = _finalized(rig, staged, key="foreign")
    cases["foreign_principal"] = (_reference(sid, tok), {"principal": stranger})
    sid, tok = _finalized(rig, staged, key="client", client=CLIENT_A)
    cases["other_client"] = (_reference(sid, tok), {"client": CLIENT_B})
    cases["remote_vs_local"] = (_reference(sid, tok), {})
    sid, tok = _finalized(rig, staged, key="local")
    cases["local_vs_remote"] = (_reference(sid, tok), {"client": CLIENT_A})
    cases["wrong_token"] = (_reference(sid, "grxtk_" + "f" * 64), {})
    open_id = _uploaded(rig, staged, key="open")
    cases["open_not_finalized"] = (_reference(open_id, some_token), {})
    sid, tok = _finalized(rig, staged, key="aborted")
    _ok(_abort(rig, sid))
    cases["aborted"] = (_reference(sid, tok), {})
    sid, tok = _finalized(rig, staged, key="expired")
    _expire(rig, sid)
    cases["expired"] = (_reference(sid, tok), {})
    sid, tok = _finalized(rig, staged, key="consumed")
    _ok(_publish(rig, _reference(sid, tok), key="consumer"))
    cases["consumed"] = (_reference(sid, tok), {})
    head = _ok(_publish(rig, {"format": "text", "body": "synthetic head"}, key="head"))
    rendered: dict[str, dict[str, Any]] = {}
    for name, (content, caller) in cases.items():
        before = _snapshot(rig)
        rendered[f"{name}/publish"] = _error(_publish(rig, content, key=f"pub-{name}", **caller))
        if "principal" not in caller:
            rendered[f"{name}/update"] = _error(
                _update(rig, head["report_id"], {"content": content}, key=f"upd-{name}", **caller)
            )
        assert _snapshot(rig) == before, name
    assert all(error == NOT_FOUND for error in rendered.values()), rendered
    # The owner's own client still consumes its session.
    sid, tok = _finalized(rig, staged, key="owner", client=CLIENT_A)
    assert _ok(_publish(rig, _reference(sid, tok), key="owner-pub", client=CLIENT_A))


def test_tampered_staging_at_consumption_is_internal_error_with_zero_mutation(rig: Rig) -> None:
    staged = _text(CHUNK + 10)
    session_id, token = _finalized(rig, staged, key="p")
    (chunk_file,) = [
        path
        for path in (rig.root / "transfer").rglob("*")
        if path.is_file() and "/01-" in str(path)
    ]
    chunk_file.chmod(0o600)
    chunk_file.write_bytes(b"x" * chunk_file.stat().st_size)
    before = _snapshot(rig)
    error = _error(_publish(rig, _reference(session_id, token), key="pub"))
    assert error["code"] == ErrorCode.INTERNAL_ERROR.value and error["safe_details"] == []
    assert _snapshot(rig) == before
    assert _consumed_row(rig, session_id).state is TransferState.FINALIZED


def test_consumption_without_staging_is_unsupported(scene: Scene, tmp_path: Path) -> None:
    full = _rig(scene, tmp_path)
    staged = _text(100)
    session_id, token = _finalized(full, staged, key="p")
    storeless = _rig(scene, tmp_path, staging=False)
    before = _snapshot(storeless)
    answer = _publish(storeless, _reference(session_id, token), key="pub")
    assert _error(answer)["code"] == ErrorCode.UNSUPPORTED.value
    assert _snapshot(storeless) == before


# ---- update consumes a transfer (T10) ----------------------------------------


def test_update_with_new_transfer_content_writes_a_content_version(rig: Rig) -> None:
    head = _ok(_publish(rig, {"format": "text", "body": "synthetic version one"}, key="v1"))
    staged = _text(CHUNK + 4096, seed=11)
    session_id, token = _finalized(rig, staged, key="u")
    answer = _ok(
        _update(rig, head["report_id"], {"content": _reference(session_id, token)}, key="u1")
    )
    print("TRANSFER_UPDATE_JSON", answer)
    assert answer["outcome"] == "applied" and answer["change_kind"] == "content"
    row = _consumed_row(rig, session_id)
    assert row.state is TransferState.CONSUMED
    assert row.consumed_content_id == answer["content_id"] != head["content"]["content_id"]
    assert _read_back(rig, head["report_id"], 2) == staged
    assert rig.staging is not None and not rig.staging.has_session(session_id)
    # A retry of the same update replays its original receipt.
    before = _snapshot(rig)
    again = _ok(
        _update(rig, head["report_id"], {"content": _reference(session_id, token)}, key="u1")
    )
    assert again == {**answer, "replayed": True}
    assert _snapshot(rig) == before
    reused = _update(
        rig,
        head["report_id"],
        {"content": _reference(session_id, token)},
        key="u2",
        expected_version=2,
    )
    assert _error(reused) == NOT_FOUND
    assert _snapshot(rig) == before


def test_update_with_the_heads_content_reuses_its_object(rig: Rig) -> None:
    staged = _text(3000, seed=12)
    first_id, first_token = _finalized(rig, staged, key="a")
    head = _ok(_publish(rig, _reference(first_id, first_token), key="v1"))
    head_content = head["content"]["content_id"]
    objects = rig.store.stored_object_ids() if rig.store is not None else ()
    # The same decoded content plus a title change: a metadata version reusing the object.
    same_id, same_token = _finalized(rig, staged, key="b")
    answer = _ok(
        _update(
            rig,
            head["report_id"],
            {"content": _reference(same_id, same_token), "title": "Synthetic retitled"},
            key="u1",
        )
    )
    assert answer["outcome"] == "applied" and answer["change_kind"] == "metadata"
    assert answer["content_id"] == head_content
    assert _consumed_row(rig, same_id).consumed_content_id == head_content
    assert (rig.store.stored_object_ids() if rig.store is not None else ()) == objects
    # The same content alone changes nothing: a no_op naming the head, still consumed.
    noop_id, noop_token = _finalized(rig, staged, key="c")
    noop = _ok(
        _update(
            rig,
            head["report_id"],
            {"content": _reference(noop_id, noop_token)},
            key="u2",
            expected_version=2,
        )
    )
    assert noop["outcome"] == "no_op" and noop["content_id"] == head_content
    assert _consumed_row(rig, noop_id).state is TransferState.CONSUMED
    assert _consumed_row(rig, noop_id).consumed_content_id == head_content


def test_a_refused_update_after_the_claim_leaves_the_session_finalized(rig: Rig) -> None:
    head = _ok(_publish(rig, {"format": "text", "body": "synthetic head"}, key="v1"))
    staged = _text(2000, seed=13)
    session_id, token = _finalized(rig, staged, key="u")
    before = _snapshot(rig)
    stale = _update(
        rig,
        head["report_id"],
        {"content": _reference(session_id, token)},
        key="u1",
        expected_version=7,
    )
    assert _details(stale, ErrorCode.CONFLICT) == ["stale_version"]
    missing = _update(rig, "grpt_" + "m" * 24, {"content": _reference(session_id, token)}, key="u2")
    assert _details(missing, ErrorCode.NOT_FOUND) == ["artifact_id"]
    assert _snapshot(rig) == before
    assert _ok(
        _update(rig, head["report_id"], {"content": _reference(session_id, token)}, key="u3")
    )
    assert _consumed_row(rig, session_id).state is TransferState.CONSUMED


# ---- the token is stored nowhere; search_text is decoded-only ------------------


def test_the_token_is_in_no_receipt_row_audit_event_or_digest_input(rig: Rig) -> None:
    head = _ok(_publish(rig, {"format": "text", "body": "synthetic head"}, key="v1"))
    staged = _text(1500, seed=14)
    pid, ptoken = _finalized(rig, staged, key="p")
    uid, utoken = _finalized(rig, _text(1600, seed=15), key="u")
    _ok(_publish(rig, _reference(pid, ptoken), key="pub"))
    _ok(_update(rig, head["report_id"], {"content": _reference(uid, utoken)}, key="upd"))
    # Every string the fake world holds: sessions, ledger, versions, receipts
    # (publish and update) and the audit events.
    dumped = "\n".join(_strings(rig.scene.world))
    # Positive controls: the walk reaches the sessions, the receipts and the audit trail.
    assert pid in dumped and uid in dumped and head["receipt_id"] in dumped
    assert rig.scene.world.audit and rig.scene.world.audit[-1].audit_id in dumped
    for token in (ptoken, utoken):
        assert token not in dumped
        assert token[len("grxtk_") :] not in dumped
    # The intent digest binds the session and the token's digest, never the token.
    command = PublishGeneralReport(
        title="Synthetic", content=_reference(pid, ptoken), idempotency_key="k"
    )
    request = publication_request(command, max_decoded=MAX_DECODED_CONTENT_BYTES)
    assert request.content is TRANSFER_CONTENT_DEFERRED
    assert request.content_source is not None
    assert request.content_source.session_id == pid
    assert request.content_source.content_token_sha256 == content_token_digest(ptoken)
    assert ptoken not in repr(request)
    other = publication_request(
        PublishGeneralReport(
            title="Synthetic", content=_reference(pid, "grxtk_" + "1" * 64), idempotency_key="k"
        ),
        max_decoded=MAX_DECODED_CONTENT_BYTES,
    )
    assert other.intent_digest != request.intent_digest
    decoded = content_from_staged(
        ContentFormat.TEXT, ContentEncoding.IDENTITY, staged, max_decoded=MAX_DECODED_CONTENT_BYTES
    )
    assert dataclasses.replace(request, content=decoded).intent_digest == request.intent_digest
    update = update_request(
        UpdateGeneralReport(
            report_id=head["report_id"],
            expected_version=1,
            patch={"content": _reference(uid, utoken)},
            change_reason="Synthetic.",
            idempotency_key="k",
        ),
        max_decoded=MAX_DECODED_CONTENT_BYTES,
    )
    assert update.content_source is not None
    assert update.content_source.content_token_sha256 == content_token_digest(utoken)


def test_search_text_comes_from_the_decoded_content_only(rig: Rig) -> None:
    raw = ("curlew estuary survey notes " * 400).encode()
    gz = _gz(raw)
    encoded = _b64(gz)
    candidates = [word for word in re.findall(r"[a-z]{6,}", encoded) if word not in raw.decode()]
    assert candidates, "the synthetic Base64 holds a token-like lowercase word"
    word = candidates[0]
    session_id, token = _finalized(rig, gz, key="g", encoding="gzip+base64")
    report = _ok(_publish(rig, _reference(session_id, token), key="pub"))
    assert report["content"]["decoded_sha256"] == _sha(raw)

    def found(query: str) -> list[str]:
        answer = _ok(
            _invoke(rig, Capability.REPORTS_SEARCH, {"plane": "standalone", "query": query})
        )
        return [item["report_id"] for item in answer["items"]]

    assert found("curlew") == [report["report_id"]]
    assert found(word) == []
    assert _read_back(rig, report["report_id"], 1, "original") == gz


# ---- T12: the permit -----------------------------------------------------------


def test_a_transfer_sourced_publish_waits_for_the_decode_permit(rig: Rig) -> None:
    session_id, token = _finalized(rig, _text(700), key="p")
    permit = service_module._REPORT_CONTENT_DECODE_PERMIT
    assert permit.acquire(timeout=5)
    published: dict[str, Any] = {}
    try:
        worker = threading.Thread(
            target=lambda: published.update(_publish(rig, _reference(session_id, token), key="k"))
        )
        worker.start()
        worker.join(timeout=0.5)
        assert worker.is_alive() and not published
    finally:
        permit.release()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert _ok(published)["replayed"] is False


# ---- large transfers through the service, measured ------------------------------


def _measured_call(
    rig: Rig, peaks: dict[str, int], name: str, capability: Capability, payload: dict[str, Any]
) -> dict[str, Any]:
    """One call, its tracemalloc peaks recorded apart: `normalize` (the transport
    adapter, `<name>_normalize`) and `ApplicationService.invoke` (`<name>`)."""
    (purpose,) = permitted_purposes(capability)
    wire = {
        "request_id": f"req-{capability.value}",
        "purpose": purpose.value,
        "principal_id": rig.scene.principal.principal_id,
        "requested_at": "2026-11-07T12:00:00.000Z",
        "payload": payload,
    }

    def peak_of(call: Callable[[], Any]) -> tuple[Any, int]:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        result = call()
        return result, tracemalloc.get_traced_memory()[1] - base

    (metadata, command), normalized = peak_of(lambda: normalize(capability.value, wire))
    envelope, invoked = peak_of(
        lambda: rig.service.invoke(
            metadata, command, principal=rig.scene.principal, transport=CaptureTransport.LOCAL
        )
    )
    for key, value in ((f"{name}_normalize", normalized), (name, invoked)):
        peaks[key] = max(peaks.get(key, 0), value)
    return _ok(envelope.model_dump(mode="json"))


def _through_the_service(rig: Rig, staged: bytes, *, fmt: str, label: str) -> None:
    peaks: dict[str, int] = {}
    timings: dict[str, float] = {}
    session_id = str(_ok(_begin(rig, staged, fmt=fmt, key=f"big-{label}"))["session_id"])
    tracemalloc.start()
    try:
        started = time.perf_counter()
        for sequence, piece in enumerate(_pieces(staged)):
            _measured_call(
                rig,
                peaks,
                "append",
                Capability.REPORTS_TRANSFER_APPEND,
                {
                    "session_id": session_id,
                    "sequence": sequence,
                    "chunk": _b64(piece),
                    "chunk_sha256": _sha(piece),
                },
            )
        timings["upload"] = time.perf_counter() - started
        started = time.perf_counter()
        token = _measured_call(
            rig, peaks, "finalize", Capability.REPORTS_TRANSFER_FINALIZE, {"session_id": session_id}
        )["content_token"]
        timings["finalize"] = time.perf_counter() - started
        started = time.perf_counter()
        report = _measured_call(
            rig,
            peaks,
            "publish",
            Capability.REPORTS_PUBLISH,
            {
                "title": "Synthetic large transfer",
                "content": _reference(session_id, token),
                "idempotency_key": f"pub-{label}",
            },
        )
        timings["publish"] = time.perf_counter() - started
        started = time.perf_counter()
        digest = hashlib.sha256()
        total = 0
        offset: int | None = 0
        index = 0
        while offset is not None:
            answer = _measured_call(
                rig,
                peaks,
                "read_chunk",
                Capability.REPORTS_TRANSFER_READ_CHUNK,
                {"report_id": report["report_id"], "version_number": 1, "offset": offset},
            )
            chunk = base64.b64decode(answer["chunk"])
            assert chunk == staged[total : total + len(chunk)]
            digest.update(chunk)
            total += len(chunk)
            offset = answer["next_offset"]
            index += 1
        timings["read_back"] = time.perf_counter() - started
    finally:
        tracemalloc.stop()
    assert total == len(staged) and digest.hexdigest() == _sha(staged)
    assert index == len(_pieces(staged))
    assert report["content"]["decoded_sha256"] == _sha(staged)
    print(
        f"TRANSFER_MEASURE {label} bytes={len(staged)} chunks={index} "
        + " ".join(f"peak_{name}={value / MIB:.2f}MiB" for name, value in sorted(peaks.items()))
        + " "
        + " ".join(f"{name}={value:.2f}s" for name, value in timings.items())
    )
    # The ceilings bound the service (`invoke`); the transport's own
    # normalization peaks are recorded above and bounded only loosely here.
    assert peaks["append"] < CHUNK_PEAK_CEILING, peaks
    assert peaks["read_chunk"] < CHUNK_PEAK_CEILING, peaks
    assert peaks["finalize"] < WHOLE_PEAK_CEILING, peaks
    assert peaks["publish"] < WHOLE_PEAK_CEILING, peaks
    assert all(peaks[f"{name}_normalize"] < 32 * MIB for name in ("append", "publish")), peaks


def test_a_600_kib_markdown_transfer_round_trips_through_the_service(rig: Rig) -> None:
    staged = _text(600 * 1024, seed=21)
    assert len(staged) > 512 * 1024
    _through_the_service(rig, staged, fmt="markdown", label="600KiB-markdown")


def _random_ascii(size: int, seed: int) -> bytes:
    """Seeded random printable ASCII: incompressible enough that gzip cannot make it fit."""
    import random

    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    alphabet = bytes(range(0x21, 0x7F)) + b" \n"
    return bytes(rng.choices(alphabet, k=size))


@pytest.mark.slow
def test_a_16_mib_identity_text_transfer_round_trips_through_the_service(rig: Rig) -> None:
    staged = _random_ascii(16 * MIB, seed=16)
    assert len(staged) == 16_777_216
    # Incompressible enough that no single gzip request could carry it.
    assert len(_gz(staged)) > MAX_REQUEST_BYTES
    _through_the_service(rig, staged, fmt="text", label="16MiB-text")


def test_the_staging_adapter_is_the_one_the_rig_composes(rig: Rig) -> None:
    assert isinstance(rig.staging, FilesystemReportTransferStaging)
