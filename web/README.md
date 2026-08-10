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
- **Capture**, wired to the durable `capture.create` path, with the four outcomes
  below kept apart, and a **Reveal** affordance posting to a stub API route that acknowledges
  with `coverage: "synthetic"` disclosures; a principal-scoped synthetic **Pulse** on
  Today; honest "not yet connected" states on Situations and Library; full
  disclosure on System.
- **PWA install surface**: web manifest plus a service worker that caches static
  assets only and **never** anything under `/api/*`. The offline capture queue is
  in `src/lib/offline/` and is described under "Offline capture" below.

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

Not delivered here: AI processing and the To-Do projection. Capture persistence and
the processing pipeline are the Python side's and are wired; offline capture is
delivered and is described under "Offline capture" below. These were sequenced as
WP-03, WP-04, WP-08 and WP-09 of the superseded Moss v4.0 campaign; that
sequencing is not a current delivery schedule.

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
| Today / Pulse | `/api/pulse` | real-backed | `continuity.pulse` |
| Situations | `/api/situations` | real-backed | `continuity.situations` |
| Projects | `/api/projects` | real-backed | `continuity.projects` |
| Reveal | `/api/reveal` | real-backed | `knowledge.reveal` |
| Relationship timeline | `/api/relationships/:id/timeline` | **not wired** — `not_implemented` | none exists |

Every **page** in `app/(app)` now reaches a capability directly too, which was
not true before WP-13: `library`, `review`, `today`, `situations` and `system`
are server components that call `lib/api/gateway` themselves. `library` and
`review` were the two that did not — `library` rendered a fixed "no sources are
connected yet" card in front of an already-wired capability, and `review` called
a fixture module that throws in a default build. The relationship timeline page
is the one destination that still has no capability to reach, and it now says so
instead of raising.

### What the capture surface says, and what it refuses to say

The screen's job is to tell a person which of four things happened, because that
is what they act on, and the dangerous direction is asymmetric: saying "saved"
for something that was not stored tells someone to stop worrying about a note
that is gone, while saying "refused" about a note that was stored merely annoys
them. So the four are kept apart and the recognition is positive —
`status: "persisted"` is the **only** condition that renders as a save, and an
answer whose shape the screen does not recognise understates rather than
overstates.

| Outcome | What is true | What the screen does |
|---|---|---|
| durable | the Python transaction committed and issued the receipt | says **saved**, clears the field |
| acknowledged, not persisted | the explicitly-enabled synthetic provider minted an in-process receipt | says **not stored**, keeps the note in the field |
| refused | validation, conflict, authorization, policy — nothing stored | names the reason, keeps the note |
| unavailable | the backend answered that it could not serve — nothing stored | says retrying is worth it, keeps the note and the same attempt key |
| queued | the request never reached the server; the note is encrypted and held **on this device only** | says held on this device and **not saved on the server**, clears the field |
| not held | the note could not even be queued — no offline storage, no storable non-extractable key, or the device queue is at its bound | names the reason, keeps the note in the field |

`queued` is never rendered as a save, and the copy says so in the same sentence
that reports it. The asymmetry is the same one that governs the first four: a
person who reads "held" as "filed" closes the tab on the only copy of their note.

**No enrichment state, and the absence is deliberate.** A save is durable before
any processing runs, and no capability this tier can call reports how that
processing went — `POST /v1/{capability}` dispatches fifteen and none of them
answers "what happened to the job". So the screen says the note is safe and that
proposals appear in Review when they exist. Inventing an "enrichment degraded"
badge here would be a claim with nothing behind it.

**One non-empty field is the whole precondition.** No title, no tags. The kind
defaults to `quick_note` and `conversation_log` is a selection rather than a
step; `POST /api/capture` refuses any other value instead of defaulting it, so a
caller that misspelled the kind is told rather than quietly given something else.

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

Every signed-in page is a server component that reaches `lib/api/gateway`
**directly** rather than calling its own API route. That is deliberate and is the
pattern `app/(app)/today` established: a server component that fetched its own
route would be a second copy of the same decision, and the two copies would
drift. The route handlers exist for the client-side surfaces — the capture
dialog, the reveal dialog, the review workbench — which are browser code and have
no other way in.

