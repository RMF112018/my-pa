import "@testing-library/jest-dom/vitest";

/**
 * The BFF session-service HMAC key, supplied explicitly by the test harness.
 *
 * Distinct from `MYPA_WEBAUTHN_BFF_SECRET`. An unset or short secret is 503
 * `authority_unavailable`, not 401. Tests that exercise the unset case stub
 * the variable themselves.
 */
process.env.MYPA_SESSION_SERVICE_SECRET ??= "synthetic-test-session-service-secret-00";
process.env.MYPA_WEBAUTHN_BFF_SECRET ??= "synthetic-test-webauthn-bff-secret-000000";

/**
 * The identity provider, supplied explicitly for the same reason.
 *
 * `src/lib/auth/mode.ts` has no default: an unset `MYPA_AUTH_MODE` throws
 * `MissingAuthModeError` rather than assuming the synthetic provider, because
 * assuming it would give a deployment that had configured nothing a working
 * passwordless sign-in. The tests that exercise sign-in say which provider they
 * are signing in against, and `src/app/api/session/route.test.ts` asserts that
 * the unset and production cases still refuse.
 */
process.env.MYPA_AUTH_MODE ??= "synthetic";
process.env.MYPA_CANONICAL_ORIGIN ??= "http://localhost:3000";
