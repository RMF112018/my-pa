"""Command validation for GoodNotes browser list/read/search/correct contracts."""

from __future__ import annotations

import dataclasses

import pytest

from my_pa.application.commands import (
    CorrectGoodNotes,
    ListGoodNotesNotebooks,
    ListGoodNotesPages,
    ListGoodNotesRuns,
    ReadGoodNotes,
    SearchGoodNotes,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.goodnotes.models import issue_stable_id
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
)
from my_pa.domain.identity.purpose import Purpose

NOTEBOOK_ID = issue_stable_id("gnnb", "browse")
PAGE_VERSION_ID = issue_stable_id("gnver", "browse")
RUN_ID = issue_stable_id("gnrun", "browse")
OCCURRENCE_ID = issue_stable_id("gnocc", "browse")
DIGEST = "a" * 64


def test_browser_names_and_purposes_are_distinct() -> None:
    assert Capability.GOODNOTES_NOTEBOOKS_LIST.value == "goodnotes.notebooks.list"
    assert Capability.GOODNOTES_PAGES_LIST.value == "goodnotes.pages.list"
    assert Capability.GOODNOTES_RUNS_LIST.value == "goodnotes.runs.list"
    assert Capability.GOODNOTES_READ.value == "goodnotes.read"
    assert Capability.GOODNOTES_SEARCH.value == "goodnotes.search"
    assert Capability.GOODNOTES_CORRECT.value == "goodnotes.correct"
    assert Purpose.GOODNOTES_BROWSE.value == "goodnotes_browse"
    assert Purpose.GOODNOTES_READ.value == "goodnotes_read"
    assert Purpose.GOODNOTES_CORRECTION.value == "goodnotes_correction"
    for capability in (
        Capability.GOODNOTES_NOTEBOOKS_LIST,
        Capability.GOODNOTES_PAGES_LIST,
        Capability.GOODNOTES_RUNS_LIST,
        Capability.GOODNOTES_READ,
        Capability.GOODNOTES_SEARCH,
        Capability.GOODNOTES_CORRECT,
    ):
        assert not is_operator_only(capability)
    assert not is_write_capability(Capability.GOODNOTES_NOTEBOOKS_LIST)
    assert not is_write_capability(Capability.GOODNOTES_READ)
    assert not is_write_capability(Capability.GOODNOTES_SEARCH)
    assert is_write_capability(Capability.GOODNOTES_CORRECT)
    assert not is_destructive_capability(Capability.GOODNOTES_CORRECT)


def test_browser_commands_do_not_accept_a_caller_supplied_principal() -> None:
    for command in (
        ListGoodNotesNotebooks,
        ListGoodNotesPages,
        ListGoodNotesRuns,
        ReadGoodNotes,
        SearchGoodNotes,
        CorrectGoodNotes,
    ):
        names = {field.name for field in dataclasses.fields(command)}
        assert "principal_id" not in names
        assert "path" not in names


def test_page_size_above_one_hundred_is_refused() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        ListGoodNotesNotebooks(page_size=101)
    assert refused.value.safe_details == (SafeDetail.PAGE_SIZE,)


def test_empty_search_query_is_refused() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        SearchGoodNotes(query="   ")
    assert refused.value.safe_details == (SafeDetail.QUERY,)


def test_pages_list_requires_a_notebook_id() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        ListGoodNotesPages(notebook_id="notebook")
    assert refused.value.safe_details == (SafeDetail.NOTEBOOK_ID,)
    listed = ListGoodNotesPages(notebook_id=NOTEBOOK_ID)
    assert listed.notebook_id == NOTEBOOK_ID


def test_read_pins_content_sha256_when_supplied() -> None:
    ReadGoodNotes(run_id=RUN_ID, page_version_id=PAGE_VERSION_ID)
    with pytest.raises(InvalidRequestError) as refused:
        ReadGoodNotes(run_id=RUN_ID, page_version_id=PAGE_VERSION_ID, content_sha256="abc")
    assert refused.value.safe_details == (SafeDetail.CONTENT_SHA256,)
    pinned = ReadGoodNotes(run_id=RUN_ID, page_version_id=PAGE_VERSION_ID, content_sha256=DIGEST)
    assert pinned.content_sha256 == DIGEST


def test_correct_requires_occurrence_and_transcription() -> None:
    with pytest.raises(InvalidRequestError) as occurrence:
        CorrectGoodNotes(occurrence_id="bad", transcription="note")
    assert occurrence.value.safe_details == (SafeDetail.OCCURRENCE_ID,)
    with pytest.raises(InvalidRequestError) as transcription:
        CorrectGoodNotes(occurrence_id=OCCURRENCE_ID, transcription="")
    assert transcription.value.safe_details == (SafeDetail.TRANSCRIPTION,)
    CorrectGoodNotes(occurrence_id=OCCURRENCE_ID, transcription="revised")
