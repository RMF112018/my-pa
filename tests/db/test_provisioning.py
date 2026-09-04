"""Live PostgreSQL checks for the shared allocator and worker-head clone path."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

from tests.db.provisioning import COUNTERS, WorkerHeadTemplate

pytestmark = [pytest.mark.database, pytest.mark.database_clone]


def test_worker_template_upgrades_head_once_per_worker(
    worker_head_template: WorkerHeadTemplate,
) -> None:
    assert COUNTERS.snapshot()["upgrade_head"] == 1
    assert worker_head_template.name.startswith("my_pa_p_t_")


def test_a_clone_can_hold_rows_the_template_does_not(
    db_engine: Engine,
) -> None:
    with db_engine.begin() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        connection.execute(text("CREATE TABLE public.clone_probe (n int)"))
        connection.execute(text("INSERT INTO public.clone_probe VALUES (1)"))
        assert connection.execute(text("SELECT n FROM public.clone_probe")).scalar_one() == 1
    assert isinstance(version, str) and version


def test_a_second_clone_starts_without_the_first_clones_table(
    db_engine: Engine,
) -> None:
    with db_engine.connect() as connection:
        present = connection.execute(text("SELECT to_regclass('public.clone_probe')")).scalar()
    assert present is None


def test_ordinary_clone_tests_do_not_invoke_upgrade_again(db_engine: Engine) -> None:
    _ = db_engine
    snapshot = COUNTERS.snapshot()
    assert snapshot["upgrade_head"] == 1
    assert snapshot["clone_create"] >= 1
