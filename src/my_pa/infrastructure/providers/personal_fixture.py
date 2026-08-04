"""Synthetic personal-source rows through the read-only fixture provider.

Containment is delegated to :class:`FixtureSourceProvider`, so traversal,
escaping symlinks, hard links, and the observe/open race are refused by the same
code and conformance suite as WP-2. This adapter only parses already-bounded JSON.
"""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256

from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.relationship.identity import IdentityObservation
from my_pa.domain.relationship.provider import PersonalSourceBatch, PersonalSourceProvider
from my_pa.domain.source.provider import ObjectKind, ProviderError, SourceProvider

__all__ = ["FixturePersonalSourceProvider"]

_MAX_FIXTURE_BYTES = 64 * 1024
_ALLOWED_DOMAINS = frozenset({"contacts", "email", "calendar"})


class FixturePersonalSourceProvider(PersonalSourceProvider):
    """Normalize one level of synthetic JSON fixtures without source mutation."""

    def __init__(self, source: SourceProvider) -> None:
        self._source = source

    def observations(self) -> tuple[PersonalSourceBatch, ...]:
        grouped: dict[str, list[IdentityObservation]] = {name: [] for name in _ALLOWED_DOMAINS}
        unavailable: dict[str, str] = {}
        objects = tuple(self._source.list_children())
        for item in objects:
            if item.kind is not ObjectKind.FILE or item.media_type not in {
                "application/json",
                None,
            }:
                continue
            content = self._source.fetch(item.source_object_id, max_bytes=_MAX_FIXTURE_BYTES)
            if content.is_truncated:
                raise ProviderError("a synthetic personal-source fixture exceeds its bound")
            try:
                raw = json.loads(content.content.decode("utf-8"))
                domain = str(raw["domain"])
                state = CoverageState(str(raw.get("state", CoverageState.PROCESSED.value)))
                limitation = raw.get("limitation")
                observed_at = datetime.fromisoformat(str(raw["observed_at"]).replace("Z", "+00:00"))
                display_name = raw.get("display_name")
            except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                raise ProviderError("a synthetic personal-source fixture is invalid") from None
            if domain not in _ALLOWED_DOMAINS:
                raise ProviderError(
                    "a synthetic personal-source fixture names an unsupported domain"
                )
            if state not in {CoverageState.PROCESSED, CoverageState.UNAVAILABLE}:
                raise ProviderError("a synthetic personal-source fixture has an unsupported state")
            if display_name is not None and not isinstance(display_name, str):
                raise ProviderError("a synthetic personal-source display name is invalid")
            if state is CoverageState.UNAVAILABLE:
                if not isinstance(limitation, str) or not limitation.strip():
                    raise ProviderError("an unavailable personal-source fixture states why")
                unavailable[domain] = limitation
                continue
            stable_binding = "\x00".join(
                (self._source.source_id, item.source_object_id, content.version_id)
            ).encode()
            observation_id = make_identifier(
                IdKind.IDENTITY_OBSERVATION,
                sha256(stable_binding).hexdigest()[:32],
            )
            grouped[domain].append(
                IdentityObservation(
                    observation_id=observation_id,
                    source_id=self._source.source_id,
                    source_object_id=item.source_object_id,
                    source_version=content.version_id,
                    observed_at=observed_at,
                    display_name=display_name,
                )
            )
        batches: list[PersonalSourceBatch] = []
        for domain in sorted(_ALLOWED_DOMAINS):
            rows = tuple(sorted(grouped[domain], key=lambda row: row.observation_id))
            if domain in unavailable:
                batches.append(
                    PersonalSourceBatch(
                        domain=domain,
                        state=CoverageState.UNAVAILABLE,
                        observations=(),
                        limitation=unavailable[domain],
                    )
                )
            elif rows:
                batches.append(
                    PersonalSourceBatch(
                        domain=domain,
                        state=CoverageState.PROCESSED,
                        observations=rows,
                    )
                )
            else:
                batches.append(
                    PersonalSourceBatch(
                        domain=domain,
                        state=CoverageState.UNAVAILABLE,
                        observations=(),
                        limitation="no fixture observation was supplied",
                    )
                )
        return tuple(batches)
