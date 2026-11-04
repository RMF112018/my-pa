"""Schedule Scenarios S6-2: the pure plane vocabulary the persistence layer stores.

Contract: `docs/architecture/schedule-scenarios-contract.md` section 14.7.3
(and sections 6.1, 6.3, 6.5, 11.2). Pure and standard-library only, plus
`my_pa.domain.schedule` and the opaque-identifier module (the `domain/schedule`
import allowlist): nothing here reads a database, the clock or the environment.

The capability names are plain strings: no plane capability is public before
S6-3, which pins these sets equal to its `Capability` members. The provenance
literal sets are frozen here rather than imported from the lineage vocabulary
(this package may not import it); a FAST test pins them equal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.schedule.model import ScheduleSeriesName, normalize_series_name

__all__ = [
    "INTAKE_SERIES_PREFIX",
    "MATCH_INTEGRITY_REFUSAL",
    "MAX_CPM_RESULT_BYTES",
    "PLANE_ACCEPTANCE_BASES",
    "PLANE_ATTESTED_DECISION_CHANNELS",
    "PLANE_AUTHORITY_CLASSES",
    "PLANE_CLIENT_DECISION_CHANNELS",
    "PLANE_CLIENT_WRITE_CAPABILITIES",
    "PLANE_OPERATOR_WRITE_CAPABILITIES",
    "PLANE_WRITE_CAPABILITIES",
    "RESULT_KIND_BY_CAPABILITY",
    "MatchAdmissionSkip",
    "PlaneProvenance",
    "PlaneResultKind",
    "intake_series_name",
    "is_intake_name_key",
    "second_admission_key",
    "writer_bucket",
]

#: Section 11.2 step 2: every automatic import gets its own intake Series.
INTAKE_SERIES_PREFIX: Final = "Schedule intake "
_INTAKE_KEY_PREFIX: Final = "schedule intake "
#: The 64-hex request digest's first 12 characters name the intake Series.
_INTAKE_DIGEST_CHARACTERS: Final = 12
#: Domain separation of the worker's second-admission idempotency key.
_SECOND_ADMISSION_DOMAIN: Final = b"series-match-v1\n"

#: Section 6.1: the 6 client-usable plane writes.
PLANE_CLIENT_WRITE_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "schedule_scenarios.create",
        "schedule_scenario_versions.create",
        "schedule_cpm_runs.create",
        "schedule_scenario_outputs.record",
        "schedule_baselines.propose",
        "schedule_baselines.withdraw",
    }
)
#: Section 6.1: the 4 attested-operator-only plane writes.
PLANE_OPERATOR_WRITE_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "schedule_baselines.approve",
        "schedule_baselines.reject",
        "schedule_baselines.revoke",
        "schedule_baselines.set_governing",
    }
)
#: The 10 plane writes the idempotency ledger and the refusal ledger admit.
PLANE_WRITE_CAPABILITIES: Final[frozenset[str]] = (
    PLANE_CLIENT_WRITE_CAPABILITIES | PLANE_OPERATOR_WRITE_CAPABILITIES
)


class PlaneResultKind(StrEnum):
    """What one completed plane write names (`schedule_scenario_write_requests.result_kind`)."""

    SCENARIO = "scenario"
    VERSION = "version"
    CPM_RUN = "cpm_run"
    OUTPUT = "output"
    BASELINE_EVENT = "baseline_event"
    GOVERNING_EVENT = "governing_event"


#: Section 14.3.10 `a_complete_plane_write_request_names_its_result`.
RESULT_KIND_BY_CAPABILITY: Final[MappingProxyType[str, PlaneResultKind]] = MappingProxyType(
    {
        "schedule_scenarios.create": PlaneResultKind.SCENARIO,
        "schedule_scenario_versions.create": PlaneResultKind.VERSION,
        "schedule_cpm_runs.create": PlaneResultKind.CPM_RUN,
        "schedule_scenario_outputs.record": PlaneResultKind.OUTPUT,
        "schedule_baselines.propose": PlaneResultKind.BASELINE_EVENT,
        "schedule_baselines.withdraw": PlaneResultKind.BASELINE_EVENT,
        "schedule_baselines.approve": PlaneResultKind.BASELINE_EVENT,
        "schedule_baselines.reject": PlaneResultKind.BASELINE_EVENT,
        "schedule_baselines.revoke": PlaneResultKind.BASELINE_EVENT,
        "schedule_baselines.set_governing": PlaneResultKind.GOVERNING_EVENT,
    }
)


class MatchAdmissionSkip(StrEnum):
    """Section 11.2 step 6: why a decided match admitted nothing."""

    PLANE_DISABLED = "plane_disabled"


#: Section 14.3.2: the refusal token a match decision records when the second
#: admission failed on an integrity error rather than a typed refusal.
MATCH_INTEGRITY_REFUSAL: Final = "integrity_violation"

#: Section 3.11: the bound of one stored CPM result's canonical bytes.
MAX_CPM_RESULT_BYTES: Final = 67_108_864

# --- provenance (section 6.5; the S3.1 sets, frozen) ---------------------------

#: The 2 authority classes a plane row may carry.
PLANE_AUTHORITY_CLASSES: Final[frozenset[str]] = frozenset({"local_operator", "ordinary_reviewer"})
#: The attested decision channels (lineage `ATTESTED_DECISION_CHANNELS`).
PLANE_ATTESTED_DECISION_CHANNELS: Final[frozenset[str]] = frozenset({"local_cli", "local_web"})
#: A connected client's decision channels (lineage `CLIENT_DECISION_CHANNELS`).
PLANE_CLIENT_DECISION_CHANNELS: Final[frozenset[str]] = frozenset(
    {"local_unattested", "remote_interactive"}
)
#: The 2 acceptance bases (lineage `AcceptanceBasis`).
PLANE_ACCEPTANCE_BASES: Final[frozenset[str]] = frozenset({"user_confirmed", "client_identified"})
_MAX_ASSERTING_CLIENT_ID_CHARACTERS: Final = 256


@dataclass(frozen=True, slots=True)
class PlaneProvenance:
    """Who wrote one plane row (section 14.3 `a_<t>_creator_is_known`).

    The attested local operator is `user_confirmed` with no client id; a
    connected client is `client_identified`, and carries a client id exactly
    on the `remote_interactive` channel.
    """

    authority_class: str
    decision_channel: str
    asserting_client_id: str | None
    acceptance_basis: str
    user_directed_claim: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.user_directed_claim, bool):
            raise ValueError("a user-directed claim is a boolean")
        client = self.asserting_client_id
        given: object = client
        if given is not None and not (
            isinstance(given, str) and 1 <= len(given) <= _MAX_ASSERTING_CLIENT_ID_CHARACTERS
        ):
            raise ValueError("an asserting client id is 1 to 256 characters")
        if self.authority_class == "local_operator":
            if (
                self.decision_channel not in PLANE_ATTESTED_DECISION_CHANNELS
                or self.acceptance_basis != "user_confirmed"
                or client is not None
            ):
                raise ValueError("an operator row is attested, user-confirmed and client-free")
            return
        if self.authority_class != "ordinary_reviewer":
            raise ValueError("a plane row carries a known authority class")
        if (
            self.decision_channel not in PLANE_CLIENT_DECISION_CHANNELS
            or self.acceptance_basis != "client_identified"
            or (client is not None) != (self.decision_channel == "remote_interactive")
        ):
            raise ValueError("a client row is client-identified on a client channel")


def writer_bucket(decision_channel: str, asserting_client_id: str | None) -> str | None:
    """The writer bucket S6-1 `ProposeRequest`/`BaselineEvent.writer_bucket` carry.

    `None` for an attested channel (`local_cli`, `local_web`); otherwise the
    channel and the client id (empty when absent) joined by U+001F.
    """
    if decision_channel in PLANE_ATTESTED_DECISION_CHANNELS:
        return None
    return decision_channel + "\x1f" + (asserting_client_id or "")


def intake_series_name(request_digest: str) -> ScheduleSeriesName:
    """Section 11.2 step 2: the intake Series' name for one automatic import."""
    return normalize_series_name(INTAKE_SERIES_PREFIX + request_digest[:_INTAKE_DIGEST_CHARACTERS])


def is_intake_name_key(key: str) -> bool:
    """Whether a Series name key is an intake Series' (S6-3's command refusal uses it)."""
    return key.startswith(_INTAKE_KEY_PREFIX)


def second_admission_key(decision_id: str) -> str:
    """The worker's second-admission idempotency key: 64 hex, the S5 key pattern."""
    return hashlib.sha256(_SECOND_ADMISSION_DOMAIN + decision_id.encode("ascii")).hexdigest()
