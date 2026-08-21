"""Exact-string provider model mapping. No inferred aliases."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from my_pa.application.goodnotes_gsqs_routellm_candidate import OPERATOR_DISPLAY_POOL

MAPPING_SCHEMA_VERSION = "gsqs-b0-provider-model-mapping-v1"
POOL_MEMBERSHIP_IN = "IN_POOL"
POOL_MEMBERSHIP_OUT = "OUT_OF_POOL"


class SelectedModelMappingState(StrEnum):
    ABSENT = "ABSENT"
    UNATTESTED = "UNATTESTED"
    UNMAPPED = "UNMAPPED"
    MAPPED_IN_POOL = "MAPPED_IN_POOL"
    MAPPED_OUT_OF_POOL = "MAPPED_OUT_OF_POOL"


@dataclass(frozen=True, slots=True)
class MappingEntry:
    provider_model_id: str
    pool_membership: str
    display_name: str | None


@dataclass(frozen=True, slots=True)
class ProviderModelMapping:
    evidence_id: str
    entries: tuple[MappingEntry, ...]

    def by_provider_id(self) -> dict[str, MappingEntry]:
        return {item.provider_model_id: item for item in self.entries}


def load_provider_model_mapping(path: Path, *, expected_evidence_id: str) -> ProviderModelMapping:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provider model mapping must be a JSON object")
    return mapping_from_payload(payload, expected_evidence_id=expected_evidence_id)


def mapping_from_payload(
    payload: Mapping[str, object], *, expected_evidence_id: str
) -> ProviderModelMapping:
    if payload.get("mapping_schema_version") != MAPPING_SCHEMA_VERSION:
        raise ValueError("wrong provider model mapping schema")
    evidence_id = payload.get("evidence_id")
    if not isinstance(evidence_id, str) or not evidence_id:
        raise ValueError("mapping evidence_id missing")
    if evidence_id != expected_evidence_id:
        raise ValueError("mapping evidence_id mismatch")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("mapping entries missing")
    entries: list[MappingEntry] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise ValueError("mapping entry must be an object")
        provider_id = raw.get("provider_model_id")
        membership = raw.get("pool_membership")
        display = raw.get("display_name")
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("mapping provider_model_id missing")
        if provider_id in seen:
            raise ValueError("duplicate mapping provider_model_id")
        if membership not in {POOL_MEMBERSHIP_IN, POOL_MEMBERSHIP_OUT}:
            raise ValueError("mapping pool_membership invalid")
        if membership == POOL_MEMBERSHIP_IN:
            if display not in OPERATOR_DISPLAY_POOL:
                raise ValueError("IN_POOL mapping display_name is not in the operator pool")
        elif display is not None and not isinstance(display, str):
            raise ValueError("OUT_OF_POOL display_name malformed")
        seen.add(provider_id)
        entries.append(
            MappingEntry(
                provider_model_id=provider_id,
                pool_membership=str(membership),
                display_name=None if display is None else str(display),
            )
        )
    return ProviderModelMapping(evidence_id=evidence_id, entries=tuple(entries))


def classify_selected_model(
    observed: object,
    mapping: ProviderModelMapping | None,
) -> tuple[SelectedModelMappingState, str | None]:
    if observed is None:
        return SelectedModelMappingState.ABSENT, None
    if not isinstance(observed, str):
        raise ValueError("selected_model is not a string")
    if observed == "":
        return SelectedModelMappingState.ABSENT, None
    if mapping is None:
        if observed == "route-llm":
            return SelectedModelMappingState.UNATTESTED, None
        return SelectedModelMappingState.UNMAPPED, None
    entry = mapping.by_provider_id().get(observed)
    if entry is None:
        if observed == "route-llm":
            return SelectedModelMappingState.UNATTESTED, None
        return SelectedModelMappingState.UNMAPPED, None
    if entry.pool_membership == POOL_MEMBERSHIP_OUT:
        return SelectedModelMappingState.MAPPED_OUT_OF_POOL, entry.display_name
    return SelectedModelMappingState.MAPPED_IN_POOL, entry.display_name
