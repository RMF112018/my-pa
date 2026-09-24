"""SP3 — the Run-02 CI-selection omission guard.

`R02-WP10` ships eight net-new test/CI files (Impl-6, R02-WP10 Phase 8-9) that
close 140 acceptance rows end-to-end. None of that closure means anything if a
required CI lane simply never selects one of the new spec files, silently
merges a mutating spec into a read-plane invocation it was never isolated
from, or drops one of the four required `@run02-mobile` sentinels. Those are
exactly the three SP5 failure modes this guard exists to catch (Artifact 04
§SP5: "omit any new E2E file from its required workflow lane", "merge Run-02
mutating E2E into the curated read-plane invocation", "remove a required
mobile `@run02-mobile` sentinel") — together with HC5 obligations 24 and 25.

This test is **naturally red on the R02-WP10 Phase 8 base**: none of the eight
edits Artifact 04 §SP2/§6 specifies exist yet in
`.github/workflows/frontend-quality.yml` at this head — they are the
Integrator's own Phase-9 commit, made *after* this guard exists and passes
against a hand-applied scratch copy (see the Phase-8 implementation handoff
for that red -> scratch-green evidence). Editing the tracked workflow file is
not this test's job and not this worker's write set; this test only reads it.

**Why text, not a YAML library.** No YAML dependency is declared for this
package (`pyproject.toml`), and this test must run in the FAST tier on an
ordinary install. The workflow's own two-space job indentation and six-space
step-list indentation are stable and are what every job in this file already
uses (checked directly against the current tree), so job and step boundaries
are found by indentation-anchored regular expressions over the raw text
rather than a general block-YAML parser. Every assertion below locates its
target by **job name and step name / exact command substring**, never by line
number — per the dispatch's own instruction, since PR #291 already shifted
line numbers once in this same file and INTEGRATOR-B's Phase-9 edit will
shift them again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Overridden only by the prove-red procedure's own throwaway scratch-copy
#: run (see the Phase-8 handoff) — never committed as anything but this.
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "frontend-quality.yml"

#: The four mobile sentinel titles, verbatim (Artifact 04 §SP2).
RUN02_MOBILE_SENTINELS = (
    "@run02-mobile Picker All Projects to Project",
    "@run02-mobile portfolio to Project Constraint navigation",
    "@run02-mobile Quick Capture Constraint",
    "@run02-mobile ordinary Close without keyboard-required input",
)

#: The exact 13-entry `frontend / required` needs list (Artifact 04 §SP3.8),
#: unchanged by Run-02 — it adds no new job, only new steps inside existing ones.
REQUIRED_NEEDS = (
    "classify",
    "static",
    "unit",
    "production-build",
    "contract",
    "security",
    "e2e-critical",
    "accessibility",
    "responsive",
    "mobile-webkit-postux",
    "pwa-offline",
    "degraded-gateway",
    "delivery-config",
)


def _read_workflow() -> str:
    if not WORKFLOW_PATH.is_file():
        pytest.fail(f"workflow file not found at {WORKFLOW_PATH}")
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block(text: str, job_name: str) -> str:
    """The full text of one top-level job, from its `  <name>:` header to the
    next top-level (two-space-indented) job key, or end of file.

    Every job in this workflow is a direct two-space-indented child of
    `jobs:`, and every job body is indented at least four spaces — verified
    directly against the current file for every job this test touches — so a
    line matching `^  [A-Za-z][\\w-]*:` after the job's own header line is
    unambiguously the *next* job, never a field inside this one.
    """
    header = re.search(rf"^  {re.escape(job_name)}:\s*$", text, re.MULTILINE)
    if header is None:
        pytest.fail(f"job {job_name!r} not found in {WORKFLOW_PATH}")
    start = header.start()
    next_job = re.search(r"^  [A-Za-z][\w-]*:\s*$", text[header.end() :], re.MULTILINE)
    end = header.end() + next_job.start() if next_job else len(text)
    return text[start:end]


def _step_block(job_text: str, step_name: str) -> str:
    """The text of one named step within a job block, up to the next step or
    end of the job.

    Steps in this workflow are six-space-indented `- name:` / `- uses:` /
    `- run:` list items (checked directly against every job this test reads).
    """
    header = re.search(rf"^      - name: {re.escape(step_name)}\s*$", job_text, re.MULTILINE)
    if header is None:
        pytest.fail(f"step {step_name!r} not found in this job")
    start = header.start()
    next_step = re.search(r"^      - (name:|uses:|run:)", job_text[header.end() :], re.MULTILINE)
    end = header.end() + next_step.start() if next_step else len(job_text)
    return job_text[start:end]


def _step_names(job_text: str) -> list[str]:
    return re.findall(r"^      - name: (.+)$", job_text, re.MULTILINE)


# ---------------------------------------------------------------------------
# 1. `frontend / security`'s Vitest command includes the Run-02 route test.
# ---------------------------------------------------------------------------


def test_security_job_runs_the_project_scope_route_test() -> None:
    job = _job_block(_read_workflow(), "security")
    vitest_lines = [line for line in job.splitlines() if "npx vitest run src/lib/http" in line]
    assert vitest_lines, "the security job's existing vitest command line was not found"
    assert "src/app/api/project-scope/route.test.ts" in vitest_lines[0], (
        "security job's vitest command must include "
        "src/app/api/project-scope/route.test.ts (Artifact 04 SP2 / HC5-17/18's route test)"
    )


# ---------------------------------------------------------------------------
# 2. `e2e-critical`'s Run-02 invocation is a third, separate step.
# ---------------------------------------------------------------------------


def test_e2e_critical_runs_run02_as_its_own_third_step() -> None:
    job = _job_block(_read_workflow(), "e2e-critical")
    names = _step_names(job)
    assert "Run the Run-02 Project Controls real-stack desktop e2e" in names, (
        "e2e-critical must contain a step named "
        "'Run the Run-02 Project Controls real-stack desktop e2e'"
    )
    run02_index = names.index("Run the Run-02 Project Controls real-stack desktop e2e")
    curated_index = names.index("Run curated WebAuthn and browser-security desktop e2e")
    wp09_index = names.index("Run the Constraint authoring real-stack desktop e2e")
    assert curated_index < wp09_index < run02_index, (
        "the Run-02 step must come after both the curated read-plane step and "
        "the WP09 constraints-mutations.spec.ts step, never merged with either"
    )

    curated = _step_block(job, "Run curated WebAuthn and browser-security desktop e2e")
    wp09 = _step_block(job, "Run the Constraint authoring real-stack desktop e2e")
    run02 = _step_block(job, "Run the Run-02 Project Controls real-stack desktop e2e")

    for spec_file in ("e2e/project-controls-run02.spec.ts", "e2e/capture-constraint.spec.ts"):
        assert spec_file not in curated, (
            f"{spec_file} must not be merged into the curated read-plane step"
        )
        assert spec_file not in wp09, f"{spec_file} must not be merged into the WP09 mutations step"
        assert spec_file in run02, f"the Run-02 step must invoke {spec_file}"

    assert "constraints-mutations.spec.ts" not in run02, (
        "the Run-02 step must not also carry the WP09 mutating spec"
    )
    assert "--project=desktop" in run02
    assert re.search(
        r"npm run e2e -- e2e/project-controls-run02\.spec\.ts "
        r"e2e/capture-constraint\.spec\.ts --project=desktop",
        run02,
    ), "the Run-02 step's exact invocation text (Artifact 04 SP2) was not found"


# ---------------------------------------------------------------------------
# 3. `accessibility` includes the Run-02 accessibility file.
# ---------------------------------------------------------------------------


def test_accessibility_job_runs_the_run02_accessibility_spec() -> None:
    job = _job_block(_read_workflow(), "accessibility")
    step = _step_block(job, "Run desktop accessibility e2e")
    assert "e2e/project-controls-run02-accessibility.spec.ts" in step


# ---------------------------------------------------------------------------
# 4. `responsive`'s verify-e2e-selection.mjs call and execution both carry
#    the Run-02 responsive file and its sentinel.
# ---------------------------------------------------------------------------


def test_responsive_job_selects_and_runs_the_run02_responsive_spec() -> None:
    job = _job_block(_read_workflow(), "responsive")
    verify = _step_block(job, "Verify the responsive selection is what this lane claims")
    run_step = _step_block(job, "Run desktop, tablet, mobile and Work reflow e2e")

    assert "--file=e2e/project-controls-run02-responsive.spec.ts" in verify
    assert (
        '--sentinel="[RUN02-RESPONSIVE] Project controls opened overlays '
        'fit the required width matrix"' in verify
    )
    assert "e2e/project-controls-run02-responsive.spec.ts" in run_step


# ---------------------------------------------------------------------------
# 5. `mobile-webkit-postux` carries the separate `@run02-mobile` invocation,
#    both files, all four sentinels, and the existing exclusion is unchanged.
# ---------------------------------------------------------------------------


def test_mobile_webkit_postux_selects_and_runs_the_run02_mobile_subset() -> None:
    job = _job_block(_read_workflow(), "mobile-webkit-postux")
    names = _step_names(job)
    assert "Run the Run-02 WebKit phone subset" in names, (
        "mobile-webkit-postux must contain a step named 'Run the Run-02 WebKit phone subset'"
    )
    curated_index = names.index("Run the curated WebKit phone lane")
    run02_index = names.index("Run the Run-02 WebKit phone subset")
    assert curated_index < run02_index, (
        "the Run-02 WebKit step must come after the existing curated step"
    )

    run02_step = _step_block(job, "Run the Run-02 WebKit phone subset")
    assert "e2e/project-controls-run02-responsive.spec.ts" in run02_step
    assert "e2e/capture-constraint.spec.ts" in run02_step
    assert '--grep "@run02-mobile"' in run02_step
    assert "--project=mobile-webkit" in run02_step
    assert re.search(
        r"npm run e2e -- e2e/project-controls-run02-responsive\.spec\.ts "
        r'e2e/capture-constraint\.spec\.ts --project=mobile-webkit --grep "@run02-mobile"',
        run02_step,
    ), "the Run-02 WebKit step's exact invocation text (Artifact 04 SP2) was not found"

    verify = _step_block(job, "Verify the mobile-webkit selection is what this lane claims")
    assert "--file=e2e/project-controls-run02-responsive.spec.ts" in verify
    assert "--file=e2e/capture-constraint.spec.ts" in verify
    for sentinel in RUN02_MOBILE_SENTINELS:
        assert f'--sentinel="{sentinel}"' in verify, f"missing mobile sentinel: {sentinel}"

    # The existing curated-WebKit step's own exclusion must be untouched: same
    # step, same grep-invert text, still present and still excluding exactly
    # one named test (Artifact 04 SP3.5's "preserving the existing single
    # grep-invert exclusion").
    curated_step = _step_block(job, "Run the curated WebKit phone lane")
    assert '--grep-invert "an ordinary active row sits under the rhythm ceiling"' in curated_step
    assert curated_step.count("--grep-invert") == 1, (
        "the curated WebKit step must keep exactly its one existing grep-invert exclusion"
    )


# ---------------------------------------------------------------------------
# 6. `pwa-offline` includes the offline-negative spec.
# ---------------------------------------------------------------------------


def test_pwa_offline_job_runs_the_constraint_offline_negative_spec() -> None:
    job = _job_block(_read_workflow(), "pwa-offline")
    step = _step_block(job, "Run Chromium desktop PWA/offline e2e (REQUIRED)")
    assert "e2e/constraint-offline-negative.spec.ts" in step


# ---------------------------------------------------------------------------
# 7. `degraded-gateway` includes the Run-02 degraded spec.
# ---------------------------------------------------------------------------


def test_degraded_gateway_job_runs_the_run02_degraded_spec() -> None:
    job = _job_block(_read_workflow(), "degraded-gateway")
    step = _step_block(job, "Run dead-gateway unavailable≠empty e2e (REQUIRED)")
    assert "e2e/project-controls-run02-degraded.spec.ts" in step


# ---------------------------------------------------------------------------
# 8. `frontend / required`'s needs array is unchanged.
# ---------------------------------------------------------------------------


def test_required_job_needs_thirteen_entries_unchanged() -> None:
    text = _read_workflow()
    match = re.search(r"^    needs: \[(.+)\]\s*$", text, re.MULTILINE)
    assert match is not None, "the `required` job's `needs: [...]` line was not found"
    entries = tuple(name.strip() for name in match.group(1).split(","))
    assert entries == REQUIRED_NEEDS, (
        f"frontend / required's needs list must remain exactly {REQUIRED_NEEDS!r}, got {entries!r}"
    )
