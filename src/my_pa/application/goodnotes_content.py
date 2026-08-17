"""Principal-bound GoodNotes visual-raster dereference.

Returns the pinned PNG used for page identity. Does not return a filesystem
path, a raw PDF, or extracted text. Does not route through knowledge.search or
knowledge.read.
"""

from __future__ import annotations

from base64 import b64encode
from typing import Any

from my_pa.application.authorization import Authorization
from my_pa.application.errors import InvalidRequestError, NotFoundError, SafeDetail
from my_pa.application.goodnotes_semantics import lookup_work
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.goodnotes.models import (
    MAX_GOODNOTES_RASTER_BYTES,
    GoodNotesPageRaster,
    GoodNotesPageWork,
)

__all__ = ["content_payload", "lookup_content"]


def lookup_content(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    *,
    run_id: str,
    page_version_id: str,
    content_sha256: str,
) -> tuple[GoodNotesPageWork, GoodNotesPageRaster]:
    """Return the pinned PNG for the same handle `goodnotes.work` publishes.

    `content_sha256` is the admitted-page digest from work, not the visual
    raster digest. Visual identity stays on the raster row.
    """
    work = lookup_work(unit_of_work, authorization, run_id=run_id, page_version_id=page_version_id)
    if work.content_sha256 != content_sha256:
        raise InvalidRequestError(SafeDetail.CONTENT_SHA256)
    raster = unit_of_work.goodnotes_semantics.page_raster(
        authorization.principal.principal_id, run_id, page_version_id
    )
    if raster is None:
        raise NotFoundError()
    if raster.byte_length > MAX_GOODNOTES_RASTER_BYTES:
        raise InvalidRequestError(SafeDetail.CONTENT)
    return work, raster


def content_payload(work: GoodNotesPageWork, raster: GoodNotesPageRaster) -> dict[str, Any]:
    return {
        "run_id": raster.run_id,
        "page_version_id": raster.page_version_id,
        "content_sha256": work.content_sha256,
        "exact_render_sha256": raster.exact_render_sha256,
        "media_type": raster.media_type,
        "byte_length": raster.byte_length,
        "digest": raster.png_sha256,
        "content_base64": b64encode(raster.png_bytes).decode("ascii"),
        "renderer_name": raster.renderer_name,
        "renderer_version": raster.renderer_version,
        "render_profile_version": raster.render_profile_version,
    }
