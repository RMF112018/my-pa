# Record lineage — Slice S3.1 open writes for connected clients: implementation contract

**Status:** proposed implementation contract under
[ADR-015](../decisions/ADR-015-record-lineage-and-issue-situations.md) (Proposed —
accepted by directive defaults; architecture/test-isolated scope only), as amended by its
S3.1 amendment (decision 15). It is the single document S3.1 implementers code against,
on top of the [S1](record-lineage-s1-contract.md), [S2](record-lineage-s2-contract.md),
[S3](record-lineage-s3-contract.md) and [S4](record-lineage-s4-program-contract.md)
contracts as implemented. It authorizes no migration run, grant, client profile or
opt-in change, deployment, ChatLLM exposure or production use. Where it differs from the
Orchestrator brief (`orchestrator-brief-S3.1-v2-mcp-clients.md`) or from the review
package (`MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`), this document controls for
S3.1 once the design review passes it, and section 12 records why.

**Authority for the change:** 2 operator directives given directly to the Manager and
recorded in the Manager ledger, not a production ratification: 2026-10-20 "Operator
authorization should not be required for linkage or lineage records." and 2026-10-25 "I
want the MCP connected clients to manage and utilize the lineage feature, i.e. as a client
identifies relationships between records, or when I provide instruction to do so, it will
have the permission to commit the associated lineage data. Connected clients will utilize
the lineage data to make searches more efficient and effective while generating feedback,
creating reports, making suggestions, etc." The operator explicitly kept (recorded
answers): the ChatLLM operator-decision gate on capability exposure; `MY_PA_LINEAGE_ENABLED`
default off; Issue close and reopen attested; `records.backfill.*` operator-only and
dry-run; OD-03's rule that nothing a client claims makes its link authority-grade or
accepted-grade evidence; server-derived actor and Principal; native ownership and
endpoint validation; the append-only ledger, idempotency, compare-and-swap and evidence
rules; cross-Principal isolation; no production grant or profile change and no grant for
a deployed client.

**Basis:** `feat/lineage-s31-open-writes@9bfd7d471b88255fb36112e7d62e1bb9ae38cdf5`
(tree `75e458392b09d797b2c8d2e496f5e3fb8f3a37e4`, the S4 head that passed FR4; its
ancestor `origin/main@19426ed5` holds PR #339). Alembic single head `c5260943d933`
(122 revisions); 229 `Capability` members, 60 `Purpose` members, 150 `IdKind` members,
240 audit-vocabulary capability names, 30 lineage capabilities behind
`MY_PA_LINEAGE_ENABLED` (19 of them lineage writes, `LINEAGE_WRITE_CAPABILITIES`), 37
`CHATLLM_OPERATOR_DECISION_REQUIRED` capabilities, 110 `gateway.json` entries. "S1 §n" …
"S4 §n" cite the earlier contracts. Paths under `src/` are written in full so the
citation guard resolves them; line numbers are at the basis commit.

All counts in this file are digits on purpose (spelled-count guard).

## 1. What S3.1 is

S3.1 lets an authenticated connected client — a remote MCP client, the stdio MCP
transport, or any other non-attested caller the ordinary grant and purpose rules admit —
**commit** the lineage writes that S1–S3 reserved to the local operator, and gives every
client a bounded read built to **use** lineage. It does so without inventing a trust
signal: every write records, server-side, which channel made it and which OAuth client
(when one is authenticated); a client's statement that the user directed the write is
stored as an unverified claim that no gate reads. A client-committed fact is visible,
labelled, traversed and usable for search, suggestion and report context, but it is
**never accepted-grade**: the Issue close gate is held while any unreviewed client fact is
in the Issue's review scope (section 4.6), S4 Program totals that depend on one are
`not_reportable` (section 7.8), and only the human channel — the local operator through
the CLI or the HTTP gateway `invoke` route — promotes a client fact, by appending a
`confirm` revision (section 4.7).

**In S3.1:**

- **Part A — open writes.** The 14 lineage writes of the gate table (section 3.1) whose
  current gate is `attested_lineage_authority` and which the directive names stop being
  attested: `records.associations.assert` / `correct` / `end` / `contest` / `reinstate`,
  `issues.memberships.add` / `end` / `correct`, `issues.project_links.add` / `end`,
  `issues.handoffs.record` / `correct`, `issues.work.create_task` /
  `create_commitment`. Remote exposure stays a **configuration** decision: the default
  remote MCP path already publishes write tools only while remote writes are enabled and
  only to a client holding a grant (section 3.3); the #339 restricted-profile ceilings gain
  an **opt-in** set, empty by default (section 7.11).
- **Part B — provenance honesty.** A new `AcceptanceBasis` member `client_identified`;
  server-derived `authority_class`, `decision_channel` and a new `asserting_client_id`
  on every fact row; the client-declared `user_directed` request flag stored as
  `user_directed_claim`; labels on every lineage read; the close-gate review scope; 3
  operator-attested `confirm` capabilities; channel-bound replay; per-client rate
  bounds; the S4 reportability rule for unreviewed Project links.
- **Part C — utilization.** `records.lineage.related` (section 7.4), a multi-seed bounded
  related-records read over the S3 traversal; the `lineage_context_ref` report block and a
  schema-2 report manifest with a server-recomputed lineage section (section 7.9); gap
  reads through the widened `issues.closure_readiness` and the related read's provenance
  filter (section 7.5); client guidance in tool descriptions, field documentation and the
  docs page `docs/operations/record-lineage-client-guidance.md` (section 7.12).
- **Part D — catalog and compact MCP facade** (operator addition, 2026-10-25: "ensure the
  new MCP capabilities for lineage are added to the catalog and can be used through the
  compact MCP facade"). Every S1–S4 lineage-plane capability and every new one has a
  `TOOLS` entry with a summary and truthful annotations, a `feature` label, and a
  deliberate facade kind; the attested writes become `operator` kind; the client-writable
  writes are `write` kind; the opt-in profile entries make them reachable through
  `my_pa.describe` / `my_pa.read` / `my_pa.write` end to end (section 7.13).

**Not in S3.1** (section 11 lists each owner): a principal-wide review queue; web
confirm/end actions; handoff confirmation; any verified "user directed" signal; a client
identifier on Issue revisions; any production grant, profile opt-in, database role
privilege, deployment or migration run.

**Unchanged and still gated:** `issues.close`, `issues.reopen`, `issues.update` of a closed
Issue (a correction), `records.backfill.plan` and `records.backfill.report`, and the 3 new
`confirm` capabilities, are local-operator attested exactly as S1 §6.1 / S2 §6.1 state
(`denied` before any row and before the replay lookup). `MY_PA_LINEAGE_ENABLED` and
`MY_PA_LINEAGE_BACKFILL_ENABLED` stay default off. Every lineage capability, old and new,
stays `CHATLLM_OPERATOR_DECISION_REQUIRED` (the 2 backfill names stay
`CHATLLM_CONTROL_PLANE_EXCLUDED`).

## 2. Identifier kinds

**No new `IdKind` member.** A confirmation is a revision (`irv_`) or a Project-link event
(`ipme_`); the related read persists nothing; a manifest is keyed by its artifact (`rpt_`).

## 3. Repository truth

### 3.1 The gate table — every lineage write, its current gate, its new gate, its pin

The one attestation helper is `attested_lineage_authority`
(`src/my_pa/application/lineage_authority.py:79`), which derives the pair through
`lineage_authority` (`src/my_pa/application/lineage_authority.py:56`) — the Knowledge
derivation `derive_knowledge_review_authority`
(`src/my_pa/domain/policy/knowledge_review_authority.py:63`) with both allowlists empty —
and raises `DeniedError` unless the class is in `ATTESTED_AUTHORITY_CLASSES`
(`src/my_pa/domain/lineage/vocabulary.py:354`) and the channel in
`ATTESTED_DECISION_CHANNELS` (`src/my_pa/domain/lineage/vocabulary.py:359`). Every
handler calls `_lineage_plane` first, then derives authority, then reaches the
reservation. The database repeats the rule with the CHECK
`a_lineage_row_is_local_operator_attested`
(`src/my_pa/infrastructure/persistence/tables.py:16517`).

| Capability | Current gate (handler) | Current gate (database) | New gate | Pinned by |
| --- | --- | --- | --- | --- |
| `records.associations.assert` | `src/my_pa/application/service.py:13632` | `src/my_pa/infrastructure/persistence/tables.py:17039` (root), `src/my_pa/infrastructure/persistence/tables.py:17156` (revision); `migrations/versions/20261017_264310e0416a_record_lineage_s1.py:662`, `migrations/versions/20261017_264310e0416a_record_lineage_s1.py:724` | open: `lineage_write_provenance` (section 6.1), never `denied`; rate bound (section 4.8) | `test_a_remote_client_commits_every_open_lineage_write`; `test_a_lineage_row_provenance_is_consistent` |
| `records.associations.correct` | `src/my_pa/application/service.py:13652` | revision CHECK as above | open | same |
| `records.associations.end` | `src/my_pa/application/service.py:13669` | revision CHECK | open | same |
| `records.associations.contest` | `src/my_pa/application/service.py:14007` | revision CHECK | open | same |
| `records.associations.reinstate` | `src/my_pa/application/service.py:14027` | revision CHECK | open | same |
| `issues.memberships.add` | `src/my_pa/application/service.py:13595` | root and revision CHECK | open | same |
| `issues.memberships.end` | `src/my_pa/application/service.py:13612` | revision CHECK | open | same |
| `issues.memberships.correct` | `src/my_pa/application/service.py:13784` | revision CHECK | open | same |
| `issues.project_links.add` | `src/my_pa/application/service.py:13551` | `src/my_pa/infrastructure/persistence/tables.py:16893`; `migrations/versions/20261017_264310e0416a_record_lineage_s1.py:569` | open | same |
| `issues.project_links.end` | `src/my_pa/application/service.py:13571` | membership-event CHECK as above | open | same |
| `issues.handoffs.record` | `src/my_pa/application/service.py:13801` | `src/my_pa/infrastructure/persistence/tables.py:17620`; `migrations/versions/20261018_d020b532ad7d_record_lineage_s2.py:643` | open | same |
| `issues.handoffs.correct` | `src/my_pa/application/service.py:14136` | `src/my_pa/infrastructure/persistence/tables.py:17843`; `migrations/versions/20261019_6f1476b8da52_record_lineage_s3.py:702` | open | same |
| `issues.work.create_task` | `src/my_pa/application/service.py:13908` | the membership and intent links' root and revision CHECKs | open | same |
| `issues.work.create_commitment` | `src/my_pa/application/service.py:13944` | same | open | same |
| `issues.create` | `lineage_authority` (recorded, open), `src/my_pa/application/service.py:13436` | `an_issue_revision_authority_is_known` (`src/my_pa/infrastructure/persistence/tables.py:16730`) | **unchanged** (open); gains the rate bound and the request-row writer columns only | `test_issue_metadata_writes_keep_their_s1_rules` |
| `issues.update` (open Issue) | `lineage_authority`, `src/my_pa/application/service.py:13531` | as above | **unchanged** (open); rate bound | same |
| `issues.update` (closed Issue: `corrected`) | `_require_attested` (`src/my_pa/application/issues.py:435`, called at `src/my_pa/application/issues.py:766` for a replay and `src/my_pa/application/issues.py:775`) | `an_issue_closure_is_operator_attested` (`migrations/versions/20261018_d020b532ad7d_record_lineage_s2.py:470`) | **unchanged, attested** | existing `test_a_correction_of_a_closed_issue_needs_the_local_operator` |
| `issues.close` | `src/my_pa/application/service.py:13695` | `an_issue_closure_is_operator_attested` | **unchanged, attested**; gate gains the review scope (section 4.6) | `test_close_reopen_and_closed_issue_corrections_stay_operator_attested`; `test_an_unreviewed_membership_holds_the_close` |
| `issues.reopen` | `src/my_pa/application/service.py:13719` | as above | **unchanged, attested** | same |
| `records.backfill.plan` | `src/my_pa/application/service.py:14166`, after `_lineage_backfill_plane`; `_OPERATOR_ONLY` | `a_lineage_row_is_local_operator_attested` on `lineage_backfill_runs` (`src/my_pa/infrastructure/persistence/tables.py:17933`; `migrations/versions/20261019_6f1476b8da52_record_lineage_s3.py:758`) | **unchanged, attested, operator-only, own switch**; that CHECK keeps its name and text there | `test_backfill_stays_operator_only_and_attested` |
| `records.backfill.report` (read) | `src/my_pa/application/service.py:14194` | — | **unchanged** | same |
| `records.associations.confirm` (new) | — | — | attested (S1 §6.1 rule) | `test_confirm_capabilities_are_operator_attested_before_the_replay_lookup` |
| `issues.memberships.confirm` (new) | — | — | attested | same |
| `issues.project_links.confirm` (new) | — | — | attested | same |

The lineage reads (`records.lineage`, `records.associations.history`, `issues.read`,
`issues.list`, `issues.history`, `issues.timeline`, `issues.handoffs.list`,
`issues.closure_readiness`, `meetings.notes.versions` / `read_version`) are not attested
today and keep their S3 §6.1 remote grant re-check (`_lineage_read`,
`src/my_pa/application/service.py:13383`).

### 3.2 Who the server can tell apart

- **The Principal is the operator for every caller.** Every remote OAuth client
  authenticates as the operator Principal (ADR-013; ADR-015 context); there is no
  client-to-human binding. `PrincipalKind` therefore distinguishes nobody.
- **The transport, the stamped surface and the OAuth client id are server-derived.**
  `Authorization.transport`, `Authorization.operator_surface` (stamped only by the CLI and
  the HTTP gateway `invoke` route) and `Authorization.authenticated_client_id` (stamped by
  the remote MCP composition from the resolved token,
  `src/my_pa/adapters/mcp/remote.py:343`) are never read from a payload; an operator
  surface together with a client, a remote transport or a grant ceiling is refused
  before any decision (`refuse_inconsistent_operator_surface`,
  `src/my_pa/application/authorization.py:828`).
- **The derivation already yields 3 lineage-relevant classes**
  (`src/my_pa/domain/policy/knowledge_review_authority.py:63`): `local_operator` with
  `local_cli` or `local_web` (the human channel); `ordinary_reviewer` with
  `remote_interactive` (a remote client, client id present); `ordinary_reviewer` with
  `local_unattested` (stdio MCP or any unstamped local composition, no client id).
  `remote_operator_attested` stays unreachable for lineage (both allowlists empty).
- **Where the client id is recorded today:** the MCP interaction log
  (`observability.mcp_interactions`, `oauth_client_id`, mutable by its own delete rule)
  and the Knowledge submission ledger; **not** `audit_events` (which has no client
  column) and not any lineage table. S3.1 records it on every lineage fact row and on the
  idempotency row (section 5).
- **What the server cannot tell:** whether a human or a model composed a remote or stdio
  call; whether the user instructed it; whether 2 calls under 1 OAuth client come from
  one agent; whether cited evidence semantically supports the relation. Section 14 states
  each as a residual.

### 3.3 Remote exposure today

- **The default remote MCP path** publishes a capability when the process composes it,
  it is not `_OPERATOR_ONLY` (no lineage write is), and — for a write, classified by
  `_WRITE_PURPOSES`, which holds `issue_authoring`, `record_lineage_authoring` and
  `issue_work_authoring` — remote writes are enabled
  (`src/my_pa/adapters/mcp/remote.py:269`); the request's tools are then intersected
  with the client's durable grants (`src/my_pa/adapters/mcp/remote.py:327`). Before
  S3.1 a granted client reached the handler and was `denied` by attestation; after S3.1
  it is admitted. **Issuing those grants is the configuration decision**, and the ChatLLM
  policy keeps every lineage name `CHATLLM_OPERATOR_DECISION_REQUIRED`
  (`src/my_pa/domain/identity/chatllm_capability_policy.py:304`,
  `src/my_pa/domain/identity/chatllm_capability_policy.py:417`), so the ChatLLM profile
  planner never desires or adds one.
- **The #339 restricted profiles** (`MY_PA_MCP_DATABASE_PROFILES_ENABLED`, default off)
  intersect a profile client's grants with a closed, code-owned ceiling:
  `MCP_PROFILE_READ_CAPABILITIES` (`src/my_pa/contracts/mcp_database_profiles.py:16`)
  and `MCP_PROFILE_WRITE_CAPABILITIES` (`src/my_pa/contracts/mcp_database_profiles.py:48`)
  through `profile_capabilities` (`src/my_pa/contracts/mcp_database_profiles.py:66`),
  applied at `src/my_pa/bootstrap/mcp_database_profiles.py:156`. No lineage, Program or
  manifest name is in either set, and the fixed data roles `my_pa_mcp_ro` / `my_pa_mcp_rw`
  hold no privilege on any lineage table (no reviewed `McpObjectGrant` names one; S4
  D-46).

### 3.4 Other facts the design is built on

- **No lineage proposal plane exists.** `records.associations.propose` / `review`
  (`irp`, `ldec`) were deferred by S1 and not built by S3 (S3 D-07); the existing proposal
  capabilities belong to other planes (`entities.proposals.create`,
  `relationship_memory.propose`, `goodnotes.propose`, `knowledge.assertions.submit`) and
  are unchanged.
- **Replay today:** an attested write derives authority before the reservation, so a
  non-attested caller re-sending an operator's committed request is `denied` (S1 §6.1, S2
  §6.1 R2-F14); the recorded writes `issues.create` / `issues.update` replay for any
  caller (channel-blind). The request digest (`request_digest`,
  `src/my_pa/domain/lineage/canonical.py:215`) binds capability, Principal and the parsed
  request only.
- **The close gate** (`close_issue`, `src/my_pa/application/issues.py:842`;
  `closure_readiness`, `src/my_pa/application/issues.py:1078`; `member_blockers`,
  `src/my_pa/domain/lineage/closure.py:149`) reads each mandatory membership's head
  revision evidence and every contested link in the Issue's context; it reads no handoff
  and no Project link.
- **S4 Program metrics** count `issue_outstanding` from the latest
  `issue_project_membership_events` row of each `(project, issue)` and flag legacy links
  (S4 §3.3); S4 certifies no total.
- **Lineage reads are commit-mark consistent** at any `known_at ≤ H` (S3 §3.4, §6.2), so a
  read at an explicit `known_at` is reproducible except for current native resolution,
  current evidence availability and current visibility.
- **Rate limiting:** the repository has no per-Principal limiter (S3 §7.2); the
  `rate_limited` public code exists (`src/my_pa/contracts/v1/errors.py:44`, bounded retry)
  and the Knowledge plane bounds autonomous submits per client and subject
  (`CAUSAL_RATE_LIMIT = 16`, `src/my_pa/domain/knowledge_assertion/provenance.py:73`).
- **Tool descriptions** are each command's first docstring line (`_summary`,
  `src/my_pa/adapters/mcp/tools.py:244`); `capabilities.get` entries carry only name,
  availability and `operator_only` (`build_capability_manifest`,
  `src/my_pa/application/capabilities.py:83`).

### 3.5 The compact MCP facade and remote keys today

- The compact facade (`src/my_pa/adapters/mcp/chatllm_gateway.py`) publishes
  `my_pa.describe` plus the invokers `my_pa.read`, `my_pa.write` and `my_pa.operator`;
  `facade_tool_names` (`src/my_pa/adapters/mcp/chatllm_gateway.py:118`) publishes an invoker
  only when the request's eligible canonical set holds a capability of its kind;
  `facade_kind` (`src/my_pa/adapters/mcp/chatllm_gateway.py:101`) is `operator` for
  `is_operator_only`, else `write` for `is_remote_write`, else `read`;
  `prepare_compact_call` (`src/my_pa/adapters/mcp/chatllm_gateway.py:190`) answers
  `unsupported` for a target outside the eligible set (absent and ineligible alike) and
  `invalid_request` for a kind mismatch; `_catalog_item`
  (`src/my_pa/adapters/mcp/chatllm_gateway.py:223`) takes `summary` and `idempotent` from
  `TOOLS` and `feature` from `_FEATURE_BY_FAMILY`
  (`src/my_pa/adapters/mcp/chatllm_gateway.py:47`), which already maps `issues` and
  `records` to `lineage`, `programs` to `programs`, `commitments` to `work`, `reports` to
  `reports` and `meetings` to `meetings` — **no lineage-plane name falls to `other`**.
  The facade call is prepared, then composed by `compose_remote_arguments`
  (`src/my_pa/adapters/mcp/server.py:314`, `src/my_pa/adapters/mcp/server.py:329`), so it
  takes exactly the canonical path. The interaction log records a facade call under its
  canonical target (`src/my_pa/adapters/mcp_interaction_capture.py:874`).
