#!/usr/bin/env bash
#
# Stand up the tiers the browser suite drives, run it, and take them down.
#
# Three tiers, all real:
#
#   PostgreSQL   a disposable database created at head for this run, so a
#                browser writing captures cannot touch the configured
#                development database. Dropped afterwards, and dropped first as
#                well, so a run interrupted before teardown is cleaned up by the
#                next one.
#   Python       apps/gateway.py on loopback, in local_operator mode — one fixed
#                process principal, which is the mode `D-15` pins the web tier
#                to one sign-in for.
#   Next.js      started by Playwright itself (see playwright.config.ts), twice:
#                once pointed at the gateway, once pointed at a dead port so the
#                failure states come from a real refused connection.
#
# Nothing here holds a credential or live personal data. The database is
# password-less over loopback through ~/.pgpass, exactly as the Python suites
# reach it. The browser cookie is an opaque 64-hex SID; PostgreSQL
# AuthSessionStore is the authority. The BFF→Python session-service HMAC and
# WebAuthn RP values below are synthetic dummies that match
# playwright.config.ts so verification succeeds. Session-service routes 503 when
# RP is unset or the secret is short, so the gateway must receive them.
#
# Usage:  npm run e2e            (from web/)
#         npm run e2e -- --project=desktop
set -euo pipefail

WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "${WEB_DIR}/.." && pwd)"
PYTHON="${MYPA_E2E_PYTHON:-${REPO_DIR}/.venv/bin/python}"

DATABASE_NAME="${MYPA_E2E_DATABASE:-my_pa_wp13_e2e}"
ADMIN_URL="${MYPA_E2E_ADMIN_URL:-postgresql+psycopg://my_pa@localhost:5433/postgres}"
DATABASE_URL="${MYPA_E2E_DATABASE_URL:-postgresql+psycopg://my_pa@localhost:5433/${DATABASE_NAME}}"
GATEWAY_PORT="${MYPA_E2E_GATEWAY_PORT:-9099}"
GATEWAY_LOG="${WEB_DIR}/.e2e-gateway.log"

gateway_pid=""

# CREATE and DROP DATABASE cannot run inside a transaction block, so the
# connection is put in AUTOCOMMIT — the same thing the Python database suites do
# for their own disposable databases.
administer() {
  MYPA_E2E_STATEMENT="$1" MYPA_E2E_ADMIN="${ADMIN_URL}" "${PYTHON}" - <<'PY'
import os

import sqlalchemy as sa

engine = sa.create_engine(os.environ["MYPA_E2E_ADMIN"])
with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
    connection.execute(sa.text(os.environ["MYPA_E2E_STATEMENT"]))
PY
}

cleanup() {
  if [[ -n "${gateway_pid}" ]] && kill -0 "${gateway_pid}" 2>/dev/null; then
    kill "${gateway_pid}" 2>/dev/null || true
    wait "${gateway_pid}" 2>/dev/null || true
  fi
  administer "DROP DATABASE IF EXISTS \"${DATABASE_NAME}\" WITH (FORCE)" || true
}
trap cleanup EXIT

if [[ ! -x "${PYTHON}" ]]; then
  echo "e2e: ${PYTHON} is not executable. The browser suite needs the repository venv." >&2
  exit 1
fi

echo "e2e: creating the disposable database ${DATABASE_NAME}"
administer "DROP DATABASE IF EXISTS \"${DATABASE_NAME}\" WITH (FORCE)"
administer "CREATE DATABASE \"${DATABASE_NAME}\""

echo "e2e: migrating it to head"
( cd "${REPO_DIR}" && PYTHONPATH="${REPO_DIR}/src" MY_PA_DATABASE_URL="${DATABASE_URL}" "${PYTHON}" -m alembic upgrade head >/dev/null )

