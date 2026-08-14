/** Server-only authentication for the single local operator. */
import { createHash, timingSafeEqual } from "node:crypto";
import type { PrincipalSession } from "@/contracts/identity";

const SECRET_PATTERN = /^[A-Za-z0-9_-]{43,128}$/;
const WINDOW_MS = 60_000;
const FAILURE_LIMIT = 8;
let failures: number[] = [];

export const LOCAL_OPERATOR_UUID = "24abf5d2-d0c2-5e1c-82f6-e72425e9ed37";
export const LOCAL_OPERATOR_PRINCIPAL_ID = `prn_${LOCAL_OPERATOR_UUID.replaceAll("-", "")}`;

export class MissingLocalOperatorSecretError extends Error {
  constructor() {
    super(
      "MYPA_LOCAL_OPERATOR_SECRET must be an explicitly configured 43-128 character URL-safe secret.",
    );
    this.name = "MissingLocalOperatorSecretError";
  }
}

export type LocalOperatorAuthentication = "authenticated" | "denied" | "rate_limited";

function digest(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest();
}

/**
 * Authenticate one submitted secret without allowing failed attempts to lock
 * out the correct credential. The successful comparison is performed before
 * the bounded failure window is consulted.
 */
export function authenticateLocalOperator(submitted: unknown): LocalOperatorAuthentication {
  const configured = process.env.MYPA_LOCAL_OPERATOR_SECRET;
  if (!configured || !SECRET_PATTERN.test(configured)) {
    throw new MissingLocalOperatorSecretError();
  }
  const candidate = typeof submitted === "string" ? submitted : "";
  const accepted = timingSafeEqual(digest(candidate), digest(configured));
  if (accepted) {
    failures = [];
    return "authenticated";
  }
  const now = Date.now();
  failures = failures.filter((at) => now - at < WINDOW_MS);
  if (failures.length >= FAILURE_LIMIT) return "rate_limited";
  failures.push(now);
  return "denied";
}

/** The only browser-session Principal admitted in local_operator mode. */
export function localOperatorPrincipal(): PrincipalSession {
  return {
    principalId: LOCAL_OPERATOR_PRINCIPAL_ID,
    tid: "local_operator",
    oid: LOCAL_OPERATOR_UUID,
    upn: "local-operator@my-pa.invalid",
    displayName: "Local operator",
    lifecycleState: "active",
    synthetic: false,
    authenticationProvider: "local_operator",
  };
}
