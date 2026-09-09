"""Append-only display labels: list-safe, not capture text, no UPDATE of captures."""

from __future__ import annotations

from typing import Any, Final

import pytest
from sqlalchemy import text
from tests.capture.conftest import counts, invoke, succeeded

from my_pa.application.commands import CreateCapture, ListCaptures, SearchCaptures
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.domain.identity.operation import Capability
from my_pa.infrastructure.persistence import capture as capture_store
from my_pa.infrastructure.persistence.capture import append_capture_label
from my_pa.infrastructure.persistence.principal_scope import capture_context

NOTE: Final = "the quarterly figures live in the red folder"
LABEL: Final = "Quarterly figures"
RENAMED: Final = "Board pack"
RENAMED_AGAIN: Final = "Final board pack"


def _create(
    runtime: GatewayRuntime, *, key: str, label: str | None = None, text: str = NOTE
) -> dict[str, Any]:
    return succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_CREATE,
            CreateCapture(text=text, idempotency_key=key, display_label=label),
            key,
        ),
        "capture.create",
    )


def _listed(runtime: GatewayRuntime) -> list[dict[str, Any]]:
    listing = succeeded(
        invoke(runtime, Capability.CAPTURE_LIST, ListCaptures(), "list"), "capture.list"
    )
    return list(listing["captures"])


@pytest.mark.database
def test_unlabelled_captures_list_and_search_with_null_display_label(
    runtime: GatewayRuntime,
) -> None:
    created = _create(runtime, key="label-none")
    listed = _listed(runtime)
    assert listed[0]["capture_id"] == created["capture_id"]
    assert listed[0]["display_label"] is None
    assert "text" not in listed[0]
    assert NOTE not in str(listed)

    search = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_SEARCH,
            SearchCaptures(query="quarterly"),
            "search",
        ),
        "capture.search",
    )
    assert search["matches"][0]["display_label"] is None
    assert "text" not in search["matches"][0]
    assert "snippet" not in search["matches"][0]
    assert NOTE not in str(search["matches"])


@pytest.mark.database
def test_create_with_a_label_does_not_copy_capture_text(runtime: GatewayRuntime) -> None:
    created = _create(runtime, key="label-create", label=LABEL)
    listed = _listed(runtime)
    assert listed[0]["capture_id"] == created["capture_id"]
    assert listed[0]["display_label"] == LABEL
    assert listed[0]["display_label"] != NOTE
    assert "text" not in listed[0]
    stored = counts(runtime.work_engine)
    assert stored["knowledge.captures"] == 1
    assert stored["knowledge.capture_versions"] == 1
    assert stored["knowledge.capture_labels"] == 1

    search = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_SEARCH,
            SearchCaptures(query="quarterly"),
            "search-labelled",
        ),
        "capture.search",
    )
    assert search["matches"][0]["display_label"] == LABEL
    assert search["matches"][0]["display_label"] != NOTE
    assert NOTE not in str(search["matches"])


@pytest.mark.database
def test_append_rename_does_not_update_captures_or_copy_text(runtime: GatewayRuntime) -> None:
    created = _create(runtime, key="label-rename", label=LABEL)
    capture_id = created["capture_id"]
    principal_id = runtime.principal.principal_id
    with runtime.work_engine.connect() as connection:
        before_xmin = connection.execute(
            text("SELECT xmin FROM knowledge.captures WHERE capture_id = :id"),
            {"id": capture_id},
        ).scalar_one()
        before_content = connection.execute(
            text("SELECT content FROM knowledge.capture_versions WHERE capture_id = :id"),
            {"id": capture_id},
        ).scalar_one()

    with runtime.work_engine.begin() as connection:
        stored = append_capture_label(
            connection,
            capture_id,
            RENAMED,
            context=capture_context(principal_id),
        )
        assert stored == RENAMED

    listed = _listed(runtime)
    assert listed[0]["display_label"] == RENAMED
    assert listed[0]["display_label"] != NOTE
    stored_counts = counts(runtime.work_engine)
    assert stored_counts["knowledge.captures"] == 1
    assert stored_counts["knowledge.capture_versions"] == 1
    assert stored_counts["knowledge.capture_labels"] == 2

    with runtime.work_engine.connect() as connection:
        after_xmin = connection.execute(
            text("SELECT xmin FROM knowledge.captures WHERE capture_id = :id"),
            {"id": capture_id},
        ).scalar_one()
        after_content = connection.execute(
            text("SELECT content FROM knowledge.capture_versions WHERE capture_id = :id"),
            {"id": capture_id},
        ).scalar_one()
        labels = list(
            connection.execute(
                text(
                    "SELECT display_label FROM knowledge.capture_labels "
                    "WHERE capture_id = :id ORDER BY recorded_at, label_id"
                ),
                {"id": capture_id},
            ).scalars()
        )
    assert after_xmin == before_xmin, "appending a label mutated the captures identity row"
    assert after_content == before_content == NOTE
    assert labels == [LABEL, RENAMED]


@pytest.mark.database
def test_second_label_appended_in_one_transaction_is_current(
    runtime: GatewayRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create(runtime, key="label-same-transaction")
    capture_id = created["capture_id"]
    principal_id = runtime.principal.principal_id
    label_ids = iter(("clbl_zzzzzzzz", "clbl_aaaaaaaa"))
    monkeypatch.setattr(capture_store, "issue_identifier", lambda _kind: next(label_ids))

    with runtime.work_engine.begin() as connection:
        append_capture_label(
            connection,
            capture_id,
            RENAMED,
            context=capture_context(principal_id),
        )
        append_capture_label(
            connection,
            capture_id,
            RENAMED_AGAIN,
            context=capture_context(principal_id),
        )

    assert _listed(runtime)[0]["display_label"] == RENAMED_AGAIN
    with runtime.work_engine.connect() as connection:
        labels = list(
            connection.execute(
                text(
                    "SELECT display_label, recorded_at FROM knowledge.capture_labels "
                    "WHERE capture_id = :id ORDER BY recorded_at, label_id"
                ),
                {"id": capture_id},
            )
        )
    assert [row.display_label for row in labels] == [RENAMED, RENAMED_AGAIN]
    assert labels[0].recorded_at < labels[1].recorded_at


@pytest.mark.database
def test_label_rows_are_principal_scoped(runtime: GatewayRuntime) -> None:
    created = _create(runtime, key="label-scope", label=LABEL)
    stranger = "prn_bbbb0002bbbbbbbbbbbbbbbb00000002"
    with runtime.work_engine.begin() as connection:
        from my_pa.contracts.ports import UnknownScopeError

        with pytest.raises(UnknownScopeError):
            append_capture_label(
                connection,
                created["capture_id"],
                RENAMED,
                context=capture_context(stranger),
            )
    listed = _listed(runtime)
    assert listed[0]["display_label"] == LABEL
    assert counts(runtime.work_engine)["knowledge.capture_labels"] == 1
