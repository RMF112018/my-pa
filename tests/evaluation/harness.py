"""Run the frozen semantic-retrieval benchmark and emit a gate record.

Lexical/structured ranking uses the production reason-code assignment and
`rank_and_pack`. The candidate is evaluation-only: the same authorized excerpts
scored by standard-library overlap, merged as a hypothetical rank, then packed
with the same identity, diversity, and byte rules. Neither path writes
embeddings, enables `hybrid_semantic`, or lives in `src/` retrieval.
"""

from __future__ import annotations

import json
import math
import tomllib
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Final

from my_pa.application.context.providers import _reason_codes
from my_pa.application.context.ranking import (
    PackedEvidence,
    apply_preferences,
    identity_key,
    rank_and_pack,
)
from my_pa.application.context.semantic_gate import (
    K_RECALL,
    PARAPHRASE_RECALL_AT_8_MIN_ABSOLUTE_DELTA,
    SEMANTIC_GATE_FAIL,
    SEMANTIC_GATE_PASS,
)
from my_pa.application.context.service import _hints_with_aliases
from my_pa.domain.context.prepared import (
    DEFAULT_EVIDENCE_BYTES,
    ContextLimitationCode,
    ContextPlane,
    ContextTruncation,
    ContradictionCode,
    EvidenceLifecycle,
    PreparedContextEvidence,
    SelectionReasonCode,
)
from my_pa.domain.search.query import SearchQuery
from tests.evaluation.candidate import CANDIDATE_MIN_SCORE, merged_overlap_score
from tests.evaluation.fixtures.cases import FROZEN_CASES, FrozenCase
from tests.evaluation.fixtures.corpus import SYNTHETIC_CORPUS

ROOT: Final = Path(__file__).resolve().parents[2]
REPORT_PATH: Final = Path(__file__).resolve().parent / "SEMANTIC_GATE.md"
PYPROJECT: Final = ROOT / "pyproject.toml"
GATE_DATE: Final = "2026-08-15"
_FORBIDDEN_DISTRIBUTIONS: Final = frozenset(
    {
        "openai",
        "anthropic",
        "cohere",
        "voyageai",
        "mistralai",
        "sentence_transformers",
        "transformers",
        "torch",
        "tensorflow",
        "onnxruntime",
        "faiss",
        "pgvector",
        "chromadb",
        "pinecone",
        "qdrant_client",
        "weaviate",
        "lancedb",
        "milvus",
        "llama_index",
        "langchain",
        "haystack",
        "ollama",
        "litellm",
        "huggingface_hub",
        "sklearn",
    }
)
_REASON_PRIORITY: Final[dict[SelectionReasonCode, int]] = {
    SelectionReasonCode.EXPLICIT_SUBJECT: 0,
    SelectionReasonCode.EXACT_IDENTIFIER: 0,
    SelectionReasonCode.CONFIRMED_ALIAS: 1,
    SelectionReasonCode.PROJECT_LINK: 1,
    SelectionReasonCode.SITUATION_LINK: 1,
    SelectionReasonCode.RELATIONSHIP_LINK: 1,
    SelectionReasonCode.PINNED_FOCUS: 1,
    SelectionReasonCode.ACCEPTED_RECORD: 2,
    SelectionReasonCode.LEXICAL_STRONG: 3,
    SelectionReasonCode.LEXICAL_MODERATE: 4,
    SelectionReasonCode.RECENT_EVIDENCE: 5,
    SelectionReasonCode.SEMANTIC_MATCH: 6,
}


def _best_priority(item: PreparedContextEvidence) -> int:
    if not item.reason_codes:
        return max(_REASON_PRIORITY.values()) + 1
    return min(_REASON_PRIORITY[code] for code in item.reason_codes)


def _identities(item: PreparedContextEvidence) -> frozenset[str]:
    return frozenset(
        value
        for value in (
            item.reference_id,
            item.knowledge_id,
            item.source_id,
            item.source_object_id,
            item.source_version_id,
            item.capture_id,
            item.capture_version_id,
            item.product_id,
            item.managed_document_id,
            item.managed_document_version_id,
        )
        if value is not None
    )