Each page classifies the gateway's answer through `lib/api/surface-answer.ts`,
which is one function rather than five copies of an `if`, and renders one of four
states from `components/ui/surface-state.tsx`. The four are **empty**,
**unavailable**, **degraded** and **not_implemented**, and the ordering inside
`surfaceAnswer` is the whole of the guarantee: a failed call and a `coverage:
"unavailable"` answer are classified *before* any row is counted, so an
unreachable backend can never reach the branch that says "you hold nothing".

`/relationships/[personId]` is the one page with no capability behind it. It
renders `not_implemented` naming the two reasons — no v1 capability exposes the
relationship read model, and `relationship_identity_observations` carries a
table-wide unique constraint that has to be partitioned before the plane can be
read across Principals — rather than raising, which is what it did before.

## Offline capture

`src/lib/offline/` holds a note that could not be sent, encrypted, on this
device, and replays it when the connection returns. Nothing about it is a
substitute for the server: a queued note is not saved anywhere the server knows
about, and every surface says so.

### The seven controls, and where each lives

| Control | Where | Proved by |
|---|---|---|
| queued and saved are visibly different states | `components/shell/capture-dialog.tsx` | `components/shell/capture-offline.test.tsx` |
| a queued entry never rebinds Principal | `lib/offline/replay.ts` | `lib/offline/replay.test.ts` |
| an account switch quarantines rather than replays | `lib/offline/queue.ts`, `lib/offline/replay.ts` | `lib/offline/queue.test.ts`, `components/offline/offline-status.test.tsx` |
| a stale session fails closed to `needs_reauth` | `lib/offline/replay.ts` | `lib/offline/replay.test.ts` |
| the local payload is deleted only for a verified receipt | `lib/offline/replay.ts` | `lib/offline/replay.test.ts` |
| append-only and bounded | `lib/offline/queue.ts` | `lib/offline/queue.test.ts` |
| idempotent replay | `lib/offline/queue.ts`, `lib/offline/replay.ts` | `lib/offline/replay.test.ts` |

**These are unit and integration proofs, not end-to-end browser proofs, and the
distinction is not a formality.** The queue, the keys, the fold, the replay
function and IndexedDB are all real in those tests; the network transport is
faked. A browser run of "sign in as A, capture offline, sign in as B, observe the
quarantine" is **not constructible at this head**: under
`MYPA_GATEWAY_AUTH_MODE=local_operator` the web tier admits exactly one Principal
(`D-15`), and with the gateway mode unset or `entra` every backend route refuses,
so no reachable configuration admits two identities *and* serves backend data.
None was performed and none is implied.

### What a verified receipt is

A local payload is deleted for a receipt that has been checked, never for an
HTTP 200. All four of these must hold:

1. `shape === "backend"` — the synthetic provider's `acknowledged_not_persisted`
   answer has a different shape and **never** deletes anything;
2. `status === "persisted"`;
3. `receipt.receiptId` is present and non-empty, and `receipt.idempotencyKey`
   equals the key this entry was minted with;
4. `receipt.contentSha256` equals a SHA-256 computed here over the same bytes the
   backend hashes.

The fourth is checkable because the backend's digest is reproducible from this
tier: `my_pa.domain.capture.version.digest_of` is
`hashlib.sha256(text.encode("utf-8")).hexdigest()` over the capture text **as
stored**, with no normalisation anywhere on the Python path, and
`POST /api/capture` sends `text.trim()` which the Python side stores verbatim.
The test carries the interpreter's own output for a fixed string, so the two
implementations are compared rather than left to agree with themselves.

Anything else — a transport failure, a non-2xx, a malformed body, a partially
shaped receipt, a mismatched digest — leaves the ciphertext exactly where it was.

### The bound refuses; it never evicts

At 50 held entries or 1,000,000 held ciphertext bytes a new enqueue raises
`OfflineQueueFullError` and the dialog keeps the note in the field with the bound
named. Nothing is evicted and nothing is dropped: deleting a note somebody
believes is held is the one outcome a queue must never produce.