echo "e2e: seeding one Principal-scoped synthetic counterparty"
( cd "${REPO_DIR}" && PYTHONPATH="${REPO_DIR}/src" MY_PA_DATABASE_URL="${DATABASE_URL}" "${PYTHON}" tests/end_to_end/seed_work.py )

echo "e2e: seeding two Principal-scoped open review cases"
( cd "${REPO_DIR}" && PYTHONPATH="${REPO_DIR}/src" MY_PA_DATABASE_URL="${DATABASE_URL}" "${PYTHON}" tests/end_to_end/seed_review.py )

echo "e2e: seeding one Principal-scoped Intelligence artifact"
( cd "${REPO_DIR}" && PYTHONPATH="${REPO_DIR}/src" MY_PA_DATABASE_URL="${DATABASE_URL}" "${PYTHON}" tests/end_to_end/seed_reports.py )

echo "e2e: seeding Principal-scoped synthetic people"
( cd "${REPO_DIR}" && PYTHONPATH="${REPO_DIR}/src" MY_PA_DATABASE_URL="${DATABASE_URL}" "${PYTHON}" tests/end_to_end/seed_entities.py )

# Seed one Principal-scoped synthetic Constraint Register.
#
# Inline rather than a `web/e2e/seed_*.py` module, and the reason is a repository
# rule rather than taste: `tests/architecture/test_ci_invokes_mypy_over_the_declared_tree.py`
# requires every Python *root* under the repository to be type-checked or named
# in that rule, and `web/` is neither. A here-document adds no root. The rows are
# inserted through the same repository the application uses, because WP08 admits
# no Constraint mutation and so cannot create them through the BFF the way the
# Work seed creates Commitments. Everything below is synthetic and disposable.
echo "e2e: seeding one Principal-scoped synthetic Constraint Register"
(
  cd "${REPO_DIR}"
  PYTHONPATH="${REPO_DIR}/src" MY_PA_DATABASE_URL="${DATABASE_URL}" "${PYTHON}" - <<'SEED'
from __future__ import annotations

import os
from datetime import UTC, date, datetime

from sqlalchemy import create_engine, insert

from my_pa.bootstrap.gateway import local_principal
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.history import (
    ConstraintHistoryEntry,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import projects

#: Published so the browser spec can address the same rows without guessing.
PROJECT_ID = "prj_e2ecst0000000001"
CATEGORY_ID = "ccat_e2ecst0000000001"
FIRST_CONSTRAINT_ID = "cst_e2ecst0000000001"
SECOND_CONSTRAINT_ID = "cst_e2ecst0000000002"
HISTORY_ID = "chst_e2ecst0000000001"

T0 = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def main() -> None:
    database_url = os.environ["MY_PA_DATABASE_URL"]
    principal_id = local_principal().principal_id
    with create_engine(database_url).begin() as connection:
        connection.execute(
            insert(projects).values(
                project_id=PROJECT_ID,
                principal_id=principal_id,
                name="E2E Synthetic Project",
                state="active",
                participants=[],
                opened_at=T0,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)
        repository.insert_project_settings(
            principal_id,
            ConstraintProjectSettings(
                principal_id=principal_id,
                project_id=PROJECT_ID,
                timezone_name="America/New_York",
                version=1,
                created_at=T0,
                updated_at=T0,
            ),
        )
        repository.insert_category(
            principal_id,
            ConstraintCategory(
                category_id=CATEGORY_ID,
                principal_id=principal_id,
                project_id=PROJECT_ID,
                prefix="1",
                title="Synthetic category",
                state=ConstraintCategoryState.ACTIVE,
                created_at=T0,
                updated_at=T0,
                display_order=1,
            ),
        )
        # Two rows, so a search term narrows the page to one and the Register
        # returning both is something the data could disprove.
        repository.insert_constraint(
            principal_id,
            ProjectConstraint(
                constraint_id=FIRST_CONSTRAINT_ID,
                principal_id=principal_id,
                lifecycle_state=ConstraintLifecycleState.IDENTIFIED,
                origin=ConstraintOrigin.PRODUCT,
                record_quality=ConstraintRecordQuality.NORMAL,
                created_at=T0,
                updated_at=T0,
                version=2,
                project_id=PROJECT_ID,
                category_id=CATEGORY_ID,
                constraint_code="1.01",
                description="Switchgear submittal outstanding",
                date_identified=date(2026, 8, 1),
                due_date=date(2026, 8, 20),
                bic=(PartyRef(kind=PartyKind.PRINCIPAL),),
                published_at=T0,
            ),
        )
        repository.insert_constraint(
            principal_id,
            ProjectConstraint(
                constraint_id=SECOND_CONSTRAINT_ID,
                principal_id=principal_id,
                lifecycle_state=ConstraintLifecycleState.IN_PROGRESS,
                origin=ConstraintOrigin.PRODUCT,
                record_quality=ConstraintRecordQuality.NORMAL,
                created_at=T0,
                updated_at=T0,
                version=3,
                project_id=PROJECT_ID,
                category_id=CATEGORY_ID,
                constraint_code="1.02",
                description="Crane pick plan pending review",
                date_identified=date(2026, 8, 2),
                due_date=date(2026, 9, 30),
                bic=(PartyRef(kind=PartyKind.PRINCIPAL),),
                published_at=T0,
            ),
        )
        repository.insert_history(
            principal_id,
            ConstraintHistoryEntry(
                history_id=HISTORY_ID,
                principal_id=principal_id,
                constraint_id=FIRST_CONSTRAINT_ID,
                # `NO_OP` rather than `APPLIED`: an applied receipt names the
                # revision it wrote, and seeding a revision ledger is not what
                # this fixture is for. The read plane projects both the same way.
                operation=ConstraintMutationOperation.UPDATE,
                actor=ConstraintMutationActor.PRINCIPAL,
                outcome=ConstraintMutationOutcome.NO_OP,
                before_version=2,
                after_version=2,
                occurred_at=T0,
                recorded_at=T0,
                project_id=PROJECT_ID,
            ),
        )


main()
SEED
)

echo "e2e: starting the Python gateway on 127.0.0.1:${GATEWAY_PORT}"
# Session-service origin checks use this allowlist. Live Next is :3100; the
# dead-gateway Next is :3101. Omitting :3101 makes synthetic sign-in 403.
(
  cd "${REPO_DIR}"
  export PYTHONPATH="${REPO_DIR}/src"
  MY_PA_ENVIRONMENT=local \
  MY_PA_AUTH_MODE=local_operator \
  MY_PA_DATABASE_URL="${DATABASE_URL}" \
  MY_PA_SESSION_SERVICE_SECRET=synthetic-e2e-session-service-secret-00 \
  MY_PA_WEBAUTHN_BFF_SECRET=synthetic-e2e-webauthn-bff-secret-0000 \
  MY_PA_WEBAUTHN_RP_ID=localhost \
  MY_PA_WEBAUTHN_RP_NAME=my-pa \
  MY_PA_WEBAUTHN_ALLOWED_ORIGINS="http://localhost:3100 http://localhost:3101" \
  MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED=true \
  "${PYTHON}" apps/gateway.py run --port "${GATEWAY_PORT}"
) >"${GATEWAY_LOG}" 2>&1 &
gateway_pid=$!

for _ in $(seq 1 50); do
  if grep -q "serving" "${GATEWAY_LOG}" 2>/dev/null; then break; fi
  if ! kill -0 "${gateway_pid}" 2>/dev/null; then
    echo "e2e: the gateway exited during startup. Log follows:" >&2
    cat "${GATEWAY_LOG}" >&2
    exit 1
  fi
  sleep 0.2
done

echo "e2e: running the browser suite"
cd "${WEB_DIR}"
MYPA_E2E_GATEWAY_URL="http://127.0.0.1:${GATEWAY_PORT}" npx playwright test "$@"
