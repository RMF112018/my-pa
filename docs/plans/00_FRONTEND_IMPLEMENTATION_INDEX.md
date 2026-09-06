# Frontend Implementation Index

**Status:** Active repository routing for the post-audit frontend implementation program.  
**Repository basis at creation:** `main@f4eaa4f950009847eb9bde2836f422d5cd731cbc`, tree `0fb4a0ecc416136e5a2a9e25a5d981e3d8a65ae2`.

Use these repository-controlled sources for frontend implementation:

1. [`frontend-implementation-authority.md`](frontend-implementation-authority.md) — current implementation sequence `UI-IMP-WP01..WP30`, target auth/session authority, browser-MossAIc/ChatLLM supersession, evidence limitations, and WP01 scope boundary.
2. [`frontend-acceptance-ledger.md`](frontend-acceptance-ledger.md) — complete `PFE-AC-001..250` implementation/acceptance universe and conservative current dispositions.
3. [`../decisions/ADR-011-passkey-webauthn-authentication-and-opaque-server-sessions.md`](../decisions/ADR-011-passkey-webauthn-authentication-and-opaque-server-sessions.md) — accepted production browser authentication/session target.
4. [`../decisions/ADR-004-mossaic-frontend-nextjs-app-router.md`](../decisions/ADR-004-mossaic-frontend-nextjs-app-router.md) — retained Next.js/BFF/PWA architecture with the conflicting authentication/session provisions explicitly superseded by ADR-011.
5. [`../decisions/ADR-008-nas-runtime-topology.md`](../decisions/ADR-008-nas-runtime-topology.md) — retained NAS/runtime topology with its Entra browser-auth selection explicitly superseded by ADR-011.
6. [`frontend-auth-persistence.md`](frontend-auth-persistence.md) — WP02 durable credential/challenge/recovery/session substrate, plus the WP04 opaque-SID cookie cutover on this PR. Does not claim production activation.

## Execution order

The controlling post-audit sequence is `UI-IMP-WP01..WP30`. Older `WP-FE-*` ordering is historical where conflicting.

`UI-IMP-WP01` is architecture/acceptance authority only. It does not implement runtime authentication or any later frontend package.

`UI-IMP-WP02` persistence substrate exists on `identity.*` (Alembic `2c00c9ac64bc`). It does not itself implement WebAuthn ceremonies.

`UI-IMP-WP03` ceremony and `UI-IMP-WP04` opaque-SID cookie cutover are implemented on this PR branch. The live cookie is the raw `AuthSessionStore` SID. That is not a production activation, production Entra retirement, or `PASS_VERIFIED` claim.

`UI-IMP-WP05` central mutation admission and browser security are on `main`. That is not a production activation or `PASS_VERIFIED` claim.

`UI-IMP-WP06` typed BFF success, error, receipt, and degraded contracts are implemented on this PR. That is not production activation, not `PASS_VERIFIED` of the whole frontend, and not Wave 1 closure until post-merge audit.

`NEXT_EXECUTABLE_PACKAGE: UI-IMP-WP27 Cross-Cutting Test Protection Hardening is implementing on this branch over current main (`21b39739` / PC-CM-IMP-WP03 #213, which includes merged WP21–WP26). WP22 is on main (`7d29d9ae` / #214). This package does not implement WP28 gate promotion, WP29 deployment, or WP30 runtime acceptance. WP14_KNOWLEDGE_LIBRARY_GOODNOTES_AUDIT_MISSING and WP08_PWA_OFFLINE_AUDIT_MISSING remain evidence limitations. gsqs.start remains not browser-admitted. frontend / pwa-offline and frontend / browsers remain ADVISORY.`

## Evidence limitations

Implementation may proceed while these remain explicit closure obligations:

- missing final post-workstream WP-02 acceptance reconciliation;
- missing dedicated WP-08 PWA/offline audit;
- missing dedicated WP-14 Knowledge/Library/GoodNotes audit;
- incomplete WP-16 exhaustive test-quality/protection audit (WP27 records current protection in `frontend-protection-ledger.json`; that is not `PASS_VERIFIED`).

These limitations are never implicit passes. The `PFE-AC-123..139` mapping discrepancy also remains explicitly `UNRECONCILED` until later evidence resolves it.