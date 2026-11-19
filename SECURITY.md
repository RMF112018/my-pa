# Security Policy

## Supported status

`my-pa` is an unreleased Minimum Viable Candidate. No production deployment or public security support commitment exists yet.

## Reporting a vulnerability

Report suspected vulnerabilities privately to the repository owner through a private GitHub security advisory when available. Do not open a public issue containing exploit details, credentials, personal information, source content, or access paths.

Include the affected commit or version, reproduction steps using synthetic data, impact, and any safe mitigation. The repository owner determines disclosure, remediation priority, release, and risk acceptance.

## Data and credential rules

Security handling uses three automatic classes rather than per-task security approvals:

- **S0 STANDARD:** ordinary source code, synthetic test fixtures, redacted diagnostics and nonsecret documents. Normal GitHub/CI workflow.
- **S1 PRIVATE:** proprietary project material, ordinary personal information and private source content. Handling within an already authorized authenticated boundary is allowed without a separate approval for each task. Public GitHub, public build logs and unapproved external recipients are not authorized destinations for S1 payloads.
- **S2 CRITICAL:** live passwords, tokens, private keys, grant changes, confirmed critical exploit/exfiltration risks, unauthorized private-data disclosure and irreversible canonical-data loss. Contain the affected action and obtain exact authority for operations outside an existing approval boundary.

Never commit or print live secrets or unredacted private content to public GitHub/CI. Use nonsecret placeholders, scoped runtime identities, redaction and least-privilege defaults. A manifest may record `PROTECTED_WITHHELD` with a safe reference; it must not archive the secret itself. Preserve provenance for derived material.

Use synthetic data and isolated test databases by default; ordinary authentication or persistence code tests are not exceptional security events. Live personal accounts, protected source repositories, production database access, credential mutation, source writes and destructive operations require an already valid operator authorization or narrowly defined standing policy. Never infer consent for cloud processing from local visibility.

Confirmed critical exposures receive targeted private escalation; routine low/medium-severity findings may be corrected in scope or carried as tracked follow-ups when not blocked by an applicable mandatory test or acceptance criterion. Do not suppress findings or weaken mandatory checks merely to release faster.

A reversible release within a separately approved standing release envelope can use its documented automation; absent that envelope, existing operator production gates remain. The repository policy change itself does not activate production.

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
