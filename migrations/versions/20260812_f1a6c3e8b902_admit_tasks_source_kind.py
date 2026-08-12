"""Admit Apple Reminders/Tasks as a read-only native source kind.

Revision ID: f1a6c3e8b902
Revises: c8f4a2d9e761
Created: 2026-08-12 05:45:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f1a6c3e8b902"
down_revision: str | None = "c8f4a2d9e761"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.sources DROP CONSTRAINT provider_kind_is_known;
        ALTER TABLE knowledge.sources ADD CONSTRAINT provider_kind_is_known
          CHECK (provider_kind IN
            ('apple_calendar', 'apple_contacts', 'apple_mail', 'apple_tasks', 'fixture'));
        ALTER TABLE knowledge.source_objects DROP CONSTRAINT kind_is_known;
        ALTER TABLE knowledge.source_objects ADD CONSTRAINT kind_is_known
          CHECK (kind IN
            ('calendar_event', 'contact', 'container', 'file', 'mail_message', 'task'));

        ALTER TABLE knowledge.source_version_evidence
          DROP CONSTRAINT source_version_evidence_evidence_kind_check;
        ALTER TABLE knowledge.source_version_evidence
          ADD CONSTRAINT source_evidence_kind_is_known
          CHECK (evidence_kind IN ('calendar_event', 'contact', 'mail_message', 'task'));

        ALTER TABLE knowledge.native_source_accounts
          DROP CONSTRAINT native_source_accounts_source_kind_check;
        ALTER TABLE knowledge.native_source_accounts
          ADD CONSTRAINT native_account_source_kind_is_known
          CHECK (source_kind IN ('calendar', 'contacts', 'mail', 'tasks'));
        ALTER TABLE knowledge.native_source_buckets
          DROP CONSTRAINT native_source_buckets_source_kind_check;
        ALTER TABLE knowledge.native_source_buckets
          ADD CONSTRAINT native_bucket_source_kind_is_known
          CHECK (source_kind IN ('calendar', 'contacts', 'mail', 'tasks'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge.native_source_buckets
          DROP CONSTRAINT native_bucket_source_kind_is_known;
        ALTER TABLE knowledge.native_source_buckets
          ADD CONSTRAINT native_source_buckets_source_kind_check
          CHECK (source_kind IN ('calendar', 'contacts', 'mail'));
        ALTER TABLE knowledge.native_source_accounts
          DROP CONSTRAINT native_account_source_kind_is_known;
        ALTER TABLE knowledge.native_source_accounts
          ADD CONSTRAINT native_source_accounts_source_kind_check
          CHECK (source_kind IN ('calendar', 'contacts', 'mail'));

        ALTER TABLE knowledge.source_version_evidence
          DROP CONSTRAINT source_evidence_kind_is_known;
        ALTER TABLE knowledge.source_version_evidence
          ADD CONSTRAINT source_version_evidence_evidence_kind_check
          CHECK (evidence_kind IN ('calendar_event', 'contact', 'mail_message'));
        ALTER TABLE knowledge.source_objects DROP CONSTRAINT kind_is_known;
        ALTER TABLE knowledge.source_objects ADD CONSTRAINT kind_is_known
          CHECK (kind IN ('calendar_event', 'contact', 'container', 'file', 'mail_message'));
        ALTER TABLE knowledge.sources DROP CONSTRAINT provider_kind_is_known;
        ALTER TABLE knowledge.sources ADD CONSTRAINT provider_kind_is_known
          CHECK (provider_kind IN ('apple_calendar', 'apple_contacts', 'apple_mail', 'fixture'));
        """
    )
