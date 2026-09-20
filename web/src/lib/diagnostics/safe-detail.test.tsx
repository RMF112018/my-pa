/**
 * WP08-RT-F010 — fabricated secrets, pushed into every diagnostic channel.
 *
 * The WP07 policy decides *whether* engineering detail renders. These tests are
 * about *what* it may contain. Each sentinel below is a made-up value in the
 * shape of a real credential — never a real one — and each is pushed into a
 * channel that a backend string can genuinely arrive on. The assertion is the
 * same every time: it must not be in the DOM, not in the accessibility tree,
 * and not in what a server component would serialise into the RSC payload,
 * with diagnostics on *or* off.
 *
 * **Why the payload leg is asserted separately.** A client gate can only hide
 * text that already shipped. `SurfaceState` renders client components, so a
 * server component that hands it a prop has that prop serialised into the
 * Flight payload inside the HTML before any client code runs — the DOM is clean
 * and the bytes are not. There is no Flight renderer in this package, so the
 * proxy here is the JSON serialisation of the value the prop is given, which is
 * what Flight walks. It is a proxy, and it catches exactly the class of leak
 * the DOM assertions cannot see: a poisoned `code` or `correlationId` that
 * `mapUserError` would never have chosen for its display string but that still
 * travels in the object.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

let diagnosticsEnabled = false;

vi.mock("@/components/diagnostics/diagnostics-provider", () => ({
  useDiagnosticsEnabled: () => diagnosticsEnabled,
  WhenDiagnostics: ({ children }: { children?: unknown }) =>
    (diagnosticsEnabled ? children : null) as never,
}));

import { SurfaceState, DegradedBanner } from "@/components/ui/surface-state";
import {
  diagnosticError,
  diagnosticLimitations,
  diagnosticText,
} from "@/lib/diagnostics/presentation";

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  diagnosticsEnabled = false;
});

/**
 * Fabricated. None of these is a credential, and none was ever issued.
 *
 * They are shaped like the five things most likely to arrive in an upstream
 * error string: a session identifier, a bearer token, a private key, a raw
 * exception, and a connection string carrying its own password.
 */
const SENTINELS = {
  session: "sid=S3SSION-9f2b41c7d05e4a18b6c37e90aa5d1f44",
  bearer:
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ZmFrZS1wYXlsb2FkLW5vdC1hLXRva2Vu.c2lnbmF0dXJlLWlzLW1hZGUtdXA",
  privateKey: "-----BEGIN PRIVATE KEY-----MIIEvQIBADANBgkqhkiG9w0BAQEFAASC-----END PRIVATE KEY-----",
  stack:
    "TypeError: cannot read properties of undefined\n    at Object.<anonymous> (/srv/app/lib/reader.js:41:17)",
  connection: "postgresql://mypa_app:Tr0ub4dor-3x@db.internal.invalid:5432/mypa?sslmode=require",
} as const;

const ALL_SENTINELS = Object.values(SENTINELS);

/** Everything a reader or a screen reader could reach, plus every attribute. */
function renderedBytes(): string {
  return document.body.innerHTML;
}

/** What Flight would walk when a server component hands this value to a prop. */
function payloadBytes(value: unknown): string {
  return JSON.stringify(value) ?? "";
}

function expectNoSentinel(where: string, bytes: string): void {
  for (const sentinel of ALL_SENTINELS) {
    if (bytes.includes(sentinel)) {
      throw new Error(`${where} carried the fabricated sentinel: ${sentinel.slice(0, 48)}…`);
    }
  }
  // The distinctive fragments, in case a channel re-encodes or truncates.
  for (const fragment of ["S3SSION-", "eyJhbGciOiJIUzI1NiI", "BEGIN PRIVATE KEY", "Tr0ub4dor", "/srv/app/lib/reader.js"]) {
    expect(bytes, `${where} carried ${fragment}`).not.toContain(fragment);
  }
}

/** Both modes, every time. A pass in one mode only is not a pass. */
const MODES: ReadonlyArray<readonly [string, boolean]> = [
  ["diagnostics off", false],
  ["diagnostics on", true],
];

