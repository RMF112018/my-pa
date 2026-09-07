/**
 * Setup and operator-recovery keep the grant and recovery codes in React state.
 * They never write localStorage, sessionStorage, or the URL.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SetupPage from "@/app/setup/page";
import OperatorRecoveryPage from "@/app/recover/operator/page";

const nav = { push: vi.fn(), refresh: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, refresh: nav.refresh }),
}));

vi.mock("@/lib/auth/webauthn-ceremony", () => ({
  createPasskey: vi.fn(async () => ({ id: "cred" })),
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
  nav.push.mockReset();
  nav.refresh.mockReset();
  Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("setup grant enrollment", () => {
  it("does not write the grant or codes to localStorage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const fetchStub = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      if (String(_url).includes("/options")) return json({ challenge: "abc" });
      return json({ sessionCreated: true, codes: ["AAAA-BBBB"] });
    });
    vi.stubGlobal("fetch", fetchStub);
    render(<SetupPage />);
    await userEvent.type(screen.getByLabelText("Setup grant"), "one-time-grant");
    await userEvent.click(screen.getByRole("button", { name: "Create the owner passkey" }));
    await screen.findByText("AAAA-BBBB");
    expect(fetchStub.mock.calls[0]?.[0]).toBe("/api/webauthn/bootstrap/registration/options");
    expect(JSON.parse(String(fetchStub.mock.calls[0]?.[1]?.body))).toEqual({
      grant: "one-time-grant",
    });
    expect(setItem).not.toHaveBeenCalled();
    expect(window.localStorage.length).toBe(0);
    setItem.mockRestore();
  });

  it("uses the same invalid-grant copy for public grant failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ error: { code: "unknown_grant" } }, 400)),
    );
    render(<SetupPage />);
    await userEvent.type(screen.getByLabelText("Setup grant"), "expired-or-unknown");
    await userEvent.click(screen.getByRole("button", { name: "Create the owner passkey" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That grant is not valid.");
  });
});

describe("operator recovery grant enrollment", () => {
  it("does not write localStorage and posts operator-recovery actions", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const fetchStub = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => {
      if (String(_url).includes("/options")) return json({ challenge: "abc" });
      return json({ sessionCreated: true, codes: ["CCCC-DDDD"] });
    });
    vi.stubGlobal("fetch", fetchStub);
    render(<OperatorRecoveryPage />);
    await userEvent.type(screen.getByLabelText("Operator recovery grant"), "operator-grant");
    await userEvent.click(screen.getByRole("button", { name: "Register a replacement passkey" }));
    await screen.findByText("CCCC-DDDD");
    expect(fetchStub.mock.calls[0]?.[0]).toBe(
      "/api/webauthn/operator-recovery/registration/options",
    );
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });
});
