# `web/` — MossAIc frontend shell

**Status:** built across WP-00 through WP-06 of the **superseded** Moss v4.0
campaign; runs against synthetic fixtures only and is not deployable.

The Next.js (App Router) progressive web app for `my-pa`, decided by
[`docs/decisions/ADR-004-mossaic-frontend-nextjs-app-router.md`](../docs/decisions/ADR-004-mossaic-frontend-nextjs-app-router.md).
Routed by `docs/00_REPOSITORY_SOURCE_INDEX.md`.

The operating lineage for this repository is
`recovery/pre-20260805-utc-rollback-c9fb513`; see
[`../README.md`](../README.md) and
[`../docs/campaign/CAMPAIGN-BRIEF.md`](../docs/campaign/CAMPAIGN-BRIEF.md).
**The `WP-nn` / `Rn` labels in this file are the superseded Moss v4.0
campaign's own numbering and do not refer to the work packages of the current
campaign, which reuses the same numbers for different work.** This file
previously read `Status: IMPLEMENTING (WP-02 / R1)`, which described neither
the delivered state of this shell nor any current work package.

## What the R1 slice delivers — and what it does not

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

Not delivered here: capture persistence and the processing pipeline, offline support,
AI processing, and the To-Do projection. These were sequenced as WP-03, WP-04, WP-08
and WP-09 of the superseded Moss v4.0 campaign; that sequencing is not a current
delivery schedule.

**Personal-data ingestion is Apple-first.** Apple Mail, Calendar, Contacts, and
Tasks/To-Do through the first-party native Apple architecture
([`../native/apple-source-host/README.md`](../native/apple-source-host/README.md))
are the active ingestion direction. Microsoft Graph is retained in the product
definition but **off by default and not an active personal-data ingestion path**; a
disabled Graph connector must not be reported as a degraded active source. The Entra
authentication used by this shell's synthetic identity boundary is a separate concern
from Graph connector activation. This file previously listed "the Microsoft Graph
connector (WP-07)" among the things pending delivery here, which presented the
superseded Graph-primary sequencing as a live commitment; it is not one.

## Commands

```bash
cd web
npm install
export MYPA_SESSION_SECRET="$(openssl rand -hex 32)"   # required to serve; see below
npm run dev        # development server
npm run lint       # eslint
npm run typecheck  # tsc --noEmit
npm test           # vitest (unit + component)
npm run build      # production build
```

### `MYPA_SESSION_SECRET` is required, and there is no default

The session cookie carries `principalId` and is trusted by `src/middleware.ts`
and by every `requirePrincipal` route, so the key that signs it decides who the
shell believes anyone is.

Until WP-04, `sessionSecret()` fell back to a hardcoded literal when the
variable was unset. That failed **open** and silently: a deployment missing one
environment variable accepted any session anyone chose to mint, for any
principal, and a forged signature verified exactly like a real one. The
fallback is gone. `MYPA_SESSION_SECRET` must be set to at least 32 characters,
or `encodeSession` and `verifySession` raise `MissingSessionSecretError` and the
request fails rather than resolving to a principal.

`npm run build` does not need it — nothing evaluates the key at build time —
but `npm run dev` and `npm start` do, from the first request onward. The tests
supply their own key explicitly in `vitest.setup.ts`; do not reintroduce an
implicit default to make anything green.

## Boundary rules

1. Identity derives only from the verified session; request payloads carrying
   `principal_id`/`principalId`/`tid`/`oid` are rejected at the client wrapper
   (`src/lib/api/client.ts`) and again at every route (`src/lib/api/guard.ts`).
2. Every API response carries a `DisclosureEnvelope`; synthetic data is always
   labeled synthetic, in the payload and in the UI.
3. Nothing is asserted on the user's behalf; the shell language keeps proposals
   and dispositions distinct even while the pipeline is a stub.
