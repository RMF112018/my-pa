/**
 * The sign-in screen offers only what the configured web mode will accept.
 *
 * Passkey mode shows PasskeySignIn only. Synthetic mode shows the development
 * principal buttons plus passkey. Neither mode offers Entra or local-operator UI.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SignInPage, { dynamic } from "@/app/sign-in/page";

const nav = {
  push: vi.fn(),
  refresh: vi.fn(),
  search: "",
};

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, refresh: nav.refresh }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

vi.mock("@/lib/auth/webauthn-ceremony", () => ({
  getPasskey: vi.fn(async () => ({ id: "cred" })),
  WebAuthnBrowserError: class WebAuthnBrowserError extends Error {
    constructor(public code: string) {
      super(code);
      this.name = "WebAuthnBrowserError";
    }
  },
}));

beforeEach(() => {
  nav.push.mockReset();
  nav.refresh.mockReset();
  nav.search = "";
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("the sign-in screen", () => {
  it("is rendered per request, so the admissible set is not baked in at build time", () => {
    expect(dynamic).toBe("force-dynamic");
  });

  it("offers one principal over a local_operator gateway in synthetic mode", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
    render(<SignInPage />);
    expect(screen.getByTestId("sign-in-synthetic-a")).toBeInTheDocument();
    expect(screen.queryByTestId("sign-in-synthetic-b")).toBeNull();
    expect(screen.getByRole("button", { name: "Sign in with a passkey" })).toBeInTheDocument();
  });

  it("offers both over an entra gateway in synthetic mode", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "entra");
    render(<SignInPage />);
    expect(screen.getByTestId("sign-in-synthetic-a")).toBeInTheDocument();
    expect(screen.getByTestId("sign-in-synthetic-b")).toBeInTheDocument();
  });

  it("offers only passkey sign-in in passkey mode", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "passkey");
    render(<SignInPage />);
    expect(screen.getByRole("button", { name: "Sign in with a passkey" })).toBeInTheDocument();
    expect(screen.queryByTestId("sign-in-synthetic-a")).toBeNull();
    expect(screen.queryByTestId("sign-in-synthetic-b")).toBeNull();
    expect(screen.queryByLabelText("Operator secret")).toBeNull();
    expect(screen.queryByText("Microsoft Entra")).toBeNull();
    expect(screen.queryByRole("link", { name: /entra/i })).toBeNull();
  });

  it("never offers Entra or local-operator UI in synthetic mode", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    render(<SignInPage />);
    expect(screen.queryByLabelText("Operator secret")).toBeNull();
    expect(screen.queryByText("Microsoft Entra")).toBeNull();
    expect(screen.queryByRole("link", { name: /entra/i })).toBeNull();
  });

  it("ships no claims to the browser", () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "entra");
    const { container } = render(<SignInPage />);
    expect(container.innerHTML).not.toContain("@moss.example");
    expect(container.innerHTML).not.toContain("aaaa0001-0000-0000-0000-000000000001");
  });

  it("honours a safe next path after synthetic sign-in", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    nav.search = "next=/work";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ signedIn: true }), { status: 200 })),
    );
    render(<SignInPage />);
    await userEvent.click(screen.getByTestId("sign-in-synthetic-a"));
    expect(nav.push).toHaveBeenCalledWith("/work");
  });

  it("ignores an unsafe next path rather than open-redirecting", async () => {
    vi.stubEnv("MYPA_AUTH_MODE", "synthetic");
    nav.search = "next=https://evil.example";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ signedIn: true }), { status: 200 })),
    );
    render(<SignInPage />);
    await userEvent.click(screen.getByTestId("sign-in-synthetic-a"));
    expect(nav.push).toHaveBeenCalledWith("/today");
  });
});
