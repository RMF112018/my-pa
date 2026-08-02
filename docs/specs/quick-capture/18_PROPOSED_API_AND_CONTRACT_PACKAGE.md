# Proposed API and Contract Package

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Contract status

Proposed product contracts only. They do not authorize implementation or change the repository’s current `v1` capability set.

All requests use:

- authenticated principal from server/session, not caller assertion;
- `Idempotency-Key` for commands;
- `X-Request-ID`/correlation;
- JSON UTF-8;
- RFC 3339 timestamps;
- strict unknown-field rejection for command bodies;
- common disclosure envelope.

## 1. Create capture

`POST /v1/captures`

Headers:

```http
Idempotency-Key: 5b9...
X-Request-ID: req_opaque
```

Request:

```json
{
  "kind": "conversation_log",
  "text": "Spoke with Jordan by phone. We agreed I will send the revised buyout by Friday. Jordan will confirm the steel lead time.",
  "client": {
    "capture_id": "cap_opaque",
    "capture_version_id": "capv_opaque",
    "created_at": "2026-08-01T16:05:00-04:00",
    "timezone": "America/New_York",
    "device_installation_id": "dev_opaque",
    "origin": "pwa_shortcut"
  },
  "launch_context": {
    "type": "project",
    "id": "prj_opaque",
    "expected_version": "7"
  },
  "classification": "private_local",
  "processing_policy": "local_only"
}
```

Response `201 Created` or `200 OK` on idempotent replay:

```json
{
  "contract_version": "v1",
  "request_id": "req_opaque",
  "correlation_id": "corr_opaque",
  "result": {
    "capture_id": "cap_opaque",
    "capture_version_id": "capv_opaque",
    "kind": "conversation_log",
    "status": "saved",
    "processing_status": "pending",
    "conversation_id": "conv_opaque",
    "receipt_id": "rcpt_opaque",
    "server_received_at": "2026-08-01T20:05:01Z"
  },
  "disclosure": {
    "authority": "source_authoritative_user_evidence",
    "classification": "private_local",
    "cloud_eligible": false,
    "context_links": [
      {"type": "project", "id": "prj_opaque", "state": "deterministic"}
    ],
    "limitations": []
  },
  "error": null
}
```

## 2. Create new capture version

`POST /v1/captures/{capture_id}/versions`

Request:

```json
{
  "expected_current_version_id": "capv_opaque",
  "text": "Corrected source text...",
  "edit_reason": "clarification",
  "client_created_at": "2026-08-01T16:12:00-04:00"
}
```

Responses:

- `201` new immutable version;
- `409 version_conflict` with current version identity;
- `422 invalid_text`;
- `403 policy_denied`.

## 3. Fetch capture

`GET /v1/captures/{capture_id}?include=versions,links,proposals,receipts`

Response distinguishes source text from derived/proposed/accepted records. Sensitive includes are policy-filtered.

## 4. List/search captures

`GET /v1/captures?kind=conversation_log&project_id=prj_opaque&from=...&cursor=...`

`GET /v1/captures/search?q=steel+lead+time&mode=exact`

Response includes:

- cursor;
- scope;
- coverage;
- result type;
- authority label;
- excerpt;
- source version;
- limitations;
- unavailable evidence.

## 5. Processing status

`GET /v1/captures/{capture_id}/processing`

```json
{
  "result": {
    "aggregate_state": "needs_review",
    "current_version_id": "capv_opaque",
    "stages": [
      {"stage": "index_original", "state": "complete"},
      {"stage": "extract_work_objects", "state": "complete"},
      {"stage": "resolve_entities", "state": "partial", "unresolved_count": 1},
      {"stage": "route_review", "state": "complete"}
    ],
    "review_case_ids": ["rvw_opaque"]
  }
}
```

## 6. Retry processing

`POST /v1/captures/{capture_id}/processing/retry`

Request:

```json
{
  "capture_version_id": "capv_opaque",
  "stages": ["resolve_entities"],
  "reason": "user_requested"
}
```

Server rejects:

- nonretryable terminal error;
- superseded version unless explicit historical reprocess allowed;
- prohibited processing route;
- exhausted policy budget.

## 7. Link context

`POST /v1/captures/{capture_id}/links`

