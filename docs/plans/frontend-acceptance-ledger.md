# Frontend Implementation / Acceptance Ledger

**Authority package:** `MYPA-PRODUCTION-FRONTEND-IMPLEMENTATION-PACKAGE-20260819-001`  
**Controlling post-audit artifact:** `18_POST_AUDIT_IMPLEMENTATION_EXECUTION_PACKAGE_20260901`  
**Repository basis:** `main@f4eaa4f950009847eb9bde2836f422d5cd731cbc`, tree `0fb4a0ecc416136e5a2a9e25a5d981e3d8a65ae2`  
**Ledger authority package:** `UI-IMP-WP01 — Target, Acceptance, and ADR Alignment`  
**Rule:** unknown is not pass.

This is the repository-controlled implementation ledger for the effective `PFE-AC-001..250` acceptance universe. It intentionally does **not** claim final frontend acceptance. The final post-workstream WP-02 acceptance reconciliation was not published, so the default disposition is `UNRECONCILED` unless an explicit current decision below supplies a narrower disposition.

## Controlled vocabulary

- `PASS_VERIFIED` — exact evidence proves the criterion at the relevant exact head/runtime.
- `IMPLEMENTATION_REQUIRED` — verified gap requires implementation.
- `VALIDATION_REQUIRED` — implementation appears present but still requires exact-head/runtime proof.
- `SUPERSEDED` — explicit current product/repository authority replaces the inherited frontend requirement.
- `JUSTIFIED_NA` — not applicable only with an explicit repository-truth rationale and accepted review.
- `UNRECONCILED` — final criterion disposition is unavailable. This is the default at WP01.

No criterion may be removed, silently renumbered, or inferred passing from absence of contrary evidence.

## Ledger schema and default values

Every ID in **ID universe** below is one ledger record. Fields are resolved by applying the source/domain/owner tables and explicit overrides below.

| Field | Default |
|---|---|
| `criterion_id` | the listed `PFE-AC-NNN` |
| `controlling_text_reference` | resolved by Source reference table |
| `domain` | resolved by Domain / owning-package table |
| `implementation_disposition` | `UNRECONCILED` |
| `owning_UI_IMP_WP` | resolved by Domain / owning-package table |
| `evidence_status` | `FINAL_WP02_RECONCILIATION_MISSING` |
| `implementation_evidence` | `NOT_YET_RECORDED` |
| `test_evidence` | `NOT_YET_RECORDED` |
| `runtime_manual_evidence` | `NOT_YET_RECORDED` |
| `supersession_or_NA_authority` | none unless explicitly overridden |
| `notes` | none unless explicitly overridden |
| `unresolved_reconciliation` | `YES` |

These defaults are deliberately conservative. WP02+ may replace `UNRECONCILED` only with evidence-backed `IMPLEMENTATION_REQUIRED`, `VALIDATION_REQUIRED`, `PASS_VERIFIED`, justified `JUSTIFIED_NA`, or an explicit current `SUPERSEDED` authority.

## ID universe — exactly 250 records

