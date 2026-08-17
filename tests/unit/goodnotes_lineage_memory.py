"""In-memory GoodNotes lineage repository for unit tests."""

from __future__ import annotations

from collections import Counter

from my_pa.domain.goodnotes.models import (
    GoodNotesIngestionRun,
    GoodNotesLogicalPage,
    GoodNotesNotebook,
    GoodNotesNotebookPath,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesPriorPageEvidence,
    GoodNotesSourceSnapshot,
)


class MemoryLineageRepository:
    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], GoodNotesIngestionRun] = {}
        self.notebooks: dict[tuple[str, str], GoodNotesNotebook] = {}
        self.paths: dict[tuple[str, str, str], GoodNotesNotebookPath] = {}
        self._snapshots: dict[tuple[str, str], GoodNotesSourceSnapshot] = {}
        self._logical: dict[tuple[str, str], GoodNotesLogicalPage] = {}
        self._positions: dict[tuple[str, str, int], GoodNotesPagePosition] = {}
        self._versions: dict[tuple[str, str], GoodNotesPageVersion] = {}

    def create_run(self, run: GoodNotesIngestionRun) -> GoodNotesIngestionRun:
        self.runs[(run.principal_id, run.run_id)] = run
        return run

    def update_run(self, run: GoodNotesIngestionRun) -> GoodNotesIngestionRun:
        self.runs[(run.principal_id, run.run_id)] = run
        return run

    def store_notebook(self, notebook: GoodNotesNotebook) -> GoodNotesNotebook:
        key = (notebook.principal_id, notebook.notebook_id)
        stored = self.notebooks.get(key)
        if stored is None:
            self.notebooks[key] = notebook
            return notebook
        updated = GoodNotesNotebook(
            notebook_id=stored.notebook_id,
            principal_id=stored.principal_id,
            source_root_id=stored.source_root_id,
            identity_status=notebook.identity_status,
            created_at=stored.created_at,
            last_observed_at=notebook.last_observed_at,
            label=notebook.label,
        )
        self.notebooks[key] = updated
        return updated

    def record_notebook_path(self, observed: GoodNotesNotebookPath) -> GoodNotesNotebookPath:
        self.paths[(observed.principal_id, observed.notebook_id, observed.path)] = observed
        return observed

    def store_snapshot(self, snapshot: GoodNotesSourceSnapshot) -> GoodNotesSourceSnapshot:
        for stored in self._snapshots.values():
            if (
                stored.principal_id == snapshot.principal_id
                and stored.notebook_id == snapshot.notebook_id
                and stored.raw_sha256 == snapshot.raw_sha256
            ):
                return stored
        self._snapshots[(snapshot.principal_id, snapshot.snapshot_id)] = snapshot
        return snapshot

    def snapshots(self, principal_id: str, notebook_id: str) -> tuple[GoodNotesSourceSnapshot, ...]:
        found = [
            item
            for item in self._snapshots.values()
            if item.principal_id == principal_id and item.notebook_id == notebook_id
        ]
        return tuple(sorted(found, key=lambda item: item.observed_at))

    def store_logical_page(self, page: GoodNotesLogicalPage) -> GoodNotesLogicalPage:
        key = (page.principal_id, page.logical_page_id)
        stored = self._logical.get(key)
        if stored is None:
            self._logical[key] = page
            return page
        updated = GoodNotesLogicalPage(
            logical_page_id=stored.logical_page_id,
            principal_id=stored.principal_id,
            notebook_id=stored.notebook_id,
            created_at=stored.created_at,
            last_seen_at=page.last_seen_at,
            identity_status=page.identity_status,
        )
        self._logical[key] = updated
        return updated

    def logical_pages(
        self, principal_id: str, notebook_id: str
    ) -> tuple[GoodNotesLogicalPage, ...]:
        return tuple(
            item
            for item in self._logical.values()
            if item.principal_id == principal_id and item.notebook_id == notebook_id
        )

    def store_page_position(self, position: GoodNotesPagePosition) -> GoodNotesPagePosition:
        self._positions[(position.principal_id, position.snapshot_id, position.page_number)] = (
            position
        )
        return position

    def page_positions(
        self, principal_id: str, snapshot_id: str
    ) -> tuple[GoodNotesPagePosition, ...]:
        found = [
            item
            for (owner, stored_snapshot, _), item in self._positions.items()
            if owner == principal_id and stored_snapshot == snapshot_id
        ]
        return tuple(sorted(found, key=lambda item: item.page_number))

    def store_page_version_render(
        self, *, page: GoodNotesPage, version: GoodNotesPageVersion
    ) -> GoodNotesPageVersion:
        del page
        self._versions[(version.page_version_id, version.page_id)] = version
        return version

    def page_version(self, principal_id: str, page_version_id: str) -> GoodNotesPageVersion | None:
        del principal_id
        for version in self._versions.values():
            if version.page_version_id == page_version_id:
                return version
        return None

    def prior_page_evidence(
        self, principal_id: str, notebook_id: str
    ) -> tuple[GoodNotesPriorPageEvidence, ...]:
        pages = self.logical_pages(principal_id, notebook_id)
        snapshots = self.snapshots(principal_id, notebook_id)
        rank = {item.snapshot_id: index for index, item in enumerate(snapshots)}
        latest: dict[str, GoodNotesPagePosition] = {}
        for snapshot in snapshots:
            for position in self.page_positions(principal_id, snapshot.snapshot_id):
                current = latest.get(position.logical_page_id)
                if current is None or rank[position.snapshot_id] >= rank[current.snapshot_id]:
                    latest[position.logical_page_id] = position
        evidence: list[GoodNotesPriorPageEvidence] = []
        for page in pages:
            latest_position = latest.get(page.logical_page_id)
            if latest_position is None:
                continue
            version = (
                None
                if latest_position.page_version_id is None
                else self.page_version(principal_id, latest_position.page_version_id)
            )
            evidence.append(
                GoodNotesPriorPageEvidence(
                    logical_page_id=page.logical_page_id,
                    last_page_number=latest_position.page_number,
                    last_page_version_id=latest_position.page_version_id,
                    exact_render_sha256=None if version is None else version.exact_render_sha256,
                    normalized_render_sha256=(
                        None if version is None else version.normalized_render_sha256
                    ),
                    perceptual_hash=None if version is None else version.perceptual_hash,
                    render_width=None if version is None else version.render_width,
                    render_height=None if version is None else version.render_height,
                )
            )
        return tuple(evidence)

    def notebooks_for_source_object(
        self, principal_id: str, source_root_id: str, source_object_id: str
    ) -> tuple[GoodNotesNotebook, ...]:
        notebook_ids = {
            snapshot.notebook_id
            for snapshot in self._snapshots.values()
            if snapshot.principal_id == principal_id
            and snapshot.source_object_id == source_object_id
        }
        return tuple(
            notebook
            for notebook in self.notebooks.values()
            if notebook.principal_id == principal_id
            and notebook.source_root_id == source_root_id
            and notebook.notebook_id in notebook_ids
        )

    def notebooks_for_snapshot_digest(
        self, principal_id: str, source_root_id: str, raw_sha256: str
    ) -> tuple[GoodNotesNotebook, ...]:
        notebook_ids = {
            snapshot.notebook_id
            for snapshot in self._snapshots.values()
            if snapshot.principal_id == principal_id and snapshot.raw_sha256 == raw_sha256
        }
        return tuple(
            notebook
            for notebook in self.notebooks.values()
            if notebook.principal_id == principal_id
            and notebook.source_root_id == source_root_id
            and notebook.notebook_id in notebook_ids
        )

    def notebooks_for_visual_page_set(
        self,
        principal_id: str,
        source_root_id: str,
        normalized_render_sha256s: tuple[str, ...],
    ) -> tuple[GoodNotesNotebook, ...]:
        wanted = Counter(normalized_render_sha256s)
        if not wanted:
            return ()
        matched: list[GoodNotesNotebook] = []
        for notebook in self.notebooks.values():
            if notebook.principal_id != principal_id or notebook.source_root_id != source_root_id:
                continue
            observed = Counter(
                item.normalized_render_sha256
                for item in self.prior_page_evidence(principal_id, notebook.notebook_id)
                if item.normalized_render_sha256 is not None
            )
            if observed == wanted:
                matched.append(notebook)
        return tuple(matched)
