"""Versioned GoodNotes page renders. PDF visual rasterization is deferred.

The production profile hashes admitted page-representation bytes and records
renderer name, version, and profile. Tests inject a mapping from raw SHA-256
onto a normalized SHA so regenerated-unchanged pages can be proven without a
live PDF rasterizer.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from my_pa.domain.goodnotes.models import PageRender

RAW_REPRESENTATION_NAME = "raw-representation"
RAW_REPRESENTATION_VERSION = "1"
RAW_REPRESENTATION_PROFILE = "raw-representation-v1"


@dataclass(frozen=True, slots=True)
class RawRepresentationRenderer:
    """Default production profile: exact = normalized = SHA-256 of admitted bytes."""

    name: str = RAW_REPRESENTATION_NAME
    version: str = RAW_REPRESENTATION_VERSION
    profile_version: str = RAW_REPRESENTATION_PROFILE

    def render(self, page_bytes: bytes) -> PageRender:
        if not page_bytes:
            raise ValueError("a GoodNotes page render requires admitted bytes")
        digest = hashlib.sha256(page_bytes).hexdigest()
        return PageRender(
            exact_render_sha256=digest,
            normalized_render_sha256=digest,
            renderer_name=self.name,
            renderer_version=self.version,
            render_profile_version=self.profile_version,
            perceptual_hash=None,
            perceptual_algorithm="none-v0",
            perceptual_algorithm_version="0",
            width=None,
            height=None,
        )


@dataclass(frozen=True, slots=True)
class MappedPageRenderer:
    """Test double: map raw SHA-256 onto a normalized SHA, fingerprint, and size."""

    mapping: Mapping[str, tuple[str, str | None, tuple[int, int] | None]]
    name: str = "mapped-test-double"
    version: str = "1"
    profile_version: str = "mapped-v1"
    perceptual_algorithm: str = "test-double"
    perceptual_algorithm_version: str = "1"

    def render(self, page_bytes: bytes) -> PageRender:
        if not page_bytes:
            raise ValueError("a GoodNotes page render requires admitted bytes")
        exact = hashlib.sha256(page_bytes).hexdigest()
        mapped = self.mapping.get(exact)
        if mapped is None:
            return PageRender(
                exact_render_sha256=exact,
                normalized_render_sha256=exact,
                renderer_name=self.name,
                renderer_version=self.version,
                render_profile_version=self.profile_version,
                perceptual_hash=None,
                perceptual_algorithm=self.perceptual_algorithm,
                perceptual_algorithm_version=self.perceptual_algorithm_version,
                width=None,
                height=None,
            )
        normalized, fingerprint, dimensions = mapped
        width, height = (None, None) if dimensions is None else dimensions
        return PageRender(
            exact_render_sha256=exact,
            normalized_render_sha256=normalized,
            renderer_name=self.name,
            renderer_version=self.version,
            render_profile_version=self.profile_version,
            perceptual_hash=fingerprint,
            perceptual_algorithm=self.perceptual_algorithm,
            perceptual_algorithm_version=self.perceptual_algorithm_version,
            width=width,
            height=height,
        )
