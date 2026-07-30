"""Shared base model and serialisation rules for the v1 contract family.

Two rules apply to every public model:

* unknown fields are rejected rather than ignored, so a caller cannot smuggle
  state past validation (`docs/specs`, section 8.2);
* serialisation is canonical, so identical values always produce identical bytes.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Final

from pydantic import AfterValidator, BaseModel, ConfigDict, PlainSerializer

from my_pa.domain.common.time import ensure_utc, format_rfc3339

__all__ = ["CONTRACT_VERSION", "StrictModel", "UtcDatetime", "canonical_json"]

#: Major version of the `my-pa-public-capabilities` contract family.
CONTRACT_VERSION: Final = "v1"

#: A timezone-aware UTC datetime that serialises as RFC 3339 with a `Z` suffix.
UtcDatetime = Annotated[
    datetime,
    AfterValidator(ensure_utc),
    PlainSerializer(format_rfc3339, return_type=str),
]


class StrictModel(BaseModel):
    """Base for every public contract model."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
        validate_default=True,
        use_enum_values=False,
    )

    def to_canonical_dict(self) -> dict[str, Any]:
        """Return the JSON-mode representation of this model."""
        return self.model_dump(mode="json")

    def to_canonical_json(self) -> str:
        """Return a deterministic JSON encoding of this model.

        Keys are sorted and separators are fixed, so the output depends only on
        the values and not on field declaration order or dictionary insertion
        order.
        """
        return canonical_json(self.to_canonical_dict())


def canonical_json(value: Any) -> str:  # noqa: ANN401 - encodes arbitrary JSON-safe values
    """Encode `value` as deterministic JSON."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
