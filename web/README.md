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

The Python contract contains one hundred and twenty-four capability names. The System route reads
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
| `/system`, `GET /api/system` | `capabilities.get` | Reports the runtime manifest, readiness, and worker planes; connected-source enumeration remains unknown because no v1 capability provides it |
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
does not reinterpret that as a running worker. If the System route cannot reach
the gateway, it renders the refusal rather than an empty healthy state.

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