describe("no fabricated secret reaches a rendered diagnostic", () => {
  for (const [modeName, mode] of MODES) {
    describe(modeName, () => {
      beforeEach(() => {
        diagnosticsEnabled = mode;
      });

      it("drops a poisoned error.message", () => {
        for (const sentinel of ALL_SENTINELS) {
          const governed = diagnosticError(mode, {
            errorClass: "unavailable",
            code: "upstream_error",
            message: sentinel,
          });
          const { unmount } = render(
            <SurfaceState kind="unavailable" title="This could not be read" error={governed} />,
          );
          expectNoSentinel("the DOM", renderedBytes());
          expectNoSentinel("the RSC payload", payloadBytes(governed));
          unmount();
        }
      });

      it("drops a poisoned error.code", () => {
        for (const sentinel of ALL_SENTINELS) {
          const governed = diagnosticError(mode, {
            errorClass: "unavailable",
            code: sentinel,
            message: "the gateway refused the request",
          });
          const { unmount } = render(
            <SurfaceState kind="unavailable" title="This could not be read" error={governed} />,
          );
          expectNoSentinel("the DOM", renderedBytes());
          expectNoSentinel("the RSC payload", payloadBytes(governed));
          unmount();
        }
      });

      it("drops a poisoned error.correlationId", () => {
        for (const sentinel of ALL_SENTINELS) {
          const governed = diagnosticError(mode, {
            errorClass: "unavailable",
            code: "upstream_error",
            message: "the gateway refused the request",
            correlationId: sentinel,
          });
          const { unmount } = render(
            <SurfaceState kind="unavailable" title="This could not be read" error={governed} />,
          );
          expectNoSentinel("the DOM", renderedBytes());
          expectNoSentinel("the RSC payload", payloadBytes(governed));
          unmount();
        }
      });

      it("never carries the principal-derived correlation id, well-formed or not", () => {
        const governed = diagnosticError(mode, {
          errorClass: "unavailable",
          code: "upstream_error",
          message: "the gateway refused the request",
          correlationId: "prn_0123456789abcdef0123456789abcdef",
        });
        const { unmount } = render(
          <SurfaceState kind="unavailable" title="This could not be read" error={governed} />,
        );
        expect(renderedBytes()).not.toContain("prn_0123456789abcdef");
        expect(payloadBytes(governed)).not.toContain("prn_0123456789abcdef");
        unmount();
      });

      it("drops a poisoned explicit diagnostic prop", () => {
        for (const sentinel of ALL_SENTINELS) {
          const governed = diagnosticText(mode, sentinel);
          const { unmount } = render(
            <SurfaceState kind="unavailable" title="This could not be read" diagnostic={governed} />,
          );
          expectNoSentinel("the DOM", renderedBytes());
          expectNoSentinel("the RSC payload", payloadBytes(governed));
          unmount();
        }
      });

      it("drops a poisoned unavailableDiagnostic", () => {
        // The People panels' prop: the owning page governs it, then hands it on.
        for (const sentinel of ALL_SENTINELS) {
          const governed = diagnosticText(mode, {
            errorClass: "unavailable",
            code: "gateway_unreachable",
            message: sentinel,
          });
          const { unmount } = render(
            <SurfaceState
              kind="unavailable"
              title="Assignments could not be read"
              error={diagnosticError(mode, governed)}
            />,
          );
          expectNoSentinel("the DOM", renderedBytes());
          expectNoSentinel("the RSC payload", payloadBytes(governed));
          unmount();
        }
      });

      it("withholds a poisoned limitation from the state card", () => {
        for (const sentinel of ALL_SENTINELS) {
          const governed = diagnosticLimitations(mode, [
            "Two mailboxes were not reachable.",
            sentinel,
          ]);
          const { unmount } = render(
            <SurfaceState kind="degraded" title="This answer is partial" limitations={governed} />,
          );
          expectNoSentinel("the DOM", renderedBytes());
          expectNoSentinel("the RSC payload", payloadBytes(governed));
          unmount();
        }
      });

      it("withholds a poisoned limitation from the degraded banner", () => {
        for (const sentinel of ALL_SENTINELS) {
          const governed = diagnosticLimitations(mode, [sentinel]);
          const { unmount } = render(<DegradedBanner scope="this board" limitations={governed} />);
          expectNoSentinel("the DOM", renderedBytes());
          expectNoSentinel("the RSC payload", payloadBytes(governed));
          unmount();
        }
      });
    });
  }
});