def _group_key(item: PreparedContextEvidence) -> str:
    return (
        item.source_id
        or item.capture_id
        or item.product_id
        or item.managed_document_id
        or item.reference_id
    )


def _authorized(principal_id: str) -> tuple[PreparedContextEvidence, ...]:
    return tuple(item for item in SYNTHETIC_CORPUS if item.principal_id == principal_id)


def _assign_lexical(
    items: tuple[PreparedContextEvidence, ...],
    case: FrozenCase,
) -> tuple[PreparedContextEvidence, ...]:
    query = SearchQuery(case.query)
    hints = _hints_with_aliases(
        (),
        case.preferences,
        query=case.query,
        conversation_context=None,
    )
    assigned: list[PreparedContextEvidence] = []
    for item in items:
        codes = _reason_codes(
            identities=_identities(item),
            searchable=item.text,
            query=query,
            extra_terms=(),
            subject_hints=hints,
            accepted=item.lifecycle is EvidenceLifecycle.ACCEPTED,
        )
        if not codes:
            continue
        assigned.append(replace(item, reason_codes=codes))
    boosted, _applied, _limitations = apply_preferences(
        tuple(assigned),
        case.preferences,
        query=case.query,
        conversation_context=None,
    )
    return boosted


def _pack_in_order(
    ordered: tuple[PreparedContextEvidence, ...],
    *,
    max_items: int,
    max_bytes: int,
) -> PackedEvidence:
    seen: set[tuple[ContextPlane, str, str]] = set()
    unique: list[PreparedContextEvidence] = []
    for item in ordered:
        key = (item.plane, identity_key(item), item.text)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    cap = max(2, math.ceil(max_items / 3))
    packed: list[PreparedContextEvidence] = []
    group_counts: dict[str, int] = {}
    total_bytes = 0
    dropped = False
    for item in unique:
        group = _group_key(item)
        if group_counts.get(group, 0) >= cap:
            dropped = True
            continue
        size = len(item.text.encode())
        if len(packed) >= max_items or total_bytes + size > max_bytes:
            dropped = True
            continue
        packed.append(item)
        group_counts[group] = group_counts.get(group, 0) + 1
        total_bytes += size
    packed_items = tuple(packed)
    contradictions: tuple[ContradictionCode, ...] = ()
    fingerprints: dict[str, set[str]] = {}
    versions: dict[str, set[str]] = {}
    for item in packed_items:
        if item.product_id is not None:
            fingerprints.setdefault(item.product_id, set()).add(item.text)
        if item.source_object_id is not None and item.source_version_id is not None:
            versions.setdefault(item.source_object_id, set()).add(item.source_version_id)
    if any(len(values) > 1 for values in fingerprints.values()) or any(
        len(values) > 1 for values in versions.values()
    ):
        contradictions = (ContradictionCode.CONFLICTING_EVIDENCE,)
    limitations: tuple[ContextLimitationCode, ...] = ()
    if dropped:
        limitations = (ContextLimitationCode.RESULT_TRUNCATED,)
    return PackedEvidence(
        items=packed_items,
        truncation=ContextTruncation(
            is_truncated=dropped, reason="item_budget" if dropped else None
        ),
        contradictions=contradictions,
        limitations=limitations,
    )


def _lexical_pack(case: FrozenCase, *, max_items: int) -> PackedEvidence:
    scored = _assign_lexical(_authorized(case.principal_id), case)
    return rank_and_pack(scored, max_items=max_items, max_bytes=DEFAULT_EVIDENCE_BYTES)


