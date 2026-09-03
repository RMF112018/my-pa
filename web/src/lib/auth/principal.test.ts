import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthorityUnavailableError, resolveSessionPrincipal } from "@/lib/auth/principal";
import { callSessionService } from "@/lib/auth/session-service";

vi.mock("@/lib/auth/session-service", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth/session-service")>();
  return {
    ...actual,
    callSessionService: vi.fn(),
  };
});

const SID = "ab".repeat(32);
const mockedCall = vi.mocked(callSessionService);

beforeEach(() => {
  mockedCall.mockReset();
});

describe("resolveSessionPrincipal", () => {
  it("maps a synthetic principal and leaves non-synthetic provider unset", async () => {
    mockedCall.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          principal: {
            principalId: "p1",
            tid: "t1",
            oid: "o1",
            upn: "a@example",
            displayName: "A",
            lifecycleState: "active",
            synthetic: true,
          },
        }),
        { status: 200 },
      ),
    );
    await expect(resolveSessionPrincipal(SID)).resolves.toMatchObject({
      authenticationProvider: "synthetic",
    });

    mockedCall.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          principal: {
            principalId: "p2",
            tid: "t2",
            oid: "o2",
            upn: "b@example",
            displayName: "B",
            lifecycleState: "active",
            synthetic: false,
          },
        }),
        { status: 200 },
      ),
    );
    const passkey = await resolveSessionPrincipal(SID);
    expect(passkey?.synthetic).toBe(false);
    expect(passkey?.authenticationProvider).toBeUndefined();
  });

  it("throws AuthorityUnavailableError when fetch fails", async () => {
    mockedCall.mockRejectedValueOnce(new Error("gateway down"));
    await expect(resolveSessionPrincipal(SID)).rejects.toBeInstanceOf(AuthorityUnavailableError);
  });
});
