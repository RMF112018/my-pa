# What the slice does not do

The limitations of the MCV vertical slice as it stands, stated at or
slightly below what has been demonstrated.

**This document was headed "the read-only slice" until 2026-08-03.** WP-6 added
the user-authored capture plane, which writes — so the slice is no longer
read-only and saying it was would be the first false claim on the page. What is
still read-only is every path to a **source**: `ADR-003` makes a capture a
product-owned record, a third authority class that is neither a source-system
write nor a managed-document write, and it grants the read-only source-provider
port no write method. Limitation 10 is where that is stated and now measured
from two ends.

**Every limitation below cites the evidence that bounds it**, and
`tests/architecture/test_limitations_cite_evidence.py` parses this file and
applies three rules: each cited path exists, each cited test resolves to a real
test function, and — the rule that makes the first two honest — **no citation
naming a real repository artifact escapes both**. That is what makes this
document non-aspirational mechanically rather than by review: a limitation whose
evidence is gone fails a test rather than quietly becoming a claim about nothing.

The third rule is there because the first two silently did not hold. At
`83a7c6c` the classifier admitted only top-level *directories*, so the three
repository-root files cited here — `PHASE-00-OPEN-DECISION-LEDGER.md`,
`pyproject.toml` and `AGENTS.md` — matched no rule and were asserted by nothing,
while this preamble said each cited path was checked. A citation nothing checks
reads exactly like one that passed.

**What "demonstrated" means here.** The slice was measured end to end by WP-5A —
9 `e2e` tests and 4 `recovery` tests, **13 of 2489 collected at `bcdbf6d`** — and
the operator sequence was executed and transcribed in
`ops/runbooks/end-to-end-operations.md`. *Bound 2026-08-03: that runbook's
transcripts span two runs — steps 1–2 at head `1a4c9e77b2d5`, steps 3–10 carried
from `08e7c81` at head `af3d35efb9c0` — and its own provenance table says which
is which. This document's rule at the top of the file, that every count is bound
to the commit it was taken at, applies to a cited transcript too: an unbound
citation into a mixed-provenance document inherits the ambiguity.* Nothing below
is derived from a design document. Where the evidence is a measurement rather than a test, the
measurement is named.

**Every count here is bound to the commit it was taken at, inline.** An unbound
count is one that has already rotted and cannot be told from one that has not.
This sentence read "13 of 2507 collected" until it was corrected: `2507` was the
total at `81b4622`, an intermediate commit one before this document was written,
and it was never the total anywhere a reader could check. The 9 and the 4 were
right. Counts about the slice as WP-5A left it are bound to `bcdbf6d`; counts
about a measurement taken for this document name the database and the date.

---

## 1. Authentication is implemented; live Entra activation is not proven

The local gateway still binds `127.0.0.1` and configures either an explicit
`local_operator` mode or an Entra bearer-verification mode. The web BFF now has a
Node-only Entra authorization-code + PKCE start/callback/session path. It checks
state and nonce, derives identity from MSAL-validated claims, keeps the access
token in the server session registry, and forwards it only from server to
gateway. No browser request or payload supplies a Principal or bearer.

What remains unproven is live activation: there is no repository credential,
tenant registration, public ingress, TLS termination, or live-tenant test. The
authorization-code protocol is tested with an injected synthetic MSAL result;
the Python verifier is tested with synthetic signed JWTs. Do not turn either
into a claim that a tenant is configured or production-ready.

Evidence: `apps/gateway.py`, `src/my_pa/bootstrap/gateway.py`,
`web/src/lib/auth/entra-code-flow.ts`,
`web/src/lib/auth/entra-session.test.ts`,
`tests/security/test_entra_authentication.py`.

## 2. Multi-principal runtime wiring exists; live tenant operation remains unproven

**Rewritten 2026-08-05 (WP-03, `PKL-MYPA-D-WP03-001`).** This limitation was
headed "ownership survives only as long as the serving process", and that was
true when it was written: `local_principal()` issued a fresh principal
identifier per composition, so three CLI processes were three principals and a
gateway restart was a new one (measured 2026-08-03 and transcribed in
`ops/runbooks/end-to-end-operations.md`; its paragraph carries the same dated
correction). WP-03 dissolved that premise rather than working around it:
`local_principal()` now derives its identifier from the fixed
`LOCAL_OPERATOR_UUID` (`domain/identity/binding.py`), so every composition — a
CLI invocation, a gateway process, a gateway process after a restart — acts as
**one** durable local operator. `tests/capture/test_owner_is_the_partition.py`
composes two runtimes over one database and asserts the identifiers are equal
and that the second runtime revises and reads what the first wrote.