PFE-AC-001, PFE-AC-002, PFE-AC-003, PFE-AC-004, PFE-AC-005, PFE-AC-006, PFE-AC-007, PFE-AC-008, PFE-AC-009, PFE-AC-010  
PFE-AC-011, PFE-AC-012, PFE-AC-013, PFE-AC-014, PFE-AC-015, PFE-AC-016, PFE-AC-017, PFE-AC-018, PFE-AC-019, PFE-AC-020  
PFE-AC-021, PFE-AC-022, PFE-AC-023, PFE-AC-024, PFE-AC-025, PFE-AC-026, PFE-AC-027, PFE-AC-028, PFE-AC-029, PFE-AC-030  
PFE-AC-031, PFE-AC-032, PFE-AC-033, PFE-AC-034, PFE-AC-035, PFE-AC-036, PFE-AC-037, PFE-AC-038, PFE-AC-039, PFE-AC-040  
PFE-AC-041, PFE-AC-042, PFE-AC-043, PFE-AC-044, PFE-AC-045, PFE-AC-046, PFE-AC-047, PFE-AC-048, PFE-AC-049, PFE-AC-050  
PFE-AC-051, PFE-AC-052, PFE-AC-053, PFE-AC-054, PFE-AC-055, PFE-AC-056, PFE-AC-057, PFE-AC-058, PFE-AC-059, PFE-AC-060  
PFE-AC-061, PFE-AC-062, PFE-AC-063, PFE-AC-064, PFE-AC-065, PFE-AC-066, PFE-AC-067, PFE-AC-068, PFE-AC-069, PFE-AC-070  
PFE-AC-071, PFE-AC-072, PFE-AC-073, PFE-AC-074, PFE-AC-075, PFE-AC-076, PFE-AC-077, PFE-AC-078, PFE-AC-079, PFE-AC-080  
PFE-AC-081, PFE-AC-082, PFE-AC-083, PFE-AC-084, PFE-AC-085, PFE-AC-086, PFE-AC-087, PFE-AC-088, PFE-AC-089, PFE-AC-090  
PFE-AC-091, PFE-AC-092, PFE-AC-093, PFE-AC-094, PFE-AC-095, PFE-AC-096, PFE-AC-097, PFE-AC-098, PFE-AC-099, PFE-AC-100  
PFE-AC-101, PFE-AC-102, PFE-AC-103, PFE-AC-104, PFE-AC-105, PFE-AC-106, PFE-AC-107, PFE-AC-108, PFE-AC-109, PFE-AC-110  
PFE-AC-111, PFE-AC-112, PFE-AC-113, PFE-AC-114, PFE-AC-115, PFE-AC-116, PFE-AC-117, PFE-AC-118, PFE-AC-119, PFE-AC-120  
PFE-AC-121, PFE-AC-122, PFE-AC-123, PFE-AC-124, PFE-AC-125, PFE-AC-126, PFE-AC-127, PFE-AC-128, PFE-AC-129, PFE-AC-130  
PFE-AC-131, PFE-AC-132, PFE-AC-133, PFE-AC-134, PFE-AC-135, PFE-AC-136, PFE-AC-137, PFE-AC-138, PFE-AC-139, PFE-AC-140  
PFE-AC-141, PFE-AC-142, PFE-AC-143, PFE-AC-144, PFE-AC-145, PFE-AC-146, PFE-AC-147, PFE-AC-148, PFE-AC-149, PFE-AC-150  
PFE-AC-151, PFE-AC-152, PFE-AC-153, PFE-AC-154, PFE-AC-155, PFE-AC-156, PFE-AC-157, PFE-AC-158, PFE-AC-159, PFE-AC-160  
PFE-AC-161, PFE-AC-162, PFE-AC-163, PFE-AC-164, PFE-AC-165, PFE-AC-166, PFE-AC-167, PFE-AC-168, PFE-AC-169, PFE-AC-170  
PFE-AC-171, PFE-AC-172, PFE-AC-173, PFE-AC-174, PFE-AC-175, PFE-AC-176, PFE-AC-177, PFE-AC-178, PFE-AC-179, PFE-AC-180  
PFE-AC-181, PFE-AC-182, PFE-AC-183, PFE-AC-184, PFE-AC-185, PFE-AC-186, PFE-AC-187, PFE-AC-188, PFE-AC-189, PFE-AC-190  
PFE-AC-191, PFE-AC-192, PFE-AC-193, PFE-AC-194, PFE-AC-195, PFE-AC-196, PFE-AC-197, PFE-AC-198, PFE-AC-199, PFE-AC-200  
PFE-AC-201, PFE-AC-202, PFE-AC-203, PFE-AC-204, PFE-AC-205, PFE-AC-206, PFE-AC-207, PFE-AC-208, PFE-AC-209, PFE-AC-210  
PFE-AC-211, PFE-AC-212, PFE-AC-213, PFE-AC-214, PFE-AC-215, PFE-AC-216, PFE-AC-217, PFE-AC-218, PFE-AC-219, PFE-AC-220  
PFE-AC-221, PFE-AC-222, PFE-AC-223, PFE-AC-224, PFE-AC-225, PFE-AC-226, PFE-AC-227, PFE-AC-228, PFE-AC-229, PFE-AC-230  
PFE-AC-231, PFE-AC-232, PFE-AC-233, PFE-AC-234, PFE-AC-235, PFE-AC-236, PFE-AC-237, PFE-AC-238, PFE-AC-239, PFE-AC-240  
PFE-AC-241, PFE-AC-242, PFE-AC-243, PFE-AC-244, PFE-AC-245, PFE-AC-246, PFE-AC-247, PFE-AC-248, PFE-AC-249, PFE-AC-250

