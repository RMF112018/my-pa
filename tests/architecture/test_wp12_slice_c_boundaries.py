"""Structural guards for WP-12C's application-only native-source boundary."""

from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from my_pa.application.native_sources import (
    NativeAdmissionReceipt,
    NativeControlReceipt,
    NativeSourceHost,
    NativeSyncAuthority,
    ReviewProposalRouter,
)
from my_pa.contracts.v1.native_sources import NativeBucketProgress
from my_pa.infrastructure.persistence.native_sources import SqlNativeReviewProposalRouter

ROOT = Path(__file__).resolve().parents[2]


def _methods(protocol: type) -> set[str]:
    return {
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    }


def test_host_boundary_is_read_only_and_holds_no_database_or_activation_surface() -> None:
    assert _methods(NativeSourceHost) == {
        "adapter_identity",
        "discover",
        "negotiate",
        "preflight",
        "read",
    }
    forbidden = {
        "connect",
        "credential",
        "delete",
        "install",
        "mutate",
        "password",
        "purge",
        "register_watcher",
        "token",
        "update",
        "watch",
        "write",
    }
    assert all(
        not any(word in method for word in forbidden) for method in _methods(NativeSourceHost)
    )


def test_consequential_enrichment_can_only_open_review_proposals() -> None:
    assert _methods(ReviewProposalRouter) == {"open_review_proposals"}
    assert _methods(ReviewProposalRouter).isdisjoint(
        {"accept", "apply", "decide", "promote", "publish"}
    )
    assert {
        name
        for name in vars(SqlNativeReviewProposalRouter)
        if callable(getattr(SqlNativeReviewProposalRouter, name)) and not name.startswith("_")
    } == {"open_review_proposals"}


def test_progress_and_receipts_have_no_source_content_channel() -> None:
    safe_fields = {
        NativeBucketProgress: {
            "bucket_id",
            "state",
            "coverage",
            "admitted_count",
            "failed_count",
            "pending_count",
            "failure",
        },
        NativeAdmissionReceipt: {
            "request_id",
            "bucket_id",
            "admitted_count",
            "duplicate_count",
            "evidence_digest",
            "enrichment_proposal_count",
            "enrichment_failed",
        },
        NativeControlReceipt: {
            "capability",
            "configuration_id",
            "configuration_revision",
            "selected_bucket_count",
            "audit_id",
        },
        NativeSyncAuthority: {
            "authority_id",
            "configuration_id",
            "configuration_revision",
            "bridge_id",
            "bucket_id",
            "source_id",
            "audit_id",
            "envelope_id",
            "request_id",
            "issued_at",
            "expires_at",
        },
    }
    content_names = {
        "address",
        "body",
        "contact",
        "content",
        "email",
        "event",
        "message",
        "path",
        "payload",
        "query",
        "snippet",
        "text",
    }
    for model, expected in safe_fields.items():
        actual = (
            set(model.model_fields)
            if hasattr(model, "model_fields")
            else {field.name for field in fields(model)}
        )
        assert actual == expected
        assert actual.isdisjoint(content_names)


def test_application_imports_no_apple_framework_or_infrastructure_module() -> None:
    path = ROOT / "src/my_pa/application/native_sources.py"
    tree = ast.parse(path.read_text())
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(module.startswith("my_pa.infrastructure") for module in imports)
    source = path.read_text().lower()
    assert all(
        token not in source
        for token in ("eventkit", "launchagent", "mailkit", "postgresql://", "tcc")
    )


def test_c_migration_adds_only_bounded_admission_status_and_review_lineage_tables() -> None:
    path = ROOT / "migrations/versions/20260805_9d5e2f7b4c61_extend_native_source_capabilities.py"
    source = path.read_text().lower()
    assert source.count("create table") == 3
    assert "create table knowledge.native_admission_authorities" in source
    assert "create table knowledge.native_preflight_observations" in source
    assert "create table knowledge.native_source_review_routes" in source
    assert "create service" not in source
    assert "credential" not in source
    assert "create table knowledge.native_watcher" not in source
    assert "audit_events" in source
    assert "capability_is_known" in source


def test_legacy_transports_do_not_expose_the_native_host_boundary() -> None:
    normalization = (ROOT / "src/my_pa/adapters/normalization.py").read_text()
    tools = (ROOT / "src/my_pa/adapters/mcp/tools.py").read_text()
    assert "Capability.NATIVE_SOURCES_" not in normalization
    assert "Capability.NATIVE_SOURCES_" not in tools
    assert "for capability in _COMMANDS" in tools
