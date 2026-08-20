"""Compose the frozen Gate B v1 synthetic corpus. No infrastructure import."""

from __future__ import annotations

from hashlib import sha256

from my_pa.application.goodnotes_gsqs_corpus import (
    CaseDraft,
    CorpusCase,
    CorpusManifest,
    assign_partitions,
    freeze_manifest,
    materialize_cases,
)
from my_pa.application.goodnotes_gsqs_pages import synthetic_labeled_page_pdf
from my_pa.application.goodnotes_gsqs_v1 import GENERATOR_VERSION, v1_drafts

SYNTHETIC_RENDERER_NAME = "gsqs-synthetic-pdf"
SYNTHETIC_RENDERER_VERSION = "1"
SYNTHETIC_RENDER_PROFILE = "helvetica-times-italic-v1"


def pdf_for_draft(draft: CaseDraft) -> bytes:
    return synthetic_labeled_page_pdf(
        case_id=draft.case_id,
        title=draft.title,
        regions=draft.regions,
        contrast=draft.contrast,
        style=draft.style,
    )


def admitted_page_digest(pdf: bytes) -> str:
    """Digest the generated single-page PDF. Avoid pdfium resave non-determinism."""
    if not pdf.startswith(b"%PDF"):
        raise ValueError("Gate B v1 cases are single-page PDFs")
    return sha256(pdf).hexdigest()


def freeze_v1_corpus() -> tuple[tuple[CorpusCase, ...], CorpusManifest]:
    drafts = v1_drafts()
    partitions = assign_partitions(drafts)
    cases = materialize_cases(
        drafts,
        partitions,
        pdf_for=pdf_for_draft,
        page_digest=admitted_page_digest,
        renderer_name=SYNTHETIC_RENDERER_NAME,
        renderer_version=SYNTHETIC_RENDERER_VERSION,
        render_profile_version=SYNTHETIC_RENDER_PROFILE,
    )
    manifest = freeze_manifest(
        cases,
        generator_version=GENERATOR_VERSION,
        approval_status="READY_FOR_OPERATOR_REVIEW",
    )
    return cases, manifest
