"""Admit the registered remote capture client, and widen two frozen vocabularies.

WP-10. Three changes, and the first two are the widening `1a4c9e77b2d5` promised
in writing: that revision froze `capture_transport_is_known` to `('local')` and
`capture_trust_state_is_known` to `('local_principal')` and stated the rule for
what happens next — "a later transport widens them by a forward `ALTER` in its
own revision rather than by editing this one". This is that revision.

* `knowledge.capture_submissions.transport` admits `remote_client` as well as
  `local`;
* `knowledge.capture_submissions.trust_state` admits `registered_client` as well
  as `local_principal`;
* `knowledge.capture_clients` is created: one row per credential the operator
  minted, bound to exactly one Principal.

**The literals below are frozen**, per the standing rule `9c6b4a18ed72` states
and every widening revision since has repeated: no Alembic revision may derive a
closed-set constraint from a domain enum. The vocabularies this revision denotes
are written out here, and so are the ones it downgrades to, so a database
downgraded past this revision holds what the revision below it describes rather
than whatever the domain says on the day the downgrade runs. The pair is checked
against the domain at head by
`tests/schema/test_capture_schema_migration.py::test_head_admits_exactly_the_vocabulary_the_domain_declares`,
which is what makes the restatement a claim rather than a copy.

**Raw SQL rather than a copy of the live declaration**, which is
`d2e3f4a5b6c7`'s shape and the current one: this revision imports no table
object, so it emits exactly what is written here and cannot start meaning
something else when `tables.py` is next edited (`D-48`). The cost of writing the
DDL out is that it could drift from the declaration, and that cost is paid by
`tests/schema/test_capture_client_migration.py`, which compares the created
table's columns, constraints and indexes against `METADATA` on a live server.

**No capability is added and no purpose is widened.** A remote submission invokes
`capture.create` — the capability that already exists, through the service that
already exists — so `audit_events.capability_is_known` is untouched at
twenty-seven names. Minting a client is an operator command rather than a
capability (`D-42`, `AGENTS.md` section 8.2), so it writes no audit event and
needs no vocabulary here.

**The downgrade refuses rather than loses.** Dropping `capture_clients` drops the
credentials; restoring the narrow `transport` vocabulary fails outright on a
database that already holds a remote submission, because that row cannot satisfy
the constraint it would restore. That is the correct direction: a downgrade that
silently rewrote `remote_client` to `local` would falsify the provenance of a
stored capture.

Revision ID: 7a1e5f3c9d24
Revises: 5e2c7b0a94f6
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "7a1e5f3c9d24"
down_revision: str | None = "5e2c7b0a94f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA: Final = "knowledge"

#: The two vocabularies as of this revision, sorted, which is the order the
#: declarative helper produces so the texts can be compared directly.
_TRANSPORT_AT_THIS_REVISION: Final = "transport IN ('local', 'remote_client')"
_TRUST_STATE_AT_THIS_REVISION: Final = "trust_state IN ('local_principal', 'registered_client')"

#: What the revision below denotes, restated rather than derived.
_TRANSPORT_BEFORE_THIS_REVISION: Final = "transport IN ('local')"
_TRUST_STATE_BEFORE_THIS_REVISION: Final = "trust_state IN ('local_principal')"


def _replace(constraint: str, expression: str) -> None:
    """Drop and recreate one CHECK inside this revision's own transaction.

    PostgreSQL has no "alter the expression of a check constraint", and doing it
    in two statements inside one transaction means there is no instant at which
    the column is unconstrained that another session could observe.
    """
    op.execute(f'ALTER TABLE {SCHEMA}.capture_submissions DROP CONSTRAINT "{constraint}"')
    op.execute(
        f'ALTER TABLE {SCHEMA}.capture_submissions ADD CONSTRAINT "{constraint}" '
        f"CHECK ({expression})"
    )


def upgrade() -> None:
    _replace("capture_transport_is_known", _TRANSPORT_AT_THIS_REVISION)
    _replace("capture_trust_state_is_known", _TRUST_STATE_AT_THIS_REVISION)
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.capture_clients (
          client_id text PRIMARY KEY
            CONSTRAINT client_id_is_an_opaque_identifier
            CHECK (client_id ~ '^cclt_[A-Za-z0-9]{{8,64}}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          secret_sha256 text NOT NULL
            CONSTRAINT client_secret_is_a_sha256_digest
            CHECK (secret_sha256 ~ '^[0-9a-f]{{64}}$'),
          state text NOT NULL
            CONSTRAINT capture_client_state_is_known
            CHECK (state IN ('active', 'revoked')),
          created_at timestamptz NOT NULL,
          revoked_at timestamptz,
          CONSTRAINT a_client_is_revoked_exactly_when_it_records_a_revocation
            CHECK ((state = 'revoked') = (revoked_at IS NOT NULL))
        )
        """
    )
    op.execute(
        f"CREATE INDEX capture_clients_by_principal "
        f"ON {SCHEMA}.capture_clients (principal_id, created_at, client_id)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX {SCHEMA}.capture_clients_by_principal")
    op.execute(f"DROP TABLE {SCHEMA}.capture_clients")
    _replace("capture_trust_state_is_known", _TRUST_STATE_BEFORE_THIS_REVISION)
    _replace("capture_transport_is_known", _TRANSPORT_BEFORE_THIS_REVISION)
