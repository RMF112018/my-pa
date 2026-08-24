"""The acting Principal is derived from validated identity, never read from the caller.

WP-04, MU-AC-02, and `docs/specs` section 8.2. A caller-supplied identifier may
*arrive* — `RequestMetadata.principal_id` is a required field on every public
request, the CLI has a `--principal-id` flag, and the MCP tool schema publishes
the same envelope — and none of that is a defect. `RequestMetadata`'s own
docstring says why: the field is correlation input. The defect would be a
production module that *read* it and acted on it, because at that point the
caller has named the partition its request runs in.

Today there are zero such reads. That is a measurement, not a design intention,
and this module is what keeps it one. The acting Principal comes from
`bootstrap.gateway.local_principal` — derived from the durable local-operator
binding — reaches `application.authorize` as a `Principal`, and leaves it inside
an `Authorization`. Every use case reads
`authorization.principal.principal_id`. Nothing else is a source of identity.

Three claims:

1. **No production module reads a principal identity from a caller-supplied
   container.** Envelope metadata, request bodies, headers, query and path
   parameters, CLI namespaces, and MCP tool-argument mappings — in the
   attribute, the subscript, the `getattr`, and the accessor-method form
   (`.get`, `.pop`, `.__getitem__`, `operator.attrgetter`/`itemgetter`), under a
   literal key or one bound to a local string constant, and under the
   container's own name *or any local name this module bound from it*. Neither
   the alias clause nor the accessor clause is decoration. An independent review
   planted `context = request_metadata` followed by `context.principal_id`,
   `getattr(metadata, "principal_id")`, and `data = envelope.copy()` followed by
   `data["principal_id"]` in `application/service.py`, and every test in this
   module stayed green; a later review planted `_acting =
   payload.get("principal_id")` in `adapters/normalization.py`, one line below a
   legitimate `payload.get("representation")`, and the whole suite stayed green
   again. All of them are controls below now.
2. **Where a caller-supplied `principal_id` is read at all, it is read to be
   verified, and the sites are registered exactly.** Three modules compare a
   request's stated owner against the server-resolved one and refuse a
   mismatch; a fourth reads a continuity command's first field. A fifth site
   has to be argued about here.
3. **A continuity command is never built from caller input.**
   `OpenSituationCommand` and its six siblings take `principal_id` as their
   first field and are unwired: no transport constructs one. When one is wired,
   the `principal_id=` it is given must be an attribute chain ending in
   `.principal.principal_id` — the Principal the authorization already
   resolved — and this test fails if it is anything else, including
   `metadata.principal_id`.

Live Entra readiness is WP-05's; nothing here asserts anything about token
validation. It asserts only that whatever the composition root resolves is the
only thing the rest of the tree reads.

Nothing here opens a connection, reaches a source, or touches a database.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"

#: The field names that name a principal, in every vocabulary this tree uses.
PRINCIPAL_FIELDS: Final = frozenset({"principal_id", "capture_principal_id", "principalId"})

#: Every key that would constitute caller-supplied identity if it were pulled
#: out of a container a caller controls. The Entra pair joins the principal
#: names because `domain.identity.user_account.FORBIDDEN_IDENTITY_FIELDS` says
#: those three are the ones a payload must never carry, and `tid`/`oid` are what
#: a Principal is *resolved from* — a request that names them has named the
#: account the resolution would have reached.
IDENTITY_KEYS: Final = PRINCIPAL_FIELDS | frozenset({"tid", "oid"})

#: Methods that read one named key out of a container. `payload["principal_id"]`
#: and `payload.get("principal_id")` are the same read, and a detector that saw
#: only the syntax saw only half of them: `adapters/normalization.py` reaches its
#: whole request document through `.get`, so the accessor form is the *idiomatic*
#: way to write this defect in this tree, not an exotic one.
_ACCESSOR_METHODS: Final = frozenset({"get", "pop", "setdefault", "__getitem__"})

#: `operator`'s two getter factories, which turn a key into a callable and so
#: split one read across two statements: `read = itemgetter("principal_id")`
#: then `read(payload)`. Both halves are tracked, under `operator.attrgetter` and
#: under the bare name a direct import gives it.
_GETTER_FACTORIES: Final = frozenset({"attrgetter", "itemgetter"})

#: Containers a caller controls. A `principal_id` read off any of these — as an
#: attribute or as a mapping key — is identity taken from payload.
#:
#: `metadata` is the first entry and the reason the list exists:
#: `RequestMetadata.principal_id` is a validated, well-formed identifier that
#: arrives on every request, which is exactly what makes reading it look
#: harmless.
CALLER_SUPPLIED: Final = frozenset(
    {
        "metadata",
        "request_metadata",
        "envelope",
        "body",
        "payload",
        "headers",
        "header",
        "cookies",
        "query",
        "query_params",
        "path_params",
        "params",
        "form",
        "arguments",
        "tool_arguments",
        "argv",
        "namespace",
        "raw",
        "untrusted",
    }
)

#: The seven R5 continuity commands. Each carries `principal_id` as its first
#: field and none is reachable from a transport yet, which is why the third
#: claim below is currently a zero.
CONTINUITY_COMMANDS: Final = frozenset(
    {
        "OpenSituationCommand",
        "CloseSituationCommand",
        "EnterFrameCommand",
        "AddProjectCommand",
        "LinkSituationToProjectCommand",
        "RecordRelationshipEventCommand",
        "TraceObjectCommand",
    }
)

#: WP-27's six managed-document commands. The same shape and the same posture as
#: the seven above — `principal_id` first, no `Capability`, no transport — and
#: they are held to the same rule for a sharper reason: this family is the one
#: whose commands cause bytes to be written to a filesystem, so a construction
#: taking its Principal from a caller's payload would write a document into
#: someone else's partition.
MANAGED_DOCUMENT_COMMANDS: Final = frozenset(
    {
        "CreateManagedDocumentCommand",
        "ReviseManagedDocumentCommand",
        "ReadManagedDocumentCommand",
        "ListManagedDocumentsCommand",
        "ArchiveManagedDocumentCommand",
        "RestoreManagedDocumentCommand",
    }
)

#: Every command that carries a resolved Principal as a field rather than taking
#: it from an `Authorization`. Claim 3 is quantified over this union, so a
#: managed-document command wired from a caller's stated identity reddens exactly
#: as a continuity one does.
PRINCIPAL_BEARING_COMMANDS: Final = CONTINUITY_COMMANDS | MANAGED_DOCUMENT_COMMANDS

#: An expression is a derived principal when it ends in one of these chains.
#: `.principal.principal_id` is an `Authorization`'s or a policy request's;
#: `account.principal_id` is the identity plane's registered account.
DERIVED_CHAINS: Final = ("principal.principal_id", "account.principal_id")

#: Every production read of a caller-supplied `principal_id` argument, as
#: `module -> ((receiver, field), ...)` sorted with multiplicity.
#:
#: Each of these reads a value the caller *stated* — and none of them trusts it.
#: `capture.py`, `enrollment.py`, and `review.py` compare the stated owner
#: against the server-resolved Principal and refuse a mismatch as
#: `CallerSuppliedPrincipalError`; `relationships.py` does the same for the
#: deciding Principal of an identity review (WP-04). `situation_service.py`
#: reads a continuity command's first field, and that command is unwired —
#: claim 3 is what keeps it from being wired unsafely.
#:
#: The registry is exact. A sixth module reading a request's stated principal is
#: a decision that has to be written here, with what verifies it.
VERIFIED_CALLER_STATEMENTS: Final = {
    # The binding is an operator-created credential record and the identity is
    # the result of verifying that record, never a request body field.
    "application/apple_machine.py": (("binding", "principal_id"),),
    "bootstrap/apple_machine_control.py": (
        ("identity", "principal_id"),
        ("identity", "principal_id"),
        ("identity", "principal_id"),
    ),
    # The grant is NAS-issued and durably journaled; the receipt is NAS-issued
    # and compared back to that grant before any protected spool acknowledgement.
    "infrastructure/apple_transport_agent.py": (
        ("grant", "principal_id"),
        ("grant", "principal_id"),
        ("grant", "principal_id"),
        ("grant", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
    ),
    # In-memory evaluation pages are staged from operator-constructed work and
    # rasters. Lookup keys copy those objects' partitions so reads stay
    # principal-bound; the values are not request-body fields.
    "infrastructure/gsqs_b0_evaluation.py": (
        ("item", "principal_id"),
        ("raster", "principal_id"),
    ),
    # Remote grant staging compares the NAS-issued contract Principal with the
    # store's authenticated Principal partition before persisting any bounds.
    "infrastructure/persistence/native_sources.py": (("grant", "principal_id"),),
    # `WP-RI-A-02`'s governed entity writes. `EntityWriteRequest.principal_id`
    # is *not* a caller-stated owner despite the shape this scan matches: the
    # request is built inside `application.entity_authoring` from
    # `Authorization.principal.principal_id`, and the transport commands that
    # reach it — `CreateEntity`, `UpdateEntity` and the ten beside them — have
    # no `principal_id` field at all, so a payload naming one is refused by the
    # dataclass constructor before any of this runs. What these reads do is
    # carry the already-resolved partition into each statement, which is the
    # same shape `MemoryWriteRequest.principal_id` has and the reason
    # `persistence.relationship_memory` is registered below.
    "application/entity_authoring.py": (("request", "principal_id"),) * 2,
    "infrastructure/persistence/entity_authoring.py": (("request", "principal_id"),) * 13,
    "application/intelligence.py": (
        ("artifact", "principal_id"),
        ("artifact", "principal_id"),
        ("artifact", "principal_id"),
        ("cycle", "principal_id"),
        ("cycle", "principal_id"),
        ("receipt", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
    ),
    # The entity plane reads the `principal_id` carried on the domain record it
    # was handed, and reads it *in order to refuse a mismatch* against the
    # `principal_id` argument the application resolved: `create` scopes its
    # collision read and its insert by `entity.principal_id`, and
    # `bind_identifier`, `record_assignment` and `record_relationship` each
    # compare the record's own field against the acting Principal and raise
    # before writing when the two differ. The value is never trusted; it is
    # checked, which is what this registry is for.
    #
    # The eight `row` reads are the row mappers, and they appear here for the
    # reason `infrastructure/persistence/relationship_memory.py`'s two do: the
    # two joined resolution lookups select `entities` and one child table at
    # once, both tables declare `updated_at` and `version`, and a `Row` read by
    # attribute answers with the entity's column — so the child records were
    # hydrated with the entity's version and revision moment. The child columns
    # are labelled and read back through `_ChildRow`, which is not a `Row`, so
    # the two child mappers take `Any` and this module stops earning the `row`
    # spelling for free. Every one of the eight reads a `principal_id` off a row
    # a partition-scoped statement returned, and stamps it onto the record built
    # from that row; none of them is caller input, and none decides a partition.
    #
    # The nineteen `request` reads are WP-RI-A-03's directed write path, and the
    # value they read is the one thing on those requests a caller could not have
    # sent. `AssignmentWriteRequest` and `RelationshipWriteRequest` are built in
    # `application/entity_directed.py` from a transport command that has no
    # `principal_id` field at all -- so a payload naming one is refused by the
    # command constructor before that module runs -- and the field is filled from
    # `authorization.principal.principal_id`. Every read here is the partition
    # predicate of a statement or the stamp on a row it writes, which is the
    # server-resolved Principal reaching persistence by the only route it has.
    # WP-RI-A-04 adds three more of exactly the first kind -- `decision`,
    # `event` and `link` are the records handed to `record_resolution_decision`,
    # `record_mutation_event` and `record_fact_evidence_link`, and each read is
    # the same `if X.principal_id != principal_id: raise` those writes already
    # perform for an observation and a proposal -- and three more row mappers.
    # WP-RI-06 adds `effect`, `operation` and `preview` to the same family, and
    # three more `row` reads for the mappers that build those records back. Each
    # is the identity-correction plane's version of the rule above: the write
    # methods refuse a record whose `principal_id` is not the acting Principal's
    # before any statement runs, and the mappers read a column out of a statement
    # `_mine` already scoped.
    "infrastructure/persistence/entity.py": (
        ("alias", "principal_id"),
        ("assignment", "principal_id"),
        ("decision", "principal_id"),
        ("effect", "principal_id"),
        ("entity", "principal_id"),
        ("entity", "principal_id"),
        ("entity", "principal_id"),
        ("entity", "principal_id"),
        ("event", "principal_id"),
        ("identifier", "principal_id"),
        ("link", "principal_id"),
        ("observation", "principal_id"),
        ("operation", "principal_id"),
        ("operation", "principal_id"),
        ("preview", "principal_id"),
        ("proposal", "principal_id"),
        ("proposal", "principal_id"),
        ("record", "principal_id"),
        ("rel", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
    ),
    # WP-RI-06's merge service. `MergePreviewCommand` and `MergeCommand` are
    # internal dataclasses whose docstrings say the actor, the clock and the
    # authority are the server's, and neither has a transport-facing counterpart
    # carrying a `principal_id` field — so there is nothing a caller could have
    # supplied for these three reads to be confused with, exactly as for
    # `ObserveCommand` above. The fourth is the stored preview's own field, read
    # to recompute that preview's binding digest and refuse a row whose stored
    # binding disagrees with the digest beside it -- so it is read in order to
    # *check* it, which is the registry's own rule. `identity_preview` is
    # partition-scoped, so a preview held by anyone else was answered as absent
    # before this read happens at all.
    "application/identity_correction.py": (
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("preview", "principal_id"),
    ),
    # WP-RI-06's governance service carries the `principal_id` of the proposal
    # it just loaded onto the decided copy of that proposal. The value is not
    # caller input: `proposal(principal_id, ...)` is partition-scoped, so a
    # proposal held by anyone else was already answered as absent, and the read
    # is of a row this Principal owns. `decide_proposal` then refuses a mismatch
    # again at the write, which is where the registry's own rule wants it.
    #
    # WP-RI-A-04's seven `command.principal_id` reads are the same shape the
    # Relationship Memory service's are, and are safe for the same reason
    # rather than for a new one: `ObserveCommand` and `ResolveMentionCommand`
    # are internal dataclasses whose docstrings say "with the Principal already
    # resolved", and the transport-facing `ObserveEntityMention` and
    # `ResolveUnresolvedMention` carry no `principal_id` field at all -- so there
    # is nothing a caller could have supplied for these reads to be confused
    # with. The handler builds them from `authorization.principal.principal_id`,
    # and every repository call below stamps or refuses on the same value.
    "application/entity_governance.py": (
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("held", "principal_id"),
    ),
    # WP-29's Relationship Memory service. Its three commands are internal
    # dataclasses whose docstrings each say "with the Principal already
    # resolved", and the transport-facing commands the normalizer builds carry
    # no `principal_id` field at all — so there is nothing a caller could have
    # supplied for these three reads to be confused with. The service copies the
    # resolved value onto the `MemoryWriteRequest` it hands the repository, and
    # the fourth read is that request's own field, used to scope the replay
    # lookup so a foreign idempotency key answers as absent rather than
    # returning another Principal's receipt.
    "application/relationship_memory.py": (
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("request", "principal_id"),
    ),
    # The context card's own invariant, and it reads both values *in order to
    # refuse a mismatch*: a card memory pairs a stored memory with a stored
    # version of itself, and `__post_init__` raises when the two halves do not
    # belong to one Principal. Neither value is caller input — both come off
    # rows a partition-scoped read returned — and the check is the reason the
    # pairing cannot be assembled across partitions by a later caller.
    "domain/relationship/context_card.py": (
        ("current_version", "principal_id"),
        ("memory", "principal_id"),
    ),
    # WP-29's memory repository. The thirteen `request.principal_id` reads are
    # the resolved Principal the service put on the `MemoryWriteRequest`, and
    # every one of them is an argument to `_mine` or `_bound` — that is, it is
    # read in order to *constrain* a statement to that partition or to stamp a
    # row with it, never to trust it. The `row` and `link` reads are stored
    # column values being mapped back onto domain records, from statements that
    # were already scoped by those same calls.
    "infrastructure/persistence/relationship_memory.py": (
        ("link", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("row", "principal_id"),
        ("row", "principal_id"),
    ),
    # The same plane's review and promotion path. All nine reads are of the
    # `ReviewDecisionRequest.principal_id` the authenticated Review capability
    # resolved, and eight of them are arguments to `_mine`, `_bound` or the
    # subject re-validation those two scope — read to constrain a statement to
    # the partition or to stamp a row with it. The ninth echoes it back onto the
    # returned `ReviewDecision`, which is the same value the caller was already
    # authenticated as and carries no partition decision of its own.
    "infrastructure/persistence/relationship_memory_review.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
    ),
    "application/goodnotes.py": (
        ("page", "principal_id"),
        ("page", "principal_id"),
        ("plan", "principal_id"),
        ("plan", "principal_id"),
        ("plan", "principal_id"),
        ("plan", "principal_id"),
        ("plan", "principal_id"),
        ("plan", "principal_id"),
        ("plan", "principal_id"),
        ("prior", "principal_id"),
    ),
    # Lineage reconcile receives the authenticated Principal as an explicit
    # argument and rechecks every admitted SourcePage before writing identity.
    "application/goodnotes_lineage.py": (
        ("page", "principal_id"),
        ("request", "principal_id"),
    ),
    # Durable-note orchestration receives the same authenticated Principal as
    # an explicit DurableNoteRequest field, not a public Command or envelope
    # value, and threads it into lineage, occurrence, and preview stores.
    # Continuation identity/consistency checks re-read the stored run partition
    # and the request Principal before any FAILED→RUNNING mutation.
    "application/goodnotes_orchestrator.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
    ),
    "application/goodnotes_delivery.py": (("existing", "principal_id"),),
    # The dormant integrity metric groups already-persisted occurrence rows by
    # their stored partition. It does not read a request-body Principal.
    "application/goodnotes_evaluation.py": (("item", "principal_id"),),
    # Evaluation handles are minted from the authenticated local-operator
    # Principal passed into `evaluation_handle`. The raster copies that
    # partition. Neither value is a request-body field.
    "application/goodnotes_gsqs_b0_mcp.py": (("work", "principal_id"),),
    "infrastructure/persistence/goodnotes_delivery.py": (
        ("association", "principal_id"),
        ("association", "principal_id"),
        ("attempt", "principal_id"),
        ("attempt", "principal_id"),
        ("attempt", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
    ),
    # The runtime receives the authenticated local operator Principal from the
    # CLI and compares a stored retry receipt to that same admitted plan.
    "bootstrap/goodnotes.py": (("prior", "principal_id"),),
    # Evidence items carry the Principal they were packed for. Construction
    # compares each item against the package owner and refuses a cross-principal
    # mix; the value is not a request-body field.
    "domain/context/prepared.py": (("item", "principal_id"),),
    "domain/context/run.py": (("item", "principal_id"),),
    "domain/modeling/gate.py": (("item", "principal_id"),),
    # Persist copies the packed package's partition, already confined to
    # `authorization.principal`. Not a request-body field.
    "application/context/service.py": (
        ("item", "principal_id"),
        ("prepared", "principal_id"),
    ),
    "infrastructure/persistence/context_runs.py": (
        ("item", "principal_id"),
        ("run", "principal_id"),
    ),
    "infrastructure/persistence/context_preferences.py": (
        ("event", "principal_id"),
        ("event", "principal_id"),
        ("event", "principal_id"),
        ("event", "principal_id"),
    ),
    "infrastructure/goodnotes/fixture.py": (("page", "principal_id"),),
    # The admitted manifest's owner is untrusted source metadata. The source
    # receives the authenticated Principal from the application and selects only
    # exact matches; GoodNotesService rechecks every returned SourcePage before
    # deriving or storing an identity.
    "infrastructure/goodnotes/local.py": (
        ("entry", "principal_id"),
        ("entry", "principal_id"),
    ),
    "infrastructure/persistence/goodnotes.py": (
        ("change", "principal_id"),
        ("change", "principal_id"),
        ("change", "principal_id"),
        ("link", "principal_id"),
        ("link", "principal_id"),
        ("link", "principal_id"),
        ("note", "principal_id"),
        ("note", "principal_id"),
        ("note", "principal_id"),
        ("note", "principal_id"),
        ("notebook", "principal_id"),
        ("notebook", "principal_id"),
        ("notebook", "principal_id"),
        ("notebook", "principal_id"),
        ("observed", "principal_id"),
        ("observed", "principal_id"),
        ("observed", "principal_id"),
        ("occurrence", "principal_id"),
        ("occurrence", "principal_id"),
        ("occurrence", "principal_id"),
        ("occurrence", "principal_id"),
        ("occurrence", "principal_id"),
        ("occurrence", "principal_id"),
        ("page", "principal_id"),
        ("page", "principal_id"),
        ("page", "principal_id"),
        ("page", "principal_id"),
        ("page", "principal_id"),
        ("page", "principal_id"),
        ("page", "principal_id"),
        ("position", "principal_id"),
        ("position", "principal_id"),
        ("position", "principal_id"),
        ("raster", "principal_id"),
        ("raster", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("receipt", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("revision", "principal_id"),
        ("revision", "principal_id"),
        ("revision", "principal_id"),
        ("row", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("run", "principal_id"),
        ("snapshot", "principal_id"),
        ("snapshot", "principal_id"),
        ("snapshot", "principal_id"),
        ("snapshot", "principal_id"),
        ("stage", "principal_id"),
        ("stage", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
        ("values", "principal_id"),
    ),
    # The request Principal is produced by the authenticated Review capability;
    # every dispatch probe and the selected repository reapply the partition.
    # Two reads, one per probe: the canonical Review surface now routes three
    # subject kinds, and each router asks its own plane whether the case is
    # theirs *within this Principal's partition* — which is also what makes a
    # foreign case answer "no such case" rather than "not yours".
    "infrastructure/persistence/unit_of_work.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
    ),
    "application/situation_service.py": (
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
        ("cmd", "principal_id"),
    ),
    # WP-27's managed-document service reads each command's stated Principal and
    # hands it to a repository that derives its own `PrincipalContext` from it and
    # stamps every row with that. The persistence module then *verifies* the
    # request's copy against the resolved context and refuses a mismatch as
    # `CallerSuppliedPrincipalError`, exactly as `capture.py` does. The
    # `document` read is the backup manifest's own `principal_id`, compared
    # against the Principal being restored and refused when they differ — so a
    # backup cannot move a document between partitions by being restored.
    "application/managed_documents.py": (
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("command", "principal_id"),
        ("document", "principal_id"),
    ),
    "infrastructure/persistence/commitment_management.py": (
        ("commitment", "principal_id"),
        ("commitment", "principal_id"),
        ("entry", "principal_id"),
    ),
    # Bulk-operation records are internal domain objects loaded from this
    # Principal's repository partition. The two reads verify the record still
    # belongs to the acting Principal before update or confirmation.
    "infrastructure/persistence/task_management.py": (
        ("operation", "principal_id"),
        ("operation", "principal_id"),
    ),
    "infrastructure/persistence/capture.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
    ),
    "infrastructure/persistence/enrollment.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
    ),
    "infrastructure/persistence/managed_documents.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
    ),
    "infrastructure/persistence/review.py": (
        ("request", "principal_id"),
        ("request", "principal_id"),
        ("request", "principal_id"),
    ),
}

#: Receivers that are not caller-supplied at all, and the bindings that earn
#: each one its trust. Everything not named here and not in `CALLER_SUPPLIED` is
#: an internal object.
#:
#: **A name on this list is trusted for what it is bound from, not merely for
#: how it is spelled.** The mapping is what makes that substantially true. It is
#: a measurement of the binding routes this scan checks, not a proof that no
#: unchecked route exists — the routes below are the ones checked, and the
#: limits recorded at the end of this comment are the ones known to remain:
#:
#: * *Assignment.* `rebound_from_caller_input` withdraws any entry the module
#:   assigns from caller data, so `context = request_metadata` followed by
#:   `context.principal_id` is a read off a caller-supplied container and is
#:   reported as one.
#: * *Parameter.* `_receivers_bound_by_an_unearned_parameter` withdraws any
#:   entry a parameter binds without an annotation naming one of the types below.
#:   This was a live bypass: `def _x(context): return context.principal_id`,
#:   called with a request document, was invisible to *both* detectors, because
#:   `rebound_from_caller_input` reads assignment targets and a parameter is not
#:   one. The annotation raises the cost from one spelling to two — a parameter
#:   must now spell both a trusted name and a matching type name — and `mypy`
#:   rejects the mismatch wherever the incoming value is not `Any` and the type
#:   name is not rebound locally. It is *not* an impossibility proof: a value
#:   typed `Any` (which `Mapping[str, Any]` subscripts produce freely) satisfies
#:   any annotation, and a module-local `Principal = dict[str, str]` buys the
#:   trusted spelling outright. Both are mypy-clean and would pass here.
#: * *Comprehension.* `_local_bindings` reads comprehension targets, so the
#:   comprehension form of a caller-rooted read is caught like the `for` form.
#: * *Import or module-level definition.* Neither can be a caller's document:
#:   both are fixed before a request exists.
#:
#: Known unchecked routes, recorded rather than implied away: `except ... as`
#: and `match ... case` captures bind without passing through the rules above,
#: and an accessor bound to a local alias (`read = payload.get`) splits the read
#: across two statements that neither detector joins. None is exercised in this
#: tree; each is a way a future module could spell a read this scan would miss.
#:
#: Without this, the mapping would be a list of names an attacker may pick.
#: `context` is the clearest case, because "a PrincipalContext or an application
#: context" is exactly the kind of object a request document could be mistaken
#: for.
#:
#: `self` takes no type names because its binding is the call protocol's, not an
#: annotation's — and it is trusted *only* as the leading parameter of a method
#: defined in a class body. A module-level `def _x(self)` is spelling again.
_DERIVED_RECEIVERS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        # A dataclass validating its own field.
        "self": frozenset(),
        # The resolved Principal.
        "principal": frozenset({"Principal"}),
        # Carries the resolved Principal.
        "authorization": frozenset({"Authorization"}),
        # A PrincipalContext or an application context.
        "context": frozenset({"PrincipalContext", "NativeRequestContext", "ServerRequestContext"}),
        # The output of `require_principal_context`.
        "resolved": frozenset({"PrincipalContext"}),
        # A registered account on the identity plane or a native source.
        "account": frozenset({"UserAccount", "NativeSourceAccount"}),
        # A registered remote capture client (WP-10), read out of
        # `knowledge.capture_clients` by `persistence.capture_clients`. Its
        # `principal_id` is the binding an operator minted, so reading it is how
        # the composition root learns *which* Principal a credential acts for —
        # the opposite of trusting a caller, and the value a caller cannot state
        # at all on that plane. `RegisteredCaptureClient` is constructed in
        # exactly two places, both from a database row or from `issue_client_secret`'s
        # own output, and never from a request document.
        "client": frozenset({"RegisteredCaptureClient"}),
        # A domain audit event.
        "event": frozenset({"AuditEvent"}),
        # A task-management domain aggregate or mutation receipt, never a
        # request document: `application.tasks.TaskManagementService` and
        # `infrastructure.persistence.task_management` construct both only from
        # a prior read or from values the service itself derived.
        "task": frozenset({"Task"}),
        "entry": frozenset({"TaskHistoryEntry"}),
        # A database row.
        "row": frozenset({"Row"}),
        # A database row mapping. Deliberately not bare `Mapping`: a caller's
        # document is a `Mapping` too.
        "mapping": frozenset({"RowMapping", "OffsetMapping"}),
        # A table's column collection.
        "c": frozenset({"ColumnCollection", "ReadOnlyColumnCollection"}),
    }
)


def _modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _relative(path: Path) -> str:
    return str(path.relative_to(PACKAGE))


def _root_name(node: ast.expr) -> str | None:
    """The nearest named receiver of an attribute or subscript chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _root_name(node.func)
    if isinstance(node, ast.Subscript):
        return _root_name(node.value)
    return None


