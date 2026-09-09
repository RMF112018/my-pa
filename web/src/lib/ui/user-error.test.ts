import { describe, expect, it } from "vitest";
import { mapUserError } from "@/lib/ui/user-error";

describe("mapUserError", () => {
  it("maps 401 to a session-ended sentence and keeps the raw diagnostic", () => {
    const presented = mapUserError({
      status: 401,
      errorClass: "authentication",
      message: "unauthenticated",
    });
    expect(presented.kind).toBe("session_ended");
    expect(presented.message).toBe("Your session has ended. Sign in again.");
    expect(presented.action).toBe("sign_in");
    expect(presented.diagnostic).toBe("unauthenticated");
    expect(presented.message).not.toMatch(/empty|nothing here|you have none/i);
  });

  it("maps 403 only when authorization is established", () => {
    const presented = mapUserError({
      status: 403,
      errorClass: "authorization",
      message: "denied",
    });
    expect(presented.kind).toBe("forbidden");
    expect(presented.message).toBe("You don't have access to this item.");
    expect(presented.action).toBe("none");
    expect(presented.diagnostic).toBe("denied");
  });

  it("maps 404 without claiming the record is empty", () => {
    const presented = mapUserError({ status: 404, errorClass: "not_found", message: "missing" });
    expect(presented.kind).toBe("not_found");
    expect(presented.message).toBe("This item could not be found.");
    expect(presented.message).not.toMatch(/holds nothing|you have none|empty record/i);
    expect(presented.diagnostic).toBe("missing");
  });

  it("maps 409 as a conflict to refresh, not as emptiness", () => {
    const presented = mapUserError({
      status: 409,
      errorClass: "conflict",
      message: "version mismatch",
    });
    expect(presented.kind).toBe("conflict");
    expect(presented.message).toBe("This was changed elsewhere. Refresh and try again.");
    expect(presented.action).toBe("retry");
    expect(presented.diagnostic).toBe("version mismatch");
  });

  it("maps offline separately from unavailable", () => {
    const presented = mapUserError({ offline: true, message: "failed to fetch" });
    expect(presented.kind).toBe("offline");
    expect(presented.message).toBe("You appear to be offline.");
    expect(presented.action).toBe("retry");
    expect(presented.diagnostic).toBe("failed to fetch");
  });

  it("maps unavailable without rewriting it as empty", () => {
    const presented = mapUserError({
      status: 503,
      errorClass: "unavailable",
      message: "the application gateway did not answer",
    });
    expect(presented.kind).toBe("unavailable");
    expect(presented.message).toBe("This could not be read. Try again.");
    expect(presented.diagnostic).toBe("the application gateway did not answer");
    expect(presented.message).not.toMatch(/empty|holds nothing|you have none/i);
  });

  it("maps session authority unavailable to a verify-session sentence", () => {
    const presented = mapUserError({
      status: 503,
      errorClass: "unavailable",
      code: "authority_unavailable",
      message: "session authority unavailable",
    });
    expect(presented.kind).toBe("session_unverified");
    expect(presented.message).toBe("We couldn't verify your session.");
    expect(presented.diagnostic).toBe("session authority unavailable");
  });
});
