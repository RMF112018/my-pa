# Troubleshooting

Troubleshoot from identity and boundaries outward. Do not compensate for an unknown state by enabling more privileges or pointing at a more important database.

## 1. Establish exact state

Record:

- repository/commit;
- process or BFF route;
- configured environment mode;
- intended database identity;
- feature plane involved;
- whether the problem is local development, CI, NAS/runtime, or a remote client.

## 2. Configuration refusal

Python settings reject unknown `MY_PA_` names and invalid combinations. Read `src/my_pa/bootstrap/settings.py` and `.env.example`; do not assume an old runbook's defaults.

Common checks:

```sh
echo "${MY_PA_DATABASE_URL:?MY_PA_DATABASE_URL is unset}"
.venv/bin/alembic current -v
```

Never print credential-bearing environment values into retained logs.

## 3. Capability is `unsupported` / missing

Check the live `capabilities.get` result and composition requirements. A capability implemented in code may still be withheld because its feature plane, write plane, storage root, identity mode, or remote grant is not configured.

Do not add a transport-only exception to expose it. Follow [API/BFF contracts](../reference/api-bff-contracts.md) and [MCP capabilities](../reference/mcp-capabilities.md).

## 4. HTTP/MCP/CLI disagree

That is a contract defect. All three Python transports normalize through the shared application path and should preserve the same authorization/disclosure behavior. Reproduce with synthetic data and inspect:

- `src/my_pa/adapters/normalization.py`;
- transport contract tests;
- application authorization/disclosure;
- the composed capability manifest.

## 5. Web/BFF refusal

The browser must not supply a Principal or gateway bearer. Server routes resolve identity/session and call the Python gateway. If the BFF has no forwardable credential for the configured gateway mode, refusal is safer than fabrication.

Read `web/README.md`, the affected route, and its decoder/test.

## 6. Database/migration issue

Do not downgrade or reset a canonical database while diagnosing. Use a disposable database, inspect `alembic heads`, and run the narrow migration/schema test first. See [Database migrations](../reference/database-migrations.md).

## 7. Worker backlog

Determine the plane and inspect backlog, lease/heartbeat, dead-letter/terminal state, and last failure. Do not launch a different worker plane as a substitute.

## 8. NAS/runtime issue

Use `.codex/skills/my-pa-nas-build-deploy/SKILL.md` and the exact `ops/runbooks/` procedure. Never infer a target host, storage root, firewall mutation, or production action.

## Escalation evidence

A useful issue/review handoff contains exact identity, reproduction, safe failure evidence, affected contract, tests already run, and what remains unknown. It does not contain source payloads, credentials, or speculative fixes presented as facts.
