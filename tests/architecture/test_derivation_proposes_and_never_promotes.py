"""Nothing derived promotes itself, and the claim is structural rather than stated.

`QC-AC-020` makes consequential classes review-gated, and the failure mode that
rule exists for is not a reviewer clicking the wrong button — it is a *derivation*
quietly writing its own output back as established fact. That path is easy to
open by accident and hard to notice, because it looks like a read.

Four properties, read off the tree rather than trusted:

1. **The Pulse derivation is a pure function.** `domain/situation/pulse_derivation.py`
   imports no persistence, no SQLAlchemy, and no infrastructure module, so there
   is nothing in it that could write.
2. **The repository's derivation is a read.** `SqlPulseRepository.derive_pulse`
   builds no `insert`, `update`, or `delete`, and calls nothing that does.
3. **Only one method writes `accepted` in the review-gated repository.**
   `ContinuityEvidenceState.ACCEPTED` appears in exactly one write in
   `situation_repository.py`, inside `SqlContinuityRepository.accept`; the
   three `propose_*` methods write the `PROPOSED` literal and take no
   parameter that could change it. User-directed Task authoring lives in
   `continuity_authoring.py` and is a different path.
4. **Acceptance is gated on a review decision.** `accept` reads
   `capture_review_decisions` before it writes, so promotion cannot happen
   without a review that happened.

**And four more on the entity plane, added by `WP-RI-B-05`.** The same failure
mode arrives there through a different door: `entities.proposals.create` gives a
source, rule or local-model producer a published way to write, and the thing
that must stay impossible is for that producer to reach the mutation its own
proposal describes.

5. **Proposing writes proposals and nothing else.** `EntityGovernanceService.propose`
   reaches exactly one write on the repository, takes no parameter that could
   name a decided state, and writes the proposed literal.
6. **Deciding is a different method that demands an actor**, so there is no
   path from producing to promoting that does not pass through somebody's name.
7. **No acceptance reaches an identity mutation.** `redirect_entity` and
   `record_merge` do not appear anywhere in `entity_governance`, which is the
   structural form of section 15: a reviewer's disposition is not an
   identity-correction grant.
8. **The promotion routing performs no write and routes no identity
   correction.** `application/entity_promotion.py` imports nothing that could
   write, and its table holds no entry for `merge_entities` or `split_identity`
   — so the mutation removed from acceptance cannot return by being routed to.

Nothing here opens a connection. It parses source.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"

DERIVATION: Final = PACKAGE / "domain" / "situation" / "pulse_derivation.py"
REPOSITORY: Final = PACKAGE / "infrastructure" / "persistence" / "situation_repository.py"
AUTHORING: Final = PACKAGE / "infrastructure" / "persistence" / "continuity_authoring.py"
GOVERNANCE: Final = PACKAGE / "application" / "entity_governance.py"
PROMOTION: Final = PACKAGE / "application" / "entity_promotion.py"

#: Statement builders that write. Named rather than inferred, because "does this
#: expression write" is not decidable in general and these five are what this
#: repository's persistence layer actually uses.
WRITERS: Final = frozenset({"insert", "update", "delete", "pg_insert", "execute"})


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.Module, *, klass: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == klass:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == name:
                    return member
    raise AssertionError(f"{klass}.{name} is not in the module; the guard is reading nothing")


def _called_names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if isinstance(target, ast.Name):
            found.add(target.id)
        elif isinstance(target, ast.Attribute):
            found.add(target.attr)
    return found


def test_the_derivation_module_imports_nothing_that_could_write() -> None:
    """Property 1. A pure function cannot promote, and this is why it is pure."""
    tree = _module(DERIVATION)
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported, "the import scan read nothing"
    forbidden = sorted(
        name
        for name in imported
        if name.startswith(("sqlalchemy", "psycopg", "my_pa.infrastructure", "my_pa.application"))
    )
    assert forbidden == [], (
        f"{DERIVATION.name} imports {forbidden}. The Pulse derivation is a read over "
        "rows it is handed; a module that can reach a connection is a module that can "
        "write its own output back as accepted state"
    )
    assert _called_names(tree).isdisjoint(WRITERS)


def test_the_repositorys_derivation_builds_no_write() -> None:
    """Property 2, over `derive_pulse` itself rather than over the module."""
    derive = _function(_module(REPOSITORY), klass="SqlPulseRepository", name="derive_pulse")
    called = _called_names(derive)
    assert "select" in called, "the guard is not reading a method that queries anything"
    writes = sorted(called & (WRITERS - {"execute"}))
    assert writes == [], (
        f"SqlPulseRepository.derive_pulse builds {writes}. A derivation that wrote its own "
        "output back would be automatic consequential promotion arriving through a listing"
    )


def test_only_the_acceptance_method_writes_the_accepted_state() -> None:
    """Property 3. One write, in one method, and the three proposers cannot reach it."""
    tree = _module(REPOSITORY)

    def _writes_accepted(node: ast.AST) -> bool:
        """Whether this function passes the accepted state into a `.values(...)`.

        A `.values(...)` keyword and not any mention of the name, because
        `derive_pulse` compares against `ACCEPTED` in a `WHERE` clause — reading
        only accepted rows is the point of it — and a guard that could not tell a
        predicate from an assignment would either miss the write or forbid the
        filter.
        """
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            target = child.func
            if not (isinstance(target, ast.Attribute) and target.attr == "values"):
                continue
            for keyword in child.keywords:
                if keyword.arg != "evidence_state":
                    continue
                if "ACCEPTED" in ast.dump(keyword.value):
                    return True
        return False

    methods_writing_accepted = sorted(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _writes_accepted(node)
    )
    assert methods_writing_accepted == ["accept"], (
        f"{methods_writing_accepted} assign the accepted state. Exactly one method may, and "
        "it is the one that first resolves a review decision"
    )
    # And the filter the guard deliberately does not read is still there, so the
    # distinction above is a distinction rather than a way of seeing nothing.
    derive = _function(tree, klass="SqlPulseRepository", name="derive_pulse")
    assert "ACCEPTED" in ast.dump(derive)

    for proposer in ("propose_commitment", "propose_decision", "propose_task"):
        method = _function(tree, klass="SqlContinuityRepository", name=proposer)
        source = ast.dump(method)
        assert "PROPOSED" in source, f"{proposer} does not write the proposed literal"
        assert "ACCEPTED" not in source
        arguments = {argument.arg for argument in method.args.kwonlyargs}
        assert "evidence_state" not in arguments, (
            f"{proposer} takes an evidence state. It must write the literal, so that no "
            "caller can propose something already accepted"
        )


def test_acceptance_reads_a_review_decision_before_it_writes() -> None:
    """Property 4. The gate is in the method, not in a caller's discipline."""
    accept = _function(_module(REPOSITORY), klass="SqlContinuityRepository", name="accept")
    names = {node.id for node in ast.walk(accept) if isinstance(node, ast.Name)}
    assert "capture_review_decisions" in names, (
        "SqlContinuityRepository.accept does not read the review plane. Promotion that "
        "does not require a review that happened is promotion by assertion"
    )


