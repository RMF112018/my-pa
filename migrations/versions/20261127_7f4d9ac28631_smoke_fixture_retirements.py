"""Add immutable, Principal-scoped retirement markers for operator smoke fixtures."""

from alembic import op

revision = "7f4d9ac28631"
down_revision = "859e93b47a21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE knowledge.smoke_fixture_retirements (
            principal_id text NOT NULL CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
            record_id text NOT NULL CHECK (
                record_id ~ '^(cmsg|isrc|spub|sscn|sscv|sser)_[A-Za-z0-9]{8,64}$'
            ),
            plan_sha256 text NOT NULL CHECK (plan_sha256 ~ '^[a-f0-9]{64}$'),
            retired_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (principal_id, record_id)
        )
        """)
    op.execute("""
        CREATE FUNCTION knowledge.refuse_smoke_retirement_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'smoke fixture retirements are append-only' USING ERRCODE = '23514';
        END;
        $$
        """)
    op.execute("""
        CREATE TRIGGER refuse_smoke_retirement_change BEFORE UPDATE OR DELETE
        ON knowledge.smoke_fixture_retirements FOR EACH ROW
        EXECUTE FUNCTION knowledge.refuse_smoke_retirement_mutation()
        """)
    op.execute("""
        CREATE TRIGGER refuse_smoke_retirement_truncate BEFORE TRUNCATE
        ON knowledge.smoke_fixture_retirements FOR EACH STATEMENT
        EXECUTE FUNCTION knowledge.refuse_smoke_retirement_mutation()
        """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("LOCK TABLE knowledge.smoke_fixture_retirements IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM knowledge.smoke_fixture_retirements) THEN
                RAISE EXCEPTION 'smoke fixture retirements exist' USING ERRCODE = '23001';
            END IF;
        END $$
        """)
    op.execute("DROP TABLE knowledge.smoke_fixture_retirements")
    op.execute("DROP FUNCTION knowledge.refuse_smoke_retirement_mutation()")
