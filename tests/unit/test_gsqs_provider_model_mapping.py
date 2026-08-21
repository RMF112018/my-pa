"""Exact-string provider model mapping. No inferred aliases."""

from __future__ import annotations

from my_pa.application.goodnotes_gsqs_provider_model_mapping import (
    SelectedModelMappingState,
    classify_selected_model,
    mapping_from_payload,
)


def _mapping() -> object:
    return mapping_from_payload(
        {
            "evidence_id": "map-1",
            "mapping_schema_version": "gsqs-b0-provider-model-mapping-v1",
            "entries": [
                {
                    "display_name": "GPT-5.6 Terra",
                    "pool_membership": "IN_POOL",
                    "provider_model_id": "gpt-5.6-terra",
                },
                {
                    "display_name": "mystery-out",
                    "pool_membership": "OUT_OF_POOL",
                    "provider_model_id": "mystery-out",
                },
            ],
        },
        expected_evidence_id="map-1",
    )


def test_exact_in_pool_and_out_of_pool() -> None:
    mapping = _mapping()
    state, display = classify_selected_model("gpt-5.6-terra", mapping)
    assert state is SelectedModelMappingState.MAPPED_IN_POOL
    assert display == "GPT-5.6 Terra"
    state, _display = classify_selected_model("mystery-out", mapping)
    assert state is SelectedModelMappingState.MAPPED_OUT_OF_POOL


def test_unmapped_is_not_out_of_pool() -> None:
    mapping = _mapping()
    for observed in (
        None,
        "",
        "route-llm",
        "GPT-5.6 Terra",
        "gpt-5.6-Terra",
        "gpt-5.6-terra ",
        "gpt_5.6_terra",
        "gpt-5.6terra",
        "unknown-id",
    ):
        state, _display = classify_selected_model(observed, mapping)
        assert state is not SelectedModelMappingState.MAPPED_OUT_OF_POOL
        if observed in {None, ""}:
            assert state is SelectedModelMappingState.ABSENT
        elif observed == "route-llm":
            assert state is SelectedModelMappingState.UNATTESTED
        else:
            assert state is SelectedModelMappingState.UNMAPPED


def test_missing_mapping_treats_ids_as_unmapped() -> None:
    state, _display = classify_selected_model("gpt-5.6-terra", None)
    assert state is SelectedModelMappingState.UNMAPPED
    state, _display = classify_selected_model("route-llm", None)
    assert state is SelectedModelMappingState.UNATTESTED
