# MossAIc web application

`web/` is the Next.js App Router PWA for the current local candidate. It is a
browser-facing shell and backend-for-frontend (BFF) over the Python capability
gateway; it is not a second source of domain truth.

## Current implementation

The normal application path is backend-served. Server routes resolve a
Principal from the opaque SID cookie via the Python session-service, call the
loopback Python gateway, and pass through the gateway's disclosure and refusal
semantics. The browser cannot submit a Principal or a gateway bearer.

An explicitly enabled synthetic provider remains available for development and
is refused when `NODE_ENV=production`. It does not silently replace an
unconfigured or unavailable backend.

The Python contract contains one hundred and twenty-five capability names. The System route reads
the live `capabilities.get` manifest, including each capability's runtime
availability, instead of restating an availability count in this tier. Six of
those names are the managed-document lifecycle (`documents.create`,
`documents.revise`, `documents.read`, `documents.list`, `documents.archive`, and
`documents.restore`). They are implemented in the Python application and become
available only when the gateway composition has a managed root; this web package
does not currently expose a managed-document screen or API route.

## Routes and capability mapping

All application pages require a verified session. `/sign-in` is public.

| UI or BFF route | Backend capability | Current behavior |
|---|---|---|
| `/today`, `GET /api/pulse` | `continuity.pulse` | Ranked accepted commitments, tasks, decisions, and current obligations |
| `/situations`, `GET /api/situations` | `continuity.situations` | Principal-scoped Situation list and relationship events |
| `GET /api/projects` | `continuity.projects` | Principal-scoped Project list used by the Situation surface |
| `/relationships/:personId`, `GET /api/relationships/:personId/timeline` | `continuity.situations` | Filters the accepted relationship events returned by the continuity read model for that person |
| `/library`, `GET /api/library` | `knowledge.read`, `knowledge.search`, `capture.search`, or `capture.list` | Chooses one capability from the request shape; no synthetic Library fixture is invented |
| `POST /api/reveal` | `knowledge.reveal` | Preserves `evidence`, `no_evidence`, and `unavailable` as distinct answers |
| `/review`, `GET /api/review` | `review.list` | Lists the acting Principal's review cases |
| `/intelligence`, `GET /api/intelligence` | `reports.list`, `reports.search` | Lists or searches Principal-scoped Intelligence artifacts; `structured_content` is persisted opaque JSON, not scraped from markdown |
| `GET /api/intelligence/:reportId` | `reports.read` | Reads one same-Principal Intelligence artifact |
| `GET /api/intelligence/latest` | `reports.latest` | Reads the current-head artifact for a cycle run |
| `GET /api/intelligence/readiness` | `reports.resolve_set` | Returns aggregate and per-member resolver states; members are not flattened to a boolean |
| `/people`, `GET /api/people` | `entities.search`, `entities.resolve` | Search or resolve Principal-scoped entities; empty URL is refused rather than listing a directory |
| `GET /api/people/:entityId` | `entities.get` | Reads one same-Principal entity |
| `GET /api/people/:entityId/profile` | `entities.profile` | Assembles the record-family profile; this is not merge and not a directory |
| `GET /api/people/:entityId/context` | `entities.context` | Returns the frozen context card without widening it |
| `GET /api/people/graph` | `entities.graph` | Seeded 1-hop or 2-hop neighborhood; missing seed is refused rather than listing a directory |
| `GET /api/people/:entityId/relationships` | `entities.relationships` | Lists same-Principal relationships |
| `GET /api/people/:entityId/names` | `entities.names.list` | Lists names for one same-Principal entity |
| `GET /api/people/:entityId/addresses` | `entities.addresses.list` | Lists addresses for one same-Principal entity |
| `GET /api/people/:entityId/communication` | `entities.communication.list` | Lists communication methods for one same-Principal entity |
| `GET /api/people/:entityId/participations` | `entities.participations.list` | Lists participations for one same-Principal entity |
| `GET /api/people/:entityId/identifiers` | `entities.identifiers.list` | Lists identifiers for one same-Principal entity |
| `GET /api/people/:entityId/aliases` | `entities.aliases.list` | Lists aliases for one same-Principal entity |
| `GET /api/people/:entityId/assignments` | `entities.assignments.list` | Lists assignments for one same-Principal entity |
| `GET /api/people/:entityId/observations`, `GET /api/people/observations` | `entities.observations.list` | Lists observations; `observed_value` is refused |
| `GET /api/people/unresolved` | `entities.unresolved_mentions` | Lists unresolved mentions; `observed_value` is refused |
| `GET /api/people/:entityId/identity-history` | `entities.identity_history` | Reads Principal-scoped identity history |
| `POST /api/review/:id/decide` | `review.decide` | Applies an optimistic-concurrency review decision |
| `POST /api/capture` | `capture.create` | Persists a Quick Capture with backend-owned idempotency and a verifiable receipt |
| `GET /api/tasks` | `tasks.list`, `tasks.search` | Lists or searches server-owned Tasks with Work-view filters and opaque cursors |
| `POST /api/tasks` | `tasks.create` | Creates a Task with server-validated origin evidence and idempotency |
| `GET /api/tasks/:taskId` | `tasks.read` | Reads one same-Principal Task and its safe evidence metadata |
| `PATCH /api/tasks/:taskId` | `tasks.update` | Applies one expected-version atomic Task patch |
| `GET /api/tasks/:taskId/history` | `tasks.history` | Reads the Task's append-only mutation history |
| `POST /api/tasks/:taskId/transition` | `tasks.transition` | Applies one lifecycle transition with closure evidence when terminal |
| `GET /api/commitments` | `commitments.list`, `commitments.search` | Lists or searches server-owned Commitments with opaque cursors |
| `POST /api/commitments` | `commitments.create` | Creates a Commitment with server-validated origin evidence and idempotency |
| `GET /api/commitments/:commitmentId` | `commitments.read` | Reads one same-Principal Commitment |
| `PATCH /api/commitments/:commitmentId` | `commitments.update` | Applies one expected-version bounded Commitment update |
| `GET /api/commitments/:commitmentId/history` | `commitments.history` | Reads the Commitment's append-only history |
| `POST /api/commitments/:commitmentId/close` | `commitments.close` | Closes a Commitment explicitly with validated closure evidence |
| `/system`, `GET /api/system` | `capabilities.get`, `reports.list`, `reports.resolve_set` | Reports the runtime manifest, readiness, and worker planes; Morning Intelligence is resolver aggregate and members (READY is not system health); PWA fields are `PWA_FIELDS_PENDING_WP26`; connected sources remain unknown |
| `POST /api/session` | none | Synthetic development sign-in only; refused in passkey mode and in production |
| `POST /api/webauthn` | none | Passkey ceremony BFF; Python issues the opaque SID cookie after authentication or recovery |

