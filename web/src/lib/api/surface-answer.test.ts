// @vitest-environment node
/**
 * `surfaceAnswer` is the one classification INV-PKL-007 trusts. These tests
 * pin the decision order, not the page chrome: unavailable is decided before
 * any row is counted, coverage unavailable is not empty, partial is degraded
 * even at zero rows, and empty is only a complete answer that carried none.
 */
import { describe, expect, it } from "vitest";
import { surfaceAnswer } from "./surface-answer";
import type { GatewayOutcome, PythonDisclosure } from "@/lib/api/gateway";

type Rows = { readonly rows: readonly string[] };

const SCOPE = "synthetic-surface";

const COMPLETE: PythonDisclosure = {
  coverage: { state: "processed" },
  freshness: { observed_at: "2026-08-20T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_bound_derived", basis: ["report_artifact"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

function ok(result: Rows, disclosure: PythonDisclosure = COMPLETE): GatewayOutcome<Rows> {
  return { ok: true, result, disclosure };
}

function refused(): GatewayOutcome<Rows> {
  return {
    ok: false,
    status: 503,
    error: {
      errorClass: "unavailable",
      code: "gateway_unreachable",
      message: "the application gateway did not answer",
    },
  };
}

function counting(onCount?: () => void): (result: Rows) => number {
  return (result) => {
    onCount?.();
    return result.rows.length;
  };
}

describe("surfaceAnswer", () => {
  it("decides unavailable before anything is counted when the gateway refused", () => {
    let counted = 0;
    const answer = surfaceAnswer(SCOPE, refused(), counting(() => {
      counted += 1;
    }));
    expect(counted).toBe(0);
    expect(answer.kind).toBe("unavailable");
    if (answer.kind === "unavailable") {
      expect(answer.error.code).toBe("gateway_unreachable");
      expect(answer.disclosure.coverage).toBe("unavailable");
      expect(answer.disclosure.freshnessAt).toBeNull();
    }
  });

  it("decides unavailable before the count when coverage itself is unavailable", () => {
    let counted = 0;
    const answer = surfaceAnswer(
      SCOPE,
      ok({ rows: ["syn-row-1", "syn-row-2"] }, { ...COMPLETE, coverage: { state: "unavailable" } }),
      counting(() => {
        counted += 1;
      }),
    );
    expect(counted).toBe(0);
    expect(answer.kind).toBe("unavailable");
    if (answer.kind === "unavailable") {
      expect(answer.error.code).toBe("coverage_unavailable");
      expect(answer.disclosure.coverage).toBe("unavailable");
    }
  });

  it("does not treat coverage unavailable as empty, even at zero rows", () => {
    const answer = surfaceAnswer(
      SCOPE,
      ok({ rows: [] }, { ...COMPLETE, coverage: { state: "unavailable" } }),
      counting(),
    );
    expect(answer.kind).not.toBe("empty");
    expect(answer.kind).toBe("unavailable");
  });

  it("classifies partial coverage as degraded even when zero rows arrived", () => {
    const viaFlag = surfaceAnswer(
      SCOPE,
      ok({ rows: [] }, { ...COMPLETE, partial_result: true }),
      counting(),
    );
    expect(viaFlag.kind).toBe("degraded");
    if (viaFlag.kind === "degraded") {
      expect(viaFlag.rowCount).toBe(0);
      expect(viaFlag.disclosure.coverage).toBe("partial");
    }

    const viaState = surfaceAnswer(
      SCOPE,
      ok({ rows: [] }, { ...COMPLETE, coverage: { state: "partially_processed" } }),
      counting(),
    );
    expect(viaState.kind).toBe("degraded");

    const viaTruncation = surfaceAnswer(
      SCOPE,
      ok({ rows: [] }, { ...COMPLETE, truncation: { is_truncated: true } }),
      counting(),
    );
    expect(viaTruncation.kind).toBe("degraded");
  });

  it("classifies empty only for a complete answer that carried zero rows", () => {
    const answer = surfaceAnswer(SCOPE, ok({ rows: [] }), counting());
    expect(answer.kind).toBe("empty");
    if (answer.kind === "empty") {
      expect(answer.disclosure.coverage).toBe("complete");
    }
  });

  it("classifies records when a complete answer carried rows", () => {
    const result = { rows: ["syn-row-1"] };
    const answer = surfaceAnswer(SCOPE, ok(result), counting());
    expect(answer.kind).toBe("records");
    if (answer.kind === "records") {
      expect(answer.result).toEqual(result);
      expect(answer.disclosure.coverage).toBe("complete");
    }
  });

  it("keeps a partial answer with rows as degraded, not records", () => {
    const answer = surfaceAnswer(
      SCOPE,
      ok({ rows: ["syn-row-1"] }, { ...COMPLETE, partial_result: true }),
      counting(),
    );
    expect(answer.kind).toBe("degraded");
    if (answer.kind === "degraded") {
      expect(answer.rowCount).toBe(1);
      expect(answer.result.rows).toEqual(["syn-row-1"]);
    }
  });
});
