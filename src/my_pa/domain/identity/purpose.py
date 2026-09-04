"""Declared purposes.

Purposes are explicit and narrow. A principal may not silently escalate one
purpose into another (`docs/specs`, section 4).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Purpose"]


class Purpose(StrEnum):
    """Purposes a request may declare."""

    SOURCE_INSPECTION = "source_inspection"
    BOUNDED_ENROLLMENT = "bounded_enrollment"
    CONTENT_EXTRACTION = "content_extraction"
    KNOWLEDGE_SEARCH = "knowledge_search"
    KNOWLEDGE_READ = "knowledge_read"
    STATUS_OBSERVATION = "status_observation"
    SECURITY_VALIDATION = "security_validation"
    # Two purposes for the capture plane rather than a reuse of the knowledge
    # ones. The knowledge plane is the *extraction* plane, and a purpose that
    # admitted both would let a `knowledge.read` request return raw
    # user-authored capture text — the silent escalation this module exists to
    # refuse. Authoring and review are separated for the same reason the map
    # is near one-to-one with the capability set: a purpose
    # wide enough to cover writing and reading is a purpose that grants both.
    CAPTURE_AUTHORING = "capture_authoring"
    CAPTURE_REVIEW = "capture_review"
    # `review_disposition` is the tenth, and revision `3c8f1e2a5b74` already
    # carries the forward `ALTER` that admits it. It is a purpose of its own
    # rather than a reuse of `capture_review` — the opposite answer `D-91`
    # reached for `capture.search`, from the same test. That test asks whether
    # reuse would widen the grant: searching captures reads rows `capture.read`
    # already returns, so reuse widened nothing, while deciding a review
    # *promotes a proposal to a canonical assertion*, so a grant issued for
    # reading captures would also authorize promotion — exactly the silent
    # escalation this module exists to refuse. It is declared with the
    # `review.decide` capability it serves, because a purpose no capability
    # permits is denied for everything and reads as a mistake rather than as a
    # decision.
    REVIEW_DISPOSITION = "review_disposition"
    # The managed-document plane's pair (WP-28), and revision `6b3d9a2f8c14`
    # already carries the forward `ALTER` that admits both. They are purposes of
    # their own rather than reuses of the capture or knowledge pair, and
    # `domain/identity/operation.py` argues it beside the mapping: managed
    # documents are a third custody plane over their own tables, so admitting a
    # managed write under `capture_authoring` would let a grant issued for
    # ADR-003's append-only records write bytes into the managed root, and
    # admitting a managed read under `knowledge_read` would let a grant issued
    # over the extraction plane return a document body. Two rather than one for
    # the reason the capture pair is two: a purpose wide enough to cover writing
    # and reading is a purpose that grants both.
    DOCUMENT_AUTHORING = "document_authoring"
    DOCUMENT_READ = "document_read"
    # User-directed continuity writes. A purpose of its own rather than a reuse
    # of `capture_authoring` or `review_disposition`: those write ADR-003 notes
    # and promote capture proposals. Admitting a Project write under either
    # would let a grant issued to store a note or decide a review also create
    # durable work context. One purpose for the three create capabilities,
    # because they are the same authority class — explicit Principal authoring
    # of the acting Principal's own continuity — and a further split would map
    # one-to-one and cost three frozen-constraint literals for a distinction
    # nobody in this build can enforce.
    CONTINUITY_AUTHORING = "continuity_authoring"
    # The task plane's read purpose (WP-TM-03). A single purpose covers all
    # four `tasks.*` capabilities rather than the authoring/reading pair the
    # capture and managed-document planes each carry, because WP-TM-03 admits
    # no write capability for tasks to pair it against — task mutation
    # (WP-TM-02's `TaskManagementService`) is not yet reachable through
    # `ApplicationService.invoke`, so there is no `task_authoring` purpose for
    # `task_read` to be kept narrower than. It is declared as its own purpose
    # rather than a reuse of `capture_review` or `document_read`: a task is
    # neither a captured proposal awaiting promotion nor a byte-bearing
    # managed document, and a grant issued to read the review queue or a
    # document body has no occasion to also return a principal's task list,
    # history, or search results. When task mutation is exposed to the
    # assistant surface, the write purpose it is given should be a purpose of
    # its own for the same reason the capture and document pairs are two:
    # a purpose wide enough to cover writing and reading is a purpose that
    # grants both.
    TASK_READ = "task_read"
    # The task plane's write purpose (WP-TM-04). Separated from `task_read` for
    # the same reason the capture and managed-document planes each have two
    # purposes: a purpose wide enough to cover writing and reading is a purpose
    # that grants both, and a grant issued to read a task list should not also
    # authorize creating, updating, or transitioning tasks. This purpose covers
    # all five task mutation capabilities (`tasks.create`, `tasks.update`,
    # `tasks.transition`, `tasks.bulk_preview`, `tasks.bulk_confirm`) because
    # they are all writes to the same task partition under the same principal,
    # and a grant issued to create a task has no reason to be narrower than one
    # issued to update or transition it — the principal owns all of them.
    TASK_AUTHORING = "task_authoring"
    # The Commitment plane's purpose pair (WP-TM-05), separated from each
    # other for the identical reason `task_read`/`task_authoring` and the
    # capture/managed-document pairs are each two: a purpose wide enough to
    # cover writing and reading is a purpose that grants both, and a grant
    # issued to read a Principal's Commitments and derived Waiting-On view
    # should not also authorize creating or closing one. Declared as their
    # own purposes rather than a reuse of `task_read`/`task_authoring`: a
    # Commitment is a distinct canonical object from a Task (a social
    # obligation with a counterparty and a direction, not a work item), and a
    # grant issued over the task plane has no occasion to also reach the
    # commitment plane. `COMMITMENT_READ` covers the two reads
    # (`commitments.read`, `commitments.list`) and the derived
    # `commitments.waiting_on` query alike, because `waiting_on` reads no row
    # `commitments.list` and `tasks.list` do not already return to the same
    # Principal — it is an assembled view, not a new store, so it carries no
    # wider authority than the two reads it is assembled from.
    COMMITMENT_READ = "commitment_read"
    COMMITMENT_AUTHORING = "commitment_authoring"
    # Context preparation is a purpose of its own rather than a reuse of
    # `knowledge_search`. `D-91`'s test: would reuse widen the grant? Yes.
    # `knowledge_search` is scoped by one enrollment on the extraction plane.
    # `context.prepare` assembles evidence that will, from WP-KC-02, cross
    # capture and continuity — planes a grant issued to search extracted text
    # does not reach. Admitting that assembly under `knowledge_search` would let
    # a request issued to search one enrollment also pack user-authored notes
    # and accepted continuity, which is the silent escalation this module exists
    # to refuse. One purpose rather than one-per-plane: the capability is one
    # assembly act, and a further split would map one-to-one for a distinction
    # no authority in this build can enforce until those planes are searched.
    CONTEXT_PREPARATION = "context_preparation"
    # Retrieval personalization is a purpose of its own rather than a reuse of
    # `capture_authoring`, `continuity_authoring`, or `review_disposition`.
    # `D-91`'s test: would reuse widen the grant? Yes. Those three write notes,
    # projects, and promotions. Admitting a ranking preference under any of
    # them would let a grant issued to store a note or start a project also
    # mutate retrieval ranking. One purpose rather than one-per-action: the
    # capability is one reversible preference write, and a further split would
    # map one-to-one for a distinction no authority in this build can enforce.
    CONTEXT_PREFERENCE = "context_preference"
    # GoodNotes page-version work is a purpose of its own rather than a reuse of
    # `knowledge_search` or `review_disposition`. `D-91`'s test: would reuse
    # widen the grant? Yes. `knowledge_search` is one enrollment's extraction
    # plane. `review_disposition` promotes a proposal to a canonical assertion.
    # Admitting an immutable page-version lookup under either would let a grant
    # issued to search extracted text or decide a review also fetch GoodNotes
    # page-version handles. The matching write purpose is separate: a purpose
    # wide enough to cover reading work and submitting a semantic proposal is a
    # purpose that grants both.
    GOODNOTES_WORK = "goodnotes_work"
    GOODNOTES_PROPOSAL = "goodnotes_proposal"
    # Page-version visual content is a purpose of its own rather than a reuse of
    # `goodnotes_work` or `knowledge_read`. `goodnotes_work` is the metadata
    # handle. `knowledge_read` is extracted text inside one enrollment. A purpose
    # wide enough to cover both the handle and the handwriting raster is a
    # purpose that grants both.
    GOODNOTES_CONTENT = "goodnotes_content"
    # Scheduled-client pull and completion share one authority: both advance
    # the authenticated client's bounded assignment ledger. Observation is
    # separate so a grant to inspect progress cannot claim or complete work.
    GOODNOTES_PULL = "goodnotes_pull"
    GOODNOTES_PULL_OBSERVATION = "goodnotes_pull_observation"
    # Intelligence Artifact / Report plane. Two purposes rather than a reuse of
    # `capture_authoring`, `document_authoring`, or `knowledge_read`. `D-91`'s
    # test: would reuse widen the grant? Yes. Capture authoring writes
    # user-authored notes. Document authoring writes managed-document bytes.
    # Knowledge read is one enrollment's extraction plane. Admitting a
    # synthesized Morning Intelligence artifact under any of those would let a
    # grant issued to store a note, write a file, or read extracted text also
    # persist or retrieve pipeline artifacts. Writing and reading are separated
    # for the same reason the capture and document pairs are two: a purpose wide
    # enough to cover both is a purpose that grants both.
    REPORT_AUTHORING = "report_authoring"
    REPORT_READ = "report_read"
    # The relationship-intelligence entity plane's read purpose, and only one of
    # it. A purpose of its own rather than a reuse, on the `TASK_READ` argument:
    # `knowledge_read` is one enrollment's extraction plane, `capture_review` is
    # the review queue, `task_read` is a Principal's tasks, and none of them
    # reaches `knowledge.entities` or its aliases, identifiers, assignments and
    # edges. A grant issued to search extracted text has no occasion to also
    # return who a person is.
    #
    # One read purpose rather than several, on the `capture.search` argument
    # (`D-91`): every `entities.*` read reaches the same rows under the same
    # authority, so a second one would map to a single capability and separate
    # nothing while costing another frozen-constraint `ALTER`. That covers the
    # paged identifier and alias listings `WP-RI-A-02` adds as well: they read
    # `entity_external_identifiers` and `entity_aliases`, which `entities.context`
    # already returns from under this purpose.
    ENTITY_READ = "entity_read"
    # The entity plane's two write purposes. Both arrived with Phase A, and all
    # three of its authoring packages declared `ENTITY_AUTHORING` independently;
    # it is declared once here, with the argument each of them made for it.
    #
    # **The comment beside `ENTITY_READ` used to record the absence of a write
    # purpose as deliberate** — "this plane has no write capability, and a
    # purpose no capability permits is denied for everything and reads as a
    # mistake rather than as a decision" — and that reasoning is why both of
    # them arrive with the write capabilities that permit them rather than
    # ahead of them. That paragraph described a plane with no writes, and stops
    # being true here rather than being quietly left standing.
    #
    # **Neither is a reuse of `ENTITY_READ`, and `D-91`'s test answers loudly in
    # both directions.** Admitting the writes under the read purpose would mean
    # a grant issued so an assistant can look up who someone is could also
    # rename them, retire the address their mail arrives at, archive them, and
    # assert who they report to — which is the exact separation the capture,
    # document, task, commitment and memory planes each split their purposes to
    # preserve. `RELATIONSHIP_MEMORY_AUTHORING` writes private notes *about* a
    # person and this writes who the person *is*; a grant for one has no
    # occasion to reach the other. `CAPTURE_AUTHORING` is ADR-003's append-only
    # user-authored plane, and an identity correction is neither append-only nor
    # a capture.
    #
    # **`ENTITY_OBSERVATION_INGEST` covers `entities.observe` alone**, and is
    # separate from `ENTITY_AUTHORING` for the reason the whole plane is built
    # around: recording what a source said is not the same act as deciding who
    # somebody is. An ingest path — a connector, a capture pipeline, anything
    # that reads a mailbox — needs to write evidence continuously and must never
    # be able to bind an identity; a grant that covered both would let the thing
    # with the widest reach and the least judgement do the one thing this plane
    # reserves. `entities.observe` is permitted under this purpose and under no
    # other, so it is unreachable by whichever grant a caller happened to hold.
    #
    # **`ENTITY_AUTHORING` covers every decision the plane admits**: what an
    # entity is called and whether it is archived, which external addresses
    # resolve to it, what it may be called, who it is assigned to and what it is
    # directed at, and what an unresolved mention refers to. One rather than one
    # per record family, on the argument `DOCUMENT_AUTHORING` covers create,
    # revise, archive and restore together: all of them touch the acting
    # Principal's own entities, none destroys anything, and each lifecycle
    # transition has an inverse. The residual is stated rather than smoothed
    # over: a grant issued to correct a misspelled display name also reaches
    # every identifier binding, every archive and every directed edge on that
    # Principal's entities. It is paid because the alternative is a purpose per
    # family, which no authority in this build could act on differently — under
    # `P00-OD-010` there is one local Principal — and which would cost several
    # more frozen-constraint literals, while the separations that do matter,
    # reading versus writing identity and ingesting evidence versus deciding
    # identity, are the two these members make.
    ENTITY_OBSERVATION_INGEST = "entity_observation_ingest"
    ENTITY_AUTHORING = "entity_authoring"
    # The Relationship Memory plane's pair. Two rather than one, on the rule
    # this module states for the capture and managed-document planes: a purpose
    # wide enough to cover writing and reading is a purpose that grants both,
    # and here that matters more than anywhere else in this schema — a grant
    # issued so an assistant can recall what the user recorded about someone
    # must not also let it write new assertions about that person.
    #
    # Neither is a reuse. `ENTITY_READ` is the identity plane and reaches
    # aliases, identifiers, assignments and edges; admitting a memory read under
    # it would let a grant issued to learn who someone is also return the
    # user's private notes about them. `CAPTURE_AUTHORING` is ADR-003's
    # append-only capture plane; admitting a memory write under it would let a
    # grant issued to store a Quick Note write an entity-bound statement about
    # another person. Different tables, different subject, different exposure.
    #
    # `RELATIONSHIP_MEMORY_READ` covers all four reads (`get`, `list`,
    # `search`, `history`) for the reason `TASK_READ` covers its four: they are
    # four queries over the acting Principal's own rows and no write, so a
    # purpose wide enough for one is wide enough for the rest without widening
    # what a grant reaches. Holding it is still not sufficient to disclose a
    # `restricted_local` memory to every destination — classification and
    # destination are decided separately, which is why `sensitivity` can be
    # readable in a profile and absent from a broad search under the same grant.
    RELATIONSHIP_MEMORY_READ = "relationship_memory_read"
    RELATIONSHIP_MEMORY_AUTHORING = "relationship_memory_authoring"
    # Phase B's additions. Each is a purpose of its own rather than a reuse, and
    # `D-91`'s test — would the reuse widen the grant? — answers loudly in every
    # case.
    #
    # **`ENTITY_PROPOSAL` is not `ENTITY_AUTHORING`.** Authoring *decides* who a
    # person is; a proposal *asks* a reviewer to. Admitting the producer path
    # under the authoring purpose would mean a grant issued so a rule can raise
    # candidates could also rename an entity, retire the address their mail
    # arrives at, and assert who they report to — which is the self-promotion
    # operator §16 forbids, arrived at by the grant rather than by a code path.
    # Nor is it `ENTITY_OBSERVATION_INGEST`: that records what a source *said*
    # and binds nothing, while a proposal names a mutation and a target version.
    # One purpose for the one producer capability, because a second would map
    # one-to-one and cost another frozen-constraint literal.
    ENTITY_PROPOSAL = "entity_proposal"
    # **`ENTITY_IDENTITY_CORRECTION` is not `ENTITY_AUTHORING` and not
    # `REVIEW_DISPOSITION`.** Operator §24 puts `entities.merge.preview` and
    # `entities.merge` behind an operator authorization context, and §15 says a
    # reviewer grant is not an identity-correction grant. Admitting either under
    # `ENTITY_AUTHORING` would hand every holder of the eighteen Phase A writes
    # the authority to collapse two people into one; admitting them under
    # `REVIEW_DISPOSITION` would make `review.decide` a hidden merge endpoint by
    # grant, which is the exact sentence §15 writes.
    #
    # **One purpose covering both the preview and the apply, deliberately, and
    # the coupling is accepted rather than worked around.** The remote boundary
    # derives write-gating from `permitted_purposes(capability) & _WRITE_PURPOSES`
    # (`adapters/mcp/remote.py`), so a shared purpose makes the preview
    # remote-write-gated too. Splitting it to un-gate the preview would create a
    # purpose that reads the whole affected world of a merge — every alias,
    # identifier, assignment, edge, observation, proposal and review case of two
    # people — under a grant narrower than the one the merge needs, which is a
    # weaker §24 boundary bought with a schema literal. The preview also
    # persists a durable control row, so it is a write in this module's own
    # terms; see `_WRITE_CAPABILITIES`.
    ENTITY_IDENTITY_CORRECTION = "entity_identity_correction"
    # **`RELATIONSHIP_MEMORY_PROPOSAL` is not `RELATIONSHIP_MEMORY_AUTHORING`,**
    # for the reason `ENTITY_PROPOSAL` is not `ENTITY_AUTHORING`, and here the
    # separation is the whole of operator §12: the authoring purpose creates an
    # *active* memory, and this path is forbidden to. A grant issued to a rule
    # so it can raise candidates about a person must not also let it write
    # accepted private statements about them — and reuse would make the
    # prohibition a property of the handler rather than of the grant. Reading is
    # separate again: a producer proposes and does not read back, so neither of
    # the plane's existing pair is widened.
    RELATIONSHIP_MEMORY_PROPOSAL = "relationship_memory_proposal"
    # Connected-MCP B0 workflow purposes. Two rather than one, on the same rule
    # as the capture and managed-document planes: a purpose wide enough to cover
    # starting a repetition and observing it is a purpose that grants both.
    # Neither reuses `goodnotes_work` / `goodnotes_content` (`D-91`): those are
    # the stdio analyzer plane. This pair is the ChatLLM-facing orchestration
    # surface on production `my-pa` MCP.
    GSQS_B0_EXECUTION = "gsqs_b0_execution"
    GSQS_B0_OBSERVATION = "gsqs_b0_observation"