No caller can supply the acting identity: the envelope's `principal_id` remains
correlation input (`contracts/v1/envelope.py`, `application/service.py`),
`apps/cli/invoke.py` refuses a `--principal` option, and a capture admission
whose payload names a principal is refused. In Entra mode identity instead
arrives through the separately validated bearer boundary.

**Captures are now owner-scoped.** `capture.read`, `capture.list`,
`capture.search` and the revise path of `capture.create` resolve against the
authenticated principal's own partition
(`infrastructure/persistence/capture.py`, `capture_search.py`), a foreign
capture answers exactly what a nonexistent one answers, and the idempotency
key's collision domain is per principal (revision `e7f3a9c2d514`). `D-72` —
owner recorded, never enforced — is superseded. The former text of this
limitation argued that adding the owner check would make `QC-AC-013` unprovable
across processes; that was true only while the owner died with its process, and
the durable binding is what made both halves hold at once.

**What changed in the remediation candidate.** In Entra mode the gateway derives
the acting Principal from a validated `(tid, oid)` token and the trusted worker
consumes the Principal already stamped on each queue row instead of binding the
process to `local_principal`. Local mode remains fixed to the durable local
operator. Cross-principal reads remain partitioned, and the worker has no CLI or
request argument that can name a partition.

**What still blocks:** no live tenant credential or personal data has exercised
this chain. Production registration and activation are operator-gated.

Recorded as `D-67` and `D-72` in `docs/plans/mcv-completion-plan.md`, both now
superseded by `PKL-MYPA-D-WP03-001` (`docs/decisions/ADR-005-principal-partitioned-capture.md`).

Evidence: `src/my_pa/bootstrap/gateway.py`,
`src/my_pa/domain/identity/binding.py`,
`src/my_pa/infrastructure/persistence/capture.py`,
`tests/capture/test_owner_is_the_partition.py::test_a_capture_created_by_one_runtime_is_revised_and_read_by_another`,
`tests/security/test_cross_principal_capture_isolation.py`,
`tests/concurrency/test_worker_lease_loop.py::test_entra_worker_consumes_rows_for_distinct_stored_principals_without_rebinding`,
`ops/runbooks/end-to-end-operations.md`.

## 3. The corpus is four synthetic objects, and nothing has been proven wider

Every measurement in this repository was taken over `fixtures/mcv/root`: four
files at depth 0, of which two are extractable. `P00-OD-009` is **open** — no
live NAS root, no GoodNotes root, and no personal corpus has been read by
anything.

**Do not claim search behaviour, extraction throughput, or coverage accuracy at
scale.** Neither has been measured at any size but this one.

Evidence: `fixtures/mcv/README.md`,
`tests/end_to_end/test_vertical_slice.py::test_the_operator_can_list_and_inspect_bounded_objects_without_recursing`.

## 4. PDF is `unsupported` — reported and counted, never silently skipped

`P00-OD-003` is **open** and no PDF library is a dependency of this repository.
A PDF in an enrolled scope produces a counted `unsupported` outcome and moves the
enrollment's coverage to `partially_processed`, which is the truthful state. It
does not produce an absence, and it does not produce an error.

Evidence:
`tests/end_to_end/test_vertical_slice.py::test_every_enumerated_identifier_is_fetchable_and_the_pdf_is_reported_not_skipped`.

## 5. No model is called, anywhere

No summarisation, no named-entity extraction, no embedding, no identity
resolution, no contradiction detection. Extraction is deterministic and cites
what it produced. `P00-OD-006` is **open**.

Evidence: `src/my_pa/infrastructure/extraction/`, `pyproject.toml`.

## 6. Listings stop at the page size, and four issue a continuation cursor

Truncation is disclosed rather than hidden — `truncation.is_truncated` with a
reason. `knowledge.search`, `entities.relationships`, `entities.search` and
`entities.unresolved_mentions` issue a `next_cursor` a caller can page with.
**Every other listing does not**, so a caller that needs the whole of a large
scope still cannot get it.

