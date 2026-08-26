"""Synthetic B0 campaign fixture. Generated PNGs only; never real handwriting."""

from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    CAMPAIGN_CLASS_SYNTHETIC,
    is_real_handwriting_campaign,
)
from my_pa.application.goodnotes_gsqs_live_b0 import B0Census, B0CensusMember

SYNTHETIC_CAMPAIGN_SCHEMA = "gsqs-b0-synthetic-campaign-v1"
SYNTHETIC_CAMPAIGN_ID = "gsqs-b0-synthetic-exec-v1"
SYNTHETIC_CORPUS_VERSION = "gsqs-b0-synthetic-exec-v1"
SYNTHETIC_PARTITION = "SYNTHETIC"
SYNTHETIC_CASE_COUNT = 73
SYNTHETIC_CASE_ID_PATTERN = re.compile(r"^synth-b0-([0-9]{3})$")
ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS = ("synth-b0-001",)


@dataclass(frozen=True, slots=True)
class SyntheticCampaign:
    campaign_id: str
    corpus_version: str
    manifest_digest: str
    combined_identity: str
    census: B0Census
    raster_root: Path


def synthetic_png(index: int) -> bytes:
    """Unique 1x1 PNG. Pixel value encodes the case ordinal; not handwriting."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return len(data).to_bytes(4, "big") + tag + data + crc.to_bytes(4, "big")

    ihdr = (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    pixel = bytes([index % 256])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" + pixel, 9))
        + chunk(b"IEND", b"")
    )


def synthetic_case_ordinal(case_id: str) -> int:
    matched = SYNTHETIC_CASE_ID_PATTERN.fullmatch(case_id)
    if matched is None:
        raise ValueError("synthetic case id is not admitted")
    ordinal = int(matched.group(1))
    if ordinal < 1:
        raise ValueError("synthetic case id is not admitted")
    return ordinal


def build_synthetic_campaign_for_case_ids(
    directory: Path, case_ids: tuple[str, ...]
) -> SyntheticCampaign:
    if not case_ids:
        raise ValueError("synthetic campaign needs at least one case")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("synthetic campaign has duplicate case ids")
    if directory.is_symlink():
        raise ValueError("synthetic raster root must not be a symlink")
    rasters = directory / "rasters"
    rasters.mkdir(parents=True, exist_ok=True)
    members: list[B0CensusMember] = []
    for case_id in case_ids:
        ordinal = synthetic_case_ordinal(case_id)
        png = synthetic_png(ordinal)
        digest = sha256(png).hexdigest()
        (rasters / f"{case_id}.png").write_bytes(png)
        members.append(
            B0CensusMember(
                case_id=case_id,
                raster_sha256=digest,
                case_digest=digest,
                file_sha256=digest,
            )
        )
    census_body = {
        "members": [
            {
                "case_id": item.case_id,
                "case_digest": item.case_digest,
                "file_sha256": item.file_sha256,
                "raster_sha256": item.raster_sha256,
            }
            for item in members
        ]
    }
    manifest_digest = sha256(
        json.dumps(census_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    combined_identity = sha256(f"{SYNTHETIC_CORPUS_VERSION}:{manifest_digest}".encode()).hexdigest()
    if is_real_handwriting_campaign(
        corpus_version=SYNTHETIC_CORPUS_VERSION, combined_identity=combined_identity
    ):
        raise ValueError("synthetic campaign collided with real handwriting identity")
    census = B0Census(
        corpus_version=SYNTHETIC_CORPUS_VERSION,
        manifest_digest=manifest_digest,
        combined_identity=combined_identity,
        partition=SYNTHETIC_PARTITION,
        members=tuple(members),
        census_digest=manifest_digest,
    )
    fixture = {
        "campaign_class": CAMPAIGN_CLASS_SYNTHETIC,
        "campaign_id": SYNTHETIC_CAMPAIGN_ID,
        "combined_identity": combined_identity,
        "corpus_version": SYNTHETIC_CORPUS_VERSION,
        "manifest_digest": manifest_digest,
        "members": census_body["members"],
        "partition": SYNTHETIC_PARTITION,
        "schema_version": SYNTHETIC_CAMPAIGN_SCHEMA,
    }
    path = directory / "campaign.json"
    path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return SyntheticCampaign(
        campaign_id=SYNTHETIC_CAMPAIGN_ID,
        corpus_version=SYNTHETIC_CORPUS_VERSION,
        manifest_digest=manifest_digest,
        combined_identity=combined_identity,
        census=census,
        raster_root=rasters,
    )


def build_synthetic_campaign(
    directory: Path, *, case_count: int = SYNTHETIC_CASE_COUNT
) -> SyntheticCampaign:
    if case_count < 1:
        raise ValueError("synthetic campaign needs at least one case")
    ids = tuple(f"synth-b0-{ordinal:03d}" for ordinal in range(1, case_count + 1))
    return build_synthetic_campaign_for_case_ids(directory, ids)


def load_synthetic_campaign(path: Path) -> tuple[B0Census, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("synthetic campaign fixture is missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("synthetic campaign fixture must be a JSON object")
    if payload.get("schema_version") != SYNTHETIC_CAMPAIGN_SCHEMA:
        raise ValueError("wrong synthetic campaign schema")
    if payload.get("campaign_class") != CAMPAIGN_CLASS_SYNTHETIC:
        raise ValueError("campaign is not SYNTHETIC")
    corpus_version = str(payload.get("corpus_version", ""))
    combined = str(payload.get("combined_identity", ""))
    if is_real_handwriting_campaign(corpus_version=corpus_version, combined_identity=combined):
        raise ValueError("synthetic campaign must not bind the real handwriting corpus")
    raw_members = payload.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValueError("synthetic campaign members missing")
    members: list[B0CensusMember] = []
    for item in raw_members:
        if not isinstance(item, dict):
            raise ValueError("synthetic campaign member is not an object")
        members.append(
            B0CensusMember(
                case_id=str(item["case_id"]),
                raster_sha256=str(item["raster_sha256"]),
                case_digest=str(item["case_digest"]),
                file_sha256=str(item["file_sha256"]),
            )
        )
    ids = [item.case_id for item in members]
    if len(ids) != len(set(ids)):
        raise ValueError("synthetic campaign has duplicate case ids")
    census = B0Census(
        corpus_version=corpus_version,
        manifest_digest=str(payload["manifest_digest"]),
        combined_identity=combined,
        partition=str(payload.get("partition", SYNTHETIC_PARTITION)),
        members=tuple(members),
        census_digest=str(payload["manifest_digest"]),
    )
    return census, str(payload["campaign_id"])
