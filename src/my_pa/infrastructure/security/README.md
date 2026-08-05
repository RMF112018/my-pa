# Security Boundary

**Status:** `IMPLEMENTING` (was `SCAFFOLD_ONLY`; activated by WP-01, the R0A
Identity Foundation work package of the ratified Moss v4.0 campaign — see
[`docs/campaign/WORK-PACKAGE-MAP.md`](/docs/campaign/WORK-PACKAGE-MAP.md)).

This directory owns the authentication boundary that turns validated token
claims into a Principal context:

- [`principal_identity.py`](principal_identity.py) —
  `PrincipalIdentityService`: rejects caller-supplied identity, validates
  `(tid, oid)` claims against the injected Moss home tenant ID, and resolves
  the stable `principal_id` through the registry. Synthetic claims only; no
  live credentials, token libraries, or tenant values appear here.

Credentials, live source-system access, deployment, and production activation
remain out of scope and separately gated.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.