def _candidate_pack(case: FrozenCase, *, max_items: int) -> PackedEvidence:
    authorized = _authorized(case.principal_id)
    lexical = {item.reference_id: item for item in _assign_lexical(authorized, case)}
    scored: list[tuple[PreparedContextEvidence, float]] = []
    for item in authorized:
        overlap = merged_overlap_score(case.query, item.text)
        held = lexical.get(item.reference_id)
        if held is not None:
            scored.append((held, overlap))
            continue
        if overlap < CANDIDATE_MIN_SCORE:
            continue
        scored.append((replace(item, reason_codes=(SelectionReasonCode.SEMANTIC_MATCH,)), overlap))
    ordered = tuple(
        item
        for item, _score in sorted(
            scored,
            key=lambda pair: (_best_priority(pair[0]), -pair[1], pair[0].reference_id),
        )
    )
    return _pack_in_order(ordered, max_items=max_items, max_bytes=DEFAULT_EVIDENCE_BYTES)


def _duplicate_rate(items: tuple[PreparedContextEvidence, ...]) -> float:
    if not items:
        return 0.0
    counts = Counter(identity_key(item) for item in items)
    extra = sum(count - 1 for count in counts.values() if count > 1)
    return extra / len(items)


def _first_relevant_rank(
    items: tuple[PreparedContextEvidence, ...], relevant: frozenset[str]
) -> int | None:
    for index, item in enumerate(items, start=1):
        if item.reference_id in relevant or bool(_identities(item) & relevant):
            return index
    return None


def _hits(items: tuple[PreparedContextEvidence, ...], relevant: frozenset[str]) -> int:
    found = 0
    for identity in relevant:
        if any(identity in _identities(item) or item.reference_id == identity for item in items):
            found += 1
    return found


def _leakage(items: tuple[PreparedContextEvidence, ...], forbidden: frozenset[str]) -> int:
    if not forbidden:
        return 0
    return sum(
        1 for item in items if item.reference_id in forbidden or bool(_identities(item) & forbidden)
    )


def _instruction_authority_true(items: tuple[PreparedContextEvidence, ...]) -> int:
    return sum(1 for item in items if item.instruction_authority)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _path_metrics(
    packer: Callable[..., PackedEvidence], *, max_items: int
) -> dict[str, float | int]:
    known_recall: list[float] = []
    paraphrase_recall: list[float] = []
    exact_recall: list[float] = []
    reciprocal_ranks: list[float] = []
    duplicate_rates: list[float] = []
    instruction_true = 0
    leakage = 0
    missing_required = 0
    for case in FROZEN_CASES:
        packed = packer(case, max_items=max_items)
        items = packed.items
        instruction_true += _instruction_authority_true(items)
        leakage += _leakage(items, case.forbidden_ids)
        duplicate_rates.append(_duplicate_rate(items))
        if case.require_return and not all(
            any(identity in _identities(item) or item.reference_id == identity for item in items)
            for identity in case.require_return
        ):
            missing_required += 1
        if not case.relevant_ids:
            continue
        hits = _hits(items, case.relevant_ids)
        recall = hits / len(case.relevant_ids)
        known_recall.append(recall)
        if case.family == "paraphrase":
            paraphrase_recall.append(recall)
        if case.family == "exact_id":
            exact_recall.append(recall)
        rank = _first_relevant_rank(items, case.relevant_ids)
        reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
    return {
        "recall_at_k": round(_mean(known_recall), 4),
        "paraphrase_recall_at_k": round(_mean(paraphrase_recall), 4),
        "exact_id_recall_at_k": round(_mean(exact_recall), 4),
        "mrr": round(_mean(reciprocal_ranks), 4),
        "duplicate_rate_after_packing": round(_mean(duplicate_rates), 4),
        "instruction_authority_true": instruction_true,
        "cross_principal_leakage": leakage,
        "missing_required_returns": missing_required,
    }


def _distribution_named(requirement: str) -> str:
    head = requirement.strip().split("[", 1)[0]
    head = head.split("<", 1)[0].split(">", 1)[0].split("=", 1)[0].split("!", 1)[0].split(";", 1)[0]
    return head.replace("-", "_").replace(".", "_").lower().strip()


def _declared_requirements(document: object, *, within: bool = False) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(document, dict):
        for name, value in document.items():
            named = "depend" in str(name) or "requires" in str(name)
            found.extend(_declared_requirements(value, within=within or named))
    elif isinstance(document, list):
        if within:
            found.extend(item for item in document if isinstance(item, str))
        else:
            for item in document:
                found.extend(_declared_requirements(item))
    return tuple(found)


