"""An explicit Conversation Log seeds one skeletal event and no inference."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from tests.capture.conftest import invoke, succeeded

from my_pa.application.commands import CreateCapture
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.conversation.event import ConversationChannel, ConversationState
from my_pa.domain.identity.operation import Capability


@pytest.mark.database
def test_explicit_conversation_log_creates_one_skeletal_event_in_the_save_transaction(
    runtime: GatewayRuntime,
) -> None:
    created = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_CREATE,
            CreateCapture(
                text="synthetic conversation notes",
                idempotency_key="conversation-log-2026-08-04-0001",
                capture_kind=CaptureKind.CONVERSATION_LOG,
            ),
            "conversation-log",
        ),
        "capture.create conversation_log",
    )
    with runtime.work_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT capture_id, version_id, event_state, channel, occurred_at_start "
                "FROM knowledge.capture_conversations WHERE capture_id = :capture_id"
            ),
            {"capture_id": created["capture_id"]},
        ).all()
    assert len(rows) == 1
    assert tuple(rows[0]) == (
        created["capture_id"],
        created["version_id"],
        ConversationState.SKELETAL.value,
        ConversationChannel.UNKNOWN.value,
        None,
    )


@pytest.mark.database
def test_quick_note_does_not_infer_a_conversation_event(runtime: GatewayRuntime) -> None:
    created = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_CREATE,
            CreateCapture(
                text="synthetic note mentioning a meeting",
                idempotency_key="quick-note-2026-08-04-0001",
            ),
            "quick-note-no-conversation",
        ),
        "capture.create quick_note",
    )
    with runtime.work_engine.connect() as connection:
        count = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.capture_conversations "
                "WHERE capture_id = :capture_id"
            ),
            {"capture_id": created["capture_id"]},
        ).scalar_one()
    assert count == 0
