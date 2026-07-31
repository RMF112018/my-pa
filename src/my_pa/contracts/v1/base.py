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
    "NondeterministicValueError",
    "StrictModel",
    "UtcDatetime",
    "canonical_json",
    "ensure_deterministic",
]

#: How deeply `ensure_deterministic` will walk. This is a policy bound, not a
#: `RecursionError` guard: the interpreter's own limit is far higher. It keeps
#: payload nesting reviewable and terminates self-referential structures.
_MAX_DEPTH: Final = 64


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


def ensure_deterministic(
    value: Any,  # noqa: ANN401 - walks arbitrary caller-supplied JSON
    _path: str = "$",
    _depth: int = 0,
) -> Any:  # noqa: ANN401 - returns a rebuilt copy of accepted input
    """Return a deterministic deep copy of `value`, or raise.

    This is an allowlist, not a blocklist. Only `None`, `bool`, `int`, finite
    `float`, `str`, and exactly `dict`, `list`, or `tuple` are accepted;
    everything else is rejected by default.

    Containers are rebuilt rather than returned as-is. Pydantic copies only the
    top-level field, so a caller holding a reference to a nested dict could
    otherwise mutate it after validation — putting a set back into a supposedly
    frozen model and changing its serialised bytes. Rebuilding severs that alias.
    Tuples become lists, which is what they serialise to anyway.

    A blocklist was tried first and was wrong. It tested for `set` and walked
    only concrete `dict`/`list`/`tuple`, while Pydantic accepts any mapping or
    iterable — so a `MappingProxyType`, `deque`, generator, or `dict.keys()`
    view slipped past unwalked and carried a hash-ordered `set` inside it
    straight to the wire. `MappingProxyType` is this package's own idiom for
    read-only mappings, so that bypass sat directly on the path a contributor
    following local convention would take.
    """
    if _depth > _MAX_DEPTH:
        raise NondeterministicValueError(f"{_path}: nested more than {_MAX_DEPTH} levels deep")

    if value is None or isinstance(value, bool | int | str):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise NondeterministicValueError(f"{_path}: {value!r} is not representable in JSON")
        return value

    if isinstance(value, set | frozenset):
        raise NondeterministicValueError(
            f"{_path}: a set has no stable order; use a list in the order you mean"
        )

    value_type = type(value)
    if value_type is dict:
        rebuilt: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise NondeterministicValueError(f"{_path}: object keys must be strings")
            rebuilt[key] = ensure_deterministic(item, f"{_path}.{key}", _depth + 1)
        return rebuilt

    if value_type is list or value_type is tuple:
        return [
            ensure_deterministic(item, f"{_path}[{index}]", _depth + 1)
            for index, item in enumerate(value)
        ]

    raise NondeterministicValueError(
        f"{_path}: {value_type.__name__} is not an accepted JSON container; use dict, list or tuple"
    )
