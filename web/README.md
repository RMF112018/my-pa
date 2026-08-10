# `web/` — MossAIc frontend shell

**Status:** four of the seven acceptance surfaces are wired to the Python
gateway; three are not, and this file says which and why. The synthetic fixture
provider is off unless explicitly configured, and in a default build no route and
no page can produce fixture data at all.

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
  development principals in a synthetic tenant — narrowed to **one** whenever the
  gateway runs `local_operator` and therefore has one identity (`D-15`; see
  "`MYPA_GATEWAY_AUTH_MODE`" below). No live Entra registration, tenant id,
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
`decide_review` partition (MU-AC-04). **Both are now backed by the Python `review.list` and
`review.decide` capabilities**; the fixture path survives only behind the explicit synthetic
switch. See "What is wired, and what is not" below.

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
a foreign person and an unknown person are indistinguishable (MU-AC-05). **These surfaces are
not backed by the Python read models**, which do exist and are unreachable over the transport;
in a default build they answer `not_implemented` rather than serving fixtures. See "What is
wired, and what is not" below.

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

## What is wired, and what is not

The table is the honest state of the seam at this head. "Real-backed" means the
route builds the canonical envelope, posts it to `POST /v1/{capability}` on the
Python gateway, and returns what came back; it does not mean the surface is
finished.

| Surface | Route | State | Python capability |
|---|---|---|---|
| System | `/api/system` | real-backed | `capabilities.get` |
| Library | `/api/library` | real-backed | `capture.list`, `capture.search`, `knowledge.search`, `knowledge.read` |
| Review | `/api/review` | real-backed | `review.list` |
| Review — decide | `/api/review/:id/decide` | real-backed | `review.decide` |
| Capture | `/api/capture` | real-backed | `capture.create` |
| Today / Pulse | `/api/pulse` | **not wired** — `not_implemented` | none exists |
| Situations | `/api/situations` | **not wired** — `not_implemented` | none exists |
| Reveal | `/api/reveal` | **not wired** — `not_implemented` | none exists |
| Projects | `/api/projects` | **not wired** — `not_implemented` | none exists |
| Relationship timeline | `/api/relationships/:id/timeline` | **not wired** — `not_implemented` | none exists |

### Why the last five are not wired, precisely

Not because the data does not exist. `SqlPulseRepository`, `SqlSituationRepository`,
`SqlProjectRepository` and `SqlRelationshipEventRepository` are real, stamp
`principal_id` on every write and filter by it on every read, and sit on tables
WP-03's migration chain created. `SituationService` routes to them.

They are unreachable over the transport. `POST /v1/{capability}` dispatches the
fifteen members of `Capability` and nothing else, and `SituationService` is
deliberately outside `ApplicationService.invoke`. Exposing any of them needs a
sixteenth `Capability` member — and `audit_events.capability` carries a **frozen**
`IN (...)` CHECK constraint listing exactly those fifteen names, widened by an
explicit forward `ALTER` each time the vocabulary grows. A member added without
one leaves every test green, because every test builds its database from scratch,
and is refused by the stored constraint on the first audited operation in the
field. So a sixteenth capability requires a migration, and the work package that
wired this seam was authorised to write none.

Reveal is a different absence: no capability takes a subject identifier and
returns its evidence spans and derivation trace at all. `knowledge.read` answers a
different question and is exposed at `/api/library` instead.

There is one further reason the relationship timeline must not be wired casually:
`relationship_identity_observations` carries a **table-wide** unique constraint, so
two Principals recording the same source version collide with an `IntegrityError`
where an absent row would have succeeded — an existence disclosure across the
partition. It is unreachable today. Whoever wires that plane owns the constraint
first.

### What the pages do, which is not what the routes do

`app/(app)/today`, `/review`, `/situations` and `/relationships/[personId]` are
server components that read the fixture modules **directly** and never call an API
route. They were not rewired here. In a default build they now fail closed rather
than rendering fixtures, because the refusal lives in the fixture modules
themselves rather than in the route handlers. Rewiring those four pages onto the
routes is follow-on work and is not done.

## The BFF transport

`src/lib/api/gateway.ts` is the server-side client to the Python gateway, and
until it existed there was none: every route assembled fixtures and
`src/lib/api/client.ts` was a browser-side wrapper around those routes.

- **Server-only, Node runtime.** It refuses outright if a browser global is
  present, and a test scans the tree for any client component or middleware that
  imports it.
