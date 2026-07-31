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
