import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SecuritySettings } from "@/app/(app)/system/security/security-settings";

vi.mock("@/lib/auth/webauthn-ceremony", () => ({
  createPasskey: vi.fn(async () => ({ id: "created" })),
  getPasskey: vi.fn(async () => ({ id: "asserted" })),
  WebAuthnBrowserError: class WebAuthnBrowserError extends Error {
    constructor(public code: string) {
      super(code);
      this.name = "WebAuthnBrowserError";
    }
  },
}));

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

beforeEach(() => {
  Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("security settings enrollment", () => {
  it("step-up then posts registration/options with the grant", async () => {
    const fetchStub = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const path = String(_url);
      if (path.endsWith("/step-up/options")) return json({ challenge: "su" });
      if (path.endsWith("/step-up/complete")) return json({ administrationGrant: "grant-1" });
      if (path.endsWith("/registration/options")) return json({ challenge: "reg" });
      if (path.endsWith("/registration/complete")) return json({ ok: true });
      if (path.endsWith("/credentials/list")) return json({ credentials: [] });
      return json({ error: { code: "failed" } }, 500);
    });
    vi.stubGlobal("fetch", fetchStub);
    render(<SecuritySettings initialCredentials={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "Add a passkey" }));
    await screen.findByRole("status");
    const actions = fetchStub.mock.calls.map((call) => String(call[0]));
    expect(actions[0]).toBe("/api/webauthn/step-up/options");
    expect(actions[1]).toBe("/api/webauthn/step-up/complete");
    expect(actions[2]).toBe("/api/webauthn/registration/options");
    expect(JSON.parse(String(fetchStub.mock.calls[2][1]?.body))).toEqual({
      grant: "grant-1",
    });
  });

  it("tells the operator to add another passkey before removing the last one", async () => {
    const fetchStub = vi.fn(async (url: string | URL | Request) => {
      const path = String(url);
      if (path.endsWith("/step-up/options")) return json({ challenge: "su" });
      if (path.endsWith("/step-up/complete")) return json({ administrationGrant: "grant-1" });
      if (path.endsWith("/credentials/revoke")) {
        return json({ error: { code: "last_passkey_requires_recovery" } }, 400);
      }
      return json({ error: { code: "failed" } }, 500);
    });
    vi.stubGlobal("fetch", fetchStub);
    render(
      <SecuritySettings
        initialCredentials={[
          {
            credentialId: "cred-1",
            label: "Only key",
            createdAt: "2026-09-07T00:00:00+00:00",
            lastUsedAt: null,
          },
        ]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Add another passkey before removing this one.",
    );
    expect(screen.queryByText("Add recovery codes before removing the last passkey.")).toBeNull();
  });
});