def test_user_directed_task_authoring_is_not_review_promotion() -> None:
    """Direct Principal authoring writes accepted state without a review decision."""
    author = _function(
        _module(AUTHORING), klass="SqlContinuityAuthoringRepository", name="author_task"
    )
    source = ast.dump(author)
    assert "ACCEPTED" in source
    assert "DIRECT_PRINCIPAL" in source
    assert "capture_review_decisions" not in source


# --- the entity plane: a producer cannot reach what it proposes --------------


#: The repository methods on `EntitiesRepository` that change an entity's
#: identity. Named rather than inferred, because "does this write" is decided by
#: the port's contract and not by the call site's spelling, and these two are the
#: pair `EntityGovernanceService._apply` used to call.
IDENTITY_WRITES: Final = frozenset({"redirect_entity", "record_merge"})

#: Every repository call a proposal producer is allowed to make. `record_proposal`
#: is the only write; the other three are the reads that refuse -- evidence that
#: is not this Principal's, evidence that is quarantined, and the open-equivalent
#: proposal a duplicate is answered with.
PRODUCER_REPOSITORY_CALLS: Final = frozenset(
    {"record_proposal", "observation", "proposals", "fact_evidence_links"}
)


def _repository_calls(node: ast.AST) -> set[str]:
    """Every `self._entities.<name>(...)` this function reaches directly."""
    found: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if not isinstance(target, ast.Attribute):
            continue
        owner = target.value
        if (
            isinstance(owner, ast.Attribute)
            and owner.attr == "_entities"
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
        ):
            found.add(target.attr)
    return found


def test_proposing_reaches_one_write_and_it_is_the_proposal_table() -> None:
    """Property 5. The producer path's whole reach, read off the source.

    `propose` delegates three checks to private helpers, so the guard walks the
    method *and* the helpers it calls: a write moved one level down would
    otherwise be invisible to a scan of the entry point alone.
    """
    tree = _module(GOVERNANCE)
    reached: set[str] = set()
    for name in ("propose", "_admit_evidence", "_refuse_a_known_bad_proposal", "_open_equivalent"):
        reached |= _repository_calls(_function(tree, klass="EntityGovernanceService", name=name))
    assert "record_proposal" in reached, "the guard is not reading a method that records anything"
    forbidden = sorted(reached - PRODUCER_REPOSITORY_CALLS)
    assert forbidden == [], (
        f"the producer path reaches {forbidden}. A producer that can reach a canonical write "
        "is a producer that can promote its own proposal without a review"
    )


