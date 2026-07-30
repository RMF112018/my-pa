# Security Policy

## Current status

This repository is a scaffold and has no supported runtime release.

## Security boundaries

- Do not commit credentials, tokens, private keys, connection strings, personal data, or unredacted source evidence.
- Source systems are read-only by default.
- Managed output storage is separate from source access.
- Database access, connector credentials, cloud disclosure, background scheduling, and production activation require explicit authorization.
- Report suspected vulnerabilities privately to the repository owner; do not publish sensitive exploit details in public artifacts.

Future security architecture belongs in `docs/security/` and must bind exact implementation identity and evidence.