Corrected 2026-08-20, a third time. It then said *two*, naming
`knowledge.search` and `entities.relationships`, while `entities.search` and
`entities.unresolved_mentions` had both shipped keyset cursors in the same
campaign — the count was restated by hand each time a cursor shipped and was
wrong each time. The paragraph below already says the build derives this; the
derived text names all four. `test_limitations_cite_evidence.py` checks that
cited paths exist and deliberately not that the sentence is true, so nothing
caught any of the three.

Corrected 2026-08-19, twice over. This section read "`next_cursor` is **always**
`null`" after `entities.relationships` shipped a keyset cursor; correcting it to
name that one capability was still wrong, because `knowledge.search` has paged
via a field called `cursor` since long before this plane existed. The published
readiness text had the same hole, for the same reason — it derived
continuability from the field name `after` and did not know the other spelling.

This one the build states about itself: it is derived into every
`capabilities.get` envelope rather than written here — from which commands
accept `after`, intersected with what the build actually serves, so a process
that withholds `entities.relationships` does not advertise its cursor.

Corrected 2026-08-19. This section read "`next_cursor` is **always** `null`"
after that cursor shipped, while the sentence above claimed the build derives
this rather than writing it down here — a section contradicting the derived text
it points at.

Evidence: `src/my_pa/application/capabilities.py`,
`tests/contract/test_capabilities_and_readiness.py`.

## 7. Recovery is proven for two failures and no others

What is proven: a worker **process** killed mid-extraction loses no object and
duplicates none, and an expired lease lets another worker finish the job. Four
`recovery` tests, one of which kills a real subprocess rather than simulating it.

What is **not** proven, and must not be claimed: a gateway crashing mid-request;
PostgreSQL failing over or restarting under load; more than one worker running
concurrently beyond the connection-pool arithmetic; or any recovery of the
migration control plane.

Evidence:
`tests/jobs/test_extraction_executor.py::test_a_worker_process_killed_mid_extraction_leaves_its_lease_and_loses_nothing`,
`tests/jobs/test_extraction_executor.py::test_an_expired_lease_lets_another_worker_finish_the_job`.

## 8. A database that cannot record an audit row answers `internal_error`

Measured on 2026-08-03 against a disposable database (`my_pa_chain_probe`,
created empty, stepped through all ten Alembic revisions that existed then —
there are eleven since WP-6 — and dropped), invoking
`capabilities.get` and `sources.list` through `apps/cli/invoke.py` at every
chain position:

- unreachable answers `unavailable`;
- an empty database and every revision from `5d75f23847c9` through
  `8b3f5c17d904` answer `internal_error` to both — "the request could not be
  completed", which tells an operator nothing about which state they are in;
- `9c6b4a18ed72`, **one revision behind head** `af3d35efb9c0` when this was
  measured and two behind `1a4c9e77b2d5` now, **serves both**:
  `capabilities.get` exited `0` with the envelope it returns at head, differing
  only in `completed_at`, `observed_at` and `correlation_id`, and `sources.list`
  returned the same `denied` it returns at head. Six audit rows were written
  while the database sat one revision behind head.

**There are two boundaries, and neither of them is "not at head" on its own.**

`9c6b4a18ed72` creates `knowledge.audit_events`. Every served request commits a
row into it, and a request that cannot be audited fails rather than being served
unaudited — so **below** that revision every capability answers `internal_error`,
and canonical `my_pa` at `6c4d3ea82f10` is three revisions below it, which is why
it answers `internal_error`.

`af3d35efb9c0` creates `enrollment_objects`, and that boundary is
per-capability. Measured on a second disposable database (`my_pa_chain_probe2`,
dropped): at `9c6b4a18ed72`, `sources.enroll` through `apps/cli/invoke.py`
answered `internal_error`, while the **same call at head** on the **same
database** answered `created true` with `coverage.eligible 4`. So a revision
behind head is a state in which some capabilities serve and at least one does
not.

**WP-6 added a third boundary of the same shape, above the other two.** Head is
now `1a4c9e77b2d5`, which creates the five capture tables *and* widens
`audit_events`' `capability_is_known` constraint to admit a capture at all
(`D-69`). A database stopped at `af3d35efb9c0` therefore serves everything it
served before and answers `internal_error` to every `capture.*` request — for
the audit-constraint reason, not for a missing-table one, and the difference is
why `D-69` exists: a build that added the capability without a migration passes
every test, because every test builds its database from scratch, and fails in the
field on the first audited capture.
`tests/schema/test_capture_schema_migration.py` is what holds that.

