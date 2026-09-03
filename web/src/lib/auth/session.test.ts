import { describe, expect, it } from "vitest";
import * as session from "@/lib/auth/session";
import {
  isOpaqueSessionSid,
  parseOpaqueSessionSid,
  SESSION_COOKIE_OPTIONS,
  sessionReplayBinding,
} from "@/lib/auth/session";

const SID = "ab".repeat(32);
const OTHER = "cd".repeat(32);

describe("opaque SID parse", () => {
  it("accepts 64 hex characters and normalizes to lowercase", () => {
    const mixed = "A".repeat(32) + "b".repeat(32);
    expect(isOpaqueSessionSid(mixed)).toBe(true);
    expect(parseOpaqueSessionSid(mixed)).toBe(mixed.toLowerCase());
    expect(parseOpaqueSessionSid(SID)).toBe(SID);
  });

  it("rejects missing, short, long, and non-hex values", () => {
    expect(parseOpaqueSessionSid(undefined)).toBeNull();
    expect(parseOpaqueSessionSid(null)).toBeNull();
    expect(parseOpaqueSessionSid("")).toBeNull();
    expect(parseOpaqueSessionSid("ab".repeat(16))).toBeNull();
    expect(parseOpaqueSessionSid(`${SID}aa`)).toBeNull();
    expect(parseOpaqueSessionSid("g".repeat(64))).toBeNull();
    expect(parseOpaqueSessionSid("not-a-token")).toBeNull();
    expect(parseOpaqueSessionSid("a.b.c")).toBeNull();
    expect(parseOpaqueSessionSid("forged.hmac.token")).toBeNull();
    const hmac = "eyJpYXQiOjE3MjUwMDAwMDB9.0123456789abcdef0123456789abcdef";
    expect(parseOpaqueSessionSid(hmac)).toBeNull();
  });

  it("is not an HMAC payload.sig cookie", () => {
    const hmac = "eyJpYXQiOjE3MjUwMDAwMDB9.0123456789abcdef0123456789abcdef";
    expect(hmac).toContain(".");
    expect(isOpaqueSessionSid(hmac)).toBe(false);
    expect(isOpaqueSessionSid("ab".repeat(32))).toBe(true);
  });
});

describe("session cookie flags", () => {
  it("is HttpOnly so document.cookie cannot read the SID", () => {
    expect(SESSION_COOKIE_OPTIONS.httpOnly).toBe(true);
    expect(SESSION_COOKIE_OPTIONS.sameSite).toBe("lax");
    expect(SESSION_COOKIE_OPTIONS.path).toBe("/");
  });
});

describe("session replay binding", () => {
  it("is stable for one SID and changes when the SID changes", async () => {
    const first = await sessionReplayBinding(SID);
    const again = await sessionReplayBinding(SID);
    const other = await sessionReplayBinding(OTHER);
    expect(first).toBe(again);
    expect(first).not.toBe(other);
    expect(first).toMatch(/^[0-9a-f]{64}$/);
  });

  it("hashes the opaque SID with the offline-replay prefix", async () => {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(`my-pa:offline-replay:v1:${SID}`) as BufferSource,
    );
    const expected = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
    expect(await sessionReplayBinding(SID)).toBe(expected);
  });
});

describe("HMAC session API is gone", () => {
  it("does not export encode/verify helpers or a session secret error", () => {
    expect(session).not.toHaveProperty("encodeSession");
    expect(session).not.toHaveProperty("verifySession");
    expect(session).not.toHaveProperty("verifySessionEnvelope");
    expect(session).not.toHaveProperty("newSessionId");
    expect(session).not.toHaveProperty("MissingSessionSecretError");
  });

  it("parses and binds SIDs without MYPA_SESSION_SECRET", async () => {
    expect(parseOpaqueSessionSid(SID)).toBe(SID);
    await expect(sessionReplayBinding(SID)).resolves.toMatch(/^[0-9a-f]{64}$/);
  });
});
