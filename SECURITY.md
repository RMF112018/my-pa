# Security Policy

## Supported status

`my-pa` is an unreleased Minimum Viable Candidate. No production deployment or public security support commitment exists yet.

## Reporting a vulnerability

Report suspected vulnerabilities privately to the repository owner through a private GitHub security advisory when available. Do not open a public issue containing exploit details, credentials, personal information, source content, or access paths.

Include the affected commit or version, reproduction steps using synthetic data, impact, and any safe mitigation. The repository owner determines disclosure, remediation priority, release, and risk acceptance.

## Data and credential rules

- Never commit tokens, passwords, private keys, connection strings, personal data, source-document contents, or unredacted evidence.
- Use least-privilege credentials supplied at runtime. Secret examples must be inert placeholders.
- Source providers are read-only by default. Managed writes belong only in designated managed storage.
- Email, calendar, contacts, NAS content, relationship records, and derived personal intelligence are sensitive. Tests must use small synthetic fixtures.
- Logs exclude sensitive payloads and credentials by default. Redact before retaining evidence.
- Cloud or external-model disclosure requires an explicit data-eligibility decision; local availability is not consent to transmit.
- Generated content must preserve provenance and must not overwrite authoritative evidence silently.
- Database access, source mutation, destructive actions, credential changes, deployment, and production activation require separate explicit operator authorization.

## Operator NAS access

Runtime never depends on an SSH alias; processes receive configured roots. Where separately authorized operator NAS access is required, the only approved alias is `ssh bf-nas`. Any earlier employer-derived host alias is deprecated and must not appear in active instructions, runtime identity, tooling, or documentation. Do not inspect or modify SSH configuration as part of ordinary work.

## Dependency and workflow security

- Add dependencies only for a current need; avoid overlapping libraries.
- Pin third-party GitHub Actions to immutable commit SHAs and grant workflows only required permissions.
- Review dependency changes, release notes, license impact, and vulnerability advisories before merge.
- Dependabot alerts and security updates should be enabled in repository settings. Add ecosystem version updates only when a corresponding manifest exists.
- Do not suppress or close a vulnerability finding without evidence tied to the exact affected head or release.

## Security tests

Use synthetic adversarial cases for authorization boundaries, path handling, source/managed-store separation, provenance, redaction, and fail-closed behavior. Live personal accounts or production credentials are prohibited in automated tests.
