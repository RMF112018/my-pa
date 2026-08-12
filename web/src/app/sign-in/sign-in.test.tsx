/**
 * The sign-in screen offers only what `POST /api/session` will accept.
 *
 * The other half of `D-15`. Blocking the second sign-in in the route is what
 * prevents the cross-principal read; not *offering* it is what keeps a person
 * from being shown a button that is guaranteed to fail. Both halves read
 * `admissibleSyntheticPrincipals()`, so they cannot drift — this test would go
 * red if the screen kept a list of its own.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import SignInPage, { dynamic } from "@/app/sign-in/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("the sign-in screen", () => {
  it("is rendered per request, so the admissible set is not baked in at build time", () => {
    // `next build` reported this page as **static** before this export existed,
    // which would have fixed the admissible set to whatever the build machine's
    // `MYPA_GATEWAY_AUTH_MODE` was. Asserted here because the symptom only
    // appears in a production build, where no test below would see it.
    expect(dynamic).toBe("force-dynamic");
  });

  it("offers one principal over a local_operator gateway", () => {
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
    render(<SignInPage />);
    expect(screen.getByTestId("sign-in-synthetic-a")).toBeInTheDocument();
    expect(screen.queryByTestId("sign-in-synthetic-b")).toBeNull();
  });

  it("offers both over an entra gateway", () => {
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "entra");
    render(<SignInPage />);
    expect(screen.getByTestId("sign-in-synthetic-a")).toBeInTheDocument();
    expect(screen.getByTestId("sign-in-synthetic-b")).toBeInTheDocument();
  });

  it("ships no claims to the browser", () => {
    vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "entra");
    const { container } = render(<SignInPage />);
    // Labels are offered; object identifiers and UPNs are not. The server
    // component hands the client half `key` and `label` and nothing else.
    expect(container.innerHTML).not.toContain("@moss.example");
    expect(container.innerHTML).not.toContain("aaaa0001-0000-0000-0000-000000000001");
  });
});
