"""Transaction-rollback isolation is opt-in and does not leak rows."""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, text

from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = [pytest.mark.database, pytest.mark.database_transactional]


def test_a_transactional_test_can_create_a_table(
    transactional_connection: Connection,
) -> None:
    transactional_connection.execute(text("CREATE TABLE public.txn_probe (n int)"))
    transactional_connection.execute(text("INSERT INTO public.txn_probe VALUES (7)"))
    found = transactional_connection.execute(text("SELECT n FROM public.txn_probe")).scalar_one()
    assert found == 7


def test_the_previous_transactional_test_left_no_table(
    worker_transactional_url: str,
) -> None:
    engine = create_database_engine(worker_transactional_url)
    try:
        with engine.connect() as connection:
            present = connection.execute(text("SELECT to_regclass('public.txn_probe')")).scalar()
    finally:
        engine.dispose()
    assert present is None
