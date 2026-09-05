# Frontend, BFF and PWA architecture

`web/` is the Next.js App Router PWA for MY-PA. It is a browser-facing product surface and backend-for-frontend over the Python gateway, not a second source of domain truth.

## Runtime boundary

Normal browser flow:

```text
browser
  -> Next.js page/server route
  -> server-side session resolution
  -> BFF API route
  -> loopback/container Python gateway
  -> canonical application capability
```

The browser does not supply a Principal or a gateway bearer. BFF routes derive identity from the opaque server session and preserve Python refusal/disclosure semantics.

## Current technology

The executable package definition is `web/package.json`. Current CI uses Node.js 20. The package uses Next.js App Router, React, TypeScript, Vitest, Playwright, Storybook, Radix primitives, Tailwind and accessibility tooling.

Do not duplicate dependency versions in feature plans; read `web/package.json` and the lockfile.

## Routing and BFF patterns

Use existing routes under:

- `web/src/app/(app)/` for authenticated product pages;
- `web/src/app/api/` for server-side BFF routes.

A BFF route should:

1. resolve the current server session;
2. validate browser-origin/mutation admission where applicable;
3. map the request to one canonical Python capability;
4. decode the canonical gateway response;
5. preserve typed conflicts/refusals rather than converting them into empty success;
6. never accept caller-supplied Principal identity.

`web/README.md` is the detailed current route-to-capability inventory.

## Contract boundary

Frontend contract handling lives under:

- `web/src/contracts/`
- `web/src/lib/api/decode/`

Python remains the capability/schema authority. Decoder parity is contract-tested across Python and TypeScript. When a backend response changes, update the decoder/fixtures/tests as one change rather than adding permissive `any` handling.

## Authentication/session

Web auth modes are:

- `synthetic` — development only; refused in production;
- `passkey` — WebAuthn/passkey flow with opaque server-side SID session.

Browser Entra/MSAL sign-in is retired. The Python gateway separately supports `local_operator` or `entra`; the BFF must not fabricate or substitute a credential when gateway mode requires one it cannot forward.

Read [`authentication-security.md`](authentication-security.md).

## State and component design

Prefer server-owned/canonical state. Local UI state should represent presentation or an explicit offline draft/queue, not shadow domain truth.

Use existing component/layout/design-system patterns before adding a new primitive. Storybook and accessibility tests are part of the supported component workflow.

## PWA/offline behavior

Offline behavior is intentionally bounded rather than general:

- Quick Capture may retain encrypted notes in IndexedDB while the gateway is unavailable.
- The queue is bounded by entry count and bytes and does not evict old entries to admit new ones.
- Replay is foreground-only.
- Replay resolves the current authenticated session before plaintext access.
- Deletion after replay requires a backend persisted receipt matching idempotency/content/session ownership conditions.
- Cross-Principal queued notes are retained without decryption/transport until the owning Principal acts.

Do not describe this as general offline mutation support or background synchronization.

## Responsive/accessibility expectations

Frontend CI includes accessibility and responsive browser validation. New product surfaces must:

- use semantic controls/labels;
- preserve keyboard focus and dialog/menu behavior;
- work at supported desktop/mobile viewports;
- avoid layout-only assumptions that break narrow screens;
- add targeted accessibility and E2E coverage when interaction risk warrants it.

## Product/UX intent

Accepted visual and UX intent is Drive-owned. Start from the [current Drive product-definition index](https://docs.google.com/document/d/1PAT3Vc6Y2POeqy5d9yHnnZLD5OWppsEw6Mwpv9UesNs/edit), especially the Frontend/UX lane. Reconcile that intent to current repository contracts; do not copy old implementation packages as technical truth.

## Validation

From `web/`:

```sh
npm test
npm run lint
npm run typecheck
npm run build
```

Use `npm run e2e` for the browser stack when the feature affects critical browser behavior, persistence/BFF integration, PWA/offline, accessibility or responsive behavior.

See [`../development/testing-and-review.md`](../development/testing-and-review.md).
