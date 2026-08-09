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
