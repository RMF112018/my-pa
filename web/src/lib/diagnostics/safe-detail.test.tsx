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
import {
  BACKEND_LIMITATIONS,
  describeSafeDiagnostic,
  isSafeDiagnostic,
  safeDiagnostic,
} from "@/lib/diagnostics/safe-detail";

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
 *
 * **Why `privateKey` is written as two fragments.** The repository-wide guard
 * `tests/architecture/test_scope_and_hygiene.py::test_repository_has_no_high_confidence_secret_signature`
 * scans every file under `web/` for `-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----`,
 * and it splits its own literals at exactly that seam so as not to match
 * itself. This file does the same. The assembled value is byte-identical to the
 * single literal it replaces — "assembles each split sentinel from fragments"
 * below pins it — so the sentinel's strength is unchanged. Do not tidy it back
 * into one string; that re-breaks CI.
 */
const SENTINELS = {
  session: "sid=S3SSION-9f2b41c7d05e4a18b6c37e90aa5d1f44",
  bearer:
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ZmFrZS1wYXlsb2FkLW5vdC1hLXRva2Vu.c2lnbmF0dXJlLWlzLW1hZGUtdXA",
  privateKey:
    "-----BEGIN " + "PRIVATE KEY-----MIIEvQIBADANBgkqhkiG9w0BAQEFAASC-----END PRIVATE KEY-----",
  stack:
    "TypeError: cannot read properties of undefined\n    at Object.<anonymous> (/srv/app/lib/reader.js:41:17)",
  connection: "postgresql://mypa_app:Tr0ub4dor-3x@db.internal.invalid:5432/mypa?sslmode=require",
} as const;

const ALL_SENTINELS = Object.values(SENTINELS);

/**
 * AWS's own documentation example access key id, assembled from two fragments.
 *
 * Never issued, grants nothing, and is here only because it is the canonical
 * credential-*shaped* value. Split at the seam for the same reason as
 * `SENTINELS.privateKey` above: the repository-wide secret-signature guard
 * scans this file for `A(?:KI|SI)A[0-9A-Z]{16}`. Rejoining the halves into one
 * token breaks CI.
 */
const FORGED_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE";

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

