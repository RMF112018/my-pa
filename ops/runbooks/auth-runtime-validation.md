# Authentication runtime validation

This is the repository procedure and evidence contract for
`AUTH-IMP-WP10`. It has not been executed. Its current disposition is
`NOT_PERFORMED_OPERATOR_GATED`.

Repository implementation does not authorize production deployment, live
database migration, DNS or Cloudflare changes, public-edge activation,
bootstrap or recovery grant issuance, passkey mutation, physical-device
commissioning, or risk acceptance. Those actions require separate operator
authority. A green CI run, Playwright virtual authenticator, or validated
template cannot close physical/runtime acceptance criteria.

## Evidence contract

Copy `ops/nas/auth-runtime-evidence.example.toml` to an owner-controlled path
outside Git only after runtime validation has been separately authorized. The
record contains non-secret identities and SHA-256 evidence references, not raw
evidence payloads. Validate the checked-in inert template with:

```sh
python ops/nas/validate-auth-runtime-evidence.py \
  --evidence ops/nas/auth-runtime-evidence.example.toml \
  --allow-template
```

`TEMPLATE_VALID_NOT_RUNTIME_EVIDENCE` means only that the template is
well-formed. It is never `PASS_VERIFIED`. After an authorized validation,
remove every placeholder, leave off `--allow-template`, and validate the
operator-controlled copy. The validator is offline and read-only. It does not
contact the NAS, database, browser, Cloudflare, or a credential service.

Never record a bootstrap or recovery grant, recovery code, SID or cookie,
WebAuthn challenge, credential identifier, private key, tunnel credential,
database URL/password, authorization header, personal data, or a screenshot
that exposes any of them. Store sensitive raw evidence only inside an already
authorized boundary; reference a redacted artifact by SHA-256.

## Repository-safe preparation

Before the operator-only boundary:

1. Bind the proposed deployment to the independently reviewed full repository
   commit and tree, current Alembic head, deployment-manifest digest, and
   digest-pinned images. A later implementation commit invalidates review.
2. Confirm a current backup receipt and a rollback target. Do not run the
   migration or rollback from this procedure.
3. Run the production environment and delivery-config validators against the
   intended configuration. Browser auth must be `passkey`; BFF-to-gateway
   transport may remain `local_operator`. They are separate authentication
   planes.
4. On the private NAS path, validate service health, proxy routing, exact Host
   allowlisting, reserved-path refusal, and that PostgreSQL and the gateway are
   unpublished. A private origin may validate those properties only.
5. Do not claim WebAuthn sign-in from a private URL. Production WebAuthn must
   be observed with the browser seeing exactly
   `https://pa.bobby-fetting.me`, valid TLS, and RP ID
   `pa.bobby-fetting.me`. A private-routing method is admissible only when it
   preserves that exact browser-visible origin and RP identity.
6. Stop and obtain separate operator authority before live migration, public
   edge or DNS changes, grant issuance, credential mutation, or device tests.

## Operator-gated runtime sequence

Only after the operator authorizes the exact target and actions, record each
required case once:

1. `bootstrap`: from `uninitialized`, an operator-authorized one-time bootstrap
   establishes the fixed Principal, first passkey, initial recovery material,
   and opaque session; replay and public self-registration refuse.
2. `physical_safari_passkey`: a physical iPhone running Safari completes
   passkey authentication at the canonical origin. Playwright, emulation, and
   virtual authenticators cannot satisfy this case.
3. `installed_pwa_sign_in`: the installed PWA signs in at the same canonical
   origin without persisting grants, recovery material, cookies, or challenges
   in browser-managed offline storage.
4. `fresh_step_up_second_passkey`: direct registration without fresh
   server-side step-up refuses; one step-up authorizes one enrollment. Exercise
   a second passkey when the commissioned device/authenticator set supports it.
5. `ordinary_recovery`: one-time ordinary recovery succeeds once and replay
   refuses.
6. `operator_recovery`: separately controlled operator recovery registers the
   replacement passkey, rotates ordinary recovery material, and revokes every
   earlier session without silently deleting surviving passkeys.
7. `session_revocation`: sign-out/revoke-all makes old opaque SIDs unusable.
8. `grant_expiry`: expired bootstrap, recovery, and credential-administration
   grants refuse without logging their values.
9. `restart_persistence`: credentials, challenges, grants, and session
   authority behave correctly across the accepted process restart topology.
10. `wrong_origin_refusal`: an origin other than the exact canonical origin
    fails without redirecting or disclosing authentication material.
11. `rollback`: rehearse and, if authorized and required, validate rollback
    against the exact prior manifest. A dry run alone is not live rollback
    evidence.

Record deployment time before validation time, physical device/browser/OS
versions, whether the installed PWA was exercised, exact reviewed and deployed
commit/tree, and hashes of redacted evidence. Every case and the rollback
record must be `PASS_VERIFIED` before the top-level record may say
`PASS_VERIFIED`.

## Stop and rollback

Stop without claiming runtime readiness when any identity differs, TLS or the
canonical origin/RP ID is wrong, a required case is absent or fails, evidence
predates deployment, a secret may have entered evidence, or review no longer
matches the deployed head.

If canonical-origin WebAuthn fails, keep or take the public browser edge down
without stopping PostgreSQL, preserve the private management path, and retain
redacted failure evidence. Execute rollback only under operator authority and
only to the exact prior manifest/digests. Do not destructively downgrade auth
data. An older application image is a valid rollback target only when its
compatibility with the current schema has been proven; otherwise leave the
edge down pending operator direction.

Repository completion may be reported as
`RUNTIME_VALIDATION_PENDING_OPERATOR_AUTHORITY`. It is distinct from runtime
commissioning, which requires direct physical/live evidence.
