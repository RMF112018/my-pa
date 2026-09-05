# Quick Capture

Quick Capture creates product-owned user-authored records inside MY-PA. ADR-003 makes these a third authority class: neither a mutation of an original source nor a managed-document write.

## Canonical record flow

A capture is admitted under a server-derived Principal with idempotency and durable receipt semantics. Versioned capture text can then move through deterministic processing/proposal/review/search flows.

Core areas include:

- `src/my_pa/domain/capture/`
- `src/my_pa/application/`
- `src/my_pa/infrastructure/persistence/`
- capture worker plane in `apps/worker.py`
- BFF `/api/capture` route and offline queue in `web/`

## Authority and provenance

A raw user capture is authoritative as a product-owned submission. Derived proposals/assertions remain distinguishable from the original text and carry evidence/provenance/review state.

Do not silently rewrite the user's captured evidence when derived processing changes.

## Idempotency

Capture admission/replay is designed so retries do not create unrelated duplicates. New capture entry points must use the same canonical admission/idempotency contract rather than invent a transport-local key.

## Worker processing

The capture worker processes stored text through bounded deterministic stages. It does not need a live source or model call for the baseline processing path.

A failure/retry must preserve durable state rather than leave an ambiguous “maybe processed” condition.

## Offline web capture

The PWA may queue encrypted capture notes in IndexedDB while the gateway is unavailable. Current guarantees are deliberately limited:

- bounded entry/byte capacity;
- no eviction to admit a new entry;
- foreground replay only;
- session/Principal ownership rechecked before plaintext access/transport;
- deletion only after a matching persisted backend receipt;
- cross-Principal queued data is retained without decryption/transport.

Do not generalize this mechanism into offline support for arbitrary domain writes without a separate design.

## Product intent

Accepted Quick Capture UX/product intent is Drive-owned. Current Drive lane `1xGy3k7HYPswSJV1x60Q9WBtvwbUk3nUN` indexes the iOS home-screen and remote Quick Capture packages.

Repository code governs current technical behavior.

## Extension checklist

For a new capture channel:

1. identify how Principal is server-derived;
2. use canonical idempotency/receipt semantics;
3. preserve original evidence/provenance;
4. classify remote/auth/disclosure boundary;
5. reuse application admission rather than writing directly;
6. define offline/retry ownership if applicable;
7. add security/idempotency/contract tests;
8. update product intent and current technical docs separately.