## Source reference table

| IDs | `controlling_text_reference` |
|---|---|
| 001..139 | Drive `08_ACCEPTANCE_AND_TEST_MATRIX` / `PFE-AC-NNN` |
| 140..226 | Drive `16_RELATIONSHIP_CANVAS_TEST_FIXTURE_PERFORMANCE_AND_ACCEPTANCE_SPECIFICATION` / `PFE-AC-NNN`, as amended by its 2026-09-01 supersession notice |
| 227..240 | Drive `08_ACCEPTANCE_AND_TEST_MATRIX` / Ambient Feedback + Review addendum / `PFE-AC-NNN` |
| 241..250 | Drive `08_ACCEPTANCE_AND_TEST_MATRIX` / Phase-3 Foundation Continuity addendum / `PFE-AC-NNN` |

Artifact `18_POST_AUDIT_IMPLEMENTATION_EXECUTION_PACKAGE_20260901` controls interpretation and implementation order wherever older package text conflicts.

## Domain / owning-package table

The owner is the package responsible for implementing or proving the criterion. Multiple owners mean the criterion spans an integration boundary; none of them may claim the criterion independently complete without the other required evidence.

| IDs | Domain | `owning_UI_IMP_WP` |
|---|---|---|
| 001..008 | Product foundation / navigation / cross-feature affordances | `UI-IMP-WP08`, with `WP10/WP24` where Evidence/Search semantics apply |
| 009..022 | Visual design / motion / interaction | `UI-IMP-WP07`, `UI-IMP-WP08` |
| 023..029 | Safe rich content | `UI-IMP-WP07` |
| 030..035 | Today composition | `UI-IMP-WP08`, `UI-IMP-WP09`, `UI-IMP-WP10`, `UI-IMP-WP12` |
| 036..047 | Work / Tasks / Commitments | `UI-IMP-WP09` |
| 048..057 | Morning Intelligence | `UI-IMP-WP11`, `UI-IMP-WP12` |
| 058..070 | Review / correction / Evidence | `UI-IMP-WP10` |
| 071..076 | People / Entity | `UI-IMP-WP13`, `UI-IMP-WP14` |
| 077..082 | Knowledge / GoodNotes | `UI-IMP-WP21`, `UI-IMP-WP22` |
| 083..085 | Federated Search / Command | `UI-IMP-WP23`, `UI-IMP-WP24` |
| 086..088 | Quick Capture / offline capture | `UI-IMP-WP05`, `UI-IMP-WP06`, `UI-IMP-WP26` |
| 089..090 | Historical browser Assistant semantics | `UI-IMP-WP01` supersession authority |
| 091..105 | Authentication / session / browser security | `UI-IMP-WP02`..`UI-IMP-WP05` |
| 106..113 | PWA / responsive | `UI-IMP-WP08`, `UI-IMP-WP26` |
| 114..122 | Accessibility | `UI-IMP-WP07`, `UI-IMP-WP08`, `UI-IMP-WP27`, `UI-IMP-WP30` |
| 123..129 | Performance / reliability | `UI-IMP-WP28`, `UI-IMP-WP30` |
| 130..139 | Testing / delivery | `UI-IMP-WP27`..`UI-IMP-WP30` |
| 140..184 | Relationship Canvas core read/workspace/edit/temporal/accessibility | `UI-IMP-WP15`..`UI-IMP-WP20` according to graph/read/workspace/edit/temporal/a11y boundary |
| 185..190 | Historical MossAIc Canvas integration semantics | `UI-IMP-WP01` supersession authority |
| 191..198 | Canvas export/fixtures/performance/degraded/visual proof | `UI-IMP-WP20`, `UI-IMP-WP27`, `UI-IMP-WP28` |
| 199..223 | Entity/Canvas contracts, mutation integrity, pagination, scale | `UI-IMP-WP13`, `UI-IMP-WP15`..`UI-IMP-WP20` |
| 224..225 | Historical MossAIc iframe/handoff semantics | `UI-IMP-WP01` supersession authority |
| 226 | Canvas terminal reconciliation | `UI-IMP-WP27`, `UI-IMP-WP30` |
| 227..240 | Ambient feedback / centralized Review | `UI-IMP-WP10`, `UI-IMP-WP27`, `UI-IMP-WP30` |
| 241..250 | Foundation continuity / integrated regression | `UI-IMP-WP07`, `UI-IMP-WP08`, `UI-IMP-WP10`, `UI-IMP-WP27`, `UI-IMP-WP30` |

