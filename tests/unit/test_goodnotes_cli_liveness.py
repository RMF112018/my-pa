from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import pytest
from apps.cli import goodnotes as cli

import my_pa.bootstrap.goodnotes as bootstrap
from my_pa.domain.goodnotes.liveness import GoodNotesSourceLiveness
from my_pa.domain.goodnotes.models import ReconciliationReceipt

PRINCIPAL = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
WHEN = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = WHEN

    def __call__(self) -> datetime:
        return self.now


class MemoryRepository:
    def __init__(self) -> None:
        self.receipts: dict[tuple[str, str], ReconciliationReceipt] = {}

    def receipt(self, principal_id: str, idempotency_key: str) -> ReconciliationReceipt | None:
        return self.receipts.get((principal_id, idempotency_key))

    def require_admitted_sources(self, principal_id: str, bindings: tuple[object, ...]) -> None:
        assert principal_id == PRINCIPAL
        assert bindings

    def store_reconciliation(self, **values: object) -> ReconciliationReceipt:
        receipt = values["receipt"]
        assert isinstance(receipt, ReconciliationReceipt)
        self.receipts[(receipt.principal_id, receipt.idempotency_key)] = receipt
        return receipt


class Context:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


class Engine:
    def __init__(self) -> None:
        self.connections = 0

    def connect(self) -> Context:
        self.connections += 1
        return Context()

    def begin(self) -> Context:
        self.connections += 1
        return Context()

    def dispose(self) -> None:
        return None


def _source(tmp_path: Path, *, create_page: bool = True) -> Path:
    page = tmp_path / "notebook/page.pdf"
    page.parent.mkdir()
    content = b"%PDF-1.7\nsynthetic\n%%EOF\n"
    if create_page:
        page.write_bytes(content)
    (tmp_path / "goodnotes-manifest.json").write_text(
        json.dumps(
            {
                "schema": "my-pa.goodnotes-local-source.v1",
                "pages": [
                    {
                        "principal_id": PRINCIPAL,
                        "source_id": "src_aaaaaaaaaaaaaaaaaaaaaaaa",
                        "source_object_id": "obj_aaaaaaaaaaaaaaaaaaaaaaaa",
                        "source_version_id": "ver_aaaaaaaaaaaaaaaaaaaaaaaa",
                        "page_number": 1,
                        "observed_at": WHEN.isoformat(),
                        "relative_path": "notebook/page.pdf",
                        "content_sha256": hashlib.sha256(content).hexdigest(),
                        "media_type": "application/pdf",
                    }
                ],
            }
        )
    )
    return page


def _runtime(tmp_path: Path, clock: Clock) -> bootstrap.LocalGoodNotesRuntime:
    script = tmp_path / "ocr.py"
    script.write_text(
        "import json, sys\nsys.stdin.buffer.read()\njson.dump({'regions': []}, sys.stdout)\n"
    )
    return bootstrap.compose_local_goodnotes_runtime(
        admitted_root=tmp_path,
        manifest_relative_path=PurePosixPath("goodnotes-manifest.json"),
        ocr_command=(sys.executable, str(script)),
        ocr_root=Path(sys.executable).resolve().parent,
        ocr_name="synthetic-ocr",
        ocr_version="1",
        source_root_id="synthetic-goodnotes",
        clock=clock,
    )


def _refused(
    runtime: bootstrap.LocalGoodNotesRuntime, receipts: object, *, match: str | None = None
) -> Engine:
    engine = Engine()
    with pytest.raises(ValueError, match=match):
        runtime.reconcile(
            engine=engine,  # type: ignore[arg-type]
            principal_id=PRINCIPAL,
            idempotency_key="liveness-refusal",
            liveness_receipts=receipts,  # type: ignore[arg-type]
        )
    assert engine.connections == 0
    return engine


def test_composed_runtime_refuses_missing_receipts_before_database_or_ocr(tmp_path: Path) -> None:
    _source(tmp_path)
    _refused(_runtime(tmp_path, Clock()), None)


