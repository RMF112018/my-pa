"""Filesystem remote-eval store: atomic JSON, recovery, and export."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs_b0_mcp import CAPTURE_SCHEMA_VERSION
from my_pa.application.goodnotes_gsqs_harness import INTERCHANGE_SCHEMA_VERSION
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_NO_ACTIVE_SESSION,
    ERROR_STATE_INTEGRITY_FAILURE,
    SCHEMA_CAPTURE_ENTRY_V1,
    SCHEMA_SESSION_MANIFEST_V1,
    SCHEMA_STATE_V1,
    SCHEMA_TERMINAL_RECEIPT_V1,
    CaptureEntry,
    ManifestCase,
    RemoteEvalError,
    RemoteEvalMode,
    RemoteEvalSessionState,
    SessionManifest,
    SessionState,
    TerminalReceipt,
    build_remote_eval_session,
    case_order_sha256,
    compute_capture_identity_sha256,
    compute_receipt_sha256,
    initial_repetition_progress,
    remote_eval_canonical_sha256,
)
from my_pa.application.goodnotes_gsqs_remote_eval_storage import (
    FilesystemRemoteEvalStore,
    atomic_write_json,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
SEGMENTS: tuple[dict[str, object], ...] = (
    {
        "kind": "SOURCE_CONTEXT",
        "geometry": {"x_min": 0.08, "y_min": 0.08, "width": 0.84, "height": 0.10},
    },
)


def _hex(label: str) -> str:
    return remote_eval_canonical_sha256(label)


def _cases() -> tuple[ManifestCase, ...]:
    return tuple(
        ManifestCase(
            ordinal=index,
            case_id=f"syn-b-{index:03d}",
            content_sha256=_hex(f"syn-b-{index:03d}"),
            byte_length=256,
            staged_filename=f"syn-b-{index:03d}.png",
        )
        for index in range(1, CASES_PER_REPETITION + 1)
    )


def _session(*, session_id: str = "sess-1") -> object:
    return build_remote_eval_session(
        session_id=session_id,
        mode=RemoteEvalMode.SYNTHETIC_CANARY,
        authorization_id="auth-1",
        principal_id="principal-1",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=2),
        repository_owner="RMF112018",
        repository_name="my-pa",
        repository_commit_sha="abc123",
        repository_tree_sha="def456",
        evaluator_id="goodnotes-gsqs-independent",
        evaluator_version="1.1",
        evaluator_behavior_sha256=_hex("eval"),
        corpus_version="synthetic-b-1",
        public_manifest_sha256=_hex("public"),
        combined_identity_sha256=_hex("combined"),
        case_count=CASES_PER_REPETITION,
        case_order_sha256=case_order_sha256(tuple(case.case_id for case in _cases())),
        analyzer_id="chatllm-goodnotes-semantic",
        analyzer_version="sit-1.0",
        semantic_prompt_sha256=_hex("semantic"),
        conversation_prompt_sha256=_hex("conversation"),
        model_selection_label="route-llm",
    )


def _manifest(session: object) -> SessionManifest:
    return SessionManifest(
        schema_version=SCHEMA_SESSION_MANIFEST_V1,
        session_id=session.session_id,  # type: ignore[attr-defined]
        session_identity_sha256=session.session_identity_sha256,  # type: ignore[attr-defined]
        cases=_cases(),
    )


def _state(session: object, **changes: object) -> SessionState:
    kwargs: dict[str, object] = {
        "schema_version": SCHEMA_STATE_V1,
        "session_id": session.session_id,  # type: ignore[attr-defined]
        "revision": 1,
        "state": RemoteEvalSessionState.PREPARED,
        "active_repetition": None,
        "next_case_ordinal": 1,
        "active_lease": None,
        "repetitions": initial_repetition_progress(),
        "captures_accepted": 0,
        "capture_export_sha256": None,
        "last_event_id": "evt-1",
        "updated_at": NOW,
        "blocked_reason_code": None,
        "terminal_reason_code": None,
    }
    kwargs.update(changes)
    return SessionState(**kwargs)  # type: ignore[arg-type]


def _capture(session: object, *, ordinal: int = 1, lease_id: str = "lease-1") -> CaptureEntry:
    case = _cases()[ordinal - 1]
    entry = CaptureEntry(
        schema_version=SCHEMA_CAPTURE_ENTRY_V1,
        session_id=session.session_id,  # type: ignore[attr-defined]
        session_identity_sha256=session.session_identity_sha256,  # type: ignore[attr-defined]
        repetition=1,
        case_id=case.case_id,
        ordinal=ordinal,
        content_sha256=case.content_sha256,
        corpus_version="synthetic-b-1",
        public_manifest_sha256=_hex("public"),
        combined_identity_sha256=_hex("combined"),
        analyzer_id="chatllm-goodnotes-semantic",
        analyzer_version="sit-1.0",
        semantic_prompt_sha256=_hex("semantic"),
        conversation_prompt_sha256=_hex("conversation"),
        model_selection_label="route-llm",
        captured_at=NOW,
        lease_id=lease_id,
        idempotency_digest=_hex(f"idem-{ordinal}"),
        segments=SEGMENTS,
        capture_identity_sha256="0" * 64,
    )
    from dataclasses import replace

    return replace(entry, capture_identity_sha256=compute_capture_identity_sha256(entry))


def _receipt(session: object) -> TerminalReceipt:
    from dataclasses import replace

    receipt = TerminalReceipt(
        schema_version=SCHEMA_TERMINAL_RECEIPT_V1,
        session_id=session.session_id,  # type: ignore[attr-defined]
        session_identity_sha256=session.session_identity_sha256,  # type: ignore[attr-defined]
        terminal_state=RemoteEvalSessionState.ABORTED,
        terminal_at=NOW,
        manifest_sha256=_hex("manifest"),
        final_state_sha256=_hex("state"),
        disclosure_journal_sha256=None,
        disclosure_counts={"disclosed": 0, "not_disclosed": 0, "started": 0},
        repetition_capture_exports=((1, None), (2, None), (3, None)),
        total_captures=0,
        cleanup_retention={"deletion_performed": False, "records_retained": True},
        receipt_sha256="0" * 64,
    )
    return replace(receipt, receipt_sha256=compute_receipt_sha256(receipt))


def _seed(
    tmp_path: Path,
) -> tuple[FilesystemRemoteEvalStore, object, SessionManifest, SessionState]:
    store = FilesystemRemoteEvalStore(tmp_path)
    session = _session()
    manifest = _manifest(session)
    state = _state(session)
    store.create_session(session, manifest, state)
    return store, session, manifest, state


def test_create_and_load_session_manifest_state_round_trip(tmp_path: Path) -> None:
    store, session, manifest, state = _seed(tmp_path)
    assert store.load_session("sess-1") == session
    assert store.load_manifest("sess-1") == manifest
    assert store.load_state("sess-1") == state
    assert store.list_session_ids() == ("sess-1",)
    assert store.find_non_terminal_session_id() == "sess-1"


def test_corrupted_json_fails_closed(tmp_path: Path) -> None:
    store, _session_obj, _manifest, _state = _seed(tmp_path)
    path = tmp_path / "sessions" / "sess-1" / "state.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(RemoteEvalError) as exc:
        store.load_state("sess-1")
    assert exc.value.code == ERROR_STATE_INTEGRITY_FAILURE


def test_mismatched_session_identity_hash_fails_closed(tmp_path: Path) -> None:
    store, _session_obj, _manifest, _state = _seed(tmp_path)
    path = tmp_path / "sessions" / "sess-1" / "session.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["session_identity_sha256"] = "a" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RemoteEvalError) as exc:
        store.load_session("sess-1")
    assert exc.value.code == ERROR_STATE_INTEGRITY_FAILURE


def test_temporary_capture_is_not_accepted(tmp_path: Path) -> None:
    store, session, _manifest, _initial_state = _seed(tmp_path)
    in_progress = _state(
        session,
        state=RemoteEvalSessionState.IN_PROGRESS,
        active_repetition=1,
        revision=2,
    )
    store.save_state(in_progress)
    capture = _capture(session)
    repetition_dir = tmp_path / "sessions" / "sess-1" / "captures" / "repetition-001"
    repetition_dir.mkdir(parents=True)
    atomic_write_json(repetition_dir / ".tmp-001-syn-b-001.json", capture)
    assert store.load_capture("sess-1", 1, "syn-b-001") is None
    assert store.list_captures("sess-1", 1) == ()
    report = store.inspect_capture_recovery("sess-1")
    assert report.classification == "C"
    assert report.recoverable_forward is False
    assert not (repetition_dir / ".tmp-001-syn-b-001.json").exists()


def test_commit_capture_round_trip_and_load_by_lease(tmp_path: Path) -> None:
    store, session, _manifest, _initial_state = _seed(tmp_path)
    capture = _capture(session)
    next_state = _state(
        session,
        revision=2,
        state=RemoteEvalSessionState.IN_PROGRESS,
        active_repetition=1,
        next_case_ordinal=2,
        captures_accepted=1,
    )
    store.commit_capture(state=next_state, capture=capture)
    loaded = store.load_capture("sess-1", 1, "syn-b-001")
    assert loaded == capture
    assert store.load_capture_by_lease("sess-1", "lease-1") == capture
    assert store.list_captures("sess-1", 1) == (capture,)
    assert store.load_state("sess-1") == next_state


def test_conflicting_capture_files_fail_closed(tmp_path: Path) -> None:
    store, session, _manifest, _state = _seed(tmp_path)
    first = _capture(session, ordinal=1, lease_id="lease-a")
    second = _capture(session, ordinal=1, lease_id="lease-b")
    repetition_dir = tmp_path / "sessions" / "sess-1" / "captures" / "repetition-001"
    atomic_write_json(repetition_dir / "001-syn-b-001.json", first)
    atomic_write_json(repetition_dir / "002-syn-b-001.json", second)
    with pytest.raises(RemoteEvalError) as exc:
        store.load_capture("sess-1", 1, "syn-b-001")
    assert exc.value.code == ERROR_STATE_INTEGRITY_FAILURE
    with pytest.raises(RemoteEvalError) as inspect_exc:
        store.inspect_capture_recovery("sess-1")
    assert inspect_exc.value.code == ERROR_STATE_INTEGRITY_FAILURE


def test_terminal_receipt_round_trip(tmp_path: Path) -> None:
    store, session, _manifest, _state = _seed(tmp_path)
    receipt = _receipt(session)
    store.save_terminal_receipt(receipt)
    assert store.load_terminal_receipt("sess-1") == receipt


def test_restrictive_permissions_on_unix(tmp_path: Path) -> None:
    _store, _session_obj, _manifest, _state = _seed(tmp_path)
    session_dir = tmp_path / "sessions" / "sess-1"
    assert stat.S_IMODE(session_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((session_dir / "session.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((session_dir / "journal").stat().st_mode) == 0o700


def test_session_id_traversal_is_rejected(tmp_path: Path) -> None:
    store = FilesystemRemoteEvalStore(tmp_path)
    for session_id in ("../evil", "foo/bar", "foo\x00bar", "..", "", "sess/../x"):
        with pytest.raises(RemoteEvalError) as exc:
            store.load_session(session_id)
        assert exc.value.code in {ERROR_INTERNAL_FAIL_CLOSED, ERROR_STATE_INTEGRITY_FAILURE}


def test_symlink_state_root_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    session = _session()
    with pytest.raises(RemoteEvalError) as exc:
        store = FilesystemRemoteEvalStore(link)
        store.create_session(session, _manifest(session), _state(session))
    assert exc.value.code == ERROR_STATE_INTEGRITY_FAILURE


def test_symlink_session_directory_is_rejected(tmp_path: Path) -> None:
    store, _session_obj, _manifest, _state = _seed(tmp_path)
    session_dir = tmp_path / "sessions" / "sess-1"
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    backup = tmp_path / "backup"
    session_dir.rename(backup)
    session_dir.symlink_to(backup)
    with pytest.raises(RemoteEvalError) as exc:
        store.load_session("sess-1")
    assert exc.value.code == ERROR_STATE_INTEGRITY_FAILURE


def test_verified_forward_capture_advances_once_and_never_on_conflict(tmp_path: Path) -> None:
    store, session, _manifest_obj, _initial_state = _seed(tmp_path)
    in_progress = _state(
        session,
        revision=2,
        state=RemoteEvalSessionState.IN_PROGRESS,
        active_repetition=1,
        next_case_ordinal=1,
    )
    store.save_state(in_progress)
    capture = _capture(session)
    dest = tmp_path / "sessions" / "sess-1" / "captures" / "repetition-001" / "001-syn-b-001.json"
    atomic_write_json(dest, capture)
    report = store.inspect_capture_recovery("sess-1")
    assert report.classification == "B"
    assert report.recoverable_forward is True
    advanced = store.apply_verified_forward_capture("sess-1")
    assert advanced.next_case_ordinal == 2
    assert advanced.captures_accepted == 1
    again = store.inspect_capture_recovery("sess-1")
    assert again.classification == "A"
    with pytest.raises(RemoteEvalError) as exc:
        store.apply_verified_forward_capture("sess-1")
    assert exc.value.code == ERROR_STATE_INTEGRITY_FAILURE


def test_export_repetition_documents_shape_and_order(tmp_path: Path) -> None:
    store, session, _manifest, state = _seed(tmp_path)
    first = _capture(session, ordinal=1, lease_id="lease-1")
    second = _capture(session, ordinal=2, lease_id="lease-2")
    store.commit_capture(state=state, capture=second)
    store.commit_capture(state=state, capture=first)
    payload = store.export_repetition_documents("sess-1", 1)
    assert payload["schema_version"] == CAPTURE_SCHEMA_VERSION
    documents = payload["documents"]
    assert isinstance(documents, list)
    assert [item["case_id"] for item in documents] == ["syn-b-001", "syn-b-002"]
    for document in documents:
        assert document["schema_version"] == INTERCHANGE_SCHEMA_VERSION
        assert "gold" not in document
        assert "path" not in document
        assert "source_path" not in document
        assert set(document) >= {
            "analyzer_name",
            "analyzer_version",
            "case_id",
            "content_sha256",
            "corpus_version",
            "proposal_schema_version",
            "schema_version",
            "segments",
        }


def test_write_canonical_export_dir_filename_pattern(tmp_path: Path) -> None:
    store, session, _manifest, state = _seed(tmp_path)
    for index in range(1, CASES_PER_REPETITION + 1):
        store.commit_capture(
            state=state,
            capture=_capture(session, ordinal=index, lease_id=f"lease-{index}"),
        )
    dest = tmp_path / "export"
    written = store.write_canonical_export_dir("sess-1", dest)
    assert written == (dest / "repetition-001.json",)
    payload = json.loads((dest / "repetition-001.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == CAPTURE_SCHEMA_VERSION
    assert len(payload["documents"]) == CASES_PER_REPETITION
    spool_export = store.write_repetition_export("sess-1", 1)
    assert spool_export.name == "repetition-001.capture.json"


def test_remove_staged_rasters_keeps_records(tmp_path: Path) -> None:
    store, _session_obj, _manifest, _state = _seed(tmp_path)
    rasters = tmp_path / "sessions" / "sess-1" / "rasters"
    rasters.mkdir()
    (rasters / "syn-b-001.png").write_bytes(b"png")
    store.remove_staged_rasters("sess-1")
    assert not rasters.exists()
    assert (tmp_path / "sessions" / "sess-1" / "session.json").is_file()
    assert (tmp_path / "sessions" / "sess-1" / "journal").is_dir()
    missing = FilesystemRemoteEvalStore(tmp_path / "empty")
    with pytest.raises(RemoteEvalError) as exc:
        missing.remove_staged_rasters("sess-1")
    assert exc.value.code in {ERROR_NO_ACTIVE_SESSION, ERROR_INTERNAL_FAIL_CLOSED}


def test_storage_module_has_no_product_db_imports() -> None:
    source = Path("src/my_pa/application/goodnotes_gsqs_remote_eval_storage.py").read_text(
        encoding="utf-8"
    )
    for needle in ("sqlalchemy", "psycopg", "my_pa.application.service"):
        assert needle not in source
