"""NAS-07A1 native-plane Principal partition migration contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
REVISION = "d7a4c9e2f165"
HEAD_REVISION = "e9b2c4d7a150"
PRIOR = "b4e8d2c7a613"
NATIVE_OWNED_TABLES: Final = frozenset(
    {
        "native_bridges",
        "native_bridge_observations",
        "native_source_accounts",
        "native_source_buckets",
        "native_discovery_snapshots",
        "native_configuration_revisions",
        "native_configuration_buckets",
        "native_preflight_observations",
        "native_admission_authorities",
        "native_source_review_routes",
        "native_sync_runs",
        "native_bucket_runs",
        "native_sync_jobs",
        "native_checkpoints",
        "source_version_evidence",
        "source_observations",
        "source_memberships",
        "native_watcher_simulations",
        "native_simulation_receipts",
        "native_live_activation_gates",
    }
)


def test_partition_revision_is_on_the_single_forward_chain() -> None:
    """One unbranched head, and this revision on the chain below it.

    Renamed from "is the single forward head": the head it named was another
    revision's, so the assertion had to be re-pinned by every work package that
    added one and rotted again at `9def3c2e63bb`. What the tests below need is
    that the chain has not branched and that this revision is on it, revising
    the one it names.
    """
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PRIOR


def test_populated_legacy_native_rows_fail_closed_instead_of_guessing_owner() -> None:
    source = next((ROOT / "migrations" / "versions").glob(f"*_{REVISION}_*.py")).read_text()
    assert "cannot infer Principal for populated knowledge." in source
    assert "ADD COLUMN principal_id TEXT NOT NULL" in source
    assert "ADD COLUMN PRINCIPAL_ID TEXT DEFAULT" not in source.upper()
    assert "UPDATE knowledge." not in source


def test_partition_revision_covers_exactly_the_native_owned_twenty() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    module = script.get_revision(REVISION).module
    assert frozenset(module._TABLES) == NATIVE_OWNED_TABLES
    assert {"source_objects", "source_object_versions"}.isdisjoint(module._TABLES)
