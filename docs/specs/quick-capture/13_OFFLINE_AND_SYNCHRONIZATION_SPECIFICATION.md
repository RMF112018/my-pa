# Offline and Synchronization Specification

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Recommendation

Offline Quick Capture should be included in the MVP because the product promise is “capture at the moment of memory.” A capture surface that fails in poor connectivity undermines the core feature.

The offline model is **append-only until server acknowledgment**.

## Local identity

The client generates:

- `capture_id`;
- `capture_version_id`;
- `idempotency_key`;
- `client_created_at`;
- `device_installation_id`;
- `content_sha256`.

Use UUIDv7/UUID4 or another repository-approved opaque ID strategy. IDs must not encode user, device, path, or content.

## Local record

```json
{
  "capture_id": "cap_opaque",
  "capture_version_id": "capv_opaque",
  "idempotency_key": "random-bounded-key",
  "kind": "conversation_log",
  "ciphertext": "...",
  "content_sha256": "...",
  "client_created_at": "2026-08-01T20:15:00-04:00",
  "timezone": "America/New_York",
  "launch_context": {"type": "project", "id": "prj_opaque"},
  "classification": "private_local",
  "processing_policy": "local_only",
  "sync_state": "pending",
  "retry_count": 0
}
```

## Local storage

PWA:

- IndexedDB transaction for payload and queue metadata;
- application-layer encryption for capture text;
- key material must not be stored as plaintext beside ciphertext;
- authentication/session data remains separate;
- no note text in Cache API URLs, localStorage, logs, or analytics.

A browser origin compromise can undermine Web Crypto and local keys. The specification must not claim equivalence to Secure Enclave, Keychain, TPM, or DPAPI. Native wrappers may improve key protection later.

## Save confirmation

The UI may say **Saved on this device** only after the IndexedDB transaction commits successfully.

It must not say server-saved or fully synchronized until the server receipt is verified.

## Synchronization triggers

Authoritative triggers:

- app launch/resume;
- foreground timer while pending;
- `online` event followed by verified request;
- explicit Retry Sync;
- navigation to pending item.

Opportunistic enhancement:

- Background Sync where supported.

Do not rely on Periodic Background Sync or guaranteed service-worker execution. Mobile operating systems may suspend or evict web storage/processes.

## Server sync contract

Client submits:

- stable IDs;
- exact original text after decryption;
- source hash;
- idempotency key;
- client time/timezone;
- mode and launch context;
- classification/processing policy;
- client schema version.

Server:

1. authenticates current principal;
2. validates stale-session policy;
3. looks up idempotency key;
4. compares request hash;
5. returns prior receipt for identical replay;
6. rejects reuse with changed payload;
7. creates capture/version/receipt/job atomically otherwise.

## Duplicate prevention

Layers:

- client stable IDs;
- unique principal/idempotency key;
- unique capture/version identity;
- exact request hash;
- server receipt replay;
- optional duplicate-content advisory only after persistence.

Never deduplicate solely by identical text. The user may intentionally record the same statement twice at different times.

## Stale authentication

Policy options reserved to operator:

- permit local encrypted capture while signed out, then require reauthentication to sync;
- deny local capture on shared/untrusted devices;
- set maximum offline age before reauthentication;
- require device binding for restricted content.

Default recommendation: permit encrypted local save on a previously authenticated personal device, but require reauthentication before server sync after session expiry.

## Conflicts

Examples:

- same capture ID with different text;
- same idempotency key with different hash;
- source version edited on another device;
- context target superseded;
- classification widened;
- server account/principal changed.

Behavior:

- preserve both local and server evidence;
- enter conflict state;
- never last-write-wins source text;
- present versions and explicit user resolution;
- context failures do not block source capture sync.

## Retry

- bounded exponential backoff;
- retry network/5xx/temporary-unavailable;
- stop on authentication, policy, schema, or idempotency conflict until user/system action;
- retain last safe error class, not server body content;
- allow manual retry.

## Local deletion

- A pending item can be deleted only with explicit confirmation that it has not synced.
- After sync, local ciphertext may be removed when verified server receipt is stored.
- Local cache clearing does not delete the server record.
- “Delete everywhere” is a separate server-side retention action, not an offline-queue operation.

## Device loss and privacy

- encrypted local storage reduces but does not eliminate risk;
- short auto-lock/session timeout for restricted devices;
- generic app title/notification;
- remote device revocation affects future sync/access but cannot prove local ciphertext destruction;
- document device-loss limitations in operator guidance.

## Attachment limits

Attachments are deferred from the typed MVP. If later introduced:

- preserve text independently;
- cap size/type/count;
- store encrypted local blobs;
- avoid Background Sync for large files;
- require resumable upload and content hash;
- never let failed attachment upload discard the text capture.

## Offline acceptance criteria

- airplane-mode save survives reload/crash;
- pending item syncs exactly once after connectivity;
- replay is idempotent;
- account switch cannot leak or attach capture to wrong principal;
- authentication expiry preserves source locally but blocks unauthorized sync;
- IndexedDB failure never produces false success;
- local queue eviction/storage pressure is detectable where the platform exposes it;
- no plaintext note appears in logs/localStorage/cache URLs.
