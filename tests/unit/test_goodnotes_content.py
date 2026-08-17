"""Pathless Principal-bound GoodNotes visual content dereference."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, datetime

import pytest

from my_pa.application.commands import GetGoodNotesContent
from my_pa.application.errors import InvalidRequestError
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.goodnotes.models import MAX_GOODNOTES_RASTER_BYTES, GoodNotesPageRaster
from my_pa.domain.identity.operation import Capability, is_operator_only
from my_pa.domain.identity.purpose import Purpose
from tests.conftest import (
    Scene,
    build_service,
    metadata_for,
    operator,
    staged_goodnotes_raster,
    staged_goodnotes_work,
)
from tests.contract.test_application_capabilities import run, succeeded

WHEN_DIGEST = hashlib.sha256(b"synthetic-goodnotes-raster").hexdigest()


def test_command_has_no_path_or_principal_field() -> None:
    names = {item.name for item in dataclasses.fields(GetGoodNotesContent)}
    assert "path" not in names
    assert "principal_id" not in names
    with pytest.raises(TypeError):
        GetGoodNotesContent(  # type: ignore[call-arg]
            run_id="gnrun_" + "a" * 24,
            page_version_id="gnver_" + "a" * 24,
            content_sha256="a" * 64,
            path="caller-supplied.png",
        )


def test_same_handle_and_digest_returns_identical_png(scene: Scene) -> None:
    work = staged_goodnotes_work(scene)
    raster = staged_goodnotes_raster(scene)
    assert work.content_sha256 != raster.exact_render_sha256
    first = succeeded(
        run(
            build_service(scene.world, scene.providers),
            scene,
            Capability.GOODNOTES_CONTENT,
            Purpose.GOODNOTES_CONTENT,
            GetGoodNotesContent(
                run_id=work.run_id,
                page_version_id=work.page_version_id,
                content_sha256=work.content_sha256,
            ),
        )
    )
    second = succeeded(
        run(
            build_service(scene.world, scene.providers),
            scene,
            Capability.GOODNOTES_CONTENT,
            Purpose.GOODNOTES_CONTENT,
            GetGoodNotesContent(
                run_id=work.run_id,
                page_version_id=work.page_version_id,
                content_sha256=work.content_sha256,
            ),
        )
    )
    assert first["content_base64"] == second["content_base64"]
    assert first["digest"] == second["digest"]
    assert first["media_type"] == "image/png"
    assert first["byte_length"] == raster.byte_length
    assert first["content_sha256"] == work.content_sha256
    assert first["exact_render_sha256"] == raster.exact_render_sha256
    assert "path" not in first


def test_visual_raster_digest_does_not_unlock_content(scene: Scene) -> None:
    work = staged_goodnotes_work(scene)
    raster = staged_goodnotes_raster(scene)
    assert raster.exact_render_sha256 != work.content_sha256
    refused = run(
        build_service(scene.world, scene.providers),
        scene,
        Capability.GOODNOTES_CONTENT,
        Purpose.GOODNOTES_CONTENT,
        GetGoodNotesContent(
            run_id=work.run_id,
            page_version_id=work.page_version_id,
            content_sha256=raster.exact_render_sha256,
        ),
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.INVALID_REQUEST


def test_wrong_principal_is_denied(scene: Scene) -> None:
    raster = staged_goodnotes_raster(scene)
    stranger = operator()
    denied = build_service(scene.world, scene.providers).invoke(
        metadata_for(Capability.GOODNOTES_CONTENT, Purpose.GOODNOTES_CONTENT, stranger),
        GetGoodNotesContent(
            run_id=raster.run_id,
            page_version_id=raster.page_version_id,
            content_sha256=staged_goodnotes_work(scene).content_sha256,
        ),
        principal=stranger,
    )
    assert denied.error is not None
    assert denied.error.code in {ErrorCode.DENIED, ErrorCode.NOT_FOUND}


def test_digest_mismatch_is_refused(scene: Scene) -> None:
    raster = staged_goodnotes_raster(scene)
    mismatch = run(
        build_service(scene.world, scene.providers),
        scene,
        Capability.GOODNOTES_CONTENT,
        Purpose.GOODNOTES_CONTENT,
        GetGoodNotesContent(
            run_id=raster.run_id,
            page_version_id=raster.page_version_id,
            content_sha256="b" * 64,
        ),
    )
    assert mismatch.error is not None
    assert mismatch.error.code is ErrorCode.INVALID_REQUEST


def test_unknown_page_version_is_not_found(scene: Scene) -> None:
    work = staged_goodnotes_work(scene)
    missing = run(
        build_service(scene.world, scene.providers),
        scene,
        Capability.GOODNOTES_CONTENT,
        Purpose.GOODNOTES_CONTENT,
        GetGoodNotesContent(
            run_id=work.run_id,
            page_version_id="gnver_" + "c" * 24,
            content_sha256=WHEN_DIGEST,
        ),
    )
    assert missing.error is not None
    assert missing.error.code is ErrorCode.NOT_FOUND


def test_oversize_raster_fails_closed() -> None:
    payload = b"\x00" * (MAX_GOODNOTES_RASTER_BYTES + 1)
    with pytest.raises(ValueError, match="size cap"):
        GoodNotesPageRaster(
            principal_id="prn_aaaaaaaaaaaaaaaaaaaaaaaa",
            page_version_id="gnver_" + "a" * 24,
            run_id="gnrun_" + "a" * 24,
            exact_render_sha256="a" * 64,
            png_sha256=hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
            png_bytes=payload,
            renderer_name="synthetic",
            renderer_version="1",
            render_profile_version="v1",
            created_at=datetime(2026, 8, 17, tzinfo=UTC),
        )


def test_content_is_not_operator_only() -> None:
    assert not is_operator_only(Capability.GOODNOTES_CONTENT)
    assert GetGoodNotesContent.capability is Capability.GOODNOTES_CONTENT
    assert Capability.GOODNOTES_CONTENT.value == "goodnotes.content"
    assert Purpose.GOODNOTES_CONTENT.value == "goodnotes_content"


def test_invalid_digest_is_invalid_request() -> None:
    with pytest.raises(InvalidRequestError):
        GetGoodNotesContent(
            run_id="gnrun_" + "a" * 24,
            page_version_id="gnver_" + "a" * 24,
            content_sha256="not-a-digest",
        )
