"""HC4 / SP4 — the E2E seed must advance the Category code allocator.

`web/e2e/stack.sh` seeds one Constraint Category (`ccat_e2ecst0000000001`,
prefix `"1"`) and two Constraints filed directly against it with hardcoded
public codes `1.01` and `1.02` (`FIRST_CONSTRAINT_ID`/`SECOND_CONSTRAINT_ID`,
inserted through `SqlConstraintManagementRepository.insert_constraint` rather
than issued through a Publish, exactly as `constraints-mutations.spec.ts`'s
own comment already documents: "stack.sh inserts the seeded 1.01 and 1.02
rows directly, without advancing that Category's code allocator").

Artifact 04's HC4/SP4 rule (verbatim, from the campaign's own controlling
extract): "`tests/architecture/test_constraint_e2e_seed_integrity.py`
asserts that the disposable E2E seed advances the Category code allocator
beyond the seeded public codes `1.01` and `1.02`. If it fails on the
implementation base, the integration owner modifies only `web/e2e/stack.sh`,
so that the seeded allocator's next value is `3`. If it passes, `stack.sh`
is not edited. This is a test-result conditional, not a design choice."

**This is not one of Impl-6's own prove-red obligations** — it is a direct,
narrow, already-worked-out fact about the current seed, checked here so the
Integrator has an exact, evidenced answer rather than a guess.

**How the allocator works, and why the seed collides.** A published code is
`f"{category.prefix}.{row.next_sequence:02d}"`
(`constraint_management.py`'s `2180`), and a successful Publish then advances
`next_sequence` by exactly one (`2189`).
`SqlConstraintManagementRepository.insert_category` — the method
`stack.sh`'s own inline seed script calls — defaults `next_sequence=1` when
the caller does not pass it, and `stack.sh`'s seed script does not pass it.
So after the seed runs, the Category's `next_sequence` is still `1`: the
*next* code a fresh Publish issues against that Category would be `1.01` —
the code already seeded on `FIRST_CONSTRAINT_ID`. Any of Impl-6's own new
E2E tests that publishes a fresh Constraint into the seeded Category (rather
than one it creates itself) would collide with the seed on first contact,
which is exactly the failure mode this guard exists to catch before it is
discovered as a flaky E2E instead.

**Why this runs against a disposable database clone, not the shared E2E
stack.** `web/e2e/stack.sh` is Integrator-only / conditional (out of this
worker's write set) and drops its own disposable database in a `trap … EXIT`
the instant its own `npx playwright test` subprocess exits — there is no
window in which an external process could open a second connection to it and
read the row back. So this test does not shell out to `stack.sh` at all;
it mirrors the **exact** insert calls `stack.sh`'s own inline seed script
makes (same repository methods, same Category id, prefix and two hardcoded
codes) against this suite's own disposable, already-migrated-to-head
database clone (`migrated_engine`, `tests/db/fixtures.py` — the same
mechanism `tests/database/test_constraint_portfolio_reads.py` and its
siblings already use), and reads the allocator state back with the same
`SqlConstraintManagementRepository` the application itself reads it with.
Anything that would make `web/e2e/stack.sh` itself "genuinely not start" is
a different, narrower failure (`EVIDENCE_REQUIRED_TEST_CANNOT_RUN`, per this
worker's own dispatch) than what this test measures.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, insert, select

from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import constraint_categories, projects

pytestmark = pytest.mark.database

#: Exactly `web/e2e/stack.sh`'s own seed identifiers — mirrored, not imported
#: (that script is a shell file, not a Python module this suite can import).
PRINCIPAL_ID = "prn_e2eseedintegrty1"
PROJECT_ID = "prj_e2ecst0000000001"
CATEGORY_ID = "ccat_e2ecst0000000001"
FIRST_CONSTRAINT_ID = "cst_e2ecst0000000001"
SECOND_CONSTRAINT_ID = "cst_e2ecst0000000002"
T0 = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: The two already-seeded public codes this allocator must not reissue.
SEEDED_CODES = {"1.01", "1.02"}


def test_e2e_seed_advances_the_category_code_allocator_beyond_1_01_and_1_02(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(projects).values(
                project_id=PROJECT_ID,
                principal_id=PRINCIPAL_ID,
                name="E2E Synthetic Project",
                state="active",
                participants=[],
                opened_at=T0,
                created_at=T0,
                updated_at=T0,
            )
        )
        repository = SqlConstraintManagementRepository(connection)

        # Exactly `stack.sh`'s own `insert_category` call: no `next_sequence`
        # or `issued_count` keyword, so the repository's own default (`1`, `0`)
        # applies — precisely what is under test.
        repository.insert_category(
            PRINCIPAL_ID,
            ConstraintCategory(
                category_id=CATEGORY_ID,
                principal_id=PRINCIPAL_ID,
                project_id=PROJECT_ID,
                prefix="1",
                title="Synthetic category",
                state=ConstraintCategoryState.ACTIVE,
                created_at=T0,
                updated_at=T0,
                display_order=1,
            ),
        )

        # The two seeded rows, filed directly with their public codes — never
        # through Publish, so the allocator is not touched by this step either.
        repository.insert_constraint(
            PRINCIPAL_ID,
            ProjectConstraint(
                constraint_id=FIRST_CONSTRAINT_ID,
                principal_id=PRINCIPAL_ID,
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
            PRINCIPAL_ID,
            ProjectConstraint(
                constraint_id=SECOND_CONSTRAINT_ID,
                principal_id=PRINCIPAL_ID,
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

        next_sequence = connection.execute(
            select(constraint_categories.c.next_sequence).where(
                constraint_categories.c.category_id == CATEGORY_ID
            )
        ).scalar_one()

    # The allocator's own next-issued code, at this `next_sequence`.
    next_code = f"1.{next_sequence:02d}"
    assert next_code not in SEEDED_CODES, (
        "the E2E seed's Category code allocator was left at next_sequence="
        f"{next_sequence}, so the very next Publish against this Category "
        f"would be issued {next_code!r} — a collision with the seed's own "
        f"hardcoded {sorted(SEEDED_CODES)!r}. Per Artifact 04's HC4/SP4 rule, "
        "the fix is that web/e2e/stack.sh's inline seed script must pass "
        "next_sequence=3 to its insert_category(...) call for "
        f"{CATEGORY_ID!r} — this is Integrator-only and conditional on this "
        "test failing; do not apply it here."
    )
