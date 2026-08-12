import "@testing-library/jest-dom/vitest";

/**
 * The session signing key, supplied explicitly by the test harness.
 *
 * `src/lib/auth/session.ts` has **no default**: an unset `MYPA_SESSION_SECRET`
 * throws `MissingSessionSecretError` rather than falling back to a literal.
 * That fallback existed until WP-04 and failed open — the session envelope
 * carries `principalId`, so a shared default meant anyone could mint a session
 * for any principal against a deployment that had forgotten the variable.
 *
 * It is set here rather than reintroduced as an implicit default, which is the
 * whole point: the tests that exercise signing say what key they are signing
 * with, and `src/lib/auth/session.test.ts` asserts the unset case still
 * refuses. This value is synthetic, is not a credential for anything, and
 * exists only inside this process.
 */
process.env.MYPA_SESSION_SECRET ??= "synthetic-test-signing-key-0000000000000000";

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
