import { describe, expect, it } from "vitest";
import {
  validateTokenClaims,
  rejectCallerSuppliedPrincipal,
  MissingClaimError,
  ForeignTenantError,
  CallerSuppliedPrincipalError,
} from "@/lib/auth/claims";
import { SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";

const HOME = SYNTHETIC_MOSS_TENANT_ID;
const OID = "aaaa0001-0000-0000-0000-000000000001";

describe("validateTokenClaims", () => {
  it("accepts home-tenant claims with a UUID oid", () => {
    const claims = validateTokenClaims(
      { tid: HOME, oid: OID, upn: "synthetic.a@moss.example", name: "Synthetic A" },
      HOME,
    );
    expect(claims.oid).toBe(OID);
    expect(claims.upn).toBe("synthetic.a@moss.example");
  });

  it("rejects a foreign tenant", () => {
    expect(() =>
      validateTokenClaims(
        { tid: "99999999-9999-9999-9999-999999999999", oid: OID, upn: "x", name: "x" },
        HOME,
      ),
    ).toThrow(ForeignTenantError);
  });

  it("rejects missing tid", () => {
    expect(() => validateTokenClaims({ oid: OID }, HOME)).toThrow(MissingClaimError);
  });

  it("rejects a non-UUID oid", () => {
    expect(() => validateTokenClaims({ tid: HOME, oid: "not-a-uuid" }, HOME)).toThrow(
      MissingClaimError,
    );
  });

  it("is case-insensitive on tenant comparison", () => {
    const claims = validateTokenClaims(
      { tid: HOME.toUpperCase(), oid: OID, upn: "", name: "" },
      HOME,
    );
    expect(claims.tid.toLowerCase()).toBe(HOME);
  });
});

describe("rejectCallerSuppliedPrincipal", () => {
  it("passes clean payloads", () => {
    expect(() =>
      rejectCallerSuppliedPrincipal({ text: "note", nested: { mode: "text" } }),
    ).not.toThrow();
  });

  it("rejects top-level identity fields", () => {
    expect(() => rejectCallerSuppliedPrincipal({ principalId: "p-1" })).toThrow(
      CallerSuppliedPrincipalError,
    );
    expect(() => rejectCallerSuppliedPrincipal({ tid: HOME })).toThrow(
      CallerSuppliedPrincipalError,
    );
  });

  it("rejects nested identity fields, including inside arrays", () => {
    expect(() =>
      rejectCallerSuppliedPrincipal({ items: [{ meta: { oid: OID } }] }),
    ).toThrow(CallerSuppliedPrincipalError);
    expect(() =>
      rejectCallerSuppliedPrincipal({ a: { b: { principal_id: "p-1" } } }),
    ).toThrow(CallerSuppliedPrincipalError);
  });
});
