"""What still holds user-owned rows with no principal partition, exactly.

WP-04's governing invariant is that every durable user-owned record is scoped to
the authenticated Principal. WP-04 did not achieve that everywhere, and the worst
available outcome would be for the parts it did not reach to be *quiet* — a suite
that goes green while three planes of user-owned data carry no partition at all
tells a reader the opposite of the truth.

So the residual is a registry, and the registry is checked against reality rather
than written once and left. Every table the live declaration holds is either
partitioned or named here with the reason it is not and what would close it. The
assertion is exact in both directions: a new unpartitioned table fails the build,
and a table that *gains* a partition without leaving this file fails it too, so
the registry cannot outlive what it describes.

Two planes make up almost all of it, while NAS-07A now measures the former
native residual as a positive partition contract:

* **the native-source plane** — twenty-two native-owned control/evidence tables now
  carry a required Principal partition. The shared `source_objects` and
  `source_object_versions` identities remain rooted in an operator-registered
  source and native paths may reach them only through partitioned evidence or
  membership. Advisory-lock scoping is the separate NAS-07A2 runtime slice;
* **the derived-capture plane** — the rows the pipeline derives *from* a capture
  version. The capture version itself is partitioned (`owner_principal_id`,
  revision `e7f3a9c2d514`); its derived text, spans, proposals, classifications
  and mentions are not, and `proposals.version_content` will return any
  Principal's capture text given only a `version_id`;
* **the 484-table migration target** of revision `1e6c0a94f3b7`, in the `core`,
  `procore`, `financial`, `schedule`, `email`, `construction`, and `calendar`
  schemas. Those tables are not in the live declaration at all and no application
  read path reaches them, so nothing here can measure them — which is recorded
  as an unmeasured residual rather than as an absence of risk.

Nothing here opens a connection or touches a database. It reads the declaration.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Table

from my_pa.infrastructure.persistence.native_sources import (
    SqlNativeBaselineStore,
    SqlNativeReviewProposalRouter,
    SqlNativeSourceControlStore,
    SqlNativeSourceRepository,
)
from my_pa.infrastructure.persistence.principal_scope import MissingPrincipalContextError
from my_pa.infrastructure.persistence.tables import METADATA

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"

PARTITION_COLUMNS: Final = ("principal_id", "owner_principal_id")

#: Every table in the live declaration that carries no principal partition, with
#: what holds ownership instead and what closing it would take.
#:
#: **Not an exemption list.** An entry is a statement that this table can hold a
#: row belonging to one Principal which no query is structurally prevented from
#: returning to another. Some are held by a transitive owner and an authorization
#: check above them; the reason says which.
UNPARTITIONED_USER_OWNED: Final = {
    # --- the derived-capture plane ---------------------------------------
    "capture_processing_text": (
        "P-02's normalized text, derived from a partitioned `capture_versions` "
        "row. Reached only through a `version_id` the pipeline already resolved."
    ),
    "capture_spans": "span offsets into `capture_processing_text`; same chain.",
    "capture_stage_results": "per-stage receipts keyed by `version_id`; same chain.",
    "capture_proposals": "proposals derived from one version's text; same chain.",
    "capture_proposal_spans": "span citations on a proposal; same chain.",
    "capture_classifications": "the classifier's output for one version; same chain.",
    "capture_entity_mentions": "entity mentions found in one version's text; same chain.",
    "capture_receipts": (
        "the admission receipt for one version. Read by receipt id, which the "
        "admitting request is the only thing that learns."
    ),
    "capture_context_links": (
        "links a capture to the source object it was captured against. Written "
        "inside the admitting transaction; no read path takes a link id."
    ),
    "capture_conversations": (
        "the Conversation Log a capture may seed. Keyed by `capture_id`, whose "
        "own table is partitioned."
    ),
    # --- the enrollment / extraction plane --------------------------------
    "sources": "a configured source is operator-registered, not user-owned.",
    "source_objects": "objects a source observed; the source is operator-registered.",
    "source_object_versions": "versions of those objects; same.",
    "enrollment_objects": (
        "the object set one enrollment names. Ownership is the enrollment's "
        "`principal_id`; `application.authorization` resolves enrollment ids "
        "only within the caller's own enrollments."
    ),
    "extractions": "extraction outcomes under one enrollment; same chain.",
    "quarantine_records": "quarantined objects under one enrollment; same chain.",
    "coverage_limitations": "coverage gaps under one enrollment; same chain.",
    # --- the RI-ENT-WP-04 project-role/discipline taxonomy plane ----------
    "entity_role_types": (
        "a global, shared reference vocabulary of project-role codes -- like a "
        "lookup table, not user-owned data. Every row is seeded by the "
        "`f5b06925857e` migration itself; no write path lets a Principal add, "
        "change, or read one row as if it were their own."
    ),
    "entity_discipline_types": (
        "the same global, shared reference vocabulary shape as "
        "`entity_role_types`, for the independent discipline axis; same reason."
    ),
}

NATIVE_PARTITIONED: Final = frozenset(
    {
        "native_bridges",
        "native_apple_bridge_credentials",
        "native_apple_read_grants",
        "native_bridge_observations",
        "native_source_accounts",
        "native_source_buckets",
        "native_source_review_routes",
        "native_discovery_snapshots",
        "native_configuration_revisions",
        "native_configuration_buckets",
        "native_sync_runs",
        "native_bucket_runs",
        "native_sync_jobs",
        "native_checkpoints",
        "native_watcher_simulations",
        "native_simulation_receipts",
        "native_live_activation_gates",
        "native_admission_authorities",
        "native_preflight_observations",
        "source_version_evidence",
        "source_observations",
        "source_memberships",
    }
)

#: NAS-07A2 requires every native serialization lock to occupy the authenticated
#: Principal's namespace as well as the resource-specific namespace.
GLOBAL_ADVISORY_LOCK_MODULE: Final = (
    PACKAGE / "infrastructure" / "persistence" / "native_sources.py"
)
GLOBAL_ADVISORY_LOCK_CALLS: Final = 3

#: Revision `1e6c0a94f3b7` creates 484 tables across seven schemas that the live
#: declaration does not describe and no application module reads. Recorded so the
#: residual is legible; the number is read from the revision's own docstring, so
#: it cannot drift from what the revision says it does.
MIGRATION_TARGET_REVISION: Final = "1e6c0a94f3b7"
MIGRATION_TARGET_SCHEMAS: Final = (
    "core",
    "procore",
    "financial",
    "schedule",
    "email",
    "construction",
    "calendar",
)


def _unpartitioned() -> dict[str, Table]:
    return {
        table.name: table
        for table in METADATA.tables.values()
        if not any(column in table.c for column in PARTITION_COLUMNS)
    }


def test_the_declaration_holds_both_partitioned_and_unpartitioned_tables() -> None:
    """Guards the exactness assertion below against a metadata that parsed empty."""
    total = len(METADATA.tables)
    unpartitioned = len(_unpartitioned())
    assert total >= 60, f"the declaration holds {total} tables; the scan is not reading it"
    assert 0 < unpartitioned < total, (
        "every table is either partitioned or unpartitioned, which means the "
        "column detector is answering the same way for all of them"
    )


def test_the_unpartitioned_registry_matches_the_declaration_exactly() -> None:
    """The residual is what the schema says it is, in both directions."""
    measured = set(_unpartitioned())
    registered = set(UNPARTITIONED_USER_OWNED)

    unregistered = sorted(measured - registered)
    assert unregistered == [], (
        f"{unregistered} hold rows with no principal partition and are not "
        "registered. Add the partition, or add the table here with what holds "
        "ownership instead — a user-owned table that is quietly unpartitioned is "
        "the outcome this registry exists to prevent"
    )

    stale = sorted(registered - measured)
    assert stale == [], (
        f"{stale} are registered as unpartitioned but now carry a partition "
        "column. Remove them from the registry; a residual list that outlives "
        "the residual stops being a measurement of anything"
    )


def test_every_registered_reason_says_something() -> None:
    """A registry of empty strings would satisfy the exactness test perfectly."""
    empty = sorted(name for name, reason in UNPARTITIONED_USER_OWNED.items() if len(reason) < 30)
    assert empty == [], f"{empty} are registered with no usable reason"


def test_the_native_owned_plane_is_principal_partitioned() -> None:
    """NAS-07A closes the native plane without claiming shared source identity."""
    assert len(NATIVE_PARTITIONED) == 22
    for name in NATIVE_PARTITIONED:
        table = METADATA.tables[f"knowledge.{name}"]
        assert table.c.principal_id.nullable is False

    # These identities remain global beneath operator-registered sources. Native
    # reads reach them only through a partitioned evidence/membership row; adding
    # nullable/default ownership here would merely disguise that relationship.
    for name in ("source_objects", "source_object_versions"):
        assert "principal_id" not in METADATA.tables[f"knowledge.{name}"].c
    assert "operator-registered" in UNPARTITIONED_USER_OWNED["source_objects"]
    assert "same" in UNPARTITIONED_USER_OWNED["source_object_versions"]


def test_the_native_source_advisory_lock_namespace_is_principal_scoped() -> None:
    source = GLOBAL_ADVISORY_LOCK_MODULE.read_text(encoding="utf-8")
    calls = re.findall(r"pg_advisory_xact_lock\(", source)
    assert len(calls) == GLOBAL_ADVISORY_LOCK_CALLS, (
        f"{GLOBAL_ADVISORY_LOCK_MODULE.name} now takes {len(calls)} advisory "
        f"locks, not {GLOBAL_ADVISORY_LOCK_CALLS}; the residual entry describes a "
        "shape that no longer exists"
    )
    normalized = re.sub(r"\s+", "", source)
    assert normalized.count(":principal_id||':'||:") == GLOBAL_ADVISORY_LOCK_CALLS
    assert source.count('"principal_id": self._partition_identity') >= GLOBAL_ADVISORY_LOCK_CALLS


def test_native_persistence_constructors_fail_closed_without_context() -> None:
    sentinel = object()
    constructors = (
        lambda: SqlNativeSourceRepository(sentinel, None),  # type: ignore[arg-type]
        lambda: SqlNativeBaselineStore(sentinel, None),  # type: ignore[arg-type]
        lambda: SqlNativeSourceControlStore(sentinel, None),  # type: ignore[arg-type]
        lambda: SqlNativeReviewProposalRouter(
            sentinel,
            lambda _version_id: (),
            None,  # type: ignore[arg-type]
        ),
    )
    for construct in constructors:
        with pytest.raises(MissingPrincipalContextError):
            construct()


def test_the_484_table_migration_target_is_recorded_as_unmeasured() -> None:
    """The residual nothing in this repository can measure, named so it is legible.

    Those tables live in `migrations/sql/target_tables.up.sql`, are created in
    seven schemas the live declaration does not describe, and are read by no
    application module — so they are vacuous today rather than safe, and the
    difference is worth writing down.
    """
    revision = next((ROOT / "migrations" / "versions").glob(f"*_{MIGRATION_TARGET_REVISION}_*.py"))
    docstring = revision.read_text(encoding="utf-8")
    assert "484 tables" in docstring, (
        "the target-table revision no longer says how many tables it creates; "
        "this residual is recorded against that number"
    )

    # No application module reads any of the seven schemas — the claim that makes
    # this residual vacuous rather than open. Measured, not asserted.
    reaching = sorted(
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        for schema in MIGRATION_TARGET_SCHEMAS
        if re.search(rf'["\']{schema}\.', path.read_text(encoding="utf-8"))
    )
    assert reaching == [], (
        f"{reaching} name one of the migration-target schemas {MIGRATION_TARGET_SCHEMAS}. "
        "Those 484 tables have no principal partition and were recorded as "
        "unreachable; a read path into them is a new, unmeasured exposure"
    )
