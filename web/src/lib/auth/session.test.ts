import { afterEach, describe, expect, it, vi } from "vitest";
import { encodeSession, MissingSessionSecretError, verifySession } from "@/lib/auth/session";
import type { PrincipalSession } from "@/contracts/identity";

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

describe("session encode/verify", () => {
  it("round-trips a principal", async () => {
    const token = await encodeSession(PRINCIPAL);
    const verified = await verifySession(token);
    expect(verified).not.toBeNull();
    expect(verified?.oid).toBe(PRINCIPAL.oid);
    expect(verified?.upn).toBe(PRINCIPAL.upn);
  });

  it("rejects a tampered payload (fail closed)", async () => {
    const token = await encodeSession(PRINCIPAL);
    const [payload, signature] = token.split(".");
    // Flip a character in the payload; the HMAC must no longer verify.
    const tampered = `${payload.slice(0, -1)}${payload.endsWith("A") ? "B" : "A"}.${signature}`;
    expect(await verifySession(tampered)).toBeNull();
  });

  it("rejects a tampered signature", async () => {
    const token = await encodeSession(PRINCIPAL);
    const [payload] = token.split(".");
    expect(await verifySession(`${payload}.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`)).toBeNull();
  });

  it("rejects garbage, empty, and missing tokens", async () => {
    expect(await verifySession("not-a-token")).toBeNull();
    expect(await verifySession("")).toBeNull();
    expect(await verifySession(undefined)).toBeNull();
    expect(await verifySession("a.b.c")).toBeNull();
  });
});

/**
 * The session envelope carries `principalId` and is trusted by `middleware.ts`
 * and every `requirePrincipal` route. Until WP-04 an unset `MYPA_SESSION_SECRET`
 * silently selected a hardcoded key, so a deployment that forgot one
 * environment variable accepted sessions minted by anyone — failing open, with
 * no signal at all. There is now no default, and these assert that.
 */
describe("session secret configuration", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("refuses to sign when no secret is configured", async () => {
    vi.stubEnv("MYPA_SESSION_SECRET", "");
    await expect(encodeSession(PRINCIPAL)).rejects.toBeInstanceOf(MissingSessionSecretError);
  });

  it("refuses to verify when no secret is configured, rather than answering", async () => {
    // The refusal has to reach the caller. Returning `null` here would be
    // indistinguishable from "not signed in" and would hide the
    // misconfiguration behind a login screen.
    const token = await encodeSession(PRINCIPAL);
    vi.stubEnv("MYPA_SESSION_SECRET", "");
    await expect(verifySession(token)).rejects.toBeInstanceOf(MissingSessionSecretError);
  });

  it("refuses a secret too short to be one", async () => {
    vi.stubEnv("MYPA_SESSION_SECRET", "short");
    await expect(encodeSession(PRINCIPAL)).rejects.toBeInstanceOf(MissingSessionSecretError);
  });

  it("signs with the configured secret and not with any other", async () => {
    // The control: two different configured secrets must not verify each
    // other's tokens. Without it, "a secret is required" could be satisfied by
    // an implementation that required the variable and then ignored it.
    vi.stubEnv("MYPA_SESSION_SECRET", "first-synthetic-signing-key-000000000000");
    const token = await encodeSession(PRINCIPAL);
    expect(await verifySession(token)).not.toBeNull();

    vi.stubEnv("MYPA_SESSION_SECRET", "second-synthetic-signing-key-00000000000");
    expect(await verifySession(token)).toBeNull();
  });
});
