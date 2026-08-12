import { describe, expect, it } from "vitest";
import { encodeSession, verifySession } from "@/lib/auth/session";
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