describe("the split sentinels are byte-identical to the literals they replace", () => {
  // Two sentinels are assembled from fragments so the repository-wide
  // secret-signature guard does not match this file's source. The split must
  // cost nothing: if an edit shortened or mangled a fragment, the sentinel
  // would stop being the shape it is meant to test and every leak assertion
  // below would pass for the wrong reason. Pin both assembled values exactly.
  it("assembles each split sentinel from fragments", () => {
    expect(SENTINELS.privateKey).toHaveLength(84);
    expect(SENTINELS.privateKey.slice(0, 11)).toBe("-----BEGIN ");
    expect(SENTINELS.privateKey.slice(11)).toBe(
      "PRIVATE KEY-----MIIEvQIBADANBgkqhkiG9w0BAQEFAASC-----END PRIVATE KEY-----",
    );

    expect(FORGED_AWS_KEY).toHaveLength(20);
    expect(FORGED_AWS_KEY.slice(0, 4)).toBe("AKIA");
    expect(FORGED_AWS_KEY.slice(4)).toBe("IOSFODNN7EXAMPLE");
  });
});

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
   * The allowlist's exact boundary, pinned so it cannot drift silently.
   *
   * These replace the run-length assertions this block used to carry. That rule
   * governed limitations on the premise that they are free prose; the backend
   * publishes a closed `Limitation` StrEnum of unbroken snake_case tokens, so
   * the rule withheld eight of its thirteen. `limitation-allowlist.test.ts`
   * pins the allowlist against the Python enum itself; what is asserted here is
   * the predicate's behaviour at the surface, including the credential-shaped
   * values the old bound could not have excluded at any threshold.
   */
  describe("the limitation allowlist boundary", () => {
    const admit = (limitation: string) => {
      const governed = diagnosticLimitations(true, [limitation]);
      render(<SurfaceState kind="degraded" title="This answer is partial" limitations={governed} />);
      return !renderedBytes().includes("did not match the safe-disclosure shape");
    };

    it("keeps every token the backend vocabulary can emit, long ones included", () => {
      for (const token of BACKEND_LIMITATIONS) {
        cleanup();
        expect(admit(token), token).toBe(true);
      }
    });

    it("keeps a parameterised aggregate disclosure", () => {
      expect(admit("objects_omitted_containment_unproven:7")).toBe(true);
    });

    it("withholds prose that is merely well shaped", () => {
      cleanup();
      expect(admit("a run of aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa here")).toBe(false);
    });

    it("withholds a 32-character hex session id, which no threshold could exclude", () => {
      cleanup();
      expect(admit("0123456789abcdef0123456789abcdef")).toBe(false);
    });

    it("withholds credential-shaped values", () => {
      for (const forged of [FORGED_AWS_KEY, "sk_live_4eC39HqLyjWDarjt"]) {
        cleanup();
        expect(admit(forged), forged).toBe(false);
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

/**
 * The two ways a record that *looks* governed could still carry something.
 *
 * NB-01. Neither is reachable from the gateway today — `decodeProblem` drops
 * unknown keys and builds a fresh object — so these are hardening rather than
 * live defects. They are worth holding because both failures are invisible in
 * the DOM: the first lands in the RSC payload, the second turns the module's
 * own writer into a renderer of a function's source text.
 */
describe("a record that is merely shaped like the vocabulary", () => {
  beforeEach(() => {
    diagnosticsEnabled = true;
  });

  it("loses an extra property rather than carrying it into the payload", () => {
    // `isSafeDiagnostic` validates the eight known fields and says nothing
    // about a ninth, so returning the input verbatim would hand a ninth key to
    // the prop and from there into the Flight payload — invisible on the page,
    // visible in `view-source`. The constructor rebuilds from the validated
    // fields instead.
    const smuggled = {
      ...safeDiagnostic({ errorClass: "unavailable", code: "upstream_error", status: 503 }),
      note_detail: SENTINELS.connection,
    };
    const governed = safeDiagnostic(smuggled);
    expect(Object.hasOwn(governed, "note_detail")).toBe(false);
    expectNoSentinel("the RSC payload", payloadBytes(governed));
    // And what it should still say, it still says.
    expect(describeSafeDiagnostic(governed)).toContain("code upstream_error");
    expect(describeSafeDiagnostic(governed)).toContain("HTTP 503");
    render(<SurfaceState kind="unavailable" title="This could not be read" error={governed} />);
    expectNoSentinel("the DOM", renderedBytes());
  });

  it("rejects a field borrowed from Object.prototype", () => {
    // `in` walks the prototype chain, so `kind: "constructor"` and `note:
    // "toString"` passed the membership tests and then made
    // `describeSafeDiagnostic` index a function off the record map.
    const real = safeDiagnostic({ errorClass: "unavailable", code: "upstream_error" });
    for (const forged of [
      { ...real, kind: "constructor" },
      { ...real, kind: "toString" },
      { ...real, reason: "valueOf" },
      { ...real, note: "toString" },
      { ...real, note: "hasOwnProperty" },
    ]) {
      expect(isSafeDiagnostic(forged), JSON.stringify(forged)).toBe(false);
    }
  });

  it("never renders a function's source text for one", () => {
    const real = safeDiagnostic({ errorClass: "unavailable", code: "upstream_error" });
    for (const forged of [{ ...real, kind: "constructor" }, { ...real, note: "toString" }]) {
      cleanup();
      const governed = safeDiagnostic(forged);
      render(<SurfaceState kind="unavailable" title="This could not be read" error={governed} />);
      const bytes = renderedBytes();
      expect(bytes).not.toContain("native code");
      expect(bytes).not.toContain("function");
    }
  });
});