## Explicit current supersession overrides

The following records override the default disposition to `SUPERSEDED` because current product authority explicitly removes browser-native MossAIc / Abacus.AI ChatLLM integration from the MY-PA frontend:

`PFE-AC-089`, `PFE-AC-090`, `PFE-AC-185`, `PFE-AC-186`, `PFE-AC-187`, `PFE-AC-188`, `PFE-AC-189`, `PFE-AC-190`, `PFE-AC-224`, `PFE-AC-225`.

For these records:

- `implementation_disposition = SUPERSEDED`
- `evidence_status = EXPLICIT_CURRENT_DECISION`
- `supersession_or_NA_authority = 18_POST_AUDIT_IMPLEMENTATION_EXECUTION_PACKAGE_20260901 + docs/plans/frontend-implementation-authority.md`
- `implementation_evidence = NO_BROWSER_NATIVE_MOSSAIC_CHATLLM_FRONTEND`
- `test_evidence = NOT_REQUIRED_FOR_RETIRED_BROWSER_INTEGRATION`
- `runtime_manual_evidence = NOT_REQUIRED_FOR_RETIRED_BROWSER_INTEGRATION`
- `unresolved_reconciliation = NO` for the retired browser-integration semantic itself; package-wide final reconciliation remains outstanding.

`PFE-AC-190` retains its underlying invariant that model/MossAIc output cannot perform the user's canonical Verify-as-fact action. That invariant continues under first-party MY-PA authority even though the browser-MossAIc criterion is superseded.

Historical evidence is preserved; supersession does not erase the original criterion text.

## UI-IMP-WP02 persistence overrides

These overrides record only the persistence substrate WP02 actually proved. They do **not** mark user-facing WebAuthn, production sign-in, or browser-cookie criteria `PASS_VERIFIED`. WP03/WP04 notes below record later ceremony and cookie wiring on this branch without production activation. Controlling text remains Drive `08_ACCEPTANCE_AND_TEST_MATRIX`.

| ID | Criterion (controlling text) | Override |
|---|---|---|
| PFE-AC-094 | Authentication challenges are random, one-time, and expiry-bounded | `implementation_disposition = VALIDATION_REQUIRED`; `owning_UI_IMP_WP = UI-IMP-WP02` (store) + `UI-IMP-WP03` (ceremony); `implementation_evidence = identity.webauthn_challenges atomic consume`; `test_evidence = tests/database/test_webauthn_auth_persistence.py` concurrent consume/replay/expiry/purpose/principal; `notes = Ceremony options/verify exist on this branch. Production activation is not claimed.` |
| PFE-AC-096 | Credential revocation is supported | `implementation_disposition = VALIDATION_REQUIRED`; `owning_UI_IMP_WP = UI-IMP-WP02` (store) + `UI-IMP-WP03` (admin UX); `implementation_evidence = identity.webauthn_credentials.revoked_at kept; active lookup excludes revoked`; `test_evidence = credential revoke persisted and excluded from active lookup`; `notes = Passkey UI exists on this branch. Production activation is not claimed.` |
| PFE-AC-097 | At least two recovery mechanisms are documented, including offline recovery codes or operator-local recovery | `implementation_disposition = IMPLEMENTATION_REQUIRED`; `owning_UI_IMP_WP = UI-IMP-WP02` (hashed recovery store) + `UI-IMP-WP03`/`UI-IMP-WP04` (second mechanism and UX); `notes = Hashed one-time recovery *persistence* exists and hashed recovery is live. Operator-local recovery ceremony and any second live mechanism are not implemented. Not PASS_VERIFIED. Do not invent operator-local recovery.` |
| PFE-AC-098 | Recovery codes are stored hashed and are one-time use | `implementation_disposition = VALIDATION_REQUIRED`; `owning_UI_IMP_WP = UI-IMP-WP02` (store) + `UI-IMP-WP03` (issue/consume UX); `implementation_evidence = identity.recovery_codes.code_hash SHA-256 hex; plaintext never persisted`; `test_evidence = plaintext absent from DB; consume-once; concurrent == 1; revoked set fails`; `notes = Recovery UX is WP03. WP04 cookie cutover does not satisfy a second recovery mechanism.` |
| PFE-AC-101 | Application session cookie is HttpOnly, Secure in production, and revocable server-side | `implementation_disposition = VALIDATION_REQUIRED`; `owning_UI_IMP_WP = UI-IMP-WP02` (server session store) + `UI-IMP-WP04` (cookie cutover); `implementation_evidence = identity.auth_sessions token_hash, idle+absolute expiry, rotate, revoke, revoke-all; this PR wires HttpOnly mypa_session to the raw AuthSessionStore SID`; `test_evidence = session create/resolve/touch-cap/rotate/concurrent rotate/second-instance; web/e2e/webauthn.spec.ts desktop proves HttpOnly 64-hex cookie and sign-out replay refusal`; `notes = This PR wires the opaque SID cookie to AuthSessionStore. Remaining runtime evidence is required. Production cutover/activation is not claimed. Not PASS_VERIFIED.` |

