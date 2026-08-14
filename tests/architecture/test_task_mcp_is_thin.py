"""MCP adapter remains a thin generated tool list. No SQL, no task store."""

from __future__ import annotations

from pathlib import Path

from my_pa.adapters.mcp.tools import TOOLS
from my_pa.domain.identity.operation import Capability

ADAPTERS = Path(__file__).resolve().parents[2] / "src" / "my_pa" / "adapters" / "mcp"


def test_generated_tools_include_the_task_capabilities() -> None:
    names = {tool.name for tool in TOOLS}
    assert "tasks.create" in names
    assert "tasks.attention" in names
    assert "tasks.waiting_on" in names
    assert "commitments.create" in names
    assert names == {capability.value for capability in Capability}


def test_mcp_adapter_contains_no_sql() -> None:
    for path in ADAPTERS.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "sqlalchemy" not in text
        assert "SELECT " not in text
        assert "INSERT " not in text


def test_tool_count_stays_compact() -> None:
    assert len(TOOLS) <= 40
