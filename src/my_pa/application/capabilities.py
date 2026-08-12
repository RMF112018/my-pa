"""The capability manifest and readiness report, derived from the wiring.

The manifest used to report every capability `not_implemented` from a constant,
and readiness `contracts_only` from counting that constant. Both were honest
then and would have stayed honest-looking after the capabilities were built,
which is the failure mode: a manifest that is a constant reports whatever it was
last edited to say, and nobody edits it at the moment a capability starts
working.

So availability is not stated here. It is *asked* of the thing that would have
to execute the capability — `application.service.ApplicationService` builds its
dispatch table and passes its keys as `implemented`, so a capability appears
`available` exactly when there is a handler bound to it and `not_implemented`
otherwise. There is no constant to edit and no second list to forget.

Content types are derived the same way, from `domain.extraction.text.SUPPORTED_MEDIA_TYPES`
— the set the extractor actually reads — rather than from a list beside it.
`application/pdf` is the one value that is stated: it is `decision_gated` because
`P00-OD-003` is an open operator decision, which is a fact about the decision
ledger and not about the code, and reporting it as merely unimplemented would
lose the distinction section 12 requires between "not supported" and "not
decided".

The limits are the object the enforcing code path reads. `capabilities.get`
publishes the same `EffectiveLimits` instance that `sources.fetch` clamps
against, that `sources.list` sizes its page from, and that `sources.enroll`
bounds its depth by, so the published maximum cannot drift from the enforced one
— there is only one of them (`D-24`).
"""

from __future__ import annotations

from my_pa.contracts.v1.capabilities import (
    Availability,
    CapabilityManifest,
    CapabilityStatus,
    ContentTypeStatus,
    EffectiveLimits,
    ReadinessReport,
    ReadinessState,
)
from my_pa.domain.extraction.text import SUPPORTED_MEDIA_TYPES
from my_pa.domain.identity.operation import Capability, is_operator_only
from my_pa.domain.modeling.gate import ModelRoutePolicy

__all__ = [
    "DECISION_GATED_MEDIA_TYPE",
    "build_capability_manifest",
    "build_readiness_report",
]

#: Reported rather than silently absent, and `decision_gated` rather than
#: unavailable, because the reason it cannot be read is an operator decision
#: (`P00-OD-003`) and not a missing implementation.
DECISION_GATED_MEDIA_TYPE = "application/pdf"


def _content_types(implemented: frozenset[Capability]) -> tuple[ContentTypeStatus, ...]:
    """Which media types this build can actually do something with.

    Derived from the extractor's own supported set and from whether the
    capability that reads content is wired. A build with no `sources.fetch` can
    decode nothing, whatever the extractor supports, so reporting those types
    available would overstate what a caller could obtain.
    """
    readable = Capability.SOURCES_FETCH in implemented
    availability = Availability.AVAILABLE if readable else Availability.NOT_IMPLEMENTED
    return (
        *(
            ContentTypeStatus(media_type=media_type, availability=availability)
            for media_type in sorted(SUPPORTED_MEDIA_TYPES)
        ),
        ContentTypeStatus(
            media_type=DECISION_GATED_MEDIA_TYPE, availability=Availability.DECISION_GATED
        ),
    )


def build_capability_manifest(
    *, implemented: frozenset[Capability], limits: EffectiveLimits
) -> CapabilityManifest:
    """Return the manifest for a build that can execute `implemented`.

    Every capability in the contract appears, whether or not it is implemented,
    so a caller cannot mistake absence for unavailability.
    """
    return CapabilityManifest(
        capabilities=tuple(
            CapabilityStatus(
                name=capability,
                availability=(
                    Availability.AVAILABLE
                    if capability in implemented
                    else Availability.NOT_IMPLEMENTED
                ),
                operator_only=is_operator_only(capability),
            )
            for capability in Capability
        ),
        content_types=_content_types(implemented),
        limits=limits,
    )


def _limitations(
    manifest: CapabilityManifest,
    implemented: int,
    model_route: ModelRoutePolicy,
) -> tuple[str, ...]:
    """What a caller should know about a build in this state.

    Derived from the manifest rather than written beside it, so a limitation
    cannot outlive the condition that produced it.
    """
    limitations: list[str] = []
    if implemented < len(manifest.capabilities):
        missing = len(manifest.capabilities) - implemented
        limitations.append(f"{missing} of {len(manifest.capabilities)} capabilities are unwired.")
    gated = sorted(
        status.media_type
        for status in manifest.content_types
        if status.availability is Availability.DECISION_GATED
    )
    if gated:
        limitations.append(
            f"Content types awaiting an operator decision: {', '.join(gated)}. "
            "They are reported rather than silently skipped."
        )
    # A line saying "no durable audit store exists" stood here until WP-4B2a.
    # WP-4B1 built one; the sentence outlived its condition because it was
    # written beside the derivation rather than inside it, which is the exact
    # failure this module's docstring describes for the manifest. Removed rather
    # than restated: the audit is durable, and a readiness limitation exists to
    # tell a caller what this build cannot do.
    limitations.append(
        "Listings stop at the page size and issue no continuation cursor; truncation is disclosed."
    )
    if model_route is ModelRoutePolicy.DISABLED:
        limitations.append(
            "Model proposals and semantic retrieval are disabled; deterministic lexical "
            "retrieval remains active."
        )
    return tuple(limitations)


def build_readiness_report(
    manifest: CapabilityManifest,
    *,
    model_route: ModelRoutePolicy = ModelRoutePolicy.DISABLED,
) -> ReadinessReport:
    """Return readiness derived from `manifest`.

    Counting the manifest rather than asserting a state means the report cannot
    claim readiness the manifest does not support, and cannot keep claiming
    `contracts_only` once the manifest stops saying so.
    """
    implemented = sum(
        1 for status in manifest.capabilities if status.availability is Availability.AVAILABLE
    )
    if implemented == 0:
        state = ReadinessState.CONTRACTS_ONLY
    elif implemented == len(manifest.capabilities):
        state = ReadinessState.READY
    else:
        state = ReadinessState.DEGRADED
    return ReadinessReport(
        state=state,
        implemented_capabilities=implemented,
        limitations=_limitations(manifest, implemented, model_route),
    )
