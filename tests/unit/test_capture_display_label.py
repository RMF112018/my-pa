"""Display labels are list-safe metadata, not capture text."""

from __future__ import annotations

import unicodedata

import pytest

from my_pa.application.commands import CreateCapture
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.contracts.ports import CaptureSearchMatch, CaptureSummary
from my_pa.contracts.v1.capture import CaptureListEntry, CaptureReceiptView, CaptureVersionView
from my_pa.domain.capture.display_label import MAX_DISPLAY_LABEL_CHARACTERS, normalize_display_label
from my_pa.domain.capture.errors import CaptureBoundsError, CaptureError


def test_empty_and_whitespace_are_omitted() -> None:
    assert normalize_display_label(None) is None
    assert normalize_display_label("") is None
    assert normalize_display_label("   ") is None


def test_nfc_and_strip_are_applied() -> None:
    nfd = unicodedata.normalize("NFD", " café ")
    assert normalize_display_label(nfd) == unicodedata.normalize("NFC", "café")


def test_length_is_unicode_scalars_after_normalisation() -> None:
    bounded = "x" * MAX_DISPLAY_LABEL_CHARACTERS
    assert normalize_display_label(bounded) == bounded
    with pytest.raises(CaptureBoundsError):
        normalize_display_label("x" * (MAX_DISPLAY_LABEL_CHARACTERS + 1))


def test_control_characters_are_refused() -> None:
    with pytest.raises(CaptureError):
        normalize_display_label("a\nb")
    with pytest.raises(CaptureError):
        normalize_display_label("a\x00b")


def test_create_command_omits_empty_and_stores_normalised() -> None:
    omitted = CreateCapture(text="a note", idempotency_key="k-empty", display_label="  ")
    assert omitted.display_label is None
    stored = CreateCapture(text="a note", idempotency_key="k-label", display_label="  Title  ")
    assert stored.display_label == "Title"


def test_create_command_refuses_a_non_string_label() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        CreateCapture(text="a note", idempotency_key="k-type", display_label=123)  # type: ignore[arg-type]
    assert SafeDetail.DISPLAY_LABEL in refused.value.safe_details


def test_list_and_search_models_have_no_text_field() -> None:
    assert "text" not in CaptureListEntry.model_fields
    assert "text" not in CaptureReceiptView.model_fields
    assert "text" in CaptureVersionView.model_fields
    assert "text" not in CaptureSummary.__dataclass_fields__
    assert "text" not in CaptureSearchMatch.__dataclass_fields__
    assert "display_label" in CaptureListEntry.model_fields
    assert "display_label" in CaptureSummary.__dataclass_fields__
    assert "display_label" in CaptureSearchMatch.__dataclass_fields__