- **Identity comes from the verified session and nowhere else.** The envelope's
  `principal_id` is derived by SHA-256 from the session's `tid`/`oid` — never read
  from a body, query string, or header — and `rejectCallerSuppliedPrincipal` runs
  on every payload before it is sent. On the Python side that field is
  *correlation* input which no production module reads; an architecture guard
  keeps that a measurement, and this tier does not change it.
- **The request shape has one definition.** `src/contracts/gateway.json` is read
  by this module and by `tests/contract/test_bff_gateway_contract_parity.py`, which
  checks every entry against `Capability`, the permitted purposes, `RequestMetadata`
  and each command's own dataclass fields, then feeds each probe through
  `normalize()`. There is no second copy to drift.
- **Failure is a typed state, never an empty success.** `unavailable`,
  `not_found`, `conflict`, `policy_denied` and `validation` stay distinguishable.

### `MYPA_GATEWAY_URL` and `MYPA_GATEWAY_AUTH_MODE` are required, with no defaults

`MYPA_GATEWAY_URL` has no default at all, not even loopback: a default would mean
a deployment that configured nothing still sent a principal's request somewhere
nobody chose. Unset is a refusal (`gateway_not_configured`), and it is **never** a
fallback to fixtures — the two are separate switches so that losing the backend
cannot quietly become serving synthetic data.

`MYPA_GATEWAY_AUTH_MODE` mirrors the Python `MY_PA_AUTH_MODE` and must agree with
it.

- `local_operator` — no `Authorization` header is sent, and the gateway serves its
  fixed process principal. **Every disclosure returned in this mode states that
  results belong to the deployment's single local-operator principal and are not
  partitioned by browser session**, because that is true and claiming otherwise
  would be the inaccuracy this seam exists to remove. **And in this mode the web
  tier admits exactly one Principal** (`D-15`): see below.
- `entra` — the gateway requires a bearer token, and **this tier holds none**. The
  session envelope carries `principalId`, `tid`, `oid`, `upn` and `displayName`
  and deliberately no credential, and `POST /api/session` implements no real
  sign-in — it refuses outright when `MYPA_AUTH_MODE` is `entra`. So the BFF
  refuses with `no_forwardable_credential` rather than sending an unauthenticated
  request or fabricating a token. Forwarding a real credential needs an Entra app
  registration and an MSAL sign-in path, both operator-gated and neither present.

#### `local_operator` narrows the admissible Principal set to one (`D-15`)

Disclosure was not enough. WP-06's reviewer signed in as `synthetic-a`, captured a
note, signed in as `synthetic-b`, and **read A's capture back** through
`/api/library`, including a full-text match on A's exact text. The limitation
above was on every one of those responses; nothing prevented the read. WP-07 makes
that read carry durable user-authored text, which under the operating brief's
Principal-isolation invariant is release-blocking.

A web tier offering two sign-ins over a one-identity backend is offering two
costumes for one person, so the **set of admissible principals itself narrows** to
one — the first, `synthetic-a` — whenever `MYPA_GATEWAY_AUTH_MODE=local_operator`.
It is deterministic and configuration-free: no new environment variable, because an
operator choice between two development principals buys nothing.

- `src/lib/auth/synthetic.ts` holds the narrowing. The full catalogue is
  module-private; `admissibleSyntheticPrincipals()` is the only listing anyone can
  import, so `POST /api/session`, the sign-in screen, and anything added later get
  the narrowed set without having to remember to ask. WP-06 learned that lesson with
  `fixtures/gate.ts`, where a gate in ten route handlers left four server components
  unguarded with every route test green.
- `POST /api/session` **refuses** the non-pinned key with
  `principal_not_admissible` (`403`) rather than silently signing the caller in as
  the pinned principal, because rebinding one identity to another is its own defect.
- `/sign-in` became a server component so it can read the same set; it offers one
  button, so nobody is shown a control guaranteed to fail.
- `entra` is unaffected — two real Principals there are two real datasets — and an
  unconfigured gateway mode is unaffected too, because in that state no backend
  request is made at all.
- The disclosure stays. Prevention plus disclosure is better than either.

`src/lib/auth/admissible-principals.test.ts` is the evidence: `synthetic-b` cannot
sign in at all under `local_operator`, both principals remain admissible under
`entra`.

### `MYPA_DATA_PROVIDER` gates the synthetic provider, and unset means off

