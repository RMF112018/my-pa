# Record lineage — P1 client exposure (ChatLLM gateway and remote MCP): implementation contract

**Status:** proposed implementation contract under
[ADR-015](../decisions/ADR-015-record-lineage-and-issue-situations.md) as amended by its
decision 16 (the P1 client-exposure amendment). It is the single document the P1
implementers code against, on top of the [S1](record-lineage-s1-contract.md),
[S2](record-lineage-s2-contract.md), [S3](record-lineage-s3-contract.md),
[S4](record-lineage-s4-program-contract.md) and
[S3.1](record-lineage-s31-open-writes-contract.md) contracts as merged. It changes a
**classification and its documentation**; it adds no migration, no capability, no
purpose, no table, no grant and no setting, and it flips no default. It authorizes no
deployment, migration run, grant, client-flag change, profile apply or production use:
those are the P2 steps of section 13, each the operator's. Where it differs from the
Orchestrator brief (`orchestrator-brief-P1-exposure.md`), this document controls for P1
once the design review passes it, and section 12 records why.

**Authority for the change:** an operator directive given directly to the Manager on
2026-10-26 (recorded in the Manager ledger), not a production ratification: deploy to
production in a later phase (P2) with every lineage switch on (`MY_PA_LINEAGE_ENABLED`,
`MY_PA_PROGRAM_REPORTING_ENABLED`, remote writes, `MY_PA_LINEAGE_BACKFILL_ENABLED` for the
dry run only), and "expose lineage in both clients": (1) reclassify the lineage
capabilities so the ChatLLM gateway's profile publishes them, and (2) admit them for the
ChatGPT connector's remote MCP path. The operator attested that Issue close and reopen,
the 3 `confirm` capabilities, `records.backfill.*` and the update of a closed Issue stay
withheld from both clients, that S3.1's security properties are not weakened, that S4
D-46 / S3.1 D-21 (no `programs.*` or `reports.manifest` on the restricted MCP database
roles) stands unless a safe alternative is proven and accepted, and that every switch
stays default-off in code.

**Basis:** `feat/lineage-client-exposure@899493aa2eba9d7927dedca1339787786af7a392`
(tree `1b3751011dd53cdfacec68b01b5f945abafae001`, `origin/main` with S3.1 merged as
#342). Alembic single head `023f8f7eb499` (123 revisions); 233 `Capability` members;
34 lineage capabilities behind `MY_PA_LINEAGE_ENABLED` (`_LINEAGE_CAPABILITIES`) and 7
S4 names behind `MY_PA_PROGRAM_REPORTING_ENABLED` (`_PROGRAM_REPORTING_CAPABILITIES`), 41
lineage-plane names in all; ChatLLM classes 74 `DATA_REQUIRED`, 97 `DATA_CONDITIONAL`, 2
`COMPATIBILITY_ONLY`, 19 `CONTROL_PLANE_EXCLUDED`, 41 `OPERATOR_DECISION_REQUIRED`;
ChatLLM data profile `chatllm-data-v9`; 31 restricted-profile opt-in names. "S3.1 §n"
and "S4 §n" cite the earlier contracts. Line numbers are at the basis commit; for a file
P1 edits, the symbol named beside the line is the stable reference.

All counts in this file are digits on purpose (spelled-count guard).

## 1. What P1 is

S3.1 made every lineage write except the attested ones open to any caller the ordinary
grant and purpose rules admit, recorded `client_identified`, and made remote exposure a
**configuration** decision: a remote client reaches a lineage capability exactly when the
process composes it, the client holds a durable grant on it, and — for a write — every
remote write gate is open. What S3.1 kept closed was the **ChatLLM data profile**: every
lineage-plane name stayed `CHATLLM_OPERATOR_DECISION_REQUIRED`, so the profile planner
(`profile-diff` / `profile-plan` / `profile-apply`) never desired, added or reported one
missing.

P1 is the operator's decision on that gate, and nothing else in code:

- **ChatLLM (section 4).** The 34 client-usable lineage-plane names move to
  `CHATLLM_DATA_CONDITIONAL` under 2 new composition prerequisites, `LINEAGE` and
  `PROGRAM_REPORTING`, so the planner desires them exactly when the process composes them;
  the 5 withheld attested names move to `CHATLLM_CONTROL_PLANE_EXCLUDED`; the data profile
  becomes `chatllm-data-v10`.
- **Remote MCP / ChatGPT (section 6).** No code change. The repository-supported reading
  of "the remote MCP profile the ChatGPT connector uses" is the **default remote MCP
  path** (section 2.2); exposure there is the P2 grant set (the v10 profile, or the same 34
  grants issued individually) plus the switches. The restricted-profile opt-in value is
  stated canonically and drift-guarded, but it is **not** part of the P2 environment,
  because the restricted profiles are not commissioned and lineage on them fails closed
  (sections 2.3, 6.2).
- **Documentation (sections 6–7).** The production environment block, the durable P2
  commands, the switch matrix with every dependency and what remote writes open, and the
  residual risks — in a new runbook section with fail-closed drift guards.

**Not in P1:** any privilege mechanism for existing objects on the fixed MCP roles; any
`programs.*` or `reports.manifest` admission to a restricted profile; any new provenance
channel value, migration, capability, purpose or setting; any web or facade change; any
default flipped on; any production action.

## 2. Repository truth: how each client connects

### 2.1 ChatLLM

- **Transport and identity.** ChatLLM reaches the server as an OAuth client of the one
  remote MCP resource (`apps/gateway.py:290`, `remote_access_context`). Every remote
  client authenticates as the operator Principal
  (`src/my_pa/infrastructure/security/remote_oauth.py:150`, `PrincipalKind.OPERATOR`);
  there is no client-to-human binding. The authenticated OAuth client id is stamped
  server-side from the token (`src/my_pa/adapters/mcp/remote.py:343`). The local stdio
  composition also remains available to a ChatLLM workflow
  (`ops/runbooks/remote-mcp-cloudflare.md`, "Supported clients"); stdio holds no grants
  and is unchanged by P1 (section 5.4).
- **Publication profile `chatllm-gateway-v1`.** The compact façade
  (`src/my_pa/adapters/mcp/chatllm_gateway.py:36`, `PROFILE_VERSION`) is a *publication
  shape* on the same `/mcp` resource: `MY_PA_MCP_CHATLLM_GATEWAY_ENABLED` plus the exact
  allowlist `MY_PA_MCP_CHATLLM_GATEWAY_OAUTH_CLIENT_IDS` select it per client
  (`src/my_pa/bootstrap/settings.py:1038`, `compact_publication_for_client`). It publishes
  `my_pa.describe` and an invoker per eligible kind (`facade_tool_names`,
  `src/my_pa/adapters/mcp/chatllm_gateway.py:118`); `facade_kind`
  (`src/my_pa/adapters/mcp/chatllm_gateway.py:101`) is `operator` for `is_operator_only`,
  else `write` for `is_remote_write`, else `read`; `prepare_compact_call`
  (`src/my_pa/adapters/mcp/chatllm_gateway.py:190`) refuses a target outside the
  eligible set as `unsupported`. The eligible set is the same `allowed` set the canonical
  catalog uses (`access_for_request`, `src/my_pa/adapters/mcp/remote.py:314`). The
  façade reads no ChatLLM classification; `chatllm-gateway-v1` does not change in P1.
- **Data profile `chatllm-data-v9`.** `CHATLLM_DATA_PROFILE_VERSION`
  (`src/my_pa/domain/identity/chatllm_capability_policy.py:18`) names the grant set the
  planner reconciles. `apps/cli/remote_mcp.py` refuses any other `--profile-version`
  (`_run_profile_command`, `apps/cli/remote_mcp.py:190`), computes `implemented` as every
  handler and `composed` from the process Settings through `_planes_from_settings`
  (`apps/cli/remote_mcp.py:144`) and `composed_capabilities`
  (`src/my_pa/application/chatllm_data_profile.py:140`), whose
  `_prerequisite_holds` (`src/my_pa/application/chatllm_data_profile.py:166`) is
  exhaustive and raises on an unknown prerequisite. The desired set is the composed
  data-management names (`desired_effective_capabilities`,
  `src/my_pa/application/chatllm_data_profile.py:195`); each grant is stamped with the
  capability's one permitted purpose (`chatllm_grant_purpose`,
  `src/my_pa/application/chatllm_data_profile.py:129`). An active grant on a
  `CONTROL_PLANE_EXCLUDED` name is the failing outcome `UNEXPECTED_CONTROL_PLANE_GRANT`
  (`diff_chatllm_data_profile`, `src/my_pa/application/chatllm_data_profile.py:239`).
