# What the read-only slice does not do

The limitations of the MCV read-only vertical slice as it stands, stated at or
slightly below what has been demonstrated.

**Every limitation below cites the evidence that bounds it**, and
`tests/architecture/test_limitations_cite_evidence.py` parses this file and
applies three rules: each cited path exists, each cited test resolves to a real
test function, and — the rule that makes the first two honest — **no citation
naming a real repository artifact escapes both**. That is what makes this
document non-aspirational mechanically rather than by review: a limitation whose
evidence is gone fails a test rather than quietly becoming a claim about nothing.

The third rule is there because the first two silently did not hold. At
`83a7c6c` the classifier admitted only top-level *directories*, so the three
repository-root files cited here — `PHASE-00-OPEN-DECISION-LEDGER.md`,
`pyproject.toml` and `AGENTS.md` — matched no rule and were asserted by nothing,
while this preamble said each cited path was checked. A citation nothing checks
reads exactly like one that passed.

**What "demonstrated" means here.** The slice was measured end to end by WP-5A —
9 `e2e` tests and 4 `recovery` tests, **13 of 2489 collected at `bcdbf6d`** — and
the operator sequence was executed and transcribed in
`ops/runbooks/end-to-end-operations.md`. Nothing below is derived from a design
document. Where the evidence is a measurement rather than a test, the
measurement is named.

**Every count here is bound to the commit it was taken at, inline.** An unbound
count is one that has already rotted and cannot be told from one that has not.
This sentence read "13 of 2507 collected" until it was corrected: `2507` was the
total at `81b4622`, an intermediate commit one before this document was written,
and it was never the total anywhere a reader could check. The 9 and the 4 were
right. Counts about the slice as WP-5A left it are bound to `bcdbf6d`; counts
about a measurement taken for this document name the database and the date.

---

## 1. One local principal, loopback only, and no authentication mechanism

The gateway binds `127.0.0.1` and has no option to bind elsewhere. No credential
is issued, read, or required; no TLS is configured; no ingress is activated.
`P00-OD-010` — which authentication mechanism this uses — is **open** and
reserved to the operator, and `D-30` builds the capture endpoint behind that
boundary rather than exposing it.

**Do not read this as "authentication is not needed yet".** Read it as: there is
exactly one principal, it is the process, and there is nothing to authenticate
*against*.

Evidence: `apps/gateway.py`, `src/my_pa/bootstrap/gateway.py`,
`PHASE-00-OPEN-DECISION-LEDGER.md`.

## 2. A principal does not survive its process, so the CLI cannot read back what it enrolled

`local_principal()` issues a fresh principal identifier per composition, and
`apps/cli/invoke.py` composes a runtime per invocation. `authorize` reads the
authorized scope from the enrollments the acting principal holds, so an
enrollment created by one CLI invocation is held by an identifier that never
exists again.

Measured on a disposable database on 2026-08-03 and transcribed in
`ops/runbooks/end-to-end-operations.md`: `sources.enroll` through
`apps/cli/invoke.py` was `allowed` and wrote its enrollment; three later
`invoke.py` calls to `sources.status` for that enrollment were each `denied`
with `denial_reason scope_not_authorized`, under three different principal
identifiers — while the same four capabilities through **one running gateway**
recorded `allowed` four times under one identifier.

**The scoped capabilities are therefore usable from `apps/cli/invoke.py` only
within a scope that same invocation enrolled, which no single invocation can
do.** `capabilities.get` is the exception and works, because it carries no
source scope. Through a running gateway or MCP server every capability works,
because that process holds one principal for its lifetime.

This is not a defect any of the work packages so far may fix: whether a local
principal has a durable identity is an authentication question and `P00-OD-010`
is open. Recorded as `D-67` in `docs/plans/mcv-completion-plan.md`, which defers
it to that decision rather than closing it here.

Evidence: `src/my_pa/bootstrap/gateway.py`,
`src/my_pa/application/authorization.py`, `src/my_pa/domain/policy/decision.py`,
`ops/runbooks/end-to-end-operations.md`.

## 3. The corpus is four synthetic objects, and nothing has been proven wider

Every measurement in this repository was taken over `fixtures/mcv/root`: four
files at depth 0, of which two are extractable. `P00-OD-009` is **open** — no
live NAS root, no GoodNotes root, and no personal corpus has been read by
anything.

**Do not claim search behaviour, extraction throughput, or coverage accuracy at
scale.** Neither has been measured at any size but this one.

Evidence: `fixtures/mcv/README.md`,
`tests/end_to_end/test_vertical_slice.py::test_the_operator_can_list_and_inspect_bounded_objects_without_recursing`.

## 4. PDF is `unsupported` — reported and counted, never silently skipped

`P00-OD-003` is **open** and no PDF library is a dependency of this repository.
A PDF in an enrolled scope produces a counted `unsupported` outcome and moves the
enrollment's coverage to `partially_processed`, which is the truthful state. It
does not produce an absence, and it does not produce an error.

Evidence:
`tests/end_to_end/test_vertical_slice.py::test_every_enumerated_identifier_is_fetchable_and_the_pdf_is_reported_not_skipped`.

## 5. No model is called, anywhere

No summarisation, no named-entity extraction, no embedding, no identity
resolution, no contradiction detection. Extraction is deterministic and cites
what it produced. `P00-OD-006` is **open**.