**What this means for the phrase "not at head".** It is not a diagnosis — a
database can be behind head and serve a capability. It is a correct statement
about the build as a whole, because a capability of this build already fails one
revision short. Both halves matter, and stating only the first is what made an
earlier version of this limitation wrong.

The unreachable case was classified correctly by WP-4B2a; the unrecordable-audit
case was not, and correcting the taxonomy is out of scope and deferred by `D-65`.

`apps/cli/health.py` **detects a database that is not at head** and names its
revision against head. It refuses everything below head, which is wider than the
audit-table boundary and is deliberate (`D-62`): it is an operational policy — a
database behind head is not a state an operator should treat as good — and it is
borne out by `sources.enroll` above. It is **not** a claim that every capability
fails below head, and it does not reclassify what the application says.

Evidence: `apps/cli/health.py`,
`tests/contract/test_health_probe.py::test_the_three_states_are_mutually_distinguishable`,
`src/my_pa/infrastructure/persistence/unit_of_work.py`,
`tests/policy/test_audit_is_not_swallowed.py`, `migrations/versions/`.

## 9. Nothing here is deployed, packaged, supervised, or multi-user

No launchd plist, no systemd unit, no console entry point, no distributable
artifact, and no second user. Both processes are started by hand and stopped by
signal. Deployment, production activation, packaging for distribution,
multi-user operation, and risk acceptance are all on WP-5's explicit
out-of-scope list and are operator-gated (`AGENTS.md` section 5).

`ops/launchd/` and `ops/systemd/` are reserved scaffold directories and hold no
unit file.

Evidence: `docs/plans/mcv-completion-plan.md`, `ops/launchd/README.md`,
`ops/systemd/README.md`.

## 10. Source access is read-only, and there is no write path to any source

Roots are opened read-only and containment is revalidated immediately before
each read. The source-provider port has no write method, so "my-pa does not
modify your files" is a property of the interface rather than of the
implementations behind it.

**This survived WP-6 unchanged, and it is worth saying why rather than leaving a
reader to wonder.** WP-6 made the build write — a capture is stored, versioned,
and receipted — but a capture is a **product-owned** record under `ADR-003`
clause 5, a third authority class that is neither a source-system write nor a
managed-document write. Two ends are checked rather than one: the port still
declares exactly its four read operations, and the module that stores a capture
imports no provider at all. A third check drives every `capture.*` capability
over both transports against a recording provider and requires the provider to be
neither called **nor looked up**.

Stated here because it is a limitation an operator may be *looking* for, not
only one they should be warned about.

Evidence: `src/my_pa/contracts/ports.py`,
`src/my_pa/infrastructure/providers/fixture.py`,
`tests/architecture/test_capture_reaches_no_source.py::test_the_source_provider_port_declares_exactly_its_four_read_operations`,
`tests/architecture/test_capture_reaches_no_source.py::test_the_capture_writer_imports_no_source_provider`,
`tests/security/test_mcp_and_cli_negative_evidence.py::test_no_capability_over_either_transport_calls_anything_but_a_read`.

## 11. Capture processing is local and deterministic, and there is no remote capture transport

A capture is stored durably and a row is written into `knowledge.capture_jobs`
at the moment it is admitted — that is what durable-first means: a crash between
accepting a capture and processing it loses the processing, not the record that
it is owed. The capture worker now claims that row and runs the nine deterministic
WP-7 stages. It persists bounded proposals with exact evidence spans, and replay
is checked against stored stage digests. It reads no source, opens no socket, and
calls no model. Relative dates remain unresolved; no model-assisted extraction,
identity resolution, summary generation, or retry backoff was added.

Nor is there a way to capture from anywhere but this machine. `D-30` refuses
ingress and issues no credential, so the iOS Shortcut the canonical package
describes has nothing to call. `RegisteredCaptureClient` and
`CaptureDeliveryAttempt` are **deferred rather than built** (`D-74`): their
defining fields are a revocable credential reference and a delivery record, and
with `D-30`, `O-21` and `P00-OD-010` standing they could never be populated, so
the tables are absent rather than permanently empty. `capture_submissions`
carries no `registered_client_id` column for the same reason.