def _chain_names(node: ast.expr) -> frozenset[str]:
    """Every identifier appearing anywhere in one attribute/subscript/call chain.

    The whole chain rather than its nearest receiver, because a caller-supplied
    container reached through a call — `headers.get("x")["principal_id"]` — has
    `get` as its nearest name and `headers` as the thing that made it
    untrusted.
    """
    return frozenset(
        {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        | {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}
    )


def _bound_names(target: ast.expr) -> frozenset[str]:
    """The plain local names one assignment target binds.

    An attribute or subscript target binds nothing local — `self.x = metadata`
    rebinds a field, not a name a later expression could resolve to — so those
    return nothing rather than being mistaken for an alias.
    """
    if isinstance(target, ast.Name):
        return frozenset({target.id})
    if isinstance(target, ast.Tuple | ast.List):
        return frozenset().union(*(_bound_names(element) for element in target.elts)) or frozenset()
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return frozenset()


def _local_bindings(tree: ast.AST) -> tuple[tuple[str, ast.expr], ...]:
    """Every `name = <expression>` in `tree`, in all the forms that bind one."""
    bindings: list[tuple[str, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bindings.extend((name, node.value) for name in _bound_names(target))
        elif (
            isinstance(node, ast.AnnAssign | ast.AugAssign | ast.NamedExpr)
            and node.value is not None
        ):
            bindings.extend((name, node.value) for name in _bound_names(node.target))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            bindings.extend((name, node.context_expr) for name in _bound_names(node.optional_vars))
        elif isinstance(node, ast.For | ast.AsyncFor):
            bindings.extend((name, node.iter) for name in _bound_names(node.target))
        elif isinstance(node, ast.comprehension):
            # A comprehension target binds exactly as `for` does, and `ast.walk`
            # does not reach it through the `For` branch above because a
            # comprehension is its own node. Without this, the identical read is
            # caught as a statement and missed as a comprehension:
            # `[context.principal_id for context in payload["accounts"]]`. That
            # asymmetry is not hypothetical — `row` and `account` are bound by
            # comprehension dozens of times in this tree today.
            bindings.extend((name, node.iter) for name in _bound_names(node.target))
    return tuple(bindings)


def _chain_root(node: ast.expr) -> str | None:
    """The name an attribute/subscript/call chain is *rooted at*, or `None`.

    The deepest name rather than the nearest one, which is the opposite end of
    the chain from `_root_name`: `envelope.copy()` is rooted at `envelope`, and
    that is the fact that decides whether the result is caller data.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute | ast.Subscript):
        return _chain_root(node.value)
    if isinstance(node, ast.Call):
        return _chain_root(node.func)
    if isinstance(node, ast.Await | ast.Starred):
        return _chain_root(node.value)
    return None


def rebound_from_caller_input(tree: ast.AST) -> frozenset[str]:
    """Local names bound, directly or transitively, from a caller-supplied container.

    This is what makes `CALLER_SUPPLIED` a statement about objects rather than
    about spelling. `context = request_metadata` puts `context` here, and
    `data = envelope.copy()` puts `data` here, so neither the whitelist below nor
    a freshly invented neutral name launders the read that follows.

    Transitive and to a fixed point, because one rename is as good as two:
    `first = metadata`, `second = first`, `second.principal_id` is the same
    defect written across three lines.

    Propagation is by the **root of the assigned chain**, not by whether a
    caller-supplied name appears anywhere in the expression, and the difference
    is the whole of what keeps this from being useless. `authorization =
    self._authorize(..., metadata, ...)` mentions `metadata` and returns the
    resolved `Authorization` — treating that as caller data would report every
    correct use case in the tree and the guard would have to be turned off. A
    chain rooted at a caller-supplied name is a *reference into* the caller's
    document; a call that merely takes one is a derivation, and the second
    detector's exact registry is what covers a derivation whose result is then
    read as a principal.

    Public for the same reason `caller_supplied_reads` is: a control below runs
    it over trees that really do rebind, so the empty answer it gives for
    production is a measurement.
    """
    bindings = _local_bindings(tree)
    rebound: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, value in bindings:
            if name in rebound or name in CALLER_SUPPLIED:
                continue
            if _chain_root(value) in (CALLER_SUPPLIED | rebound):
                rebound.add(name)
                changed = True
    return frozenset(rebound)


def string_constants(tree: ast.AST) -> Mapping[str, frozenset[str]]:
    """Every local name bound, directly or transitively, to a string literal.

    A key is as reboundable as a container, and one indirection was enough:
    `key = "principal_id"` followed by `payload.get(key)` reads exactly what
    `payload.get("principal_id")` reads. Resolved off `_local_bindings`, so it is
    the same notion of "a name this module bound" the alias rule uses, and to a
    fixed point for the same reason.

    A name is mapped to the *set* of literals it is ever bound to rather than to
    one, so a name assigned twice is forbidden if either assignment forbids it.
    That is the fail-closed direction: a detector that took the last write would
    be turned off by adding a later one.
    """
    bindings = _local_bindings(tree)
    constants: dict[str, set[str]] = {}
    changed = True
    while changed:
        changed = False
        for name, value in bindings:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literals = {value.value}
            elif isinstance(value, ast.Name):
                literals = set(constants.get(value.id, ()))
            else:
                continue
            known = constants.setdefault(name, set())
            if not literals <= known:
                known |= literals
                changed = True
    return {name: frozenset(literals) for name, literals in constants.items()}


def _literal_key(
    node: ast.expr, constants: Mapping[str, frozenset[str]], keys: frozenset[str]
) -> str | None:
    """The forbidden key an expression names, written out or bound to a local.

    Only a literal or a name this module bound to one. A genuinely computed name
    stays out, which is what keeps `getattr(parsed, field)` in the CLI adapter —
    a loop over that adapter's own option names — from being reported as
    identity.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if node.value in keys else None
    if isinstance(node, ast.Name):
        named = constants.get(node.id, frozenset()) & keys
        return min(named) if named else None
    return None


def _getter_key(
    node: ast.expr, constants: Mapping[str, frozenset[str]], keys: frozenset[str]
) -> str | None:
    """The forbidden key an `attrgetter`/`itemgetter` construction would read."""
    if not isinstance(node, ast.Call) or not node.args:
        return None
    if isinstance(node.func, ast.Name):
        factory = node.func.id
    elif isinstance(node.func, ast.Attribute):
        factory = node.func.attr
    else:
        return None
    if factory not in _GETTER_FACTORIES:
        return None
    return _literal_key(node.args[0], constants, keys)


def identity_getters(
    tree: ast.AST, constants: Mapping[str, frozenset[str]], keys: frozenset[str]
) -> Mapping[str, str]:
    """Local names bound to an `attrgetter`/`itemgetter` over a forbidden key.

    The second half of the split form. `read = operator.itemgetter("oid")` names
    no container, so it is not a read yet; `read(payload)` is, and this is what
    lets the call site know what `read` was built to pull out.
    """
    return {
        name: key
        for name, value in _local_bindings(tree)
        if (key := _getter_key(value, constants, keys)) is not None
    }


def _identity_call_read(
    node: ast.Call,
    keys: frozenset[str],
    constants: Mapping[str, frozenset[str]],
    getters: Mapping[str, str],
) -> tuple[ast.expr, str] | None:
    """The container and key of an identity read written as a call."""
    if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
        key = _literal_key(node.args[1], constants, keys)
        if key is not None:
            return node.args[0], key
    if isinstance(node.func, ast.Attribute) and node.func.attr in _ACCESSOR_METHODS and node.args:
        key = _literal_key(node.args[0], constants, keys)
        if key is not None:
            return node.func.value, key
    if node.args:
        applied = _getter_key(node.func, constants, keys)
        if applied is None and isinstance(node.func, ast.Name):
            applied = getters.get(node.func.id)
        if applied is not None:
            return node.args[0], applied
    return None


def identity_read(
    node: ast.AST,
    keys: frozenset[str],
    constants: Mapping[str, frozenset[str]] | None = None,
    getters: Mapping[str, str] | None = None,
) -> tuple[ast.expr, str] | None:
    """The container and key of one identity read, in each of the forms it has.

    `x.principal_id`, `x["principal_id"]`, `getattr(x, "principal_id")`,
    `x.get("principal_id")`, `x.pop("principal_id")`,
    `x.__getitem__("principal_id")`, and `operator.itemgetter("principal_id")(x)`
    are one defect written seven ways, and each widening here closed a detector
    some rewrite had got past. The accessor family was the largest hole and the
    least exotic one: `adapters/normalization.py` reads its whole request
    document through `.get`, so `payload.get("principal_id")` is how this defect
    would actually be written in this tree, and it was invisible.

    `constants` extends every key position to a name this module bound to a
    string literal, so `k = "principal_id"` before `payload.get(k)` is the same
    read; `getters` extends the call form to an `operator` getter bound to a
    local name. Both default to empty, which is this function's behaviour over a
    single expression with nothing around it.

    `getattr` with a *computed* name is still not here, on purpose:
    `getattr(parsed, field)` in the CLI adapter iterates a list of option names,
    and reporting it would say nothing about identity. A name bound to a literal
    is not computed, which is why `constants` does not disturb that exemption.
    """
    constants = {} if constants is None else constants
    getters = {} if getters is None else getters
    if isinstance(node, ast.Attribute) and node.attr in keys:
        return node.value, node.attr
    if isinstance(node, ast.Subscript):
        key = _literal_key(node.slice, constants, keys)
        if key is not None:
            return node.value, key
    if isinstance(node, ast.Call):
        return _identity_call_read(node, keys, constants, getters)
    return None


def caller_supplied_reads(tree: ast.AST) -> tuple[tuple[int, str], ...]:
    """Every identity read off a caller-supplied container in `tree`.

    Public, because this module's own control runs it over a synthetic tree that
    really does contain one. A detector that found nothing would otherwise agree
    with the production zero for the wrong reason.

    Four axes, each of which was a way past some version of this function: the
    *key* is any of `IDENTITY_KEYS` rather than the principal names alone and may
    be written out or bound to a local string, the *form* is attribute,
    subscript, `getattr`, or the accessor-method family, and the *container* is
    anything `CALLER_SUPPLIED` names **or anything this module bound from one**.
    """
    untrusted = CALLER_SUPPLIED | rebound_from_caller_input(tree)
    constants = string_constants(tree)
    getters = identity_getters(tree, constants, IDENTITY_KEYS)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        read = identity_read(node, IDENTITY_KEYS, constants, getters)
        if read is None:
            continue
        container, _ = read
        if _chain_names(container) & untrusted:
            found.append((node.lineno, ast.unparse(node)))  # type: ignore[attr-defined]
    return tuple(sorted(found))


def _annotation_names(annotation: ast.expr | None) -> frozenset[str]:
    """The type names an annotation asserts, with unions flattened.

    A subscript contributes its *head* and not its arguments, because `Row[Any]`
    is a `Row` however it is parameterised, while `Mapping[str, Any]` must not
    borrow trust from whatever it is parameterised by. `None` in a union
    contributes nothing, so `PrincipalContext | None` asserts exactly
    `PrincipalContext`. A string annotation is parsed, so a forward reference is
    not a way out.
    """
    if annotation is None:
        return frozenset()
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return frozenset()
    if isinstance(annotation, ast.Name):
        return frozenset({annotation.id})
    if isinstance(annotation, ast.Attribute):
        return frozenset({annotation.attr})
    if isinstance(annotation, ast.Subscript):
        return _annotation_names(annotation.value)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _annotation_names(annotation.left) | _annotation_names(annotation.right)
    return frozenset()


def _method_bodies(tree: ast.AST) -> frozenset[int]:
    """The `id()` of every function defined directly in a class body."""
    return frozenset(
        id(item)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
    )


def receivers_bound_by_an_unearned_parameter(tree: ast.AST) -> frozenset[str]:
    """Derived-receiver names that some parameter in `tree` binds without earning it.

    The other half of "trusted for what it is bound from". `rebound_from_caller_input`
    inspects assignment targets, and a parameter is not one, so before this
    existed a helper only had to *spell* its parameter with one of the ten
    trusted names to take a request document and read a principal out of it —
    `def _x(context): return context.principal_id`, called with caller data, was
    invisible to both detectors.

    A parameter earns the trust by declaring one of the types
    `_DERIVED_RECEIVERS` lists for its name. That raises the cost from one
    spelling to two and is checked by `mypy` over the whole tree wherever the
    incoming value is not `Any` and the type name is not rebound locally. It is
    not an impossibility proof: `Any` satisfies any annotation, and a
    module-local alias of a trusted type name buys the spelling outright. The
    module comment records both. `self` earns it differently — as the leading parameter of a method
    defined in a class body, where the call protocol does the binding — and a
    module-level `def _x(self)` earns nothing.

    Withdrawal is module-wide, not per-function, because every other rule here is
    module-wide too. If one function in a module binds `context` without earning
    it, `context` stops being a derived receiver for that whole module and its
    principal reads land in the exact registry, where a human has to say what
    verifies them. That is the fail-closed direction.

    Public because a control below runs it over trees that really do bind an
    unearned parameter, so the empty answer it gives for production is a
    measurement rather than an assumption.
    """
    methods = _method_bodies(tree)
    withdrawn: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        positional = [*node.args.posonlyargs, *node.args.args]
        optional = (node.args.vararg, node.args.kwarg)
        every = [*positional, *node.args.kwonlyargs, *(a for a in optional if a is not None)]
        for argument in every:
            accepted = _DERIVED_RECEIVERS.get(argument.arg)
            if accepted is None:
                continue
            if argument.arg == "self":
                if not (id(node) in methods and positional and positional[0] is argument):
                    withdrawn.add("self")
                continue
            declared = _annotation_names(argument.annotation)
            if not declared or not declared <= accepted:
                withdrawn.add(argument.arg)
    return frozenset(withdrawn)


def _stated_principal_reads(tree: ast.AST) -> tuple[tuple[str, str], ...]:
    """Every `principal_id` read off a receiver that is neither derived nor a table.

    The backstop behind claim 1: whatever `caller_supplied_reads` does not
    classify as caller data still has to be a receiver someone registered. It
    reads the same forms, so neither a subscript nor a `.get` is a blind spot
    here either, and it withdraws `_DERIVED_RECEIVERS` membership from every name
    the module binds without earning it — assigned from a request document
    (`rebound_from_caller_input`) or taken as a parameter that declares no
    derived type (`receivers_bound_by_an_unearned_parameter`). A whitelisted name
    is a derived receiver because of where its value came from, never because of
    what it is called.
    """
    unearned = rebound_from_caller_input(tree) | receivers_bound_by_an_unearned_parameter(tree)
    derived = frozenset(_DERIVED_RECEIVERS) - unearned
    constants = string_constants(tree)
    getters = identity_getters(tree, constants, PRINCIPAL_FIELDS)
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        read = identity_read(node, PRINCIPAL_FIELDS, constants, getters)
        if read is None:
            continue
        container, field = read
        receiver = _root_name(container)
        if receiver is None or receiver in derived:
            continue
        found.append((receiver, field))
    return tuple(sorted(found))


def continuity_constructions(tree: ast.AST) -> tuple[tuple[int, str, str], ...]:
    """Every construction of a continuity command, with the `principal_id=` it names."""
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in PRINCIPAL_BEARING_COMMANDS:
            continue
        named = next(
            (kw.value for kw in node.keywords if kw.arg == "principal_id"),
            None,
        )
        rendered = "<positional or absent>" if named is None else ast.unparse(named)
        found.append((node.lineno, node.func.id, rendered))
    return tuple(found)


def _is_derived(expression: str) -> bool:
    return any(expression.endswith(chain) for chain in DERIVED_CHAINS)


def test_the_scan_reaches_the_source_tree() -> None:
    """Guards every zero below against being a walk that parsed nothing."""
    modules = _modules()
    assert len(modules) >= 100
    read_principals = [
        path for path in modules if _stated_principal_reads(ast.parse(path.read_text("utf-8")))
    ]
    assert read_principals, "no module reads a principal at all; the detector is broken"


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_no_module_reads_a_principal_from_caller_supplied_input(path: Path) -> None:
    """Claim 1: envelope, body, headers, query, path, CLI, and MCP arguments."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    reads = caller_supplied_reads(tree)
    assert reads == (), (
        f"{_relative(path)} reads a principal identity from caller-supplied "
        f"input at {[f'line {line}: {text}' for line, text in reads]}. "
        "`RequestMetadata.principal_id` and its CLI and MCP equivalents are "
        "correlation input; the acting Principal is what the composition root "
        "resolved and nothing else (MU-AC-02, specs section 8.2)"
    )


def test_the_caller_supplied_detector_reports_a_read_that_really_is_one() -> None:
    """The control for claim 1. Each shape is a different bug, not a restatement.

    The last three were each a **reachable bypass** of the first version of this
    guard: all three were planted in `application/service.py` and the whole
    module stayed green. They are kept here in the exact form that got through,
    because the value of a control is that it fails on what the thing it controls
    used to miss.
    """
    bypasses = (
        "principal = metadata.principal_id",
        "principal = request.metadata.principal_id",
        "principal = body['principal_id']",
        "principal = headers.get('x')['principal_id']",
        "principal = arguments['principal_id']",
        "principal = namespace.principal_id",
        # Aliasing onto a whitelisted receiver name. `context` is trusted for
        # being a `PrincipalContext`, and an application context is exactly what
        # a request document could be mistaken for.
        "context = request_metadata\nprincipal = context.principal_id",
        # The same read, through the builtin rather than the syntax.
        "principal = getattr(metadata, 'principal_id')",
        # Subscript off a neutral name. There was no backstop at all for this
        # one: the detector walked `ast.Attribute` and never `ast.Subscript`
        # through a rebound name.
        "data = envelope.copy()\nprincipal = data['principal_id']",
        # Two renames are one rename twice.
        "first = metadata\nsecond = first\nprincipal = second.principal_id",
        # The Entra pair is identity too: a payload that names `tid`/`oid` has
        # named the account the resolution would have reached.
        "claims = payload['claims']\ntenant = claims['tid']",
        # The accessor family. The first of these is the exact probe an
        # independent review planted one line below `payload.get("representation")`
        # in `adapters/normalization.py`; the entire architecture suite stayed
        # green, because the detector walked `ast.Subscript` and never the `.get`
        # that this tree actually reads its request documents with.
        "_acting = payload.get('principal_id')",
        "_acting = arguments.get('principal_id', None)",
        "_acting = payload.pop('principal_id')",
        "_acting = payload.setdefault('oid', '')",
        "_acting = payload.__getitem__('principal_id')",
        # A key is as reboundable as a container.
        "key = 'principal_id'\n_acting = payload.get(key)",
        "key = 'tid'\n_acting = envelope[key]",
        # `operator` splits one read across two statements, applied inline or
        # bound to a name first, under the module and under a direct import.
        "import operator\n_acting = operator.attrgetter('principal_id')(metadata)",
        "import operator\n_acting = operator.itemgetter('principal_id')(payload)",
        "from operator import itemgetter\n_acting = itemgetter('oid')(payload)",
        "from operator import attrgetter\n"
        "read = attrgetter('principal_id')\n"
        "_acting = read(request_metadata)",
        # The accessor form reaches through the alias rule like every other form.
        "data = envelope.copy()\n_acting = data.get('principal_id')",
    )
    for source in bypasses:
        assert caller_supplied_reads(ast.parse(source)) != (), (
            f"the detector missed {source!r}, so the zero it reports over the "
            "source tree means nothing"
        )

    # And it does not report a derived read, or every module would fail.
    for allowed in (
        "principal = authorization.principal.principal_id",
        "principal = resolved.principal_id",
        "principal = row.principal_id",
        # `D-55` again, and the reason the alias rule propagates by the *root*
        # of the assigned chain rather than by any mention: a use case binds its
        # `Authorization` from a call that takes the request document, and that
        # is the correct shape. A rule that reported this would report every
        # handler in the tree, and a guard that fires on everything is a guard
        # somebody switches off.
        "authorization = self._authorize(metadata, command)\n"
        "principal = authorization.principal.principal_id",
        # A computed attribute name says nothing about identity: the CLI adapter
        # iterates its own option names through `getattr(parsed, field)`.
        "for field in fields:\n    supplied = getattr(parsed, field)",
        # The accessor widening is about the *key*, not about `.get`. These two
        # are the real lines at `adapters/normalization.py:170` and `:393` — the
        # module reads its whole request document this way — and a rule that
        # reported them would have to be turned off, which is the only outcome
        # worse than the hole it closed.
        "named = payload.get('representation')",
        "payload = arguments.get(PAYLOAD_KEY, {})",
        "kind = payload.get('kind')\nvalues = arguments.pop('values', ())",
        # A computed key stays out of the accessor form too, for the same reason
        # it stays out of `getattr`: it names no identity.
        "for field in fields:\n    supplied = payload.get(field)",
        # An `operator` getter over something that is not identity is not a read.
        "import operator\nname = operator.itemgetter('representation')(payload)",
    ):
        assert caller_supplied_reads(ast.parse(allowed)) == (), (
            f"the detector reported {allowed!r}, which is a derived read; a "
            "control that failed on every input would distinguish nothing"
        )


def test_the_alias_rule_withdraws_a_whitelisted_name_that_was_rebound() -> None:
    """`_DERIVED_RECEIVERS` is trusted for what a name is bound from, not its spelling.

    The claim-2 backstop is the other half of the alias fix. If `context` stayed
    whitelisted after being assigned a request document, a rebound read would be
    invisible to *both* detectors rather than one, and the exact registry below
    would go on agreeing with a tree that had a hole in it.
    """
    rebound = ast.parse("context = request_metadata\nprincipal = context.principal_id")
    # `principal` is rebound too, and that is the rule working rather than
    # leaking: a name bound from a rebound one carries the same taint, so
    # `principal` stops being a derived receiver in this tree as well.
    assert rebound_from_caller_input(rebound) == frozenset({"context", "principal"})
    assert _stated_principal_reads(rebound) == (("context", "principal_id"),)

    # The control at the other end: an untouched `context` stays derived, or
    # every module that carries a `PrincipalContext` would land in the registry.
    intact = ast.parse(
        "context = capture_context(principal.principal_id)\nx = context.principal_id"
    )
    assert rebound_from_caller_input(intact) == frozenset()
    assert _stated_principal_reads(intact) == ()

    # And the subscript and `getattr` forms reach the backstop too, so the
    # registry is exact over all three ways of writing the same read.
    assert _stated_principal_reads(ast.parse("x = found['principal_id']")) == (
        ("found", "principal_id"),
    )
    assert _stated_principal_reads(ast.parse("x = getattr(found, 'principal_id')")) == (
        ("found", "principal_id"),
    )
    assert _stated_principal_reads(ast.parse("x = found.get('principal_id')")) == (
        ("found", "principal_id"),
    )


def test_a_parameter_does_not_earn_a_derived_receiver_name_by_spelling_it() -> None:
    """The other half of claim 2's backstop, and a bypass of both detectors until now.

    `rebound_from_caller_input` reads assignment targets, and a parameter is not
    one, so a helper used to be able to take a request document and read a
    principal out of it by *spelling* its parameter with one of the ten trusted
    names. Every line below survived the whole module before this control
    existed. The registry is only exact if a name earns its trust from what binds
    it.
    """
    for unearned in (
        "def _x(context):\n    return context.principal_id",
        "def _x(resolved):\n    return resolved.principal_id",
        "def _x(row):\n    return row.principal_id",
        "def _x(authorization):\n    return authorization.principal_id",
        "def _x(principal):\n    return principal.principal_id",
        # An annotation that is not one of the types the name claims earns
        # nothing, which is the case that matters: a request document is a
        # `Mapping` and would otherwise take `mapping`'s trust by declaring it.
        "def _x(mapping: dict[str, str]):\n    return mapping['principal_id']",
        "def _x(context: Mapping[str, object]):\n    return context.get('principal_id')",
        # `self` is bound by the call protocol, so a module-level function only
        # spells it.
        "def _x(self):\n    return self.principal_id",
        # A keyword-only, starred, or lambda parameter binds a name too.
        "def _x(*, account):\n    return account.principal_id",
        "def _x(**event):\n    return event['principal_id']",
        "_x = lambda row: row.principal_id",
    ):
        assert _stated_principal_reads(ast.parse(unearned)) != (), (
            f"{unearned!r} reads a principal off a parameter that earned nothing "
            "but its spelling, and neither detector reported it"
        )

    # And the control at the other end, or every correct helper in the tree would
    # land in the registry and the registry would stop meaning anything. Each of
    # these is a shape production actually uses.
    for earned in (
        "def _x(principal: Principal):\n    return principal.principal_id",
        "def _x(authorization: Authorization):\n    return authorization.principal.principal_id",
        "def _x(context: PrincipalContext | None):\n    return context.principal_id",
        "def _x(context: 'PrincipalContext'):\n    return context.principal_id",
        "def _x(row: Row[tuple[object, ...]]):\n    return row.principal_id",
        "def _x(account: UserAccount):\n    return account.principal_id",
        "def _x(event: AuditEvent):\n    return event.principal_id",
        "class C:\n    def _x(self):\n        return self.principal_id",
    ):
        assert _stated_principal_reads(ast.parse(earned)) == (), (
            f"{earned!r} declares a derived type and was reported anyway; a "
            "backstop that fired on every helper would distinguish nothing"
        )

    # The withdrawal itself, named rather than inferred from the reads above.
    assert receivers_bound_by_an_unearned_parameter(
        ast.parse("def _x(context, row: Row[int], mapping: dict[str, str]):\n    return 0")
    ) == frozenset({"context", "mapping"})
    assert (
        receivers_bound_by_an_unearned_parameter(
            ast.parse("class C:\n    def _x(self, principal: Principal):\n        return 0")
        )
        == frozenset()
    )


def test_the_identity_keys_are_the_ones_the_domain_forbids_in_a_payload() -> None:
    """`tid` and `oid` are in `IDENTITY_KEYS` because the domain says they are.

    Bound to `domain.identity.user_account.FORBIDDEN_IDENTITY_FIELDS` rather than
    restated, so a fourth forbidden key added there cannot leave this scan
    checking three.
    """
    from my_pa.domain.identity.user_account import FORBIDDEN_IDENTITY_FIELDS

    assert FORBIDDEN_IDENTITY_FIELDS <= IDENTITY_KEYS, (
        f"{sorted(FORBIDDEN_IDENTITY_FIELDS - IDENTITY_KEYS)} are forbidden in a "
        "payload by the domain and are not scanned for here"
    )


def test_reads_of_a_caller_stated_principal_match_their_registry_exactly() -> None:
    """Claim 2: a stated owner may be verified; the sites are counted."""
    measured = {
        _relative(path): reads
        for path in _modules()
        if (reads := _stated_principal_reads(ast.parse(path.read_text("utf-8"))))
    }
    assert measured == VERIFIED_CALLER_STATEMENTS, (
        "the production reads of a caller-stated `principal_id` no longer match "
        "their registry. Each registered site reads the value in order to refuse "
        "a mismatch against the server-resolved Principal; a new one has to say "
        "here what verifies it, or stop reading it"
    )


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_a_continuity_command_is_never_built_from_caller_input(path: Path) -> None:
    """Claim 3: wiring the unwired family unsafely fails here.

    Zero constructions exist today, so this passes vacuously per module — which
    is precisely why the detector is exercised against real trees below rather
    than trusted.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for lineno, command, principal in continuity_constructions(tree):
        assert _is_derived(principal), (
            f"{_relative(path)}:{lineno} builds {command} with "
            f"principal_id={principal}. A continuity command's first field is the "
            "acting Principal; it comes from the authorization that already "
            f"resolved one — an attribute chain ending in {DERIVED_CHAINS} — and "
            "never from the request"
        )


def test_the_continuity_detector_accepts_a_derived_principal_and_refuses_a_stated_one() -> None:
    """The control for claim 3, at both ends.

    `D-55`: a control that failed on every input would distinguish nothing, so
    the safe wiring has to pass the same detector the unsafe wiring fails.
    """
    unsafe = ast.parse(
        "OpenSituationCommand(principal_id=metadata.principal_id, title='t', kind='k')"
    )
    found = continuity_constructions(unsafe)
    assert len(found) == 1
    assert not _is_derived(found[0][2])

    safe = ast.parse(
        "OpenSituationCommand("
        "principal_id=authorization.principal.principal_id, title='t', kind='k')"
    )
    found = continuity_constructions(safe)
    assert len(found) == 1
    assert _is_derived(found[0][2])

    # A positional principal is refused too: it names the field without naming
    # where the value came from, and this detector cannot see through that.
    positional = ast.parse("CloseSituationCommand(caller_id, 'sit_1', 'done')")
    assert continuity_constructions(positional) == (
        (1, "CloseSituationCommand", "<positional or absent>"),
    )
    assert not _is_derived("<positional or absent>")

    # The thirteen names are the whole family, so a command added to
    # `application/commands.py` without being added here is not silently exempt.
    from my_pa.application import commands

    # `Command` itself is the union alias every capability's command belongs to,
    # not a member of the family.
    declared = {
        name
        for name in vars(commands)
        if name.endswith("Command") and not name.startswith("_") and name != "Command"
    }
    assert declared == PRINCIPAL_BEARING_COMMANDS, (
        f"the principal-bearing command family is now {sorted(declared)}; this "
        "guard covers "
        f"{sorted(PRINCIPAL_BEARING_COMMANDS)}"
    )