```json
{
  "target_type": "relationship",
  "target_id": "person_opaque",
  "link_role": "about",
  "expected_target_version": "12"
}
```

User-confirmed link creates an auditable canonical link. Model proposals use internal proposal workflow, not this user command.

Unlink:

`DELETE /v1/captures/{capture_id}/links/{link_id}?expected_version=...`

Unlinking does not erase historical evidence.

## 8. Review proposal

`POST /v1/review-cases/{review_case_id}/dispositions`

```json
{
  "expected_review_version": "3",
  "disposition": "correct_and_accept",
  "corrections": {
    "obligor_entity_id": "person_user",
    "counterparty_entity_id": "person_jordan",
    "due_at": "2026-08-07"
  }
}
```

Response includes:

- resulting canonical object/version;
- source/proposal links;
- receipt;
- downstream impact;
- remaining proposals.

## 9. Offline synchronization

`POST /v1/captures/sync`

Request may contain a bounded batch:

```json
{
  "client_schema_version": "1",
  "items": [
    {
      "capture_id": "cap_opaque",
      "capture_version_id": "capv_opaque",
      "idempotency_key": "key",
      "request_sha256": "hash",
      "kind": "quick_note",
      "text": "Observed water at the north stair.",
      "client_created_at": "2026-08-01T15:55:00-04:00",
      "timezone": "America/New_York",
      "classification": "private_local",
      "processing_policy": "local_only"
    }
  ]
}
```

Per-item response:

- `created`;
- `replayed`;
- `authentication_required`;
- `policy_denied`;
- `idempotency_conflict`;
- `invalid`;
- `temporary_unavailable`.

Partial batch results are explicit.

## 10. Create/resolve Conversation

For an explicit Conversation Log, the create-capture response may return a skeletal Conversation ID.

Manual creation from Quick Note proposal:

`POST /v1/captures/{capture_id}/conversation`

```json
{
  "capture_version_id": "capv_opaque",
  "channel": "unknown",
  "occurred_at": null,
  "participant_ids": [],
  "expected_capture_version": "capv_opaque"
}
```

This is a user command, not model promotion.

Conversation correction:

`POST /v1/conversations/{conversation_id}/versions` or repository-consistent update command with expected version.

## 11. Retrieve evidence span

`GET /v1/captures/{capture_id}/versions/{version_id}/spans/{span_id}`

```json
{
  "result": {
    "span_id": "span_opaque",
    "offset_basis": "unicode_code_point_v1",
    "start_offset": 28,
    "end_offset": 82,
    "quoted_text": "We agreed I will send the revised buyout by Friday",
    "quoted_text_sha256": "…",
    "line_start": 1,
    "column_start": 29,
    "line_end": 1,
    "column_end": 83,
    "roles": ["direct"]
  }
}
```

## Error taxonomy

| Code | HTTP | Meaning |
|---|---:|---|
| `invalid_request` | 400 | Unknown/invalid structure |
| `authentication_required` | 401 | Current principal unavailable |
| `policy_denied` | 403 | Operation or processing route prohibited |
| `not_found` | 404 | Opaque subject not visible/found |
| `version_conflict` | 409 | Expected version is stale |
| `idempotency_conflict` | 409 | Key reused with different request |
| `payload_too_large` | 413 | Text/batch exceeds bound |
| `unsupported_content` | 415 | Deferred attachment/type |
| `validation_failed` | 422 | Semantic validation |
| `rate_limited` | 429 | Bounded abuse/resource control |
| `temporary_unavailable` | 503 | Retryable service issue |
| `processing_failed` | 500/200 status endpoint | Saved source exists; downstream failed |
| `local_persistence_failed` | client-only | No false save claim |

Errors contain correlation, safe retry guidance, and no source text.

## Authorization

Suggested purposes:

- `capture_create`
- `capture_edit`
- `capture_read`
- `capture_search`
- `capture_process`
- `capture_review`
- `capture_archive`
- `capture_sync`

Caller-provided purpose is policy input, not self-granted authority. CLI/MCP do not bypass the same application policy.

## Versioning

The contracts may reuse the repository’s current common `v1` envelope only after explicit design review. New capability names and schemas require repository integration, generated client compatibility tests, and an operator-authorized scope change.
