# Migration Logging and Audit Standard

**Criterion:** `P00-AC-07`  
**Default:** content-safe, least-privilege, fail-closed.

## Prohibited log and audit values

Do not record:

- message bodies, subject lines, attachments, or quoted correspondence;
- document contents, excerpts, OCR text, filenames that expose personal content, or raw file payloads;
- personal contact details, addresses, phone numbers, birthdays, relationship notes, or free-text profiles;
- credentials, passwords, private keys, access or refresh tokens, cookies, authorization headers, secrets, or connection strings;
- raw JSON, raw connector responses, raw source payloads, database rows, retained-snapshot content, or source-record dumps;
- SQL text, sensitive query text, model prompts containing source content, or exception strings that may embed payloads;
- absolute operator host paths or identifiers that reveal sensitive local structure.

Redaction after logging is not an acceptable primary control. Do not collect the value.

## Permitted fields

Audit events may contain only what is operationally necessary:

- stable non-content identifiers and correlation IDs;
- event type, policy decision, bounded status code, and allow/deny outcome;
- coarse timestamps and bounded duration or count metrics;
- repository, goal, phase, work-item, authorization, evidence, decision, commit, PR, and check identifiers;
- redacted provider or source category metadata;
- deterministic validation result names;
- bounded error categories written from an allowlist.

Counts must be bounded and must not reveal content through cardinality or free-text labels.

## Event contract

Every retained event must define:

```text
event_id
event_type
occurred_at
actor_class
resource_class
resource_id_or_redacted_reference
decision
reason_code
correlation_id
evidence_reference
```

Free-text `message`, `details`, `payload`, `query`, and `content` fields are prohibited in retained audit contracts.

## Failure handling

- Use allowlisted reason codes instead of raw exception messages.
- Fail closed when a value cannot be classified as safe.
- Keep test fixtures synthetic and content-minimal.
- Security-relevant denials should be auditable without retaining the rejected payload.
- Evidence publications must apply the same exclusions.

## Validation

`validate_phase00_governance.py` asserts the required exclusions and permitted-field contract are present. Runtime implementations must add contract tests before emitting any event.