- **Measured at the basis** (`TOOLS`, `facade_kind`, `feature_label` over the 30 lineage
  and 7 S4 names): every one has a `TOOLS` entry with a non-null summary; every lineage
  write is `write` kind **including `issues.close` and `issues.reopen`** (they are not
  `_OPERATOR_ONLY`; only their handler refuses a non-attested caller); the 2 backfill
  names are `operator`; every read is `read`; and **every tool's `idempotent_hint` is
  `false`**, because `tools.py` derives it from `is_server_replay_capability`
  (`src/my_pa/adapters/mcp/tools.py:274`), a 3-name set of keyless writes
  (`src/my_pa/adapters/remote_request.py:51`).
- **Remote idempotency keys are server-derived.** A remote caller may not send
  `idempotency_key` (`REMOTE_OWNED_PAYLOAD_FIELDS`,
  `src/my_pa/adapters/remote_request.py:83`); for every capability in
  `_IDEMPOTENT_REMOTE_CAPABILITIES` — which already holds all 19 lineage writes — the
  boundary stamps `idk_` + the first 32 hex of `sha256({capability, principal_id,
  payload})` (`src/my_pa/adapters/remote_request.py:438`). The key does not bind the
  client: 2 remote clients sending the same payload get the same key.

## 4. Vocabulary and rules

Widened in `domain/lineage/vocabulary.py` and in the S3.1 revision's CHECKs together (S1
§3 rule).

| Vocabulary | S1–S4 | S3.1 adds |
| --- | --- | --- |
| `AcceptanceBasis` | `user_confirmed` | `client_identified` |
| `LinkRevisionAction` | `assert`, `end`, `correct_evidence`, `contest`, `reinstate` | `confirm` |
| `IssueProjectMembershipAction` | `assert`, `end`, `reinstate` | `confirm` |
| `RecordLinkKind`, `RelationType`, `LinkLifecycleState`, `MemberRole`, `EvidenceRole`, `LineageCompleteness` | as S3 | — |
| `LineageReferenceVerification` (new, `domain/intelligence/source_manifest.py`) | — | `verified_at_commit`, `changed_since_read`, `recompute_failed`, `not_attempted` (the S4 `ProgramVerificationState` tokens, a separate enum so the Program and lineage sections never share a type) |
| `LineageRecomputeFailure` (new, same module) | — | `budget_exceeded`, `statement_timeout`, `seed_not_found`, `cut_beyond_horizon` |

New constants in `domain/lineage/vocabulary.py`: `CLIENT_ACCEPTANCE_BASES =
{client_identified}`; `OPERATOR_ACCEPTANCE_BASES = {user_confirmed}`;
`CLIENT_DECISION_CHANNELS = {remote_interactive, local_unattested}`;
`CONFIRM_CAPABILITIES` (the 3 names); `OPEN_LINEAGE_WRITE_CAPABILITIES` (the 14 names of
section 1); `ATTESTED_LINEAGE_WRITE_CAPABILITIES = {issues.close, issues.reopen,
records.backfill.plan} ∪ CONFIRM_CAPABILITIES`; `LINK_REVISION_CAPABILITIES` gains
`records.associations.confirm` and `issues.memberships.confirm`;
`MEMBERSHIP_EVENT_CAPABILITIES` gains `issues.project_links.confirm`;
`LINEAGE_WRITE_CAPABILITIES` becomes 22 names; `MAX_ASSERTING_CLIENT_ID_CHARACTERS = 256`
(the Knowledge submission precedent); the rate constants of section 4.8;
`MAX_RELATED_SEEDS = 25`; `LINEAGE_RELATED_DIGEST_PREFIX = b"lineage-related-v1\n"`;
`LINEAGE_CONTEXT_BLOCK_KEY = "lineage_context_ref"`. `LINEAGE_READ_GENERATION` stays 1:
no traversal, visibility, ordering or paging rule of an existing read changes (S3 §3).

### 4.1 Provenance classes (server-derived; nothing in a payload reaches them)

| Class (read label = `acceptance_basis`) | `authority_class` | `decision_channel` | `asserting_client_id` | `user_directed_claim` | Accepted-grade |
| --- | --- | --- | --- | --- | --- |
| `user_confirmed` — the human channel | `local_operator` | `local_cli` or `local_web` | null | `false` | yes |
| `client_identified` — a remote client | `ordinary_reviewer` | `remote_interactive` | the authenticated OAuth client id (1..256 characters) | the client's declared flag | **no** |
| `client_identified` — stdio MCP or another unstamped local caller | `ordinary_reviewer` | `local_unattested` | null | the client's declared flag | **no** |

- `client_identified` is the **default for every MCP write**: no transport, flag or field
  can make an MCP call `user_confirmed`.
- `user_directed_claim` is a client-declared statement, recorded verbatim as a boolean,
  bound into the request digest, shown on reads, and **consulted by nothing**: no gate,
  no reportability rule, no authority derivation, no rate bound and no manifest
  verification reads it (pinned statically, section 10). It never upgrades a class.
- A request from the human channel that sends `user_directed: true` is `invalid_request`
  / `user_directed` (the human channel is the directing user; the flag would be
  meaningless and the database CHECK refuses it).
- **Existing rows stay valid unchanged.** Every S1–S4 fact row is `user_confirmed` /
  `local_operator` by the old CHECK, and the new CHECK (section 5) admits exactly that
  shape with `asserting_client_id` null and `user_directed_claim` false — the column
  defaults — so no row is updated.

### 4.2 What a client may write

Any caller the ordinary grant and purpose rules admit (local: every local caller;
remote: a client holding a grant on the capability for one of its permitted purposes) may
call every open write of section 1 within its Principal, under every S1–S3 rule unchanged:
strict `IdKind`, Principal ownership and native-parent checks in the fixed order (`not_found`
alike for absent and foreign), linkability, the closed relation matrix and its per-entry
evidence rule, exact passage anchors, the frozen closed Issue, the `blocks` cycle search,
the transition table, CAS, the composite-only relations, the native-writer refusal of an
Issue `situation_id` (ADR-015 decision 2), and the lock order — **plus** the remote
write-visibility rule (section 6.4) and the accepted-lineage rule of section 4.4. Every
revision a client writes is itself `client_identified` and is what the review scope
(section 4.6) holds the close on.

### 4.3 How client facts appear in reads

