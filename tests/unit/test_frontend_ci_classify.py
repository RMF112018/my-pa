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
        (["src/my_pa/infrastructure/persistence/canvas_workspace.py"], True),
        (["src/my_pa/infrastructure/persistence/task_management.py"], True),
        (["src/my_pa/domain/task/lifecycle.py"], True),
        (["src/my_pa/domain/relationship/graph.py"], True),
        (["src/my_pa/domain/search/query.py"], True),
        (["src/my_pa/domain/intelligence/reports.py"], True),
        (["migrations/versions/20260906_a1c9e4b72f80_admit_goodnotes_browser_contracts.py"], True),
        (["src/my_pa/application/constraints.py"], False),
        (["tests/database/test_constraint_read_list.py"], False),
        (["docs/plans/frontend-acceptance-ledger.md"], False),
        (["README.md"], False),
        (["src/my_pa/application/managed_documents.py"], False),
    ],
)
def test_frontend_classify_path_sets(paths: list[str], expected: bool) -> None:
    assert _applicable(paths) is expected, paths


def test_unrelated_backend_and_docs_do_not_force_frontend_ci() -> None:
    paths = ["docs/plans/mcv-completion-plan.md", "src/my_pa/application/constraints.py"]
    assert _applicable(paths) is False


def test_frontend_only_change_is_applicable() -> None:
    assert _applicable(["web/src/components/shell/command-palette.tsx"]) is True
