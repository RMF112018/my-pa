"""RE-DBH-01 guards: migration authority, role separation, and trigger DDL."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "migrations" / "env.py"
PROVISION = ROOT / "src" / "my_pa" / "infrastructure" / "database" / "record_event_roles.py"
REVISION = (
    ROOT / "migrations" / "versions" / "20261002_c8e4a1b70d35_record_event_truncate_refusal.py"
)


def _function(source: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(found) == 1
    return found[0]


def test_online_migration_uses_only_the_migration_authority_parse() -> None:
    source = ENV.read_text(encoding="utf-8")
    online = _function(source, "run_migrations_online")
    calls = [
        node
        for node in ast.walk(online)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"load_settings", "parsed_database_url"}
    ]
    assert [node.func.attr for node in calls] == ["parsed_database_url"]
    assert "MY_PA_DATABASE_URL" not in ast.get_source_segment(source, online)
    offline = _function(source, "run_migrations_offline")
    assert "load_settings" not in ast.get_source_segment(source, offline)
    assert "load_migration_authority" not in ast.get_source_segment(source, offline)


def test_application_modules_do_not_read_the_migration_url() -> None:
    allowed = {
        ROOT / "src" / "my_pa" / "bootstrap" / "migration_authority.py",
        ROOT / "src" / "my_pa" / "bootstrap" / "settings.py",
    }
    offenders: list[str] = []
    for path in (ROOT / "src" / "my_pa").rglob("*.py"):
        if path in allowed or "__pycache__" in path.parts:
            continue
        if "MY_PA_MIGRATION_DATABASE_URL" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
    settings = (ROOT / "src" / "my_pa" / "bootstrap" / "settings.py").read_text(encoding="utf-8")
    assert "MIGRATION_DATABASE_URL" in settings
    assert "migration_database_url" not in settings


def test_role_provisioning_has_no_credential_and_no_runtime_membership() -> None:
    source = PROVISION.read_text(encoding="utf-8")
    folded = source.upper()
    assert "PASSWORD" not in folded
    assert "GRANT MY_PA_OWNER TO MY_PA_RUNTIME" not in folded
    assert "GRANT MY_PA_MIGRATOR TO MY_PA_RUNTIME" not in folded
    assert "CREATE ROLE" in folded
    revision = REVISION.read_text(encoding="utf-8")
    assert "BEFORE TRUNCATE ON {SCHEMA}.{table}" in revision
    assert '("record_events_refuse_truncate", "record_events")' in revision
    assert '("record_event_sequences_refuse_truncate", "record_event_sequences")' in revision
    assert "PASSWORD" not in revision.upper()
