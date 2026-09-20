"""Frontend CI applicability is a protection control, not a convenience filter.

`frontend / classify` decides whether the heavy frontend jobs run. A regex that
misses a browser-consumed backend path lets a regression merge without
`frontend / required`. A regex that matches every Python file makes every
backend-only change pay for Playwright. This module pins both sides against
the exact pattern currently published in `.github/workflows/frontend-quality.yml`.

It does not run those jobs. It proves the classifier would have marked the
synthetic path sets applicable or not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/frontend-quality.yml"


def _published_pattern() -> re.Pattern[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"grep -Eq '(\^\([^']+\))'", text)
    assert match is not None, "frontend / classify grep -Eq pattern is missing"
    return re.compile(match.group(1))


def _applicable(paths: list[str]) -> bool:
    pattern = _published_pattern()
    return any(pattern.search(path) for path in paths)


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["web/src/app/(app)/today/page.tsx"], True),
        (["web/src/contracts/gateway.json"], True),
        (["src/my_pa/contracts/ports.py"], True),
        (["src/my_pa/application/capabilities.py"], True),
        (["tests/contract/test_gateway_capability_catalog.py"], True),
        (["src/my_pa/application/webauthn.py"], True),
        (["src/my_pa/application/session_service.py"], True),
        (["src/my_pa/application/goodnotes.py"], True),
        (["src/my_pa/application/tasks.py"], True),
        (["src/my_pa/application/commitments.py"], True),
        (["src/my_pa/application/intelligence.py"], True),
        (["src/my_pa/application/entity_resolution.py"], True),
        (["src/my_pa/application/identity_history.py"], True),
        (["src/my_pa/application/constraints.py"], True),
        (["src/my_pa/application/constraint_management.py"], True),
        (["src/my_pa/application/constraint_settings.py"], True),
        (["src/my_pa/application/commands.py"], True),
        (["src/my_pa/application/service.py"], True),
        (["src/my_pa/application/authorization.py"], True),
        (["src/my_pa/adapters/mcp/server.py"], True),
        (["src/my_pa/adapters/mcp/tools.py"], True),
        (["src/my_pa/infrastructure/persistence/canvas_workspace.py"], True),
        (["src/my_pa/infrastructure/persistence/task_management.py"], True),
        (["src/my_pa/infrastructure/persistence/constraints.py"], True),
        (["src/my_pa/infrastructure/persistence/capture_search.py"], True),
        (["src/my_pa/infrastructure/persistence/situation_repository.py"], True),
        (["src/my_pa/infrastructure/persistence/tables.py"], True),
        (["src/my_pa/infrastructure/persistence/unit_of_work.py"], True),
        (["src/my_pa/domain/project_controls/settings.py"], True),
        (["src/my_pa/domain/project_controls/business_time.py"], True),
        (["src/my_pa/domain/capture/submission.py"], True),
        (["src/my_pa/domain/situation/situation.py"], True),
        (["src/my_pa/domain/situation/project_history.py"], True),
        (["src/my_pa/domain/task/lifecycle.py"], True),
        (["src/my_pa/domain/relationship/graph.py"], True),
        (["src/my_pa/domain/search/query.py"], True),
        (["src/my_pa/domain/intelligence/reports.py"], True),
        (["migrations/versions/20260906_a1c9e4b72f80_admit_goodnotes_browser_contracts.py"], True),
        (["ops/nas/validate-delivery-config.py"], True),
        (["ops/nas/production-environment.example.env"], True),
        (["ops/nas/compose.public-browser.example.yml"], True),
        (["ops/nas/proxy-public-browser.example.caddy"], True),
        (["docs/decisions/ADR-012-public-browser-cloudflare-tunnel.md"], True),
        (["docs/decisions/ADR-013-fixed-local-principal-and-operator-auth-grants.md"], True),
        (["src/my_pa/domain/identity/auth_grants.py"], True),
        (["src/my_pa/domain/identity/auth_state.py"], True),
        (["src/my_pa/domain/identity/user_account.py"], True),
        (["src/my_pa/infrastructure/persistence/auth_grants.py"], True),
        (["src/my_pa/infrastructure/persistence/auth_state.py"], True),
        (["src/my_pa/infrastructure/persistence/user_accounts.py"], True),
        (["src/my_pa/infrastructure/security/webauthn_ceremony.py"], True),
        (["apps/cli/auth.py"], True),
        (["tests/unit/test_auth_grants.py"], True),
        (["tests/unit/test_auth_state.py"], True),
        (["tests/unit/test_cli_auth.py"], True),
        (["tests/unit/test_user_account_identity.py"], True),
        (["tests/unit/test_webauthn_http.py"], True),
        (["tests/database/test_constraint_read_list.py"], True),
        (["tests/situation/test_continuity.py"], True),
        (["tests/unit/test_task_management_service.py"], True),
        (["tests/schema/test_constraint_management_migration.py"], True),
        (["tests/security/test_cross_principal_capture_isolation.py"], True),
        (["tests/security/test_mcp_surface_controls.py"], True),
        (["tests/policy/test_application_authorization.py"], True),
        (["tests/unit/test_gateway_composition.py"], True),
        ([".github/workflows/frontend-quality.yml"], True),
        (["docs/plans/frontend-acceptance-ledger.md"], False),
        (["README.md"], False),
        (["src/my_pa/application/managed_documents.py"], False),
        ([".github/workflows/frontend-quality.yml.old"], False),
        (["src/my_pa/application/service.py.old"], False),
        (["src/my_pa/adapters/mcp/tools.py.old"], False),
        (["src/my_pa/infrastructure/persistence/unit_of_work.py.old"], False),
        (["src/my_pa/domain/situation/project_history.py.old"], False),
        (["tests/database/test_constraint_read_list.py.old"], False),
        (["tests/policy/test_application_authorization.py.old"], False),
        (["tests/security/test_mcp_surface_controls.py.old"], False),
        (["tests/unit/test_gateway_composition.py.old"], False),
    ],
)
def test_frontend_classify_path_sets(paths: list[str], expected: bool) -> None:
    assert _applicable(paths) is expected, paths


def test_unrelated_backend_and_docs_do_not_force_frontend_ci() -> None:
    paths = ["docs/plans/mcv-completion-plan.md", "src/my_pa/application/managed_documents.py"]
    assert _applicable(paths) is False


def test_frontend_only_change_is_applicable() -> None:
    assert _applicable(["web/src/components/shell/command-palette.tsx"]) is True


def test_one_project_controls_backend_change_schedules_frontend_suite() -> None:
    assert _applicable(["src/my_pa/application/constraints.py"]) is True


class TestBlockingGateFailsClosed:
    """F022 — `frontend / required` must not pass on an unresolved applicability.

    The gate used to read `if [[ "${APPLICABLE}" != "true" ]]; then exit 0`.
    Every value other than an exact ``true`` took that branch, including the
    empty string GitHub substitutes when the classifier job was skipped or
    failed. A classifier that crashed therefore reported the one blocking
    frontend check as green, which is the precise opposite of what a required
    check is for.

    These assertions are about the published shell rather than a simulation of
    it, because the defect was a property of the text.
    """

    def _gate(self) -> str:
        text = WORKFLOW.read_text(encoding="utf-8")
        start = text.index("  required:\n")
        return text[start:]

    def test_the_gate_requires_the_classifier_job_to_have_succeeded(self) -> None:
        gate = self._gate()
        assert "CLASSIFY: ${{ needs.classify.result }}" in gate
        assert '"${CLASSIFY}" != "success"' in gate

    def test_applicability_is_a_closed_vocabulary(self) -> None:
        gate = self._gate()
        # `true` and `false` are the only accepted values; the wildcard arm is
        # what turns an empty or malformed value into a failure.
        assert 'case "${APPLICABLE}" in' in gate
        assert "NOT_APPLICABLE" in gate
        assert "expected 'true' or 'false'" in gate

    def test_the_old_fail_open_comparison_is_gone(self) -> None:
        gate = self._gate()
        assert '"${APPLICABLE}" != "true"' not in gate


class TestApplicabilityUsesEventIdentities:
    """F023 — a push to `main` must not compare a commit against itself.

    `classify` checked out ``github.event.pull_request.head.sha || github.sha``
    and diffed ``origin/main...HEAD``. On a push to `main` the fetched
    `origin/main` *is* that HEAD, so the diff was empty, applicability resolved
    `false`, and the frontend gates classified themselves away on exactly the
    integration event that most needed them.
    """

    def _classify(self) -> str:
        text = WORKFLOW.read_text(encoding="utf-8")
        start = text.index("      - id: classify")
        return text[start : text.index("  static:")]

    def test_the_self_comparing_diff_is_gone(self) -> None:
        assert "origin/main...HEAD" not in self._classify()

    def test_pull_request_uses_the_event_base_and_head(self) -> None:
        classify = self._classify()
        assert "github.event.pull_request.base.sha" in classify
        assert "github.event.pull_request.head.sha" in classify

    def test_push_uses_the_event_before_and_after(self) -> None:
        classify = self._classify()
        assert "github.event.before" in classify
        assert "github.event.after" in classify

    def test_an_unresolvable_comparison_falls_back_to_applicable(self) -> None:
        classify = self._classify()
        # Zero-before, force-push and shallow-history cases must run the suite
        # rather than silently skip it.
        assert "0000000000000000000000000000000000000000" in classify
        assert 'echo "applicable=true" >> "$GITHUB_OUTPUT"' in classify
        assert 'resolved="false"' in classify


class TestWp07DiagnosticsSpecIsCollected:
    """F024 — a new spec file is not collected by a blocking lane on its own.

    Playwright's default projects match ``**/*.spec.ts``, but the blocking
    `e2e-critical` and `accessibility` lanes each name their specs explicitly.
    A WP07 spec that nothing named would exist, pass locally, and gate nothing.
    """

    def test_named_by_the_blocking_lanes(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        assert text.count("e2e/diagnostics-visibility.spec.ts") >= 2

    def test_the_spec_file_exists(self) -> None:
        assert (REPO / "web/e2e/diagnostics-visibility.spec.ts").is_file()
