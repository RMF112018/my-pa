/**
 * Envelope XOR: exactly one of `disclosure` or `error`.
 *
 * A bare `ProblemDetail` (top-level `code` string, no envelope) remains a
 * supported second response shape. Extra unknown envelope keys are ignored.
 */
import { decodeDisclosure, type DecodedDisclosure } from "./disclosure";
import { decodeProblem, type DecodedProblem } from "./problem";
import {
  closed,
  ignoreUnknownKeys,
  isRecord,
  isString,
  ok,
  type DecodeResult,
} from "./primitives";

export type EnvelopeSuccess = {
  readonly kind: "success";
  readonly result: unknown;
  readonly disclosure: DecodedDisclosure;
  readonly correlationId?: string;
};

export type EnvelopeProblem = {
  readonly kind: "problem";
  readonly problem: DecodedProblem;
};

export type DecodedEnvelope = EnvelopeSuccess | EnvelopeProblem;

const ENVELOPE_KEYS = ["result", "disclosure", "error", "code", "correlation_id"] as const;

const INVALID = "upstream_contract_invalid";
const UNCONTRACTED = "gateway_response_uncontracted";

function present(value: unknown): boolean {
  return value !== undefined && value !== null;
}

function correlationOf(known: Record<string, unknown>): string | undefined {
  return isString(known.correlation_id) ? known.correlation_id : undefined;
}

function asProblem(decoded: DecodeResult<DecodedProblem>): DecodeResult<DecodedEnvelope> {
  if (!decoded.ok) return decoded;
  return ok({ kind: "problem", problem: decoded.value });
}

export function decodeEnvelope(input: unknown): DecodeResult<DecodedEnvelope> {
  if (!isRecord(input)) {
    return closed(INVALID, "the gateway answer was not a contract envelope");
  }
  const known = ignoreUnknownKeys(input, ENVELOPE_KEYS);
  const hasError = present(known.error);
  const hasDisclosure = present(known.disclosure);
  const hasResult = present(known.result);
  const hasBareCode = isString(known.code);

  // Bare ProblemDetail: top-level `code`, no envelope error/disclosure.
  if (hasBareCode && !hasError && !hasDisclosure) {
    return asProblem(decodeProblem(input));
  }
  if (hasBareCode && (hasError || hasDisclosure)) {
    return closed(INVALID, "the gateway answer mixed a problem with an envelope");
  }

  if (hasError === hasDisclosure) {
    if (!hasError && !hasDisclosure && hasResult) {
      return closed(
        UNCONTRACTED,
        "the gateway answered without the mandatory disclosure envelope",
      );
    }
    return closed(INVALID, "the gateway answer did not separate success from error");
  }

  if (hasError) {
    if (hasResult) {
      return closed(INVALID, "the gateway answer mixed a result with an error");
    }
    return asProblem(decodeProblem(known.error));
  }

  if (!hasResult) {
    return closed(INVALID, "the gateway success omitted its result");
  }

  const disclosure = decodeDisclosure(known.disclosure);
  if (!disclosure.ok) return disclosure;
  const correlationId = correlationOf(known);
  return ok({
    kind: "success" as const,
    result: known.result,
    disclosure: disclosure.value,
    ...(correlationId ? { correlationId } : {}),
  });
}