One switch, no `||` fallback, refused in a production build the way
`MYPA_AUTH_MODE=synthetic` already is. Any value other than `synthetic` is refused
rather than treated as unset, so a typo is visible instead of silently safe.

The refusal lives in `src/lib/fixtures/gate.ts` and every fixture entry point
calls it — including `syntheticDisclosure`, because the label is the half that can
lie on its own. That placement is the guarantee: a gate written into the ten route
handlers would have left the four server components above serving fixtures in a
default build while every route-level test stayed green.

`src/app/api/routes.test.ts` asserts the default build both ways: with the switch
unset the fixture functions throw and no route returns fixture data, and with it
set the synthetic surfaces carry `coverage: "synthetic"` /
`authority: "synthetic_fixture"` while backend-served ones never do.

## Commands

```bash
cd web
npm install
export MYPA_SESSION_SECRET="$(openssl rand -hex 32)"   # required to serve; see below
export MYPA_AUTH_MODE=synthetic                        # required to serve; see below
export MYPA_GATEWAY_URL=http://127.0.0.1:8000          # required; no default; see below
export MYPA_GATEWAY_AUTH_MODE=local_operator           # required; no default; see below
# export MYPA_DATA_PROVIDER=synthetic                  # optional; OFF unless set
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

### `MYPA_AUTH_MODE` is required too, and unset is a refusal

Two values, `synthetic` and `entra`, and no default. Until WP-05,
`POST /api/session` would mint a session for either hardcoded synthetic
principal with **no gate at all** — no mode, no environment check, nothing. A
deployment did not have to be a development one for the passwordless sign-in
buttons to work, and nothing said so.

- `synthetic` — the two fixed development principals. **Refused outright when
  `NODE_ENV === "production"`**, rather than warned about.
- `entra` — real sign-in. A synthetic key is refused (`403`), and
  `MYPA_ENTRA_HOME_TENANT_ID` must name the tenant whose tokens are accepted;
  without it the deployment cannot reject a foreign tenant and so refuses to
  answer. A live Entra registration is operator-gated and is not configured
  anywhere in this repository.

### Sessions are revocable, and revocation is enforced on the Node side

The session envelope carries a random `sid`. Signing in registers it and revokes
whatever that principal held before, so a session identifier cannot be carried
across a sign-in. Signing out **revokes the `sid` server-side** and then clears
the cookie — in that order, because clearing a cookie is a request the holder may
decline, and the property that matters is that replaying the exact same cookie
value after sign-out is refused. An idle timeout applies on top of the absolute
expiry.

The registry (`src/lib/auth/session-registry.ts`) is an in-memory `Map` in the
Node runtime. It is **process-local and lost on restart** — the web tier has no
durable store at this head — and that limitation is stated in the module rather
than implied away.

`src/middleware.ts` runs in the **Edge** runtime and cannot see that registry, so
it is a cheap signature-and-expiry pre-filter and **not** the authority. The
authority is `src/lib/auth/principal.ts`, which every `/api/*` route handler and
every server component that needs a principal goes through. Do not call
`verifySession` directly from a Node route; it cannot see a revocation.

### Sign-in requests no Microsoft Graph scope

`src/lib/auth/msal.config.ts` asked for `User.Read` until WP-05, which is a Graph
resource scope and therefore a Graph consent dependency on the sign-in path.
Sign-in now requests `openid`, `profile`, `offline_access`, plus the
application's own API scope when `NEXT_PUBLIC_MYPA_API_SCOPE` names one — and a
value that points at Graph is dropped rather than honoured.
`src/lib/auth/msal.config.test.ts` holds that, and holds that no module on the
sign-in path imports or starts a Graph connector, delta worker, or webhook.

## Boundary rules

1. Identity derives only from the verified session; request payloads carrying
   `principal_id`/`principalId`/`tid`/`oid` are rejected at the client wrapper
   (`src/lib/api/client.ts`), again at every route (`src/lib/api/guard.ts`), and a
   third time before anything leaves for the backend (`src/lib/api/gateway.ts`).
   No Principal is ever supplied by a browser: the identifier on the wire is
   derived from the session, and a foreign one in a body, query string, or header
   reaches nothing.
2. Every API response carries a `DisclosureEnvelope`, and it is accurate in both
   directions: synthetic data is always labeled synthetic, and backend data never
   is. Neither label is reachable from the other's code path.
3. Nothing is asserted on the user's behalf; the shell language keeps proposals
   and dispositions distinct even while the pipeline is a stub.