describe("what survives is still worth reading", () => {
  beforeEach(() => {
    diagnosticsEnabled = true;
  });

  it("still names the class, the code and the status", () => {
    const governed = diagnosticError(true, {
      errorClass: "unavailable",
      code: "upstream_contract_invalid",
      message: "the gateway result did not match the capability contract",
      status: 503,
    });
    render(<SurfaceState kind="unavailable" title="This could not be read" error={governed} />);
    const text = renderedBytes();
    expect(text).toContain("unavailable");
    expect(text).toContain("upstream_contract_invalid");
    expect(text).toContain("503");
  });

  it("says a code was withheld rather than showing it or going silent", () => {
    const governed = diagnosticError(true, {
      errorClass: "unavailable",
      code: SENTINELS.session,
      message: "the gateway refused the request",
    });
    render(<SurfaceState kind="unavailable" title="This could not be read" error={governed} />);
    expect(renderedBytes()).toContain("does not recognise");
  });

  it("says a limitation was withheld rather than dropping it silently", () => {
    const governed = diagnosticLimitations(true, [SENTINELS.connection]);
    render(<SurfaceState kind="degraded" title="This answer is partial" limitations={governed} />);
    expect(renderedBytes()).toContain("did not match the safe-disclosure shape");
  });

  it("keeps a genuine backend limitation exactly as the backend wrote it", () => {
    const governed = diagnosticLimitations(true, [
      "The gateway runs in local_operator mode: results belong to the deployment's single " +
        "local-operator principal and are not partitioned by browser session.",
    ]);
    render(<SurfaceState kind="degraded" title="This answer is partial" limitations={governed} />);
    expect(renderedBytes()).toContain("local-operator principal");
  });

  /**
   * The run-length rule's exact boundary, pinned so it cannot drift silently.
   *
   * These assert what the predicate *does*, which is not the same as what would
   * be safe: a 32-character run is admitted, and that includes a 32-character
   * hex session id. `safe-detail.ts` records why the bound is not lowered — the
   * backend's limitation vocabulary is unbroken snake_case tokens, several of
   * them longer than this — and that narrowing it is a product-disclosure
   * decision for the owning work package, not a threshold tweak here.
   */
  describe("the limitation run-length boundary", () => {
    const admit = (limitation: string) => {
      const governed = diagnosticLimitations(true, [limitation]);
      render(<SurfaceState kind="degraded" title="This answer is partial" limitations={governed} />);
      return !renderedBytes().includes("did not match the safe-disclosure shape");
    };

    it("admits a run of exactly 32 characters", () => {
      expect(admit(`a run of ${"a".repeat(32)} here`)).toBe(true);
    });

    it("withholds a run of 33 characters", () => {
      expect(admit(`a run of ${"a".repeat(33)} here`)).toBe(false);
    });

    it("admits a 32-character hex session id, which the bound does not exclude", () => {
      expect(admit("the session 0123456789abcdef0123456789abcdef was used")).toBe(true);
    });

    it("keeps every limitation the backend vocabulary can emit that fits the bound", () => {
      for (const token of [
        "content_truncated_at_fetch_limit",
        "result_label_is_media_type_only",
        "evidence_scope_was_not_searched",
        "no_extracted_text_in_scope",
        "scope_not_fully_extracted",
      ]) {
        cleanup();
        expect(admit(token), token).toBe(true);
      }
    });
  });

  it("acknowledges a correlation id without printing it", () => {
    const governed = diagnosticError(true, {
      errorClass: "unavailable",
      code: "upstream_error",
      message: "the gateway refused the request",
      correlationId: "prn_0123456789abcdef0123456789abcdef",
    });
    render(<SurfaceState kind="unavailable" title="This could not be read" error={governed} />);
    expect(renderedBytes()).toContain("server log");
  });
});