Unchanged and still not claimed by WP02: PFE-AC-091, 092, 093, 095, 099, 100, 102, 103, 104, 105, and user-facing WebAuthn/sign-in criteria. PFE-AC-136 security tests remain later-package evidence.

## UI-IMP-WP03 ceremony notes

Ceremony options/verify, recovery issue/consume, step-up grants, and passkey UX exist on this package. Conservative dispositions:

- PFE-AC-094/096/098 remain `VALIDATION_REQUIRED` (now with ceremony tests in addition to stores).
- PFE-AC-097 remains `IMPLEMENTATION_REQUIRED` (hashed recovery is live; operator-local recovery is not).
- PFE-AC-101 is no longer blocked on HMAC cookie minting. WP03 creates `identity.auth_sessions` rows; WP04 (this branch) sets `mypa_session` to the raw opaque SID rather than a Principal-bearing HMAC token.
- PFE-AC-091/092/093/095/099/100: `VALIDATION_REQUIRED` for ceremony/CI, not `PASS_VERIFIED` for production cutover.

## UI-IMP-WP04 cookie-cutover notes

Conservative dispositions for the opaque-SID cutover on this PR. Production Entra retirement is **not** recorded as a completed production deployment.

- **PFE-AC-097** remains `IMPLEMENTATION_REQUIRED`. Hashed recovery is live. Operator-local recovery is not implemented. Not `PASS_VERIFIED`.
- **PFE-AC-101** remains not `PASS_VERIFIED`. `implementation_disposition = VALIDATION_REQUIRED`. This PR wires HttpOnly `mypa_session` to the raw `AuthSessionStore` SID (64 hex), Next BFF talks to the Python session-service (`x-my-pa-session-service`), and desktop `web/e2e/webauthn.spec.ts` proves sign-out replay refusal. Production cutover/activation is not claimed; remaining runtime evidence is required.
- Browser Entra/MSAL and browser `local_operator` are retired as *web* `MYPA_AUTH_MODE` values (`passkey` | `synthetic` only). Python `MY_PA_AUTH_MODE` / `MYPA_GATEWAY_AUTH_MODE` are unchanged. That is a repository web-mode cutover, not a production Entra retirement or production activation.
- No Redis, no Next→PostgreSQL, no WP-05 mutation admission, no deploy.

## UI-IMP-WP05 central mutation admission notes

Conservative dispositions for central mutation admission and browser security on this PR. Production activation is **not** claimed.

- **PFE-AC-097** remains `IMPLEMENTATION_REQUIRED`. Hashed recovery is live. Operator-local recovery is not implemented. Not `PASS_VERIFIED`.
- **PFE-AC-101** remains not `PASS_VERIFIED`. `implementation_disposition = VALIDATION_REQUIRED`.
- **PFE-AC-136** is not passed from this package. Security tests remain later-package evidence.
- PFE-AC-023..029 (safe rich content / WP-07) are not passed because of `safeHref`. This package added a central fail-closed `safeHref` used by current RichContent without expanding WP-07.
- Residuals: NAS secrets cleanup is not this package; GET idle-touch Origin gating is not this package; production activation is not claimed.
- `frontend / security` now also runs the WP-05 vitest corpus; `frontend / e2e-critical` now also runs `web/e2e/browser-security.spec.ts` alongside `web/e2e/webauthn.spec.ts`. Later CI gates remain `NOT_YET_INTRODUCED`.

## UI-IMP-WP06 typed BFF contract notes

