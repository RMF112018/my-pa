"""Dormant GoodNotes rollout gates stay off and do not activate production.

Synthetic settings only. Does not ingest, write notes, deliver, or call Abacus.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from my_pa.application import goodnotes as goodnotes_application
from my_pa.application import goodnotes_delivery, goodnotes_evaluation, goodnotes_semantics
from my_pa.bootstrap import goodnotes as goodnotes_bootstrap
from my_pa.bootstrap import goodnotes_rollout as rollout_module
from my_pa.bootstrap import goodnotes_tbr as tbr
from my_pa.bootstrap.goodnotes import compose_local_goodnotes_runtime
from my_pa.bootstrap.goodnotes_durable_note import durable_note_task_is_activated
from my_pa.bootstrap.goodnotes_rollout import (
    ACTIVATION_STEPS,
    PILOT_ACTIVATED,
    PRODUCTION_ACTIVATED,
    allowed_activation_steps,
    rollout_gates,
    rollout_report,
)
from my_pa.bootstrap.goodnotes_tbr import (
    CONTRACT_STATUS,
    LIVE_BRIDGE_IMPLEMENTED,
    LIVE_TASK_MUTATION,
    OPTIONAL_BRIDGE_AUTHORIZED,
)
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, load_settings

DSN = "postgresql+psycopg://my_pa@localhost:5433/my_pa_settings_probe"

GATE_FIELDS = (
    "goodnotes_durable_note_ingestion_enabled",
    "goodnotes_durable_note_intelligence_enabled",
    "goodnotes_canonical_semantic_writes_enabled",
    "goodnotes_user_facing_summary_delivery_enabled",
    "goodnotes_tbr_bridge_enabled",
    "goodnotes_self_improving_optimizer_enabled",
)

GENERAL_PATHS = (
    goodnotes_bootstrap,
    goodnotes_application,
    goodnotes_delivery,
    goodnotes_evaluation,
    goodnotes_semantics,
    tbr,
)


def _settings(**overrides: object) -> Settings:
    return Settings(database_url=DSN, **overrides)  # type: ignore[arg-type]


def test_all_gates_default_off() -> None:
    settings = _settings()
    for name in GATE_FIELDS:
        assert getattr(settings, name) is False
    loaded = load_settings({f"{ENV_PREFIX}DATABASE_URL": DSN})
    for name in GATE_FIELDS:
        assert getattr(loaded, name) is False
    gates = rollout_gates(loaded)
    assert gates.durable_note_ingestion is False
    assert gates.semantic_agent_work_dispatch is False
    assert gates.canonical_semantic_writes is False
    assert gates.user_facing_summary_delivery is False
    assert gates.optional_tbr_bridge is False
    assert gates.optional_self_improving_optimizer is False
    assert PRODUCTION_ACTIVATED is False
    assert PILOT_ACTIVATED is False


def test_environment_can_enable_each_gate_independently() -> None:
    for name in GATE_FIELDS:
        loaded = load_settings(
            {
                f"{ENV_PREFIX}DATABASE_URL": DSN,
                f"{ENV_PREFIX}{name.upper()}": "true",
            }
        )
        assert getattr(loaded, name) is True
        for other in GATE_FIELDS:
            if other != name:
                assert getattr(loaded, other) is False


def test_default_flags_allow_observe_and_page_identity_dry_run_only() -> None:
    settings = _settings()
    assert allowed_activation_steps(settings) == (
        "observe-only",
        "page-identity-dry-run",
    )
    assert ACTIVATION_STEPS[0] == "observe-only"
    assert ACTIVATION_STEPS[-1] == "optional-tbr-bridge"
    report = rollout_report(settings)
    assert report["production_activated"] is False
    assert report["pilot_activated"] is False
    assert report["live_transition_operator_gated"] is True
    assert report["ingests"] is False
    assert report["writes_canonical_notes"] is False
    assert report["delivers"] is False
    assert report["calls_abacus"] is False
    assert report["allowed_activation_steps"] == [
        "observe-only",
        "page-identity-dry-run",
    ]


def test_intelligence_gate_is_reused_for_semantic_proposals() -> None:
    settings = _settings(goodnotes_durable_note_intelligence_enabled=True)
    assert durable_note_task_is_activated(settings) is True
    assert allowed_activation_steps(settings) == (
        "semantic-proposals-without-canonical-note-writes",
    )
    with_writes = _settings(
        goodnotes_durable_note_intelligence_enabled=True,
        goodnotes_canonical_semantic_writes_enabled=True,
    )
    assert allowed_activation_steps(with_writes) == (
        "canonical-writes-with-delivery-disabled",
        "new-only-summary-preview",
    )
    with_delivery = _settings(
        goodnotes_durable_note_intelligence_enabled=True,
        goodnotes_canonical_semantic_writes_enabled=True,
        goodnotes_user_facing_summary_delivery_enabled=True,
    )
    assert allowed_activation_steps(with_delivery) == ("operator-reviewed-delivery-canary",)
    scheduled = _settings(
        goodnotes_durable_note_ingestion_enabled=True,
        goodnotes_durable_note_intelligence_enabled=True,
        goodnotes_canonical_semantic_writes_enabled=True,
        goodnotes_user_facing_summary_delivery_enabled=True,
    )
    assert allowed_activation_steps(scheduled) == ("bounded-scheduled-operation",)
    bridged = _settings(
        goodnotes_durable_note_ingestion_enabled=True,
        goodnotes_durable_note_intelligence_enabled=True,
        goodnotes_canonical_semantic_writes_enabled=True,
        goodnotes_user_facing_summary_delivery_enabled=True,
        goodnotes_tbr_bridge_enabled=True,
    )
    assert allowed_activation_steps(bridged) == ("optional-tbr-bridge",)


def test_out_of_order_flags_fail_closed() -> None:
    delivery_without_writes = _settings(
        goodnotes_user_facing_summary_delivery_enabled=True,
    )
    assert allowed_activation_steps(delivery_without_writes) == ()
    writes_without_intelligence = _settings(
        goodnotes_canonical_semantic_writes_enabled=True,
    )
    assert allowed_activation_steps(writes_without_intelligence) == ()
    tbr_alone = _settings(goodnotes_tbr_bridge_enabled=True)
    assert allowed_activation_steps(tbr_alone) == ()
    ingestion_alone = _settings(goodnotes_durable_note_ingestion_enabled=True)
    assert allowed_activation_steps(ingestion_alone) == ()


def test_optimizer_flag_does_not_advance_the_sequence() -> None:
    settings = _settings(goodnotes_self_improving_optimizer_enabled=True)
    assert rollout_gates(settings).optional_self_improving_optimizer is True
    assert allowed_activation_steps(settings) == (
        "observe-only",
        "page-identity-dry-run",
    )


def test_tbr_flag_does_not_implement_or_authorize_a_live_bridge() -> None:
    settings = _settings(goodnotes_tbr_bridge_enabled=True)
    assert settings.goodnotes_tbr_bridge_enabled is True
    assert CONTRACT_STATUS == "GN-09_EXTERNAL_TASK_GATE_PENDING"
    assert LIVE_BRIDGE_IMPLEMENTED is False
    assert LIVE_TASK_MUTATION is False
    assert OPTIONAL_BRIDGE_AUTHORIZED is False
    assert "goodnotes_tbr_bridge_enabled" not in inspect.getsource(tbr)
    document = tbr.contract_document()
    bridge = document["optional_bridge"]
    assert isinstance(bridge, dict)
    assert bridge["authorized"] is False
    assert bridge["implemented"] is False
    assert bridge["wp_15_activation"] is False


def test_ocr_composition_and_general_paths_do_not_read_the_gates() -> None:
    runtime_source = inspect.getsource(compose_local_goodnotes_runtime)
    bootstrap_source = inspect.getsource(goodnotes_bootstrap)
    for name in GATE_FIELDS:
        assert name not in runtime_source
        assert name not in bootstrap_source
        for module in GENERAL_PATHS:
            assert name not in inspect.getsource(module)
    assert "goodnotes_rollout" not in bootstrap_source
    assert "durable_note" not in runtime_source


def test_dry_run_helper_does_not_ingest_write_deliver_or_call_abacus() -> None:
    source = inspect.getsource(rollout_module)
    assert "urllib" not in source
    assert "httpx" not in source
    assert "requests" not in source
    assert "abacus.ai" not in source.casefold()
    assert "import abacus" not in source
    assert "compose_local_goodnotes_runtime" not in source
    assert "GoodNotesService" not in source
    assert "build_new_only_summary" not in source
    assert "alembic" not in source.casefold()
    report = rollout_report(_settings(goodnotes_durable_note_ingestion_enabled=True))
    assert report["ingests"] is False
    assert report["writes_canonical_notes"] is False
    assert report["delivers"] is False
    assert report["calls_abacus"] is False
    assert report["allowed_activation_steps"] == []


def test_operator_runbook_forbids_live_activation() -> None:
    text = (
        Path(__file__).resolve().parents[2]
        / "ops"
        / "runbooks"
        / "goodnotes-durable-note-rollout.md"
    ).read_text(encoding="utf-8")
    assert "Production is not activated" in text
    assert "Pilot is not activated" in text
    assert "operator-only" in text.casefold()
    assert "MY_PA_GOODNOTES_DURABLE_NOTE_INGESTION_ENABLED" in text
    assert "MY_PA_GOODNOTES_DURABLE_NOTE_INTELLIGENCE_ENABLED" in text
    assert "does not ingest" in text.casefold()
    assert "GN-09_EXTERNAL_TASK_GATE_PENDING" in text