def _new_dependency_count() -> int:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    forbidden = {name.replace("-", "_") for name in _FORBIDDEN_DISTRIBUTIONS}
    return sum(
        1
        for requirement in _declared_requirements(document)
        if _distribution_named(requirement) in forbidden
    )


def decide_disposition(
    baseline_at_8: dict[str, float | int],
    candidate_at_8: dict[str, float | int],
) -> str:
    paraphrase_delta = float(candidate_at_8["paraphrase_recall_at_k"]) - float(
        baseline_at_8["paraphrase_recall_at_k"]
    )
    exact_drop = float(candidate_at_8["exact_id_recall_at_k"]) < float(
        baseline_at_8["exact_id_recall_at_k"]
    )
    if (
        paraphrase_delta >= PARAPHRASE_RECALL_AT_8_MIN_ABSOLUTE_DELTA
        and not exact_drop
        and int(baseline_at_8["cross_principal_leakage"]) == 0
        and int(candidate_at_8["cross_principal_leakage"]) == 0
        and int(baseline_at_8["instruction_authority_true"]) == 0
        and int(candidate_at_8["instruction_authority_true"]) == 0
        and _new_dependency_count() == 0
        and int(baseline_at_8["missing_required_returns"]) == 0
        and int(candidate_at_8["missing_required_returns"]) == 0
    ):
        return SEMANTIC_GATE_PASS
    return SEMANTIC_GATE_FAIL


def compute_gate_record() -> dict[str, object]:
    baseline_8 = _path_metrics(_lexical_pack, max_items=K_RECALL[0])
    baseline_16 = _path_metrics(_lexical_pack, max_items=K_RECALL[1])
    candidate_8 = _path_metrics(_candidate_pack, max_items=K_RECALL[0])
    candidate_16 = _path_metrics(_candidate_pack, max_items=K_RECALL[1])
    disposition = decide_disposition(baseline_8, candidate_8)
    paraphrase_delta = round(
        float(candidate_8["paraphrase_recall_at_k"]) - float(baseline_8["paraphrase_recall_at_k"]),
        4,
    )
    return {
        "date": GATE_DATE,
        "disposition": disposition,
        "production_semantic_authorized": disposition == SEMANTIC_GATE_PASS,
        "k": list(K_RECALL),
        "paraphrase_recall_at_8_min_absolute_delta": PARAPHRASE_RECALL_AT_8_MIN_ABSOLUTE_DELTA,
        "baseline": {"k8": baseline_8, "k16": baseline_16},
        "candidate": {"k8": candidate_8, "k16": candidate_16},
        "paraphrase_delta_at_8": paraphrase_delta,
        "new_forbidden_dependency_count": _new_dependency_count(),
        "note": (
            "Production semantic retrieval is not authorized. "
            "context.prepare remains lexical_structured. WP-KC-08 runs only after "
            "SEMANTIC_GATE_PASS."
        ),
    }


def render_report(record: dict[str, object]) -> str:
    payload = json.dumps(record, indent=2, sort_keys=True)
    disposition = record["disposition"]
    return (
        "# Semantic retrieval gate\n\n"
        f"Date: {record['date']}\n\n"
        f"Disposition: `{disposition}`\n\n"
        "Production semantic retrieval is **not authorized**. The active path is "
        "lexical/structured `context.prepare`. This file is the frozen WP-KC-07 "
        "decision. Re-run the evaluation to recompute; the JSON record below must "
        "match the harness exactly.\n\n"
        "```json\n"
        f"{payload}\n"
        "```\n"
    )


def load_frozen_record(path: Path = REPORT_PATH) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    start = text.index("```json\n") + len("```json\n")
    end = text.index("\n```", start)
    loaded: object = json.loads(text[start:end])
    if not isinstance(loaded, dict):
        raise TypeError("semantic gate record must be an object")
    return loaded
