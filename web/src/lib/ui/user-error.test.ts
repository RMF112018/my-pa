/**
 * WP08-RT-F010. The product language below is unchanged — every `title`,
 * `message` and `action` assertion is exactly the one that was here before, and
 * that is the point: only the diagnostic leg moved. What changed is that
 * `diagnostic` is no longer the raw upstream string. Each case now asserts that
 * the free-text `message` is *absent* from the closed record and from its
 * rendered text, and that the class, code and status that were genuinely safe
 * survive.
 */
import { describe, expect, it } from "vitest";
import { mapUserError } from "@/lib/ui/user-error";
import { describeSafeDiagnostic } from "@/lib/diagnostics/safe-detail";

describe("mapUserError", () => {
  it("maps 401 to a session-ended sentence and withholds the raw diagnostic", () => {
    const presented = mapUserError({
      status: 401,
      errorClass: "authentication",
      message: "unauthenticated",
    });
    expect(presented.kind).toBe("session_ended");
    expect(presented.message).toBe("Your session has ended. Sign in again.");
    expect(presented.action).toBe("sign_in");
    expect(presented.diagnostic.errorClass).toBe("authentication");
    expect(presented.diagnostic.status).toBe(401);
    expect(describeSafeDiagnostic(presented.diagnostic)).not.toContain("unauthenticated");
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
    expect(presented.diagnostic.errorClass).toBe("authorization");
    expect(presented.diagnostic.status).toBe(403);
    expect(describeSafeDiagnostic(presented.diagnostic)).not.toContain("denied");
  });

  it("maps 404 without claiming the record is empty", () => {
    const presented = mapUserError({ status: 404, errorClass: "not_found", message: "missing" });
    expect(presented.kind).toBe("not_found");
    expect(presented.message).toBe("This item could not be found.");
    expect(presented.message).not.toMatch(/holds nothing|you have none|empty record/i);
    expect(presented.diagnostic.errorClass).toBe("not_found");
    expect(describeSafeDiagnostic(presented.diagnostic)).not.toContain("missing");
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
    expect(presented.diagnostic.errorClass).toBe("conflict");
    expect(describeSafeDiagnostic(presented.diagnostic)).not.toContain("version mismatch");
  });

  it("maps offline separately from unavailable", () => {
    const presented = mapUserError({ offline: true, message: "failed to fetch" });
    expect(presented.kind).toBe("offline");
    expect(presented.message).toBe("You appear to be offline.");
    expect(presented.action).toBe("retry");
    expect(presented.diagnostic.reason).toBe("network_unreachable");
    expect(describeSafeDiagnostic(presented.diagnostic)).not.toContain("failed to fetch");
  });

  it("maps unavailable without rewriting it as empty", () => {
    const presented = mapUserError({
      status: 503,
      errorClass: "unavailable",
      message: "the application gateway did not answer",
    });
    expect(presented.kind).toBe("unavailable");
    expect(presented.message).toBe("This could not be read. Try again.");
    expect(presented.diagnostic.errorClass).toBe("unavailable");
    expect(presented.diagnostic.status).toBe(503);
    expect(describeSafeDiagnostic(presented.diagnostic)).not.toContain("gateway did not answer");
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
    expect(presented.diagnostic.code).toBe("authority_unavailable");
    expect(presented.diagnostic.reason).toBe("session_authority_unavailable");
    expect(describeSafeDiagnostic(presented.diagnostic)).not.toContain(
      "session authority unavailable",
    );
  });
});

describe("the closed vocabulary is the only thing that renders", () => {
  it("never renders an upstream message, however it arrived", () => {
    for (const input of [
      "a raw caught string",
      new Error("a raw exception message"),
      { message: "a raw envelope message" },
      { errorClass: "internal", code: "internal_error", message: "a raw envelope message" },
    ]) {
      const rendered = describeSafeDiagnostic(mapUserError(input).diagnostic);
      expect(rendered).not.toMatch(/raw (caught string|exception message|envelope message)/);
    }
  });

  it("replaces a code it does not recognise rather than printing it", () => {
    const presented = mapUserError({ errorClass: "unavailable", code: "sid=deadbeef" });
    expect(presented.diagnostic.code).toBe("unrecognised_code");
    expect(describeSafeDiagnostic(presented.diagnostic)).not.toContain("deadbeef");
  });

  it("acknowledges a correlation id without carrying it", () => {
    const presented = mapUserError({
      errorClass: "unavailable",
      code: "upstream_error",
      message: "x",
      correlationId: "prn_0123456789abcdef0123456789abcdef",
    });
    expect(presented.diagnostic.correlated).toBe(true);
    expect(JSON.stringify(presented.diagnostic)).not.toContain("prn_");
  });
});
