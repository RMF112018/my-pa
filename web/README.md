# `web/` — MossAIc frontend shell

**Status:** `IMPLEMENTING` (WP-02 / R1)

The Next.js (App Router) progressive web app for `my-pa`, decided by
[`docs/decisions/ADR-004-mossaic-frontend-nextjs-app-router.md`](../docs/decisions/ADR-004-mossaic-frontend-nextjs-app-router.md).
Routed by `docs/00_REPOSITORY_SOURCE_INDEX.md`.

## What WP-02 delivers — and what it does not

Delivered:

- The five destinations — **Today, Situations, Review, Library, System** — inside a
  persistent shell (context header, desktop navigation rail, mobile bottom navigation),
  with landmarks, visible focus, and a skip link.
- The **identity boundary**: HMAC-signed HttpOnly session cookie, Edge-runtime route
  guard (`src/middleware.ts`), server-side re-verification in the signed-in layout, and
  claims validation with the same rules as the Python identity domain — home-tenant
  check, UUID `oid`, and outright rejection of caller-supplied identity fields
  (`src/lib/auth/claims.ts`).
- A **synthetic identity provider** (`src/lib/auth/synthetic.ts`) with two fixed
  development principals in a synthetic tenant. No live Entra registration, tenant id,
  or personal data anywhere. The real MSAL wiring has a configuration seam
  (`src/lib/auth/msal.config.ts`) and is inert until one exists.
- **Canonical TypeScript contracts** (`src/contracts/`) — parity mirror of the Python
  contract and domain vocabulary; see `src/contracts/README.md`.
- **Capture** and **Reveal** affordances posting to stub API routes that acknowledge
  with `coverage: "synthetic"` disclosures; a principal-scoped synthetic **Pulse** on
  Today; honest "not yet connected" states on Situations and Library; full
  disclosure on System.
- **PWA install surface**: web manifest plus a minimal network-only service worker.
  No offline queue — that is WP-04 (R3).

WP-05 (R4) adds the **Review workbench**: a principal-scoped listing (`/api/review`) and
per-case disposition route (`/api/review/:id/decide`) that turn a proposal into a
canonical record only on an explicit accept / correct-and-accept, returning the immutable
receipt the promotion issues. Correct-and-accept preserves the original proposal. The
listing and every disposition are scoped to the signed-in principal — a foreign case is
`not_found`, never disclosed — the web-tier shadow of the Python `review_cases` /
`decide_review` partition (MU-AC-04). Cases are principal-scoped synthetic fixtures until
the Python read models are wired.

WP-06 (R5) adds the **relationship / project continuity** surfaces. The **Situation board**
(`/situations`, `/api/situations`, `/api/projects`) gathers the principal's Situations and
Projects into one purposeful view — a Situation references records it does not own and shows
their state without claiming authority. The **relationship timeline**
(`/relationships/:personId`, `/api/relationships/:personId/timeline`) shows a person's
accepted interactions, meetings, and commitments in time order. Both read **only accepted
records**: a proposed (not-accepted) relationship event never surfaces on a timeline, the
web-tier shadow of the Python `list_accepted_events` filter, and this is the WP-06 gate that
Today/Pulse and timelines read only accepted records. Every listing is scoped to the signed-in
principal, and a person that does not resolve in the caller's own partition is `not_found` —
a foreign person and an unknown person are indistinguishable (MU-AC-05). Records are
principal-scoped synthetic fixtures until the Python continuity read models are wired.

Not delivered here: capture persistence and the processing pipeline (WP-03), offline
(WP-04), the Microsoft Graph connector (WP-07), AI processing (WP-08), and the To-Do
projection (WP-09).

## Commands

```bash
cd web
npm install
npm run dev        # development server
npm run lint       # eslint
npm run typecheck  # tsc --noEmit
npm test           # vitest (unit + component)
npm run build      # production build
```

## Boundary rules

1. Identity derives only from the verified session; request payloads carrying
   `principal_id`/`principalId`/`tid`/`oid` are rejected at the client wrapper
   (`src/lib/api/client.ts`) and again at every route (`src/lib/api/guard.ts`).
2. Every API response carries a `DisclosureEnvelope`; synthetic data is always
   labeled synthetic, in the payload and in the UI.
3. Nothing is asserted on the user's behalf; the shell language keeps proposals
   and dispositions distinct even while the pipeline is a stub.
