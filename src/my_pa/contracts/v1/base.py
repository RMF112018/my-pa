"""Shared base model and serialisation rules for the v1 contract family.

Two rules apply to every public model:

* unknown fields are rejected rather than ignored, so a caller cannot smuggle
  state past validation (`docs/specs`, section 8.2);
* serialisation is canonical, so identical values always produce identical bytes.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Annotated, Any, Final

from pydantic import AfterValidator, BaseModel, ConfigDict, PlainSerializer

from my_pa.domain.common.time import ensure_utc, format_rfc3339

__all__ = [
    "CONTRACT_VERSION",
    "JsonValue",
    "NondeterministicValueError",
    "StrictModel",
    "UtcDatetime",
    "canonical_json",
    "ensure_deterministic",
]

#: A value that survives a JSON roundtrip with its ordering intact.
type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None


class NondeterministicValueError(ValueError):
    """Raised when a value cannot be encoded deterministically."""


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


def ensure_deterministic(value: Any, _path: str = "$") -> Any:  # noqa: ANN401 - walks arbitrary JSON
    """Return `value` if it encodes deterministically, else raise.

    Two shapes are rejected because they would make identical inputs produce
    different bytes across processes:

    * a `set` or `frozenset`, whose iteration order depends on hash seeding —
      Pydantic would silently coerce one to a list, so the nondeterminism would
      otherwise reach the wire with no error and no warning;
    * a non-finite float, which `json.dumps` writes as bare `NaN` or `Infinity`,
      neither of which is valid JSON.
    """
    if isinstance(value, set | frozenset):
        raise NondeterministicValueError(
            f"{_path}: a set has no stable order; use a list in the order you mean"
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise NondeterministicValueError(f"{_path}: {value!r} is not representable in JSON")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise NondeterministicValueError(f"{_path}: object keys must be strings")
            ensure_deterministic(item, f"{_path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            ensure_deterministic(item, f"{_path}[{index}]")
    return value
