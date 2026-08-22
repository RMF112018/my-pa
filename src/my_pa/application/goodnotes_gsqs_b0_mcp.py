"""RouteLLM-over-MCP GSQS B0 evaluation plane. Isolated from live NAS and HTTP.

Does not call production `goodnotes.propose`, does not import RouteLLM HTTP, and
does not sit in the evaluator implementation digest.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from my_pa.application.goodnotes_gsqs_live_b0 import (
    AnalyzerCaseInput,
    B0Census,
    B0CensusMember,
    ExecutionAuthorization,
    FrozenAnalyzerConfig,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesPageRaster,
    GoodNotesPageWork,
    issue_stable_id,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose

MCP_EVALUATION_SURFACE_STDIO = "stdio-isolated"
MCP_BINDING_ISOLATED_IN_PROCESS = "ISOLATED_IN_PROCESS"
MCP_BINDING_OPERATOR_LOCAL_STDIO = "OPERATOR_LOCAL_STDIO"
MCP_EVALUATION_BINDING_MODES = frozenset(
    {MCP_BINDING_ISOLATED_IN_PROCESS, MCP_BINDING_OPERATOR_LOCAL_STDIO}
)
CAPTURE_SCHEMA_VERSION = "gsqs-analyzer-capture-v1"
EVALUATION_RENDERER_NAME = "gsqs-b0-eval"
EVALUATION_RENDERER_VERSION = "1"
EVALUATION_RENDER_PROFILE = "png-identity-v1"
LIVE_REMOTE_MCP_ORIGIN = "https://my-pa-mcp.bobby-fetting.me"
EVALUATION_MCP_TOOLS = frozenset(
    {Capability.GOODNOTES_WORK.value, Capability.GOODNOTES_CONTENT.value}
)
EVALUATION_MCP_PURPOSES = frozenset(
    {
        (Capability.GOODNOTES_WORK, Purpose.GOODNOTES_WORK),
        (Capability.GOODNOTES_CONTENT, Purpose.GOODNOTES_CONTENT),
    }
)


class CapturedAnalyzerAdapter:
    """Admit previously captured interchange. No image bytes, no HTTP POST.

    Capture already happened. Scoring is local and does not open a disclosure
    journal or require RouteLLM HTTP origin.
    """

    requires_durable_disclosure_journal = False

    def __init__(self, repetitions: Sequence[Mapping[str, Mapping[str, object]]]) -> None:
        if not repetitions:
            raise ValueError("captured analyzer output is missing")
        self._repetitions = tuple(dict(item) for item in repetitions)
        self._repetition_index = 0
        self._seen: set[str] = set()

    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        del config
        if case.case_id in self._seen:
            self._repetition_index += 1
            self._seen = set()
        if self._repetition_index >= len(self._repetitions):
            raise ValueError("captured analyzer output exhausted")
        document = self._repetitions[self._repetition_index].get(case.case_id)
        if not isinstance(document, Mapping):
            raise ValueError("missing captured analyzer output")
        self._seen.add(case.case_id)
        return dict(document)


def validate_mcp_evaluation_bindings(authorization: ExecutionAuthorization) -> None:
    surface = authorization.mcp_evaluation_surface
    if surface.startswith("https://") or surface == LIVE_REMOTE_MCP_ORIGIN:
        raise ValueError("live remote MCP is not an evaluation surface")
    if surface != MCP_EVALUATION_SURFACE_STDIO:
        raise ValueError("authorization missing mcp_evaluation_surface")
    if authorization.mcp_evaluation_binding_mode not in MCP_EVALUATION_BINDING_MODES:
        raise ValueError("authorization missing mcp_evaluation_binding_mode")
    if not authorization.mcp_evaluation_evidence_id:
        raise ValueError("authorization missing mcp_evaluation_evidence_id")


def evaluation_handle(member: B0CensusMember, *, principal_id: str) -> GoodNotesPageWork:
    return GoodNotesPageWork(
        run_id=issue_stable_id("gnrun", principal_id, "gsqs-b0-eval", member.case_id),
        page_version_id=issue_stable_id("gnver", principal_id, "gsqs-b0-eval", member.case_id),
        principal_id=principal_id,
        content_sha256=member.raster_sha256,
        logical_page_id=issue_stable_id("gnlp", principal_id, "gsqs-b0-eval", member.case_id),
        renderer_name=EVALUATION_RENDERER_NAME,
        renderer_version=EVALUATION_RENDERER_VERSION,
        render_profile_version=EVALUATION_RENDER_PROFILE,
    )


def load_evaluation_png(root: Path, case_id: str) -> bytes:
    if not case_id or "/" in case_id or ".." in case_id:
        raise ValueError("case_id is invalid")
    resolved = root.resolve()
    for suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        candidate = resolved / f"{case_id}{suffix}"
        if candidate.is_symlink():
            raise ValueError("raster path must not be a symlink")
        if candidate.is_file():
            return candidate.read_bytes()
    raise ValueError("raster missing")


def pin_evaluation_raster(
    work: GoodNotesPageWork, png: bytes, *, created_at: datetime
) -> GoodNotesPageRaster:
    digest = sha256(png).hexdigest()
    if digest != work.content_sha256:
        raise ValueError("raster digest mismatch")
    return GoodNotesPageRaster(
        principal_id=work.principal_id,
        page_version_id=work.page_version_id,
        run_id=work.run_id,
        exact_render_sha256=digest,
        png_sha256=digest,
        byte_length=len(png),
        png_bytes=png,
        renderer_name=EVALUATION_RENDERER_NAME,
        renderer_version=EVALUATION_RENDERER_VERSION,
        render_profile_version=EVALUATION_RENDER_PROFILE,
        created_at=created_at,
    )


def evaluation_handle_records(
    census: B0Census, *, principal_id: str
) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for member in census.members:
        work = evaluation_handle(member, principal_id=principal_id)
        records.append(
            {
                "case_id": member.case_id,
                "run_id": work.run_id,
                "page_version_id": work.page_version_id,
                "content_sha256": work.content_sha256,
                "raster_sha256": member.raster_sha256,
            }
        )
    return tuple(records)


def stage_evaluation_pages(
    census: B0Census,
    *,
    raster_root: Path,
    principal_id: str,
    created_at: datetime,
) -> tuple[tuple[GoodNotesPageWork, GoodNotesPageRaster], ...]:
    pages: list[tuple[GoodNotesPageWork, GoodNotesPageRaster]] = []
    for member in census.members:
        work = evaluation_handle(member, principal_id=principal_id)
        png = load_evaluation_png(raster_root, member.case_id)
        pages.append((work, pin_evaluation_raster(work, png, created_at=created_at)))
    return tuple(pages)


def load_captured_repetitions(
    directory: Path, census: B0Census
) -> tuple[dict[str, dict[str, object]], ...]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("captured analyzer directory is missing")
    loaded: list[dict[str, dict[str, object]]] = []
    for index in range(1, 100):
        path = directory / f"repetition-{index:03d}.json"
        if not path.exists():
            break
        if path.is_symlink() or not path.is_file():
            raise ValueError("captured analyzer output is missing")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("captured analyzer output must be a JSON object")
        if payload.get("schema_version") != CAPTURE_SCHEMA_VERSION:
            raise ValueError("wrong captured analyzer schema")
        raw = payload.get("documents")
        if not isinstance(raw, list):
            raise ValueError("captured analyzer documents missing")
        if len(raw) != len(census.members):
            raise ValueError("captured analyzer documents do not match Partition B census")
        mapped: dict[str, dict[str, object]] = {}
        for item, member in zip(raw, census.members, strict=True):
            if not isinstance(item, Mapping):
                raise ValueError("captured analyzer document is not an object")
            document = dict(item)
            if str(document.get("case_id")) != member.case_id:
                raise ValueError("captured analyzer documents do not match Partition B census")
            mapped[member.case_id] = document
        loaded.append(mapped)
    if len(loaded) < 3:
        raise ValueError("captured analyzer output needs at least three repetitions")
    return tuple(loaded)
