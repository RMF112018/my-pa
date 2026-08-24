"""Dedicated visual-canary prompt is a one-case stop, not a full-repetition loop."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FULL_PROMPT = ROOT / "ops/goodnotes/gsqs/b0/chatllm-remote-eval-prompt-v1.txt"
CANARY_PROMPT = ROOT / "ops/goodnotes/gsqs/b0/chatllm-remote-eval-visual-canary-prompt-v1.txt"
CANARY_PROMPT_V2 = ROOT / "ops/goodnotes/gsqs/b0/chatllm-remote-eval-visual-canary-prompt-v2.txt"
CANARY_PROMPT_V3 = ROOT / "ops/goodnotes/gsqs/b0/chatllm-remote-eval-visual-canary-prompt-v3.txt"


def _assert_single_case_visual_canary_prompt(text: str) -> None:
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


def test_visual_canary_prompt_stops_after_one_successful_submit() -> None:
    _assert_single_case_visual_canary_prompt(CANARY_PROMPT.read_text(encoding="utf-8"))


def test_visual_canary_prompt_v2_ordinary_visual_inspection_only() -> None:
    text = CANARY_PROMPT_V2.read_text(encoding="utf-8")
    _assert_single_case_visual_canary_prompt(text)
    lower = text.lower()
    assert "ordinary visual inspection" in lower
    assert "do not parse png" in lower
    assert "zlib" in lower
    assert "do not write" in lower and "python" in lower
    assert "pixels" in lower


def test_visual_canary_prompt_v3_immediate_submit_without_local_inspection() -> None:
    text = CANARY_PROMPT_V3.read_text(encoding="utf-8")
    _assert_single_case_visual_canary_prompt(text)
    lower = text.lower()
    assert "immediately visually inspect" in lower
    assert "immediately call goodnotes.eval.submit" in lower
    assert "do not use a shell" in lower
    assert "do not cat files" in lower
    assert "do not run python" in lower
    assert "zlib" in lower
    assert "lease_expired" in lower
    assert "expected token" not in lower


def test_full_run_frozen_prompt_is_unchanged_as_a_repetition_loop() -> None:
    text = FULL_PROMPT.read_text(encoding="utf-8")
    assert "Loop until the server reports that the current repetition is complete" in text
    assert FULL_PROMPT.read_bytes() != CANARY_PROMPT.read_bytes()