def test_proposing_writes_the_proposed_literal_and_takes_no_state() -> None:
    """Property 5, the other half — `propose_*`'s rule on the entity plane.

    The state is written as a literal, and there is no parameter through which a
    caller could supply one, so a proposal cannot arrive already accepted.
    """
    propose = _function(_module(GOVERNANCE), klass="EntityGovernanceService", name="propose")
    source = ast.dump(propose)
    assert "PROPOSED" in source
    for decided in ("ACCEPTED", "CORRECTED_ACCEPTED", "REJECTED"):
        assert decided not in source, f"propose mentions {decided}"
    arguments = {argument.arg for argument in propose.args.kwonlyargs}
    for reserved in ("state", "decided_by", "decided_at", "proposal_id", "dedupe_sha256"):
        assert reserved not in arguments, (
            f"propose takes {reserved}. Every one of these is the server's, and a producer "
            "that could supply one could file a proposal that had already been decided"
        )


def test_deciding_is_a_separate_method_that_demands_an_actor() -> None:
    """Property 6. There is no path from producing to promoting without a name."""
    tree = _module(GOVERNANCE)
    decide = _function(tree, klass="EntityGovernanceService", name="_decide")
    arguments = {argument.arg for argument in decide.args.kwonlyargs}
    assert {"state", "decided_by", "decided_at", "has_operator_authority"} <= arguments
    assert "names who made it" in ast.dump(decide), (
        "_decide no longer refuses a blank actor; a decision nobody signed is a decision "
        "a producer could have made"
    )
    propose = _function(tree, klass="EntityGovernanceService", name="propose")
    assert "_decide" not in _called_names(propose)


def test_no_acceptance_on_this_plane_reaches_an_identity_mutation() -> None:
    """Property 7, and the structural form of `WP-RI-B-05`.

    Read over the whole module rather than over one method, because the point is
    that there is nowhere in it for a merge to live. Restoring the redirect and
    the lineage write inside the decision path — the code this replaced — turns
    this red without needing the guard to know which method they were put in.
    """
    tree = _module(GOVERNANCE)
    reached = _repository_calls(tree)
    assert reached, "the guard read no repository call at all"
    identity = sorted(reached & IDENTITY_WRITES)
    assert identity == [], (
        f"entity_governance reaches {identity}. Identity mutation is an operator act under "
        "entity_identity_correction; a review disposition that could reach it would make a "
        "reviewer grant an identity-correction grant"
    )
    # And the module still reaches the *read* of that lineage, so the assertion
    # above is about writes rather than about the merge vocabulary disappearing.
    assert "merges" in reached


def test_the_promotion_routing_imports_nothing_that_could_write() -> None:
    """Property 8. Routing is a decision about which command; it is not the write."""
    tree = _module(PROMOTION)
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported, "the import scan read nothing"
    forbidden = sorted(
        name
        for name in imported
        if name.startswith(("sqlalchemy", "psycopg", "my_pa.infrastructure"))
        or name.endswith("contracts.ports")
    )
    assert forbidden == [], (
        f"{PROMOTION.name} imports {forbidden}. A module that can reach a repository is a "
        "module in which promotion could stop being the Review path's act"
    )
    assert _called_names(tree).isdisjoint(WRITERS)


def test_the_promotion_table_routes_no_identity_correction() -> None:
    """Property 8, the half that matters most.

    `_apply` used to merge on acceptance. Removing it is only half a correction
    if the promotion table that replaced it holds an entry for the same kinds,
    so the keys are read out of the source and the two are required to be
    absent.
    """
    tree = _module(PROMOTION)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if (
                isinstance(key, ast.Attribute)
                and isinstance(key.value, ast.Name)
                and key.value.id == "EntityProposalKind"
            ):
                keys.add(key.attr)
    assert "RECORD_ALIAS" in keys, "the guard is not reading the promotion table"
    assert "MERGE_ENTITIES" not in keys
    assert "SPLIT_IDENTITY" not in keys


@pytest.mark.parametrize(
    "path", [DERIVATION, REPOSITORY, AUTHORING, GOVERNANCE, PROMOTION], ids=lambda p: p.name
)
def test_the_modules_this_guard_reads_exist_and_parse(path: Path) -> None:
    """Guards every assertion above: a moved file would make them all vacuous."""
    assert path.is_file()
    assert len(_module(path).body) > 5