Conservative dispositions for typed BFF success, error, receipt, and degraded contracts on this PR. Production activation, whole-frontend `PASS_VERIFIED`, and Wave 1 closure are **not** claimed. Wave 1 security/shared-contract foundation is not declared complete in this ledger entry (post-merge).

- **PFE-AC-097** remains `IMPLEMENTATION_REQUIRED`. Hashed recovery is live. Operator-local recovery is not implemented. Not `PASS_VERIFIED`.
- **PFE-AC-101** remains not `PASS_VERIFIED`. `implementation_disposition = VALIDATION_REQUIRED`.
- **PFE-AC-005 / 006**: Drive criterion wording is not in the repository. Remain `UNRECONCILED`; not `PASS_VERIFIED`. WP08-owned band; this package supplies substrate only.
- **PFE-AC-126 / 131**: Remain `UNRECONCILED` (`PFE-AC-123..139` mapping discrepancy). Contract negatives and a promoting frontend contract job are substrate, not Drive `PASS_VERIFIED`.
- **PFE-AC-136** is not passed from this package.
- Capture/review/work receipt bands: named runtime decode now exists for the corresponding GatewayCapability keys. Lifecycle UX remains `UI-IMP-WP09` / `UI-IMP-WP10`. At most `VALIDATION_REQUIRED` notes; never `PASS_VERIFIED`.
- Twenty-nine `APPLICATION_GATEWAY_CAPABILITY` keys now have named runtime decoders; omitted arrays fail closed; `review.decide` no longer synthesizes version/disposition; `rate_limited` is HTTP 429; malformed success is `upstream_contract_invalid` / 503.

## Known evidence limitations / record overrides

These limitations are additive to the default `FINAL_WP02_RECONCILIATION_MISSING` status and do not create a pass:

- **All records:** final post-workstream WP-02 acceptance reconciliation is missing.
- **PFE-AC-106..113 and related PWA evidence:** `WP08_PWA_OFFLINE_AUDIT_MISSING`; WP26 is validation-first.
- **PFE-AC-077..082 and GoodNotes-related evidence:** `WP14_KNOWLEDGE_LIBRARY_GOODNOTES_AUDIT_MISSING`; WP21/WP22 remain provisional.
- **Cross-cutting test/protection records, including PFE-AC-130..139, PFE-AC-193..198, PFE-AC-226, PFE-AC-240, PFE-AC-250:** `WP16_TEST_QUALITY_AUDIT_INCOMPLETE` until the applicable protection ledger is completed by WP27.

### PFE-AC-123..139 discrepancy

`PFE-AC-123..139` carry this additional flag:

- `evidence_status += UNRECONCILED_ACCEPTANCE_MAPPING_123_139`
- `unresolved_reconciliation = YES`
- `notes = Published criterion wording and later audit normalization diverge in part of this performance/delivery range. Preserve the published IDs/text. Do not renumber, delete, weaken, or silently overwrite them. UI-IMP-WP28..WP30 separately implement/prove the route/bundle budgets, request/bootstrap ceilings, E2E/merge-blocking CI, deployment/rollback, and cross-engine browser controls identified by the later audit.`

## Browser Assistant / MossAIc implementation authority

`BROWSER_NATIVE_MOSSAIC_CHATLLM_FRONTEND = SUPERSEDED`

The frontend must not implement, reactivate, or infer a requirement for:

- ChatLLM iframe/embed;
- MossAIc sidebar;
- browser ChatLLM/provider API client;
- reverse proxy or dedicated browser tunnel for ChatLLM;
- native MY-PA chat surface;
- browser-originated Assistant action channel;
- provider-specific browser answer contract;
- manual browser handoff requirements in PFE-AC-189/225 unless separately reauthorized.

ChatLLM interaction begins in the ChatLLM UI through separately governed connected-service/MCP capabilities. Historical package artifacts remain provenance only where they conflict with this authority.

## Closure rules

1. No record becomes `PASS_VERIFIED` without exact evidence.
2. Missing evidence remains visible; no audit absence is a pass.
3. Candidate-only or fixture-only behavior cannot satisfy integrated/current-main criteria.
4. `JUSTIFIED_NA` requires a repository-truth rationale and accepted review.
5. A later material commit invalidates exact-head evidence for the changed criterion boundary.
6. Overall frontend completion cannot be claimed while any effective record remains `UNRECONCILED`.
7. WP01 completion establishes this ledger and authority only; it does not resolve the remaining 240 non-superseded criteria.