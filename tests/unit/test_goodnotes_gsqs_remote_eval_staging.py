"""Filesystem raster staging: copy-not-symlink authorized PNG seal."""

from __future__ import annotations

import json
import zlib
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ERROR_RASTER_INTEGRITY_FAILURE,
    ERROR_STATE_INTEGRITY_FAILURE,
    SCHEMA_SESSION_MANIFEST_V1,
    SCHEMA_STATE_V1,
    ManifestCase,
    RemoteEvalError,
    RemoteEvalMode,
    RemoteEvalSessionState,
    SessionManifest,
    SessionState,
    build_remote_eval_session,
    case_order_sha256,
    initial_repetition_progress,
    remote_eval_canonical_dumps,
    remote_eval_canonical_sha256,
)
from my_pa.application.goodnotes_gsqs_remote_eval_staging import FilesystemRasterStaging
from my_pa.application.goodnotes_gsqs_remote_eval_storage import FilesystemRemoteEvalStore
from my_pa.domain.goodnotes.page_crop import PNG_MAGIC, grayscale_from_png

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _hex(label: str) -> str:
    return remote_eval_canonical_sha256(label)


def _gray_png(marker: int) -> bytes:
    width = height = 8
    pixels = bytes((marker + index) % 256 for index in range(width * height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return len(data).to_bytes(4, "big") + tag + data + crc.to_bytes(4, "big")

    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    raw = b"".join(b"\x00" + pixels[row * width : (row + 1) * width] for row in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _cases_from_pngs(pngs: list[bytes]) -> tuple[ManifestCase, ...]:
    return tuple(
        ManifestCase(
            ordinal=index,
            case_id=f"syn-b-{index:03d}",
            content_sha256=sha256(payload).hexdigest(),
            byte_length=len(payload),
            staged_filename=f"syn-b-{index:03d}.png",
        )
        for index, payload in enumerate(pngs, start=1)
    )


def _prepared_session(
    tmp_path: Path, pngs: list[bytes]
) -> tuple[FilesystemRemoteEvalStore, FilesystemRasterStaging, object, SessionManifest, Path]:
    state_root = tmp_path / "state"
    source_root = tmp_path / "source"
    source_root.mkdir()
    cases = _cases_from_pngs(pngs)
    for case, payload in zip(cases, pngs, strict=True):
        (source_root / case.staged_filename).write_bytes(payload)
    session = build_remote_eval_session(
        session_id="sess-1",
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
        case_count=len(cases) if len(cases) != CASES_PER_REPETITION else CASES_PER_REPETITION,
        case_order_sha256=case_order_sha256(tuple(case.case_id for case in cases)),
        analyzer_id="chatllm-goodnotes-semantic",
        analyzer_version="sit-1.0",
        semantic_prompt_sha256=_hex("semantic"),
        conversation_prompt_sha256=_hex("conversation"),
        model_selection_label="route-llm",
    )
    manifest = SessionManifest(
        schema_version=SCHEMA_SESSION_MANIFEST_V1,
        session_id=session.session_id,
        session_identity_sha256=session.session_identity_sha256,
        cases=cases,
    )
    state = SessionState(
        schema_version=SCHEMA_STATE_V1,
        session_id=session.session_id,
        revision=1,
        state=RemoteEvalSessionState.PREPARED,
        active_repetition=None,
        next_case_ordinal=1,
        active_lease=None,
        repetitions=initial_repetition_progress(),
        captures_accepted=0,
        capture_export_sha256=None,
        last_event_id="evt-1",
        updated_at=NOW,
        blocked_reason_code=None,
        terminal_reason_code=None,
    )
    store = FilesystemRemoteEvalStore(state_root)
    store.create_session(session, manifest, state)
    staging = FilesystemRasterStaging(state_root, source_root)
    return store, staging, session, manifest, source_root


def _valid_pngs() -> list[bytes]:
    return [_gray_png(index) for index in range(1, CASES_PER_REPETITION + 1)]


def test_valid_73_member_corpus_seals_and_destination_shas_match(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, _source = _prepared_session(tmp_path, pngs)
    sealed = staging.seal_authorized_rasters(session, manifest)
    assert sealed.ok is True
    assert sealed.manifest is manifest
    rasters = tmp_path / "state" / "sessions" / "sess-1" / "rasters"
    assert rasters.is_dir()
    assert not rasters.is_symlink()
    for case, payload in zip(manifest.cases, pngs, strict=True):
        dest = rasters / case.staged_filename
        written = dest.read_bytes()
        assert sha256(written).hexdigest() == case.content_sha256
        assert len(written) == case.byte_length
        assert written == payload


def test_missing_raster_fails(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, source = _prepared_session(tmp_path, pngs)
    (source / "syn-b-001.png").unlink()
    with pytest.raises(RemoteEvalError) as exc:
        staging.seal_authorized_rasters(session, manifest)
    assert exc.value.code == ERROR_RASTER_INTEGRITY_FAILURE
    assert not (tmp_path / "state" / "sessions" / "sess-1" / "rasters").exists()


def test_extra_raster_fails(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, source = _prepared_session(tmp_path, pngs)
    (source / "extra.png").write_bytes(_gray_png(99))
    with pytest.raises(RemoteEvalError) as exc:
        staging.seal_authorized_rasters(session, manifest)
    assert exc.value.code == ERROR_RASTER_INTEGRITY_FAILURE


def test_wrong_sha_fails(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, source = _prepared_session(tmp_path, pngs)
    (source / "syn-b-001.png").write_bytes(_gray_png(200))
    with pytest.raises(RemoteEvalError) as exc:
        staging.seal_authorized_rasters(session, manifest)
    assert exc.value.code == ERROR_RASTER_INTEGRITY_FAILURE


def test_bad_png_fails(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, source = _prepared_session(tmp_path, pngs)
    (source / "syn-b-002.png").write_bytes(b"not-a-png")
    with pytest.raises(RemoteEvalError) as exc:
        staging.seal_authorized_rasters(session, manifest)
    assert exc.value.code == ERROR_RASTER_INTEGRITY_FAILURE
    truncated = PNG_MAGIC + b"\x00\x01"
    (source / "syn-b-002.png").write_bytes(truncated)
    with pytest.raises(RemoteEvalError) as truncated_exc:
        staging.seal_authorized_rasters(session, manifest)
    assert truncated_exc.value.code == ERROR_RASTER_INTEGRITY_FAILURE


def test_symlink_source_file_fails(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, source = _prepared_session(tmp_path, pngs)
    target = tmp_path / "elsewhere.png"
    target.write_bytes((source / "syn-b-001.png").read_bytes())
    (source / "syn-b-001.png").unlink()
    (source / "syn-b-001.png").symlink_to(target)
    with pytest.raises(RemoteEvalError) as exc:
        staging.seal_authorized_rasters(session, manifest)
    assert exc.value.code in {ERROR_RASTER_INTEGRITY_FAILURE, ERROR_STATE_INTEGRITY_FAILURE}


def test_symlink_destination_fails(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, _source = _prepared_session(tmp_path, pngs)
    session_dir = tmp_path / "state" / "sessions" / "sess-1"
    decoy = tmp_path / "decoy-rasters"
    decoy.mkdir()
    (session_dir / "rasters").symlink_to(decoy)
    with pytest.raises(RemoteEvalError) as exc:
        staging.seal_authorized_rasters(session, manifest)
    assert exc.value.code in {ERROR_RASTER_INTEGRITY_FAILURE, ERROR_STATE_INTEGRITY_FAILURE}


def test_traversal_in_filename_fails(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, _source = _prepared_session(tmp_path, pngs)
    cases = list(manifest.cases)
    cases[0] = ManifestCase(
        ordinal=1,
        case_id="syn-b-001",
        content_sha256=cases[0].content_sha256,
        byte_length=cases[0].byte_length,
        staged_filename="../escape.png",
    )
    bad = SessionManifest(
        schema_version=manifest.schema_version,
        session_id=manifest.session_id,
        session_identity_sha256=manifest.session_identity_sha256,
        cases=tuple(cases),
    )
    with pytest.raises(RemoteEvalError) as exc:
        staging.seal_authorized_rasters(session, bad)
    assert exc.value.code == ERROR_RASTER_INTEGRITY_FAILURE


def test_duplicate_case_in_manifest_fails(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, _source = _prepared_session(tmp_path, pngs)
    cases = list(manifest.cases)
    cases[1] = ManifestCase(
        ordinal=2,
        case_id="syn-b-001",
        content_sha256=cases[1].content_sha256,
        byte_length=cases[1].byte_length,
        staged_filename=cases[1].staged_filename,
    )
    bad = SessionManifest(
        schema_version=manifest.schema_version,
        session_id=manifest.session_id,
        session_identity_sha256=manifest.session_identity_sha256,
        cases=tuple(cases),
    )
    with pytest.raises(RemoteEvalError) as exc:
        staging.seal_authorized_rasters(session, bad)
    assert exc.value.code == ERROR_RASTER_INTEGRITY_FAILURE


def test_destination_sha_mismatch_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import my_pa.application.goodnotes_gsqs_remote_eval_staging as staging_mod

    pngs = _valid_pngs()
    _store, staging, session, manifest, _source = _prepared_session(tmp_path, pngs)
    real = staging_mod.atomic_write_bytes

    def corrupt(path: Path, data: bytes) -> None:
        real(path, data + b"\x00")

    monkeypatch.setattr(staging_mod, "atomic_write_bytes", corrupt)
    with pytest.raises(RemoteEvalError) as exc:
        staging.seal_authorized_rasters(session, manifest)
    assert exc.value.code == ERROR_RASTER_INTEGRITY_FAILURE
    assert not (tmp_path / "state" / "sessions" / "sess-1" / "rasters").exists()


def test_atomic_seal_does_not_leave_usable_rasters_on_failure(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    _store, staging, session, manifest, source = _prepared_session(tmp_path, pngs)
    (source / "syn-b-073.png").unlink()
    with pytest.raises(RemoteEvalError):
        staging.seal_authorized_rasters(session, manifest)
    session_dir = tmp_path / "state" / "sessions" / "sess-1"
    assert not (session_dir / "rasters").exists()
    leftovers = [path for path in session_dir.iterdir() if path.name.startswith(".rasters-tmp-")]
    assert leftovers == []


def test_source_path_does_not_appear_in_manifest_json(tmp_path: Path) -> None:
    pngs = _valid_pngs()
    store, staging, session, manifest, source = _prepared_session(tmp_path, pngs)
    sealed = staging.seal_authorized_rasters(session, manifest)
    dumped = remote_eval_canonical_dumps(sealed.manifest)
    assert str(source) not in dumped
    on_disk = (tmp_path / "state" / "sessions" / "sess-1" / "manifest.json").read_text(
        encoding="utf-8"
    )
    assert str(source) not in on_disk
    assert "gold" not in json.loads(on_disk)
    _ = store


def test_grayscale_from_png_is_used() -> None:
    import my_pa.application.goodnotes_gsqs_remote_eval_staging as staging

    assert staging.grayscale_from_png is grayscale_from_png
    assert staging.PNG_MAGIC == PNG_MAGIC
    source = Path("src/my_pa/application/goodnotes_gsqs_remote_eval_staging.py").read_text(
        encoding="utf-8"
    )
    assert "from my_pa.domain.goodnotes.page_crop import" in source
    assert "grayscale_from_png" in source
    assert "pypdfium2" not in source
    assert "os.symlink" not in source
