"""Read a fixed smoke-fixture plan and write only its append-only markers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import Connection, RowMapping, Table, or_, select, union_all
from sqlalchemy.dialects.postgresql import insert

from my_pa.infrastructure.persistence.principal_scope import capture_context, partition_criterion
from my_pa.infrastructure.persistence.tables import (
    communication_mailbox_items,
    communication_messages,
    communication_observations,
    ingest_snapshots,
    ingest_sources,
    projects,
    record_links,
    schedule_activities,
    schedule_baselines,
    schedule_p6_snapshots,
    schedule_publications,
    schedule_scenario_outputs,
    schedule_scenario_versions,
    schedule_scenarios,
    smoke_fixture_retirements,
)


@dataclass(frozen=True, slots=True)
class SmokeFixtureTarget:
    message_id: str
    source_id: str
    publication_id: str
    scenario_id: str
    expected_source_sha256: str
    expected_xer_sha256: str
    apply_plan_sha256: str | None


class RetirementRefusalError(ValueError):
    """A closed exit without changes or disclosure of record contents."""


def _require(valid: bool, reason: str) -> None:
    if not valid:
        raise RetirementRefusalError(reason)


def _plan(connection: Connection, principal: str, target: SmokeFixtureTarget) -> list[str]:
    context = capture_context(principal)

    columns = {
        communication_messages: (
            "mailbox_ref",
            "first_snapshot_id",
            "text_snapshot_id",
            "latest_snapshot_id",
        ),
        ingest_sources: ("consumer", "workspace_id", "path_prefix", "file_pattern", "enabled"),
        ingest_snapshots: ("snapshot_id", "file_sha256", "status"),
        communication_observations: ("item_id",),
        communication_mailbox_items: ("item_id",),
        schedule_publications: (
            "publication_id",
            "project_id",
            "series_id",
            "p6_snapshot_id",
            "source_format",
            "status",
        ),
        schedule_scenarios: ("project_id", "series_id", "origin_publication_id", "name"),
        projects: ("project_id", "state", "name", "description"),
        schedule_scenario_versions: ("version_id",),
        schedule_p6_snapshots: ("sha256",),
    }

    def rows(table: Table, **expected: object) -> list[RowMapping]:
        statement = (
            select(*(table.c[key] for key in columns[table]))
            .where(
                partition_criterion(table, context),
                *(table.c[key] == value for key, value in expected.items()),
            )
            .limit(2)
        )
        if target.apply_plan_sha256 and table in (ingest_sources, projects):
            statement = statement.with_for_update()
        return list(connection.execute(statement).mappings())

    def one(table: Table, **expected: object) -> RowMapping:
        found = rows(table, **expected)
        _require(len(found) == 1, "fixture_identity_mismatch")
        return found[0]

    message = one(communication_messages, message_id=target.message_id)
    source = one(ingest_sources, ingest_source_id=target.source_id)
    _require(
        source.consumer == "communications_evidence_v2"
        and source.workspace_id == "mcp"
        and source.path_prefix.startswith("mypa-smoke-wp5-")
        and source.path_prefix.endswith("/")
        and source.file_pattern == "synthetic-title-match.json"
        and not source.enabled
        and message.mailbox_ref.startswith("synthetic_wp5_"),
        "communications_fixture_mismatch",
    )
    snapshots = rows(ingest_snapshots, ingest_source_id=target.source_id)
    _require(
        len(snapshots) == 1
        and snapshots[0].status == "ingested"
        and snapshots[0].file_sha256 == target.expected_source_sha256
        and snapshots[0].snapshot_id == message.first_snapshot_id
        and snapshots[0].snapshot_id == message.text_snapshot_id
        and snapshots[0].snapshot_id == message.latest_snapshot_id,
        "nonexclusive_source",
    )
    observations = rows(communication_observations, snapshot_id=snapshots[0].snapshot_id)
    items = rows(communication_mailbox_items, message_id=target.message_id)
    _require(
        len(items) == 1
        and len(observations) == 1
        and observations[0].item_id == items[0].item_id
        and len(rows(communication_observations, item_id=items[0].item_id)) == 1,
        "nonexclusive_communication",
    )

    publication = one(schedule_publications, publication_id=target.publication_id)
    scenario = one(schedule_scenarios, scenario_id=target.scenario_id)
    project = one(projects, project_id=publication.project_id)
    xer = one(schedule_p6_snapshots, snapshot_id=publication.p6_snapshot_id)
    _require(
        project.state == "closed"
        and project.description == "Dedicated synthetic WP5 and P6 smoke fixture"
        and project.name.startswith("Qzxsmokefixture")
        and publication.source_format == "p6_xer"
        and publication.status == "complete"
        and xer.sha256 == target.expected_xer_sha256
        and scenario.project_id == project.project_id
        and scenario.series_id == publication.series_id
        and scenario.origin_publication_id == publication.publication_id
        and scenario.name == project.name + " parallel relationships",
        "schedule_fixture_mismatch",
    )
    _require(
        len(rows(schedule_publications, series_id=publication.series_id)) == 1
        and len(rows(schedule_scenarios, series_id=publication.series_id)) == 1
        and len(rows(schedule_publications, project_id=project.project_id)) == 1
        and len(rows(schedule_scenarios, project_id=project.project_id)) == 1,
        "nonexclusive_schedule",
    )
    versions = rows(schedule_scenario_versions, scenario_id=target.scenario_id)
    _require(len(versions) == 1, "nonexclusive_scenario")
    ids = sorted(
        (
            target.message_id,
            target.source_id,
            target.publication_id,
            target.scenario_id,
            publication.series_id,
            versions[0].version_id,
        )
    )
    activities = schedule_activities
    baselines = schedule_baselines
    outputs = schedule_scenario_outputs
    dependent_endpoints = union_all(
        select(activities.c.schedule_activity_id).where(
            partition_criterion(activities, context),
            activities.c.series_id == publication.series_id,
        ),
        select(baselines.c.baseline_id).where(
            partition_criterion(baselines, context),
            baselines.c.series_id == publication.series_id,
        ),
        select(outputs.c.output_id).where(
            partition_criterion(outputs, context),
            outputs.c.version_id == versions[0].version_id,
        ),
    )
    link = connection.execute(
        select(record_links.c.link_id)
        .where(
            partition_criterion(record_links, context),
            or_(
                record_links.c.from_id.in_(ids),
                record_links.c.to_id.in_(ids),
                record_links.c.from_id.in_(dependent_endpoints),
                record_links.c.to_id.in_(dependent_endpoints),
            ),
        )
        .limit(1)
    ).first()
    _require(link is None, "fixture_has_record_links")
    _require(
        not rows(schedule_scenarios, origin_version_id=versions[0].version_id),
        "fixture_has_scenario_dependents",
    )
    return ids


def retire_smoke_fixtures(
    connection: Connection,
    principal: str,
    expected: tuple[str, str, str],
    target: SmokeFixtureTarget,
) -> dict[str, str | list[str]]:
    ids = _plan(connection, principal, target)
    digest = hashlib.sha256(
        json.dumps(
            (
                expected,
                principal,
                ids,
                target.expected_source_sha256,
                target.expected_xer_sha256,
            ),
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    table = smoke_fixture_retirements
    condition = (
        partition_criterion(table, capture_context(principal)),
        table.c.record_id.in_(ids),
    )
    if target.apply_plan_sha256 is not None:
        _require(digest == target.apply_plan_sha256, "preview_digest_mismatch")
        _require(
            not connection.execute(
                select(table.c.record_id).where(*condition, table.c.plan_sha256 != digest)
            ).first(),
            "retirement_conflict",
        )
        connection.execute(
            insert(table)
            .values(
                [
                    {
                        "principal_id": principal,
                        "record_id": record_id,
                        "plan_sha256": digest,
                    }
                    for record_id in ids
                ]
            )
            .on_conflict_do_nothing(index_elements=[table.c.principal_id, table.c.record_id])
        )
    marked = sorted(connection.execute(select(table.c.record_id).where(*condition)).scalars())
    _require(not target.apply_plan_sha256 or marked == ids, "incomplete_retirement")
    return {"plan_sha256": digest, "ids": ids, "retired": marked}
