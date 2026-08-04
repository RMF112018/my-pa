"""Review disposition has no source-system or external-action authority."""

from __future__ import annotations

import ast
from pathlib import Path

import my_pa.infrastructure.persistence.review as review_module
from my_pa.contracts.ports import ReviewRepository


def test_the_review_port_exposes_only_listing_and_disposition() -> None:
    public = {
        name
        for name, value in vars(ReviewRepository).items()
        if callable(value) and not name.startswith("_")
    }
    assert public == {"cases", "decide"}


def test_review_persistence_imports_no_provider_or_external_client() -> None:
    path = Path(review_module.__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    forbidden = ("provider", "http", "requests", "reminder", "calendar", "email")
    assert not {name for name in imported if any(token in name.lower() for token in forbidden)}