def test_composed_runtime_refuses_stale_and_reappeared_server_receipts(tmp_path: Path) -> None:
    page = _source(tmp_path)
    clock = Clock()
    runtime = _runtime(tmp_path, clock)
    available = runtime.observe_liveness(principal_id=PRINCIPAL)
    page.unlink()
    clock.now += timedelta(seconds=301)
    stale = runtime.observe_liveness(
        principal_id=PRINCIPAL,
        previous=available,
        maximum_staleness=timedelta(minutes=5),
    )
    assert stale[0].state is GoodNotesSourceLiveness.STALE
    _refused(runtime, stale)
    _refused(runtime, available, match="not issued")

    page.write_bytes(b"%PDF-1.7\nreplacement\n%%EOF\n")
    clock.now += timedelta(seconds=1)
    reappeared = runtime.observe_liveness(principal_id=PRINCIPAL, previous=stale)
    assert reappeared[0].state is GoodNotesSourceLiveness.REAPPEARED
    _refused(runtime, reappeared)


def test_composed_runtime_refuses_forged_mismatched_and_expired_receipts(tmp_path: Path) -> None:
    page = _source(tmp_path)
    clock = Clock()
    runtime = _runtime(tmp_path, clock)
    receipts = runtime.observe_liveness(principal_id=PRINCIPAL)
    forged = tuple(replace(receipt) for receipt in receipts)
    _refused(runtime, forged, match="not issued")

    page.write_bytes(b"%PDF-1.7\nchanged\n%%EOF\n")
    _refused(runtime, receipts, match="does not match")

    page.write_bytes(b"%PDF-1.7\nsynthetic\n%%EOF\n")
    clock.now += timedelta(seconds=301)
    _refused(runtime, receipts, match="stale")


def test_composed_runtime_accepts_current_exact_runtime_issued_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(tmp_path)
    runtime = _runtime(tmp_path, Clock())
    receipts = runtime.observe_liveness(principal_id=PRINCIPAL)
    repository = MemoryRepository()
    monkeypatch.setattr(bootstrap, "PostgresGoodNotesRepository", lambda connection: repository)
    engine = Engine()
    result = runtime.reconcile(
        engine=engine,  # type: ignore[arg-type]
        principal_id=PRINCIPAL,
        idempotency_key="current-exact",
        liveness_receipts=receipts,
    )
    assert result.principal_id == PRINCIPAL
    assert engine.connections == 2


def test_real_cli_composition_refuses_a_missing_source_before_engine_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _source(tmp_path, create_page=False)
    monkeypatch.setenv("MY_PA_GOODNOTES_ROOT", str(tmp_path))
    monkeypatch.setenv("MY_PA_GOODNOTES_OCR_ROOT", str(Path(sys.executable).parent))
    monkeypatch.setenv("MY_PA_GOODNOTES_OCR_EXECUTABLE", sys.executable)
    monkeypatch.setattr(cli, "_operator_principal_id", lambda supplied: PRINCIPAL)
    monkeypatch.setattr(cli, "_engine", lambda: pytest.fail("database was reached"))
    assert cli.main(["reconcile", "--idempotency-key", "missing-source"]) == cli.EXIT_REFUSED
    assert "missing" in capsys.readouterr().err


def test_real_cli_composition_uses_a_current_runtime_issued_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _source(tmp_path)
    script = tmp_path / "cli-ocr.py"
    script.write_text(
        "import json, sys\nsys.stdin.buffer.read()\njson.dump({'regions': []}, sys.stdout)\n"
    )
    monkeypatch.setenv("MY_PA_GOODNOTES_ROOT", str(tmp_path))
    monkeypatch.setenv("MY_PA_GOODNOTES_OCR_ROOT", str(Path(sys.executable).resolve().parent))
    monkeypatch.setenv("MY_PA_GOODNOTES_OCR_EXECUTABLE", sys.executable)
    monkeypatch.setenv("MY_PA_GOODNOTES_OCR_ARGUMENTS_JSON", json.dumps([str(script)]))
    monkeypatch.setattr(cli, "_operator_principal_id", lambda supplied: PRINCIPAL)
    monkeypatch.setattr(cli, "_engine", Engine)
    repository = MemoryRepository()
    monkeypatch.setattr(bootstrap, "PostgresGoodNotesRepository", lambda connection: repository)

    assert cli.main(["reconcile", "--idempotency-key", "cli-current"]) == cli.EXIT_OK
    output = capsys.readouterr().out
    assert "pages 1" in output
    assert "replayed false" in output
