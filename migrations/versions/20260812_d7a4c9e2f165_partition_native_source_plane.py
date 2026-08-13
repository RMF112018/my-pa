"""Partition the native-owned source plane by authenticated Principal.

The legacy rows carry no trustworthy root from which their Principal can be
derived.  This revision therefore refuses a populated native plane instead of
guessing ownership, deleting rows, or installing a nullable/default partition.
Operators must migrate such a database with an explicit, separately reviewed
ownership map before applying this revision.

Revision ID: d7a4c9e2f165
Revises: b4e8d2c7a613
Created: 2026-08-12 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d7a4c9e2f165"
down_revision: str | None = "b4e8d2c7a613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "native_bridges",
    "native_bridge_observations",
    "native_source_accounts",
    "native_source_buckets",
    "native_discovery_snapshots",
    "native_configuration_revisions",
    "native_configuration_buckets",
    "native_preflight_observations",
    "native_admission_authorities",
    "native_source_review_routes",
    "native_sync_runs",
    "native_bucket_runs",
    "native_sync_jobs",
    "native_checkpoints",
    "source_version_evidence",
    "source_observations",
    "source_memberships",
    "native_watcher_simulations",
    "native_simulation_receipts",
    "native_live_activation_gates",
)

_UNIQUE_KEYS = (
    ("native_bridges", "native_bridge_belongs_to_principal", "principal_id,bridge_id"),
    ("native_source_accounts", "native_account_belongs_to_principal", "principal_id,account_id"),
    ("native_source_buckets", "native_bucket_belongs_to_principal", "principal_id,bucket_id"),
    (
        "native_configuration_revisions",
        "native_configuration_belongs_to_principal",
        "principal_id,configuration_id,revision",
    ),
    (
        "native_configuration_buckets",
        "native_configuration_bucket_belongs_to_principal",
        "principal_id,configuration_id,revision,bucket_id",
    ),
    (
        "native_admission_authorities",
        "native_authority_belongs_to_principal",
        "principal_id,authority_id",
    ),
    ("native_sync_runs", "native_run_belongs_to_principal", "principal_id,run_id"),
    ("native_sync_jobs", "native_job_belongs_to_principal", "principal_id,job_id"),
    ("native_checkpoints", "native_checkpoint_belongs_to_principal", "principal_id,checkpoint_id"),
    (
        "native_watcher_simulations",
        "native_simulation_belongs_to_principal",
        "principal_id,simulation_id,sequence",
    ),
)

# child, name, local columns, parent, parent columns. Frozen literals: this
# historical revision must not derive its schema from the live declaration.
_PARTITION_FKS = (
    (
        "native_bridge_observations",
        "native_bridge_observation_stays_in_principal",
        "principal_id,bridge_id",
        "native_bridges",
        "principal_id,bridge_id",
    ),
    (
        "native_source_accounts",
        "native_account_bridge_stays_in_principal",
        "principal_id,bridge_id",
        "native_bridges",
        "principal_id,bridge_id",
    ),
    (
        "native_source_buckets",
        "native_bucket_account_stays_in_principal",
        "principal_id,account_id",
        "native_source_accounts",
        "principal_id,account_id",
    ),
    (
        "native_source_buckets",
        "native_bucket_parent_stays_in_principal",
        "principal_id,parent_bucket_id",
        "native_source_buckets",
        "principal_id,bucket_id",
    ),
    (
        "native_discovery_snapshots",
        "native_discovery_bridge_stays_in_principal",
        "principal_id,bridge_id",
        "native_bridges",
        "principal_id,bridge_id",
    ),
    (
        "native_configuration_revisions",
        "native_configuration_bridge_stays_in_principal",
        "principal_id,bridge_id",
        "native_bridges",
        "principal_id,bridge_id",
    ),
    (
        "native_configuration_buckets",
        "native_selected_configuration_stays_in_principal",
        "principal_id,configuration_id,revision",
        "native_configuration_revisions",
        "principal_id,configuration_id,revision",
    ),
    (
        "native_configuration_buckets",
        "native_selected_bucket_stays_in_principal",
        "principal_id,bucket_id",
        "native_source_buckets",
        "principal_id,bucket_id",
    ),
    (
        "native_preflight_observations",
        "native_preflight_stays_in_principal",
        "principal_id,configuration_id,configuration_revision,bucket_id",
        "native_configuration_buckets",
        "principal_id,configuration_id,revision,bucket_id",
    ),
    (
        "native_admission_authorities",
        "native_authority_bridge_stays_in_principal",
        "principal_id,bridge_id",
        "native_bridges",
        "principal_id,bridge_id",
    ),
    (
        "native_admission_authorities",
        "native_authority_selection_stays_in_principal",
        "principal_id,configuration_id,configuration_revision,bucket_id",
        "native_configuration_buckets",
        "principal_id,configuration_id,revision,bucket_id",
    ),
    (
        "native_sync_runs",
        "native_run_configuration_stays_in_principal",
        "principal_id,configuration_id,configuration_revision",
        "native_configuration_revisions",
        "principal_id,configuration_id,revision",
    ),
    (
        "native_sync_runs",
        "native_run_bridge_stays_in_principal",
        "principal_id,bridge_id",
        "native_bridges",
        "principal_id,bridge_id",
    ),
    (
        "native_bucket_runs",
        "native_bucket_run_stays_in_principal",
        "principal_id,run_id",
        "native_sync_runs",
        "principal_id,run_id",
    ),
    (
        "native_bucket_runs",
        "native_bucket_run_bucket_stays_in_principal",
        "principal_id,bucket_id",
        "native_source_buckets",
        "principal_id,bucket_id",
    ),
    (
        "native_sync_jobs",
        "native_job_bucket_stays_in_principal",
        "principal_id,bucket_id",
        "native_source_buckets",
        "principal_id,bucket_id",
    ),
    (
        "native_sync_jobs",
        "native_job_selection_stays_in_principal",
        "principal_id,configuration_id,configuration_revision,bucket_id",
        "native_configuration_buckets",
        "principal_id,configuration_id,revision,bucket_id",
    ),
    (
        "native_sync_jobs",
        "native_job_run_stays_in_principal",
        "principal_id,run_id",
        "native_sync_runs",
        "principal_id,run_id",
    ),
    (
        "native_checkpoints",
        "native_checkpoint_job_stays_in_principal",
        "principal_id,job_id",
        "native_sync_jobs",
        "principal_id,job_id",
    ),
    (
        "native_checkpoints",
        "native_checkpoint_bucket_stays_in_principal",
        "principal_id,bucket_id",
        "native_source_buckets",
        "principal_id,bucket_id",
    ),
    (
        "native_checkpoints",
        "native_checkpoint_authority_stays_in_principal",
        "principal_id,admission_authority_id",
        "native_admission_authorities",
        "principal_id,authority_id",
    ),
    (
        "native_checkpoints",
        "native_checkpoint_chain_stays_in_principal",
        "principal_id,previous_checkpoint_id",
        "native_checkpoints",
        "principal_id,checkpoint_id",
    ),
    (
        "source_observations",
        "source_observation_bucket_stays_in_principal",
        "principal_id,bucket_id",
        "native_source_buckets",
        "principal_id,bucket_id",
    ),
    (
        "source_memberships",
        "source_membership_bucket_stays_in_principal",
        "principal_id,parent_bucket_id",
        "native_source_buckets",
        "principal_id,bucket_id",
    ),
    (
        "native_watcher_simulations",
        "native_simulation_bucket_stays_in_principal",
        "principal_id,bucket_id",
        "native_source_buckets",
        "principal_id,bucket_id",
    ),
    (
        "native_simulation_receipts",
        "native_simulation_receipt_stays_in_principal",
        "principal_id,simulation_id,simulation_sequence",
        "native_watcher_simulations",
        "principal_id,simulation_id,sequence",
    ),
    (
        "native_simulation_receipts",
        "native_simulation_checkpoint_stays_in_principal",
        "principal_id,checkpoint_id",
        "native_checkpoints",
        "principal_id,checkpoint_id",
    ),
    (
        "native_live_activation_gates",
        "native_live_gate_bucket_stays_in_principal",
        "principal_id,bucket_id",
        "native_source_buckets",
        "principal_id,bucket_id",
    ),
)


def upgrade() -> None:
    # Check each table explicitly so the first legacy row aborts the transaction.
    for table in _TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM knowledge.{table}) THEN "  # noqa: S608
            f"RAISE EXCEPTION 'cannot infer Principal for populated knowledge.{table}'; "
            "END IF; END $$"
        )
        op.execute(f"ALTER TABLE knowledge.{table} ADD COLUMN principal_id TEXT NOT NULL")
        op.execute(
            f"ALTER TABLE knowledge.{table} ADD CONSTRAINT "
            "principal_id_is_an_opaque_identifier CHECK "
            "(principal_id ~ '^prn_[A-Za-z0-9]{8,64}$')"
        )
    for table, name, columns in _UNIQUE_KEYS:
        op.create_unique_constraint(name, table, columns.split(","), schema="knowledge")
    op.drop_constraint(
        "a_native_bridge_identity_is_stable",
        "native_bridges",
        schema="knowledge",
        type_="unique",
    )
    op.create_unique_constraint(
        "a_native_bridge_identity_is_stable",
        "native_bridges",
        ["principal_id", "protocol_version", "label"],
        schema="knowledge",
    )
    op.drop_constraint(
        "source_version_evidence_is_idempotent",
        "source_version_evidence",
        schema="knowledge",
        type_="unique",
    )
    op.create_unique_constraint(
        "source_version_evidence_is_idempotent",
        "source_version_evidence",
        ["principal_id", "version_id", "evidence_kind", "payload_sha256"],
        schema="knowledge",
    )
    for table, name, local, parent, remote in _PARTITION_FKS:
        op.create_foreign_key(
            name,
            table,
            parent,
            local.split(","),
            remote.split(","),
            source_schema="knowledge",
            referent_schema="knowledge",
        )


def downgrade() -> None:
    for table, name, *_ in reversed(_PARTITION_FKS):
        op.drop_constraint(name, table, schema="knowledge", type_="foreignkey")
    for table, name, _ in reversed(_UNIQUE_KEYS):
        op.drop_constraint(name, table, schema="knowledge", type_="unique")
    op.drop_constraint(
        "source_version_evidence_is_idempotent",
        "source_version_evidence",
        schema="knowledge",
        type_="unique",
    )
    op.create_unique_constraint(
        "source_version_evidence_is_idempotent",
        "source_version_evidence",
        ["version_id", "evidence_kind", "payload_sha256"],
        schema="knowledge",
    )
    op.drop_constraint(
        "a_native_bridge_identity_is_stable",
        "native_bridges",
        schema="knowledge",
        type_="unique",
    )
    op.create_unique_constraint(
        "a_native_bridge_identity_is_stable",
        "native_bridges",
        ["protocol_version", "label"],
        schema="knowledge",
    )
    for table in reversed(_TABLES):
        op.execute(
            f"ALTER TABLE knowledge.{table} DROP CONSTRAINT principal_id_is_an_opaque_identifier"
        )
        op.execute(f"ALTER TABLE knowledge.{table} DROP COLUMN principal_id")