What a capture therefore is today: text the operator types into a loopback
process, stored immutably by version, retrievable by version, searchable, and
processed locally into noncanonical evidence-bound proposals. Consequential
promotion still passes through WP-8 review; processing grants no external-action
authority.

Evidence: `src/my_pa/infrastructure/persistence/tables.py`,
`src/my_pa/infrastructure/persistence/capture.py`,
`src/my_pa/infrastructure/jobs/capture_pipeline.py`,
`docs/plans/mcv-completion-plan.md`,
`tests/pipeline/test_proposal_spans.py::test_every_proposal_the_pipeline_persists_cites_a_span_that_re_derives`,
`tests/pipeline/test_stage_replay.py::test_every_stage_replays_to_the_digest_it_stored`.

## 12. Relationship identity and profiles are fixture-only read models

WP-9 implements governed person and organisation identities, unresolved
mentions, duplicate review, reversible merge/split, conversation participants,
and source-backed profile and timeline reads. It does so only through the
fixture personal-source provider and an internal application/read-model path;
it adds no public capability and has not been exercised against live contacts,
email, or calendar data.

**That describes WP-9, and is no longer true of the plane.** Corrected
2026-08-19 when it acquired public reads, and again after Phase A, which gave it
writes: the Relationship Intelligence entity plane is fifty-four `entities.`
names now — sixteen reads and thirty-eight writes over identity, identifiers, aliases,
assignments, directed edges, observations, mention resolution, proposal staging,
and governed merge preview/apply. This document,
whose job is stating what the build does not do, said nothing about them. What
remains true, and is the limitation:

* **They are off by default, and the writes are off twice.** A process that has
  not set `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` publishes none of the
  fifty-four and refuses each with `unsupported` on every transport. A process
  that has set it but not
  `MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` serves the reads and refuses
  all thirty-eight writes the same way.
* **Proposal review and governed merge are available, but remain fail-closed and
  off by default.** Entity and Relationship Memory cases use canonical
  `review.list`/`review.decide`; accepting a merge proposal does not execute a
  merge. Apply requires a separate persisted `entities.merge.preview` followed
  by operator-only `entities.merge`. Remotely, both additionally require global
  remote writes, an exact server-resolved `remote.operator` durable capability
  set, the allowed-capability and purpose intersections, every feature gate, and
  application policy. No raw allowlist or non-operator profile can publish them,
  and this repository change activates no live profile, grant, or flag.
* **No live personal data has reached it.** Every figure and every test is
  synthetic, and no connector writes an observation.
* **Identity history and split exist in repository code but have not been live
  commissioned.** `entities.identity_history` is Principal-scoped and
  keyset-paginated; `entities.split.preview`/`entities.split` use the same
  operator-only identity-correction and remote-profile boundary as merge. No
  flag, grant, OAuth setting, runtime, connector, or live personal-data path was
  activated by final completion.

Profiles disclose coverage, unavailable domains, freshness, calculation basis,
and time windows. They do not claim completeness. There is no automatic identity
merge, relationship score, sensitive-trait inference, public research,
commitment or briefing generation, Pulse surface, or relationship frontend.
Authorizing a real connector still requires its exact account and scope plus the
authentication and live-personal-data decisions the plan leaves open.

Evidence: `src/my_pa/domain/relationship/`,
`src/my_pa/application/relationships.py`,
`src/my_pa/infrastructure/providers/personal_fixture.py`,
`tests/relationship/test_relationship_domain.py::test_profile_coverage_fails_closed_unless_it_names_the_exact_observation_set`,
`tests/provider_conformance/test_personal_fixture_provider.py::test_personal_source_port_and_adapter_expose_no_mutation_method`,
`docs/plans/mcv-completion-plan.md`.

## 13. Managed documents: a capability seat since WP-28, and two stores that are not one transaction

WP-27 implements the product-owned write plane: a designated managed root, stable
document identity, immutable versions, expected-version checking, idempotency,
receipts, archive/restore, backup/restore and an integrity check. Source roots
stay read-only, and the byte store refuses a managed root that is, contains, or
lies inside a configured source root, after resolving both.

