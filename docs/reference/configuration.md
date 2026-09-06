# Configuration reference

Configuration authority is executable code, not this table. Python settings live in `src/my_pa/bootstrap/settings.py`; checked non-secret examples live in `.env.example`. Browser/BFF variables live in `web/.env.example`.

## Python configuration model

Rules:

- prefix: `MY_PA_`;
- unknown variables fail closed;
- invalid values/combinations fail startup;
- `MY_PA_DATABASE_URL` is required and has no default;
- credential-bearing values are supplied out of band and must not be logged/committed;
- feature/remote/write surfaces are explicit rather than inferred.

Representative groups:

| Concern | Canonical source |
|---|---|
| database target | `MY_PA_DATABASE_URL` / `bootstrap/settings.py` |
| environment/logging | `MY_PA_ENVIRONMENT`, `MY_PA_LOG_LEVEL` |
| Python HTTP identity | `MY_PA_AUTH_MODE` plus required Entra fields when selected |
| gateway binding mode | validated settings; loopback is the normal local boundary |
| managed-document storage | `MY_PA_MANAGED_DOCUMENT_ROOT` |
| remote capture/MCP | explicit remote feature/security settings |
| Relationship Intelligence / Relationship Memory | explicit plane/write feature settings |
| GoodNotes/model rollout | explicit GoodNotes settings and governed runbooks |
| request limits | validated settings exposed through effective capability limits |

Do not copy this list to decide whether a setting exists; inspect `Settings` and `.env.example`.

## Web configuration

The web tier has a separate configuration model. Important categories include:

- browser auth mode (`synthetic` development or passkey mode);
- BFF↔Python session-service secret;
- WebAuthn ceremony secret;
- Python gateway URL;
- Python gateway auth mode;
- explicit synthetic data-provider switch.

Use `web/.env.example` and `web/README.md` as the executable-tree references.

## Secrets

Tracked examples must contain inert placeholders only. Never commit:

- passwords/tokens/private keys;
- connection strings containing credentials;
- tenant/customer identifiers that are not approved for publication;
- personal filesystem/NAS roots;
- source content or personal-data fixtures.

## Changing configuration

A configuration change must document:

1. name and owning process;
2. type/allowed values;
3. default or required status;
4. secret/sensitive classification;
5. fail-closed behavior;
6. compatibility/upgrade impact;
7. tests;
8. operational documentation impact.

Prefer one source of validation. Do not validate one interpretation in a wrapper and let the runtime parse another.
