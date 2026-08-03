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