**WP-28 gave it a capability seat, and that is what changed.** Six
`documents.` capabilities under two purposes of their own reach
`ManagedDocumentService` through `ApplicationService.invoke`, so a managed
operation is authorized, audited and refused by the machinery every other
capability meets. WP-27's statement that "a managed operation writes no
`audit_events` row" is **superseded**: every managed request now writes one.

**What the row says, exactly, because it is easy to over-read.** `authorize`
records the *decision* on the audit sink's own connection and commits it there
(`D-34`), before the handler runs. So a policy refusal — a purpose the capability
does not permit — is recorded as `denied` with its reason. A refusal raised by the
*handler* — a stale `expected_version_number`, an idempotency key bound to a
different request, a document another Principal owns — rolls the work back and
leaves a row that says `allowed`, because authorization *was* granted and that
remains true. `outcome` carries the **authorization decision** and not the result
of the work, and that is `invoke`'s pre-existing semantics for **all 26**
capabilities rather than anything the managed plane introduced. **Nothing writes
a second event to say the work then failed**, for this plane or any other.

**The join that would settle it does not exist, and an earlier version of this
section said it did.** It told an operator to "join the version and lifecycle
rows to see whether anything landed". That is not performable. No `managed_*`
table carries an `audit_id` or a `request_id`; the only shared column name is
`correlation_id`, and the value on `managed_document_versions`,
`managed_document_submissions` and `managed_document_lifecycle_events` is minted
inside `ManagedDocumentService` and is a **different value** from the one on the
`audit_events` row `invoke` wrote for the same request. Neither is passed to the
other. What is actually available is heuristic: the same `principal_id`, the same
capability, and two timestamps close together. For an operator reconciling one
request on a single-operator process that is usually enough to form a belief, and
it is never enough to prove one — two `documents.create` calls from the same
Principal in the same second cannot be told apart.

**This must close before `EXT-08`.** Once a non-operator client drives this
surface, the audit is the only record of what that client did, and "the Principal
attempted `documents.create`, and a version appeared at about the same time" is
an inference rather than a trail. Closing it means carrying one identifier across
the boundary — the `invoke` correlation identifier into the managed rows, or the
`audit_id` — and it is not carried today. It is a prerequisite of external client
activation rather than of this package, and it is recorded here as an open item
rather than described as a control that exists.

**A process with no `MY_PA_MANAGED_DOCUMENT_ROOT` publishes none of the six.**
`capabilities.get` omits them and the MCP tool list omits them, and a call by name
is refused `unsupported`. There is no default location and no inference.

**The filesystem and the database are not one transaction, and the product does
not claim they are.** Bytes are written and fsynced before the metadata rows are
inserted, so the failure that survives a crash is **bytes with no row** —
unreachable, reclaimable, reported by `verify` as an orphan, and never cleaned up
automatically. The reverse, a row naming absent bytes, is what the ordering
refuses to produce.

**Archive withdraws a document from the active set; it does not lock it.** The
two lifecycle transitions are reversible state changes and nothing more, so
revising an archived document succeeds — the revision creates the next version
and the document stays `archived`. This is the specified behaviour rather than a
gap in the checks: there is no seal, and no operation refuses a write on the
strength of the current state. An operator who reads "archived" as "frozen" will
be wrong.

**Not implemented, deliberately:** hard delete of a managed document (out of
scope, and irreversible destruction of canonical data is reserved to the operator
under `AGENTS.md` section 8.2); automatic reclamation of orphaned bytes; comments
on a managed document; copy and relocate — neither has a caller, and a location
is not something this plane exposes at all. A backup carries versions and their
bytes and **not** the lifecycle rows, the submissions, or the receipts. A
restored plane is **active**: a document that was archived when the backup was
taken comes back active and has to be archived again, and an idempotency key used
before the restore is free again afterwards.

**The intermediate-component TOCTOU window WP-27 disclosed is closed (WP-28).**
Every write and every read is now performed relative to a directory descriptor:
the chain from the root down is walked once with `O_DIRECTORY | O_NOFOLLOW`,
holding a descriptor at each level, and the create, the link, the unlink and the
read are `openat`/`linkat`/`unlinkat` against it. A descriptor names an inode, so
after the walk there is no component left to swap.
`tests/security/test_managed_store_toctou.py` reproduces the attack at the instant
the window opens, shows the *previous* publication landing bytes outside the root
under it, and shows this one refusing.