Evidence: `src/my_pa/infrastructure/extraction/`, `pyproject.toml`.

## 6. Listings stop at the page size and issue no continuation cursor

Truncation is disclosed rather than hidden — `truncation.is_truncated` with a
reason — but `next_cursor` is always `null` and there is no way to ask for the
next page. A caller that needs the whole of a large scope cannot get it.

This one the build states about itself: it is derived into every
`capabilities.get` envelope rather than written here.

Evidence: `src/my_pa/application/capabilities.py`,
`tests/contract/test_capabilities_and_readiness.py`.

## 7. Recovery is proven for two failures and no others

What is proven: a worker **process** killed mid-extraction loses no object and
duplicates none, and an expired lease lets another worker finish the job. Four
`recovery` tests, one of which kills a real subprocess rather than simulating it.

What is **not** proven, and must not be claimed: a gateway crashing mid-request;
PostgreSQL failing over or restarting under load; more than one worker running
concurrently beyond the connection-pool arithmetic; or any recovery of the
migration control plane.

Evidence:
`tests/jobs/test_extraction_executor.py::test_a_worker_process_killed_mid_extraction_leaves_its_lease_and_loses_nothing`,
`tests/jobs/test_extraction_executor.py::test_an_expired_lease_lets_another_worker_finish_the_job`.

## 8. A database that cannot record an audit row answers `internal_error`

Measured on 2026-08-03 against a disposable database (`my_pa_chain_probe`,
created empty, stepped through all ten Alembic revisions and dropped), invoking
`capabilities.get` and `sources.list` through `apps/cli/invoke.py` at every
chain position:

- unreachable answers `unavailable`;
- an empty database and every revision from `5d75f23847c9` through
  `8b3f5c17d904` answer `internal_error` to both — "the request could not be
  completed", which tells an operator nothing about which state they are in;
- `9c6b4a18ed72`, **one revision behind head** `af3d35efb9c0`, **serves both**:
  `capabilities.get` exited `0` with the envelope it returns at head, differing
  only in `completed_at`, `observed_at` and `correlation_id`, and `sources.list`
  returned the same `denied` it returns at head. Six audit rows were written
  while the database sat one revision behind head.

**There are two boundaries, and neither of them is "not at head" on its own.**

`9c6b4a18ed72` creates `knowledge.audit_events`. Every served request commits a
row into it, and a request that cannot be audited fails rather than being served
unaudited — so **below** that revision every capability answers `internal_error`,
and canonical `my_pa` at `6c4d3ea82f10` is three revisions below it, which is why
it answers `internal_error`.

Head `af3d35efb9c0` creates `enrollment_objects`, and that boundary is
per-capability. Measured on a second disposable database (`my_pa_chain_probe2`,
dropped): at `9c6b4a18ed72`, `sources.enroll` through `apps/cli/invoke.py`
answered `internal_error`, while the **same call at head** on the **same
database** answered `created true` with `coverage.eligible 4`. So one revision
behind head is a state in which some capabilities serve and at least one does
not.

**What this means for the phrase "not at head".** It is not a diagnosis — a
database can be behind head and serve a capability. It is a correct statement
about the build as a whole, because a capability of this build already fails one
revision short. Both halves matter, and stating only the first is what made an
earlier version of this limitation wrong.

The unreachable case was classified correctly by WP-4B2a; the unrecordable-audit
case was not, and correcting the taxonomy is out of scope and deferred by `D-65`.

`apps/cli/health.py` **detects a database that is not at head** and names its
revision against head. It refuses everything below head, which is wider than the
audit-table boundary and is deliberate (`D-62`): it is an operational policy — a
database behind head is not a state an operator should treat as good — and it is
borne out by `sources.enroll` above. It is **not** a claim that every capability
fails below head, and it does not reclassify what the application says.

Evidence: `apps/cli/health.py`,
`tests/contract/test_health_probe.py::test_the_three_states_are_mutually_distinguishable`,
`src/my_pa/infrastructure/persistence/unit_of_work.py`,
`tests/policy/test_audit_is_not_swallowed.py`, `migrations/versions/`.

## 9. Nothing here is deployed, packaged, supervised, or multi-user

No launchd plist, no systemd unit, no console entry point, no distributable
artifact, and no second user. Both processes are started by hand and stopped by
signal. Deployment, production activation, packaging for distribution,
multi-user operation, and risk acceptance are all on WP-5's explicit
out-of-scope list and are operator-gated (`AGENTS.md` section 5).

`ops/launchd/` and `ops/systemd/` are reserved scaffold directories and hold no
unit file.

Evidence: `docs/plans/mcv-completion-plan.md`, `ops/launchd/README.md`,
`ops/systemd/README.md`.

## 10. Source access is read-only, and there is no write path to any source

Roots are opened read-only and containment is revalidated immediately before
each read. The source-provider port has no write method, so "my-pa does not
modify your files" is a property of the interface rather than of the
implementations behind it.

Stated here because it is a limitation an operator may be *looking* for, not
only one they should be warned about.

Evidence: `src/my_pa/contracts/ports.py`,
`src/my_pa/infrastructure/providers/fixture.py`.

---

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy
identities may appear only in explicit compatibility or evidence records.