- **What the classification governs.** Only the planner and its tests. No runtime
  publication path, the façade, `capabilities.get` (`build_capability_manifest` carries
  name, availability and `operator_only` only) or any `web/src/contracts/*` fixture reads
  it. Publication is composition ∩ the client's grants ∩ the write gates.
- **Reclassification convention.** Every data-class change has bumped the profile version
  (`git log -G 'chatllm-data-v[0-9]+"'` on the policy module: `#261`, `#296`, `#297`,
  `#302`, `#314`, `#315`, `#316`, `#326`). The exact precedent for a plane-switched set is
  KLP-WP-03 (`chatllm-data-v6`): `DATA_CONDITIONAL` names composed only by their plane
  switch, through an explicit name set (`KNOWLEDGE_ASSERTION_DATA_NAMES`,
  `src/my_pa/domain/identity/chatllm_capability_policy.py:354`) and a prerequisite the
  planes carry (`ChatLLMCompositionPlanes.knowledge_assertions`).
- **Classification pins.** `tests/contract/test_chatllm_capability_policy.py` (counts,
  version), `tests/contract/test_chatllm_data_profile_diff.py` (targets, version
  literals), `tests/unit/test_remote_mcp_chatllm_profile.py` (CLI version refusal), the
  S1–S3.1 and S4 admission modules (each name `CHATLLM_OPERATOR_DECISION_REQUIRED`), and
  `tests/integration/test_lineage_s31_compact_facade.py::test_a_chatllm_client_sees_and_reaches_no_lineage_capability`
  (S3.1 R31-F08). Section 10.1 converts exactly the assertions the directive changes.

### 2.2 ChatGPT

