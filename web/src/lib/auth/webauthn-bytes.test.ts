import { describe, expect, it } from "vitest";
import { base64UrlToBuffer, bufferToBase64Url } from "@/lib/auth/webauthn-bytes";

describe("webauthn bytes", () => {
  it("round-trips challenge material", () => {
    const bytes = new Uint8Array([1, 2, 250, 255]).buffer;
    const encoded = bufferToBase64Url(bytes);
    expect(encoded).not.toContain("+");
    expect(encoded).not.toContain("/");
    expect(encoded).not.toContain("=");
    expect(new Uint8Array(base64UrlToBuffer(encoded))).toEqual(new Uint8Array(bytes));
  });
});