The relationship timeline is therefore implemented, but it is not a separate
public capability. It is a projection of `relationship_events` already returned
by `continuity.situations`. Microsoft Graph remains off by default and is not an
active personal-data source. Browser Entra/MSAL sign-in is retired.

## Worker-plane reporting

`GET /api/system` returns the gateway's `worker_planes` data as
`backend.workerPlanes`. The two current planes are `capture` and `enrollment`.
Each reports its state, backlog, dead-letter count, and last heartbeat when
known.

The gateway degrades readiness when worker health is unavailable, when queued
work has an absent or stale worker, or when a plane has dead-lettered work. An
absent worker with no backlog is reported as `idle_or_not_required`; the web tier
does not reinterpret that as a running worker. Worker `last_heartbeat_at` is
rendered or explicitly unknown — never implied healthy. Morning Intelligence on
this route is `reports.resolve_set` for `morning_brief_inputs` after discovering
`cycle_run_id` from `reports.list`; READY is not mapped to a healthy system. If
the System route cannot reach the gateway, it renders the refusal rather than an
empty healthy state.

## Authentication and gateway identity

`MYPA_AUTH_MODE` is required and has exactly two web values:

- `synthetic` exposes fixed development principals. It is refused in production.
- `passkey` is production web authentication. Sessions are an opaque SID issued
  by Python after WebAuthn or recovery; `POST /api/session` does not mint a
  synthetic identity.

