"""Reports Modernization WP06 B6: the transfer behaviour table against the in-memory fake.

FAST. The same scenarios `tests/database/test_reports_transfer_repository.py`
runs on PostgreSQL (`tests/report_transfer_behaviour.py`), here against the
`FakeUnitOfWork` repository with a real filesystem staging under `tmp_path`,
so the fake every service suite uses cannot drift from the SQL semantics on
anything the table states. Plus the static claims about the SQL module: no
DELETE statement, no `intelligence_*` table.
"""

from __future__ import annotations

import ast
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeVar

import pytest

from my_pa.contracts.ports import ReportTransferQuotaError, ReportTransferRepository
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.report_content_stores.staging import FilesystemReportTransferStaging
from tests.conftest import FakeUnitOfWork, World
from tests.report_transfer_behaviour import (
    CLIENT_1,
    PRINCIPAL_A,
    SCENARIOS,
    T0,
    declaration,
)

T = TypeVar("T")

MODULE: Final = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "my_pa"
    / "infrastructure"
    / "persistence"
    / "report_transfers.py"
)


class FakeHarness:
    def __init__(self, root: Path) -> None:
        self.world = World()
        root.mkdir()
        self.staging_root = root
        self.staging = FilesystemReportTransferStaging(root)

    def tx(self, work: Callable[[ReportTransferRepository], T]) -> T:
        with FakeUnitOfWork(self.world) as unit:
            return work(unit.report_transfers)

    def content_id(self, principal_id: str) -> str:
        return issue_identifier(IdKind.REPORT_CONTENT)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_behaviour_table_on_the_fake(tmp_path: Path, name: str) -> None:
    SCENARIOS[name](FakeHarness(tmp_path / "staging"))


def test_concurrent_fake_begins_cannot_exceed_the_client_quota(tmp_path: Path) -> None:
    harness = FakeHarness(tmp_path / "staging")
    outcomes: list[str] = []
    barrier = threading.Barrier(8)

    def run(index: int) -> None:
        barrier.wait(timeout=10)
        try:
            harness.tx(
                lambda r: r.begin(
                    declaration(byte_count=10),
                    principal_id=PRINCIPAL_A,
                    client_ref=CLIENT_1,
                    idempotency_key=f"race-{index}",
                    now=T0,
                )
            )
            outcomes.append("begun")
        except ReportTransferQuotaError:
            outcomes.append("quota")

    threads = [threading.Thread(target=run, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(outcomes) == ["begun"] * 4 + ["quota"] * 4


def test_the_sql_module_has_no_delete_and_no_intelligence_table() -> None:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "delete" not in calls
    assert "DELETE " not in source
    tables = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith(".tables")
        for alias in node.names
    }
    assert tables == {"report_transfer_chunks", "report_transfer_sessions"}
