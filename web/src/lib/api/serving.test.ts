// @vitest-environment node
/**
 * What a refused gateway discloses, as opposed to what it logs.
 *
 * `gatewayRefusal` writes two things into one response: the `ErrorEnvelope`,
 * which the closed diagnostic vocabulary governs before anything is rendered
 * from it, and a `DisclosureEnvelope` whose `limitations` are the page's answer
 * to "what is missing from this answer". It used to put `error.message` into
 * the second as well — the same upstream string the vocabulary drops, arriving
 * on a channel that bypassed the drop. This pins the separation: the message
 * stays in the error, and the disclosure says what this tier can establish on
 * its own, which for a read that did not happen is the whole of the scope.
 */
import { describe, expect, it } from "vitest";
import { gatewayRefusal } from "./serving";
import { WEB_LIMITATIONS } from "@/lib/diagnostics/safe-detail";
import type { ErrorEnvelope } from "@/contracts/envelope";

const UNREACHABLE: ErrorEnvelope = {
  errorClass: "unavailable",
  code: "gateway_unreachable",
  message: "the application gateway did not answer",
};

describe("gatewayRefusal", () => {
  it("discloses what is missing without repeating the gateway's own sentence", async () => {
    const body = (await gatewayRefusal("pulse", 503, UNREACHABLE).json()) as {
      state: string;
      error: ErrorEnvelope;
      disclosure: { coverage: string; limitations: readonly string[] };
    };
    expect(body.state).toBe("unavailable");
    expect(body.disclosure.coverage).toBe("unavailable");
    expect(body.disclosure.limitations).toEqual([WEB_LIMITATIONS.nothingInScopeWasRead]);
    expect(body.disclosure.limitations).not.toContain(UNREACHABLE.message);
    // The envelope itself is untouched: this is a change to what is disclosed,
    // not to what is classified.
    expect(body.error).toEqual(UNREACHABLE);
  });
});