Browser Entra/MSAL and browser local-operator sign-in are retired. There is no
`/auth/sign-in` route and no MSAL package on this tier.

`MYPA_GATEWAY_AUTH_MODE` separately describes the Python gateway:

- `local_operator` sends no credential. The gateway serves one configured
  process Principal, and the web tier admits only the matching synthetic
  Principal so browser sessions cannot imply backend partitioning that does not
  exist.
- `entra` requires a bearer token. Browser Entra/MSAL is retired, so this BFF
  has no forwardable Entra credential and refuses (`no_forwardable_credential`)
  rather than sending the session cookie as a bearer or fabricating a token.

## Configuration

Copy `.env.example` only as a list of non-secret variable names. Supply real
values out of band and never commit them.

| Variable | Required use |
|---|---|
| `MYPA_SESSION_SERVICE_SECRET` | At least 32 characters; BFF→Python session-service HMAC; distinct from the WebAuthn BFF secret |
| `MYPA_WEBAUTHN_BFF_SECRET` | At least 32 characters; WebAuthn BFF ceremony HMAC; distinct from the session-service secret |
| `MYPA_AUTH_MODE` | `synthetic` or `passkey`; no default |
| `MYPA_GATEWAY_URL` | Absolute HTTP(S) URL for the Python gateway; no default |
| `MYPA_GATEWAY_AUTH_MODE` | `local_operator` or `entra`; must match the Python gateway plane |
| `MYPA_DATA_PROVIDER` | Optional explicit `synthetic` fixture switch; unset means off |
| `MYPA_ENTRA_HOME_TENANT_ID` | Optional home tenant when configured; not a browser MSAL client id |

A minimal synthetic development configuration is:

```sh
export MYPA_SESSION_SERVICE_SECRET='replace-with-a-local-random-value-of-at-least-32-characters'
export MYPA_WEBAUTHN_BFF_SECRET='replace-with-a-distinct-local-random-value-of-at-least-32-characters'
export MYPA_AUTH_MODE=synthetic
export MYPA_GATEWAY_URL=http://127.0.0.1:8000
export MYPA_GATEWAY_AUTH_MODE=local_operator
export MYPA_DATA_PROVIDER=synthetic
npm run dev
```

The placeholders above are documentation, not acceptable shared or deployed
secrets. Generate local values out of band.

## Offline Quick Capture

Quick Capture can retain encrypted notes in IndexedDB while the gateway is
unavailable. The queue fails closed at 50 retained entries or 1,000,000 bytes
and never evicts an older note to admit a new one. Replay is foreground-only: it
runs while the application is open, not as a background-sync guarantee.

Replay resolves the current authenticated session immediately before plaintext
access. The write carries an opaque binding to that exact session, so the BFF
refuses a cookie transition between the check and Capture admission. An entry is
deleted automatically only after a backend `persisted` receipt matches its
idempotency key, content digest, and server-derived Principal. A note owned by
another signed-in Principal is retained without decryption or transport.
The owning Principal can explicitly release it for retry or delete the local copy;
those controls never authorize one Principal to act on another's entry.

## Validation

From `web/`:

```sh
npm test
npm run lint
npm run typecheck
npm run build
```

The browser suite uses a disposable PostgreSQL database, a loopback Python
gateway in `local_operator` mode, and Next.js servers for both healthy and
unreachable-gateway cases. It runs desktop Chrome and a Pixel 7 viewport:

```sh
npm run e2e
```

The suite requires the repository Python environment and the local PostgreSQL
authentication/configuration described by `e2e/stack.sh`. It does not use a live
Entra tenant or live personal data.

## Boundaries

This package does not authorize deployment, production activation, live
personal-data connector access, source-system mutation, credential creation or
rotation, or an amendment of repository policy. Synthetic provider behavior is
development evidence, not production readiness. Current campaign decisions and
exact-head evidence belong in the remediation/PR/final-state records, not in
this package README.
