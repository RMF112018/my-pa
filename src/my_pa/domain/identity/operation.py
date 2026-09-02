"""The public capabilities and the purposes that may invoke them.

Binding capability to purpose in the domain keeps the rule in one place instead
of scattering it through transport or adapter conditionals.

**The failure mode here is silent, which is why both maps are exhaustive.**
`permitted_purposes` answers with the empty set for a capability nobody mapped,
so an unmapped member is denied for every purpose with no error anywhere — the
policy denial reads exactly like a deliberate one. `_OPERATOR_ONLY` fails the
other way: an unlisted member defaults to *not* operator-only, so a capability
that should have been restricted is silently open. Neither absence raises, so a
member added to `Capability` without a decision in both maps below is a defect
that no test of this module alone can see. `tests/unit/test_policy.py` compares
the mapping against the enum for exactly that reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.identity.purpose import Purpose

__all__ = [
    "AuthorizedCapability",
    "Capability",
    "NativeSourceCapability",
    "is_destructive_capability",
    "is_operator_only",
    "is_write_capability",
    "permitted_purposes",
]


class Capability(StrEnum):
    """Public capability names in the `my-pa-public-capabilities` v1 family."""

    CAPABILITIES_GET = "capabilities.get"
    SOURCES_LIST = "sources.list"
    SOURCES_METADATA = "sources.metadata"
    SOURCES_FETCH = "sources.fetch"
    SOURCES_STATUS = "sources.status"
    SOURCES_ENROLL = "sources.enroll"
    KNOWLEDGE_SEARCH = "knowledge.search"
    KNOWLEDGE_READ = "knowledge.read"
    # The sixteenth, and `5e2c7b0a94f6` carries the forward `ALTER` that admits
    # it — written before the member, for the reason the two below record.
    #
    # **A capability rather than a widening of `knowledge.read`.** `read`
    # answers *what* one stored record says inside one enrollment's grant;
    # `reveal` answers *why* a derived record exists, by returning the evidence
    # spans under it, the version and capture they lie in, and the derivation
    # trace from proposal through review case and decision to assertion and
    # promotion receipt. Those are different rows, a different scope — a capture
    # belongs to no enrollment — and a different answer, so one grant covering
    # both would let a request issued to read a record also traverse lineage.
    #
    # **`knowledge.` rather than `capture.`** because the question is about the
    # product's knowledge of a subject rather than about the capture plane's own
    # storage, and a caller holding a subject identifier does not know which
    # plane it came from. What the *build* can traverse is narrower than that
    # name, and Reveal says so in its answer rather than in its name: a subject
    # this evidence model does not cover is reported `unavailable` rather than
    # answered with an empty result.
    KNOWLEDGE_REVEAL = "knowledge.reveal"
    # The capture plane (`D-70`). `capture.create` is the name the canonical
    # package fixes in six places; the other three are this repository's choice
    # under `ADR-003:107`, which gives capability names to "an implementing work
    # package and its pull request". Two segments each, like the eight above,
    # and a domain act rather than CRUD — `revise` is ADR-003 clause 3's own
    # frame for an edit that appends a successor version.
    CAPTURE_CREATE = "capture.create"
    CAPTURE_REVISE = "capture.revise"
    CAPTURE_READ = "capture.read"
    CAPTURE_LIST = "capture.list"
    # The thirteenth, and it is a capability rather than a widening of
    # `knowledge.search` (`D-91`). `domain.identity.purpose` already argues why:
    # the knowledge plane is the *extraction* plane, and one grant spanning both
    # would let a `knowledge.read`-shaped request return raw user-authored
    # capture text. There is also no scope to share — `knowledge.search` is
    # scoped by enrollment and a capture belongs to none. The word `search`
    # bound to the capture noun is the canonical package's own
    # (`docs/specs/quick-capture/18_PROPOSED_API_AND_CONTRACT_PACKAGE.md:334`),
    # and two segments of `noun.verb` is the rule the four above follow.
    CAPTURE_SEARCH = "capture.search"
    # `review.list` and `review.decide` are the fourteenth and fifteenth, and
    # `3c8f1e2a5b74` already carries the forward `ALTER` that admits them — the
    # freeze is written before the members, because a member with no `ALTER`
    # leaves every test green and is refused by the stored constraint on the
    # first audited operation in the field. The members, commands, and handlers
    # land together because `adapters/mcp/tools` derives its tool set at import.
    REVIEW_LIST = "review.list"
    REVIEW_DECIDE = "review.decide"
    # The seventeenth, eighteenth and nineteenth, and `8f2b6c4d1a37` carries the
    # forward `ALTER` that admits all three — written before the members, for the
    # reason `5e2c7b0a94f6` records: a member with no `ALTER` leaves every test
    # green, because every test builds its database from scratch, and is refused
    # by the stored constraint on the first audited operation in the field.
    #
    # **`continuity.` rather than `knowledge.`** because these read the durable
    # continuity plane — Situations, Projects, Commitments, Decisions, Tasks —
    # which belongs to no enrollment and holds no extracted record. Reaching them
    # under a `knowledge.` name would tell a caller that a grant issued over the
    # extraction plane covers the Principal's own obligations, and it does not.
    #
    # **Three rather than one.** A single `continuity.read` would make the Pulse,
    # the Situation board and the Project list one grant, and they are three
    # different answers over three different row sets: Pulse *derives* and ranks,
    # Situations lists a partition, Projects lists another. `D-91`'s test — does
    # one name reach rows another does not — separates them.
    #
    # None is operator-only: each reads the acting Principal's own accepted
    # records, grants nothing, and promotes nothing.
    CONTINUITY_PULSE = "continuity.pulse"
    CONTINUITY_SITUATIONS = "continuity.situations"
    CONTINUITY_PROJECTS = "continuity.projects"
    # User-directed continuity writes. Three rather than one, by `D-91`:
    # `projects.create` writes a Project row, `situations.create` writes a
    # Situation row, and `tasks.create` writes a Task row. One grant covering
    # all three would let a request permitted to start a project also open a
    # situation and accept a task. None is operator-only: each writes the
    # acting Principal's own partition and grants nothing.
    #
    # `7c2e9b4a1d80` carries the forward `ALTER` that admits these three writes
    # and `continuity_authoring`.
    CONTINUITY_PROJECTS_CREATE = "continuity.projects.create"
    CONTINUITY_SITUATIONS_CREATE = "continuity.situations.create"
    CONTINUITY_TASKS_CREATE = "continuity.tasks.create"
    # The twentieth, and `2d9f4a7c1e58` carries the forward `ALTER` that admits
    # it — written before the member, for the reason `5e2c7b0a94f6` records: a
    # member with no `ALTER` leaves every test green, because every test builds
    # its database from scratch, and is refused by the stored constraint on the
    # first audited operation in the field.
    #
    # **A capability rather than a widening of `sources.status`.** `D-91`'s test
    # is whether one name reaches rows another does not. `sources.status` answers
    # about **one named subject** — a source, an enrollment, an operation or an
    # object — inside a scope the Principal already holds, and its requested
    # scope is derived from that subject. `knowledge.coverage` names no subject at
    # all: it reads every enrollment the acting Principal holds at once, and it
    # reads `source_objects` rows that lie *outside* every one of them, which no
    # status request can reach through any subject it is able to name. Widening
    # `sources.status` to answer it would mean a request that named one source
    # returning counts about all of them, which is the silent scope escalation
    # `_requested_scope` exists to prevent.
    #
    # **And not a widening of `knowledge.search`.** That capability is scoped by
    # the enrollment the request names, and WP-23 makes a search *say* that its
    # answer does not span the corpus rather than letting it reach past the
    # enrollment to find out. Admitting the corpus read under the search name
    # would authorize exactly the reach that token exists to deny.
    #
    # **`knowledge.` rather than `sources.` or `continuity.`** because the answer
    # is about the extraction plane's coverage of what the Principal holds —
    # enrollments, enumerated objects, and outcomes — and not about a configured
    # source's own state, which is what the `sources.` family answers.
    #
    # Not operator-only: it grants nothing, writes nothing, and returns counts
    # over the acting Principal's own enrollments and no one else's.
    KNOWLEDGE_COVERAGE = "knowledge.coverage"
    # The managed-document plane (WP-28), and `6b3d9a2f8c14` carries the forward
    # `ALTER` that admits all six — written before the members, for the reason
    # `5e2c7b0a94f6` records: a member with no `ALTER` leaves every test green,
    # because every test builds its database from scratch, and is refused by the
    # stored constraint on the first audited operation in the field.
    #
    # **Why they exist at all.** WP-27 shipped the managed-document write plane
    # with no seat, so `ManagedDocumentService` was reachable only from a
    # composition root and a managed write left no `knowledge.audit_events` row
    # — not even for a refusal. That was disclosed and bounded because nothing
    # could reach it; exposing the plane over a transport removes the bound, so
    # the seat lands before the transport does. `authorize()` writes the audit
    # row in the request's own transaction, so a seat *is* the audit.
    #
    # **`documents.` rather than `knowledge.` or `capture.`.** These reach
    # `knowledge.managed_documents` and its four sibling tables, which belong to
    # no enrollment, hold no extracted record and hold no user-authored capture.
    # A `knowledge.` name would tell a caller that a grant issued over the
    # extraction plane covers the product's own document custody, and a
    # `capture.` name would say the same of ADR-003's append-only records. Two
    # neutral segments of `noun.verb`, as `AGENTS.md` section 4 requires of every
    # external and MCP name.
    #
    # **Six rather than fewer, by `D-91`'s own test — does one name reach rows
    # another does not.** `create` writes a document that did not exist and
    # `revise` appends to one that did, which is the difference
    # `CreateManagedDocumentCommand` and `ReviseManagedDocumentCommand` already
    # make in the type rather than in a nullable field; conflating them would let
    # a grant issued to start a document rewrite every document the Principal
    # holds. `read` returns one version's metadata and, when asked, its bytes,
    # while `list` returns a page of documents and no bytes at all — one reaches
    # a body the other cannot. `archive` withdraws a document from the active set
    # and `restore` returns it: opposite transitions, and one grant covering both
    # would mean a request permitted to hide a document is also permitted to
    # un-hide one somebody else's session hid. And no write shares a name with a
    # read, which is the line `domain/identity/purpose.py` draws for the capture
    # plane and this plane is no different.
    #
    # None is operator-only. The test `_OPERATOR_ONLY` applies is whether the
    # capability *grants authority* — widens the scope a later request is
    # evaluated against — and none of these does: they write, read and transition
    # the acting Principal's own documents inside the acting Principal's own
    # partition, exactly as `capture.create` does for the capture plane. Archive
    # is a reversible transition and destroys nothing; there is no delete on this
    # plane at all, and `AGENTS.md` section 8.2 keeps irreversible destruction of
    # canonical data with the operator whether or not a seat exists for it.
    DOCUMENTS_CREATE = "documents.create"
    DOCUMENTS_REVISE = "documents.revise"
    DOCUMENTS_READ = "documents.read"
    DOCUMENTS_LIST = "documents.list"
    DOCUMENTS_ARCHIVE = "documents.archive"
    DOCUMENTS_RESTORE = "documents.restore"
    # The `tasks.` read plane (WP-TM-03), and the forward `ALTER` that admits all
    # four lands with them, in the shape `6b3d9a2f8c14` set for the `documents.`
    # plane and for the reason `5e2c7b0a94f6` records: a member added here with
    # no widened constraint leaves every test green — every test builds its
    # database from scratch — and is refused by the stored check the first time
    # a real deployment serves the capability.
    #
    # **Four rather than one `tasks.read`, by `D-91`'s own test — does one name
    # reach rows another does not.** `read` answers about one named task;
    # `list` answers a bounded page of every task this Principal holds, filtered
    # by lifecycle state and priority; `search` answers the same page filtered by
    # a lexical match on the title instead of by a structured column; and
    # `history` answers the append-only mutation receipts for one task, which is
    # `knowledge.task_history` and not `knowledge.tasks` at all. A single name
    # covering the four would let a grant issued to look up one task by
    # identifier also enumerate every task the Principal holds, search all of
    # them, and read the mutation trail behind any of them — four different
    # answers over two different tables under one name.
    #
    # **`tasks.` rather than `continuity.` or `knowledge.`.** `WP-TM-01`'s
    # `domain.task.task.Task` is the richer per-task model this build is
    # growing deliberately apart from `situation.continuity.Task`'s two-state
    # shape, and `continuity.situations`/`continuity.projects`/`continuity.pulse`
    # read the accepted end of that older, coarser model. A `continuity.` name
    # here would tell a caller that a grant issued for the Pulse also reaches
    # the finer lifecycle, priority, and scheduling fields this plane adds, which
    # is not true today and need not become true for this package to ship.
    # `knowledge.` is the extraction plane's, scoped by enrollment, and a task
    # belongs to no enrollment — exactly the reasoning `capture.` and
    # `documents.` already state for themselves.
    #
    # **Read-only, and MCP-exposed for the first time.** WP-TM-01 built the
    # domain and schema and WP-TM-02 built the canonical mutation mechanism,
    # both deliberately unreachable from any transport. This package is the
    # first time a `tasks.` request can be made from outside this process, and
    # it admits only the four reads above — no create, update, or transition
    # capability is named here, because exposing mutation over MCP is a later
    # package's job (the plan's WP-TM-04), not this one's.
    #
    # None is operator-only: each reads the acting Principal's own tasks inside
    # the acting Principal's own partition, grants nothing, and promotes
    # nothing — exactly the test `_OPERATOR_ONLY` applies to every other read
    # capability above.
    TASKS_READ = "tasks.read"
    TASKS_LIST = "tasks.list"
    TASKS_SEARCH = "tasks.search"
    TASKS_HISTORY = "tasks.history"
    # The task plane's write capabilities (WP-TM-04), and the forward `ALTER`
    # that admits all five lands with them, in the shape `6b3d9a2f8c14` set for
    # the `documents.` plane and for the reason `5e2c7b0a94f6` records: a member
    # added here with no widened constraint leaves every test green — every test
    # builds its database from scratch — and is refused by the stored check the
    # first time a real deployment serves the capability.
    #
    # **Five rather than fewer, by `D-91`'s own test — does one name reach rows
    # another does not.** `create` writes a task that did not exist and `update`
    # modifies one that did, which is the difference `CreateTask` and `UpdateTask`
    # already make in the type rather than in a nullable field; conflating them
    # would let a grant issued to start a task rewrite every task the Principal
    # holds. `transition` moves a task through its lifecycle and is a distinct
    # operation from `update` because it carries closure evidence and enforces
    # terminal-state rules. `bulk_preview` and `bulk_confirm` are the two-phase
    # bulk operation: preview returns changes without applying them, confirm
    # applies them atomically. A grant issued to preview changes should not also
    # authorize applying them without the caller's explicit confirmation, so they
    # are separate capabilities.
    #
    # None is operator-only. The test `_OPERATOR_ONLY` applies is whether the
    # capability *grants authority* — widens the scope a later request is
    # evaluated against — and none of these does: they write the acting
    # Principal's own tasks inside the acting Principal's own partition, exactly
    # as `documents.create` does for the managed-document plane. No write shares
    # a name with a read, which is the line `domain/identity/purpose.py` draws
    # for the capture plane and this plane is no different.
    TASKS_CREATE = "tasks.create"
    TASKS_UPDATE = "tasks.update"
    TASKS_TRANSITION = "tasks.transition"
    TASKS_BULK_PREVIEW = "tasks.bulk_preview"
    TASKS_BULK_CONFIRM = "tasks.bulk_confirm"
    # The Commitment plane (WP-TM-05). `COMMITMENTS_READ`/`COMMITMENTS_LIST`
    # are the two direct reads, over `knowledge.commitments`, exactly
    # parallel to `TASKS_READ`/`TASKS_LIST`. `COMMITMENTS_WAITING_ON` is a
    # third read rather than a filter on `COMMITMENTS_LIST`: it answers a
    # different question ("what am I waiting on", assembled from accepted
    # `OWED_TO_PRINCIPAL` Commitments plus linked `WAITING`/Follow-Up Task
    # state) over two tables rather than one, and no new table or store backs
    # it — see `application.service`'s handler. `COMMITMENTS_CREATE`/
    # `COMMITMENTS_CLOSE` are the two writes `CommitmentManagementService`
    # exposes; there is no update capability beyond closure because that
    # service names no other Commitment mutation. None of the five is
    # operator-only, for the identical reason the task plane's own nine are
    # not: each reads or writes the acting Principal's own Commitments inside
    # the acting Principal's own partition, granting nothing and promoting
    # nothing.
    COMMITMENTS_READ = "commitments.read"
    COMMITMENTS_LIST = "commitments.list"
    COMMITMENTS_SEARCH = "commitments.search"
    COMMITMENTS_HISTORY = "commitments.history"
    COMMITMENTS_WAITING_ON = "commitments.waiting_on"
    COMMITMENTS_CREATE = "commitments.create"
    COMMITMENTS_UPDATE = "commitments.update"
    COMMITMENTS_CLOSE = "commitments.close"
    # A capability rather than a widening of `knowledge.search`. **A new purpose
    # rather than `knowledge_search`.** `D-91`'s test is whether reuse would
    # widen the grant, and here it would: `knowledge.search` is scoped by one
    # enrollment on the extraction plane, while `context.prepare` is the
    # assembly that will (WP-KC-02) cite capture and continuity rows that
    # search cannot reach. One grant covering both would let a request issued
    # to search one enrollment also pack user-authored notes and accepted
    # continuity — the silent escalation `purpose.py` exists to refuse.
    #
    # Not operator-only: it grants nothing, writes nothing, and returns a
    # bounded package of the acting Principal's own authorized evidence.
    # Remotely grantable for the same reason `knowledge.search` is: a ChatLLM
    # needs this before answering questions that depend on personal context.
    #
    # Alembic revision `8a1c4e7b2d90` admits the live vocabulary. A stored
    # `capability_is_known` constraint before that revision refuses the name.
    CONTEXT_PREPARE = "context.prepare"
    # A capability rather than a widening of `context.prepare`. Prepare is a
    # read of authorized evidence; feedback writes a reversible ranking
    # preference. One grant covering both would let a request issued to assemble
    # a packet also mutate later ranking — the silent escalation `purpose.py`
    # exists to refuse. Not operator-only: it writes the acting Principal's own
    # partition and grants nothing. It cannot change canonical facts, authority,
    # source scope, or lifecycle.
    #
    # Alembic revision `c6f1a8d3e204` admits the live vocabulary. A stored
    # `capability_is_known` constraint before that revision refuses the name.
    CONTEXT_FEEDBACK = "context.feedback"
    # A pair of capabilities rather than a widening of `knowledge.search`,
    # `knowledge.read`, `review.decide`, or `context.prepare` (`D-91`). Search
    # and read are the extraction plane, scoped by enrollment. Review decides
    # canonical change state. Prepare assembles a cross-plane packet. None of
    # those is "return one immutable GoodNotes page-version handle" or "accept a
    # structured semantic proposal without reconciling it". One grant covering
    # both of these would let a request issued to fetch work also submit a
    # proposal, so the names stay distinct. Two-segment `noun.verb`, no
    # former-employer branding.
    #
    # Neither is operator-only: each operates on the acting Principal's own
    # partition and grants no authority. Alembic revision `d7e1a4c8b926` admits
    # the live vocabulary.
    GOODNOTES_WORK = "goodnotes.work"
    GOODNOTES_PROPOSE = "goodnotes.propose"
    # A capability rather than a widening of `goodnotes.work` or `knowledge.read`.
    # `D-91`'s test: would reuse widen the grant? Yes. `goodnotes.work` returns a
    # digest/handle and renderer provenance with no page bytes. `knowledge.read`
    # is one enrollment's extraction plane. Admitting the pinned visual raster
    # under either would let a grant issued to fetch metadata or search extracted
    # text also retrieve handwriting pixels. Alembic revision `a4d9c2e7b815`
    # admits the live vocabulary. Not operator-only: it reads the acting
    # Principal's own partition and grants no authority.
    GOODNOTES_CONTENT = "goodnotes.content"
    # Connected-MCP B0 prediction-acquisition workflow. A pair of names rather than a
    # widening of `goodnotes.work` / `goodnotes.content` (`D-91`): those remain
    # the stdio-isolated analyzer plane. ChatLLM initiates a repetition through
    # production `my-pa` MCP; the server owns campaign identity, stdio lifecycle,
    # and capture persistence. Alembic revision `c4b0a1d9e827` admits the live
    # vocabulary. Neither is operator-only: each operates on the acting
    # Principal's own partition. Real handwriting remains fail-closed.
    GSQS_START = "gsqs.start"
    GSQS_STATUS = "gsqs.status"
    # Intelligence Artifact / Report plane. Eight `reports.*` names rather than a
    # widening of `capture.*`, `documents.*`, `knowledge.*`, or `context.*`
    # (`D-91`). Capture is user-authored notes. Documents are managed bytes.
    # Knowledge is enrollment-scoped extraction. Context assembles a retrieval
    # packet. None of those is "begin a Morning Intelligence cycle", "commit an
    # immutable pipeline artifact", or "resolve the exact fan-in set for one
    # cycle run". Writes and reads stay distinct: a grant issued to commit a
    # Collector must not also authorize reading another Principal's Brief, and
    # a grant issued to read a Brief must not authorize writing one. Alembic
    # revision `e9b2c4d7a150` admits the live vocabulary.
    #
    # None is operator-only: each reads or writes the acting Principal's own
    # partition and grants no authority. Production remote grants stay off;
    # this only names the capabilities.
    REPORTS_BEGIN_CYCLE = "reports.begin_cycle"
    REPORTS_COMMIT = "reports.commit"
    REPORTS_RECORD_RUN_STATE = "reports.record_run_state"
    REPORTS_READ = "reports.read"
    REPORTS_LATEST = "reports.latest"
    REPORTS_LIST = "reports.list"
    REPORTS_SEARCH = "reports.search"
    REPORTS_RESOLVE_SET = "reports.resolve_set"
    # The relationship-intelligence entity plane. Forty-eight `entities.` names
    # over `knowledge.entities` and the tables around it, declared in four
    # blocks by the package that added each: WP-RI-05's six reads here, then
    # WP-RI-A-02's twelve, WP-RI-A-03's seven and WP-RI-A-04's three.
    # Alembic revision `c1a7e4b93d58` admits the first five and the
    # `entity_read` purpose, `e4d7b2f9a316` the sixth, and `823e23b6cc63` the
    # remaining twenty-two together with `entity_authoring` and
    # `entity_observation_ingest`; the freeze is written before the members,
    # because a member with no `ALTER` leaves every test green and is refused by
    # the stored constraint on the first audited operation in the field.
    #
    # `D-91`'s test, applied once for the family: would reuse widen the grant?
    # Yes, in both directions. `knowledge.search` is the extraction plane and
    # would have to return who a person is; `entities.search` would have to
    # return extracted document text. They are different custody planes over
    # different tables.
    #
    # Six rather than one, because they answer different questions and a caller
    # granted one has no occasion to hold the others. `search` is a name-shaped
    # lookup over a Principal's own entities. `get` is one entity by identifier.
    # `resolve` answers "who is this reference", and is the one whose answer can
    # be *ambiguous on purpose*. `context` assembles a bounded card. `relationships`
    # walks one entity's typed edges to depth one. `unresolved_mentions` lists the
    # references nothing has placed, admitted later by `e4d7b2f9a316`. None of them
    # writes, which is why `_PERMITTED_PURPOSES` maps every one of them to a
    # single read purpose. **The plane as a whole is no longer read-only** --
    # the three blocks below add four further reads and eighteen writes, and
    # each records what its own package changed and what it did not.
    #
    # Not operator-only: each reads the acting Principal's own partition and
    # grants no authority. Withholding from a process that has not enabled the
    # plane is `_ENTITY_CAPABILITIES` in `application.service`, not this flag —
    # operator-only is about who may call a capability, and composition gating is
    # about whether this build serves it at all.
    ENTITIES_SEARCH = "entities.search"
    ENTITIES_GET = "entities.get"
    ENTITIES_RESOLVE = "entities.resolve"
    ENTITIES_CONTEXT = "entities.context"
    ENTITIES_RELATIONSHIPS = "entities.relationships"
    #: The queue of references nothing has placed. Named for exactly what it
    #: returns: `entities.mentions` would read as every mention, and this answers
    #: only the unresolved ones, which is the whole of its use.
    ENTITIES_UNRESOLVED_MENTIONS = "entities.unresolved_mentions"
    # WP-RI-A-02: the entity plane's authoring half, and the first block here to
    # write anything. Two more reads and ten writes, and the comment above --
    # "this plane has no write capability at all" -- was true of the reads-only
    # build it was written for and is not true after this package. The reason it
    # was true is worth keeping: nothing in this build could *author* an
    # identity, so a write purpose would have been a purpose no capability
    # permitted. There is one now, and it is
    # `entity_authoring`.
    #
    # **The two new reads exist because the writes do.** A caller that may
    # retire an identifier has to be able to see which identifiers there are and
    # which of them are still active, and `entities.context` cannot answer that:
    # it is one bounded card that truncates, and it discloses neither state nor
    # a continuation for either collection. So `identifiers.list` and
    # `aliases.list` are the paged, filterable reads the lifecycle writes are
    # driven from. They map to `entity_read` with the other six, on the argument
    # that module already makes for the family: they read the same rows under
    # the same authority and a purpose apiece would separate nothing.
    #
    # **Ten writes rather than four, and the split is by what a grant reaches.**
    # `create`/`update`/`archive`/`restore` change what an entity *is*;
    # `identifiers.*` change which external addresses resolve to it, which is
    # the half that decides whether a stranger's mail lands on this person; and
    # `aliases.*` change what it may be called, which resolves nothing on its
    # own because section 15.2 says names alone are insufficient. `bind`,
    # `retire` and `supersede` are three rather than one for the reason
    # `tasks.bulk_preview` and `tasks.bulk_confirm` are two: a grant issued to
    # record a new address has no occasion to also withdraw the one that is
    # there, and superseding is both at once and says so.
    #
    # `D-91`'s test, applied to the family: would reuse widen the grant? There
    # is nothing to reuse -- no capability in this build writes
    # `knowledge.entities` -- so the question is whether these should have been
    # folded into `entities.update`. They should not: an update naming an
    # `identifiers` array would make one grant reach identity bindings, and the
    # whole argument for the split is that it must not.
    #
    # Not operator-only, on the argument the six reads make: each writes the
    # acting Principal's own partition and none widens the scope a later request
    # is evaluated against, which is the property that puts `sources.enroll`
    # there. Withholding them from a build that has not enabled the plane is
    # `_ENTITY_CAPABILITIES` in `application.service`.
    ENTITIES_IDENTIFIERS_LIST = "entities.identifiers.list"
    ENTITIES_ALIASES_LIST = "entities.aliases.list"
    ENTITIES_CREATE = "entities.create"
    ENTITIES_UPDATE = "entities.update"
    ENTITIES_ARCHIVE = "entities.archive"
    ENTITIES_RESTORE = "entities.restore"
    ENTITIES_IDENTIFIERS_BIND = "entities.identifiers.bind"
    ENTITIES_IDENTIFIERS_RETIRE = "entities.identifiers.retire"
    ENTITIES_IDENTIFIERS_SUPERSEDE = "entities.identifiers.supersede"
    ENTITIES_ALIASES_ADD = "entities.aliases.add"
    ENTITIES_ALIASES_RETIRE = "entities.aliases.retire"
    ENTITIES_ALIASES_SUPERSEDE = "entities.aliases.supersede"

    # The directed-relationship write family (WP-RI-A-03). One read and six
    # writes over the two tables that carry *directed* fact: `entity_assignments`
    # and `entity_relationships`. Phase A's single revision `823e23b6cc63`
    # carries the forward `ALTER` admitting all seven; the members were written
    # here before it existed, for the reason the six reads above were, and the
    # consequence was stated plainly at the time -- without that revision the
    # stored `capability_is_known` CHECK refuses the audit row, so an end-to-end
    # call fails at the audit sink rather than in this file.
    #
    # **Three segments rather than two, and only on this family.** Every earlier
    # capability is `plane.verb`, and `entities.create` would have been that
    # shape -- but it would also have been a lie about what it creates. The
    # entity plane holds five record families and this package writes two of
    # them, so the name has to say which; `entities.assignments.create` and
    # `entities.relationships.create` are two different acts on two different
    # tables with two different semantic identities, and a single
    # `entities.create` covering both would be one grant reaching both. The
    # middle segment is the record family, and it is the only thing that makes
    # the pair distinguishable where grants are decided.
    #
    # `entities.assignments.list` is a read and takes `entity_read`, because it
    # returns rows `entities.context` and `entities.relationships` already reach
    # under that purpose. It is a capability of its own rather than a widening
    # of `entities.relationships` on `D-91`'s test read the other way: an
    # assignment is not an edge -- it binds one entity to a scope with a role,
    # where an edge binds two entities -- so serving both from one name would
    # make a caller that wanted one page of edges receive a second record family
    # it did not ask for and cannot page independently.
    #
    # **The six writes are `revise`/`end`, never `update`/`delete`.** ADR-003
    # clause 3's frame: an edit appends, and withdrawal is a lifecycle
    # transition that keeps the row. There is no capability that destroys an
    # assignment or an edge, for the reason there is no
    # `relationship_memory.delete` -- and correction of what a record *means*
    # (its type, its endpoints, its scope) is not an edit at all: it is `end`
    # followed by `create`, because those fields are the record's identity and
    # editing identity in place rewrites history rather than recording it.
    #
    # Not operator-only. These write canonical fact about the acting Principal's
    # own entities and grant no authority -- none of them widens the scope a
    # later request is evaluated against, which is the property that puts
    # `sources.enroll` there. Withholding them from a build that has not enabled
    # the plane is `_ENTITY_CAPABILITIES` in `application.service`.
    ENTITIES_ASSIGNMENTS_LIST = "entities.assignments.list"
    ENTITIES_ASSIGNMENTS_CREATE = "entities.assignments.create"
    ENTITIES_ASSIGNMENTS_REVISE = "entities.assignments.revise"
    ENTITIES_ASSIGNMENTS_END = "entities.assignments.end"
    ENTITIES_RELATIONSHIPS_CREATE = "entities.relationships.create"
    ENTITIES_RELATIONSHIPS_REVISE = "entities.relationships.revise"
    ENTITIES_RELATIONSHIPS_END = "entities.relationships.end"

    #: WP-RI-A-04. One read and two writes, the last of Phase A's four blocks.
    #:
    #: `entities.observations.list` is the second read of the observation table
    #: and is not a widening of `entities.unresolved_mentions`: that one answers
    #: "what could nobody place", and this one answers "what has this plane been
    #: told, and what happened to it" -- including the mentions that *were*
    #: placed, which the queue by definition never shows. Both withhold the
    #: observed text; neither is a way to read it back.
    #:
    #: `entities.observe` records evidence and creates nothing. Its own name
    #: rather than an `entities.create`, because those are different acts with
    #: different authority: section 12.2 says a source record "does not become
    #: the canonical person by itself", and a capability called `create` would
    #: be the first half of building one that did.
    #:
    #: `entities.unresolved_mentions.resolve` decides one mention. Named as the
    #: queue's own verb rather than `entities.link`, because four of its five
    #: dispositions link nothing: three are refusals and one creates. A name
    #: that promised a link would describe the minority of what it does.
    ENTITIES_OBSERVATIONS_LIST = "entities.observations.list"
    ENTITIES_OBSERVE = "entities.observe"
    ENTITIES_UNRESOLVED_MENTIONS_RESOLVE = "entities.unresolved_mentions.resolve"

    #: Phase B's three additions to this plane, and they divide into two very
    #: different authorities that happen to share a name prefix.
    #:
    #: `entities.proposals.create` is the *producer's* whole write surface. It
    #: asks for a mutation and performs none, which is why it is not operator-only
    #: and why it carries a purpose of its own rather than `entity_authoring`: a
    #: rule, a source worker or a local model may hold it, and holding it must
    #: not amount to holding the eighteen writes above. Operator §16 lists it
    #: among the capabilities a producer client may have, beside
    #: `entities.observe` and `review.list`, and beside no disposition at all.
    #:
    #: `entities.merge.preview` and `entities.merge` are **operator-only**, and
    #: they are the first knowledge-plane members of `_OPERATOR_ONLY` — every
    #: other member is source enrollment or a native-host command. The argument
    #: that kept the capture, review and memory planes out of that set is the
    #: one that puts these two in: `_OPERATOR_ONLY` asks whether a capability
    #: *widens the scope a later request is evaluated against*. Deciding a review
    #: promotes the Principal's own proposal about the Principal's own capture
    #: and widens nothing. A merge collapses two identities into one, and every
    #: alias, identifier, assignment, edge, observation and memory that named the
    #: merged-away entity is thereafter reached through the survivor — so a grant
    #: issued before the merge reaches records it did not reach before. That is
    #: the widening `sources.enroll` is here for, arriving on the knowledge
    #: plane for the first time.
    #:
    ENTITIES_PROPOSALS_CREATE = "entities.proposals.create"
    ENTITIES_MERGE_PREVIEW = "entities.merge.preview"
    ENTITIES_MERGE = "entities.merge"
    # Final identity-recovery surface. History is a Principal-scoped read over
    # the authoritative mutation and identity-operation ledgers. Split uses the
    # same two-gate preview/apply shape as merge: the preview persists an exact,
    # expiring plan and the apply consumes it atomically. Both split operations
    # are operator-only identity correction; history grants no authority.
    ENTITIES_IDENTITY_HISTORY = "entities.identity_history"
    ENTITIES_SPLIT_PREVIEW = "entities.split.preview"
    ENTITIES_SPLIT = "entities.split"

    #: `RI-ENT-WP-10`. Five reads over the six Entity-bound record families —
    #: typed names, the organization profile, addresses, communication methods,
    #: project participations and person/organization affiliations — which this
    #: plane has stored since `RI-ENT-WP-02`..`WP-06b` and published through no
    #: capability at all. Every one of the five is a read; none of them appears
    #: in `_WRITE_CAPABILITIES`, `_ADDITIVE_WRITE_CAPABILITIES`, `_OPERATOR_ONLY`
    #: or any other write register, and all five map to `Purpose.ENTITY_READ`.
    #:
    #: **`entities.profile` is a new name rather than a widening of
    #: `entities.context`.** The card that capability returns is a fixed twelve
    #: keys that existing callers parse, and adding collections to it would
    #: change a response every one of them already reads — the compatibility
    #: table classes that as breaking. `entities.context` summarises *who this
    #: is* out of aliases, identifiers, assignments, edges, observations and
    #: memories; `entities.profile` returns *what is recorded about them* out of
    #: the six record families, which is a different set of tables answering a
    #: different question. `D-91`'s test the other way: a caller granted one has
    #: no occasion to hold the other, and neither answer contains the other's.
    #:
    #: **The paged names exist because `entities.profile` is bounded.** The
    #: composite carries a per-collection ceiling and discloses when it hit one,
    #: exactly as the context card does, and it issues no cursor — so a caller
    #: whose entity has more names, addresses, communication methods or
    #: participations than the ceiling admits needs somewhere to go, and these
    #: are it. Each covers one family, keyset-paged on that family's own primary
    #: key. The organization profile has no such name and needs none: it is one
    #: row per entity by construction, and the affiliation families are read
    #: whole within the composite's own bound.
    ENTITIES_PROFILE = "entities.profile"
    ENTITIES_NAMES_LIST = "entities.names.list"
    ENTITIES_ADDRESSES_LIST = "entities.addresses.list"
    ENTITIES_COMMUNICATION_LIST = "entities.communication.list"
    ENTITIES_PARTICIPATIONS_LIST = "entities.participations.list"

    #: `RI-ENT-WP-11`, the write half of the same six record families
    #: `RI-ENT-WP-10` published as reads. `RI-ENT-WP-08` gave every family a
    #: writer and no capability reached one, so the plane could store a typed
    #: name and had no name for recording one. These are the names.
    #:
    #: **Three verbs per family, and the third is never `delete`.** ADR-003
    #: clause 3's frame, the one the directed family already keeps: an addition
    #: appends, a correction is a *supersession* -- a new row, the predecessor
    #: marked superseded -- and a withdrawal is a lifecycle transition that keeps
    #: the row and its history. There is no capability that destroys a name, an
    #: address, a channel, a participation or an affiliation, for the reason
    #: there is no `relationship_memory.delete`.
    #:
    #: **The verb spelling is inconsistent across the five families and is the
    #: accepted contract.** Names supersede where the other four revise, and the
    #: first three families retire where the last two end. That came out of the
    #: source audit that fixed this vocabulary, and normalizing it here would
    #: rename a published capability to make a table look tidy. What matters is
    #: that `supersede` and `revise` are the *same act* -- both reach the
    #: family's `correct_*` verb, both mint a successor row and mark the
    #: predecessor superseded, and neither edits anything in place.
    #:
    #: **There is no `entities.profile.save` and there will not be one.** A
    #: capability that took the whole profile as a field map would be a mass
    #: assignment: one grant able to rewrite every family at once, with no
    #: per-family authority and no `expected_version` for any row it touched.
    #: One narrow name per act is the shape that makes each write refusable on
    #: its own.
    #:
    #: Every one carries an `idempotency_key`, and every correction and
    #: withdrawal carries an `expected_version`. All fifteen are
    #: `Purpose.ENTITY_AUTHORING`, reusing the purpose the directed writes hold
    #: rather than minting one: they write canonical fact about the acting
    #: Principal's own entities, which is exactly what that purpose names.
    #:
    #: Not operator-only, on the argument the directed six make: none of them
    #: widens the scope a later request is evaluated against, which is the
    #: property that puts `sources.enroll` there. Withholding them from a build
    #: that has not enabled the plane -- or has enabled it with writes off -- is
    #: `_ENTITY_CAPABILITIES` and `_ENTITY_WRITE_CAPABILITIES` in
    #: `application.service`.
    ENTITIES_NAMES_ADD = "entities.names.add"
    ENTITIES_NAMES_SUPERSEDE = "entities.names.supersede"
    ENTITIES_NAMES_RETIRE = "entities.names.retire"
    ENTITIES_ADDRESSES_ADD = "entities.addresses.add"
    ENTITIES_ADDRESSES_REVISE = "entities.addresses.revise"
    ENTITIES_ADDRESSES_RETIRE = "entities.addresses.retire"
    ENTITIES_COMMUNICATION_ADD = "entities.communication.add"
    ENTITIES_COMMUNICATION_REVISE = "entities.communication.revise"
    ENTITIES_COMMUNICATION_RETIRE = "entities.communication.retire"

    # The Relationship Memory plane: durable, entity-bound knowledge the user
    # meant to keep. **A family of its own rather than an `entities.update`**,
    # and the naming is a policy decision rather than a style one. These
    # capabilities reach a different record class from entity identity, aliases,
    # assignments and edges, and one grant spanning both would let a client
    # issued authority to correct a misspelled name also read and write private
    # notes about the person. The noun is what makes the sensitive class legible
    # where grants are decided.
    #
    # Eight original read/write capabilities, followed below by the ninth,
    # producer-only capability. Separately, there is no
    # `relationship_memory.delete`: archive is reversible and history is
    # retained, hard deletion is unresolved by ADR-003 and reserved to the
    # operator, and a capability name for it would be the first half of building
    # one.
    #
    # Not operator-only, on the argument `_OPERATOR_ONLY` makes for the capture
    # plane: these write and read content the acting Principal already owns and
    # grant no authority — none of them widens the scope a later request is
    # evaluated against, which is the property that puts `sources.enroll` there.
    # Withholding them from a build that has not enabled the plane is
    # `_RELATIONSHIP_MEMORY_CAPABILITIES` in `application.service`, for the
    # reason the entity comment beside it gives.
    RELATIONSHIP_MEMORY_CREATE = "relationship_memory.create"
    RELATIONSHIP_MEMORY_GET = "relationship_memory.get"
    RELATIONSHIP_MEMORY_LIST = "relationship_memory.list"
    RELATIONSHIP_MEMORY_SEARCH = "relationship_memory.search"
    RELATIONSHIP_MEMORY_HISTORY = "relationship_memory.history"
    RELATIONSHIP_MEMORY_REVISE = "relationship_memory.revise"
    RELATIONSHIP_MEMORY_ARCHIVE = "relationship_memory.archive"
    RELATIONSHIP_MEMORY_RESTORE = "relationship_memory.restore"

    #: The ninth, and it is the producer's and not the user's. Operator §12
    #: keeps `relationship_memory.create` for a person saying "remember this"
    #: and routes everything a rule, a source or a local model derived through
    #: here, where it lands as a candidate awaiting Review and never as an
    #: active memory. Not operator-only, on the argument the eight above are
    #: not: it writes a request about the acting Principal's own subject and
    #: grants nothing. The separation that matters for it is the *purpose*, not
    #: the operator flag — a producer holding this must not thereby hold
    #: `relationship_memory.create`, and `_PERMITTED_PURPOSES` is where that is
    #: decided.
    RELATIONSHIP_MEMORY_PROPOSE = "relationship_memory.propose"


class NativeSourceCapability(StrEnum):
    """Authenticated native-host commands, separate from legacy public transports."""

    DISCOVER = "native_sources.discover"
    CONFIGURE = "native_sources.configure"
    PREFLIGHT = "native_sources.preflight"
    SYNC = "native_sources.sync"
    STATUS = "native_sources.status"
    RETRY = "native_sources.retry"
    RECONCILE = "native_sources.reconcile"
    PAUSE = "native_sources.pause"
    RESUME = "native_sources.resume"
    BACKFILL = "native_sources.backfill"
    DISABLE = "native_sources.disable"


type AuthorizedCapability = Capability | NativeSourceCapability


#: Capabilities restricted to an authenticated operator principal.
#:
#: `sources.enroll` alone, and no capture capability, which is a decision rather
#: than a default (`D-70`). Enrollment **grants authority** — it widens the
#: authorized scope a later request is evaluated against — while a capture
#: creates content the principal already owns and grants nothing. Making capture
#: operator-only would also contradict the canonical direction of travel, where a
#: non-operator device client holds a permitted capture capability.
#:
#: `capture.search` is decided on the same terms and reaches the same answer: it
#: reads rows `capture.read` and `capture.list` already return to the same
#: principal under the same purpose, so restricting the *search* over them while
#: leaving the *read* of them open would restrict nothing and would tell a
#: caller that finding a capture is a more privileged act than opening it.
#:
#: `review.list` and `review.decide` are decided the same way and reach the same
#: answer, and neither belongs here when it arrives. Deciding a review is the
#: most consequential capture-plane act there is, but it grants no authority: it
#: promotes the principal's own proposal about the principal's own capture.
#: Enrollment is operator-only because it *widens* the scope a later request is
#: evaluated against, and a review disposition widens nothing. Under
#: `P00-OD-010` there is one local principal in any case, so making it
#: operator-only would restrict nobody while implying an authority boundary this
#: build cannot draw.
#:
#: `knowledge.reveal` is decided last and reaches the same answer for the
#: narrowest reason: it grants nothing and reads nothing a permitted capability
#: does not already return. Restricting the *explanation* of a record while
#: leaving the record itself readable would tell a caller that understanding
#: what it is looking at is more privileged than looking at it.
#:
#: **`entities.merge.preview` and `entities.merge` are the first knowledge-plane
#: members, and the paragraphs above are the reason rather than an exception to
#: it.** Every argument that kept capture, review, continuity, documents, tasks,
#: commitments, entities and Relationship Memory out of this set turns on one
#: question: does the capability *widen the scope a later request is evaluated
#: against*? A capture creates content the Principal already owns. A review
#: disposition promotes the Principal's own proposal. A merge does something
#: neither does — after it, every alias, identifier, assignment, edge,
#: observation, proposal, review case and memory that named a merged-away entity
#: is reached through the survivor, so a grant issued before the merge returns
#: records it did not return before. That is the same property `sources.enroll`
#: has, and operator §24 states the conclusion independently: neither
#: `relationship_standard`, nor `relationship_reviewer` merely because a reviewer
#: can decide proposals, nor `relationship_producer`, nor an ordinary ChatLLM may
#: hold them.
#:
#: The preview is here beside the apply and not left out as "only a read". It
#: reads the exact identities of two people and the whole affected world of a
#: proposed merge, which is the disclosure the apply's authority exists to
#: protect; an operator boundary that admitted the inspection and refused only
#: the act would be a boundary on the least sensitive half.
_OPERATOR_ONLY: frozenset[AuthorizedCapability] = frozenset(
    {
        Capability.SOURCES_ENROLL,
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
        NativeSourceCapability.CONFIGURE,
        NativeSourceCapability.PREFLIGHT,
        NativeSourceCapability.SYNC,
        NativeSourceCapability.RETRY,
        NativeSourceCapability.RECONCILE,
        NativeSourceCapability.PAUSE,
        NativeSourceCapability.RESUME,
        NativeSourceCapability.BACKFILL,
        NativeSourceCapability.DISABLE,
    }
)

_PERMITTED_PURPOSES: Mapping[AuthorizedCapability, frozenset[Purpose]] = MappingProxyType(
    {
        Capability.CAPABILITIES_GET: frozenset(
            {Purpose.STATUS_OBSERVATION, Purpose.SECURITY_VALIDATION}
        ),
        Capability.SOURCES_LIST: frozenset({Purpose.SOURCE_INSPECTION}),
        Capability.SOURCES_METADATA: frozenset({Purpose.SOURCE_INSPECTION}),
        Capability.SOURCES_FETCH: frozenset(
            {Purpose.SOURCE_INSPECTION, Purpose.CONTENT_EXTRACTION}
        ),
        Capability.SOURCES_STATUS: frozenset({Purpose.STATUS_OBSERVATION}),
        Capability.SOURCES_ENROLL: frozenset({Purpose.BOUNDED_ENROLLMENT}),
        Capability.KNOWLEDGE_SEARCH: frozenset({Purpose.KNOWLEDGE_SEARCH}),
        Capability.KNOWLEDGE_READ: frozenset({Purpose.KNOWLEDGE_READ}),
        # `CAPTURE_REVIEW` rather than a purpose of its own, and rather than
        # `KNOWLEDGE_READ` despite the capability's name. The test is `D-91`'s:
        # does the reuse widen the grant? Reveal reads exactly the rows
        # `capture.read`, `capture.list`, `capture.search` and `review.list`
        # already return to the same Principal, and returns no capture text at
        # all — spans carry offsets, a basis and a digest, never a quote — so it
        # widens nothing. `KNOWLEDGE_READ` would be the escalation this module
        # refuses in the other direction: that purpose is the *extraction*
        # plane's, and admitting a capture-plane traversal under it would make a
        # grant issued for one plane reach the other.
        Capability.KNOWLEDGE_REVEAL: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.CAPTURE_CREATE: frozenset({Purpose.CAPTURE_AUTHORING}),
        Capability.CAPTURE_REVISE: frozenset({Purpose.CAPTURE_AUTHORING}),
        Capability.CAPTURE_READ: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.CAPTURE_LIST: frozenset({Purpose.CAPTURE_REVIEW}),
        # `CAPTURE_REVIEW` reused rather than a `capture_search` purpose added
        # (`D-91`). Searching captures is a read of the same rows under the same
        # authority as `capture.read` and `capture.list`, so a purpose of its own
        # would separate nothing — it would map to exactly one capability — while
        # costing another frozen-constraint `ALTER` on `purpose_is_known`.
        Capability.CAPTURE_SEARCH: frozenset({Purpose.CAPTURE_REVIEW}),
        # `review.list` maps to `CAPTURE_REVIEW` and `review.decide` to a purpose
        # of its own; both land with the capabilities themselves, for the reason
        # the enum above records.
        Capability.REVIEW_LIST: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.REVIEW_DECIDE: frozenset({Purpose.REVIEW_DISPOSITION}),
        # The three continuity reads map to `CAPTURE_REVIEW`. **No purpose is
        # widened, and the residual is stated rather than smoothed over.**
        #
        # `D-91`'s test asks whether reuse widens the grant. Honestly answered:
        # partly. What the three reads return is the accepted end of the same
        # chain `capture_review` already covers — a Situation, a Project, a
        # Commitment is what a promoted proposal becomes — and they promote
        # nothing, write nothing, grant nothing, and return only the acting
        # Principal's own *accepted* rows. But `capture_review` did not reach the
        # continuity tables before this package, and after it a grant issued for
        # reviewing captures reaches them. That is the cost, and it is paid for
        # the reason the alternative is worse in both directions: a
        # `continuity_read` purpose would map one-to-three and separate nothing
        # any authority in this build can act on (under `P00-OD-010` there is one
        # local Principal), while reusing `KNOWLEDGE_READ` would be the
        # escalation `purpose.py` refuses — that purpose is the *extraction*
        # plane's and is scoped by enrollment, and continuity belongs to none.
        Capability.CONTINUITY_PULSE: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.CONTINUITY_SITUATIONS: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.CONTINUITY_PROJECTS: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.CONTINUITY_PROJECTS_CREATE: frozenset({Purpose.CONTINUITY_AUTHORING}),
        Capability.CONTINUITY_SITUATIONS_CREATE: frozenset({Purpose.CONTINUITY_AUTHORING}),
        Capability.CONTINUITY_TASKS_CREATE: frozenset({Purpose.CONTINUITY_AUTHORING}),
        # `STATUS_OBSERVATION`, reused, and the residual is stated rather than
        # smoothed over. `D-91`'s test asks whether the reuse widens the grant.
        # Honestly answered: partly. Corpus coverage is a status observation —
        # how far processing has got, over the extraction plane — which is
        # exactly what that purpose already admits for `sources.status`. But
        # `sources.status` answers about one named subject and this answers about
        # every enrollment the Principal holds plus the objects outside them all,
        # so after this package a grant issued to observe status reaches a wider
        # row set than it did.
        #
        # It is paid because both alternatives are worse. A `corpus_observation`
        # purpose would map one-to-one, separate nothing any authority in this
        # build can act on — under `P00-OD-010` there is one local Principal —
        # and cost a frozen-constraint `ALTER` on `purpose_is_known` for a
        # distinction nobody could enforce. `KNOWLEDGE_SEARCH` would be the
        # escalation this module refuses in the other direction: that purpose is
        # bound to the enrollment a search names, and admitting a corpus-wide read
        # under it would make a grant issued to search one scope reach every scope.
        Capability.KNOWLEDGE_COVERAGE: frozenset({Purpose.STATUS_OBSERVATION}),
        # The managed-document plane maps to a purpose pair of its own, and neither
        # is a reuse. `D-91`'s test asks whether reuse would widen the grant, and
        # here it plainly would in both directions: `capture_authoring` is
        # ADR-003's append-only user-authored plane and admitting a managed write
        # under it would let a grant issued to write a Quick Note write a document
        # into the managed root, while `knowledge_read` is the extraction plane's
        # and admitting a managed read under it would let a grant issued to read
        # an extracted record return a document body. Different tables, different
        # custody, different bytes.
        #
        # **Writing and reading are separated, and the transitions travel with
        # the writes.** A purpose wide enough to cover both is a purpose that
        # grants both, which is the rule `purpose.py` states for the capture
        # plane. `archive` and `restore` sit under `document_authoring` rather
        # than under a purpose of their own: they write, they touch only the acting
        # Principal's own documents, they destroy nothing and each undoes the
        # other, so a further purpose would map one-to-two, separate nothing any
        # authority in this build can act on — under `P00-OD-010` there is one
        # local Principal — and cost a third frozen-constraint literal. The
        # residual is stated rather than smoothed over: a grant issued to write a
        # document also reaches the reversible lifecycle state of every document
        # that Principal holds. It does not reach a *read* of any of them, which
        # is the separation that matters, and it reaches no other plane at all.
        Capability.DOCUMENTS_CREATE: frozenset({Purpose.DOCUMENT_AUTHORING}),
        Capability.DOCUMENTS_REVISE: frozenset({Purpose.DOCUMENT_AUTHORING}),
        Capability.DOCUMENTS_ARCHIVE: frozenset({Purpose.DOCUMENT_AUTHORING}),
        Capability.DOCUMENTS_RESTORE: frozenset({Purpose.DOCUMENT_AUTHORING}),
        Capability.DOCUMENTS_READ: frozenset({Purpose.DOCUMENT_READ}),
        Capability.DOCUMENTS_LIST: frozenset({Purpose.DOCUMENT_READ}),
        # The four `tasks.` reads map to one purpose of their own, `task_read`,
        # rather than to a reuse. `D-91`'s test is whether reuse would widen the
        # grant, and here it would in every direction available: `capture_review`
        # is the capture plane's, scoped to captures and to the continuity rows
        # that plane's own proposals promote into, and a task is promoted by no
        # capture-plane review; `document_read` is the managed-document plane's
        # own custody, over `knowledge.managed_documents` and its bytes, and a
        # task is neither a document nor written by that plane; `knowledge_read`
        # is the extraction plane's and scoped by an enrollment a task has none
        # of. One purpose for all four rather than one apiece, for the reason
        # `document_authoring`/`document_read` are a pair and not six: `read`,
        # `list`, `search` and `history` are four different queries over the
        # acting Principal's own rows and no write, so a purpose wide enough to
        # cover any one of them is wide enough to cover the rest without
        # widening what a grant reaches.
        Capability.TASKS_READ: frozenset({Purpose.TASK_READ}),
        Capability.TASKS_LIST: frozenset({Purpose.TASK_READ}),
        Capability.TASKS_SEARCH: frozenset({Purpose.TASK_READ}),
        Capability.TASKS_HISTORY: frozenset({Purpose.TASK_READ}),
        # The five `tasks.` write capabilities map to `task_authoring`, and all
        # five are covered by one purpose for the reason `document_authoring`
        # covers `documents.create`, `documents.revise`, `documents.archive`,
        # and `documents.restore`: they are all writes to the same partition
        # under the same principal, and a grant issued to create a task has no
        # reason to be narrower than one issued to update or transition it. The
        # two-phase bulk operation (`bulk_preview` and `bulk_confirm`) is
        # covered by the same purpose because both are writes — preview is a
        # write of the bulk operation's state, and confirm is a write of the
        # task mutations themselves — and a grant issued to preview changes
        # should not also authorize applying them without the caller's explicit
        # confirmation, so they are separate capabilities, but they are not
        # separate purposes.
        Capability.TASKS_CREATE: frozenset({Purpose.TASK_AUTHORING}),
        Capability.TASKS_UPDATE: frozenset({Purpose.TASK_AUTHORING}),
        Capability.TASKS_TRANSITION: frozenset({Purpose.TASK_AUTHORING}),
        Capability.TASKS_BULK_PREVIEW: frozenset({Purpose.TASK_AUTHORING}),
        Capability.TASKS_BULK_CONFIRM: frozenset({Purpose.TASK_AUTHORING}),
        # The Commitment plane's purpose pair (WP-TM-05): `commitment_read`
        # covers the three reads (`commitments.read`, `commitments.list`,
        # and the derived `commitments.waiting_on`), and `commitment_authoring`
        # covers the two writes (`commitments.create`, `commitments.close`),
        # for the identical reason the task plane's own pair is split.
        Capability.COMMITMENTS_READ: frozenset({Purpose.COMMITMENT_READ}),
        Capability.COMMITMENTS_LIST: frozenset({Purpose.COMMITMENT_READ}),
        Capability.COMMITMENTS_SEARCH: frozenset({Purpose.COMMITMENT_READ}),
        Capability.COMMITMENTS_HISTORY: frozenset({Purpose.COMMITMENT_READ}),
        Capability.COMMITMENTS_WAITING_ON: frozenset({Purpose.COMMITMENT_READ}),
        Capability.COMMITMENTS_CREATE: frozenset({Purpose.COMMITMENT_AUTHORING}),
        Capability.COMMITMENTS_UPDATE: frozenset({Purpose.COMMITMENT_AUTHORING}),
        Capability.COMMITMENTS_CLOSE: frozenset({Purpose.COMMITMENT_AUTHORING}),
        # A purpose of its own, not a reuse of `KNOWLEDGE_SEARCH`. The mapping
        # comment sits with the member: `knowledge.search` is one enrollment's
        # extraction plane, and this capability is a cross-plane assembly.
        Capability.CONTEXT_PREPARE: frozenset({Purpose.CONTEXT_PREPARATION}),
        # A purpose of its own, not a reuse of `CAPTURE_AUTHORING`,
        # `CONTINUITY_AUTHORING`, or `REVIEW_DISPOSITION`. The mapping comment
        # sits with the member: those write notes, projects, and promotions.
        Capability.CONTEXT_FEEDBACK: frozenset({Purpose.CONTEXT_PREFERENCE}),
        # Matching purposes, not a reuse of `knowledge_search` or
        # `review_disposition`. The mapping comment sits with the members.
        Capability.GOODNOTES_WORK: frozenset({Purpose.GOODNOTES_WORK}),
        Capability.GOODNOTES_PROPOSE: frozenset({Purpose.GOODNOTES_PROPOSAL}),
        Capability.GOODNOTES_CONTENT: frozenset({Purpose.GOODNOTES_CONTENT}),
        Capability.GSQS_START: frozenset({Purpose.GSQS_B0_EXECUTION}),
        Capability.GSQS_STATUS: frozenset({Purpose.GSQS_B0_OBSERVATION}),
        Capability.REPORTS_BEGIN_CYCLE: frozenset({Purpose.REPORT_AUTHORING}),
        Capability.REPORTS_COMMIT: frozenset({Purpose.REPORT_AUTHORING}),
        Capability.REPORTS_RECORD_RUN_STATE: frozenset({Purpose.REPORT_AUTHORING}),
        Capability.REPORTS_READ: frozenset({Purpose.REPORT_READ}),
        Capability.REPORTS_LATEST: frozenset({Purpose.REPORT_READ}),
        Capability.REPORTS_LIST: frozenset({Purpose.REPORT_READ}),
        Capability.REPORTS_SEARCH: frozenset({Purpose.REPORT_READ}),
        Capability.REPORTS_RESOLVE_SET: frozenset({Purpose.REPORT_READ}),
        Capability.ENTITIES_SEARCH: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_UNRESOLVED_MENTIONS: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_GET: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_RESOLVE: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_CONTEXT: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_RELATIONSHIPS: frozenset({Purpose.ENTITY_READ}),
        # WP-RI-A-02. The two paged child listings join the read purpose; the
        # ten writes take the plane's new one. The argument for the split is
        # beside `Purpose.ENTITY_AUTHORING` and is the one this module makes for
        # every other plane that reads and writes the same rows.
        Capability.ENTITIES_IDENTIFIERS_LIST: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_ALIASES_LIST: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_CREATE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_UPDATE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_ARCHIVE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_RESTORE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_IDENTIFIERS_BIND: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_IDENTIFIERS_RETIRE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_ALIASES_ADD: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_ALIASES_RETIRE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_ALIASES_SUPERSEDE: frozenset({Purpose.ENTITY_AUTHORING}),
        # `entities.assignments.list` reuses `ENTITY_READ`, and the reuse widens
        # nothing: it returns the assignment rows `entities.context` already
        # assembles into a card and `entities.resolve` already corroborates
        # against, for the same Principal over the same table. A read purpose of
        # its own would map to exactly one capability and separate nothing.
        Capability.ENTITIES_ASSIGNMENTS_LIST: frozenset({Purpose.ENTITY_READ}),
        # The six directed writes, all under `ENTITY_AUTHORING` and none of them
        # under `ENTITY_READ`. The separation is the rule `purpose.py` states
        # for the capture plane: a purpose wide enough to cover writing and
        # reading is a purpose that grants both, and a grant issued so an
        # assistant may look up who someone reports to must not also let it
        # assert that they do.
        #
        # **The `end` transitions travel with the writes rather than taking a
        # purpose of their own**, exactly as `documents.archive` and
        # `relationship_memory.archive` do. Ending an assignment is the same
        # authority over the same row as revising it -- it is how a correction to
        # a record's *identity* is expressed, since type, endpoints and scope are
        # not editable in place -- so splitting it off would separate a pair of
        # acts that are always held together.
        Capability.ENTITIES_ASSIGNMENTS_CREATE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_ASSIGNMENTS_REVISE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_ASSIGNMENTS_END: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_RELATIONSHIPS_CREATE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_RELATIONSHIPS_REVISE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_RELATIONSHIPS_END: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_OBSERVATIONS_LIST: frozenset({Purpose.ENTITY_READ}),
        # The two writes, each under exactly one purpose. `entities.observe` is
        # deliberately *not* permitted under `ENTITY_AUTHORING`: an ingest path
        # writes evidence continuously and must never be able to decide an
        # identity, and a capability permitted under both purposes would be
        # reachable by whichever grant a caller happened to hold.
        Capability.ENTITIES_OBSERVE: frozenset({Purpose.ENTITY_OBSERVATION_INGEST}),
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE: frozenset({Purpose.ENTITY_AUTHORING}),
        # One purpose each, and none of the three reuses `entity_authoring`.
        # `entity_proposal` is the producer's, and the pairing is what makes
        # operator §16's "a producer may not self-promote" a property of the
        # grant: a client granted this purpose can invoke exactly one capability
        # with it, and that capability writes a request.
        Capability.ENTITIES_PROPOSALS_CREATE: frozenset({Purpose.ENTITY_PROPOSAL}),
        # All four merge/split preview/apply capabilities take the same purpose
        # and only that purpose. The coupling is deliberate; `purpose.py` argues
        # it, and `_WRITE_CAPABILITIES` below records the persistence behaviour
        # that makes both previews writes.
        Capability.ENTITIES_MERGE_PREVIEW: frozenset({Purpose.ENTITY_IDENTITY_CORRECTION}),
        Capability.ENTITIES_MERGE: frozenset({Purpose.ENTITY_IDENTITY_CORRECTION}),
        Capability.ENTITIES_IDENTITY_HISTORY: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_SPLIT_PREVIEW: frozenset({Purpose.ENTITY_IDENTITY_CORRECTION}),
        Capability.ENTITIES_SPLIT: frozenset({Purpose.ENTITY_IDENTITY_CORRECTION}),
        # `RI-ENT-WP-10`'s five reads, all under `ENTITY_READ` and no new
        # purpose. The reuse widens nothing: they return rows of the same
        # Principal's own entities that `entities.context` already summarises
        # and `entities.resolve` already corroborates against, and a read
        # purpose of its own would map to exactly these five and separate them
        # from nothing. None of them is permitted under `ENTITY_AUTHORING`,
        # which is what keeps them out of `_ENTITY_WRITE_CAPABILITIES` --
        # `tests/contract/test_entity_write_gate.py` derives that set from this
        # mapping, so a read admitted under a write purpose here would be a
        # write gate this plane never intended.
        Capability.ENTITIES_PROFILE: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_NAMES_LIST: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_ADDRESSES_LIST: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_COMMUNICATION_LIST: frozenset({Purpose.ENTITY_READ}),
        Capability.ENTITIES_PARTICIPATIONS_LIST: frozenset({Purpose.ENTITY_READ}),
        # `RI-ENT-WP-11`'s record-family writes, all under `ENTITY_AUTHORING`
        # and none under `ENTITY_READ`. The separation is the rule `purpose.py`
        # states and the directed six already keep: a purpose wide enough to
        # cover writing and reading is a purpose that grants both, and a grant
        # issued so an assistant may read somebody's recorded addresses must not
        # also let it record one.
        #
        # **Reusing `ENTITY_AUTHORING` rather than minting a purpose per family
        # widens nothing.** A purpose is the authority a grant carries, and
        # these write canonical fact about the acting Principal's own entities
        # -- the same act, on neighbouring tables, that `entities.update` and
        # the directed writes already perform under it. A purpose of its own
        # would map to exactly these fifteen and separate them from nothing a
        # holder of `ENTITY_AUTHORING` cannot already do.
        #
        # **The retire/end transitions travel with the writes**, exactly as the
        # directed `end` names and `documents.archive` do. Withdrawing a name is
        # the same authority over the same row as superseding it, so splitting
        # it off would separate a pair of acts always held together.
        Capability.ENTITIES_NAMES_ADD: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_NAMES_SUPERSEDE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_NAMES_RETIRE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_ADDRESSES_ADD: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_ADDRESSES_REVISE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_ADDRESSES_RETIRE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_COMMUNICATION_ADD: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_COMMUNICATION_REVISE: frozenset({Purpose.ENTITY_AUTHORING}),
        Capability.ENTITIES_COMMUNICATION_RETIRE: frozenset({Purpose.ENTITY_AUTHORING}),
        # The Relationship Memory pair, and neither is a reuse. `D-91`'s test
        # asks whether reuse would widen the grant, and here it plainly would in
        # both directions: `entity_read` is the identity plane — aliases,
        # identifiers, assignments, edges — and admitting a memory read under it
        # would let a grant issued to learn who someone *is* also return what the
        # user privately wrote about them; `capture_authoring` is ADR-003's
        # append-only capture plane and admitting a memory write under it would
        # let a grant issued to store a Quick Note write an entity-bound
        # assertion about another person.
        #
        # **Writing and reading are separated, and the lifecycle transitions
        # travel with the writes.** A purpose wide enough to cover both is a
        # purpose that grants both, which is the rule `purpose.py` states for the
        # capture plane. `archive` and `restore` sit under
        # `relationship_memory_authoring` rather than under a purpose of their
        # own, exactly as `documents.archive`/`documents.restore` sit under
        # `document_authoring`: they write, they touch only the acting
        # Principal's own memories, they destroy nothing and each undoes the
        # other. The residual is stated rather than smoothed over: a grant issued
        # to write a memory also reaches the reversible lifecycle state of every
        # memory that Principal holds. It does not reach a *read* of any of them,
        # which is the separation that matters here more than anywhere else in
        # this schema.
        Capability.RELATIONSHIP_MEMORY_CREATE: frozenset({Purpose.RELATIONSHIP_MEMORY_AUTHORING}),
        Capability.RELATIONSHIP_MEMORY_REVISE: frozenset({Purpose.RELATIONSHIP_MEMORY_AUTHORING}),
        Capability.RELATIONSHIP_MEMORY_ARCHIVE: frozenset({Purpose.RELATIONSHIP_MEMORY_AUTHORING}),
        Capability.RELATIONSHIP_MEMORY_RESTORE: frozenset({Purpose.RELATIONSHIP_MEMORY_AUTHORING}),
        Capability.RELATIONSHIP_MEMORY_GET: frozenset({Purpose.RELATIONSHIP_MEMORY_READ}),
        Capability.RELATIONSHIP_MEMORY_LIST: frozenset({Purpose.RELATIONSHIP_MEMORY_READ}),
        Capability.RELATIONSHIP_MEMORY_SEARCH: frozenset({Purpose.RELATIONSHIP_MEMORY_READ}),
        Capability.RELATIONSHIP_MEMORY_HISTORY: frozenset({Purpose.RELATIONSHIP_MEMORY_READ}),
        # The producer path, mapped to the producer purpose and to nothing else.
        # A grant issued so a rule can raise candidates reaches this capability
        # and neither `relationship_memory.create` nor any of the four reads.
        Capability.RELATIONSHIP_MEMORY_PROPOSE: frozenset({Purpose.RELATIONSHIP_MEMORY_PROPOSAL}),
        NativeSourceCapability.DISCOVER: frozenset({Purpose.SOURCE_INSPECTION}),
        NativeSourceCapability.CONFIGURE: frozenset({Purpose.BOUNDED_ENROLLMENT}),
        NativeSourceCapability.PREFLIGHT: frozenset({Purpose.SECURITY_VALIDATION}),
        NativeSourceCapability.SYNC: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.STATUS: frozenset({Purpose.STATUS_OBSERVATION}),
        NativeSourceCapability.RETRY: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.RECONCILE: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.PAUSE: frozenset({Purpose.BOUNDED_ENROLLMENT}),
        NativeSourceCapability.RESUME: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.BACKFILL: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.DISABLE: frozenset({Purpose.BOUNDED_ENROLLMENT}),
    }
)

# Public capabilities that can change product-owned state. This is operation
# truth rather than an authorization-purpose shortcut.
_WRITE_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.SOURCES_ENROLL,
        Capability.CAPTURE_CREATE,
        Capability.CAPTURE_REVISE,
        Capability.REVIEW_DECIDE,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Capability.CONTINUITY_SITUATIONS_CREATE,
        Capability.CONTINUITY_TASKS_CREATE,
        Capability.DOCUMENTS_CREATE,
        Capability.DOCUMENTS_REVISE,
        Capability.DOCUMENTS_ARCHIVE,
        Capability.DOCUMENTS_RESTORE,
        Capability.TASKS_CREATE,
        Capability.TASKS_UPDATE,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_BULK_PREVIEW,
        Capability.TASKS_BULK_CONFIRM,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_UPDATE,
        Capability.COMMITMENTS_CLOSE,
        Capability.CONTEXT_FEEDBACK,
        Capability.GOODNOTES_PROPOSE,
        Capability.GSQS_START,
        Capability.REPORTS_BEGIN_CYCLE,
        Capability.REPORTS_COMMIT,
        Capability.REPORTS_RECORD_RUN_STATE,
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_UPDATE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        # Phase B's four, each classified from what it actually persists rather
        # than from what it is called (operator §25).
        #
        # `entities.proposals.create` inserts a row into
        # `knowledge.entity_proposals` (and its evidence links) through
        # `EntityGovernanceService.propose`. It is a write of a *request* and not
        # of canonical fact, and it is still a write.
        Capability.ENTITIES_PROPOSALS_CREATE,
        # `relationship_memory.propose` inserts a candidate and its evidence
        # rows. Same shape, other plane.
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        # **`entities.merge.preview` is a write, and this is the one people will
        # want to argue with.** It mutates no canonical record — that is what
        # makes it additive below — but it INSERTs a durable row into
        # `knowledge.entity_identity_previews` carrying a preview digest, a
        # conflict digest, an expiry and a consumption state, and
        # `entities.merge` later UPDATEs that row's `consumed_at`. A control row
        # a second request reads and consumes is product-owned state, so calling
        # this a read would be an annotation that contradicts the transaction.
        # `tasks.bulk_preview` is the established precedent and is here for the
        # same reason.
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT,
        # `RI-ENT-WP-11`'s record-family writes. Each inserts, supersedes or
        # retires a row in one of the five Entity-bound families and appends the
        # mutation-ledger row that accounts for it, so every one is a write by
        # what it persists rather than by what it is called (operator §25).
        Capability.ENTITIES_NAMES_ADD,
        Capability.ENTITIES_NAMES_SUPERSEDE,
        Capability.ENTITIES_NAMES_RETIRE,
        Capability.ENTITIES_ADDRESSES_ADD,
        Capability.ENTITIES_ADDRESSES_REVISE,
        Capability.ENTITIES_ADDRESSES_RETIRE,
        Capability.ENTITIES_COMMUNICATION_ADD,
        Capability.ENTITIES_COMMUNICATION_REVISE,
        Capability.ENTITIES_COMMUNICATION_RETIRE,
    }
)

# Writes that only add a new durable record and do not replace, transition,
# supersede, archive, restore, promote, or otherwise change an existing state.
_ADDITIVE_WRITE_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.SOURCES_ENROLL,
        Capability.CAPTURE_CREATE,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Capability.CONTINUITY_SITUATIONS_CREATE,
        Capability.CONTINUITY_TASKS_CREATE,
        Capability.DOCUMENTS_CREATE,
        Capability.TASKS_CREATE,
        Capability.TASKS_BULK_PREVIEW,
        Capability.COMMITMENTS_CREATE,
        Capability.GOODNOTES_PROPOSE,
        Capability.GSQS_START,
        Capability.REPORTS_BEGIN_CYCLE,
        Capability.REPORTS_RECORD_RUN_STATE,
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_OBSERVE,
        # Three of Phase B's four add and never change. The two producer paths
        # only insert: an open-equivalent repeat of `entities.proposals.create`
        # returns the proposal that is already open and writes nothing, and
        # `relationship_memory.propose` cannot reach an existing record at all.
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        # `entities.merge.preview` creates a control row and mutates no
        # canonical record — proved rather than asserted by the preview refusal
        # tests, which assert `entities`, `entity_aliases` and their neighbours
        # are untouched after one.
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_SPLIT_PREVIEW,
        # `entities.merge` is deliberately absent: it redirects entities,
        # reparents and coalesces children, supersedes self-edges and invalidates
        # dependent proposals. It is the destructive half of this plane.
        #
        # `RI-ENT-WP-11`: exactly the `add`/`create` third of the fifteen. Each
        # of those inserts one new row in its family and reaches no existing one
        # -- no predecessor is marked, no version is advanced, no state moves.
        #
        # **The `supersede`/`revise`/`retire`/`end` names are deliberately
        # absent, and that is what `is_destructive_capability` reads.** A
        # correction is *two* writes: it mints the successor and marks the
        # predecessor SUPERSEDED, so it changes a record that already existed.
        # A retirement moves a live row to RETIRED and releases whatever
        # preferred or open-ended slot it held. Calling either additive would
        # publish a `readOnlyHint`-adjacent annotation that contradicts the
        # transaction, which is the same reading that keeps `entities.merge` out.
        Capability.ENTITIES_NAMES_ADD,
        Capability.ENTITIES_ADDRESSES_ADD,
        Capability.ENTITIES_COMMUNICATION_ADD,
    }
)


def is_operator_only(capability: AuthorizedCapability) -> bool:
    """Return whether `capability` requires an authenticated operator."""
    return capability in _OPERATOR_ONLY


def is_write_capability(capability: Capability) -> bool:
    """Return whether a public capability can change product-owned state."""
    return capability in _WRITE_CAPABILITIES


def is_destructive_capability(capability: Capability) -> bool:
    """Return whether a public write can make a non-additive state change."""
    return capability in _WRITE_CAPABILITIES - _ADDITIVE_WRITE_CAPABILITIES


def permitted_purposes(capability: AuthorizedCapability) -> frozenset[Purpose]:
    """Return the purposes that may invoke `capability`.

    An unmapped capability yields the empty set, so policy denies it.
    """
    return _PERMITTED_PURPOSES.get(capability, frozenset())
