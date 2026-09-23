#!/usr/bin/env bash
# Synthetic, database-free checks for the responsive lane's additive setup marker.
set -euo pipefail

stack="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/stack.sh"
scratch="$(mktemp -d)"
trap 'rm -rf -- "${scratch}"' EXIT

# This fake never opens a database. The wrapper gets through each requested
# stage and its EXIT cleanup, while arbitrary child output remains unchanged.
fake_python="${scratch}/synthetic-python"
cat >"${fake_python}" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail

emit_failure() {
  # Deliberately adversarial but wholly synthetic child output. Only the new
  # annotation, not baseline wrapper/child stdout or stderr, is constrained.
  printf 'SYNTHETIC_PAYLOAD_\033[31m%%0A\r::warning::not-a-real-secret\n' >&2
  exit "$1"
}

if [[ "${MYPA_E2E_STATEMENT:-}" == "DROP DATABASE"* ]]; then
  printf 'drop\n' >>"${TEST_TRACE_FILE}"
  if [[ "${TEST_FAIL_STAGE}" == "database_reset" ]] \
     && [[ "$(grep -c '^drop$' "${TEST_TRACE_FILE}")" -eq 1 ]]; then
    emit_failure 37
  fi
  exit 0
fi
if [[ "${MYPA_E2E_STATEMENT:-}" == "CREATE DATABASE"* ]]; then
  exit 0
fi
if [[ "$*" == *"alembic upgrade head"* && "${TEST_FAIL_STAGE}" == "database_migrate" ]]; then
  emit_failure 53
fi
if [[ "$*" == *"seed_work.py"* && "${TEST_FAIL_STAGE}" == "seed_work" ]]; then
  emit_failure 71
fi
exit 0
FAKE
chmod 700 "${fake_python}"

fail() {
  printf 'responsive stage test failed: %s\n' "$1" >&2
  exit 1
}

run_case() {
  local stage="$1"
  local expected_status="$2"
  local diagnostic="$3"
  local trace="${scratch}/trace"
  local output status marker expected_marker drops
  : >"${trace}"

  set +e
  if [[ "${diagnostic}" == "on" ]]; then
    output="$(CI_RESPONSIVE_DIAGNOSTIC=1 TEST_FAIL_STAGE="${stage}" \
      TEST_TRACE_FILE="${trace}" MYPA_E2E_PYTHON="${fake_python}" \
      MYPA_E2E_DATABASE='synthetic%0A\r::warning::payload' \
      bash "${stack}" 2>&1)"
  else
    output="$(env -u CI_RESPONSIVE_DIAGNOSTIC TEST_FAIL_STAGE="${stage}" \
      TEST_TRACE_FILE="${trace}" MYPA_E2E_PYTHON="${fake_python}" \
      MYPA_E2E_DATABASE='synthetic%0A\r::warning::payload' \
      bash "${stack}" 2>&1)"
  fi
  status=$?
  set -e

  [[ "${status}" -eq "${expected_status}" ]] || fail "exit status for ${stage}"
  drops="$(grep -c '^drop$' "${trace}" || true)"
  [[ "${drops}" -eq 2 ]] || fail "cleanup did not issue its drop for ${stage}"
  marker="$(printf '%s\n' "${output}" | grep '^::error title=Responsive setup failed::' || true)"
  if [[ "${diagnostic}" == "on" ]]; then
    expected_marker="::error title=Responsive setup failed::stage=${stage} status=${expected_status}"
    [[ "${marker}" == "${expected_marker}" ]] || fail "annotation for ${stage}"
    [[ "${marker}" != *SYNTHETIC_PAYLOAD* ]] || fail "child payload entered annotation"
    [[ "${marker}" != *warning* ]] || fail "escaped payload entered annotation"
  else
    [[ -z "${marker}" ]] || fail "diagnostic annotation appeared without opt-in"
    [[ "${output}" == *"e2e: creating the disposable database"* ]] \
      || fail "baseline output changed without opt-in"
  fi
}

run_case database_reset 37 on
run_case database_migrate 53 on
run_case seed_work 71 on
run_case database_reset 37 off
printf 'responsive stage diagnostics: PASS\n'
