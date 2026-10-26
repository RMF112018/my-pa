"""Shared database harness for the record lineage S1 Issue-plane tests.

A helper module, not a test module: pytest does not collect it. It composes a
real `ApplicationService` over PostgreSQL with every plane the Issue tests write
or read, and `lineage_enabled` stated explicitly (S1 contract section 7.5:
Python database tests compose the service with the switch on, except the
switch-off tests, which pass `lineage_enabled=False`).

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import Engine, func, select

from my_pa.application.commands import Command, CreateIssue, CreateProject
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import (
    issue_project_membership_events,
    issue_revisions,
    lineage_evidence_anchors,
    lineage_write_requests,
    project_situations,
    situations,
)
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

__all__ = [
    "OTHER_PRINCIPAL",
    "PRINCIPAL",
    "REMOTE_CLIENT",
    "WHEN",
    "LineageRuntime",
    "lineage_row_counts",
]

PRINCIPAL: Final = "prn_lineageissue0001"
OTHER_PRINCIPAL: Final = "prn_lineageissue0002"
REMOTE_CLIENT: Final = "synthetic-lineage-remote-client"
WHEN: Final = datetime(2026, 10, 17, 12, tzinfo=UTC)
LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)

#: The Issue-plane tables a refused write must leave untouched.
_LINEAGE_TABLES: Final = (
    issue_revisions,
    issue_project_membership_events,
    lineage_evidence_anchors,
    lineage_write_requests,
    project_situations,
)


class LineageRuntime:
    """`ApplicationService` over PostgreSQL with the planes the Issue tests touch."""

    def __init__(
        self,
        url: str,
        *,
        lineage_enabled: bool = True,
        knowledge_operator_review_client_ids: frozenset[str] = frozenset(),
        knowledge_manager_client_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.engine, audit=audit, relationship_memory_enabled=True)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            task_management_unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(self.engine),
            commitment_management_unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(
                self.engine
            ),
            relationship_intelligence_enabled=True,
            relationship_intelligence_writes_enabled=True,
            relationship_memory_enabled=True,
            lineage_enabled=lineage_enabled,
            knowledge_operator_review_client_ids=knowledge_operator_review_client_ids,
            knowledge_manager_client_ids=knowledge_manager_client_ids,
        )

    def close(self) -> None:
        self.engine.dispose()
        self.audit_engine.dispose()

    def invoke(
        self,
        command: Command,
        *,
        principal_id: str = PRINCIPAL,
        purpose: Purpose | None = None,
        remote_client: str | None = None,
        surface: OperatorSurface | None = None,
        grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
    ) -> ResponseEnvelope:
        """One request. `remote_client` is an ordinary remote OAuth client with the grant.

        A local call carries no operator surface unless `surface` is given; the
        CLI and the HTTP gateway stamp one, which is what makes a caller
        `local_operator` (S1 contract section 6.1). `grants` replaces a remote
        client's one grant with an exact set (S3.1: a remote writer that sees
        the families its write names, section 6.4).
        """
        capability = command.capability
        chosen = purpose or sorted(permitted_purposes(capability))[0]
        remote = remote_client is not None
        if grants is None:
            grants = frozenset({(capability, chosen)}) if remote else None
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=chosen,
                principal_id=principal_id,
                requested_at=WHEN,
            ),
            command,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            transport=CaptureTransport.REMOTE_CLIENT if remote else CaptureTransport.LOCAL,
            capability_grants=grants,
            authenticated_client_id=remote_client,
            operator_surface=surface,
        )

    def ok(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        envelope = self.invoke(command, **kwargs)
        assert envelope.error is None, (command.capability.value, envelope.error)
        dumped = envelope.to_canonical_dict()["result"]
        assert isinstance(dumped, dict)
        return dumped

    def refused(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        envelope = self.invoke(command, **kwargs)
        assert envelope.error is not None, command.capability.value
        error = envelope.to_canonical_dict()["error"]
        assert isinstance(error, dict)
        return error

    # --- seeds -------------------------------------------------------------

    def issue(self, key: str, *, principal_id: str = PRINCIPAL, title: str = "") -> str:
        written = self.ok(
            CreateIssue(
                title=title or f"Synthetic issue {key}", idempotency_key=f"lineage-issue-{key}"
            ),
            principal_id=principal_id,
        )
        return str(written["issue"]["issue_id"])

    def project(self, key: str, *, principal_id: str = PRINCIPAL) -> str:
        written = self.ok(
            CreateProject(name=f"Synthetic project {key}", idempotency_key=f"lineage-prj-{key}"),
            principal_id=principal_id,
        )
        return str(written["project_id"])


def lineage_row_counts(engine: Engine) -> Mapping[str, int]:
    """Row counts of the Issue-plane tables and of Issue `situations` rows."""
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for table in _LINEAGE_TABLES:
            counts[table.name] = int(
                connection.execute(select(func.count()).select_from(table)).scalar_one()
            )
        counts["issue_situations"] = int(
            connection.execute(
                select(func.count())
                .select_from(situations)
                .where(situations.c.kind == "issue_workstream")
            ).scalar_one()
        )
    return counts


#: Exported for tests that name the capability set the harness composes.
ISSUE_CAPABILITIES: Final = frozenset(
    capability for capability in Capability if capability.value.startswith("issues.")
)