Every lineage view that shows a revision-bearing fact carries its stored
`acceptance_basis` (now `user_confirmed` or `client_identified`), `authority_class`
where it already did, and 2 new keys: `user_directed_claim: bool` and
`asserting_client_id: str|null`. `asserting_client_id` is shown **only to a local reader**
and is `null` for every remote reader (a remote client sees that a fact is
client-identified, never another client's OAuth id). The views are listed in section 7.6.
A link's label is its **head revision's** basis; a confirmed link reads `user_confirmed`
with action `confirm` in its history. Client facts are traversed by every lineage read
exactly as operator facts are (they are live facts of the ledger); the related read
filters by basis (section 7.4).

### 4.4 Ending, correcting and contesting: clients never remove accepted lineage (R31-F02 option a, RR1-F01)

**The accepted-lineage rule (keyed on the fact's history, not its head).** A client may
write a revision of a fact only when **no revision of that fact is `user_confirmed`** (a
fact never accepted by the human channel), with exactly 1 exception: it may `contest` an
`active` semantic link whose head is `user_confirmed`. After that contest, **only the human
channel** may write the next revision of that link (`reinstate`, `end`, `correct` or a
further `contest`); every client revision of it is `denied`.

- **The same history rule for every fact family.** A *link* (semantic or membership) is
  accepted when any of its revisions is `user_confirmed`; a *Project link* when any event of
  its `(principal, project, issue)` triplet is `user_confirmed`; a *handoff* when the event
  or any of its corrections is `user_confirmed`. On an accepted fact a client's
  `records.associations.end`, `correct`, `reinstate` or `contest` (other than the 1
  exception), `issues.memberships.end` or `correct`, `issues.project_links.end` or a
  reinstating `issues.project_links.add`, and `issues.handoffs.correct` (`retime` or
  `void`) are **`denied`** (no detail), checked under the head (or triplet, or chain) lock
  after the CAS check, so before any row and before the rate count. The check reads
  whether any `user_confirmed` revision, event or correction exists for the fact
  (`EXISTS`, under the lock), never only the head.
- **A confirmed client fact becomes accepted.** Once the human channel confirms a client
  fact (section 4.7), that fact has a `user_confirmed` revision, so by the same rule no
  client may revise it further — except the 1 `contest` exception, after which again only
  the human channel writes.
- **What a client can do instead.** Dispute an accepted semantic link with the 1
  `contest` (an exact `contradicts` anchor, S3 §3.1), which holds the close until the human
  channel answers it; dispute an accepted membership by reporting it (a membership has no
  contest, S3 §3.2); state a later change of responsibility by recording a new handoff,
  which chains from the last live event (S3 §3.3); and propose any new fact as a new root.
  On never-accepted facts — its own or another client's — a client may end, correct,
  contest, reinstate, void or retime under the S1–S3 transition table and CAS.
- **The human channel** may write every S1–S3 revision on any fact, and additionally
  confirms (section 4.7). Nothing a client writes changes or removes an earlier revision,
  and no sequence of client actions can end, correct or reinstate a fact the human channel
  has accepted at any revision, so accepted lineage is never removed from the default
  traversal by a client.

### 4.5 Asserting an identity that already has a live head

ADR-015 decision 11 holds unchanged: asserting an identity whose head is `active` answers
the existing association with `created: false`, writes only the request row and **never
changes or upgrades its authority** — whichever channel asserts. So an operator's
`records.associations.assert` of an identity a client committed answers the
`client_identified` association; the operator promotes it with
`records.associations.confirm` (section 4.7). A `contested` head stays `conflict` /
`state` (S3 §3.1).

### 4.6 The Issue close gate: the review scope

S2 §3.3 and S3 §3.2 are unchanged and gain 1 condition: **no link in the Issue's review
scope has a `client_identified` head revision.**

- **Review scope of Issue I** = every record link, in any head state, that satisfies the
  S3 §3.2 predicate `in_issue_context` for I: a membership from I; a semantic link whose
  `context_issue_id` is I; a semantic link with I as an endpoint; a null-context semantic
  link whose 2 endpoints are inside I (the S3 inside set: I, its active members and the
  members of their pair sets, at the current head state). Unlike S3's `links_in_context`
  (live heads only), the review scope also includes `ended` heads, so a client's `end` of
  a mandatory membership, a client's `reinstate` of a link the operator contested, and a
  client's `correct` of resolution evidence each **hold** the close instead of opening it.
- **Why a hold and not "does not count".** If client facts merely did not count, a
  client could still weaken the gate by ending a blocking member or reinstating a
  contested link — the S2/S3 gate counted only live heads. Holding the close on every
  unreviewed fact in scope makes the gate no weaker than S3 for any client action, and
  makes client resolution evidence non-accepted-grade by construction: a mandatory member
  whose head revision is `client_identified` holds the close whatever its anchors say.
- **Clearing a hold.** For a live head (`active` or `contested`) the human channel confirms
  it (an `active` head, section 4.7) or writes its own S1–S3 revision of it (`end`,
  `correct`, `contest` or `reinstate`, as the transition table admits). For an `ended`
  head — which, by the history rule of section 4.4, can only be the end of a fact the human
  channel never accepted at any revision — the human channel confirms the end (it accepts
  the removal of an unreviewed client fact; there is no accepted fact to restore) and, if it wants the relationship, asserts it anew
  as a new root (S1). After either the head revision is `user_confirmed`. A client cannot
  clear a hold.
- `issues.close` with a non-empty unreviewed set answers `conflict` / `closure_gate`;
  `issues.closure_readiness` lists it (section 7.5) and is `ready: false`. Close and
  reopen stay attested; Project links and handoffs are outside the gate, as in S2/S3.
- **Serialization.** Every link *revision* writer already takes `FOR SHARE` on every Issue
  the link is in the context of (S3 §6.2, `issues_in_context_of`), and every membership
  writer shares its Issue, so a close and any revision of a link in its review scope
  serialize; the close's `FOR SHARE` set is unchanged. A new null-context `assert` shares
  only its own context and needs no more: a fact first written concurrently with a close is
  equivalent to one written just after it, which the frozen closed Issue already admits
  for null-context asserts (S3 §3.2); readiness and the timeline list it and it holds any
  re-close. The review-scope read is a new repository method
  `review_scope_links(principal_id, issue_id)` (live and ended heads).

### 4.7 Confirmation: the human channel promotes a client fact

A confirmation is a **new immutable revision**, never a mutation:

- **`records.associations.confirm`** (semantic links) and **`issues.memberships.confirm`**
  (memberships; the S1 symmetric `link_id` kind rule): admitted only when the head
  revision is `client_identified` and the head state is `active` or `ended`; else
  `conflict` / `state` (an already `user_confirmed` head, or a `contested` head — a human
  who agrees with a client's dispute ends the link instead). Writes revision `n + 1`,
  action `confirm`, the **same** lifecycle state, `acceptance_basis = user_confirmed`, the
  attested pair, a `reason` (1..2000), the head revision's evidence set re-cited anchor
  by anchor (same anchor ids, roles and ordinals, so the same `evidence_set_digest`), and
  the head revision's `member_native_version` copied (so evidence that was stale stays
  stale: confirming never re-affirms a moved member — that is `issues.memberships.correct`
  under S2 §3.3).
- **`issues.project_links.confirm`**: admitted only when the latest event is
  `client_identified` and its state is `active` or `ended`; appends event `n + 1`, action
  `confirm`, the same state, the latest event's `evidence_anchor_id`, `user_confirmed`, the
  attested pair and a `reason`.
- `ended` stays terminal for every other action; `confirm` of a `client_identified` end is
  the one revision admitted after an `ended` head (it accepts the end of a never-accepted
  client fact; by the history rule of section 4.4 a client can never end a fact the human
  channel accepted at any revision). A confirmed fact is accepted from then on and is
  client-immutable apart from the 1 `contest` exception.
- A closed Issue refuses a confirm of any link in its context or naming it (S2/S3 frozen
  closed Issue), `conflict` / `state`.
- Handoffs and handoff corrections have no confirmation in S3.1 (no gate consumes them;
  section 11).

### 4.8 Rate and volume bounds

Every **non-attested** lineage write (the 14 open writes and the 2 recorded Issue writes)
is counted against 2 rolling budgets of its **writer bucket** — `(decision_channel,
asserting_client_id)`, so each remote OAuth client is one bucket and every stdio/unstamped
local caller shares the `local_unattested` bucket — and 1 budget of the Principal:

| Constant | Value | Window |
| --- | --- | --- |
| `CLIENT_LINEAGE_WRITES_PER_HOUR` | 120 | completed client requests of the bucket with `created_at > at − 1 hour` |
| `CLIENT_LINEAGE_WRITES_PER_DAY` | 1000 | same bucket, `> at − 24 hours` |
| `PRINCIPAL_CLIENT_LINEAGE_WRITES_PER_DAY` | 2000 | every client bucket of the Principal, `> at − 24 hours` |

- Counted on `lineage_write_requests` rows with `completed_at IS NOT NULL` and a client
  `decision_channel` (section 5.2), read **after** the commit mark (S3 §6.2 step 1b) and
  **after every validation, immediately before the first fact row** (section 6.2 step 7):
  the allocator row lock serializes the Principal's lineage writers, so the count is
  race-free without a new table; and because every refusal — an absent or hidden subject
  (section 6.4), a transition, evidence or accepted-lineage refusal — is answered before
  it, a refusal never consumes budget and an absent and a hidden subject answer alike even
  at the bound. `at` is the request's authorization instant.
- Reaching any bound answers **`rate_limited`** / `lineage_write_budget` (new
  `RateLimitedError`, `ErrorCode.RATE_LIMITED`, retry guidance `bounded_retry`) and rolls
  back the reservation and the mark: nothing is written. The limit is a hard ceiling,
  not an integrity rule; it bounds the review work one client can impose.
- A **replay** returns before the count and consumes nothing; a refused write leaves no
  row and consumes nothing; a composite counts as 1 request (it writes at most 5 links,
  S2 §6.4 — a stated residual, section 14). Operator writes are never counted or limited.
- Changing a bound is a code change under review (no settings key).

### 4.9 Idempotency and replay: the digest binds the writer

The S1 §5.4 request digest is unchanged for the human channel and gains the writer for a
client:

- **Human channel:** the digest document is exactly the S1–S4 document. Every recorded
  S1–S4 key therefore replays byte-identically for the operator.
- **Client channel:** the digest document gains the key `"writer": {"decision_channel":
  …, "asserting_client_id": … | null}` (a server-only key the strict request models can
  never carry). A client re-sending its own committed request replays it (`replayed:
  true`, the stored answer, no write); the same key re-sent through another writer — an
  operator's key by a client, a client's key by the operator or by another client — has a
  different digest and answers **`conflict` / `idempotency_key`** (superseded by section 12.1 N2-01: the answer is `conflict` / `idempotency_conflict`), writing nothing. No
  client therefore ever receives an attested write response, first-time or replayed (S2
  §6.1 R2-F14 kept for the open writes in this form).
- **The remote key binds the client** (Part D, R-key): for the 14 open writes the
  remote boundary adds `"client": authenticated_client_id` to the document it hashes into
  the derived `idk_` key (a new `_CLIENT_BOUND_KEY_CAPABILITIES` set in
  `adapters/remote_request.py`); every other capability's derivation is unchanged. So 2
  remote clients sending the same payload get 2 keys and both reach the identity rule
  (the second is answered `created: false`, section 4.5), while a client's own retry
  derives its own key and replays.
- **`user_directed`** enters the request document only when `true` (as
  `"user_directed": true`); absent and `false` produce the S1–S4 document, so every
  existing digest is unchanged.
- **Attested capabilities** (close, reopen, closed-Issue correction, backfill, confirm)
  keep S1 §6.1: authority before the reservation, so a non-attested replay is `denied`.
- `issues.create` / `issues.update` keep their channel-blind S1 replay (section 12, D-06).

### 4.10 Cross-Principal isolation and audit

Unchanged: every statement is Principal-scoped; a foreign identifier answers like an
absent one; reads carry no hidden counts. Every client write leaves its existing
`audit_events` row (capability, purpose, outcome) and, in the same transaction, fact rows
and an idempotency row that carry `decision_channel` and `asserting_client_id` — the
append-only record of which client wrote what. No new cross-Principal disclosure exists:
`asserting_client_id` is shown only to local readers of the same Principal.

## 5. Schema — one additive revision

One Alembic revision, `down_revision = "c5260943d933"`, the new single head (file
`migrations/versions/<date>_<rev>_record_lineage_s31.py`; slug `record_lineage_s31`).
Frozen literal DDL, no domain or persistence import, declarations mirrored in
`infrastructure/persistence/tables.py` with the `TABLES_SHA256` pin and every W1 §2.2
registration step. S1–S4 §4 conventions hold (schema `knowledge`, principal partition,
`_is_identifier`, a restated CHECK keeps its name, a replaced function is `CREATE OR
REPLACE` and `downgrade()` restores its S4 body byte for byte). The revision executes **no
`GRANT` or `REVOKE`** and calls nothing in `infrastructure/database/mcp_object_grants.py`.

### 5.1 The 4 fact tables

`record_link_revisions`, `issue_project_membership_events`, `issue_responsibility_events`,
`issue_responsibility_corrections`:

- `ADD COLUMN asserting_client_id text` (null) and `ADD COLUMN user_directed_claim boolean
  NOT NULL DEFAULT false` (a constant default: no row is rewritten and no append-only
  trigger fires).
- CHECK `an_asserting_client_is_bounded`: `asserting_client_id IS NULL OR
  char_length(asserting_client_id) BETWEEN 1 AND 256`.
- Widen `<table>`'s acceptance-basis CHECK (`a_link_revision_acceptance_basis_is_known`,
  `a_membership_event_acceptance_basis_is_known`, `a_handoff_acceptance_basis_is_known`,
  `a_handoff_correction_acceptance_basis_is_known`) to `('client_identified',
  'user_confirmed')`.
- **Drop** `a_lineage_row_is_local_operator_attested` and add
  `a_lineage_row_provenance_is_consistent`:

```text
(acceptance_basis = 'user_confirmed' AND authority_class = 'local_operator'
   AND decision_channel IN ('local_cli', 'local_web')
   AND asserting_client_id IS NULL AND NOT user_directed_claim)
OR (acceptance_basis = 'client_identified' AND authority_class = 'ordinary_reviewer'
   AND ((decision_channel = 'remote_interactive' AND asserting_client_id IS NOT NULL)
     OR (decision_channel = 'local_unattested' AND asserting_client_id IS NULL)))
```

  A new name, because the old name would state a rule that no longer holds; the old text
  is restored by `downgrade()`. `lineage_backfill_runs` keeps
  `a_lineage_row_is_local_operator_attested` unchanged.

**`record_link_revisions`** additionally:

- Widen `a_link_revision_action_is_known` (+ `confirm`), `a_link_revision_capability_is_known`
  (+ `records.associations.confirm`, `issues.memberships.confirm`) and
  `a_link_revision_states_its_reason` (`confirm` needs a reason).
- Restate `a_link_revision_ends_exactly_when_it_ends`: `(action = 'end' AND lifecycle_state
  = 'ended') OR (action = 'confirm' AND lifecycle_state IN ('active', 'ended')) OR (action
  NOT IN ('end', 'confirm') AND lifecycle_state <> 'ended')`.
- New CHECK `a_confirmation_is_operator_attested`: `action <> 'confirm' OR
  acceptance_basis = 'user_confirmed'`.
- `CREATE OR REPLACE FUNCTION knowledge.a_link_revision_follows_an_active_predecessor()`:
  the S3 table plus `confirm` admitted iff the predecessor's `acceptance_basis` is
  `client_identified`, its state is `active` or `ended`, `NEW.lifecycle_state` equals it,
  `NEW.evidence_set_digest` and `NEW.evidence_count` equal the predecessor's and
  `NEW.member_native_version IS NOT DISTINCT FROM` the predecessor's; else
  `restrict_violation`. (`a_link_revision_evidence_set_is_frozen` still proves the count at
  commit; with the equal digest the re-cited set is the predecessor's.)

**`issue_project_membership_events`** additionally:

- Widen `a_membership_event_action_is_known` (+ `confirm`) and
  `a_membership_event_capability_is_known` (+ `issues.project_links.confirm`).
- Restate `a_membership_event_ends_exactly_when_it_ends`: `(action = 'end' AND state =
  'ended') OR (action = 'confirm') OR (action IN ('assert', 'reinstate') AND state =
  'active')`; new CHECK `a_project_link_confirmation_states_its_reason` (`action <>
  'confirm' OR reason IS NOT NULL`); `a_confirmation_is_operator_attested` as above.
- `CREATE OR REPLACE FUNCTION knowledge.a_membership_event_follows_its_predecessor()`: the
  S1 rule plus `confirm` admitted iff the predecessor's `acceptance_basis` is
  `client_identified`, `NEW.state` equals the predecessor's state and
  `NEW.evidence_anchor_id IS NOT DISTINCT FROM` the predecessor's.

### 5.2 `record_links` and `lineage_write_requests`

- **`record_links`**: drop `a_lineage_row_is_local_operator_attested`; add
  `a_record_link_creator_is_known`: `(authority_class = 'local_operator' AND
  decision_channel IN ('local_cli', 'local_web')) OR (authority_class =
  'ordinary_reviewer' AND decision_channel IN ('remote_interactive', 'local_unattested'))`.
  The root keeps no client column; its creator's client is revision 1's.
- **`lineage_write_requests`**: `ADD COLUMN decision_channel text` and `ADD COLUMN
  asserting_client_id text` (null on every pre-S3.1 row; set at reservation for every
  later row, operator rows included). CHECK `a_lineage_write_request_writer_is_known`:
  `(decision_channel IS NULL AND asserting_client_id IS NULL) OR (decision_channel IN
  ('local_cli', 'local_web', 'local_unattested') AND asserting_client_id IS NULL) OR
  (decision_channel = 'remote_interactive' AND asserting_client_id IS NOT NULL AND
  char_length(asserting_client_id) BETWEEN 1 AND 256)`. Index
  `lineage_write_requests_by_writer (principal_id, decision_channel, asserting_client_id,
  created_at)`. Widen the capability CHECK (+ the 3 confirm names: 22),
  `a_completed_link_write_names_its_revision` (+ the 2 link confirms, `result_created IS
  NULL`) and `a_completed_project_link_write_names_its_event` (+
  `issues.project_links.confirm`, through `MEMBERSHIP_EVENT_CAPABILITIES`). `CREATE OR
  REPLACE FUNCTION knowledge.a_lineage_write_request_completes_once()` so the 2 writer
  columns are among those that may never change.

### 5.3 Existing S4 and audit tables

- **`intelligence_artifact_manifests`**: restate `manifest_schema_version` CHECK to `IN (1,
  2)`; `CREATE OR REPLACE FUNCTION knowledge.a_manifest_names_its_own_artifact()` so a
  schema-2 manifest is also checked to carry the key `lineage` (an object) and a schema-1
  manifest to carry no such key; every S4 condition is kept. No new column.
- **`audit_events`**: `capability_is_known` restated (BEFORE text a byte copy of
  `c5260943d933`'s AT text; AT text adds exactly the 4 section 7 names, sorted);
  `purpose_is_known` unchanged (no new purpose); `_CURRENT_AUDIT_CAPABILITIES` 240 → 244;
  schema-ahead precedent with `tests/schema/lineage_s31_schema_ahead_contract.py`.

No change to `issue_revisions`, `record_link_heads`, `record_link_revision_evidence`,
`lineage_evidence_anchors`, the commit-mark tables, the backfill tables,
`project_situations`, any native table or any index other than the one named.

### 5.4 Downgrade

`downgrade()` first refuses (`restrict_violation`) while any of these 11 clauses holds,
each alone sufficient and each pinned by its own case (R31-F07): (1) a
`record_link_revisions`, (2) an `issue_project_membership_events`, (3) an
`issue_responsibility_events` and (4) an `issue_responsibility_corrections` row with
`acceptance_basis = 'client_identified'`; (5) a `record_links` row whose `authority_class`
is `ordinary_reviewer`; (6) a `record_link_revisions` row and (7) an
`issue_project_membership_events` row with action `confirm`; (8) a `lineage_write_requests`
row naming a confirm capability; (9) a `lineage_write_requests` row with a client
`decision_channel`; (10) an `audit_events` row naming an S3.1 capability; (11) an
`intelligence_artifact_manifests` row with `manifest_schema_version = 2`. Only then it
restores every restated CHECK, the 4 replaced functions and the dropped
`a_lineage_row_is_local_operator_attested` CHECKs to their S4 texts byte for byte, and drops
the new CHECKs, index and columns. A downgrade therefore never discards a client fact, a
client id or a confirmation; dropping the writer columns of operator-only request rows
loses nothing the fact rows do not hold.

## 6. Authority, transaction and visibility

### 6.1 Derivation

`application/lineage_authority.py` keeps `lineage_authority` and
`attested_lineage_authority` (the latter now used only by the attested set) and adds:

```text
LineageProvenance(authority_class, decision_channel, acceptance_basis,
                  asserting_client_id: str | None, user_directed_claim: bool)
lineage_write_provenance(authorization, *, user_directed: bool) -> LineageProvenance
```

`lineage_write_provenance` derives the pair through `lineage_authority` (both allowlists
empty, unchanged); maps `local_operator` + `local_cli`/`local_web` to `user_confirmed`
(refusing `user_directed = True` with `invalid_request` / `user_directed`) and
`ordinary_reviewer` + `remote_interactive`/`local_unattested` to `client_identified`
(`asserting_client_id = authorization.authenticated_client_id` for `remote_interactive`,
else null); any other pair (unreachable today: `remote_operator_attested`) is
`internal_error`. It never raises `DeniedError`. The S1 composition refusals are kept: an
inconsistent composition is `internal_error`, a remote transport without a client is
`unsupported`.

### 6.2 Transaction and check order (S3 §6.3, extended)

**Open writes:**

1. Switch (`_lineage_plane`); strict parse (a payload naming `acceptance_basis`,
   `authority_class`, `decision_channel`, `asserting_client_id`, `user_directed_claim` or
   any S1 server-owned field is `invalid_request`).
2. `lineage_write_provenance` (section 6.1).
3. **Remote only** (section 6.4): the write-grant re-check, the composite native-grant
   check, then the visibility pre-check of every subject the request names or its
   `link_id` / `handoff_id` / Issue-and-Project pair addresses — before any row, the
   replay lookup and the rate count.
4. Request digest (section 4.9); reserve the request row with its writer columns. A replay
   returns here.
5. Commit mark (S3 §6.2 step 1b).
6. Locks, validation and write-specific checks exactly as S1–S3 (lock order S3 §6.2), the
   accepted-lineage rule (section 4.4) under the head lock.
7. Rate bounds (section 4.8), client writes only; for `issues.work.*` it precedes the native
   Task or Commitment create (RR1-F04). An identity answered `created: false` is **checked
   and counted**: it completes a client request row, so it passes the bound like any other
   write and counts toward later ones (pinned by `test_a_created_false_answer_is_checked_and_counted`).
8. The rows, each carrying the provenance of section 4.1; complete the request row; build
   the answer under the section 6.4 answer filter; commit; deferred triggers verify.

**Attested writes** (close, reopen, closed-Issue correction, backfill, confirm): S1 §6.1
unchanged — switch, `attested_lineage_authority` (`denied` before any row and before the
replay lookup), digest (the human-channel document), reservation, mark, then locks. A
confirm locks as the revision writers do (the link's Issues in context `FOR SHARE`, the
identity key, the head `FOR UPDATE`; for a Project link the S1 Project-link order), then
checks section 4.7.

### 6.3 Visibility

S3 §6.4 is unchanged and applies to every new read and key. Additions: a remote reader
sees `asserting_client_id` as `null` everywhere (section 4.3); the related read's records,
links and anchors follow the S3 family rule; the readiness `unreviewed_links` list
withholds an entry whose endpoint is invisible and sets `restricted` (S3 R3-F13 form);
`ready` is computed over everything. **Hidden items are never counted (R31-F10):** the
related read's 20-Issue cap per seed and its `issue_ids` range only over Issues visible to
the reader (an invisible Issue is never a candidate, S3 §6.4), and
`unreviewed_links_truncated` (like `blockers_truncated` and `contested_links_truncated`)
is computed over the visible entries only; only `ready` is computed over everything.

### 6.4 Remote write visibility and grants (R31-F01)

S3 §6.4 is the intra-Principal disclosure control for remote callers and, before S3.1,
applied only to reads, because no remote caller could pass attestation. For every open
write and every remote caller (`authorization.capability_grants is not None`):

1. **Write-grant re-check (defence in depth).** `require_write_grant(grants, capability)`,
   the write analogue of `_lineage_read`'s `require_read_grant`: a remote caller without a
   grant on the called capability for one of its permitted purposes is **`unsupported`**
   (`invoke` does not consult grants, G1-RD-008).
2. **Composites need the native create grant.** `issues.work.create_task` also needs a
   grant on `tasks.create` for `task_authoring`, and `issues.work.create_commitment` one on
   `commitments.create` for `commitment_authoring`; without it the composite is **`denied`**
   (no detail), so `issue_work_authoring` never becomes a native create grant.
3. **Hidden is absent.** With the caller's visibility `lineage_visibility(grants,
   capability)` (S3 §6.4 table; for `issues.project_links.*` also the S4 `project` family,
   `PROGRAM_FAMILY_READS`), and — for every open write on a semantic link or a membership
   (`records.associations.*`, `issues.memberships.*`, both composites) — **the `situation`
   family itself (RR1-F02)**: a remote caller without Issue visibility answers every such
   write exactly as absent (`not_found` / `link_id`, or the first named subject's detail)
   before any row, so the frozen-closed refusal and the Issue-context and Project
   qualification checks never disclose a hidden Issue. Then every subject in a family the
   caller cannot see answers exactly as an absent one — `not_found` with the same safe detail — read without locks before the
   reservation: every endpoint (`from_record`, `to_record`, `member`), every Issue
   (`issue_id`, `context_issue_id`), every evidence anchor's source family
   (`evidence_anchors`), a handoff's Commitment (`commitment_id`), a Project
   (`project_id`); for a `link_id`-addressed revision, the link root is read
   Principal-scoped and any invisible endpoint or context Issue answers `not_found` /
   `link_id`; for a `handoff_id`, an invisible Commitment or Issue answers `not_found` /
   `handoff_id`. An absent subject is refused later, at validation (step 6), with the same
   code and detail, and both are refused before the rate count, so neither consumes budget
   and no answer differs between them.
4. **Answer filter: withhold, and say so.** Every view in a remote caller's write answer is
   filtered by S3 §6.4: an anchor whose source family is invisible (possible only on an
   existing revision shown back, e.g. the `created: false` answer of an active identity) is
   withheld, and **every answer of the 14 open writes and the 3 confirms always carries a
   top-level `restricted: bool`** — `false` for every local caller, and for a remote caller
   true exactly when something was withheld (no count; the S3 R3-F13 form). A **replay**
   rebuilds its answer from the stored rows (S1 §6.3) and applies the current filter; a
   replay whose subject is now hidden is already refused by step 3, and the filter covers a
   now-hidden anchor. A write is never
   refused for a hidden anchor on a revision it did not write, because refusing would
   itself disclose it.
5. Local callers see every family (S3 §6.4), unchanged.

## 7. Capabilities

4 new `Capability` members (229 → 233; audit vocabulary 240 → 244); **no new purpose**
(60). All 4 are `_SCOPELESS`, family `records` or `issues` → feature `lineage`, join
`_LINEAGE_CAPABILITIES` (30 → 34) and are `CHATLLM_OPERATOR_DECISION_REQUIRED` (37 → 41)
with rationale "record lineage S3.1; exposure is an operator decision (ADR-015, OD-07)".
The 3 confirms are in `_WRITE_CAPABILITIES`, `_IDEMPOTENT_REMOTE_CAPABILITIES` and
`_OPERATOR_ONLY` (operator kind, section 7.13: a remote caller is never attested), and not
additive.

| Capability | W/R | Purpose | Idempotency / authority | Purpose of the call |
| --- | --- | --- | --- | --- |
| `records.associations.confirm` | W | `record_lineage_authoring` | key + `expected_revision`, attested | promote a client-identified semantic link |
| `issues.memberships.confirm` | W | `issue_authoring` | key + `expected_revision`, attested | promote a client-identified membership |
| `issues.project_links.confirm` | W | `issue_authoring` | key + `expected_membership_revision`, attested | promote a client-identified Project-link event |
| `records.lineage.related` | R | `record_lineage_read` | — (remote grant re-check) | related records of 1..25 seeds |

### 7.1 Open writes (deltas to S1–S3 §7)

Every open write's request gains `user_directed?: bool` (default `false`; the field
documentation of section 7.12). Requests, answers and refusals are otherwise unchanged,
except: no open write answers `denied` for want of attestation; a cross-writer key reuse
answers `conflict` / `idempotency_key` (section 4.9;superseded by section 12.1 N2-01: the answer is `conflict` / `idempotency_conflict`); a client past a budget answers
`rate_limited` / `lineage_write_budget`; a client revision of accepted lineage answers
`denied` (section 4.4); a remote caller's hidden subject answers like an absent one and its
answer carries `restricted` (section 6.4); and every answer's views carry the section 4.3
labels. `issues.create` and `issues.update` gain no field (section 12, D-13).

### 7.2 `records.associations.confirm` and `issues.memberships.confirm`

**In:** `{link_id, expected_revision, idempotency_key, reason (1..2000)}`; **out:**
`{association, replayed}` (`issues.memberships.confirm` answers `{membership, replayed}`,
its S1 key). Order: S1 §3.2 `link_id` checks (`not_found` / `link_id` alike for absent and
foreign; wrong kind `invalid_request` / `link_id`), the closed-Issue refusal (`conflict` /
`state`), CAS (`conflict` / `stale_version`), section 4.7 (`conflict` / `state`).

### 7.3 `issues.project_links.confirm`

**In:** `{issue_id, project_id, expected_membership_revision, idempotency_key, reason
(1..2000)}`; **out:** `{project_link, replayed}`. The `issues.project_links.end` order
(S1), then section 4.7.

### 7.4 `records.lineage.related`

**In:**

```text
{seeds: [RecordRef] (1..25, distinct), max_depth? (1..3, default 2),
 acceptance_bases? ([AcceptanceBasis], 1..2, distinct; default both),
 relation_types? ([RelationType], 1..8, distinct; default all),
 known_at?, valid_at?, page_size? (10..100), cursor?}
```

A malformed, duplicate, empty or oversize list is `invalid_request` naming the field
(`seeds`, `acceptance_bases`, `relation_types`); `cursor` without `page_size` is
`invalid_request` / `cursor`.

**Algorithm** (the S3 §7.2 machinery, reused: one bounded result recomputed per page):

1. **Seeds.** Each seed is checked in the S1 §3.2 order and visibility (S3 §6.4); any
   absent, foreign, invisible or not-known-at-the-cut seed answers `not_found` / `seeds`
   for the whole request (absent and hidden alike). Seeds are records at depth 0.
2. **Cut.** S3 §3.4: `T_k`, `T_v`, `W(T_v)`, the native cut `N`; every link at its
   revision at `W(T_v)`; live = `active` or `contested`. A link whose selected revision's
   `acceptance_basis` is not in `acceptance_bases`, or whose relation is not in
   `relation_types`, is **neither followed nor emitted**.
3. **Expansion, per seed in request order.** (a) *One hop*: every live link incident to
   the seed's pair set (S1 §7.2), any context, adds its far endpoint at depth 1. (b)
   *Issue-confined*: for each **visible** Issue matching the seed (S1 §7.2 step 2; at most
   20 per seed, in `issue_id` `COLLATE "C"` order; more visible ones set
   `truncated_budget`; an invisible Issue is never a candidate and never counted), the S3 §7.2
   step 3 breadth-first expansion from the seed under that Issue to `max_depth`, the Issue
   context fixed per state, so a shared Meeting, Project, Series or participant never
   bridges 2 Issues (AT-006 holds). No other traversal exists.
4. **Union and paths.** A record's `depth` is its least depth over seeds; its
   `reached_from` / `reached_via` (S3 §7.1) are those of the first reaching step in
   `(depth, seed position, Issue order, S3 §7.2 step 4 tie-breaks)`; `seeds` lists the
   0-based positions of every seed that reached it; `issue_ids` lists the visible Issues
   under which it was reached (at most 20, sorted).
5. **Budgets** (whole query, all seeds, all pages): the S3 `MAX_LINEAGE_NODES` (250) and
   `MAX_LINEAGE_EDGES` (400); per page `page_size` items and `MAX_LINEAGE_BYTES`; a 2000 ms
   traversal deadline per page and the 2000 ms per-statement timeout (S3 §7.2 step 5,
   same consequences: `truncated_budget`, deadline ends paging, a statement timeout is
   `unavailable`).
6. **Order and paging.** Records `(depth, family, record_id)`, then typed links by
   `link_id`, then virtual edges by `(meeting_id, version_number)`; the S3 §5 cursor
   (bound to `records.lineage.related` and this request, with the grant scope digest and
   generation), checked in the S3 §7.2 step 7 order; a grant change between pages answers
   `scope_changed_restart_required`.
7. **Hidden data is never counted** (S3 §6.4): an invisible record is not emitted, not
   expanded and not counted; a typed link is emitted only when both endpoints are; an
   invisible anchor is dropped; `restricted_evidence` says something was withheld.
8. **Digest.** `related_sha256 = sha256(LINEAGE_RELATED_DIGEST_PREFIX +
   canonical_json(D))`, `D = {"schema_version": 1, "seeds", "max_depth",
   "acceptance_bases", "relation_types", "records", "links", "virtual_edges",
   "complete_state", "qualifiers"}` over the **whole** bounded result (every page's
   items), without the read stamps `known_at`, `valid_at`, `lineage_valid_at`,
   `native_cut_at`, `next_cursor`; the same value on every page of one cursor chain. A read
   with an explicit `known_at` (so `N = known_at`) and unchanged visibility, native
   resolution and evidence availability reproduces it.

**Out:**

```text
{seeds, records: [RelatedRecordView], links: [AssociationView], virtual_edges: [VirtualEdgeView],
 complete_state, qualifiers, known_at, valid_at, lineage_valid_at, native_cut_at,
 related_sha256, next_cursor}
RelatedRecordView = LineageNodeView keys + seeds: [int] + issue_ids: [sit_]
```

Links carry their evidence anchors (exact version, offsets, role, availability — never a
digest, S1 F11) and the section 4.3 labels, so a client can cite and qualify them.
`related_sha256` is a digest of metadata the reader can already read; it carries no
source or passage digest.

### 7.5 `issues.closure_readiness` (widened) — the gap read

The answer gains `unreviewed_links: [UnreviewedLinkView]` (at most `MAX_UNREVIEWED_LINKS
= 100`, by `link_id`) and `unreviewed_links_truncated: bool`; `ready` is false while the
unreviewed set (section 4.6) is non-empty. `UnreviewedLinkView = {link_id, kind,
relation_type, member_role, lifecycle_state, revision_no, action, user_directed_claim,
recorded_at}`. With the existing `blockers` (native state, missing, unavailable,
contradicted and **stale** resolution evidence) and `contested_links`, this one read
answers the gaps a client reports: unsatisfied mandatory members, stale evidence,
contested links and unreviewed client facts. Client facts outside any Issue are found
with `records.lineage.related` and `acceptance_bases: ["client_identified"]`.

**Suggestions and proposals.** There is no parallel proposal plane: a client's committed
`client_identified` fact **is** the lineage proposal — stored in the one ledger, labelled,
never accepted-grade, holding the close, and promoted only by a human `confirm`. A client
that wants to suggest without committing writes nothing (it reports the suggestion in its
own output) or uses another plane's existing proposal capability for that plane's facts;
none of those is changed.

### 7.6 Labels on existing lineage reads (lockstep widening)

Each view below gains `user_directed_claim` and `asserting_client_id`, and its
`acceptance_basis` admits `client_identified`:

- `AssociationView` (`records.lineage` `typed_edges`, `issues.read` memberships, every link
  write answer, `records.lineage.related` `links`); `LinkHistoryRevisionView`
  (`records.associations.history`; `action` admits `confirm`);
- `ProjectLinkView` (`issues.read` `project_links`, the Project-link write answers);
- `HandoffView` and `HandoffCorrectionView` (`issues.handoffs.list`, the handoff write
  answers; `HandoffCorrectionView` gains `acceptance_basis` too);
- `TimelineEntryView` (`issues.timeline`): gains `acceptance_basis`, `user_directed_claim`
  and `asserting_client_id`, non-null exactly for the `project_link`, `membership`,
  `association`, `handoff` and `handoff_correction` kinds (null for `issue_revision` and
  `native_event`); `action` admits `confirm`.

`IssueRevisionView`, `IssueListEntry` and the S4 Program and Commitment v2 views gain
nothing.

### 7.7 Errors (additions to S1–S4 §7)

| Situation | Code / safe detail |
| --- | --- |
| `user_directed: true` from the human channel | `invalid_request` / `user_directed` |
| an open write re-sending another writer's key | `conflict` / `idempotency_key` (superseded by section 12.1 N2-01: the answer is `conflict` / `idempotency_conflict`) |
| a client past a section 4.8 bound | `rate_limited` / `lineage_write_budget` |
| confirm of a `user_confirmed` or `contested` head, or of a Project-link event that is not `client_identified` | `conflict` / `state` |
| confirm, close, reopen, closed-Issue correction or backfill by a non-attested caller | `denied` (unchanged rule) |
| unreviewed link in the review scope at close | `conflict` / `closure_gate` |
| a client revision of a `user_confirmed` fact other than `contest` of an active semantic link | `denied` |
| remote open write without a grant on its own capability | `unsupported` |
| remote composite without the native `tasks.create` / `commitments.create` grant | `denied` |
| remote write naming or addressing a subject in an invisible family | `not_found` with the subject's detail, as absent |
| related: seeds malformed, duplicate, empty, above 25; a bad filter list | `invalid_request` / `seeds`, `acceptance_bases`, `relation_types` |
| related: a seed absent, foreign, invisible or not known at the cut | `not_found` / `seeds` |
| malformed `lineage_context_ref`, or one on a collector or researcher artifact | `invalid_request` / `structured_content` |

New `SafeDetail` members `user_directed`, `lineage_write_budget`, `seeds`,
`acceptance_bases`, `relation_types` (reuse any existing member with the same token). New
`RateLimitedError(ApplicationError)` with `code = ErrorCode.RATE_LIMITED`.

### 7.8 S4 Program overview (delta)

An Issue↔Project link is **unreviewed** exactly when the latest
`issue_project_membership_events` row for `(principal, project, issue)` has
`acceptance_basis = 'client_identified'`, **in any state** (`active` or `ended`), and the
Issue's `state` is not `closed` (`open`, `active` or `suspended`). The `ended` case is the
point (R31-F03): `_OUTSTANDING_ISSUE_LINKS` counts only active latest events, so without it
a client's end of a link would silently shrink `issue_outstanding`. A closed Issue cannot
contribute to `issue_outstanding` whatever its link state (the S4 R4-F16 reasoning), so its
unreviewed links are neither counted here nor gating. In the S4 snapshot (S4 §6.3), the
legacy-link statement also counts, per resolved Project, the pairs meeting this predicate
(`unreviewed_issue_links`). Such a
link is neither counted nor dropped: the Project's `issue_outstanding` is `not_reportable`
with the **existing** reason `issue_link_unverified`, and so is every Issue total of a
scope holding it — exactly the legacy-link rule (S4 §3.3, R4-F02). The answer gains
`per_project[].unreviewed_issue_links: int|null`, `denominator.unreviewed_issue_links` and
`project_ids_with_unreviewed_issue_links` (Issue-family visibility as the legacy keys);
`PROGRAM_CALCULATION_VERSION` becomes `"program-overview-v2"`;
`PROGRAM_METRIC_SCHEMA_VERSION` stays 1 (the metric catalogue is unchanged). A confirmed
link (latest event `user_confirmed`) is reported as in S4. No `NotReportableReason` is
added.

### 7.9 `reports.commit` (delta) and the schema-2 manifest

**The block.** A synthesizer, reporter or morning-brief artifact written from a related
read puts, under the reserved top-level `structured_content` key `lineage_context_ref`,
exactly `{"block_schema_version": 1, "seeds": [RecordRef] (1..25), "max_depth",
"acceptance_bases", "relation_types", "known_at": <the answer's known_at, S4 §5.3 instant
format>, "related_sha256": <64-hex>}`. It is interpreted **only when
`records.lineage.related ∈ available_capabilities()`** (else it is ordinary content and
S4 behaviour is byte-identical); then a malformed block, or one on a collector or
researcher artifact, is `invalid_request` / `structured_content` (a pure check, first, as
S4 D-38).

**The recompute** (the S4 §7.4 order, reused): after the replay lookup and every remaining
refusal check, immediately before the commit's first write, and only when
`records.lineage.related` admits the committing caller (its remote grant re-check and the
visibility of every seed), the server runs the section 7.4 computation for the block's
seeds, filters and `known_at` (`valid_at` omitted) **with the committing caller's
visibility**, as one unpaged bounded result, on the request's own work connection (a
lineage read at a cut ≤ `H` reads immutable facts; no snapshot pool is needed), under a
**5000 ms total budget** with each statement at `min(2000, remaining)` ms (the S4 D-36
deadline hook). Outcome: `verified_at_commit` when its `related_sha256` equals the
claim, else `changed_since_read`; any budget, timeout, missing seed or a `known_at` after
the horizon is **recorded** as `recompute_failed` with its `LineageRecomputeFailure`
token and never refuses the commit; not admitted ⇒ `not_attempted`. A replay never
recomputes. Nothing about it appears in the `reports.commit` answer.

**Schema-2 manifest.** `M` (S4 §5.3) is unchanged — and stays `manifest_schema_version: 1`,
byte for byte — for every artifact whose block is absent or not interpreted **and** whose
upstreams carry no lineage gate. Otherwise `manifest_schema_version: 2` and `M` gains
exactly 1 key, `"lineage": LineageManifestSection | null`, and `release_requirement`
gains `lineage_grant: bool` and `lineage_families: [RecordFamily]` (sorted):

```text
LineageManifestSection = {block_schema_version: 1, seeds, max_depth, acceptance_bases, relation_types,
  claimed_known_at, claimed_related_sha256, verification_state, recompute_failure|null,
  families_seen|null, server|null}
server = {related_sha256, known_at, complete_state, qualifiers, record_count, link_count,
  links_by_acceptance_basis: {client_identified: int, user_confirmed: int},
  user_directed_claims: int}
```

`server` and `families_seen` (the S3 §6.4 families visible to the committer during the
recompute) are non-null exactly for `verified_at_commit` and `changed_since_read`. So a
report can state, bound by the server, "N related links, M client-identified and
unreviewed, K of them claimed user-directed" — `user_directed_claims` is a count of
claims, never a verified fact.

**Release (FR4-F01 extended).** A schema-2 manifest's own lineage gate is: `lineage` null
or `not_attempted` ⇒ nothing; otherwise `lineage_grant: true` and `lineage_families` =
the seeds' families ∪ `families_seen`. `release_requirement` unites that gate, the S4
Program gate and every upstream's recorded requirement (a schema-1 upstream contributes
`lineage_grant: false`, no families), transitively; a downstream of a lineage-gated
upstream is schema 2 for that reason alone. `reports.manifest` releases a manifest in full
to a remote reader only when the reader satisfies the Program part (S4 §6.2) **and**, when
`lineage_grant`, holds a `records.lineage.related` grant for `record_lineage_read` and sees
every family in `lineage_families`; otherwise `restricted_evidence` with the text and the
digest `null` (S4 R4-F20). A local reader sees it all. `reports.manifest`'s answer shape
is unchanged (`manifest_schema_version` now `1|2`).

### 7.10 Admission switch

S1 §7.5 unchanged: `MY_PA_LINEAGE_ENABLED` (default off) withholds all 34 lineage
capabilities; every new handler calls `_lineage_plane` first. With the switch off a
`lineage_context_ref` key is ordinary content and every manifest is schema 1, except
a downstream of a lineage-gated upstream recorded while the switch was on, which stays
schema 2 (section 12.1 N4-02).

### 7.11 Remote exposure as configuration: the profile opt-in

`contracts/mcp_database_profiles.py` gains 2 closed, code-owned sets:

- `MCP_PROFILE_OPT_IN_READ_CAPABILITIES`: `records.lineage`, `records.lineage.related`,
  `records.associations.history`, `issues.read`, `issues.list`, `issues.history`,
  `issues.timeline`, `issues.handoffs.list`, `issues.closure_readiness`,
  `meetings.notes.versions`, `meetings.notes.read_version`, `commitments.v2.read`,
  `commitments.v2.list`, `commitments.v2.search`, `commitments.v2.waiting_on`;
- `MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES`: the 14 open writes and `issues.create`,
  `issues.update`.

**Never admissible:** `issues.close`, `issues.reopen`, the 3 confirms (attested: a profile
client is never the human channel), `records.backfill.*` (operator-only),
`programs.members.resolve` / `programs.overview` (a profile composition builds no Program
read engine and never serves them, S4 D-46), and **`reports.manifest`** (R31-F04: its table
`intelligence_artifact_manifests` is an `intelligence_` object, which
`mcp_object_grants.py` refuses to grant to an MCP role under every classification, so it
can never succeed on a profile service; recorded in section 11).

A new setting `mcp_database_profile_opt_ins: frozenset[str]` (env
`MY_PA_MCP_DATABASE_PROFILE_OPT_INS`, comma-separated, **default empty**, fails closed: a
name outside the 2 sets, or any name while `MY_PA_MCP_DATABASE_PROFILES_ENABLED` is off,
is a `SettingsError`). `profile_capabilities(profile, opt_ins=frozenset())` adds the
opted-in read names to both profiles and the opted-in write names to `rw` only.
**`surviving_write` considers the opted-in write names too** (R31-F04):
`McpDatabaseServices.access` selects `READ_WRITE` for an rw-listed client when, and only
when, a surviving grant names a capability in `MCP_PROFILE_WRITE_CAPABILITIES ∪ (opted-in
write names)` for a permitted purpose and writes are allowed; otherwise an rw-listed client
granted only lineage writes would get the `ro` profile and its opted-in writes would never
appear. With the default it is byte-identical to #339, and it **never issues a grant**:
`access` still intersects the ceiling with the client's own grants
(`src/my_pa/bootstrap/mcp_database_profiles.py:156`). **No privilege mechanism exists yet
for the lineage tables:** they already exist, and `mcp_object_grants.py` grants only around
a new `CREATE` and never re-grants an existing object. Until an operator applies a
separately reviewed privilege mechanism for existing objects (section 11, section 13), an
opted-in lineage call on a profile service fails closed (`internal_error`, no row written),
pinned by `test_an_opted_in_lineage_write_on_a_profile_service_fails_closed_and_writes_nothing`. `ops/runbooks/gateway-operations.md` gains the
variable. No production setting, profile, grant or deployed-client grant changes.

### 7.12 Client guidance

- **Tool descriptions** (each command's first docstring line, `_summary`), pinned
  verbatim by `test_lineage_tool_descriptions_carry_the_client_guidance`, one sentence
  each, for example: `records.associations.assert` — "Commit a typed link you identified
  from cited exact evidence or the user's instruction; it is recorded client-identified
  and unreviewed, and shared projects, dates, names or similar text are not evidence of
  it." `records.lineage.related` — "Read records related to up to 25 seeds through
  recorded lineage, with each link's evidence and provenance label; pass known_at to
  reproduce a read." Each confirm — "Operator only: confirm a client-identified lineage
  fact as user-confirmed by appending a revision." The worker writes one for every
  lineage write and read, within 240 characters, and rewrites the docstring **bodies** of
  the 14 open commands, which today state "Local operator only." (for example
  `AssertRecordAssociation`), to the S3.1 rule: open to any admitted caller, recorded
  `client_identified` unless from the local operator, never accepted-grade, rate-bounded,
  and unable to remove accepted lineage (section 4.4).
- **Field documentation** through the existing command field-documentation path:
  `user_directed` — "Set true only when the user explicitly instructed this write; it is
  stored as an unverified claim and changes no gate or label."; `evidence_anchors` — "Cite
  the exact stored version (mnote_ or capver_) and code-point offsets of the stored body;
  read it with meetings.notes.read_version first."
- **`capabilities.get`** lists the 4 new names with their availability and
  `operator_only` (true for the 3 confirms, section 7.13); it gains **no** key (a v1
  shape; section 12, D-10).
- **Docs page** `docs/operations/record-lineage-client-guidance.md` (routed from
  `docs/operations/README.md`): when to commit (a relationship identified from exact
  cited evidence, or an explicit user instruction — then `user_directed: true`); how to
  cite (exact note or Capture version, code-point offsets of the stored, unnormalized
  body, the right `EvidenceRole`); when not to (similarity, a shared Project, Series,
  date, participant or name is never causation — OD-05; never infer origin from
  discussion); how to read labels (`client_identified` is unreviewed and never
  accepted-grade; `user_directed_claim` is the client's word; `user_confirmed` is the
  human channel); that only the operator confirms; the rate bounds and replay rule; and
  how to pin `known_at` for a reproducible report reference. It also states **the compact
  facade call shape** (section 7.13): `my_pa.describe` to find a capability and its exact
  remote input schema, then `my_pa.read` or `my_pa.write` with `{"capability": <name>,
  "arguments": <that schema's document>}`, where the document is `{"payload": {...}}` with
  **no** `idempotency_key`, purpose or provenance field (the server derives the key and the
  purpose). Its 2 worked examples, written against the published remote schemas
  (R31-F05):

```json
{"name": "my_pa.describe", "arguments": {"feature": "lineage", "kind": "write"}}
{"name": "my_pa.describe", "arguments": {"capability": "records.associations.assert"}}
{"name": "my_pa.write", "arguments": {"capability": "records.associations.assert", "arguments": {"payload": {
  "relation_type": "originated_from",
  "from_record": {"family": "commitment", "record_id": "cmt_EXAMPLE0001"},
  "to_record": {"family": "meeting_note_version", "record_id": "mnote_EXAMPLE0001"},
  "evidence_anchors": [{"family": "meeting_note_version", "root_id": "mtg_EXAMPLE0001",
    "version_kind": "immutable_version", "version_id": "mnote_EXAMPLE0001",
    "passage_start_cp": 120, "passage_end_cp": 184, "role": "origin"}],
  "user_directed": true}}}}
```

```json
{"name": "my_pa.read", "arguments": {"capability": "tasks.search", "arguments": {"payload": {"query": "crane permit"}}}}
{"name": "my_pa.read", "arguments": {"capability": "records.lineage.related", "arguments": {"payload": {
  "seeds": [{"family": "task", "record_id": "tsk_EXAMPLE0001"}, {"family": "task", "record_id": "tsk_EXAMPLE0002"}],
  "max_depth": 2, "acceptance_bases": ["user_confirmed", "client_identified"]}}}}
```

  The first commits a client-identified `originated_from` link from a Commitment to the
  exact note version and code-point passage it came from (the passage is of the stored
  body read with `meetings.notes.read_version`; `source_sha256` and `passage_sha256` are
  optional and, when given, must match; superseded by section 12.1 N3-06: the parser
  requires both, and the docs page's example carries them). The second maps each `tasks.search` hit's
  `task_id` to a seed `{"family": "task", "record_id": <task_id>}` and reads what recorded
  lineage relates to them. Each `{"name", "arguments"}` line is the params of one MCP
  `tools/call` (RR1-F06); the
  page writes every example as a fenced `json` block of such lines, and
  `test_the_guidance_examples_validate_against_the_remote_schemas` parses every block and
  validates each inner `arguments` against `remote_tool_schema` of the named capability's
  published tool (and each describe document against the describe schema).

### 7.13 Part D — catalog, kinds and the compact facade

**Kinds (deliberate, section 3.5 corrected).**

- The 14 open writes stay **`write`** kind: their purposes are in `_WRITE_PURPOSES`, so
  `is_remote_write` is true; they are published to a remote client only while remote writes
  are enabled and only when granted, and through the facade only via `my_pa.write`.
- `issues.close`, `issues.reopen` and the 3 confirms join **`_OPERATOR_ONLY`**
  (`domain/identity/operation.py`) and so become **`operator`** kind with
  `operator_only: true` in `capabilities.get`: each is attested to the local operator
  surface, so no remote caller can ever satisfy it, and `remote_tool_names` and the facade
  now withhold it instead of publishing a write a remote caller can only be `denied`. The
  backfill pair stays `operator`. `issues.update` stays `write` (only its closed-Issue
  correction is attested, in the handler). Every read stays **`read`**.
- `is_remote_write` and `_WRITE_PURPOSES` are unchanged; no purpose moves.

**Catalog.** The 4 new commands' first docstring lines are their summaries (section
7.12); no summary may be null (`test_every_lineage_capability_has_a_catalog_entry`). MCP
`idempotent_hint` becomes true for every lineage write (the 22 names of
`LINEAGE_WRITE_CAPABILITIES`): `tools.py` derives it from a new
`adapters/remote_request.py::is_remote_idempotent(capability)` = in
`_SERVER_REPLAY_REMOTE_CAPABILITIES` **or** in `LINEAGE_WRITE_CAPABILITIES`; every
non-lineage tool's annotations are unchanged (section 12, D-17). `_FEATURE_BY_FAMILY`
needs no new family: `records.lineage.related` and the confirms are `lineage`.

**Capability table** (current = measured at the basis; profile entry = section 7.11 opt-in
set, never a default ceiling member):

| Capability | `TOOLS` | Feature | Current kind | New kind | Profile entry |
| --- | --- | --- | --- | --- | --- |
| `issues.create` | yes | lineage | write | write | write opt-in |
| `issues.update` | yes | lineage | write | write | write opt-in |
| `issues.read` | yes | lineage | read | read | read opt-in |
| `issues.list` | yes | lineage | read | read | read opt-in |
| `issues.history` | yes | lineage | read | read | read opt-in |
| `issues.timeline` | yes | lineage | read | read | read opt-in |
| `issues.closure_readiness` | yes | lineage | read | read | read opt-in |
| `issues.close` | yes | lineage | write | **operator** | never |
| `issues.reopen` | yes | lineage | write | **operator** | never |
| `issues.project_links.add` | yes | lineage | write | write | write opt-in |
| `issues.project_links.end` | yes | lineage | write | write | write opt-in |
| `issues.project_links.confirm` (new) | new | lineage | — | operator | never |
| `issues.memberships.add` | yes | lineage | write | write | write opt-in |
| `issues.memberships.end` | yes | lineage | write | write | write opt-in |
| `issues.memberships.correct` | yes | lineage | write | write | write opt-in |
| `issues.memberships.confirm` (new) | new | lineage | — | operator | never |
| `issues.handoffs.record` | yes | lineage | write | write | write opt-in |
| `issues.handoffs.correct` | yes | lineage | write | write | write opt-in |
| `issues.handoffs.list` | yes | lineage | read | read | read opt-in |
| `issues.work.create_task` | yes | lineage | write | write | write opt-in |
| `issues.work.create_commitment` | yes | lineage | write | write | write opt-in |
| `records.associations.assert` | yes | lineage | write | write | write opt-in |
| `records.associations.correct` | yes | lineage | write | write | write opt-in |
| `records.associations.end` | yes | lineage | write | write | write opt-in |
| `records.associations.contest` | yes | lineage | write | write | write opt-in |
| `records.associations.reinstate` | yes | lineage | write | write | write opt-in |
| `records.associations.confirm` (new) | new | lineage | — | operator | never |
| `records.associations.history` | yes | lineage | read | read | read opt-in |
| `records.lineage` | yes | lineage | read | read | read opt-in |
| `records.lineage.related` (new) | new | lineage | — | read | read opt-in |
| `records.backfill.plan` | yes | lineage | operator | operator | never |
| `records.backfill.report` | yes | lineage | operator | operator | never |
| `meetings.notes.versions` | yes | meetings | read | read | read opt-in |
| `meetings.notes.read_version` | yes | meetings | read | read | read opt-in |
| `programs.members.resolve` | yes | programs | read | read | never (not served under a profile, S4 D-46) |
| `programs.overview` | yes | programs | read | read | never (same) |
| `commitments.v2.read` | yes | work | read | read | read opt-in |
| `commitments.v2.list` | yes | work | read | read | read opt-in |
| `commitments.v2.search` | yes | work | read | read | read opt-in |
| `commitments.v2.waiting_on` | yes | work | read | read | read opt-in |
| `reports.manifest` | yes | reports | read | read | never (an `intelligence_` table; R31-F04) |

Outside the profiles, the default remote MCP path admits a name to a client only through
the operator's grants (section 3.3); the ChatLLM classification stays
`CHATLLM_OPERATOR_DECISION_REQUIRED` for every lineage-plane name (the backfill pair
`CHATLLM_CONTROL_PLANE_EXCLUDED`), so the ChatLLM gateway profile planner still never
desires, adds or diffs one as missing. No production grant, profile or opt-in changes.

**End to end through the facade** (pinned by section 10's facade rows, **on the default
remote MCP path** — the full-role service, a synthetic remote client, compact publication
on, the lineage switch on, remote writes on, durable grants on the named capabilities; no
restricted profile): (a) `my_pa.describe` lists
exactly the eligible lineage names with their summary, kind, feature and `idempotent`, and
lists none that is not admitted; (b) `my_pa.read` invokes `records.lineage.related` and
`issues.closure_readiness`, and `my_pa.write` invokes `records.associations.assert` and
`issues.memberships.add`, each with the canonical strict schema (an unknown key, a
`idempotency_key` or a provenance field is `invalid_request`) and each write recorded
`client_identified` with the client id; (c) `my_pa.read` naming a write, or `my_pa.write`
naming a read, is `invalid_request`; (d) a lineage name not admitted (no grant, not
opted in, switch off, or `operator` kind such as `issues.close`) is absent from describe
and `unsupported` at call, answered exactly like a nonexistent name; (e) the interaction
log records each facade call with its canonical target as `capability`; (f) the
`capabilities.get` manifest lists all 41 lineage-plane names with `operator_only` equal to
`is_operator_only`, the regenerated `success.json` equals the served answer, and
`gateway.json` keeps its 110 entries and every lineage decoder's closed sets equal the
server vocabulary. **Profile path:** a separate row composes the #339 restricted services
with the lineage names opted in and asserts that a granted opted-in write answers
`internal_error` and writes no row (the fail-closed state of section 7.11). **ChatLLM
gateway path (R31-F08):** a ChatLLM client with compact publication and only the
planner-provisioned grants of the ChatLLM data profile sees no lineage name in
`my_pa.describe`, gets `unsupported` from `my_pa.read` / `my_pa.write` naming one, and the
profile planner's diff desires, adds and reports missing no lineage-plane name.

## 8. Old-client rule and compatibility

- **Non-lineage v1 shapes are byte-identical**: every `tasks.*`, `commitments.*` (v1),
  `constraints.*`, `meetings.*`, `continuity.*`, `capture.*`, `reports.*` (v1),
  `record_events.*` request and answer, and `capabilities.get`'s keys. The S3 payload
  pin over the 192 non-lineage, non-S4 tools stays equal (the 4 new names are lineage
  names, so excluded like the rest); no purpose is added, so the envelope purpose enum is
  unchanged.
- **Lineage contracts are widened additively in lockstep** (the S2 §7.4 and S3 §8.1
  precedent; every lineage capability is behind `MY_PA_LINEAGE_ENABLED`, default off, holds
  no grant and has no deployed client): the request field `user_directed`; the section
  7.6 keys; `client_identified` and `confirm` in their closed sets; the readiness keys of
  section 7.5. **For a Principal holding no `client_identified` row, every lineage answer
  equals its S4 answer plus the added keys with their neutral values**
  (`user_directed_claim: false`, `asserting_client_id: null` for operator facts,
  `unreviewed_links: []`, `unreviewed_links_truncated: false`, and `restricted: false` on
  the 14 open-write and 3 confirm answers), pinned by
  `test_s31_answers_without_client_rows_differ_from_s4_only_by_the_added_keys`.
- **S4 manifests:** schema 1 unchanged byte for byte whenever no lineage section or gate
  applies; the S4 golden vectors stay. **S4 overview:** the 3 added keys and the
  calculation version (section 7.8) change the overview digest; the S4 overview golden
  vectors are regenerated in lockstep (an admitted edit, section 10).
- **The strict web client:** `gateway.json` keeps its 110 entries (no new route); the
  `records.lineage`, `issues.read` and `issues.timeline` decoders widen in lockstep
  (the keys and closed sets above), the related-Issue panel and the Issue view say
  "identified by a connected client (unreviewed)" for `client_identified` and "user said
  they directed it (not verified)" for a true claim; `success.json` is regenerated for
  `capabilities.get` (229 → 233 rows, and `operator_only: true` now on `issues.close` and
  `issues.reopen`) and the widened fixtures; `web/README.md`'s count moves 229 → 233.
- **MCP tool annotations:** the 22 lineage write tools gain `idempotentHint: true`; the
  `issues.close` / `issues.reopen` tools leave the remote publication (operator kind);
  every non-lineage tool's annotations and payload schema are unchanged.
- Any later change to a deployed contract needs a negotiated version (S1 §8).

## 9. File plan, registration and the work split

- `domain/lineage/vocabulary.py` (section 4), `domain/lineage/closure.py`
  (`in_review_scope`, the unreviewed condition), `domain/lineage/canonical.py` (the writer
  key of the client digest document, section 4.9), `domain/program/reportability.py` and
  `domain/program/vocabulary.py` (section 7.8), `domain/intelligence/source_manifest.py`
  (the block, the schema-2 `M`, the lineage release requirement and its 2 enums).
- `application/lineage_authority.py` (section 6.1), `application/lineage_rate.py` (new:
  the section 4.8 check), `application/record_lineage.py` (open writes, link confirm, the
  related read, the label projection), `application/issues.py` (Project-link writes and
  confirm, the review scope in close and readiness), `application/issue_handoffs.py`,
  `application/issue_work.py`, `application/lineage_visibility.py` (the client-id rule),
  `application/program_work.py` (section 7.8), `application/intelligence.py` (the lineage
  block check and recompute callback), `application/errors.py` (`RateLimitedError`, 5
  `SafeDetail` members), `application/commands.py`, `adapters/normalization.py`,
  `application/service.py` (handlers, the provenance call in the 14 open handlers, the
  4 new handlers).
- `infrastructure/persistence/record_lineage.py` (`review_scope_links`, related-read
  statements, provenance columns), `infrastructure/persistence/issues.py`
  (request-row writer columns, the rate counts, Project-link confirm),
  `infrastructure/persistence/issue_handoffs.py`, `infrastructure/persistence/program_metrics.py`
  (the unreviewed count in the legacy-link statement), `infrastructure/persistence/intelligence.py`
  (the schema-2 manifest).
- Part D: `domain/identity/operation.py` (`_OPERATOR_ONLY`), `adapters/remote_request.py`
  (`is_remote_idempotent`, `_CLIENT_BOUND_KEY_CAPABILITIES`), `adapters/mcp/tools.py`
  (the annotation derivation), no change to `adapters/mcp/chatllm_gateway.py` beyond a test
  of `_FEATURE_BY_FAMILY` coverage.
- `contracts/v1/record_lineage.py`, `contracts/v1/issues.py`, `contracts/v1/issue_timeline.py`,
  `contracts/v1/programs.py`, `contracts/v1/report_manifests.py` (section 7.6–7.9 shapes),
  `contracts/ports.py`, `contracts/mcp_database_profiles.py`,
  `bootstrap/settings.py` and `bootstrap/mcp_database_profiles.py` (section 7.11),
  `domain/identity/operation.py` / `chatllm_capability_policy.py` registrations.
- Web: `web/src/lib/api/decode/capabilities/{records.lineage,issues.read,issues.timeline}.ts`,
  `web/src/components/work/related-issues.tsx`, `web/src/components/issues/*`
  (words only), `success.json`, `web/README.md` (any new web file is `git add -f` and
  `git ls-tree` checked).
- Docs: `docs/operations/record-lineage-client-guidance.md` and its README row; the
  section 10 / 12.1 "as implemented" notes of this contract; `ops/runbooks/gateway-operations.md`.
- Every W1 §2.2 / §5.4 registration step and count pin applies (capability 233, purpose 60,
  audit vocabulary 244, lineage set 34, lineage writes 22, operator-decision 41, revision
  count 123, head literal and head-pin list, `TABLES_SHA256`, `TABLES_ABOVE`, the
  principal-partition guard registry for `application/lineage_rate.py` if its guard asks,
  spelled counts in `adapters/cli/app.py`, `bootstrap/gateway.py`, the architecture index
  and READMEs; `gateway.json` stays 110). Sharded CI: new modules are placed by
  `tests/ci_shard.py`; the worker adding heavy database modules re-measures and adds
  `tests/ci_shard_weights.json` entries when its guard asks.

**Work split** (serial; each package testable alone; one worker at a time):

| Worker | Owns | Delivers |
| --- | --- | --- |
| **N1** | the revision, `tables.py`, vocabulary, every registry, count pins, `ports.py` stubs, the 4 capability registrations (unbuilt handlers answer `unsupported`, S3 D-37), ChatLLM classification, `lineage_authority.py` provenance derivation, `RateLimitedError` and `SafeDetail`s, the profile opt-in sets, setting and `profile_capabilities`, the `_OPERATOR_ONLY` additions, `is_remote_idempotent` and `_CLIENT_BOUND_KEY_CAPABILITIES` | section 5 in full; sections 4.1, 6.1, 7.11, the kind and annotation half of 7.13; tests: S3.1 migration, S3.1 integrity guards, admission (FAST), profile ceilings, Part D catalog and kinds; the lockstep pin moves; the section 10.1 rows marked N1 (the S1 integrity-test needle conversion lands in the same commit as the CHECK drop, so the suite is never red between packages, and the Part D `_OPERATOR_ONLY` conversions land with the set change) |
| **N2** | the write paths | sections 4.2, 4.4–4.9, 6.2, 7.1–7.3, 7.5 (gate and readiness), 7.8; every open handler, the 3 confirms, the rate check, the channel-bound digest, the review scope, the accepted-lineage rule, **the section 6.4 remote write visibility and grants, including the write-answer filter** (kept in N2 rather than split with N3: the filter runs inside the write handlers on the views they build, and N3 later adds only label keys), the S4 delta; tests: open writes, remaining gates, confirmation, close gate, write visibility, rate bounds and race, the S4 rows; the section 10.1 rows marked N2 |
| **N3** | reads, web and guidance | sections 4.3, 6.3, 7.4, 7.6, 7.12; the label projection, `records.lineage.related`, the web decoders and words, tool descriptions and field documentation, the docs page with the facade examples; tests: read labels, related read, web decoder vocabulary, guidance pins and the example validation, the section 7.13 facade end-to-end rows (a)–(f), the profile fail-closed row and the ChatLLM row, truncation visibility |
| **N4** | reports and hardening | section 7.9 (block, recompute, schema-2 manifest, release), the S3.1 scope guard, docs sync ("as implemented" notes, index rows), full local tiers; tests: lineage manifest rows, scope guard |

## 10. Acceptance-test crosswalk

Same conventions as S1–S4 §10 (tier = marker selection; FAST = no marker; names binding;
a renamed test updates this table in the same commit; paths new unless marked existing).
`tests/architecture/test_record_lineage_s31_scope.py` parses this table the way the S4
scope guard parses S4 §10.

| Concern | Module | Test functions | Tier |
| --- | --- | --- | --- |
| Part A open writes | `tests/database/test_lineage_s31_open_writes.py` | `test_a_remote_client_commits_every_open_lineage_write` (each of the 14, each row `client_identified`, `ordinary_reviewer`, `remote_interactive`, with the client id); `test_a_local_unattested_caller_commits_as_client_identified_without_a_client_id`; `test_an_operator_write_still_records_user_confirmed_and_no_client`; `test_user_directed_is_stored_as_an_unverified_claim`; `test_the_operator_cannot_send_a_user_directed_claim`; `test_no_payload_can_supply_provenance`; `test_a_client_replay_of_its_own_write_is_a_replay`; `test_a_client_reusing_an_operator_key_is_conflict_and_writes_nothing`; `test_the_operator_reusing_a_client_key_is_conflict`; `test_a_client_reusing_another_clients_key_is_conflict`; `test_an_operator_replay_of_a_pre_s31_key_answers_the_original` (a request row and facts seeded at `c5260943d933`, upgraded, replayed); `test_an_active_identity_answers_created_false_and_never_changes_its_provenance` (both directions); `test_clients_end_correct_and_contest_each_others_links_within_the_principal`; `test_a_client_composite_writes_client_identified_links`; `test_a_client_cannot_end_or_correct_accepted_lineage` (`records.associations.end`/`correct`/`reinstate`, `issues.memberships.end`/`correct`, `issues.project_links.end` and a reinstating `add`, each on a `user_confirmed` head, `denied`, nothing written); `test_a_client_may_contest_an_accepted_semantic_link`; `test_a_client_cannot_end_or_reinstate_its_own_contest_of_accepted_lineage` (RR1-F01: contest → end, and contest → reinstate, each `denied` at the second step, plus `correct` after an operator reinstate of the client's contest); `test_a_client_cannot_revise_a_confirmed_client_fact` (a client fact confirmed by the operator, then a client `end`, `correct` and Project-link `end`, each `denied`); `test_a_client_cannot_void_or_retime_a_human_channel_handoff`; `test_clients_may_revise_client_identified_facts`; `test_a_remote_byte_identical_reassert_after_an_end_replays_the_old_answer` (pins residual R31-F11 d); `test_a_local_caller_reusing_an_operator_key_gets_conflict` (pins residual R31-F11 e); `test_cross_principal_open_writes_answer_like_absent`; `test_switch_off_answers_unsupported_for_every_open_write`; `test_issue_metadata_writes_keep_their_s1_rules` | database |
| Remaining gates | `tests/database/test_lineage_s31_remaining_gates.py` | `test_close_reopen_and_closed_issue_corrections_stay_operator_attested` (remote and unstamped `denied`, before the replay lookup, nothing written); `test_backfill_stays_operator_only_and_attested`; `test_confirm_capabilities_are_operator_attested_before_the_replay_lookup` | database |
| Confirmation | `tests/integration/test_lineage_s31_confirmation.py` | `test_confirm_appends_a_user_confirmed_revision_with_the_same_evidence`; `test_confirm_of_a_user_confirmed_or_contested_head_is_conflict_state`; `test_confirm_of_a_client_ended_link_keeps_it_ended`; `test_a_confirmed_membership_keeps_its_recorded_member_version`; `test_project_link_confirm_appends_a_confirm_event`; `test_confirm_is_refused_on_a_closed_issue`; `test_confirm_with_a_stale_expected_revision_is_conflict` | database |
| Close gate (OD-03) | `tests/integration/test_lineage_s31_close_gate.py` | `test_an_unreviewed_membership_holds_the_close`; `test_an_unreviewed_semantic_link_in_context_holds_the_close`; `test_a_client_end_of_a_mandatory_member_holds_the_close_until_confirmed`; `test_a_client_reinstatement_of_a_contested_link_holds_the_close`; `test_client_resolution_evidence_never_satisfies_the_gate_until_confirmed`; `test_readiness_lists_unreviewed_links_and_is_not_ready`; `test_confirming_or_an_operator_revision_clears_the_hold`; `test_confirming_a_client_end_clears_the_hold_and_a_new_root_restores_the_relationship`; `test_unreviewed_links_outside_the_review_scope_do_not_hold_it`; `test_a_close_and_a_client_revision_in_scope_serialize`; `test_the_user_directed_claim_changes_no_outcome` (R31-F06: the same scenario with `user_directed` false and true gives identical `ready`, blockers, close outcome, Program reportability, rate consumption and lineage `verification_state`). Every fixture of this module includes at least 1 fact written with `user_directed: true` | database |
| Remote write visibility (R31-F01) | `tests/security/test_lineage_s31_write_visibility.py` | `test_an_absent_and_a_hidden_endpoint_answer_alike` (each open write; same code and detail; nothing written; no budget consumed); `test_a_hidden_link_revision_answers_not_found` (`end`, `correct`, `contest`, `reinstate` by `link_id` with an invisible endpoint or context Issue); `test_a_hidden_anchor_source_answers_not_found`; `test_a_hidden_handoff_commitment_answers_not_found`; `test_a_hidden_project_answers_not_found_for_project_link_writes`; `test_a_write_answer_withholds_a_hidden_anchor_and_says_restricted`; `test_a_composite_without_the_native_create_grant_is_denied`; `test_a_remote_write_without_its_own_grant_is_unsupported`; `test_hidden_and_absent_answer_alike_at_the_budget_bound` | database |
| Validation-stage disclosure (RR1-F02) | `tests/security/test_lineage_s31_write_visibility.py` | `test_a_link_or_membership_write_without_issue_visibility_answers_as_absent` (covers the frozen-closed and Issue-context cases); the `blocks` cycle refusal is an explicit non-goal (section 14), pinned only by the existing S2 cycle tests | database |
| Truncation visibility (R31-F10) | `tests/security/test_lineage_s31_write_visibility.py` | `test_related_and_readiness_truncation_count_only_visible_items` | database |
| Rate bounds | `tests/database/test_lineage_s31_rate_bounds.py` | `test_a_client_past_its_hourly_budget_is_rate_limited_and_writes_nothing`; `test_the_daily_and_principal_budgets_bound_client_writes`; `test_replays_and_refusals_never_consume_budget`; `test_operator_writes_are_never_rate_limited`; `test_each_client_has_its_own_budget_and_unattested_callers_share_one`; `test_a_created_false_answer_is_checked_and_counted`; `test_a_composite_past_its_budget_creates_no_native_record` | database |
| Rate race (R31-F13) | `tests/concurrency/test_lineage_s31_budget_race.py` | `test_concurrent_client_writes_at_the_budget_boundary_admit_exactly_one` | database |
| Labels | `tests/contract/test_lineage_s31_read_labels.py` | `test_every_lineage_view_carries_the_s31_labels` (FAST, model keys); `test_s31_answers_without_client_rows_differ_from_s4_only_by_the_added_keys` (FAST, fixtures; includes every open-write answer and its `restricted: false`); `test_a_replay_applies_the_current_answer_filter` (database); `test_a_remote_reader_never_sees_a_client_id` (database); `test_every_read_labels_a_client_fact` (database: `records.lineage`, `issues.read`, `records.associations.history`, `issues.timeline`, `issues.handoffs.list`, `issues.closure_readiness`) | FAST + database |
| Part C related read | `tests/integration/test_records_lineage_related.py` | `test_related_returns_issue_context_predecessors_successors_and_evidence`; `test_related_never_crosses_issues_through_a_shared_meeting`; `test_related_filters_by_acceptance_basis_and_relation`; `test_related_order_is_deterministic_and_pages_union_to_one_answer`; `test_a_grant_change_between_pages_restarts`; `test_hidden_records_are_never_emitted_or_counted`; `test_related_budgets_truncate`; `test_the_related_digest_is_stable_and_excludes_read_stamps`; `test_a_foreign_or_invisible_seed_is_not_found`; `test_an_explicit_known_at_reproduces_an_earlier_answer` | database |
| Part C reports | `tests/integration/test_report_manifest_lineage.py` | `test_a_lineage_reference_binds_the_server_state_and_provenance_counts`; `test_a_changed_lineage_source_is_recorded_changed_since_read`; `test_a_failed_lineage_recompute_never_refuses_the_commit`; `test_a_manifest_without_a_lineage_reference_stays_schema_1`; `test_a_lineage_section_needs_the_related_grant_and_every_family`; `test_a_downstream_inherits_a_lineage_gate`; `test_the_lineage_reference_is_ordinary_content_when_related_is_not_served`; `test_a_collector_cannot_carry_a_lineage_reference`; `test_a_replayed_commit_never_recomputes_the_lineage_reference`; `test_a_cancelled_recompute_statement_is_recorded_and_the_commit_succeeds` (FR31-F01: a statement PostgreSQL really cancels) | database |
| S4 reportability | existing `tests/integration/test_program_metric_reconciliation.py` | new `test_an_unreviewed_issue_link_makes_the_issue_metric_not_reportable`; new `test_a_client_ended_issue_link_makes_the_issue_metric_not_reportable` (R31-F03); new `test_an_unreviewed_link_of_a_closed_issue_never_gates`; new `test_a_confirmed_issue_link_is_reported` | database |
| Profiles (config) | existing `tests/unit/test_mcp_database_profiles.py` | new `test_default_profile_ceilings_are_byte_identical`; `test_an_opt_in_admits_only_admissible_lineage_names`; `test_an_opt_in_outside_the_admissible_set_refuses_composition`; `test_write_opt_ins_reach_only_the_rw_profile`; `test_an_opted_in_write_grant_selects_the_rw_profile` (R31-F04 `surviving_write`); `test_reports_manifest_is_never_admissible`; `test_close_reopen_backfill_confirm_and_program_reads_are_never_admissible`; `test_an_opt_in_never_issues_a_grant` | FAST |
| Part D catalog and kinds | `tests/contract/test_lineage_s31_facade_catalog.py` | `test_every_lineage_capability_has_a_catalog_entry` (all 41 names: a `TOOLS` entry, a non-null summary, feature not `other`); `test_lineage_facade_kinds_are_deliberate` (the section 7.13 table, kind by kind); `test_lineage_write_tools_are_annotated_idempotent`; `test_non_lineage_tool_annotations_are_unchanged`; `test_attested_lineage_writes_are_never_published_remotely`; `test_the_remote_key_binds_the_client_for_open_writes_only` | FAST |
| Part D facade end to end | `tests/integration/test_lineage_s31_compact_facade.py` | `test_describe_lists_exactly_the_eligible_lineage_capabilities` (a); `test_the_read_and_write_wrappers_invoke_lineage_capabilities_strictly` (b); `test_the_wrong_wrapper_is_refused` (c); `test_a_non_admitted_lineage_name_is_absent_and_refused_like_a_nonexistent_one` (d); `test_facade_calls_are_captured_under_their_canonical_target` (e); `test_the_capability_manifest_and_web_fixtures_agree_for_lineage` (f); `test_two_clients_asserting_one_identity_get_created_false_not_conflict` — all on the default remote path; `test_an_opted_in_lineage_write_on_a_profile_service_fails_closed_and_writes_nothing` (profile path); `test_an_opted_in_lineage_read_on_a_profile_service_fails_closed` (profile path, read side, FR31-F02); `test_a_chatllm_client_sees_and_reaches_no_lineage_capability` (ChatLLM gateway path, with the planner-diff assertion) | database |
| Guidance examples (R31-F05) | `tests/contract/test_lineage_s31_guidance.py` | `test_the_guidance_examples_validate_against_the_remote_schemas`; `test_open_command_docstrings_state_the_s31_rule` | FAST |
| Migration | `tests/schema/test_record_lineage_s31_migration.py` | FAST: `test_the_revision_is_the_single_head_on_c5260943d933`; `test_the_revision_imports_no_domain_module`; `test_frozen_ddl_names_every_declared_constraint`; `test_the_revision_issues_no_grant`; `test_before_texts_are_byte_copies_of_the_s4_texts`; `test_at_vocabulary_adds_exactly_the_s31_names`; `test_offline_downgrade_refuses_first`. DB: `test_empty_to_head`; `test_s4_head_with_attested_rows_upgrades_unchanged`; `test_downgrade_refuses_while_s31_rows_exist`; `test_downgrade_restores_every_s4_text`; `test_each_downgrade_refusal_clause_alone_refuses` (11 cases, section 5.4's clauses each alone: client-identified rows in `record_link_revisions`, `issue_project_membership_events`, `issue_responsibility_events` and `issue_responsibility_corrections` separately; an `ordinary_reviewer` `record_links` row; a `confirm` revision; a `confirm` membership event; a request row naming a confirm capability; a request row with a client channel; an `audit_events` row naming an S3.1 capability; a schema-2 manifest) | FAST + migration markers |
| Integrity | `tests/database/test_lineage_s31_integrity_guards.py` | `test_a_lineage_row_provenance_is_consistent` (the 4 fact tables); `test_a_record_link_creator_is_known`; `test_a_confirmation_is_operator_attested`; `test_a_confirmation_follows_a_client_head_and_keeps_its_state`; `test_a_confirmation_keeps_its_evidence_and_member_version`; `test_a_project_link_confirmation_follows_a_client_event`; `test_a_write_request_records_its_writer_once`; `test_an_asserting_client_is_bounded`; `test_a_schema_2_manifest_names_its_lineage_section` | database |
| Admission | `tests/contract/test_lineage_s31_capability_admission.py` | `test_s31_capabilities_are_operator_decision_required`; `test_switch_off_withholds_every_s31_capability`; `test_s31_requests_reject_server_owned_fields`; `test_open_writes_derive_provenance_and_never_deny`; `test_remaining_gated_capabilities_derive_attested_authority`; `test_no_s31_capability_is_in_the_chatllm_data_profile`; `test_lineage_tool_descriptions_carry_the_client_guidance`; `test_existing_non_lineage_v1_shapes_are_unchanged_by_s31` | FAST |
| Scope | `tests/architecture/test_record_lineage_s31_scope.py` | `test_every_s31_crosswalk_test_exists`; `test_s31_adds_no_record_event_family`; `test_no_gate_reads_the_user_directed_claim` (R31-F06: the tokens `user_directed_claim` and `user_directed` appear nowhere in `domain/lineage/closure.py`, `domain/program/reportability.py` and `application/lineage_rate.py`, nor — by AST — in the bodies of `IssueApplication.close_issue`, the readiness `ready` computation `IssueApplication.closure_readiness` (except the `UnreviewedLinkView` construction, which is exempt) and the lineage verification comparator `source_manifest.lineage_verification_state`; `lineage_write_provenance` reads the flag only to store it and the manifest's `lineage_server_counts` only to count it, both exempt by name); `test_the_web_lineage_decoders_admit_exactly_the_server_vocabulary_after_s31` | FAST |

### 10.1 Existing tests converted by the directive (names kept: S1–S3 §10 bind them)

Each conversion keeps its function name because the S1–S3 scope guards bind it; the
assertion changes exactly where the directive changes the rule (reason, every row: the
operator directives of 2026-10-20 and 2026-10-25). No other S1–S4 assertion is removed or
weakened, and no skip or xfail is added.

| Module::name | Old assertion | New assertion | Owner |
| --- | --- | --- | --- |
| `tests/database/test_lineage_attested_writes.py::test_an_ordinary_remote_client_is_denied_accepted_lineage_writes` | each S1 link write by a remote client and by an unstamped local caller is `denied`, nothing written | each is admitted and every row it writes is `client_identified` (never `user_confirmed`): the client is still denied an *accepted* link | N2 |
| `tests/database/test_lineage_attested_writes.py::test_an_operator_review_client_cannot_call_any_s1_write` | overlay grants no S1 write, and directly granted the service denies each | overlay half unchanged; directly granted, each write is admitted as `client_identified` / `remote_interactive`, never `remote_operator_attested` (the Knowledge allowlists still confer nothing) | N2 |
| `tests/database/test_lineage_attested_writes.py::test_a_replayed_attested_write_from_an_ordinary_client_is_denied_before_the_replay_lookup` | `denied` for the client and the unstamped caller; operator replay answers the original | `conflict` / `idempotency_key` (`idempotency_conflict`, section 12.1 N2-01) for both, nothing written, never the operator's answer; operator replay unchanged | N2 |
| `tests/database/test_lineage_attested_writes.py::test_every_replayed_attested_write_is_denied_before_the_replay_lookup` | the 7 attested S1 writes `denied`; `issues.create`/`update` replay | the 7 now `conflict` / `idempotency_key` (`idempotency_conflict`, section 12.1 N2-01); `issues.create`/`update` unchanged | N2 |
| `tests/contract/test_lineage_capability_admission.py::test_lineage_authority_ignores_the_knowledge_manager_allowlist` | derivation `ordinary_reviewer`/`remote_interactive`; `issues.project_links.add` invoke `denied`; `attested_lineage_authority` raises | derivation unchanged; the invoke answers `not_found` / `issue_id` (the FAST world holds no Issue), never `denied`; `attested_lineage_authority` still raises | N2 |
| `tests/database/test_lineage_integrity_guards.py::test_attested_tables_refuse_a_non_local_operator_row` | the 4 inconsistent pairs refused by `a_lineage_row_is_local_operator_attested` | the same 4 pairs still refused, by `a_lineage_row_provenance_is_consistent` (revisions, events) and `a_record_link_creator_is_known` (root) — needle only | N1 |
| `tests/database/test_lineage_s2_attested_writes.py::test_an_ordinary_remote_client_is_denied_every_s2_write` | correct, handoff, both composites, close, reopen and the S2 relation asserts `denied` | correct, handoff, both composites and the relation asserts admitted as `client_identified`; close and reopen still `denied`, nothing written | N2 |
| `tests/database/test_lineage_s2_attested_writes.py::test_a_replayed_s2_write_from_an_ordinary_client_is_denied_before_the_replay_lookup` | every S2 write `denied` on replay by a non-attested caller | correct, handoff and composites `conflict` / `idempotency_key` (`idempotency_conflict`, section 12.1 N2-01); close and reopen still `denied` | N2 |
| `tests/database/test_lineage_s3_attested_writes.py::test_an_ordinary_remote_client_is_denied_every_s3_write` | contest, reinstate, handoff correct and backfill plan `denied` | contest, reinstate and handoff correct admitted as `client_identified` (the operator's follow-up request uses its own key); backfill plan still `denied` | N2 |
| `tests/database/test_lineage_s3_attested_writes.py::test_a_replayed_s3_write_from_an_ordinary_client_is_denied_before_the_replay_lookup` | every S3 write `denied` on a non-attested replay | contest, reinstate, handoff correct `conflict` / `idempotency_key` (`idempotency_conflict`, section 12.1 N2-01); backfill batches still `denied` | N2 |


**Part D conversions (reason: section 7.13 and D-16, not the directive; each keeps its name).**

| Module::name | Old assertion | New assertion | Owner |
| --- | --- | --- | --- |
| `tests/contract/test_capabilities_and_readiness.py::test_the_operator_only_set_is_enrollment_and_governed_identity_correction` | `_OPERATOR_ONLY` equals enrollment, the identity-correction pairs and the backfill pair (exact set) | the same set plus `issues.close`, `issues.reopen` and the 3 confirms, each named with the D-16 reason | N1 |
| `tests/contract/test_lineage_s2_capability_admission.py::test_s2_capabilities_are_operator_decision_required` | `not is_operator_only` for every S2 name | `is_operator_only` exactly for `issues.close` and `issues.reopen`; `not` for the other 6 | N1 |
| any remote-publication or facade-kind assertion naming `issues.close` / `issues.reopen` in `tests/contract/test_transport_parity.py`, `tests/unit/test_policy.py`, `tests/policy/test_application_authorization.py` or `tests/architecture/test_mcp_is_a_thin_adapter.py` | published to a granted remote client as a write; `operator_only: false` | withheld remotely (operator kind); `operator_only: true` — N1 lists each concrete function it changes in section 12.1, and changes nothing else | N1 |

**Admitted lockstep edits (assertions kept; owner N1 unless the edit is in a module another worker owns):** the head literal and revision count
(122 → 123) in every head-pin file and the head-pin list; count pins (`Capability` 229 →
233, audit vocabulary 240 → 244, lineage set 30 → 34, `LINEAGE_WRITE_CAPABILITIES` 19 →
22, operator-decision 37 → 41, `TABLES_SHA256`, permitted pairs, tool, builder,
command-union counts, docs count claims); `test_s1_and_s2_views_keep_every_key` admits the
section 7.6 additions beside `_S3_VIEW_ADDITIONS` (union; the subset assertion stays);
the S3 web-decoder vocabulary tests admit `client_identified` and `confirm`; any test pinning `operator_only` or the remote publication of `issues.close` / `issues.reopen`, or `idempotent_hint: false` on a lineage write tool, moves with section 7.13; the S4
overview digest golden vectors (section 8) and any S4 test reading
`PROGRAM_CALCULATION_VERSION`; migration suites that seed client-shaped rows below
`c5260943d933` do not exist (every earlier suite writes attested rows only); the S3 and S4
migration suites run their downgrade-refusal tests at their own revisions. Also existing
and binding: `tests/integration/test_issue_close_reopen.py::test_a_correction_of_a_closed_issue_needs_the_local_operator`,
`tests/database/test_lineage_backfill.py::test_backfill_is_operator_only_attested_and_behind_its_own_switch`,
`tests/database/test_lineage_s2_integrity_guards.py::test_an_issue_closure_row_is_local_operator_attested`,
`tests/database/test_lineage_attested_writes.py::test_a_local_operator_write_records_its_class_and_channel`,
`tests/contract/test_bff_success_decoder_parity.py`, `web/src/lib/api/decode/registry.test.ts`.

### 10.2 Prove-red expectations

Break exactly that one guard, show the named test red for that reason, restore; a green
prove-red is reported as redundancy, a masked test or an unreachable hazard, never as
"covered".

| Guard | Break | Test that must redden |
| --- | --- | --- |
| provenance CHECK | drop `a_lineage_row_provenance_is_consistent` (direct insert of `client_identified` with `local_operator`) | `test_a_lineage_row_provenance_is_consistent` |
| creator CHECK | drop `a_record_link_creator_is_known` | `test_a_record_link_creator_is_known` |
| server-derived client id | take `asserting_client_id` from a payload field | `test_no_payload_can_supply_provenance` |
| `client_identified` default | map `remote_interactive` to `user_confirmed` | `test_a_remote_client_commits_every_open_lineage_write` |
| claim never upgrades | derive `user_confirmed` when `user_directed` is true | `test_user_directed_is_stored_as_an_unverified_claim` |
| claim read by nothing | let the close gate skip unreviewed links whose claim is true | `test_no_gate_reads_the_user_directed_claim`; `test_the_user_directed_claim_changes_no_outcome` |
| accepted lineage kept (R31-F02) | admit a client `end` of a `user_confirmed` head | `test_a_client_cannot_end_or_correct_accepted_lineage` |
| history-keyed rule (RR1-F01) | key the rule on the head basis | `test_a_client_cannot_end_or_reinstate_its_own_contest_of_accepted_lineage` |
| confirmed becomes accepted (RR1-F01) | key the rule on the head basis | `test_a_client_cannot_revise_a_confirmed_client_fact` |
| contest still open (R31-F02) | refuse a client `contest` of a `user_confirmed` head | `test_a_client_may_contest_an_accepted_semantic_link` |
| handoff analogue (R31-F02) | admit a client `void` of a `user_confirmed` handoff | `test_a_client_cannot_void_or_retime_a_human_channel_handoff` |
| hidden is absent (R31-F01) | skip the visibility pre-check for `records.associations.assert` | `test_an_absent_and_a_hidden_endpoint_answer_alike` |
| link_id-addressed visibility (R31-F01) | skip the root read for `records.associations.end` | `test_a_hidden_link_revision_answers_not_found` |
| anchor family visibility (R31-F01) | admit an anchor of an invisible family | `test_a_hidden_anchor_source_answers_not_found` |
| situation visibility for link writes (RR1-F02) | drop the `situation` family requirement | `test_a_link_or_membership_write_without_issue_visibility_answers_as_absent` |
| answer filter (R31-F01) | return the unfiltered `AssociationView` | `test_a_write_answer_withholds_a_hidden_anchor_and_says_restricted` |
| composite native grant (R31-F01) | drop the `tasks.create` grant check | `test_a_composite_without_the_native_create_grant_is_denied` |
| write-grant re-check (R31-F01) | drop `require_write_grant` | `test_a_remote_write_without_its_own_grant_is_unsupported` |
| refusals before the rate count (R31-F01) | move the rate check back before validation | `test_hidden_and_absent_answer_alike_at_the_budget_bound`; `test_replays_and_refusals_never_consume_budget` |
| unreviewed ended Project link (R31-F03) | count only active latest events | `test_a_client_ended_issue_link_makes_the_issue_metric_not_reportable` |
| `surviving_write` (R31-F04) | compute it over `MCP_PROFILE_WRITE_CAPABILITIES` alone | `test_an_opted_in_write_grant_selects_the_rw_profile` |
| manifest never admissible (R31-F04) | admit `reports.manifest` | `test_reports_manifest_is_never_admissible` |
| guidance examples (R31-F05) | use `from` instead of `from_record` in an example | `test_the_guidance_examples_validate_against_the_remote_schemas` |
| truncation counts visible only (R31-F10) | count hidden entries in `unreviewed_links_truncated` | `test_related_and_readiness_truncation_count_only_visible_items` |
| budget race (R31-F13) | read the count before taking the commit mark | `test_concurrent_client_writes_at_the_budget_boundary_admit_exactly_one` |
| ChatLLM gate (R31-F08) | classify `records.lineage.related` `CHATLLM_DATA_REQUIRED` | `test_a_chatllm_client_sees_and_reaches_no_lineage_capability` |
| channel-bound digest | omit the writer from the client digest document | `test_a_client_reusing_an_operator_key_is_conflict_and_writes_nothing` |
| pre-S3.1 replay | add the writer to the human-channel document | `test_an_operator_replay_of_a_pre_s31_key_answers_the_original` |
| claim absent from old digests | put `"user_directed": false` in every document | `test_an_operator_replay_of_a_pre_s31_key_answers_the_original` |
| no upgrade on re-assert | append a revision when the operator asserts a client identity | `test_an_active_identity_answers_created_false_and_never_changes_its_provenance` |
| review scope: live heads | read only live heads (S3 `links_in_context`) | `test_a_client_end_of_a_mandatory_member_holds_the_close_until_confirmed` |
| review scope: reinstate | count only `contested` heads | `test_a_client_reinstatement_of_a_contested_link_holds_the_close` |
| client resolution evidence | evaluate the head's anchors whatever its basis | `test_client_resolution_evidence_never_satisfies_the_gate_until_confirmed` |
| readiness agrees with close | compute `ready` without the unreviewed set | `test_readiness_lists_unreviewed_links_and_is_not_ready` |
| confirm attested | derive `lineage_write_provenance` in a confirm handler | `test_confirm_capabilities_are_operator_attested_before_the_replay_lookup` |
| confirm DB attestation | drop `a_confirmation_is_operator_attested` | `test_a_confirmation_is_operator_attested` |
| confirm keeps evidence | let the confirm revision cite an empty set | `test_a_confirmation_keeps_its_evidence_and_member_version`; `test_confirm_appends_a_user_confirmed_revision_with_the_same_evidence` |
| confirm keeps member version | record the observed member version | `test_a_confirmed_membership_keeps_its_recorded_member_version` |
| confirm only a client head | admit confirm of a `user_confirmed` head (function and handler) | `test_confirm_of_a_user_confirmed_or_contested_head_is_conflict_state`; `test_a_confirmation_follows_a_client_head_and_keeps_its_state` |
| ended terminal except confirm | admit `correct_evidence` after `ended` | `test_a_confirmation_follows_a_client_head_and_keeps_its_state` |
| Project-link confirm DB rule | drop the `confirm` branch condition in `a_membership_event_follows_its_predecessor` | `test_a_project_link_confirmation_follows_a_client_event` |
| rate bound | remove the hourly check | `test_a_client_past_its_hourly_budget_is_rate_limited_and_writes_nothing` |
| replays are free | count before the replay lookup | `test_replays_and_refusals_never_consume_budget` |
| per-client bucket | key the bucket by channel only | `test_each_client_has_its_own_budget_and_unattested_callers_share_one` |
| operator unlimited | count operator rows | `test_operator_writes_are_never_rate_limited` |
| writer columns immutable | drop them from `a_lineage_write_request_completes_once` | `test_a_write_request_records_its_writer_once` |
| remote client-id hiding | return `asserting_client_id` to a remote reader | `test_a_remote_reader_never_sees_a_client_id` |
| related: Issue confinement | follow every live link from every reached node | `test_related_never_crosses_issues_through_a_shared_meeting` |
| related: filter | emit filtered links but do not follow them | `test_related_filters_by_acceptance_basis_and_relation` |
| related: hidden never counted | count invisible nodes against the budget | `test_hidden_records_are_never_emitted_or_counted` |
| related: per-page grants | skip the scope digest check | `test_a_grant_change_between_pages_restarts` |
| related: digest stamps | include `native_cut_at` in `D` | `test_the_related_digest_is_stable_and_excludes_read_stamps` |
| S4 unreviewed link | ignore the unreviewed count | `test_an_unreviewed_issue_link_makes_the_issue_metric_not_reportable` |
| schema-1 kept | write schema 2 for every manifest | `test_a_manifest_without_a_lineage_reference_stays_schema_1` |
| lineage release gate | gate on the Program part only | `test_a_lineage_section_needs_the_related_grant_and_every_family` |
| transitive lineage gate | drop the upstream lineage union | `test_a_downstream_inherits_a_lineage_gate` |
| recompute never refuses | refuse the commit on a recompute error | `test_a_failed_lineage_recompute_never_refuses_the_commit` |
| recompute compares | record `verified_at_commit` without comparing | `test_a_changed_lineage_source_is_recorded_changed_since_read` |
| recompute savepoint (FR31-F01) | run the recompute without its savepoint | `test_a_cancelled_recompute_statement_is_recorded_and_the_commit_succeeds` |
| profile default | add the opt-in sets to the ceiling unconditionally | `test_default_profile_ceilings_are_byte_identical` |
| profile admissible set | admit `issues.close` as an opt-in | `test_close_reopen_backfill_confirm_and_program_reads_are_never_admissible` |
| opt-in never grants | skip the grant intersection for opt-ins | `test_an_opt_in_never_issues_a_grant` |
| close/reopen operator kind | remove `issues.close` from `_OPERATOR_ONLY` | `test_lineage_facade_kinds_are_deliberate`; `test_attested_lineage_writes_are_never_published_remotely` |
| open writes are write kind | add `records.associations.assert` to `_OPERATOR_ONLY` | `test_lineage_facade_kinds_are_deliberate`; `test_the_read_and_write_wrappers_invoke_lineage_capabilities_strictly` |
| idempotent annotation | derive `idempotent_hint` from `is_server_replay_capability` alone | `test_lineage_write_tools_are_annotated_idempotent` |
| annotations scoped to lineage | derive it from `_IDEMPOTENT_REMOTE_CAPABILITIES` | `test_non_lineage_tool_annotations_are_unchanged` |
| client-bound remote key | drop the client from the derived key | `test_the_remote_key_binds_the_client_for_open_writes_only`; `test_two_clients_asserting_one_identity_get_created_false_not_conflict` |
| facade eligibility | let `prepare_compact_call` admit a name outside the eligible set | `test_a_non_admitted_lineage_name_is_absent_and_refused_like_a_nonexistent_one` |
| facade kind check | skip the kind comparison | `test_the_wrong_wrapper_is_refused` |
| capture target | record the wrapper name as `capability` | `test_facade_calls_are_captured_under_their_canonical_target` |
| switch | drop `_lineage_plane()` in one new handler | `test_switch_off_withholds_every_s31_capability` |
| downgrade refusal, each clause (R31-F07) | delete that 1 clause (11 rows: one per section 5.4 clause, each fact table separately, the 2 request-row clauses separately) | the matching case of `test_each_downgrade_refusal_clause_alone_refuses` |

**Not S3.1:** AT-020, AT-021 (OD-06); web confirm actions (section 11).

## 11. Deferred work and its owner

| Item | Owner / reason |
| --- | --- |
| A principal-wide review queue of unreviewed client facts (a list read over every Issue and null-context link) | a later lineage package; S3.1 finds them per Issue (readiness) and per seed (related read with the basis filter) |
| Web confirm and end actions, a review UI | WP-06B; S3.1 confirms through the CLI and the HTTP gateway `invoke` route |
| Handoff and handoff-correction confirmation | no gate or total consumes handoff provenance; a human corrects a client handoff with `issues.handoffs.correct`; a later package adds `confirm` if a consumer needs it |
| A client identifier on `issue_revisions` and a `user_directed` field on `issues.create`/`update` | Issue metadata writes were already open (S1) and assert nothing about other records; their client id is recorded on the request row (section 5.2) |
| A verified "user directed" signal (human presence or consent proof) | an operator decision and a new trust mechanism; S3.1 records a claim only (section 14) |
| Bulk confirm; a per-Issue cap on unreviewed facts | not needed for the bounded review load of section 4.8; revisit with measured use |
| A lineage expansion inside existing search reads (`knowledge.search`, `*.search`) | their v1 shapes stay byte-identical; a client feeds search results as seeds to `records.lineage.related` |
| A privilege mechanism for **existing** objects (the lineage tables, and whatever the `commitments.v2.*` reads touch) for the #339 MCP roles | operator item: `mcp_object_grants.py` grants only around a new `CREATE`; until a separately reviewed mechanism exists, every opted-in lineage call on a profile service fails closed (R31-F04) |
| `reports.manifest` on the restricted profiles | not admissible: `intelligence_` objects are refused for MCP roles under every classification (S4 D-46); a change needs its own security review |
| A client dispute action for an accepted membership | memberships have no `contest` (S3 §3.2) and a client may not correct accepted lineage (section 4.4); a client reports the dispute; a later package may add a membership contest |
| Cheap refusals before the allocator lock | every refusal after the commit mark serializes behind the Principal's lineage writers (section 14); moving validation before the mark would change the S3 lock order and is not done here |
| A remote attested lineage writer (own allowlist, settings key) | not scheduled; S1 §11 unchanged |
| `idempotentHint` for non-lineage keyed writes | a catalog decision outside lineage (D-17) |

## 12. Divergences — brief, package and repository, with resolutions

| # | Brief or package says | Repository truth or design reason | Resolution |
| --- | --- | --- | --- |
| D-01 | "server-derived channel/provenance on every revision" (a provenance field) | every fact row already stores `authority_class` and `decision_channel`, and `acceptance_basis` is the labelled "why accepted" column | `client_identified` is an `AcceptanceBasis` member and the read label; the 2 new columns are `asserting_client_id` and `user_directed_claim`; no redundant provenance column |
| D-02 | default: client links "not accepted-grade evidence for the close gate" | counting only live heads, a client `end`, `reinstate` or `correct` could weaken the S2/S3 gate | stricter: any `client_identified` head in the review scope **holds** the close until the human channel confirms or revises it (section 4.6) |
| D-03 | proposals "via the existing proposal mechanism" | no lineage proposal plane exists (S3 D-07); other planes' proposals are for their own facts | the `client_identified` fact in the one ledger is the proposal state; no `irp`/`ldec`; other planes unchanged |
| D-04 | "strict v1 shapes unchanged" | lineage reads are behind a default-off switch with no grant and no deployed client; S2 and S3 widened them in lockstep | non-lineage v1 shapes byte-identical; lineage shapes widened additively in lockstep with the web decoders (section 8) — the design reviewer is asked to adjudicate this reading |
| D-05 | "lineage/program capability names" admissible in the profile ceilings | profile compositions build no Program read engine (S4 D-46), so the 2 `programs.*` reads are never served there | `commitments.v2.*` admissible; `programs.members.resolve` and `programs.overview` not; `reports.manifest` not admissible either (D-21) |
| D-06 | idempotency "incl. previously-attested keys" | S1 recorded writes replay channel-blind; attested writes refused a non-attested replay as `denied` | the open writes bind the writer into the client digest (`conflict` across writers; human-channel digests unchanged); `issues.create`/`update` keep their S1 channel-blind replay (unchanged behaviour, no test converted) |
| D-07 | S4 "certified/NOT_REPORTABLE reporting" | S4 certifies nothing; its `issue_outstanding` reads the latest Project-link event | an unreviewed link reuses `issue_link_unverified` (no new reason), 3 keys added, calculation version `program-overview-v2` |
| D-08 | handoffs (record/retime/void) open | open as directed; nothing consumes their provenance | open and labelled; no confirmation (section 11) |
| D-09 | "or when I provide instruction to do so" | the server cannot observe the instruction | `user_directed` is a stored, displayed, unconsulted claim (section 4.1) |
| D-10 | "`capabilities.get` entries" as guidance | its entries are a v1 shape with no description key | the 4 names appear as entries; guidance is in tool descriptions, field documentation and the docs page |
| D-11 | gap reads for suggestions | `issues.closure_readiness` already computes blockers, stale evidence and contested links | widened with `unreviewed_links`; no separate gaps capability |
| D-12 | rate/volume bounds "with exact limits" | no limiter exists; the commit mark serializes a Principal's lineage writers | counts over request rows under the mark lock; 120/hour and 1000/day per client bucket, 2000/day per Principal; `rate_limited` |
| D-13 | Part A lists the link writes | `issues.create`/`update` were open since S1 | unchanged except the rate bound and request-row writer columns |
| D-14 | brief: reuse the S3 bounded-graph machinery for a related read | `records.lineage` selects one Issue per origin | a new read with multiple seeds over the same traversal, filters and cursor; `records.lineage` unchanged except labels |
| D-16 | Part D: "Issue close/reopen … stay `operator`" | at the basis they are `write` kind (not `_OPERATOR_ONLY`); `_OPERATOR_ONLY`'s stated test is "widens a later request's scope", which they do not | they join `_OPERATOR_ONLY` with the 3 confirms, because their attestation can never be met remotely; the deviation from that module's stated test is deliberate and recorded |
| D-17 | Part D: "accurate idempotency annotations" | every tool's `idempotent_hint` is false; many non-lineage writes are also keyed | true for the 22 lineage writes only; non-lineage annotations unchanged (their under-annotation is a pre-existing residual, section 11) |
| D-18 | brief: channel-bound replay (section 4.9) | the remote boundary derives one key per payload, not per client | the derived key binds the client for the 14 open writes, so identical requests from 2 clients reach the identity rule instead of `conflict` |
| D-19 | R31-F02: clients ending or correcting accepted lineage | the S1–S3 transition table admits any writer | option (a), keyed on history (RR1-F01): a client may revise only a fact the human channel has never accepted at any revision, except 1 `contest` of an active accepted semantic link, after which only the human channel writes that link; every other client revision of a fact the human channel has accepted at any revision (links, memberships, Project links by triplet, handoffs by event or any correction) is `denied`; ended heads in review scope are therefore only ends of never-accepted facts (section 4.4) |
| D-20 | R31-F01: open writes and S3 §6.4 | S3 §6.4 applied only to reads | remote writes get a write-grant re-check, a composite native-create grant, hidden-is-absent pre-checks before any row, replay and rate count, and an answer filter that withholds with `restricted: true` (section 6.4); the rate check moves after validation |
| D-21 | §7.11 admissible set held `reports.manifest` | its table can never be granted to an MCP role | removed; deferred (section 11) |
| D-15 | package/ADR-015 decision 7: only an attested surface writes accepted lineage | the directive opens the writes | ADR-015 decision 15 amends decision 7: the open writes are not accepted-grade; acceptance needs the human channel's revision |

### 12.1 As implemented

Reserved for the S3.1 workers' resolutions (N1–N4), each reported in its handoff and
accepted by the Orchestrator.

**N1** (revision `023f8f7eb499`, registration, provenance derivation, profile opt-ins,
the kind and annotation half of section 7.13):

| # | Point | Resolution |
| --- | --- | --- |
| N1-01 | Section 4.7 copies a membership head's `member_native_version` into its confirm, but S2's `only_membership_writes_record_a_member_version` admitted a version only for `issues.memberships.add`/`correct` and the composites | the revision restates that CHECK by same-name replacement to admit `issues.memberships.confirm` too (`tables.py` declares `MEMBER_VERSION_CAPABILITIES` plus the confirm; the vocabulary set itself is unchanged); downgrade restores the S2 text; pinned by `test_a_confirmation_keeps_its_evidence_and_member_version` |
| N1-02 | Section 5.2's `a_lineage_write_request_writer_is_known` text admits a null `decision_channel` with a non-null `asserting_client_id` (SQL `NULL` in its third disjunct) | the third disjunct reads `decision_channel IS NOT NULL AND decision_channel = 'remote_interactive' AND …`, so a client id needs its channel; stricter, same intent; pinned by `test_a_write_request_records_its_writer_once` |
| N1-03 | Section 5.3 says a schema-2 manifest carries `lineage` "(an object)"; section 7.9 makes it `LineageManifestSection \| null` | `a_manifest_names_its_own_artifact` admits the key with an object or `null` value on schema 2, refuses it on schema 1, and checks the row's version equals the text's; pinned by `test_a_schema_2_manifest_names_its_lineage_section` |
| N1-04 | Section 7.11 names a setting `mcp_database_profile_opt_ins: frozenset[str]` | the peer settings' shape: a string field `mcp_database_profile_opt_ins` (env `MY_PA_MCP_DATABASE_PROFILE_OPT_INS`) and the parsed accessor `mcp_database_profile_opt_in_set()`; `McpDatabaseServices` gains `opt_ins` (default empty); `profile_capabilities(profile, opt_ins=frozenset())` as written |
| N1-05 | Section 7.13 Part D conversions, the concrete functions changed | `tests/contract/test_capabilities_and_readiness.py::test_the_operator_only_set_is_enrollment_and_governed_identity_correction`, `tests/contract/test_lineage_s2_capability_admission.py::test_s2_capabilities_are_operator_decision_required`, `tests/contract/test_chatllm_operator_publication.py::test_full_inventory_catalog_without_execution` (the remote catalog now omits the 5 operator-only lineage writes); no function of `tests/contract/test_transport_parity.py`, `tests/unit/test_policy.py`, `tests/policy/test_application_authorization.py` or `tests/architecture/test_mcp_is_a_thin_adapter.py` asserted their remote publication, so none changed beyond the registry additions for the 4 new names |
| N1-06 | Lockstep pins outside the section 10.1 list | `tests/architecture/test_record_lineage_s4_scope.py`'s lineage-vocabulary digest moves (S3.1 widens the vocabulary S4 left untouched); `tests/unit/test_lineage_s3_domain.py::test_link_transition_table` admits `confirm` beside `assert` as no state transition (its 12 S3 rows unchanged); `tests/schema/test_constraint_authoring_capability_migration.py`'s head-pin list drops the extraction ledger (S3.1 creates no table, so that file no longer names the head) |
| N1-07 | The 4 new handlers | unbuilt (S3 D-37): after the switch the 3 confirms derive attested authority (`denied` for a non-attested caller) and every one answers `unsupported`; the command request validation of sections 7.2–7.4 is complete; no `ports.py` method is added (the N2/N3 repository methods are theirs to declare) |
| N1-08 | `test_lineage_tool_descriptions_carry_the_client_guidance` | pins the section 7.12 sentences of the 4 new commands verbatim and every lineage tool's description within 240 characters; the open commands' summaries and docstring bodies are N3's (section 7.12), which extends this test |

**N2** (the write paths: sections 4.2, 4.4-4.9, 6.2, 6.4, 7.1-7.3, 7.5 and 7.8):

| # | Point | Resolution |
| --- | --- | --- |
| N2-01 | Sections 4.9, 7.7 and 10.1 name the cross-writer key reuse `conflict` / `idempotency_key` | `idempotency_key` is the existing malformed-key detail; a key bound to a different request already answers `idempotency_conflict` (`LineageIdempotencyConflictError`), and the server cannot tell a writer change from a payload change without reading the winner; kept `idempotency_conflict`, asserted by every converted and new test |
| N2-02 | Section 4.6 names `review_scope_links(principal_id, issue_id)` | it takes the current `inside` set too, as `links_in_issue_context` does; `record_lineage.unreviewed_links_in_scope` builds the set and applies `closure.in_review_scope` and `is_unreviewed` |
| N2-03 | Section 6.4 step 4 withholds an invisible anchor from a write answer | `HandoffView.evidence` is one required anchor (no withholding); a `handoff_id` whose own event anchor is invisible to the remote caller answers `not_found` / `handoff_id` in the pre-check, as `issues.handoffs.list` withholds that entry whole; Project-link answers carry no anchor body (`restricted: false`); the filter applies to remote callers only |
| N2-04 | Section 6.4 step 3, "the same safe detail" as an absent subject | the pre-check walks the subjects in validation's lock order (`lineage_endpoints.lock_order_families`), so a hidden subject answers what an absent one would; the Project-link writes check Issue, then Project, then anchor (the order section 10.1 pins with `not_found` / `issue_id`); a composite's hidden Project answers `invalid_request` / `project_id`, as an absent one does |
| N2-05 | RR1-F02 situation-family rule | kept first for every link, membership and composite write; for asserts, membership adds and composites the lock-order walk would also hide the Issue (with its own detail), so the rule is load-bearing for the `link_id`-addressed writes (prove-red P13b) and changes only the detail elsewhere (P13c) |
| N2-06 | Section 4.6, a client's resolution evidence is not accepted-grade | `MembershipHeadEvidence.accepted`: a `client_identified` mandatory head offers no resolution evidence, so readiness lists `resolution_evidence_missing` for it (no new blocker token) until the human channel confirms it |
| N2-07 | Section 5.2, writer columns "for every later row" | every lineage request row records its writer: the open writes, the confirms, close, reopen, `issues.create`/`update` (the remote client id, `lineage_authority.recorded_client_id`) and the backfill plan |
| N2-08 | Section 7.1 `user_directed?: bool` | added to the 14 open commands with a minimal boolean schema; its field documentation and the 14 docstring bodies (still "Local operator only.") are N3's (section 7.12) |
| N2-09 | Lockstep pins outside the section 10.1 list | `tests/architecture/test_mcp_is_a_thin_adapter.py` exempts the boolean `user_directed` from the location-word scan (39 -> 53, the `direction` precedent); the S4 denominator dict and calculation version (`test_program_metric_reconciliation.py`, `test_report_manifest_integrity.py`); the readiness dicts of `test_issue_close_reopen.py`; the S4 overview golden vectors; the plans' module and tier counts; `LineageRuntime.invoke` gains an exact `grants` override |
| N2-10 | R31-F03's counterexample (a client ends the operator's Project link) | impossible under section 4.4 (`denied`); the R31-F03 row uses a client-created link the client ends |
| N2-11 | R31-F06 claim row | covers `ready`, blockers, unreviewed links, the close answer and budget consumption; Program reportability is pinned by the S4 row whose link is written claimed; the lineage `verification_state` part is N4's (section 7.9) |
| N2-12 | Section 10 truncation-visibility row | N3's (with the related read); readiness computes `unreviewed_links_truncated` over visible entries only |

**N3** (reads, labels, guidance and the facade rows: sections 4.3, 6.3, 7.4, 7.6, 7.12 and the
section 7.13 end-to-end rows):

| # | Point | Resolution |
| --- | --- | --- |
| N3-01 | Section 4.3, where the client id is withheld from a remote reader | one choke point: `ApplicationService._run` passes every lineage capability's answer to a caller holding a grant set through `lineage_visibility.withhold_client_ids`, which sets every `asserting_client_id` to `null` (the writer itself included); view builders always state the stored value, so a local reader sees it; the related read applies the same function to the items its digest covers; pinned by `test_a_remote_reader_never_sees_a_client_id` |
| N3-02 | Section 7.6 view keys | the 2 labels are model fields with the neutral defaults (`false`, `null`; `HandoffCorrectionView.acceptance_basis` `user_confirmed`), and every builder sets them from the row; `TimelineEntryView` gains the 3 keys (`null` exactly off the 5 fact kinds, `TIMELINE_LABELLED_KINDS`); `ports.TimelineLinkRevision` gains the 3 columns and `issue_timeline.link_revisions` selects them |
| N3-03 | Section 7.4, the expansion order behind "first reaching step" | per seed in request order its one hop, then each of its Issues in `issue_id` order, each breadth-first in the S3 tie-break order; a record keeps its least depth and the first step at it; each expansion keeps its own visited set, so a record another seed reached first is still expanded; a seed's own `issue_ids` name the Issues it was expanded under; `issue_ids` are capped at 20 across seeds |
| N3-04 | Section 7.4 step 2, what the filters bind | only following and emitting: the candidate Issues (S1 section 7.2 step 2) and the Issue's inside set are computed over every live link, so a filter never changes which Issue context applies; the filters are sets (normalized to vocabulary order; the defaults are every member), so their order never changes the digest or the cursor binding |
| N3-05 | Section 7.4 steps 1 and 5, seeds and budgets | a Situation seed that is not an Issue is `invalid_request` / `seeds` (the S1 `origin` rule); a note-version seed beyond the native cut is `not_found` / `seeds`; the bounded result always uses the paged budgets (nodes and edges, no byte bound during expansion), and `related_sha256` is over that whole result before the per-page 512 KiB bound; without `page_size` the read is one page that drops what does not fit, says `truncated_budget` and has no cursor; a restart page's digest is the empty restart result's |
| N3-06 | Section 7.12 says `source_sha256` and `passage_sha256` are optional | the S1 command parser (`lineage_endpoints` shape check over `EvidenceAnchor`) requires `source_sha256` on every exact-version anchor and `passage_sha256` with a passage, so the docs page states both as required (the version's `content_sha256`; the SHA-256 of the passage's UTF-8 text) and its write example carries both; `test_the_guidance_examples_validate_against_the_remote_schemas` also runs each payload through the command's own checks. A contract-versus-code point, resolved in the page; section 7.12's example text is superseded by it |
| N3-07 | Section 7.12, the page "routed from `docs/operations/README.md`" | that README is a `SCAFFOLD_ONLY` delegation; the page is routed from the Operations section of `docs/00_REPOSITORY_SOURCE_INDEX.md`, the router `test_non_scaffold_readmes_are_routed` reads |
| N3-08 | Section 7.12 tool descriptions | all 34 lineage summaries are pinned verbatim (one sentence, at most 240 characters); the 14 open commands' docstring bodies state the S3.1 rule, with the Project-link and handoff bodies naming their own consequence (a Project link is outside the close gate and makes totals not reportable; a handoff is outside both); `user_directed` and every evidence-anchor field carry the section 7.12 field documentation |
| N3-09 | Section 7.13 profile row | `build_mcp_database_services` attests PostgreSQL 17 role identities and the fixed roles do not exist on a scratch cluster, and a test does not create cluster roles; the row composes `McpDatabaseServices` directly over 2 data engines whose sessions `SET ROLE pg_read_all_data` (a predefined role that reads every table and writes nothing, so it models the missing write privilege only; corrected by N4, FR31-F02), routes the opted-in write grant through `access` to the rw service and the real remote app (`require_bound_service`), and asserts `internal_error` with no row written. Only the write side is pinned by that row; the read side is pinned by N4's `test_an_opted_in_lineage_read_on_a_profile_service_fails_closed` (sessions `SET ROLE pg_write_all_data`, a predefined role with no SELECT on any table, stricter than the fixed roles, which may read their granted non-lineage objects): an opted-in `records.lineage.related` answers `internal_error` and writes nothing |
| N3-10 | Section 7.13 ChatLLM row | the planner's own `plan_chatllm_grant_actions` over an empty grant set provisions the client; describe lists none of the 41 lineage-plane names, every lineage call is `unsupported`, and the diff desires, adds and reports missing none |
| N3-11 | Lockstep edits (section 10.1 admitted list) | `test_s1_and_s2_views_keep_every_key` unions `_S31_VIEW_ADDITIONS`; `test_s1_lineage_views_keep_every_s1_key` and `test_existing_v1_shapes_are_unchanged_by_s2` subtract the 2 labels and keep their exact S1/S2 sets; `test_issue_timeline.py`'s `_ENTRY_KEYS` gains the 3 labels; `test_an_active_identity_answers_created_false_and_never_changes_its_provenance` compares the 2 answers without `asserting_client_id` and asserts it is the client's for the local reader and `null` for the remote one; the parity fixtures label the timeline's fact entries (one a client's contest) and `success.json` is regenerated for `records.lineage`, `issues.read` and `issues.timeline`; the plans' module and tier counts |
| N3-12 | Section 10 scope module | `tests/architecture/test_record_lineage_s31_scope.py` is created with N3's web-vocabulary row only; the crosswalk, Record Event and `user_directed` rows are N4's |

**N4** (reports and hardening: section 7.9, the scope guard, the docs sync and the full local tiers):

| # | Point | Resolution |
| --- | --- | --- |
| N4-01 | Section 7.9 runs the recompute "on the request's own work connection" with each statement at `min(2000, remaining)` ms | a statement cancelled by its timeout aborts the PostgreSQL transaction, which would refuse the commit; the recompute therefore runs inside `RecordLineageRepository.bounded_by_deadline(deadline)`, a savepoint that is always rolled back (it writes nothing) with a `before_cursor_execute` hook that sets `SET LOCAL statement_timeout = min(2000, remaining)` before each statement and raises `LineageReadTimeoutError` at a spent budget before the statement is sent; the rollback also ends the `SET LOCAL`, so no timeout outlives the recompute; pinned by `test_a_failed_lineage_recompute_never_refuses_the_commit` (its spent-budget case commits) |
| N4-02 | Sections 7.9 and 7.10: "with the switch off ... every manifest is schema 1" beside "a downstream of a lineage-gated upstream is schema 2 for that reason alone" | the transitive rule wins: a manifest is schema 2 exactly when its block was interpreted or an upstream's recorded requirement carries a lineage gate, whatever the switch (a gated upstream exists only if the switch was on when it was committed), so no downstream text ever carries a gated upstream's digest without the gate (FR4-F01); with the switch off and no gated upstream every manifest is schema 1, pinned by `test_the_lineage_reference_is_ordinary_content_when_related_is_not_served` |
| N4-03 | Section 7.9 block shape | all 7 keys are required (`max_depth`, `acceptance_bases` and `relation_types` have no default in the block); the 2 lists are distinct, non-empty token lists normalized to vocabulary order exactly as the related read normalizes its filters, so the recompute's digest document equals the read's; `max_depth` is 1..3 by a domain constant that the scope guard keeps equal to the command's `MAX_RELATED_DEPTH`; the block's own checks live in `domain/intelligence/source_manifest.py::lineage_reference_block` and the recompute in `application/record_lineage.py::recompute_lineage_reference` |
| N4-04 | Section 7.9 "only when `records.lineage.related` admits the committing caller (its remote grant re-check and the visibility of every seed)" | not admitted -- a remote caller with no `records.lineage.related` grant for a permitted purpose, or a seed of a family it cannot see -- records `not_attempted` and reads nothing; such a section is no gate (`lineage_grant: false`, no families), as the S4 rule treats `not_attempted`, but the manifest is still schema 2 because the block was interpreted; a seed absent, foreign or a non-Issue Situation at the cut is `seed_not_found` |
| N4-05 | Section 7.9 cut and budgets | the recompute is the section 7.4 computation at an explicit `known_at` (so `N = known_at`), `valid_at` omitted; a `known_at` after the horizon (or after now, or with no horizon) is `cut_beyond_horizon`; the traversal deadline is the 5000 ms budget itself, and a result the deadline ended early records `budget_exceeded` rather than binding a truncated digest; a statement cancelled with budget left is `statement_timeout` |
| N4-06 | Section 7.9 `server` | `record_count` and `link_count` count the whole unpaged bounded result as the committing caller is answered it (hidden records and links are neither emitted nor counted, S3 section 6.4), `links_by_acceptance_basis` always names both bases, and `user_directed_claims` counts the links whose claim is true (`lineage_server_counts`, the one place the manifest reads the claim); `known_at` is the recompute's `T_k` in the section 5.3 format; `families_seen` is the committer's visible `RecordFamily` set, sorted (all 7 for a local caller), and `lineage_families` is the seeds' families with it (the seeds' families alone for `recompute_failed`) |
| N4-07 | Section 7.9 release | `reports.manifest` applies `source_manifest.lineage_released` beside `program_released`: with a recorded `lineage_grant` a remote reader needs a `records.lineage.related` grant for `record_lineage_read` and, through `lineage_visibility`, every family in `lineage_families`; a schema-1 manifest's recorded requirement holds no lineage key and passes; `recorded_release_requirement` returns the 2 lineage keys only for a schema-2 manifest, so every S4 caller and vector is unchanged |
| N4-08 | Section 10 claim row (R31-F06, N2-11) | `test_the_user_directed_claim_changes_no_outcome` gains the lineage `verification_state`, `recompute_failure` and server counts of a report citing a related read of each scenario's Issue (equal with and without the claim; only `user_directed_claims` differs), and a second Issue whose only hold is the client's link, claimed or not: the original scenario's close is also held by the client's resolution evidence (N2-06), so a close-only bypass of claimed links was masked there (prove-red green) and is red with the added Issue; it now uses a fixture over `S31ReportRuntime` (`tests/database/lineage_s31_harness.py`, which also gains `lineage_reference`) |
| N4-09 | Section 10 scope guard | besides the crosswalk table the guard checks that every `module::name` of the section 10.1 conversion tables exists; the `user_directed` row is an AST walk that skips only the `UnreviewedLinkView(...)` call in `closure_readiness` and asserts the exemption is real (the readiness body does display the claim), and that `lineage_write_provenance` and `lineage_server_counts` do read it |
| N4-10 | Docs sync | the S4 and S3.1 rows of `docs/architecture/00_ARCHITECTURE_INDEX.md` and the ADR-015 status paragraph say each slice is implemented on its branch, test-isolated, not merged or deployed; the client guidance page states the block's exact keys and where the outcome is read; the plan's tier counts move by the N4 rows |
| N4-11 | Full local tiers at the N4 head | `tests/architecture/test_every_capability_reaching_a_memory_row_is_declared.py::test_no_call_to_a_memory_reaching_port_method_has_an_untyped_receiver` failed at the N3 head (`_Related.reach` called `graph.budget.admit` through an unannotated local); the local is annotated `_Graph`, so the reach walk follows it, and no other change was needed. The lineage browser specs pass on the desktop, tablet and mobile Chromium projects; the 2 WebKit keyboard-reachability rows fail identically on the S4 base tree (macOS WebKit does not move focus to these controls with Tab), so they are recorded as an environment limit, not an S3.1 regression |
| N4-12 | Final review FR31 (F01-F05) | F01: `test_a_cancelled_recompute_statement_is_recorded_and_the_commit_succeeds` makes PostgreSQL cancel a recompute statement through a test-only seam (a 100 ms statement cap and a `pg_sleep` before the watermark read); it records `statement_timeout` and commits, and it is red with the savepoint removed (the commit answers `internal_error`). F02: the N3-09 text is corrected and the read side is pinned (above). F03: the guidance page names the release families exactly. F04: a stale handler comment is rewritten. F05: the body passages that section 12.1 supersedes (N2-01, N3-06, N4-02) carry a marker in place |

## 13. Operator gates that remain

Ratification of ADR-015 and its S3.1 amendment beyond the directive defaults; enabling
`MY_PA_LINEAGE_ENABLED` anywhere but a test; issuing any grant on a lineage capability to
any client, and any change of a ChatLLM classification (every lineage name stays
`CHATLLM_OPERATOR_DECISION_REQUIRED`); setting `MY_PA_MCP_DATABASE_PROFILE_OPT_INS`, and
the separately reviewed database privileges the fixed MCP roles would need on lineage
tables; enabling remote writes for any client; any live migration, deployment or backfill
(OD-07); any change of the section 4.8 bounds; any certified total or looser threshold
(OD-08); close and reopen stay the operator's; a verified user-direction signal (section
11). Nothing else in S3.1 is left for a worker to decide beyond local naming with no
incumbent constraint.

*Amended by the P1 client-exposure contract* ([`record-lineage-client-exposure-contract.md`](record-lineage-client-exposure-contract.md), ADR-015 decision 16, operator directive 2026-10-26): the ChatLLM classification gate above is decided — the client-usable lineage-plane names join the ChatLLM data profile `chatllm-data-v10` and the attested names become `CHATLLM_CONTROL_PLANE_EXCLUDED` — and that contract states the production environment, write gates and grants for the later deployment phase. The restricted-profile opt-in and its privilege mechanism, close and reopen, and every other gate in this section stand; the S3.1 section 10.2 row "ChatLLM gate (R31-F08)" is superseded by that contract's section 10.2 prerequisite rows. The text above is kept as written for S3.1.

## 14. Residual risks (stated plainly)

- **The server cannot verify `client_identified` or `user_directed` claims.** It knows the
  transport, the stamped local surface and the OAuth client id; it cannot know whether a
  human or a model made a remote or stdio call, whether the user instructed it, or
  whether the cited passage supports the relation. Every remote client is the operator
  Principal. A `client_identified` fact therefore says only "an authenticated client in
  this Principal wrote this", and `user_directed_claim` only "that client said so".
- **Shared or stolen client credentials** make 2 agents 1 bucket and 1 label; revoking the
  client's grant or token is the control.
- **stdio and unstamped local callers share 1 bucket and have no client id**; their facts
  are distinguishable only by channel.
- **Review load:** a misbehaving client can commit up to 120 requests an hour (a composite
  writes up to 5 links) of unreviewed facts that hold Issue closes until the operator
  reviews each — confirming or revising a live head, or confirming the end of an ended
  client fact (section 4.6); the bounds cap it and revoking the grant stops it.
- **Clients can end, correct or dispute each other's never-accepted facts, and contest an
  accepted semantic link once (after which only the human channel writes it), within the
  Principal**; no sequence of client actions can end, correct or reinstate a fact the
  human channel has accepted at any revision (section 4.4). Every such revision holds the close until
  reviewed; the default traversal shows a client-revised unreviewed fact in its latest
  state.
- **(R31-F11 a) The Principal-wide budget is shared:** 1 or 2 granted clients, or the
  shared `local_unattested` bucket, can exhaust the 2000-per-day Principal budget and deny
  every other client's lineage writes for up to 24 hours (operator writes are never
  limited). Revoking the offending grant is the control.
- **(b) Refused writes are unbounded and serialize:** a refused client write consumes no
  budget, but each that reaches the commit mark holds the Principal's allocator lock until
  it rolls back, so a client spamming refusable writes slows the operator's lineage
  writes. Remote hidden-subject refusals happen before the mark (section 6.4); other
  refusals do not.
- **(c) The human channel is whatever reaches the CLI or the HTTP gateway `invoke` route**
  with its credential (`OperatorSurface.HTTP_GATEWAY`); that route is now the sole
  promoter of client facts, so its credential is accepted-lineage authority.
- **(d) A remote byte-identical re-assert after an `end` replays the old answer:** the
  remote key is derived from the payload (and client), so it names the earlier request and
  returns its stored answer instead of creating the new root S1 would; a client that
  wants a new root after an end must change the payload (for example its evidence).
  Pinned by `test_a_remote_byte_identical_reassert_after_an_end_replays_the_old_answer`;
  a non-goal for S3.1.
- **(e) A local stdio caller reusing an operator key now gets `conflict` /
  `idempotency_key`** (superseded by section 12.1 N2-01: the answer is `conflict` / `idempotency_conflict`) where it got `denied`, which reveals to a same-Principal local caller
  that the key exists; pinned by `test_a_local_caller_reusing_an_operator_key_gets_conflict`.
- **(f) Buckets are per granted client:** dynamic client registration exists, so the number
  of buckets is bounded only by grant issuance (a registration alone grants no tool).
- **(g) The `blocks` cycle refusal can disclose a hidden path (RR1-F02):** asserting `A
  blocks B` with visible A and B is refused when a `blocks` path from B to A exists through
  a record the caller cannot see. The cycle rule is an integrity rule and cannot be hidden
  without admitting a cycle; an explicit non-goal (the frozen-closed and Issue-context
  cases are closed by the `situation` visibility requirement of section 6.4).
- **Related reads and report recomputes reflect current visibility, native resolution and
  evidence availability**; a reference recorded `verified_at_commit` proves agreement at
  commit only.
- **Database immutability is a DML guarantee** (S1 §4.3, CR-014 role separation still an
  operator follow-up); the new CHECKs and functions share that limit.
