/**
 * The auth mode fails closed, and the WP-04 secret control is unregressed.
 *
 * An unset `MYPA_AUTH_MODE` is the same class of defect as the unset session
 * secret WP-04 closed: a deployment that configured nothing would otherwise get
 * a working passwordless sign-in, and nothing anywhere would say so.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  authMode,
  homeTenantId,
  MissingAuthModeError,
  MissingHomeTenantError,
  SyntheticModeInProductionError,
} from "@/lib/auth/mode";
import { encodeSession, MissingSessionSecretError } from "@/lib/auth/session";
import { SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";
import type { PrincipalSession } from "@/contracts/identity";

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: SYNTHETIC_MOSS_TENANT_ID,
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("auth mode", () => {
  it("refuses an unset mode rather than defaulting to synthetic", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "");
    expect(() => authMode()).toThrow(MissingAuthModeError);
  });

  it("refuses an unknown mode rather than falling back", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "development");
    expect(() => authMode()).toThrow(MissingAuthModeError);
  });

  it("refuses the synthetic provider in a production build", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    vi.stubEnv("NODE_ENV", "production");
    expect(() => authMode()).toThrow(SyntheticModeInProductionError);
  });

  it("accepts the two configured modes", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    expect(authMode()).toBe("synthetic");
    vi.stubEnv("MYPA_AUTH_MODE", "entra");
    expect(authMode()).toBe("entra");
  });

  it("permits entra in a production build", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "entra");
    vi.stubEnv("NODE_ENV", "production");
    expect(authMode()).toBe("entra");
  });
});

describe("home tenant", () => {
  it("comes from configuration when one is set", () => {
    vi.stubEnv("MYPA_ENTRA_HOME_TENANT_ID", "22222222-3333-4444-5555-666666666666");
    expect(homeTenantId()).toBe("22222222-3333-4444-5555-666666666666");
  });

  it("falls back to the synthetic tenant only in synthetic mode", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    vi.stubEnv("MYPA_ENTRA_HOME_TENANT_ID", "");
    expect(homeTenantId()).toBe(SYNTHETIC_MOSS_TENANT_ID);
  });

  it("refuses entra mode with no configured home tenant", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "entra");
    vi.stubEnv("MYPA_ENTRA_HOME_TENANT_ID", "");
    expect(() => homeTenantId()).toThrow(MissingHomeTenantError);
  });
});

describe("the WP-04 session secret control, unregressed", () => {
  it("still refuses to sign when no secret is configured", async () => {
    vi.stubEnv("MYPA_SESSION_SECRET", "");
    await expect(encodeSession(PRINCIPAL)).rejects.toBeInstanceOf(MissingSessionSecretError);
  });
});