### Replay is a foreground path

It runs when the shell mounts and when the browser fires `online`. **Background
Sync is not used and no background-sync guarantee is claimed** — a note queued in
a tab that is then closed stays queued until the app is opened again.

### The service worker caches static assets and never `/api/*`

A cache is shared by every session using this browser profile, while every `/api`
response was produced for one signed-in Principal, so a cached `/api` response
served to a later session would be a cross-Principal disclosure with the worker
as the carrier. `public/sw.js` refuses `/api` explicitly, and also refuses HTML
documents, because a server-rendered page here can carry the signed-in
principal's display name. `src/lib/offline/sw.test.ts` evaluates the real
`public/sw.js` against a recording scope and asserts that no cache operation
occurs for any `/api` path.

**Consequently this does not make the app cold-start offline, and it is not
described as doing so.** What it buys is that an already-open tab keeps its
assets when the network drops. The worker holds no queue and no key.

### OD-COMP-004: device-local protected key — what it is, and what it is not

The queued payload is encrypted with AES-GCM 256. The key is generated by
`crypto.subtle.generateKey(..., extractable: false, ...)`, is stored as a
`CryptoKey` in IndexedDB, is **per principal** — one key record per
`principalId`, so a note queued by A is not decryptable with B's key — and is
never exported, never serialised, never sent anywhere, and never logged. A fresh
random 96-bit IV is drawn for every record.

**If a non-extractable key cannot be established or stored, the enqueue is
refused.** There is no fallback to an extractable key, none to a key held only in
memory, and none to plaintext; a stored key that reads back `extractable === true`
is refused rather than used. `src/lib/offline/key.test.ts` proves the
no-downgrade property directly, including the case where `generateKey` is made to
return an extractable key and the case where the store refuses to hold one.

**The limitations are real and are stated rather than implied away. This raises
the bar against casual local inspection and against offline disk access. It is
not a confidentiality guarantee against an attacker with same-origin execution.**

- **Not hardware-backed** in most browsers. `extractable: false` is enforced by
  the browser's object model, not by a secure element or a TPM, and this code
  cannot tell the difference.
- **Same-origin script reaches the decryption capability.** An XSS, a compromised
  dependency, a browser extension with host access, or a devtools console can
  open the same database, obtain the same `CryptoKey` handle, and call `decrypt`.
  `extractable: false` stops the raw bytes being read out; it does not stop the
  key being *used*. Against that attacker the encryption buys close to nothing.
- **Local profile access is a partial defence, not a total one.** Reading the raw
  IndexedDB files with an unrelated tool does not yield plaintext; using the
  browser's own tooling against the same profile may.
- **No protection against a compromised device** — keylogger, hostile OS account,
  malicious extension, or a disk image taken while the profile is unlocked.
- **Storage is evictable.** The browser may clear this database under storage
  pressure, in private browsing, or when the user clears site data. If the key is
  evicted the queued ciphertext is permanently undecryptable; if the database is
  evicted the queued notes are gone. There is no copy anywhere else and neither
  is recoverable.

### Known limitation: quarantine is terminal for automatic replay

