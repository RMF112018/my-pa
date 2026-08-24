"""Dedicated visual-canary prompt is a one-case stop, not a full-repetition loop."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FULL_PROMPT = ROOT / "ops/goodnotes/gsqs/b0/chatllm-remote-eval-prompt-v1.txt"
CANARY_PROMPT = ROOT / "ops/goodnotes/gsqs/b0/chatllm-remote-eval-visual-canary-prompt-v1.txt"


def test_visual_canary_prompt_stops_after_one_successful_submit() -> None:
    text = CANARY_PROMPT.read_text(encoding="utf-8")
    assert "goodnotes.eval.status" in text
    assert "goodnotes.eval.next" in text
    assert "goodnotes.eval.submit" in text
    assert "exactly once" in text
    assert "STOP" in text
    assert "ordinal 2" in text
    assert "Loop until the server reports that the current repetition is complete" not in text
    assert "SOURCE_CONTEXT" in text
    assert "NOTE_UNIT" in text
    assert "x_min" in text
    assert "expected token" not in text.lower()
    assert "gold" in text  # forbidden to infer/request gold, must mention the prohibition


def test_full_run_frozen_prompt_is_unchanged_as_a_repetition_loop() -> None:
    text = FULL_PROMPT.read_text(encoding="utf-8")
    assert "Loop until the server reports that the current repetition is complete" in text
    assert FULL_PROMPT.read_bytes() != CANARY_PROMPT.read_bytes()
