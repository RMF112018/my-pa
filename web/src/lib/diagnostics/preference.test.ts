/**
 * T01 / AC-42 / WP07-AC-056 — the preference parser fails closed.
 *
 * Every one of these cases is a way the stored value can be wrong, and every
 * one of them must resolve OFF. The assertions are written as `toBe(false)`
 * rather than a truthiness check on purpose: a parser that returned `undefined`
 * for a malformed value would pass a falsy assertion while handing callers a
 * third state the contract does not have.
 */
import { describe, expect, it } from "vitest";

import {
  DIAGNOSTICS_COOKIE,
  DIAGNOSTICS_PREFERENCE_VERSION,
  clearDiagnosticsPreference,
  diagnosticsPreferenceValue,
  diagnosticsPrincipalBinding,
  parseDiagnosticsPreference,
  serializeDiagnosticsPreference,
} from "./preference";

const BINDING_A = "a".repeat(64);
const BINDING_B = "b".repeat(64);

describe("diagnosticsPrincipalBinding", () => {
  it("is 64 lowercase hex characters", async () => {
    const binding = await diagnosticsPrincipalBinding("principal-1");
    expect(binding).toMatch(/^[0-9a-f]{64}$/);
  });

  it("is stable for one principal and different for another", async () => {
    const first = await diagnosticsPrincipalBinding("principal-1");
    const second = await diagnosticsPrincipalBinding("principal-1");
    const other = await diagnosticsPrincipalBinding("principal-2");
    expect(first).toBe(second);
    expect(other).not.toBe(first);
  });

  it("does not contain the principal id", async () => {
    const binding = await diagnosticsPrincipalBinding("principal-secret-value");
    expect(binding).not.toContain("principal");
    expect(binding).not.toContain("secret");
  });
});

describe("parseDiagnosticsPreference — the only value that resolves ON", () => {
  it("resolves ON for the exact value this application writes", () => {
    expect(parseDiagnosticsPreference(`v1.${BINDING_A}.on`, BINDING_A)).toBe(true);
  });

  it("resolves OFF for the explicit off value", () => {
    expect(parseDiagnosticsPreference(`v1.${BINDING_A}.off`, BINDING_A)).toBe(false);
  });

  it("round-trips its own serialized value", () => {
    expect(parseDiagnosticsPreference(diagnosticsPreferenceValue(true, BINDING_A), BINDING_A)).toBe(
      true,
    );
    expect(
      parseDiagnosticsPreference(diagnosticsPreferenceValue(false, BINDING_A), BINDING_A),
    ).toBe(false);
  });
});

describe("parseDiagnosticsPreference — every untrusted state resolves OFF", () => {
  const cases: ReadonlyArray<readonly [string, string | undefined | null]> = [
    ["absent (undefined)", undefined],
    ["absent (null)", null],
    ["empty", ""],
    ["a bare boolean", "true"],
    ["a bare on", "on"],
    ["the wrong version", `v2.${BINDING_A}.on`],
    ["no version", `${BINDING_A}.on`],
    ["too few segments", `v1.${BINDING_A}`],
    ["too many segments", `v1.${BINDING_A}.on.on`],
    ["an unrecognised state token", `v1.${BINDING_A}.enabled`],
    ["an uppercase state token", `v1.${BINDING_A}.ON`],
    ["an uppercase version token", `V1.${BINDING_A}.on`],
    ["surrounding whitespace", ` v1.${BINDING_A}.on `],
    ["a URI-encoded value", `v1.${BINDING_A}%2Eon`],
    ["a short binding", `v1.${"a".repeat(32)}.on`],
    ["a non-hex binding", `v1.${"g".repeat(64)}.on`],
    ["an uppercase binding", `v1.${"A".repeat(64)}.on`],
  ];

  for (const [name, value] of cases) {
    it(`resolves OFF for ${name}`, () => {
      expect(parseDiagnosticsPreference(value, BINDING_A)).toBe(false);
    });
  }

  it("resolves OFF for an oversized value even if it starts correctly", () => {
    const oversized = `v1.${BINDING_A}.on${"x".repeat(512)}`;
    expect(parseDiagnosticsPreference(oversized, BINDING_A)).toBe(false);
  });

  it("resolves OFF when the value was written for a different principal", () => {
    // The cross-Principal leak the contract forbids: a well-formed ON that
    // belongs to somebody else must not be honoured here.
    expect(parseDiagnosticsPreference(`v1.${BINDING_B}.on`, BINDING_A)).toBe(false);
  });

  it("resolves OFF when the expected binding is itself not a valid binding", () => {
    // A caller that could not establish a Principal must never get ON, even if
    // it passes the stored value straight back in as the expectation.
    expect(parseDiagnosticsPreference(`v1..on`, "")).toBe(false);
    expect(parseDiagnosticsPreference(`v1.undefined.on`, "undefined")).toBe(false);
  });
});

describe("serializeDiagnosticsPreference", () => {
  it("writes HttpOnly, SameSite=Lax, Path=/ and Secure", () => {
    const header = serializeDiagnosticsPreference(true, BINDING_A);
    expect(header).toContain(`${DIAGNOSTICS_COOKIE}=${DIAGNOSTICS_PREFERENCE_VERSION}.`);
    expect(header).toContain("HttpOnly");
    expect(header).toContain("SameSite=Lax");
    expect(header).toContain("Path=/");
    expect(header).toContain("Secure");
  });

  it("omits Secure only when explicitly asked (non-TLS development)", () => {
    expect(serializeDiagnosticsPreference(true, BINDING_A, { secure: false })).not.toContain(
      "Secure",
    );
  });

  it("never writes the raw principal id", () => {
    expect(serializeDiagnosticsPreference(true, BINDING_A)).not.toContain("principal");
  });

  it("clearing expires the cookie and stays HttpOnly", () => {
    const header = clearDiagnosticsPreference();
    expect(header).toContain(`${DIAGNOSTICS_COOKIE}=`);
    expect(header).toContain("Max-Age=0");
    expect(header).toContain("HttpOnly");
  });
});