A quarantined entry keeps its bytes and stays visible as a count and a state, but
nothing in this package releases it — not even signing back in as the principal
that queued it. Releasing one would need a user-initiated control that does not
exist here, so a quarantined entry occupies its share of the bound indefinitely.
There is also no user-initiated discard: the only removal is the receipt-verified
deletion above.

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
npm test           # vitest (unit + component) — never the browser suite
npm run build      # production build
npm run e2e        # the browser suite; see below
```

### `npm run e2e` — a real browser against the real stack

`e2e/stack.sh` creates a **disposable** PostgreSQL database at head, starts
`apps/gateway.py` on loopback, and hands over to Playwright, which starts two
Next servers of its own and drives Chromium against them. The database is
dropped afterwards, and dropped first as well, so an interrupted run is cleaned
up by the next one. It needs the repository venv (`../.venv`) and the same
PostgreSQL the Python suites use; it needs no credential.

Three things about it are worth knowing before reading its results:

* **It runs `next dev`, and that is forced rather than convenient.** The only
  sign-in this build implements is the synthetic provider, and `lib/auth/mode.ts`
  refuses it outright when `NODE_ENV === "production"`. `next start` sets that.
  So a browser run that signs in has to be a dev run. The production build is
  checked by `npm run build`, which is a separate and honest claim.
* **The second Next server exists to fail.** Its `MYPA_GATEWAY_URL` names a port
  nothing listens on, so `e2e/failure-states.spec.ts` reaches the genuine
  connect-refused path through the real transport rather than a stub. A browser
  cannot intercept the gateway call — it happens on the server — so this is the
  only way that path can be exercised for real.
* **It is not in the unit baseline.** `vitest.config.ts` includes `src/**` only
  and these live in `e2e/`, so `npm test` neither collects nor reports them.

A run reports 72 tests across two viewports — a 1280x800 desktop and a Pixel 7
profile — of which one, the 44px touch-target rule, is skipped on desktop by
design.

### Dependencies added here

`fake-indexeddb` (devDependency, test-only). jsdom exposes no IndexedDB, and the
offline queue is IndexedDB — inventing an abstraction so the tests could avoid it
would be the speculative layer `AGENTS.md` section 2 forbids and would mean the
tests exercised the wrapper rather than the store. It is required by no runtime
code path, is imported only from `*.test.ts(x)`, and removing it means removing
the offline tests. It round-trips a non-extractable `CryptoKey` in this
environment, so the real key path is exercised rather than approximated.

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

A `sid` is live **for one principal**, and `touchSession` checks that as well as
liveness. Until WP-08 it checked liveness only, so a session envelope naming
principal B while carrying principal A's live `sid` resolved to B. Reaching that
state requires the HMAC signing secret — which permits forging any identity
outright — so it was never a reachable isolation hole; it is closed anyway
because it is one comparison. `src/lib/auth/session-binding.test.ts` holds it.

The registry (`src/lib/auth/session-registry.ts`) is an in-memory `Map` in the
Node runtime. It is **process-local and lost on restart** — the web tier has no
durable store at this head — and that limitation is stated in the module rather
than implied away.

Note also that the `D-15` admissible-Principal pin is enforced at **sign-in**,
not at session verification: `resolveSessionPrincipal` re-checks the signature,
the registry, the idle window and now the principal binding, but it does not
re-check admissibility. A `synthetic-b` cookie minted before the pin existed
therefore fails `401` because the registry is process-local and lost on restart,
not because admissibility was re-evaluated. WP-08 did not widen that pin.

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
4. A note held offline is bound to the Principal that was authenticated when it
   was queued, and that binding is written once and never rewritten. Replay
   refuses when that binding differs from the Principal the surface was
   **rendered for** — it quarantines, and never rebinds, deletes, or sends.

   **State the check precisely, because the two are not the same thing.** The
   comparison is against `principalId`, a prop supplied by a server render. It is
   *not* a comparison against the session that will actually authenticate the
   replay: `httpCaptureTransport` posts with `credentials: "same-origin"`, so the
   request carries whichever cookie the browser holds at that moment. A rendered
   prop and a live cookie can in principle disagree — an open tab whose session
   changed underneath it is the obvious way — and this check would not catch that
   case. Saying "refuses when the signed-in Principal differs" would overstate
   it, so this document does not say that.

   What makes the gap unreachable at this head is the tier below, not this check:
   no configuration serves a durable cross-principal write. Under
   `MYPA_GATEWAY_AUTH_MODE=local_operator` exactly one Principal is admissible
   (D-15); with the mode unset or `entra` the backend refuses. The one reachable
   variant answers `shape: "synthetic"`, which receipt verification rejects
   outright — the ciphertext is retained rather than deleted — and the synthetic
   provider is refused when `NODE_ENV=production`.

   **This becomes release-blocking the moment two identities can hold sessions
   while the backend serves.** At that point the comparison must be made against
   the authenticating session rather than a rendered prop.

   The service worker caches no `/api` response, so nothing principal-bound is
   ever served out of a shared cache.
