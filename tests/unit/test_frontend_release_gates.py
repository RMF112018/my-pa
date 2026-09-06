"""WP28 gate membership must stay explicit.

Advisory jobs may exist. They must not silently join `frontend / required`.
This is not a coverage-percentage gate and not a budget.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "frontend-quality.yml"

REQUIRED_CHILDREN = (
    "static",
    "unit",
    "production-build",
    "contract",
    "security",
    "e2e-critical",
    "accessibility",
    "responsive",
)

ADVISORY = (
    "pwa-offline",
    "browsers",
    "visual",
    "performance",
    "degraded-gateway",
)


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_required_aggregate_lists_exactly_the_wp27_children() -> None:
    text = _workflow()
    match = re.search(
        r"name: frontend / required\n\s+needs: \[([^\]]+)\]",
        text,
    )
    assert match is not None, "frontend / required needs list is missing"
    needs = [item.strip() for item in match.group(1).split(",")]
    assert needs[0] == "classify"
    assert needs[1:] == list(REQUIRED_CHILDREN)
    for job in ADVISORY:
        assert job not in needs


def test_advisory_jobs_use_continue_on_error_and_exist() -> None:
    text = _workflow()
    for job in ADVISORY:
        block = re.search(
            rf"  {re.escape(job)}:\n    name: frontend / {re.escape(job)}\n"
            rf"    needs: classify\n"
            rf"    if: needs.classify.outputs.applicable == 'true'\n"
            rf"    continue-on-error: true\n",
            text,
        )
        assert block is not None, f"{job} must exist as continue-on-error advisory"


def _job_block(text: str, job: str) -> str:
    match = re.search(rf"^  {re.escape(job)}:\n", text, re.M)
    assert match is not None, job
    rest = text[match.end() :]
    nxt = re.search(r"^  [a-z0-9-]+:", rest, re.M)
    return text[match.start() : match.end() + (nxt.start() if nxt else len(rest))]


def test_required_child_jobs_do_not_continue_on_error() -> None:
    text = _workflow()
    for job in REQUIRED_CHILDREN:
        assert "continue-on-error: true" not in _job_block(text, job), job


def test_dead_gateway_harness_allowlists_session_origin_and_splits_urls() -> None:
    """Sign-in on :3101 needs both the session URL split and the RP origin list."""
    repo = Path(__file__).resolve().parents[2]
    stack = (repo / "web" / "e2e" / "stack.sh").read_text(encoding="utf-8")
    assert "http://localhost:3100" in stack
    assert "http://localhost:3101" in stack
    config = (repo / "web" / "playwright.config.ts").read_text(encoding="utf-8")
    assert "MYPA_SESSION_SERVICE_URL: GATEWAY_URL" in config
    assert "MYPA_CANONICAL_ORIGIN: DEAD_GATEWAY_URL" in config
    assert 'MYPA_GATEWAY_URL: "http://127.0.0.1:1"' in config
