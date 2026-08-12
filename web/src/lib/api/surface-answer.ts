/**
 * One place that decides which of the four answers a surface is holding.
 *
 * Server-only, and deliberately a single function rather than four `if`s copied
 * into each page. The decision it encodes is the one `INV-PKL-007` governs and
 * the one this tier has the most ways to get wrong:
 *
 * * **`unavailable` is decided before anything is counted.** A refused or
 *   unreachable gateway is `unavailable`, and so is a *successful* response
 *   whose own disclosure says `coverage: "unavailable"` — the backend answered,
 *   and what it answered was "this scope was not searched". Counting its
 *   (necessarily empty) rows and calling the surface empty is precisely the
 *   substitution the invariant forbids, so the count is not even consulted on
 *   that path.
 * * **`degraded` is the backend's own word**, read off `coverage: "partial"`,
 *   which `backendDisclosure` derives from `partial_result`, a partial coverage
 *   state, or truncation. It is never inferred from how few rows arrived.
 * * **`empty` requires a whole, successful answer that carried no rows.** It is
 *   the only one of the four that asserts anything about the Principal's record,
 *   which is why it is the last branch and the most conditioned one.
 * * **`records`** is everything else.
 *
 * The row count is supplied by the caller because only the caller knows the
 * shape of its own payload. It is a `number`, not a `boolean`, so a caller
 * cannot pass "looks empty to me" in place of a measurement.
 *
 * **Server-only by transitivity.** It imports `lib/api/gateway`, which refuses
 * to run anywhere a browser could reach; no separate guard is added here, for
 * the same reason there is no second copy of the decision below.
 */
import { backendDisclosure, transportLimitations, type GatewayOutcome } from "@/lib/api/gateway";
import type { DisclosureEnvelope, ErrorEnvelope } from "@/contracts/envelope";

/** What a surface is holding, once the gateway has answered. */
export type SurfaceAnswer<T> =
  | {
      readonly kind: "records";
      readonly result: T;
      readonly disclosure: DisclosureEnvelope;
    }
  | {
      readonly kind: "degraded";
      readonly result: T;
      readonly rowCount: number;
      readonly disclosure: DisclosureEnvelope;
    }
  | {
      readonly kind: "empty";
      readonly disclosure: DisclosureEnvelope;
    }
  | {
      readonly kind: "unavailable";
      readonly error: ErrorEnvelope;
      readonly disclosure: DisclosureEnvelope;
    };

/**
 * The disclosure a failed read carries.
 *
 * `coverage: "unavailable"` and the failure's own message as the limitation, so
 * that a reader of the disclosure alone reaches the same conclusion as a reader
 * of the rendered page. Never `complete`, and never carrying a freshness moment,
 * because nothing was observed.
 */
function failureDisclosure(scope: string, message: string): DisclosureEnvelope {
  return {
    scope,
    coverage: "unavailable",
    freshnessAt: null,
    authority: "derived",
    limitations: [message, ...transportLimitations()],
    truncated: false,
  };
}

/**
 * Classify one gateway outcome into exactly one of the four answers.
 *
 * @param scope the surface's own name, carried into the disclosure.
 * @param outcome what `callGateway` returned.
 * @param countRows how many records the payload actually carried. Consulted
 *   only after `unavailable` and `degraded` have been ruled out.
 */
export function surfaceAnswer<T>(
  scope: string,
  outcome: GatewayOutcome<T>,
  countRows: (result: T) => number,
): SurfaceAnswer<T> {
  if (!outcome.ok) {
    return {
      kind: "unavailable",
      error: outcome.error,
      disclosure: failureDisclosure(scope, outcome.error.message),
    };
  }

  const disclosure = backendDisclosure(scope, outcome.disclosure, transportLimitations());

  // The backend answered that it could not search. Not an empty record, and
  // the row count is deliberately not reached.
  if (disclosure.coverage === "unavailable") {
    return {
      kind: "unavailable",
      error: {
        errorClass: "unavailable",
        code: "coverage_unavailable",
        message:
          "The backend answered, and reported that this scope was not searched. " +
          "No conclusion about what you hold follows from it.",
      },
      disclosure,
    };
  }

  if (disclosure.coverage === "partial") {
    return { kind: "degraded", result: outcome.result, rowCount: countRows(outcome.result), disclosure };
  }

  if (countRows(outcome.result) === 0) return { kind: "empty", disclosure };

  return { kind: "records", result: outcome.result, disclosure };
}