- **Transport and identity.** The ChatGPT connector is a Dynamic Client Registration client
  of the same `/mcp` resource (`ops/runbooks/remote-mcp-cloudflare.md`, "Connect ChatGPT
  in developer mode"): the same operator Principal, the same server-stamped client id, the
  same grant, purpose and write gates; DCR alone grants no tool. The runbook's commands
  issue its grants individually (`grant`), not through a profile.
- **Which "profile" it uses.** 3 things in the repository are called a profile for a
  remote client: (a) the `remote.operator` relationship-grant marker
  (`src/my_pa/adapters/mcp/remote.py:245`, `remote_tool_names`), which widens publication
  only to the 4 identity-correction names; (b) the compact operator publication
  (`MY_PA_MCP_CHATLLM_OPERATOR_OAUTH_CLIENT_IDS`), which widens it only to those 4 and
  `sources.enroll` (`_REMOTE_OPERATOR_IDENTITY_CAPABILITIES`,
  `src/my_pa/adapters/mcp/remote.py:226`); and (c) the #339 restricted database profiles
  (`MY_PA_MCP_DATABASE_PROFILES_ENABLED`, `ro`/`rw` fixed roles). None of (a)–(c) is a
  lineage grant profile, and (a) and (b) can never publish a lineage name. **The
  repository-supported interpretation is the default remote MCP path**: the deployed
  composition's example environment runs the remote MCP process as the application role
  `my_pa` (`ops/nas/remote/remote.env.example:4`) with the database profiles absent
  (default off, `src/my_pa/bootstrap/settings.py:385`), and the runbook states the
  database profiles are a "bounded implementation, not commissioned"
  (`ops/runbooks/remote-mcp-cloudflare.md`, "Default-off database profiles"). On that
  path ChatGPT reaches lineage through its own grants, exactly as ChatLLM does. Whether
  the deployed ChatGPT client is in the compact-façade allowlist is a runtime fact this
  repository does not hold (the Manager's operational notes say production's façade
  overlay lists it); it changes the tool shape only, never what is reachable.
- **Remote write gates.** 3 independent inputs, all required for any remote write: the
  process setting `MY_PA_REMOTE_WRITES_ENABLED` (`src/my_pa/bootstrap/settings.py:383`;
  `writes_enabled=settings.remote_writes_enabled`, `apps/gateway.py:470`), the durable
  global control and the per-client flag
  (`writes_allowed = bool(row.writes_enabled and row.global_writes_enabled)`,
  `src/my_pa/infrastructure/persistence/remote_identity.py:256`; a write grant of a
  client without both is dropped before resolution).

### 2.3 The restricted MCP database profiles (#339 / #340) and the opt-in

- `MY_PA_MCP_DATABASE_PROFILE_OPT_INS` (`src/my_pa/bootstrap/settings.py:398`) parses
  comma- or space-separated names; a name outside `MCP_PROFILE_OPT_IN_CAPABILITY_NAMES`
  (`src/my_pa/contracts/mcp_database_profiles.py:101`, 15 reads at
  `src/my_pa/contracts/mcp_database_profiles.py:61` and 16 writes at
  `src/my_pa/contracts/mcp_database_profiles.py:80`, 31 names) or **any** name while
  `MY_PA_MCP_DATABASE_PROFILES_ENABLED` is off is a `SettingsError` at start
  (`src/my_pa/bootstrap/settings.py:737`). With profiles off,
  `build_mcp_database_services` returns `None` (`src/my_pa/bootstrap/mcp_database_profiles.py:218`)
  and the opt-in is never read.
- With profiles on, every client must be listed `ro` or `rw` or it is refused
  (`McpDatabaseServices.access`, `src/my_pa/bootstrap/mcp_database_profiles.py:156`);
  the ceiling intersects the client's own grants. The fixed roles hold no privilege on
  any lineage table, because `mcp_object_grants.py` grants only around a new `CREATE` and
  refuses every `intelligence_` object
  (`src/my_pa/infrastructure/database/mcp_object_grants.py:105`), so an opted-in lineage
  call on a profile service fails closed with `internal_error` and writes nothing (S3.1
  §7.11, pinned by `test_an_opted_in_lineage_write_on_a_profile_service_fails_closed_and_writes_nothing`
  and `test_an_opted_in_lineage_read_on_a_profile_service_fails_closed`). A profile
  composition builds no Program read engine (`src/my_pa/bootstrap/gateway.py:1092`), so
  `programs.*` are never served there (S4 D-46).

### 2.4 The S3.1 client-usable and withheld sets

From `domain/lineage/vocabulary.py` and `domain/program/vocabulary.py` (code constants):
`OPEN_LINEAGE_WRITE_CAPABILITIES` (14), `RECORDED_LINEAGE_WRITE_CAPABILITIES`
(`issues.create`, `issues.update`), `ATTESTED_LINEAGE_WRITE_CAPABILITIES` (`issues.close`,
`issues.reopen`, `records.backfill.plan` and `CONFIRM_CAPABILITIES`, 3),
`LINEAGE_BACKFILL_CAPABILITIES` (2), `PROGRAM_REPORTING_CAPABILITIES` (7, of which
`PROGRAM_READ_CAPABILITIES` 2). Today every name is `CHATLLM_OPERATOR_DECISION_REQUIRED`
(`_OPERATOR_DECISION_REQUIRED`, `src/my_pa/domain/identity/chatllm_capability_policy.py:290`)
except the backfill pair (`_CONTROL_PLANE_EXCLUDED`,
`src/my_pa/domain/identity/chatllm_capability_policy.py:256`). `issues.close`,
`issues.reopen` and the 3 confirms are `_OPERATOR_ONLY` (S3.1 §7.13), so
`remote_tool_names` withholds them from every remote publication, canonical or compact,
including both operator ceilings of section 2.2. The update of a **closed** Issue is not a
capability: it is `issues.update`'s handler refusing a non-attested caller (S3.1 §3.1).

### 2.5 What a ChatLLM or ChatGPT write records today

Both are `remote_interactive` callers with an authenticated client id, so
`lineage_write_provenance` (`src/my_pa/application/lineage_authority.py:135`) records
`acceptance_basis = client_identified`, `authority_class = ordinary_reviewer`,
`decision_channel = remote_interactive`, `asserting_client_id` = that client's OAuth id,
and the declared `user_directed` flag as `user_directed_claim`, which no gate reads (S3.1
§4.1). The rate bounds key the writer bucket by `(decision_channel, asserting_client_id)`
(`require_client_write_budget`, `src/my_pa/application/lineage_rate.py:54`; 120/hour and
1000/day per bucket, 2000/day per Principal, `src/my_pa/domain/lineage/vocabulary.py:575`).
Visibility is the S3 §6.4 family rule over the client's own grants
(`LINEAGE_FAMILY_READS`, `src/my_pa/domain/lineage/vocabulary.py:605`); every open write
re-checks its own grant (`require_write_grant`,
`src/my_pa/application/lineage_visibility.py:104`). The compact façade composes the same
canonical call (`compose_remote_arguments`, `src/my_pa/adapters/remote_request.py:443`),
so the façade and canonical paths record identically.

## 3. Exposure table

"ChatLLM" is the data-profile class (what the planner desires and adds). "Remote MCP" is
the default remote path for **both** clients: reachability is S3.1's unchanged rule
(composed ∩ granted ∩ write gates); the column states whether the section 6.3 grant set
issues the grant in P2. "Profile opt-in" is the restricted-profile admissibility (S3.1
§7.11, unchanged). ODR = `CHATLLM_OPERATOR_DECISION_REQUIRED`; DC = `CHATLLM_DATA_CONDITIONAL`;
CPE = `CHATLLM_CONTROL_PLANE_EXCLUDED`. The prerequisite is the new composition
prerequisite (section 4.2). `tests/contract/test_lineage_client_exposure_policy.py::test_the_policy_matches_the_contract_exposure_table`
parses this table.

| Capability | W/R | Purpose | ChatLLM v9 | ChatLLM v10 | Prerequisite | Remote MCP grant (P2) | Profile opt-in | Withheld reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `issues.create` | W | `issue_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.update` | W | `issue_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — (a closed Issue's update stays attested in the handler) |
| `issues.read` | R | `issue_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.list` | R | `issue_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.history` | R | `issue_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.timeline` | R | `issue_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.closure_readiness` | R | `issue_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.close` | W | `issue_authoring` | ODR | CPE | — | no | never | attested to the local operator surface (S2 §6.1); operator kind |
| `issues.reopen` | W | `issue_authoring` | ODR | CPE | — | no | never | same |
| `issues.project_links.add` | W | `issue_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.project_links.end` | W | `issue_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.project_links.confirm` | W | `issue_authoring` | ODR | CPE | — | no | never | attested human-channel promotion (S3.1 §4.7); operator kind |
| `issues.memberships.add` | W | `issue_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.memberships.end` | W | `issue_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.memberships.correct` | W | `issue_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.memberships.confirm` | W | `issue_authoring` | ODR | CPE | — | no | never | attested human-channel promotion; operator kind |
| `issues.handoffs.record` | W | `issue_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.handoffs.correct` | W | `issue_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.handoffs.list` | R | `issue_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.work.create_task` | W | `issue_work_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `issues.work.create_commitment` | W | `issue_work_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `records.associations.assert` | W | `record_lineage_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `records.associations.correct` | W | `record_lineage_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `records.associations.end` | W | `record_lineage_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `records.associations.contest` | W | `record_lineage_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `records.associations.reinstate` | W | `record_lineage_authoring` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `records.associations.confirm` | W | `record_lineage_authoring` | ODR | CPE | — | no | never | attested human-channel promotion; operator kind |
| `records.associations.history` | R | `record_lineage_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `records.lineage` | R | `record_lineage_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `records.lineage.related` | R | `record_lineage_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `records.backfill.plan` | W | `lineage_backfill` | CPE | CPE | — | no | never | operator-only dry run (S3 §7); unchanged |
| `records.backfill.report` | R | `lineage_backfill` | CPE | CPE | — | no | never | same; unchanged |
| `meetings.notes.versions` | R | `meeting_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `meetings.notes.read_version` | R | `meeting_note_history_read` | ODR | DC | `LINEAGE` | yes | admissible | — |
| `programs.members.resolve` | R | `program_reporting_read` | ODR | DC | `PROGRAM_REPORTING` | yes | never (S4 D-46) | — on the default path |
| `programs.overview` | R | `program_reporting_read` | ODR | DC | `PROGRAM_REPORTING` | yes | never (S4 D-46) | — on the default path |
| `commitments.v2.read` | R | `commitment_read` | ODR | DC | `PROGRAM_REPORTING` | yes | admissible | — |
| `commitments.v2.list` | R | `commitment_read` | ODR | DC | `PROGRAM_REPORTING` | yes | admissible | — |
| `commitments.v2.search` | R | `commitment_read` | ODR | DC | `PROGRAM_REPORTING` | yes | admissible | — |
| `commitments.v2.waiting_on` | R | `commitment_read` | ODR | DC | `PROGRAM_REPORTING` | yes | admissible | — |
| `reports.manifest` | R | `report_read` | ODR | DC | `PROGRAM_REPORTING` | yes | never (S3.1 D-21) | — on the default path |

Totals: 34 exposed (16 writes, 18 reads; 27 under `LINEAGE`, 7 under
`PROGRAM_REPORTING`); 7 withheld (`issues.close`, `issues.reopen`, the 3 confirms, the 2
backfill names). Every exposed name has exactly 1 permitted purpose, so
`chatllm_grant_purpose` stamps it without a multi-purpose entry; every exposed write is
`write` kind and every exposed read `read` kind (S3.1 §7.13, unchanged).

## 4. ChatLLM reclassification mechanism

### 4.1 Classes and version

In `domain/identity/chatllm_capability_policy.py`:

- `CHATLLM_DATA_PROFILE_VERSION = "chatllm-data-v10"` (a data class moved; the convention
  of section 2.1).
- The 34 exposed names leave `_OPERATOR_DECISION_REQUIRED` and join `_DATA_CONDITIONAL`.
  Their `_EXCLUSION_RATIONALE` entries are removed (a data class carries none); the now
  unused `_LINEAGE_S1_EXCLUSION`, `_LINEAGE_S2_EXCLUSION`, `_LINEAGE_S3_EXCLUSION`,
  `_LINEAGE_S31_EXCLUSION` and `_PROGRAM_REPORTING_EXCLUSION` constants are removed.
- `issues.close`, `issues.reopen`, `records.associations.confirm`,
  `issues.memberships.confirm` and `issues.project_links.confirm` leave
  `_OPERATOR_DECISION_REQUIRED` and join `_CONTROL_PLANE_EXCLUDED`, with the rationale
  `_LINEAGE_ATTESTED_EXCLUSION = "attested to the local operator surface; withheld from
  every client (operator directive 2026-10-26)"`. The backfill pair keeps its class and
  rationale.
- `_OPERATOR_DECISION_REQUIRED` keeps `gsqs.start` and `gsqs.status` only.
- Counts after: `DATA_REQUIRED` 74, `DATA_CONDITIONAL` 131, `COMPATIBILITY_ONLY` 2,
  `CONTROL_PLANE_EXCLUDED` 24, `OPERATOR_DECISION_REQUIRED` 2, `RETIRED` 0 (233).

**Why `CONTROL_PLANE_EXCLUDED` and not left as an operator decision.** The operator has
decided: these names are withheld from both clients. `OPERATOR_DECISION_REQUIRED` would
state a pending decision that is not pending; `CONTROL_PLANE_EXCLUDED` states the
decision and makes the planner fail closed — an active grant on one of them is
`UNEXPECTED_CONTROL_PLANE_GRANT` and the diff is unhealthy — which is the ChatLLM-side
form of "withheld". Publication is withheld independently by `_OPERATOR_ONLY` and the
handlers still deny a non-attested caller; P1 changes neither.

### 4.2 Composition prerequisites

- 2 new `ChatLLMCompositionPrerequisite` members, `LINEAGE = "LINEAGE"` and
  `PROGRAM_REPORTING = "PROGRAM_REPORTING"`.
- 2 new explicit name sets in the policy module, by member, never by prefix (the
  `KNOWLEDGE_ASSERTION_DATA_NAMES` precedent: `meetings.notes.*` and `commitments.v2.*`
  share prefixes with always-composed names): `LINEAGE_DATA_NAMES` (the 27 exposed names
  of `_LINEAGE_CAPABILITY_NAMES`) and `PROGRAM_REPORTING_DATA_NAMES` (the 7
  `PROGRAM_REPORTING_CAPABILITIES`). `_prerequisite_of` tests them **before** any prefix
  rule. The domain module does not import the application's switch sets; a test pins
  `LINEAGE_DATA_NAMES == _LINEAGE_CAPABILITIES − withheld` and
  `PROGRAM_REPORTING_DATA_NAMES == _PROGRAM_REPORTING_CAPABILITIES`.
- `ChatLLMCompositionPlanes` (`application/chatllm_data_profile.py`) gains `lineage: bool
  = False` and `program_reporting: bool = False` (default off, as the switches and the
  `knowledge_assertions` precedent).
- `_prerequisite_holds`, still exhaustive:
  - `LINEAGE`: `planes.lineage`;
  - `PROGRAM_REPORTING`: `planes.lineage and planes.program_reporting`, and for the 2
    `PROGRAM_READ_CAPABILITIES` also `planes.relationship_intelligence`, and for
    `programs.overview` also `planes.constraints` — the service's own conditions
    (`src/my_pa/application/service.py:4356` and the lines after it). The Program read
    factory exists in every composition the CLI plans for (it is absent only in a
    restricted-profile composition, which the planner does not model; section 12, DV-09).
- `apps/cli/remote_mcp.py::_planes_from_settings` passes
  `lineage=settings.lineage_enabled` and `program_reporting=settings.program_reporting_enabled`.
  The planner therefore desires lineage grants **only when the CLI runs with the same
  switches as the serving process**; the runbook says so (section 6.4).
- Desired-set targets the tests pin (derived; the worker re-measures from the live
  derivation and reports any difference as a contract point): `_FULL_PLANES` unchanged
  164; `_FULL_PLANES` with `lineage` 191; with `lineage` and `program_reporting` 198;
  `_DEFAULT_PLANES` (relationship intelligence off) with both 130 (the 2 Program reads
  need the entity plane).

### 4.3 Compatibility

- No `web/src/contracts/*` fixture, `success.json`, `gateway.json` entry, decoder, tool
  schema, tool annotation, `capabilities.get` row or façade item changes: none reads the
  ChatLLM class (section 2.1). No Playwright run is needed for P1.
- The planner refuses `--profile-version chatllm-data-v9` from the P1 head on; a client
  converged on v9 plans exactly the 34 adds when both switches and the entity plane are
  on (section 10, `test_a_v9_converged_client_plans_exactly_the_lineage_adds`).
- A Knowledge Manager keeps the ordinary profile plus its 2 exceptions (unchanged); the
  lineage names are ordinary data names for it too. A Knowledge discovery or
  operator-review client is never planned with this profile (unchanged).

## 5. Provenance, rate and visibility on the ChatLLM path

### 5.1 Channel value: reuse `client_identified` / `remote_interactive`

A ChatLLM write is already recorded `client_identified` / `ordinary_reviewer` /
`remote_interactive` with the ChatLLM OAuth client id (section 2.5), and a ChatGPT write
identically with its own id. **No distinct channel value is added.** Reasons: (1) the
server cannot verify a vendor — the OAuth client id is the only server-verifiable
distinction, and it is already recorded on every fact row and request row and shown to
local readers; (2) a new `decision_channel` would widen 3 CHECKs
(`a_lineage_row_provenance_is_consistent`, `a_record_link_creator_is_known`,
`a_lineage_write_request_writer_is_known`), need a migration and change the S3.1 rate and
digest rules, for no added verifiability; (3) the compact façade is a publication shape,
not a trust signal. Reuse is safe because nothing about a ChatLLM caller differs from any
other remote OAuth client: same Principal, same derivation, same allowlists (both empty).

### 5.2 Unchanged rules, now reachable by a planner-provisioned client

- `user_directed_claim` stays an unverified claim read by no gate (S3.1 §4.1; the S3.1
  scope guard `test_no_gate_reads_the_user_directed_claim` is unchanged).
- Accepted lineage stays client-immutable (S3.1 §4.4); unreviewed client facts hold the
  close (S3.1 §4.6); only the human channel confirms (S3.1 §4.7) — and that channel is the
  CLI or the HTTP gateway `invoke` route, never either client.
- Rate buckets: ChatLLM and ChatGPT are 2 buckets (each 120/hour, 1000/day) sharing the
  Principal's 2000/day with every other client and the `local_unattested` bucket.
- Visibility: a v10 client holds the family reads of its profile (`issues.read`/`list`,
  `meetings.read`/`list`, `tasks.read`/`list`, `commitments.read`/`list`,
  `constraints.read`/`list` when composed, `capture.read`/`list`), so the S3 §6.4 rule
  shows it every family whose read it holds and nothing else; a client issued the 34
  grants individually sees only the families its other grants name.
- The composites still need the native `tasks.create` / `commitments.create` grant (S3.1
  §6.4); the v10 profile already holds both.

### 5.3 S3.1 prove-reds re-run on this path

The P1 integration module (section 10) runs these S3.1 guards with a client provisioned
by the v10 planner through the compact façade; each break is S3.1's own (S3.1 §10.2) and
the P1 test named must redden: server-derived client id → `test_a_v10_client_cannot_supply_provenance_or_a_key_through_the_facade`;
`client_identified` default → `test_a_v10_chatllm_client_commits_client_identified_lineage_through_the_facade`;
claim never upgrades → same; accepted lineage kept → `test_a_v10_client_cannot_revise_accepted_lineage`;
per-client bucket → `test_two_remote_clients_keep_separate_client_ids_and_budgets`;
facade eligibility and close/reopen operator kind → `test_withheld_lineage_names_are_absent_and_unsupported_for_a_v10_client`;
switch → `test_the_lineage_switch_off_withholds_every_lineage_name_from_a_v10_client`.

### 5.4 stdio

A stdio MCP process composes every non-operator-only tool its switches serve and holds no
grants; its lineage writes are `local_unattested`, share one bucket and carry no client
id (S3.1 §14). P1 does not change it; enabling `MY_PA_LINEAGE_ENABLED` in a stdio
process's environment exposes lineage to whatever drives that process.

## 6. Remote MCP (ChatGPT) configuration

### 6.1 Decision

ChatGPT's lineage exposure is the **default remote path**: P2 switches on, write gates
on, and the section 6.3 grants on the ChatGPT client. Nothing in code is needed for it:
S3.1 already serves a granted client. The same holds for ChatLLM, whose grants come from
`profile-apply` with v10.

### 6.2 The opt-in value, stated and guarded, not deployed

The canonical serialization of the full admissible set (sorted by name, comma-separated,
no spaces) is:

```text
MY_PA_MCP_DATABASE_PROFILE_OPT_INS=commitments.v2.list,commitments.v2.read,commitments.v2.search,commitments.v2.waiting_on,issues.closure_readiness,issues.create,issues.handoffs.correct,issues.handoffs.list,issues.handoffs.record,issues.history,issues.list,issues.memberships.add,issues.memberships.correct,issues.memberships.end,issues.project_links.add,issues.project_links.end,issues.read,issues.timeline,issues.update,issues.work.create_commitment,issues.work.create_task,meetings.notes.read_version,meetings.notes.versions,records.associations.assert,records.associations.contest,records.associations.correct,records.associations.end,records.associations.history,records.associations.reinstate,records.lineage,records.lineage.related
```

It is **not** in the P2 environment block: with the database profiles off (the deployed
shape) the process refuses to start with any opt-in set; with them on, every opted-in
lineage call fails closed until a separately reviewed privilege mechanism for existing
objects exists (S3.1 §11), and every client not mapped `ro`/`rw` is refused outright — so
commissioning the profiles for ChatGPT would **remove** lineage (and every other
capability outside the #339 ceilings of 26 reads, plus 1 write on `rw`) from it. The value is documented so the
day that mechanism exists the operator has the exact, guarded string;
`test_the_documented_opt_in_value_equals_the_admissible_set` keeps it equal to
`MCP_PROFILE_OPT_IN_CAPABILITY_NAMES` and fails closed on drift either way.

### 6.3 Production environment block (names and values; no secrets)

**Remote MCP process** (the owner-only file named by `MY_PA_REMOTE_ENV_FILE`; set or
change exactly these lines):

```env
MY_PA_LINEAGE_ENABLED=true
MY_PA_PROGRAM_REPORTING_ENABLED=true
MY_PA_LINEAGE_BACKFILL_ENABLED=true
MY_PA_REMOTE_WRITES_ENABLED=true
```

**Gateway process** (its production environment file; the human channel's CLI and
`invoke` route run here):

```env
MY_PA_LINEAGE_ENABLED=true
MY_PA_PROGRAM_REPORTING_ENABLED=true
MY_PA_LINEAGE_BACKFILL_ENABLED=true
```

**Must remain as deployed, verified read-only before P2 proceeds:**
`MY_PA_MCP_DATABASE_PROFILES_ENABLED` absent or `false`; `MY_PA_MCP_DATABASE_PROFILE_OPT_INS`
absent; `MY_PA_MCP_DATABASE_WITNESS_ENABLED` absent or `false`;
`MY_PA_MCP_CHATLLM_GATEWAY_ENABLED`, `MY_PA_MCP_CHATLLM_GATEWAY_OAUTH_CLIENT_IDS` and
`MY_PA_MCP_CHATLLM_OPERATOR_OAUTH_CLIENT_IDS` unchanged (and the deployed compose overlay
files reused exactly); `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` unchanged — if it is
off, `programs.*` stay unserved and unplanned, which is correct, not a fault.

Every one-off CLI container (`apps/cli/remote_mcp.py`, `apps/cli/invoke.py`) runs with
the environment of the process it acts for, so the planner sees the same planes.
`MY_PA_LINEAGE_BACKFILL_ENABLED` on the remote process publishes nothing (both backfill
names are operator kind); it is set there only so both files state the directive's
switch set identically.

### 6.4 Durable state and grants (P2, operator; each a mutation)

```bash
python apps/cli/remote_mcp.py control --remote-enabled --writes-enabled
python apps/cli/remote_mcp.py set-client-writes --oauth-client-id "$CHATLLM_OAUTH_CLIENT_ID" --writes-enabled
python apps/cli/remote_mcp.py set-client-writes --oauth-client-id "$CHATGPT_OAUTH_CLIENT_ID" --writes-enabled
python apps/cli/remote_mcp.py profile-diff --oauth-client-id "$CLIENT" --scope my-pa.read --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v10
python apps/cli/remote_mcp.py profile-plan --oauth-client-id "$CLIENT" --scope my-pa.read --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v10
python apps/cli/remote_mcp.py profile-apply --oauth-client-id "$CLIENT" --scope my-pa.read --resource "$OAUTH_AUDIENCE" --profile-version chatllm-data-v10 --apply
```

For each client: if `profile-plan` adds exactly the 34 names of section 3 (a client
converged on v9), apply it. If it adds more (a client not on the full-data profile, which
the ChatGPT client may be), either accept the whole v10 profile deliberately or issue the
34 grants individually with `grant --oauth-client-id … --scope my-pa.read --capability
<name> --purpose <purpose> [--write] --resource "$OAUTH_AUDIENCE"`, using the runbook's
grant table (the section 3 purpose and W/R columns; `--write` for the 16 writes). Never
grant a withheld name.

### 6.5 Runbook location and guards

A new section **"Record lineage client exposure (P1)"** in
`ops/runbooks/remote-mcp-cloudflare.md` (the runbook that owns ChatGPT, ChatLLM, grants,
write gates and the database profiles), holding: the section 6.3 block, the section 6.2
value, the section 6.4 commands, a grant table `| Canonical capability | Purpose | Write |`
of the 34 names, the switch matrix of section 7 and the residual risks of section 14.
`ops/runbooks/gateway-operations.md`'s lineage paragraphs gain one pointer sentence to it
and move "every lineage name stays an operator decision for the ChatLLM profile" to the
v10 truth; `ops/runbooks/mcp-and-cli-operations.md` gains the `chatllm-data-v10`
sentence in its profile-version paragraph and v10 commands;
`ops/runbooks/managed-knowledge-context.md` and `docs/operations/mcv-limitations.md` move
their v9 commands and statements to v10; `docs/operations/record-lineage-client-guidance.md`'s
status paragraph states the v10 exposure. Guards in section 10.

## 7. Switch matrix

| Switch | Code default | Enables | Depends on | P2 value |
| --- | --- | --- | --- | --- |
| `MY_PA_LINEAGE_ENABLED` | `false` (`src/my_pa/bootstrap/settings.py:512`) | serves the 34 lineage names (`_LINEAGE_CAPABILITIES`, `src/my_pa/application/service.py:17322`) in the process; v10 planner desires the 27 `LINEAGE` names | nothing | `true` (gateway, remote MCP) |
| `MY_PA_PROGRAM_REPORTING_ENABLED` | `false` (`src/my_pa/bootstrap/settings.py:530`) | serves the 7 S4 names; builds a 5-connection Program read pool per composing process | `MY_PA_LINEAGE_ENABLED`; the 2 `programs.*` reads also `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` and a Program read factory, `programs.overview` the Constraint plane | `true` (gateway, remote MCP) |
| `MY_PA_LINEAGE_BACKFILL_ENABLED` | `false` (`src/my_pa/bootstrap/settings.py:520`) | serves the 2 operator-only dry-run names (no apply exists) | `MY_PA_LINEAGE_ENABLED` | `true` (gateway; inert on remote MCP) |
| `MY_PA_REMOTE_WRITES_ENABLED` | `false` (`src/my_pa/bootstrap/settings.py:383`) | publishes and admits **every** remote write a client is granted, not only lineage | `MY_PA_REMOTE_MCP_ENABLED`; durable `control --writes-enabled`; per-client `set-client-writes`; a write grant | `true` (remote MCP) |
| durable global writes (`control --writes-enabled`) | off | same, durably | `MY_PA_REMOTE_WRITES_ENABLED` | on |
| per-client writes (`set-client-writes`) | off at registration | same, per client | the 2 above | on for the ChatLLM and ChatGPT clients only |
| `MY_PA_MCP_DATABASE_PROFILES_ENABLED` | `false` | restricted `ro`/`rw` roles; refuses every unmapped client | password files, cluster id | unchanged (off) |
| `MY_PA_MCP_DATABASE_PROFILE_OPT_INS` | empty | admits the 31 names to the restricted ceilings (fail closed today) | `MY_PA_MCP_DATABASE_PROFILES_ENABLED` | unset |
| `MY_PA_MCP_CHATLLM_GATEWAY_ENABLED` + allowlist | off / empty | compact façade publication shape | — | unchanged |

**Remote writes widen all remote writes.** With the 3 write gates open for a client,
every capability whose permitted purpose is in `_WRITE_PURPOSES` and on which that client
holds a write grant is published and admitted — not only lineage. For a client on the
v10 profile with every plane composed that is up to 103 writes: the 16 lineage writes
and 87 others — the `tasks.*`, `commitments.*`, `capture.*`, `meetings.*`,
`constraints.*` / `constraint_categories.*`, `continuity.*`, `documents.*`, `entities.*`,
`relationship_memory.*`, `reports.*`, `review.decide`, `canvas.workspace.put`,
`context.feedback`, `goodnotes.correct` / `propose`, `knowledge.assertions.create` and
`project_controls.configure` writes of the data profile. The exact set per client is its
`profile-plan` output after apply, filtered to writes. Turning remote writes on is
therefore a decision about each write-enabled client's whole write grant set; the
per-client flag is the control that limits it to the 2 named clients.

## 8. File plan and registration

- `src/my_pa/domain/identity/chatllm_capability_policy.py`: section 4.1 and 4.2 (version,
  classes, the 2 prerequisites, the 2 name sets, the withheld rationale, removal of the
  stale rationales).
- `src/my_pa/application/chatllm_data_profile.py`: `ChatLLMCompositionPlanes` fields and
  `_prerequisite_holds` (section 4.2); docstrings.
- `apps/cli/remote_mcp.py`: `_planes_from_settings` (section 4.2).
- Tests: section 10 (new modules, conversions, lockstep literals); `tests/ci_shard_weights.json`
  when its guard asks for the new database module.
- Runbooks and docs: section 6.5.
- This contract's section 12.1 "as implemented" notes; ADR-015's implementation-status
  paragraph for P1; the architecture index row's status.
- **Not touched:** migrations, `tables.py`, `operation.py` (`_OPERATOR_ONLY` is unchanged),
  `contracts/mcp_database_profiles.py`, `bootstrap/settings.py`, any handler, `web/`, the
  façade, `remote.py`. No count pin outside the ChatLLM class counts and the version moves
  (`Capability` stays 233, lineage set 34, `LINEAGE_WRITE_CAPABILITIES` 22, opt-in set
  31, `gateway.json` 110, head `023f8f7eb499`).

## 9. Work split (serial, one worker at a time)

| Worker | Owns | Delivers |
| --- | --- | --- |
| **P1-A** | `src/my_pa/domain/identity/chatllm_capability_policy.py`, `src/my_pa/application/chatllm_data_profile.py`, `apps/cli/remote_mcp.py`; the section 10.1 conversions and lockstep literal edits; `tests/contract/test_lineage_client_exposure_policy.py`; the additions to `tests/contract/test_chatllm_data_profile_diff.py` and `tests/unit/test_remote_mcp_chatllm_profile.py`; `tests/integration/test_lineage_client_exposure.py`; `tests/ci_shard_weights.json` if asked | sections 4 and 5 in code and tests; the section 10.2 prove-reds of its guards and the section 5.3 re-runs; ruff, mypy and floor mypy, FAST tier in per-file chunks over every touched module, `tests/architecture` incl. the CI-shard guards, the new database module and the S3.1 compact-façade and admission modules on a scratch cluster |
| **P1-B** | the 6 runbook and docs files of section 6.5; `tests/contract/test_lineage_client_exposure_runbook.py`; `tests/architecture/test_record_lineage_client_exposure_scope.py`; this contract's section 12.1; ADR-015's P1 implementation-status paragraph and the index row status | section 6.5 and the guards; docs guards (spelled-count, citation, limitation, runbook-path, link check); full local tiers at the P1 head (ruff, mypy and floor mypy, FAST, database, recovery, migration, `ci_shard` verify, `npm` lint/typecheck/test/contract/build as a no-change confirmation) |

## 10. Acceptance-test crosswalk

Same conventions as S1–S3.1 §10 (tier = marker selection; FAST = no marker; names
binding; a renamed test updates this table in the same commit; paths new unless marked
existing). `tests/architecture/test_record_lineage_client_exposure_scope.py` parses this
table and the section 10.1 table the way the S3.1 scope guard parses S3.1 §10.

| Concern | Module | Test functions | Tier |
| --- | --- | --- | --- |
| Classification (P1-A) | `tests/contract/test_lineage_client_exposure_policy.py` | `test_v10_client_usable_lineage_names_are_data_conditional` (the 34, each with its section 3 prerequisite and no exclusion rationale); `test_v10_withheld_lineage_names_are_control_plane_excluded` (the 5 with `_LINEAGE_ATTESTED_EXCLUSION`, the backfill pair unchanged, all 7 `is_operator_only`); `test_the_lineage_name_sets_equal_the_switch_sets`; `test_every_exposed_lineage_name_has_one_chatllm_purpose_and_its_remote_kind`; `test_v10_demands_lineage_grants_only_when_the_lineage_plane_is_composed`; `test_v10_demands_program_reporting_grants_only_with_both_switches_and_their_planes`; `test_v10_never_desires_a_withheld_lineage_name_in_any_composition` (every combination of the 8 plane flags, ordinary and Knowledge Manager); `test_an_active_grant_on_a_withheld_lineage_name_is_an_unexpected_control_plane_grant`; `test_v10_full_plane_targets_with_lineage_and_program_reporting` (191, 198, 130 of section 4.2); `test_no_lineage_or_remote_switch_defaults_on` (`Settings` defaults of the 4 switches false, opt-ins empty, database profiles off); `test_the_policy_matches_the_contract_exposure_table` | FAST |
| Profile diff (P1-A) | existing `tests/contract/test_chatllm_data_profile_diff.py` | new `test_a_v9_converged_client_plans_exactly_the_lineage_adds` (34 `add` actions, each its section 3 purpose and write flag); new `test_v10_adds_exactly_the_lineage_plane_names` (v10 = v9 + the 34, plane-conditional; every v9 behaviour across the 64 old compositions unchanged with both new flags off) | FAST |
| Planner CLI (P1-A) | existing `tests/unit/test_remote_mcp_chatllm_profile.py` | new `test_v10_profile_plan_adds_the_lineage_grants_only_with_the_switch_on` (Settings with the switch off: no lineage action; on: the 27 `LINEAGE` adds; with Program reporting and the entity plane: all 34) | FAST |
| Client path end to end (P1-A) | `tests/integration/test_lineage_client_exposure.py` | `test_a_v10_chatllm_client_describes_exactly_the_client_usable_lineage_names` (compact publication, planner-provisioned grants, both switches and writes on: `my_pa.describe` lists exactly the 34 and none of the 7); `test_a_v10_chatllm_client_commits_client_identified_lineage_through_the_facade` (assert and membership add through `my_pa.write`, rows `client_identified` / `ordinary_reviewer` / `remote_interactive` with the client id, `user_directed: true` stored as the claim only); `test_withheld_lineage_names_are_absent_and_unsupported_for_a_v10_client` (close, reopen, 3 confirms, 2 backfill names, each also granted directly: absent from describe and the canonical catalog, `unsupported` through every invoker); `test_with_remote_writes_off_a_v10_client_sees_only_the_lineage_reads`; `test_two_remote_clients_keep_separate_client_ids_and_budgets` (a compact ChatLLM client and a canonical ChatGPT-shaped client); `test_a_v10_client_cannot_supply_provenance_or_a_key_through_the_facade`; `test_a_v10_client_cannot_revise_accepted_lineage`; `test_a_v10_client_reads_program_reporting_on_the_default_path` (`programs.overview`, `commitments.v2.list` and `reports.manifest` answer; a restricted-profile composition still withholds `programs.*`); `test_the_lineage_switch_off_withholds_every_lineage_name_from_a_v10_client` | database |
| Runbook drift (P1-B) | `tests/contract/test_lineage_client_exposure_runbook.py` | `test_the_documented_opt_in_value_equals_the_admissible_set` (exact string equality with the sorted, comma-joined `MCP_PROFILE_OPT_IN_CAPABILITY_NAMES`, both directions); `test_the_documented_opt_in_value_needs_the_database_profiles` (Settings refuses it with profiles off, accepts it with profiles on and placeholder files); `test_the_documented_env_blocks_name_real_settings_whose_defaults_are_off` (every name maps to a `Settings` field; each code default is off; no opt-in or profile variable in either block); `test_the_documented_grant_table_equals_the_v10_lineage_set` (names, purposes and write flags equal section 3 and the policy); `test_the_runbooks_state_the_v10_profile_version` (no `chatllm-data-v9` command remains in the 4 runbook and docs files of section 6.5) | FAST |
| Scope (P1-B) | `tests/architecture/test_record_lineage_client_exposure_scope.py` | `test_every_client_exposure_crosswalk_test_exists`; `test_every_client_exposure_conversion_exists` | FAST |

### 10.1 Existing tests converted by the directive (names kept: S1–S3.1 §10 bind them)

Reason, every row: the operator directive of 2026-10-26 (the ChatLLM decision is made).
Each conversion changes exactly the classification assertion; every other assertion of
the function is kept; no skip or xfail is added. Owner P1-A.

| Module::name | Old assertion | New assertion |
| --- | --- | --- |
| `tests/contract/test_lineage_capability_admission.py::test_s1_capabilities_are_operator_decision_required` | each declared S1 name `OPERATOR_DECISION_REQUIRED` with the S1 rationale | each is `DATA_CONDITIONAL`, prerequisite `LINEAGE`, rationale `None` |
| `tests/contract/test_lineage_capability_admission.py::test_no_s1_capability_is_in_the_chatllm_data_profile` | no S1 name is data management; none is desired from the all-composed set | with the lineage plane off (the default) no S1 name is composed or desired; every S1 name is data management and desired exactly when composed |
| `tests/contract/test_lineage_s2_capability_admission.py::test_s2_capabilities_are_operator_decision_required` | all 8 S2 names `OPERATOR_DECISION_REQUIRED` | the 6 non-attested `DATA_CONDITIONAL` / `LINEAGE`; `issues.close` and `issues.reopen` `CONTROL_PLANE_EXCLUDED` with `_LINEAGE_ATTESTED_EXCLUSION` |
| `tests/contract/test_lineage_s3_capability_admission.py::test_s3_capabilities_are_operator_decision_required` | the 6 non-backfill S3 names `OPERATOR_DECISION_REQUIRED` with the S3 rationale | each `DATA_CONDITIONAL` / `LINEAGE`, rationale `None`; the backfill pair untouched |
| `tests/contract/test_lineage_s4_capability_admission.py::test_s4_capabilities_are_operator_decision_required_reads` | the 7 `OPERATOR_DECISION_REQUIRED` with the S4 rationale | each `DATA_CONDITIONAL` / `PROGRAM_REPORTING`, rationale `None` |
| `tests/contract/test_lineage_s4_capability_admission.py::test_s4_registers_no_report_type_and_issues_no_grant` | no S4 name in a data class | every S4 name in `DATA_CONDITIONAL` (the profile planner, never a bootstrap source, plans its grant); the report-type and bootstrap-source halves unchanged |
| `tests/contract/test_lineage_s31_capability_admission.py::test_s31_capabilities_are_operator_decision_required` | the 4 S3.1 names `OPERATOR_DECISION_REQUIRED`; 41 in that class | `records.lineage.related` `DATA_CONDITIONAL` / `LINEAGE`; the 3 confirms `CONTROL_PLANE_EXCLUDED` with `_LINEAGE_ATTESTED_EXCLUSION`; 2 in `OPERATOR_DECISION_REQUIRED` |
| `tests/contract/test_lineage_s31_capability_admission.py::test_no_s31_capability_is_in_the_chatllm_data_profile` | no lineage-plane name desired from the all-composed set | from the all-composed set exactly the 34 exposed names are desired and none of the 7 withheld, ordinary and Knowledge Manager alike; with the lineage plane off no S3.1 name is composed |
| `tests/contract/test_chatllm_capability_policy.py::test_classification_counts_match_the_approved_plan` | 97 / 19 / 41 | 131 `DATA_CONDITIONAL`, 24 `CONTROL_PLANE_EXCLUDED`, 2 `OPERATOR_DECISION_REQUIRED` |

**Admitted lockstep edits (assertions kept):** every `"chatllm-data-v9"` literal and
`CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v9"` assertion in `tests/` moves to
`chatllm-data-v10` (at the basis: `tests/contract/test_chatllm_capability_policy.py::test_policy_covers_every_public_capability_exactly_once`;
`tests/contract/test_chatllm_data_profile_diff.py::test_no_path_grants_every_capability_enum_member`,
`::test_a_v2_converged_client_plans_exactly_the_six_meeting_adds`,
`::test_a_v3_converged_client_plans_exactly_the_record_events_add`,
`::test_a_v4_converged_client_plans_exactly_the_capture_lifecycle_adds`,
`::test_v6_demands_the_knowledge_grants_only_when_the_plane_is_composed`,
`::test_v8_adds_exactly_provenance_and_still_excludes_the_discovery_pair`,
`::test_v9_adds_exactly_the_report_type_registry_on_every_composition`;
`tests/unit/test_remote_mcp_chatllm_profile.py::test_profile_apply_adds_the_meeting_grants_once_and_then_converges`,
`::test_profile_commands_refuse_the_previous_profile_version` (now refuses v9),
`::test_v6_profile_apply_adds_the_knowledge_grants_only_with_the_plane_on`;
`tests/contract/test_chatllm_knowledge_manager_profile.py::test_the_manager_exception_set_is_exactly_the_discovery_pair`;
`tests/unit/test_knowledge_discovery_profile.py::test_the_ordinary_chatllm_profile_excludes_submit_and_checkpoint`;
and the version line inside each section 10.1 row); docstring and comment text naming
v9 as current. P1-A lists every function it edits in section 12.1.

**Kept unchanged and still binding:**
`tests/integration/test_lineage_s31_compact_facade.py::test_a_chatllm_client_sees_and_reaches_no_lineage_capability`
builds its planes without the new flags, so it now pins the **lineage-plane-off**
planner (the default) and stays green unchanged. Its S3.1 §10.2 prove-red row (classify
`records.lineage.related` `DATA_REQUIRED`) no longer reddens it by a class change alone,
because the `LINEAGE_DATA_NAMES` set gives that name the `LINEAGE` prerequisite whatever
its data class; that S3.1 row is superseded by the section 10.2 "lineage prerequisite"
and "explicit name set" rows, which pin the same hazard (a lineage grant planned
for a process that does not compose lineage). The 64-composition tests
(`test_v8_…`, `test_v9_…`, `tests/contract/test_chatllm_knowledge_manager_profile.py::test_ordinary_desired_sets_are_unchanged_across_every_composition`)
keep their compositions with both new flags off. `tests/contract/test_chatllm_capability_policy.py::test_odr_holdout_is_explicit`
and `::test_control_plane_and_odr_are_never_data_management` stay as written and pass
(the GSQS pair is the whole holdout; every excluded name carries a rationale).

### 10.2 Prove-red expectations

Break exactly that one guard, show the named test red for that reason, restore; a green
prove-red is reported as redundancy, a masked test or an unreachable hazard, never as
"covered".

| Guard | Break | Test that must redden |
| --- | --- | --- |
| lineage prerequisite | `_prerequisite_holds(LINEAGE)` returns `True` | `test_v10_demands_lineage_grants_only_when_the_lineage_plane_is_composed`; `test_v10_profile_plan_adds_the_lineage_grants_only_with_the_switch_on` |
| Program prerequisite needs lineage | drop `planes.lineage` from `PROGRAM_REPORTING` | `test_v10_demands_program_reporting_grants_only_with_both_switches_and_their_planes` |
| Program reads need the entity plane | drop the `relationship_intelligence` clause | same; `test_v10_full_plane_targets_with_lineage_and_program_reporting` (130) |
| explicit name set | drop `meetings.notes.versions` from `LINEAGE_DATA_NAMES` (it falls to `ALWAYS`) | `test_the_lineage_name_sets_equal_the_switch_sets`; `test_v10_client_usable_lineage_names_are_data_conditional`; `test_v10_demands_lineage_grants_only_when_the_lineage_plane_is_composed` |
| CLI planes | drop `lineage=` from `_planes_from_settings` | `test_v10_profile_plan_adds_the_lineage_grants_only_with_the_switch_on` |
| withheld class | move `issues.close` to `_DATA_CONDITIONAL` | `test_v10_withheld_lineage_names_are_control_plane_excluded`; `test_v10_never_desires_a_withheld_lineage_name_in_any_composition`; `test_the_policy_matches_the_contract_exposure_table` |
| withheld grant fails closed | move `issues.reopen` to `_OPERATOR_DECISION_REQUIRED` | `test_an_active_grant_on_a_withheld_lineage_name_is_an_unexpected_control_plane_grant` |
| publication withholds attested names | remove `issues.close` from `_OPERATOR_ONLY` (temporarily, test-local) | `test_withheld_lineage_names_are_absent_and_unsupported_for_a_v10_client` (granted directly, it would be listed) |
| profile version | leave `chatllm-data-v9` | `test_v10_adds_exactly_the_lineage_plane_names`; `test_the_runbooks_state_the_v10_profile_version` |
| documented opt-in | drop 1 name from the runbook value; separately add `issues.close` to `MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES` | `test_the_documented_opt_in_value_equals_the_admissible_set` (both breaks) |
| env block defaults | default `lineage_enabled` to `True` | `test_no_lineage_or_remote_switch_defaults_on`; `test_the_documented_env_blocks_name_real_settings_whose_defaults_are_off` |
| env block names | misspell `MY_PA_PROGRAM_REPORTING_ENABLED` in the runbook block | `test_the_documented_env_blocks_name_real_settings_whose_defaults_are_off` |
| grant table | give `records.lineage.related` purpose `report_read` in the runbook table | `test_the_documented_grant_table_equals_the_v10_lineage_set` |
| contract table | change one section 3 row's v10 class | `test_the_policy_matches_the_contract_exposure_table` |
| S3.1 re-runs | each break of section 5.3 | the P1 test section 5.3 names |

## 11. Deferred work and its owner

| Item | Owner / reason |
| --- | --- |
| A privilege mechanism for existing objects on the fixed MCP roles (lineage tables; `commitments.v2.*` sources) | S3.1 §11, unchanged: a separately reviewed security package; until then no lineage call works on a restricted profile |
| `programs.*` and `reports.manifest` on the restricted profiles | S4 D-46 / S3.1 D-21 stand: the Program engine would read with broader credentials than the injected role, and `intelligence_` objects are not grantable to MCP roles; no safe alternative is proposed |
| A distinct provenance channel for ChatLLM | not needed (section 5.1); revisit only with a server-verifiable vendor signal |
| A raw-`grant` refusal for the 7 withheld names | defence in depth only (publication and handler already refuse; the planner flags the grant); a later hardening item |
| A web review/confirm UI for client facts | WP-06B (S3.1 §11); confirm stays CLI / gateway `invoke` |
| Program pool sizing on the remote MCP process | S4 §13 operator item, now live for P2 (section 14) |

## 12. Divergences — brief and repository, with resolutions

| # | Brief says | Repository truth or design reason | Resolution |
| --- | --- | --- | --- |
| DV-01 | admit the lineage names "to the remote MCP profile the ChatGPT connector uses via `MY_PA_MCP_DATABASE_PROFILE_OPT_INS`" | the connector uses the default remote path (section 2.2); the opt-in refuses start with profiles off and fails closed with them on (section 2.3) | ChatGPT exposure = switches + write gates + the 34 grants; the opt-in value is documented canonically and drift-guarded but not deployed (section 6.2) |
| DV-02 | update `web/src/contracts/*` and the `capabilities.get` manifest | neither reads the ChatLLM class | no web or manifest change; the profile version, policy, planner, tests and runbooks move |
| DV-03 | "a distinct channel value if needed" | a ChatLLM write is already `remote_interactive` with its client id | reuse; no migration (section 5.1) |
| DV-04 | "the 14 open writes + reads" | `issues.create` / `issues.update` are the only way to create and maintain an Issue, open since S1 and in the S3.1 opt-in set | both exposed; a closed Issue's update stays attested by the handler |
| DV-05 | withhold close/reopen/confirm/backfill | `OPERATOR_DECISION_REQUIRED` would state a pending decision | the 5 attested names become `CONTROL_PLANE_EXCLUDED` (fail-closed planner); publication and handler guards unchanged |
| DV-06 | `programs.*` / `commitments.v2.*` / `reports.manifest`: decide | on the default path the remote MCP process runs as the application role with its own Program pool; S4 built remote grant re-checks, family visibility and restricted manifests for remote readers (S4 §6.2, FR4-F01) | exposed to both clients on the default path (`PROGRAM_REPORTING` prerequisite); D-21 / D-46 unchanged for the restricted profiles |
| DV-07 | "re-run S3.1 prove-reds on this path" | the ChatLLM path is the S3.1 remote path; S3.1's façade rows already ran with compact publication | the section 5.3 subset re-runs with a v10-planner-provisioned client |
| DV-08 | ChatLLM gateway "profile name/version" bump | `chatllm-gateway-v1` is a publication shape the change does not touch | only `chatllm-data` bumps (v9 → v10) |
| DV-09 | backfill switch "on" | both backfill names are operator kind and never published remotely; the planner does not model the restricted-profile Program factory | set in both files for uniformity; inert remotely (section 6.3); the planner's `PROGRAM_REPORTING` rule models the default path only |
| DV-10 | a drift test for the opt-in set | the env block and the grant table can drift the same way | 5 runbook guards (section 10) |

### 12.1 As implemented

Reserved for the P1 workers' resolutions (P1-A, P1-B), each reported in its handoff and
accepted by the Orchestrator.

## 13. Operator gates that remain (P2)

None of these is authorized by P1; each is the operator's, in this order:

1. Merge the P1 PR (the PR CI must be green on the required gates).
2. Back up the production database (`ops/runbooks/postgres-operations.md`).
3. Migrate to `023f8f7eb499` (the 2 revisions above the deployed S3 head per the
   Manager's read-only recon: `c5260943d933`, `023f8f7eb499`).
4. Build and load the images at the merge commit; recreate the gateway and the remote
   MCP with the deployed compose files and overlays reused exactly.
5. Before recreating, verify read-only that the remote env has the database profiles
   off and no opt-in (section 6.3); stop if not.
6. Set the section 6.3 environment lines; recreate.
7. `control --remote-enabled --writes-enabled`; `set-client-writes` for the 2 clients only.
8. `profile-diff` / `profile-plan` v10 per client; `profile-apply` or the individual
   grants (section 6.4).
9. Acceptance with synthetic, non-personal data: describe lists the 34 and none of the
   7 for each client; one lineage write per client is recorded `client_identified` with
   its client id; a confirm from the CLI promotes it; `issues.close` from either client
   is absent and `unsupported`.
10. Optionally, the backfill dry run from the CLI (no apply exists).
11. Size the connection budget: the gateway reaches 15 backends with Program reporting
    on, and the remote MCP process adds its own 5-connection Program pool.

Ratification of ADR-015 decisions 15 and 16 beyond the directive defaults, any change to
the S3.1 rate bounds, a verified user-direction signal, the restricted-profile privilege
mechanism and any certified Program total stay separate operator gates.

## 14. Residual risks (stated plainly)

- **Unverifiable client and user claims (S3.1 §14).** The server knows the transport and
  the OAuth client id; it cannot know whether a human or a model composed a call, whether
  the user directed it, or whether evidence supports the relation. Every remote client is
  the operator Principal. `client_identified` means "an authenticated client wrote this";
  `user_directed_claim` means "that client said so". Both clients are model-driven.
- **The human channel is whoever holds the gateway `invoke` credential or the CLI**; it
  is the only promoter of client facts, so that credential is accepted-lineage authority.
- **Shared rate buckets.** ChatLLM and ChatGPT each have a bucket, but they share the
  Principal's 2000/day with each other, any other granted client and the stdio bucket;
  one misbehaving client can deny lineage writes to the other for up to 24 hours.
  Revoking its grant or its write flag is the control.
- **Remote writes widen every write.** Section 7: turning writes on for a client opens
  every write it is granted (up to 103 under v10), not only lineage.
- **Review load.** Up to 120 requests an hour per client of unreviewed facts that hold
  Issue closes until the operator confirms each through the CLI or `invoke`; no web
  review UI exists yet.
- **Model-vendor disclosure.** Lineage reads return metadata, but
  `meetings.notes.read_version` returns a historical note body to the client; with the
  MCP interaction log on, request and response bodies are kept (redacted) for 14 days.
- **Restricted profiles.** Commissioning `MY_PA_MCP_DATABASE_PROFILES_ENABLED` later
  removes lineage from every profile client until the privilege mechanism exists, and
  refuses every unmapped client.
- **Planner environment.** The planner desires lineage grants only when it runs with the
  serving process's switches; run with the wrong environment it reports no lineage gap
  rather than a wrong one.
- **Pool budget.** Program reporting adds a 5-connection pool to every composing process,
  including the remote MCP container under its 768 MiB limit.
