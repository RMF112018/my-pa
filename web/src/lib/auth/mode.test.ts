/**
 * The auth mode fails closed. Unset `MYPA_AUTH_MODE` is a deployment defect,
 * not a default synthetic provider.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  authMode,
  homeTenantId,
  MissingAuthModeError,
  SyntheticModeInProductionError,
} from "@/lib/auth/mode";
import { SYNTHETIC_MOSS_TENANT_ID } from "@/lib/auth/synthetic";

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

  it("refuses retired entra and local_operator web modes", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "entra");
    expect(() => authMode()).toThrow(MissingAuthModeError);
    vi.stubEnv("MYPA_AUTH_MODE", "local_operator");
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
    vi.stubEnv("MYPA_AUTH_MODE", "passkey");
    expect(authMode()).toBe("passkey");
  });

  it("permits passkey in a production build", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "passkey");
    vi.stubEnv("NODE_ENV", "production");
    expect(authMode()).toBe("passkey");
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

  it("does not require an Entra home tenant in passkey mode and does not invent one", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "passkey");
    vi.stubEnv("MYPA_ENTRA_HOME_TENANT_ID", "");
    expect(() => homeTenantId()).not.toThrow();
    expect(homeTenantId()).toBe("");
  });
});
