"""The managed-document use cases: write, read, archive, restore, and reconcile.

`ManagedDocumentService` is a standalone application service in the same shape as
`SituationService`: each method takes the ports it operates through and one
command, and the Principal travels in the command as a **resolved partition**
rather than as a caller-supplied identity. It is deliberately *not* wired behind
`ApplicationService.invoke`, and the WP-27 section of `application.commands`
records why: exposing managed writes over a transport is WP-28's package, and a
capability seat with nothing behind it would publish a name `capabilities.get`
reports as available and no transport can reach.

**The write ordering is the transactional decision of this package, and it is
stated rather than implied.** The filesystem and the database are not one
transaction. `create` and `revise` therefore:

1. mint the version identifier and build the write request, which is what
   computes the payload digest;
2. read whether the key is already bound *to that digest*, inside the caller's
   transaction. A replay returns the original receipt here having written no
   bytes, and a key bound to a different request is refused here rather than
   after a copy of bytes no row will name has been stored. It is an
   optimisation and never the decision — the unique constraint underneath
   `admit` is still what makes two concurrent writers produce one version;
3. write and fsync the bytes under that identifier through the byte store,
   which derives their location from it and accepts no path;
4. insert the submission, document, version and receipt rows;
5. return, leaving the caller's transaction to commit.

**What that leaves, honestly.** A failure between (3) and the commit leaves
**bytes with no row**. Those bytes are unreachable — nothing can name a version
that does not exist — and `verify` reports them as orphans for an operator to
reclaim. The reverse ordering would leave a **row naming absent bytes**, which no
reconciliation can repair and which reads to every caller as durable data that is
gone. This package chooses the recoverable failure and says so here, in
`infrastructure.managed_document_stores.filesystem.store`, and in
`ops/runbooks/managed-document-operations.md`.

**Archive is a state transition and never destruction.** There is no delete
method on this service, no delete statement under it, and no `deleted` member in
the lifecycle vocabulary. The register puts hard delete out of scope and
`AGENTS.md` section 8.2 reserves irreversible destruction of canonical data to
the operator.

**Backup and restore are per-Principal operator operations.** A backup reads one
Principal's versions and their bytes and writes both into a second byte store —
so the destination is a managed root with the same containment as the source, not
an arbitrary directory. A restore reads that manifest and rebuilds the rows and
the bytes. Every statement on both paths carries the partition, which is also
what makes a restore unable to move a document between Principals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from my_pa.application.commands import (
    ArchiveManagedDocumentCommand,
    CreateManagedDocumentCommand,
    ListManagedDocumentsCommand,
    ReadManagedDocumentCommand,
    RestoreManagedDocumentCommand,
    ReviseManagedDocumentCommand,
)
from my_pa.contracts.ports import (
    ManagedByteStore,
    ManagedDocumentRepository,
    ManagedWriteRequest,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc, utc_now
from my_pa.domain.documents.managed import (
    DocumentState,
    LifecycleTransition,
    ManagedContent,
    ManagedDocument,
    ManagedDocumentReceipt,
    ManagedDocumentVersion,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "BackupSummary",
    "IntegrityReport",
    "ManagedDocumentService",
    "ManagedVersionBytes",
    "RestoreSummary",
]

#: The manifest format this package writes and reads. Bumping it is a deliberate
#: edit: `restore` refuses a manifest whose version it does not recognise rather
#: than guessing at a shape, because a half-understood backup restored is worse
#: than one refused.
_MANIFEST_VERSION = 1


@dataclass(frozen=True, slots=True)
class ManagedVersionBytes:
    """One stored version and, when asked for, the bytes it names."""

    version: ManagedDocumentVersion
    state: DocumentState
    is_current: bool
    content: ManagedContent | None


@dataclass(frozen=True, slots=True)
class BackupSummary:
    """What one backup wrote: counts and the digest of the manifest it left."""

    documents: int
    versions: int
    bytes_copied: int
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class RestoreSummary:
    """What one restore rebuilt, and what it found already present."""

    documents: int
    versions: int
    bytes_restored: int
    versions_already_present: int


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """What `verify` measured, in both directions.

    `missing_bytes` is the failure this package's ordering is designed never to
    produce: a row naming bytes that are not there. A non-empty list is a real
    data-loss finding and the operations document says so.

    `digest_mismatches` is a row whose stored bytes are present but are not the
    bytes the row records. Nothing in this product can produce one — the bytes are
    written once, create-exclusive, and never reopened for writing — so a
    non-empty list means something outside this product wrote into the managed
    root.

    `orphaned_version_ids` is the recoverable side: bytes with no row, which is
    what a crash between the byte write and the commit leaves, and what a replayed
    write leaves when its key was already bound.

    `unreadable_entries` is anything in the object tree that is not a well-formed
    managed version object at all.
    """

    versions_checked: int
    missing_bytes: tuple[str, ...]
    digest_mismatches: tuple[str, ...]
    orphaned_version_ids: tuple[str, ...]
    unreadable_entries: tuple[str, ...]

    @property
    def is_consistent(self) -> bool:
        """Whether the two stores agree in the direction that cannot be repaired."""
        return not self.missing_bytes and not self.digest_mismatches


class ManagedDocumentService:
    """Route each managed-document command to the ports that answer it."""

    def create(
        self,
        repository: ManagedDocumentRepository,
        store: ManagedByteStore,
        command: CreateManagedDocumentCommand,
    ) -> ManagedDocumentReceipt:
        """Store the first immutable version of a new managed document."""
        return self._write(
            repository,
            store,
            principal_id=command.principal_id,
            document_id=None,
            expected_version_number=None,
            title=command.title,
            media_type=command.media_type,
            content=ManagedContent(bytes(command.content)),
            idempotency_key=command.idempotency_key,
        )

    def revise(
        self,
        repository: ManagedDocumentRepository,
        store: ManagedByteStore,
        command: ReviseManagedDocumentCommand,
    ) -> ManagedDocumentReceipt:
        """Append a successor version, refusing a stale expected version."""
        return self._write(
            repository,
            store,
            principal_id=command.principal_id,
            document_id=command.document_id,
            expected_version_number=command.expected_version_number,
            title=command.title,
            media_type=command.media_type,
            content=ManagedContent(bytes(command.content)),
            idempotency_key=command.idempotency_key,
        )

    def read(
        self,
        repository: ManagedDocumentRepository,
        store: ManagedByteStore,
        command: ReadManagedDocumentCommand,
    ) -> ManagedVersionBytes | None:
        """One stored version, with its bytes when they were asked for.

        `None` for a document this Principal does not own, one that does not
        exist, and a version identifier belonging to another document: three
        absences and one answer, so the read cannot be used to map identifiers
        this Principal may not see.
        """
        version = repository.version(
            command.document_id,
            version_id=command.version_id,
            principal_id=command.principal_id,
        )
        if version is None:
            return None
        head = repository.version(command.document_id, principal_id=command.principal_id)
        state = repository.state(command.document_id, principal_id=command.principal_id)
        if head is None or state is None:  # pragma: no cover - the version was just read
            return None
        content = ManagedContent(store.read(version.version_id)) if command.include_bytes else None
        return ManagedVersionBytes(
            version=version,
            state=state,
            is_current=version.version_id == head.version_id,
            content=content,
        )

    def list_documents(
        self, repository: ManagedDocumentRepository, command: ListManagedDocumentsCommand
    ) -> tuple[ManagedDocument, ...]:
        """One bounded page of this Principal's documents."""
        return repository.documents(
            limit=command.limit,
            principal_id=command.principal_id,
            include_archived=command.include_archived,
        )

    def archive(
        self, repository: ManagedDocumentRepository, command: ArchiveManagedDocumentCommand
    ) -> bool:
        """Withdraw one document from the active set. Returns whether it changed."""
        return repository.transition(
            command.document_id,
            transition=LifecycleTransition.ARCHIVED,
            principal_id=command.principal_id,
            correlation_id=issue_identifier(IdKind.CORRELATION),
        )

    def restore(
        self, repository: ManagedDocumentRepository, command: RestoreManagedDocumentCommand
    ) -> bool:
        """Return one archived document to the active set. Returns whether it changed."""
        return repository.transition(
            command.document_id,
            transition=LifecycleTransition.RESTORED,
            principal_id=command.principal_id,
            correlation_id=issue_identifier(IdKind.CORRELATION),
        )

    # ---- operations ------------------------------------------------------

    def verify(
        self,
        repository: ManagedDocumentRepository,
        store: ManagedByteStore,
        *,
        principal_id: str,
    ) -> IntegrityReport:
        """Compare the rows against the bytes, in both directions.

        The row-to-bytes direction is per Principal, because that is the direction
        a partition can answer. The bytes-to-rows direction is not and cannot be:
        an orphan is bytes that belong to *no* row, so the set it is subtracted
        from is every version identifier the database holds — which is why
        `known_version_identifiers` exists and why it returns identifiers and
        nothing else.
        """
        missing: list[str] = []
        mismatched: list[str] = []
        checked = 0
        for document in repository.documents(
            limit=_ALL_DOCUMENTS, principal_id=principal_id, include_archived=True
        ):
            for version in repository.versions(document.document_id, principal_id=principal_id):
                checked += 1
                if not store.has(version.version_id):
                    missing.append(version.version_id)
                    continue
                if ManagedContent(store.read(version.version_id)).digest != version.content_sha256:
                    mismatched.append(version.version_id)
        known = repository.known_version_identifiers()
        orphans = tuple(sorted(set(store.stored_version_ids()) - known))
        return IntegrityReport(
            versions_checked=checked,
            missing_bytes=tuple(sorted(missing)),
            digest_mismatches=tuple(sorted(mismatched)),
            orphaned_version_ids=orphans,
            unreadable_entries=store.unreadable_entries(),
        )

    def back_up(
        self,
        repository: ManagedDocumentRepository,
        store: ManagedByteStore,
        destination: ManagedByteStore,
        *,
        principal_id: str,
    ) -> BackupSummary:
        """Copy one Principal's versions and their bytes into a second managed root.

        The destination is a `ManagedByteStore`, not a directory, and that is the
        point: a backup writes through exactly the same containment as a live
        write, so "back up somewhere convenient" cannot become a path this product
        writes to without proving it first.
        """
        entries: list[dict[str, object]] = []
        copied = 0
        documents = repository.documents(
            limit=_ALL_DOCUMENTS, principal_id=principal_id, include_archived=True
        )
        for document in documents:
            for version in repository.versions(document.document_id, principal_id=principal_id):
                content = store.read(version.version_id)
                if not destination.has(version.version_id):
                    destination.put(version.version_id, content)
                copied += len(content)
                entries.append(_version_entry(version))
        manifest = json.dumps(
            {
                "manifest_version": _MANIFEST_VERSION,
                "principal_id": principal_id,
                "taken_at": utc_now().isoformat(),
                "versions": entries,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        destination.put_manifest(manifest)
        return BackupSummary(
            documents=len(documents),
            versions=len(entries),
            bytes_copied=copied,
            manifest_sha256=ManagedContent(manifest).digest,
        )

    def restore_from_backup(
        self,
        repository: ManagedDocumentRepository,
        store: ManagedByteStore,
        backup: ManagedByteStore,
        *,
        principal_id: str,
    ) -> RestoreSummary:
        """Rebuild rows and bytes for one Principal from a backup manifest.

        Refuses a manifest taken for a different Principal, so restoring one
        Principal's backup into another's partition is not something a mistyped
        argument can do. Versions are inserted oldest first per document, so the
        `supersedes` chain resolves as it is built.
        """
        document = json.loads(backup.read_manifest().decode("utf-8"))
        if document.get("manifest_version") != _MANIFEST_VERSION:
            raise ValueError("the backup manifest is not a format this build reads")
        if document.get("principal_id") != principal_id:
            raise ValueError("the backup manifest was taken for a different Principal")
        versions = [_version_from_entry(entry) for entry in document["versions"]]
        versions.sort(key=lambda version: (version.document_id, version.version_number))
        already = 0
        restored_bytes = 0
        for version in versions:
            if not store.has(version.version_id):
                content = backup.read(version.version_id)
                store.put(version.version_id, content)
                restored_bytes += len(content)
            else:
                already += 1
            repository.restore_version(version, principal_id=principal_id)
        return RestoreSummary(
            documents=len({version.document_id for version in versions}),
            versions=len(versions),
            bytes_restored=restored_bytes,
            versions_already_present=already,
        )

    # ---- the one write path ----------------------------------------------

    def _write(
        self,
        repository: ManagedDocumentRepository,
        store: ManagedByteStore,
        *,
        principal_id: str,
        document_id: str | None,
        expected_version_number: int | None,
        title: str,
        media_type: str,
        content: ManagedContent,
        idempotency_key: str,
    ) -> ManagedDocumentReceipt:
        """The one write path both `create` and `revise` take. See the module docstring."""
        version_id = issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION)
        request = ManagedWriteRequest(
            document_id=document_id,
            expected_version_number=expected_version_number,
            version_id=version_id,
            title=title,
            media_type=media_type,
            content_sha256=content.digest,
            byte_size=content.byte_size,
            idempotency_key=idempotency_key,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            principal_id=principal_id,
            server_received_at=utc_now(),
        )
        # The replay pre-read happens *after* the request is built, because the
        # payload digest is what decides whether a key in use is a replay or a
        # conflict, and the request is what computes it. A replay returns here
        # having written no bytes at all; a conflict raises here rather than
        # storing a copy of bytes no row will ever name.
        replayed = repository.replay_for(
            idempotency_key, request.payload_digest, principal_id=principal_id
        )
        if replayed is not None:
            return replayed
        # Bytes first, then rows. The module docstring states which failure this
        # ordering leaves and which one it refuses to leave.
        store.put(version_id, content.bytes_)
        return repository.admit(request).receipt


#: What "every document" means to the two operator paths. A bound rather than an
#: unbounded read, because a page size is what the repository's contract takes;
#: it is deliberately far above any local corpus this build holds and the
#: operations document says what to do if a plane ever exceeds it.
_ALL_DOCUMENTS = 100_000


def _version_entry(version: ManagedDocumentVersion) -> dict[str, object]:
    """One version as the manifest records it. Metadata only; the bytes are objects."""
    return {
        "version_id": version.version_id,
        "document_id": version.document_id,
        "version_number": version.version_number,
        "supersedes_version_id": version.supersedes_version_id,
        "owner_principal_id": version.owner_principal_id,
        "title": version.title,
        "media_type": version.media_type,
        "content_sha256": version.content_sha256,
        "byte_size": version.byte_size,
        "idempotency_key": version.idempotency_key,
        "correlation_id": version.correlation_id,
        "recorded_at": ensure_utc(version.recorded_at).isoformat(),
    }


def _version_from_entry(entry: dict[str, object]) -> ManagedDocumentVersion:
    """One manifest entry read back, validated by the domain value it becomes."""
    recorded_at = entry["recorded_at"]
    if not isinstance(recorded_at, str):
        raise ValueError("a manifest entry records when its version was written")
    moment: datetime = ensure_utc(datetime.fromisoformat(recorded_at))
    supersedes = entry["supersedes_version_id"]
    return ManagedDocumentVersion(
        version_id=str(entry["version_id"]),
        document_id=str(entry["document_id"]),
        version_number=int(str(entry["version_number"])),
        supersedes_version_id=None if supersedes is None else str(supersedes),
        owner_principal_id=str(entry["owner_principal_id"]),
        title=str(entry["title"]),
        media_type=str(entry["media_type"]),
        content_sha256=str(entry["content_sha256"]),
        byte_size=int(str(entry["byte_size"])),
        idempotency_key=str(entry["idempotency_key"]),
        correlation_id=str(entry["correlation_id"]),
        recorded_at=moment,
    )