**What that does not cover, stated so it is not read as more.** The managed root
itself is opened by name — once for every anchored step rather than once per
public call, which is five times during a single `put` — and is the one component
no descriptor sits above; a root replaced between any two of those opens is a
different root. A platform
without directory-relative syscalls cannot hold the guarantee, and the store
**refuses** rather than reverting to name-based calls, so such a build fails to
write rather than writing less safely. The precondition for the original attack —
local write access inside the managed root as the product's own UID — was never
what made it a NOTE and is unchanged.

**Nothing here has run against a real managed root.** Every test writes into
`tmp_path`; pointing the plane at an operator's real storage is `EXT-10` and
remains an operator action.

Evidence: `src/my_pa/domain/documents/managed.py`,
`src/my_pa/infrastructure/managed_document_stores/filesystem/store.py`,
`src/my_pa/application/managed_documents.py`,
`ops/runbooks/managed-document-operations.md`,
`tests/security/test_managed_document_containment.py::test_no_managed_store_method_accepts_a_path`,
`tests/architecture/test_managed_writes_are_contained.py::test_every_filesystem_write_is_the_managed_store_or_is_registered`,
`tests/database/test_managed_documents.py::test_a_rolled_back_write_leaves_bytes_with_no_row_and_verify_finds_them`,
`tests/database/test_managed_documents.py::test_a_backup_restores_into_a_fresh_root_and_an_emptied_database`,
`tests/database/test_managed_document_audit.py`,
`tests/security/test_managed_store_toctou.py`,
`tests/schema/test_managed_document_capability_migration.py`.

## 13a. The Frontier MCP surface (WP-28)

**Thin adapter, and the claim is a parse rather than a promise.**
`tests/architecture/test_mcp_is_a_thin_adapter.py` reads every module under
`src/my_pa/adapters/mcp/` and asserts a closed import allowlist, no forbidden
operation in applied or unapplied form, exactly one `normalize` and one `invoke`,
no capability name written anywhere in the package, and no read of a field out of
a caller's request. The last two exist because a plant that wrote expected-version
and idempotency logic inline in the transport passed every other claim.

**Local stdio and a separately gated persistent remote surface.** The default
`apps/gateway.py mcp` process opens no socket and imports only the stdio MCP
adapter. `apps/gateway.py mcp-remote` is a distinct authenticated Streamable
HTTP surface: it is disabled by default, requires the origin OAuth configuration
and durable remote-security control, and enforces exact host/origin and DNS
rebinding protections. This repository does not activate or deploy it.

**The kill switch.** `MY_PA_MCP_SURFACE_DISABLED` is **off by default and the
surface serves** — it is a pipe an operator starts deliberately, not a network
listener. Engaging it empties `tools/list` *and* refuses `tools/call` before the
application is reached. A malformed value refuses to start.

**Client binding is identification, not authentication.** `MY_PA_MCP_CLIENT_ID`
binds the surface to a row in the existing `capture_clients` registry and the
process refuses to serve when that row is absent, foreign or **revoked** — so
`revoke_client` withdraws the surface at the next start. stdio carries no
credential, so nothing is verified and nothing is presented.

**Remote authentication is implemented, not activated.** The persistent remote
surface has an origin OAuth authorization server, protected-resource metadata,
resource-bound access and optional refresh tokens, and durable client grants.
It still fails closed unless the global remote switch, database security control,
exact host/origin checks, token resource/scope, and capability/purpose
intersections all admit the request. Remote writes need their independent global
write switch; operator-only merge additionally needs the exact server-resolved
`remote.operator` durable capability set. No live client, grant, flag, public
ingress, or deployment is established by this implementation.

**No live NAS source provider.** Source reads over MCP go through the existing
`sources.*` capabilities and the fixture provider, which are read-only; a live
NAS provider is `EXT-10`-gated and is not built.

Evidence: `src/my_pa/adapters/mcp/server.py`, `src/my_pa/adapters/mcp/tools.py`,
`tests/architecture/test_mcp_is_a_thin_adapter.py`,
`tests/security/test_mcp_surface_controls.py`,
`tests/security/test_mcp_and_cli_negative_evidence.py`.

---

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy
identities may appear only in explicit compatibility or evidence records.
