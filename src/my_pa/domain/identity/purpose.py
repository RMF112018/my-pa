"""Declared purposes.

Purposes are explicit and narrow. A principal may not silently escalate one
purpose into another (`docs/specs`, section 4).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Purpose"]


class Purpose(StrEnum):
    """Purposes a request may declare."""

    SOURCE_INSPECTION = "source_inspection"
    BOUNDED_ENROLLMENT = "bounded_enrollment"
    CONTENT_EXTRACTION = "content_extraction"
    KNOWLEDGE_SEARCH = "knowledge_search"
    KNOWLEDGE_READ = "knowledge_read"
    STATUS_OBSERVATION = "status_observation"
    SECURITY_VALIDATION = "security_validation"
    # Two purposes for the capture plane rather than a reuse of the knowledge
    # ones. The knowledge plane is the *extraction* plane, and a purpose that
    # admitted both would let a `knowledge.read` request return raw
    # user-authored capture text — the silent escalation this module exists to
    # refuse. Authoring and review are separated for the same reason the map
    # is near one-to-one with the capability set: a purpose
    # wide enough to cover writing and reading is a purpose that grants both.
    CAPTURE_AUTHORING = "capture_authoring"
    CAPTURE_REVIEW = "capture_review"
    # `review_disposition` is the tenth, and revision `3c8f1e2a5b74` already
    # carries the forward `ALTER` that admits it. It is a purpose of its own
    # rather than a reuse of `capture_review` — the opposite answer `D-91`
    # reached for `capture.search`, from the same test. That test asks whether
    # reuse would widen the grant: searching captures reads rows `capture.read`
    # already returns, so reuse widened nothing, while deciding a review
    # *promotes a proposal to a canonical assertion*, so a grant issued for
    # reading captures would also authorize promotion — exactly the silent
    # escalation this module exists to refuse. It is declared with the
    # `review.decide` capability it serves, because a purpose no capability
    # permits is denied for everything and reads as a mistake rather than as a
    # decision.
    REVIEW_DISPOSITION = "review_disposition"
    # The managed-document plane's pair (WP-28), and revision `6b3d9a2f8c14`
    # already carries the forward `ALTER` that admits both. They are purposes of
    # their own rather than reuses of the capture or knowledge pair, and
    # `domain/identity/operation.py` argues it beside the mapping: managed
    # documents are a third custody plane over their own tables, so admitting a
    # managed write under `capture_authoring` would let a grant issued for
    # ADR-003's append-only records write bytes into the managed root, and
    # admitting a managed read under `knowledge_read` would let a grant issued
    # over the extraction plane return a document body. Two rather than one for
    # the reason the capture pair is two: a purpose wide enough to cover writing
    # and reading is a purpose that grants both.
    DOCUMENT_AUTHORING = "document_authoring"
    DOCUMENT_READ = "document_read"
