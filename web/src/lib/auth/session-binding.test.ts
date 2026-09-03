/**
 * Session binding is the opaque SID plus Python authority — not a process-local Map.
 *
 * `resolveSessionPrincipal` POSTs the SID to the session-service. Two live
 * principals resolve independently; a dead SID is unauthenticated; a 503 is
 * authority_unavailable. The cookie never carries a Principal.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { parseOpaqueSessionSid, sessionReplayBinding } from "@/lib/auth/session";
import { AuthorityUnavailableError, resolveSessionPrincipal } from "@/lib/auth/principal";
import { callSessionService } from "@/lib/auth/session-service";
import type { PrincipalSession } from "@/contracts/identity";

vi.mock("@/lib/auth/session-service", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth/session-service")>();
  return {
    ...actual,
    callSessionService: vi.fn(),
  };
});

const SID_A = "aa".repeat(32);
const SID_B = "bb".repeat(32);
const SID_DEAD = "cc".repeat(32);
const SID_DOWN = "dd".repeat(32);

const A: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

const B: PrincipalSession = {
  ...A,
  principalId: "syn-bbbb0002",
  oid: "bbbb0002-0000-0000-0000-000000000002",
  upn: "synthetic.b@moss.example",
  displayName: "Synthetic B",
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const mockedCall = vi.mocked(callSessionService);

beforeEach(() => {
  mockedCall.mockReset();
  mockedCall.mockImplementation(async (_action, body) => {
    const sid = (body as { sid?: string }).sid;
    if (sid === SID_A) return jsonResponse(200, { principal: A });
    if (sid === SID_B) return jsonResponse(200, { principal: B });
    if (sid === SID_DEAD) return jsonResponse(401, { error: { code: "unauthenticated" } });
    if (sid === SID_DOWN) {
      return jsonResponse(503, { error: { code: "authority_unavailable" } });
    }
    return jsonResponse(401, { error: { code: "unauthenticated" } });
  });
});

describe("parseOpaqueSessionSid rejects garbage", () => {
  it("refuses HMAC-shaped and short values", () => {
    expect(parseOpaqueSessionSid("forged.token")).toBeNull();
    expect(parseOpaqueSessionSid("short")).toBeNull();
    expect(parseOpaqueSessionSid("zz".repeat(32))).toBeNull();
    expect(
      parseOpaqueSessionSid("eyJpYXQiOjE3MjUwMDAwMDB9.0123456789abcdef0123456789abcdef"),
    ).toBeNull();
  });
});

describe("sessionReplayBinding uses the prefix", () => {
  it("digests my-pa:offline-replay:v1: plus the SID", async () => {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(`my-pa:offline-replay:v1:${SID_A}`) as BufferSource,
    );
    const expected = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    expect(await sessionReplayBinding(SID_A)).toBe(expected);
  });
});

describe("resolveSessionPrincipal consults the session-service", () => {
  it("resolves two live principals from distinct SIDs", async () => {
    await expect(resolveSessionPrincipal(SID_A)).resolves.toMatchObject({
      principalId: A.principalId,
      authenticationProvider: "synthetic",
    });
    await expect(resolveSessionPrincipal(SID_B)).resolves.toMatchObject({
      principalId: B.principalId,
    });
    expect(mockedCall).toHaveBeenCalledWith("sessions/touch", { sid: SID_A }, undefined);
    expect(mockedCall).toHaveBeenCalledWith("sessions/touch", { sid: SID_B }, undefined);
  });

  it("never resolves principal B from principal A's SID", async () => {
    const fromA = await resolveSessionPrincipal(SID_A);
    expect(fromA?.principalId).toBe(A.principalId);
    expect(fromA?.principalId).not.toBe(B.principalId);
    expect(fromA?.oid).not.toBe(B.oid);
  });

  it("returns null for a dead SID", async () => {
    await expect(resolveSessionPrincipal(SID_DEAD)).resolves.toBeNull();
  });

  it("throws AuthorityUnavailableError on 503", async () => {
    await expect(resolveSessionPrincipal(SID_DOWN)).rejects.toBeInstanceOf(
      AuthorityUnavailableError,
    );
  });

  it("returns null for a non-SID cookie without calling the service", async () => {
    await expect(resolveSessionPrincipal("not-a-sid")).resolves.toBeNull();
    expect(mockedCall).not.toHaveBeenCalled();
  });

  it("does not call the service for an HMAC payload.sig cookie", async () => {
    await expect(
      resolveSessionPrincipal("eyJpYXQiOjE3MjUwMDAwMDB9.0123456789abcdef0123456789abcdef"),
    ).resolves.toBeNull();
    expect(mockedCall).not.toHaveBeenCalled();
  });
});
