"""Deterministic GoodNotes logical-page matching from versioned renders.

Page number and path stay evidence. OCR text is never consulted. A match
requires a unique render feature; an ambiguous candidate set stays unresolved.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import utc_now
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesLogicalPageMatch,
    GoodNotesMatchMethod,
    GoodNotesNotebook,
    GoodNotesNotebookPath,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesPriorPageEvidence,
    GoodNotesSourceSnapshot,
    PageRender,
    SourcePage,
    issue_stable_id,
)

_CONFIDENCE: dict[GoodNotesMatchMethod, float | None] = {
    GoodNotesMatchMethod.EXACT_NORMALIZED_RENDER: 1.0,
    GoodNotesMatchMethod.EXACT_CANONICAL_RENDER: 1.0,
    GoodNotesMatchMethod.STRONG_VISUAL_FINGERPRINT: 0.9,
    GoodNotesMatchMethod.PERCEPTUAL_STRUCTURAL: 0.7,
    GoodNotesMatchMethod.SEQUENCE_TIEBREAK: 0.5,
    GoodNotesMatchMethod.ORDINAL_WEAK: 0.2,
    GoodNotesMatchMethod.UNRESOLVED: None,
}


class PageRenderer(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def profile_version(self) -> str: ...

    def render(self, page_bytes: bytes) -> PageRender: ...


class GoodNotesLineageRepository(Protocol):
    def create_run(self, run: GoodNotesIngestionRun) -> GoodNotesIngestionRun: ...

    def update_run(self, run: GoodNotesIngestionRun) -> GoodNotesIngestionRun: ...

    def store_notebook(self, notebook: GoodNotesNotebook) -> GoodNotesNotebook: ...

    def record_notebook_path(self, observed: GoodNotesNotebookPath) -> GoodNotesNotebookPath: ...

    def store_snapshot(self, snapshot: GoodNotesSourceSnapshot) -> GoodNotesSourceSnapshot: ...

    def snapshots(
        self, principal_id: str, notebook_id: str
    ) -> tuple[GoodNotesSourceSnapshot, ...]: ...

    def store_logical_page(self, page: GoodNotesLogicalPage) -> GoodNotesLogicalPage: ...

    def logical_pages(
        self, principal_id: str, notebook_id: str
    ) -> tuple[GoodNotesLogicalPage, ...]: ...

    def store_page_position(self, position: GoodNotesPagePosition) -> GoodNotesPagePosition: ...

    def page_positions(
        self, principal_id: str, snapshot_id: str
    ) -> tuple[GoodNotesPagePosition, ...]: ...

    def prior_page_evidence(
        self, principal_id: str, notebook_id: str
    ) -> tuple[GoodNotesPriorPageEvidence, ...]: ...

    def notebook(self, principal_id: str, notebook_id: str) -> GoodNotesNotebook | None: ...

    def page(self, principal_id: str, page_id: str) -> GoodNotesPage | None: ...

    def page_version(
        self, principal_id: str, page_version_id: str
    ) -> GoodNotesPageVersion | None: ...

    def notebooks_for_source_object(
        self, principal_id: str, source_root_id: str, source_object_id: str
    ) -> tuple[GoodNotesNotebook, ...]: ...

    def notebooks_for_snapshot_digest(
        self, principal_id: str, source_root_id: str, raw_sha256: str
    ) -> tuple[GoodNotesNotebook, ...]: ...

    def notebooks_for_visual_page_set(
        self,
        principal_id: str,
        source_root_id: str,
        normalized_render_sha256s: tuple[str, ...],
    ) -> tuple[GoodNotesNotebook, ...]: ...

    def store_page_version_render(
        self, *, page: GoodNotesPage, version: GoodNotesPageVersion
    ) -> GoodNotesPageVersion: ...

    def run_by_request(
        self, principal_id: str, request_id: str
    ) -> GoodNotesIngestionRun | None: ...


@dataclass(frozen=True, slots=True)
class ObservedNotebookFile:
    relative_path: str
    size_bytes: int
    sha256: str
    mtime_ns: int
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class LineageReconcileRequest:
    principal_id: str
    request_id: str
    source_root_id: str
    source_object_id: str
    observation: ObservedNotebookFile
    pages: tuple[SourcePage, ...]
    notebook_id: str | None = None
    label: str | None = None
    trigger_type: GoodNotesIngestionTrigger = GoodNotesIngestionTrigger.MANUAL
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LineageReconcileResult:
    run: GoodNotesIngestionRun
    notebook: GoodNotesNotebook
    snapshot: GoodNotesSourceSnapshot
    replayed_snapshot: bool
    matches: tuple[GoodNotesLogicalPageMatch, ...]
    positions: tuple[GoodNotesPagePosition, ...]


@dataclass(frozen=True, slots=True)
class _CurrentPage:
    page_number: int
    render: PageRender


def match_logical_pages(
    *,
    notebook_id: str,
    current: Sequence[tuple[int, PageRender]],
    prior: Sequence[GoodNotesPriorPageEvidence],
) -> tuple[GoodNotesLogicalPageMatch, ...]:
    """Match strongest unique render evidence to weakest. Never uses OCR text."""
    remaining_current = [_CurrentPage(page_number, render) for page_number, render in current]
    remaining_prior = list(prior)
    claimed: dict[int, GoodNotesLogicalPageMatch] = {}

    def claim(
        page: _CurrentPage,
        evidence: GoodNotesPriorPageEvidence,
        method: GoodNotesMatchMethod,
    ) -> None:
        remaining_current.remove(page)
        remaining_prior.remove(evidence)
        claimed[page.page_number] = GoodNotesLogicalPageMatch(
            page_number=page.page_number,
            logical_page_id=evidence.logical_page_id,
            is_new=False,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
            match_method=method,
            match_confidence=_CONFIDENCE[method],
            prior_page_version_id=evidence.last_page_version_id,
        )

    def mark_ambiguous(pages: Iterable[_CurrentPage]) -> None:
        for page in tuple(pages):
            if page not in remaining_current:
                continue
            remaining_current.remove(page)
            claimed[page.page_number] = _new_match(
                notebook_id,
                page,
                identity_status=GoodNotesIdentityStatus.AMBIGUOUS,
                method=GoodNotesMatchMethod.UNRESOLVED,
            )

    _assign_unique(
        remaining_current,
        remaining_prior,
        key_current=lambda page: page.render.normalized_render_sha256,
        key_prior=lambda item: item.normalized_render_sha256,
        method=GoodNotesMatchMethod.EXACT_NORMALIZED_RENDER,
        claim=claim,
        mark_ambiguous=mark_ambiguous,
    )
    _assign_unique(
        remaining_current,
        remaining_prior,
        key_current=lambda page: page.render.exact_render_sha256,
        key_prior=lambda item: item.exact_render_sha256,
        method=GoodNotesMatchMethod.EXACT_CANONICAL_RENDER,
        claim=claim,
        mark_ambiguous=mark_ambiguous,
    )
    _assign_unique(
        remaining_current,
        remaining_prior,
        key_current=lambda page: page.render.perceptual_hash,
        key_prior=lambda item: item.perceptual_hash,
        method=GoodNotesMatchMethod.STRONG_VISUAL_FINGERPRINT,
        claim=claim,
        mark_ambiguous=mark_ambiguous,
    )
    _assign_unique(
        remaining_current,
        remaining_prior,
        key_current=_structural_key_current,
        key_prior=_structural_key_prior,
        method=GoodNotesMatchMethod.PERCEPTUAL_STRUCTURAL,
        claim=claim,
        mark_ambiguous=mark_ambiguous,
    )

    if len(remaining_current) == 1 and len(remaining_prior) == 1:
        page = remaining_current[0]
        evidence = remaining_prior[0]
        if abs(evidence.last_page_number - page.page_number) <= 1:
            claim(page, evidence, GoodNotesMatchMethod.SEQUENCE_TIEBREAK)

    if remaining_current and remaining_prior:
        mark_ambiguous(remaining_current)
    else:
        for page in tuple(remaining_current):
            remaining_current.remove(page)
            claimed[page.page_number] = _new_match(
                notebook_id,
                page,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                method=GoodNotesMatchMethod.UNRESOLVED,
            )

    return tuple(claimed[number] for number, _ in current)


def _structural_key_current(page: _CurrentPage) -> str | None:
    render = page.render
    if render.perceptual_hash is None or render.width is None or render.height is None:
        return None
    return f"{render.perceptual_hash}\x1f{render.width}\x1f{render.height}"


def _structural_key_prior(item: GoodNotesPriorPageEvidence) -> str | None:
    if item.perceptual_hash is None or item.render_width is None or item.render_height is None:
        return None
    return f"{item.perceptual_hash}\x1f{item.render_width}\x1f{item.render_height}"


def _assign_unique(
    remaining_current: list[_CurrentPage],
    remaining_prior: list[GoodNotesPriorPageEvidence],
    *,
    key_current: Callable[[_CurrentPage], str | None],
    key_prior: Callable[[GoodNotesPriorPageEvidence], str | None],
    method: GoodNotesMatchMethod,
    claim: Callable[[_CurrentPage, GoodNotesPriorPageEvidence, GoodNotesMatchMethod], None],
    mark_ambiguous: Callable[[Iterable[_CurrentPage]], None],
) -> None:
    current_unique = _unique_index(remaining_current, key_current)
    prior_unique = _unique_index(remaining_prior, key_prior)
    for key, page in tuple(current_unique.items()):
        evidence = prior_unique.get(key)
        if evidence is None or page not in remaining_current or evidence not in remaining_prior:
            continue
        claim(page, evidence, method)
    contested: list[_CurrentPage] = []
    for page in remaining_current:
        feature = key_current(page)
        if feature is None:
            continue
        hits = [item for item in remaining_prior if key_prior(item) == feature]
        if len(hits) > 1 or (len(hits) == 1 and feature not in current_unique):
            contested.append(page)
    if contested:
        mark_ambiguous(contested)


def _unique_index[T](items: Sequence[T], key_fn: Callable[[T], str | None]) -> dict[str, T]:
    grouped: dict[str, list[T]] = {}
    for item in items:
        key = key_fn(item)
        if key is None:
            continue
        grouped.setdefault(key, []).append(item)
    return {key: group[0] for key, group in grouped.items() if len(group) == 1}


def _new_match(
    notebook_id: str,
    page: _CurrentPage,
    *,
    identity_status: GoodNotesIdentityStatus,
    method: GoodNotesMatchMethod,
) -> GoodNotesLogicalPageMatch:
    return GoodNotesLogicalPageMatch(
        page_number=page.page_number,
        logical_page_id=issue_stable_id(
            "gnlp", notebook_id, page.render.exact_render_sha256, str(page.page_number)
        ),
        is_new=True,
        identity_status=identity_status,
        match_method=method,
        match_confidence=_CONFIDENCE[method],
    )


class GoodNotesLineageService:
    def reconcile(
        self,
        request: LineageReconcileRequest,
        *,
        renderer: PageRenderer,
        repository: GoodNotesLineageRepository,
        clock: Callable[[], datetime] = utc_now,
        finalize_run: bool = True,
    ) -> LineageReconcileResult:
        principal_id = request.principal_id
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(request.source_object_id, IdKind.SOURCE_OBJECT)
        if not request.pages:
            raise ValueError("a GoodNotes lineage reconcile requires admitted pages")
        for page in request.pages:
            if page.principal_id != principal_id:
                raise ValueError("source inventory crossed its Principal boundary")
        observed_at = request.observed_at or clock()
        rendered = tuple(
            (page.page_number, renderer.render(page.content)) for page in request.pages
        )
        notebook_id, identity_status = resolve_notebook_identity(
            request,
            principal_id=principal_id,
            repository=repository,
            normalized_render_sha256s=tuple(
                render.normalized_render_sha256 for _, render in rendered
            ),
        )
        fingerprint = ingestion_request_fingerprint(
            principal_id=principal_id,
            source_root_id=request.source_root_id,
            source_object_id=request.source_object_id,
            observation_sha256=request.observation.sha256,
            renderer=renderer,
        )
        existing_run = repository.run_by_request(principal_id, request.request_id)
        if existing_run is not None and existing_run.request_fingerprint != fingerprint:
            raise ValueError("the request id is bound to another ingestion")
        held_positions = _positions_for_observation(
            repository,
            principal_id=principal_id,
            notebook_id=notebook_id,
            raw_sha256=request.observation.sha256,
        )
        if held_positions and existing_run is not None:
            verify_persisted_page_identity(
                principal_id=principal_id,
                pages=request.pages,
                positions=held_positions,
                renderer=renderer,
                repository=repository,
                verify_supplied_content_digest=True,
            )
        if existing_run is None:
            run = repository.create_run(
                GoodNotesIngestionRun(
                    run_id=issue_stable_id("gnrun", principal_id, request.request_id),
                    principal_id=principal_id,
                    source_root_id=request.source_root_id,
                    trigger_type=request.trigger_type,
                    request_id=request.request_id,
                    idempotency_key=request.request_id,
                    request_fingerprint=fingerprint,
                    started_at=observed_at,
                    status=GoodNotesIngestionStatus.RUNNING,
                )
            )
        elif existing_run.status is GoodNotesIngestionStatus.FAILED:
            run = repository.update_run(
                replace(
                    existing_run,
                    status=GoodNotesIngestionStatus.RUNNING,
                    ended_at=None,
                    error_code=None,
                    error_class=None,
                )
            )
        else:
            run = existing_run
        notebook = repository.store_notebook(
            GoodNotesNotebook(
                notebook_id=notebook_id,
                principal_id=principal_id,
                source_root_id=request.source_root_id,
                identity_status=identity_status,
                created_at=observed_at,
                last_observed_at=observed_at,
                label=request.label,
            )
        )
        snapshot = repository.store_snapshot(
            GoodNotesSourceSnapshot(
                snapshot_id=issue_stable_id(
                    "gnsnap", notebook.notebook_id, request.observation.sha256
                ),
                principal_id=principal_id,
                notebook_id=notebook.notebook_id,
                source_object_id=request.source_object_id,
                observed_path=request.observation.relative_path,
                raw_sha256=request.observation.sha256,
                size_bytes=request.observation.size_bytes,
                page_count=request.observation.page_count
                if request.observation.page_count is not None
                else len(request.pages),
                observed_at=observed_at,
                settled_at=observed_at,
                run_id=run.run_id,
                mtime_ns=request.observation.mtime_ns,
            )
        )
        repository.record_notebook_path(
            GoodNotesNotebookPath(
                principal_id=principal_id,
                notebook_id=notebook.notebook_id,
                path=request.observation.relative_path,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                is_current=True,
                first_snapshot_id=snapshot.snapshot_id,
                last_snapshot_id=snapshot.snapshot_id,
            )
        )
        existing_positions = repository.page_positions(principal_id, snapshot.snapshot_id)
        if existing_positions:
            finished = repository.update_run(
                replace(
                    run,
                    status=(
                        GoodNotesIngestionStatus.REPLAYED
                        if finalize_run
                        else GoodNotesIngestionStatus.RUNNING
                    ),
                    ended_at=clock() if finalize_run else None,
                    snapshot_count=len(repository.snapshots(principal_id, notebook.notebook_id)),
                    page_count=len(existing_positions),
                    new_logical_page_count=0,
                    changed_page_count=0,
                    ambiguous_page_count=0,
                )
            )
            return LineageReconcileResult(
                run=finished,
                notebook=notebook,
                snapshot=snapshot,
                replayed_snapshot=True,
                matches=(),
                positions=existing_positions,
            )

        prior = repository.prior_page_evidence(principal_id, notebook.notebook_id)
        matches = match_logical_pages(
            notebook_id=notebook.notebook_id, current=rendered, prior=prior
        )
        prior_by_id = {item.logical_page_id: item for item in prior}
        page_by_number = {page.page_number: page for page in request.pages}
        render_by_number = dict(rendered)
        positions: list[GoodNotesPagePosition] = []
        new_logical = 0
        changed = 0
        ambiguous = 0
        for match in matches:
            source_page = page_by_number[match.page_number]
            render = render_by_number[match.page_number]
            if match.is_new:
                new_logical += 1
            if match.identity_status is GoodNotesIdentityStatus.AMBIGUOUS:
                ambiguous += 1
            prior_item = prior_by_id.get(match.logical_page_id)
            if (
                prior_item is not None
                and prior_item.exact_render_sha256 is not None
                and prior_item.exact_render_sha256 != render.exact_render_sha256
            ):
                changed += 1
            logical = repository.store_logical_page(
                GoodNotesLogicalPage(
                    logical_page_id=match.logical_page_id,
                    principal_id=principal_id,
                    notebook_id=notebook.notebook_id,
                    created_at=observed_at,
                    last_seen_at=observed_at,
                    identity_status=match.identity_status,
                )
            )
            version = _page_version(source_page, render, match.logical_page_id)
            stored_version = repository.store_page_version_render(
                page=GoodNotesPage(
                    page_id=version.page_id,
                    principal_id=principal_id,
                    source_id=source_page.source_id,
                    source_object_id=source_page.source_object_id,
                    page_number=source_page.page_number,
                ),
                version=version,
            )
            positions.append(
                repository.store_page_position(
                    GoodNotesPagePosition(
                        principal_id=principal_id,
                        snapshot_id=snapshot.snapshot_id,
                        page_number=match.page_number,
                        logical_page_id=logical.logical_page_id,
                        created_at=observed_at,
                        match_method=match.match_method,
                        page_version_id=stored_version.page_version_id,
                        match_confidence=match.match_confidence,
                        prior_page_version_id=match.prior_page_version_id,
                    )
                )
            )
        finished = repository.update_run(
            replace(
                run,
                status=(
                    GoodNotesIngestionStatus.SUCCEEDED
                    if finalize_run
                    else GoodNotesIngestionStatus.RUNNING
                ),
                ended_at=clock() if finalize_run else None,
                snapshot_count=len(repository.snapshots(principal_id, notebook.notebook_id)),
                page_count=len(positions),
                new_logical_page_count=new_logical,
                changed_page_count=changed,
                ambiguous_page_count=ambiguous,
            )
        )
        return LineageReconcileResult(
            run=finished,
            notebook=notebook,
            snapshot=snapshot,
            replayed_snapshot=False,
            matches=matches,
            positions=tuple(positions),
        )


def _page_version(
    page: SourcePage, render: PageRender, logical_page_id: str
) -> GoodNotesPageVersion:
    digest = hashlib.sha256(page.content).hexdigest()
    page_id = issue_stable_id("gnpg", page.source_object_id, str(page.page_number))
    return GoodNotesPageVersion(
        page_version_id=issue_stable_id(
            "gnver",
            page_id,
            page.source_version_id,
            page.representation_media_type,
            digest,
        ),
        page_id=page_id,
        source_version_id=page.source_version_id,
        content_sha256=digest,
        observed_at=page.observed_at,
        logical_page_id=logical_page_id,
        exact_render_sha256=render.exact_render_sha256,
        normalized_render_sha256=render.normalized_render_sha256,
        perceptual_hash=render.perceptual_hash,
        render_width=render.width,
        render_height=render.height,
        renderer_name=render.renderer_name,
        renderer_version=render.renderer_version,
        render_profile_version=render.render_profile_version,
    )


def verify_persisted_page_identity(
    *,
    principal_id: str,
    pages: Sequence[SourcePage],
    positions: Sequence[GoodNotesPagePosition],
    renderer: PageRenderer,
    repository: GoodNotesLineageRepository,
    verify_supplied_content_digest: bool,
) -> None:
    """Fail closed when supplied pages do not match persisted page/version evidence.

    gnver is recomputed from persisted content_sha256 plus the supplied page
    identity fields. This is not the ingestion fingerprint and does not hash
    freshly supplied page bytes into GoodNotesIngestionRun.request_fingerprint.

    `verify_supplied_content_digest` is an explicit path contract, not inferred
    from caller type: standalone request-bound lineage replay requires
    sha256(SourcePage.content) == persisted content_sha256; durable-orchestrator
    completed-LINEAGE continuation does not, because split_admitted_pdf is not
    byte-stable across equivalent invocations.
    """
    if len(positions) != len(pages):
        raise ValueError("the request id is bound to another ingestion")
    by_number = {page.page_number: page for page in pages}
    for position in positions:
        source_page = by_number.get(position.page_number)
        if source_page is None or position.page_version_id is None:
            raise ValueError("the request id is bound to another ingestion")
        version = repository.page_version(principal_id, position.page_version_id)
        if version is None:
            raise ValueError("the request id is bound to another ingestion")
        page_id = issue_stable_id(
            "gnpg", source_page.source_object_id, str(source_page.page_number)
        )
        expected_version_id = issue_stable_id(
            "gnver",
            page_id,
            source_page.source_version_id,
            source_page.representation_media_type,
            version.content_sha256,
        )
        if position.page_version_id != expected_version_id:
            raise ValueError("the request id is bound to another ingestion")
        if version.source_version_id != source_page.source_version_id:
            raise ValueError("the request id is bound to another ingestion")
        if (
            version.renderer_name != renderer.name
            or version.renderer_version != renderer.version
            or version.render_profile_version != renderer.profile_version
        ):
            raise ValueError("the request id is bound to another ingestion")
        stored_page = repository.page(principal_id, version.page_id)
        if stored_page is None:
            raise ValueError("the request id is bound to another ingestion")
        if stored_page.source_id != source_page.source_id:
            raise ValueError("the request id is bound to another ingestion")
        if stored_page.source_object_id != source_page.source_object_id:
            raise ValueError("the request id is bound to another ingestion")
        if stored_page.page_number != source_page.page_number:
            raise ValueError("the request id is bound to another ingestion")
        if stored_page.page_id != page_id:
            raise ValueError("the request id is bound to another ingestion")
        if verify_supplied_content_digest and (
            hashlib.sha256(source_page.content).hexdigest() != version.content_sha256
        ):
            raise ValueError("the request id is bound to another ingestion")


def _positions_for_observation(
    repository: GoodNotesLineageRepository,
    *,
    principal_id: str,
    notebook_id: str,
    raw_sha256: str,
) -> tuple[GoodNotesPagePosition, ...]:
    for snapshot in repository.snapshots(principal_id, notebook_id):
        if snapshot.raw_sha256 == raw_sha256:
            return repository.page_positions(principal_id, snapshot.snapshot_id)
    return ()


def ingestion_request_fingerprint(
    *,
    principal_id: str,
    source_root_id: str,
    source_object_id: str,
    observation_sha256: str,
    renderer: PageRenderer,
) -> str:
    """Canonical GoodNotesIngestionRun.request_fingerprint (ingestion, not page-byte)."""
    return hashlib.sha256(
        f"{principal_id}\x1f{source_root_id}\x1f"
        f"{source_object_id}\x1f{observation_sha256}\x1f"
        f"{renderer.name}\x1f{renderer.version}\x1f{renderer.profile_version}\x1f".encode()
    ).hexdigest()


def resolve_notebook_identity(
    request: LineageReconcileRequest,
    *,
    principal_id: str,
    repository: GoodNotesLineageRepository,
    normalized_render_sha256s: tuple[str, ...],
) -> tuple[str, GoodNotesIdentityStatus]:
    """Resolve notebook identity without path. Path is recorded as history elsewhere.

    Order: caller id, unique source object, unique prior snapshot digest, unique
    visual page-set. Multiple candidates stay AMBIGUOUS. None issues today's id.
    """
    issued = issue_stable_id("gnnb", principal_id, request.source_root_id, request.source_object_id)
    if request.notebook_id is not None:
        return request.notebook_id, GoodNotesIdentityStatus.ACTIVE
    by_object = repository.notebooks_for_source_object(
        principal_id, request.source_root_id, request.source_object_id
    )
    decided = _unique_notebook(by_object, issued)
    if decided is not None:
        return decided
    by_digest = repository.notebooks_for_snapshot_digest(
        principal_id, request.source_root_id, request.observation.sha256
    )
    decided = _unique_notebook(by_digest, issued)
    if decided is not None:
        return decided
    by_visual = repository.notebooks_for_visual_page_set(
        principal_id, request.source_root_id, normalized_render_sha256s
    )
    decided = _unique_notebook(by_visual, issued)
    if decided is not None:
        return decided
    return issued, GoodNotesIdentityStatus.ACTIVE


def _unique_notebook(
    candidates: tuple[GoodNotesNotebook, ...], issued: str
) -> tuple[str, GoodNotesIdentityStatus] | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].notebook_id, GoodNotesIdentityStatus.ACTIVE
    return issued, GoodNotesIdentityStatus.AMBIGUOUS
