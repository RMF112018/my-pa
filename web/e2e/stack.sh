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
# Nothing here holds a credential. The database is password-less over loopback
# through ~/.pgpass, exactly as the Python suites reach it, and the session
# signing key is a synthetic value that signs cookies for a disposable database.
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
( cd "${REPO_DIR}" && MY_PA_DATABASE_URL="${DATABASE_URL}" "${PYTHON}" -m alembic upgrade head >/dev/null )

echo "e2e: starting the Python gateway on 127.0.0.1:${GATEWAY_PORT}"
(
  cd "${REPO_DIR}"
  MY_PA_ENVIRONMENT=local \
  MY_PA_AUTH_MODE=local_operator \
  MY_PA_DATABASE_URL="${DATABASE_URL}" \
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
