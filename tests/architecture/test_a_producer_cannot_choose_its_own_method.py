"""What produced a proposal is the server's answer, and the *dispatcher's* too.

Operator sections 11 and 12 make the proposal method and the model identity
server-owned, and two mechanisms already keep a caller from stating one: the
commands carry no such field, so a payload naming one is refused by the
constructor, and `FORBIDDEN_PAYLOAD_FIELDS` refuses the names again inside the
nested proposal payload.

**Neither of those is the claim this file makes.** B2 named the residual risk in
one sentence and it is worth quoting rather than paraphrasing: *a payload cannot
carry `method`, but nothing yet proves the dispatcher did not choose it from
something the caller influenced*. Absence on the command closes the wire; it says
nothing about the line of code that decides what to pass. A dispatcher that read
`command.proposed_by` and mapped it to a method, or branched on the payload's
kind, or consulted a header, would satisfy every existing test and would hand a
reviewer a provenance the caller picked.

So the separation is made structural in the one place it can be, and measured
here: `ApplicationService._proposal_origin` and
`ApplicationService._memory_proposal_origin` **take no parameters**. A function
with no parameters cannot have been influenced by a request, whatever is written
inside it, and that is a property `ast` can read off the signature rather than a
property a reader has to trust a body for.

**The residual gap, stated rather than closed.** There is no producer registry at
this head: nothing maps an authenticated client to the method it is registered as
using, so every proposal this build records carries the same method, and `method`
distinguishes no producer from another. That is a real limitation and it is a
*different* limitation from the one this file forecloses -- an uninformative
value is not a caller-chosen one. Closing it needs a grant-profile change WP-09
owns. What is closed here is that the value cannot become caller-chosen by a
later edit to the dispatcher without this test going red.

`local_model` is unreachable from any transport for a related and stronger
reason: the schema requires `model_id` on a `local_model` proposal, no handler
passes one, and `RelationshipMemoryProposal.__post_init__` and
`a_model_proposal_names_its_model` both refuse the pairing. That is asserted here
too, because "no path can claim a model ran" is the sharpest half of what section
21.4 is protecting.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from my_pa.application.commands import (
    CreateEntityProposal,
    ProposeRelationshipMemory,
)
from my_pa.application.service import ApplicationService
from my_pa.domain.relationship.governance import EntityProposalMethod
from my_pa.domain.relationship.memory import MemoryProposalMethod
from my_pa.domain.relationship.proposal_payload import FORBIDDEN_PAYLOAD_FIELDS

ROOT: Final = Path(__file__).resolve().parents[2]
SERVICE: Final = ROOT / "src" / "my_pa" / "application" / "service.py"

#: The two methods that decide what produced a proposal, and the claim about each.
ORIGIN_METHODS: Final = ("_proposal_origin", "_memory_proposal_origin")

#: Every field name that would state a method or a model, on either plane.
PROVENANCE_FIELDS: Final = frozenset(
    {"method", "method_version", "model_id", "model_version"}
)


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"), filename=str(SERVICE))
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, f"{name} is defined {len(found)} times in {SERVICE.name}"
    return found[0]


@pytest.mark.parametrize("name", ORIGIN_METHODS)
def test_the_origin_decision_takes_nothing_a_caller_could_have_influenced(name: str) -> None:
    """The signature is the guarantee, and it is read rather than reasoned about.

    `self` and nothing else. Not the command, not the payload, not the
    authorization, not the transport. Every argument a dispatcher could derive a
    method from is absent from the place the method is decided, so deriving one
    is a signature change and a red test rather than a line nobody notices.
    """
    function = _function(name)
    arguments = function.args
    names = [argument.arg for argument in arguments.posonlyargs + arguments.args]
    assert names == ["self"], (
        f"`{name}` now takes {names[1:]}. A parameter here is a value the "
        "dispatcher could choose a proposal method from, and operator sections 11 "
        "and 12 make that the server's decision rather than one derived from a "
        "request"
    )
    assert not arguments.kwonlyargs, f"`{name}` takes keyword-only arguments"
    assert arguments.vararg is None and arguments.kwarg is None


@pytest.mark.parametrize("name", ORIGIN_METHODS)
def test_the_origin_decision_reads_no_attribute_of_anything(name: str) -> None:
    """A no-parameter function can still reach a request through `self`.

    It cannot here, and this is what says so: the only attributes either method
    reads are class constants on `self`. Reaching `self._something` that held a
    request would be the same defect one level in, and this walk sees it.
    """
    function = _function(name)
    reached = {
        node.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    }
    assert reached <= {
        "_PROPOSAL_METHOD",
        "_PROPOSAL_METHOD_VERSION",
        "_MEMORY_PROPOSAL_METHOD",
        "_MEMORY_PROPOSAL_METHOD_VERSION",
    }, f"`{name}` reads {sorted(reached)} off `self`; only the frozen constants belong here"


@pytest.mark.parametrize("command", [CreateEntityProposal, ProposeRelationshipMemory])
def test_no_producer_command_carries_a_method_or_a_model(command: type) -> None:
    """The other half, restated where this file can see it beside the first.

    Absence on the command is what closes the wire; the two tests above are what
    close the dispatcher. Both are needed, and a reader looking at one should be
    able to see the other.
    """
    import dataclasses

    named = {field.name for field in dataclasses.fields(command)}
    assert not named & PROVENANCE_FIELDS, (
        f"{command.__name__} declares {sorted(named & PROVENANCE_FIELDS)}; a field "
        "that can be sent is a field a later change can start honouring"
    )


def test_the_nested_proposal_payload_refuses_the_same_names() -> None:
    """And once more inside the payload, which is the third place they could arrive."""
    assert PROVENANCE_FIELDS <= FORBIDDEN_PAYLOAD_FIELDS


def test_the_recorded_method_claims_no_more_than_the_server_can_attest() -> None:
    """`rule`, on both planes, and the direction of the error is the reason.

    `EntityProposalMethod`'s own docstring names the danger: "a model conclusion
    filed as a deterministic match is a model conclusion a threshold would accept
    without a person". Filing every producer's work as `deterministic` is exactly
    that record. `rule` is the least specific true statement this build can make
    about a governed producer path -- something ran and asked -- and it claims no
    exact match.

    The method version names the thing that actually chose the method, which is
    the dispatcher. A reviewer reading `rule / entity-proposal-dispatch.1` learns
    precisely what the server can attest.
    """
    assert ApplicationService._PROPOSAL_METHOD is EntityProposalMethod.RULE
    assert ApplicationService._MEMORY_PROPOSAL_METHOD is MemoryProposalMethod.RULE
    assert ApplicationService._PROPOSAL_METHOD_VERSION == "entity-proposal-dispatch.1"
    assert ApplicationService._MEMORY_PROPOSAL_METHOD_VERSION == "memory-proposal-dispatch.1"
    assert ApplicationService._PROPOSAL_METHOD is not EntityProposalMethod.DETERMINISTIC
    assert ApplicationService._MEMORY_PROPOSAL_METHOD is not MemoryProposalMethod.DETERMINISTIC


def test_no_dispatched_path_can_claim_a_local_model_ran() -> None:
    """`local_model` is unreachable, and it is unreachable in two ways at once.

    Neither origin decision returns it, and neither *names* a model at all --
    which the schema and both domain records require of a `local_model` proposal,
    so a build that started returning the method without the identity would be
    refused at the constructor rather than recording a model that does not exist.
    The second half is read off the source rather than by calling the method,
    which keeps this file's whole claim on one mechanism: the text of the two
    decisions, not their return values on one invocation.
    """
    assert ApplicationService._PROPOSAL_METHOD is not EntityProposalMethod.LOCAL_MODEL
    assert ApplicationService._MEMORY_PROPOSAL_METHOD is not MemoryProposalMethod.LOCAL_MODEL
    for name in ORIGIN_METHODS:
        # The body without its docstring: both methods *describe* the model
        # pairing in prose, which is the explanation and not a reach.
        function = _function(name)
        body = [node for node in function.body if not _is_docstring(node)]
        rendered = "\n".join(ast.unparse(node) for node in body)
        assert "model_id" not in rendered, f"`{name}` names a model identity"
        assert "model_version" not in rendered, f"`{name}` names a model version"
        assert "LOCAL_MODEL" not in rendered, f"`{name}` names the local-model method"
