/**
 * The one diagnostics visibility preference, and the only thing that may parse it.
 *
 * **Why a first-party HttpOnly cookie and not localStorage.** The contract says
 * OFF must be indistinguishable from an application in which diagnostics were
 * never added — including in server-rendered markup. That is only decidable if
 * the *server* can read the preference before it renders anything, which rules
 * out `localStorage` on its own: the server cannot see it, so the page would
 * have to render diagnostics and strip them at hydration, which is the exact
 * anti-pattern the contract names. `HttpOnly` means page script can neither
 * read nor write the value; the only way this application changes it is a
 * `Set-Cookie` from `POST /api/system/diagnostics`, which is authenticated and
 * same-origin. There is therefore no *script* authority that could act as a
 * second, untrusted source of ON.
 *
 * **What that does not cover, stated rather than implied.** `HttpOnly` bounds
 * script, not the cookie jar. This cookie is not `__Host-` prefixed, so a
 * related origin able to set a `Domain=` cookie could write a well-formed value
 * for a Principal whose id it knows — and that id is not a secret, since the
 * product displays it. The blast radius is small and one-directional: the parser
 * still requires the binding to recompute from *this* request's Principal, so no
 * cross-Principal read is possible, and the only achievable effect is turning a
 * victim's own diagnostics on, which grants presentation and nothing else.
 * `__Host-` would close it and costs nothing structurally — `Path=/`, no
 * `Domain`, and `Secure` already hold in production — but `__Host-` also
 * *requires* `Secure`, which this build deliberately omits on `http://localhost`
 * so the development and browser-test stack works. Making the cookie name differ
 * between environments is a change to the trust core; it is recorded as a
 * follow-up rather than made unreviewed at the end of this work package.
 *
 * This follows the shape already landed for Project Scope in
 * `lib/project-scope/preference.ts`: a named first-party cookie, a parser that
 * accepts only values this application wrote, and a serializer used by a
 * server-owned endpoint. It introduces no secret, no key, no schema and no
 * migration — trust is the existing session boundary plus `HttpOnly`.
 *
 * **Why the value is bound to the Principal.** A cookie belongs to a browser,
 * not to a person. A bare `on` would survive a sign-out and be honoured for
 * whoever signed in next, which is precisely the cross-Principal leak the
 * contract forbids. So the stored value carries a one-way binding derived from
 * the acting Principal, and `parseDiagnosticsPreference` resolves ON only when
 * that binding recomputes from the Principal established for *this* request.
 * A value written for someone else does not parse, and an unparseable value is
 * OFF. This is the same one-way-digest idea as `sessionReplayBinding`; like
 * that one it is a binding, not a credential, and it authenticates nothing.
 *
 * **Every refusal resolves OFF.** Absent, empty, malformed, wrong version,
 * oversized, wrong segment count, foreign binding, or an unrecognised state
 * token all return `false`. There is no "unknown" and no third state to leak
 * through: the function returns a boolean and its failure direction is OFF.
 */

/** The single first-party cookie. Nothing else may carry this preference. */
export const DIAGNOSTICS_COOKIE = "my-pa-diagnostics";

/** Contract version. A value that does not carry exactly this token is refused. */
export const DIAGNOSTICS_PREFERENCE_VERSION = "v1";

const BINDING_PREFIX = "my-pa:diagnostics-preference:v1:";
const ON = "on";
const OFF = "off";
const SEPARATOR = ".";

/**
 * The value carries a monotonic generation as its fourth segment.
 *
 * Without one, "the server says ON" and "the server said ON a while ago" are
 * the same statement to the client, and a cached RSC payload rendered before an
 * accepted OFF could put diagnostics back. The counter is incremented by the
 * one route on every accepted write, so a payload can be *ordered* against what
 * this browser has already applied and a superseded one is ignored rather than
 * obeyed. It is a sequence number, not a clock: it reveals nothing and is
 * meaningless outside this cookie.
 */
const MAX_GENERATION = Number.MAX_SAFE_INTEGER;
const GENERATION_PATTERN = /^[0-9a-z]{1,11}$/;

/**
 * Hard ceiling on the value we will even look at.
 *
 * `v1` + `.` + 64 hex + `.` + `off` is 71 characters. 96 leaves room for the
 * version token to grow without leaving an oversized value unbounded: anything
 * longer was not written by this application and is refused before any parsing
 * work happens.
 */
const MAX_VALUE_LENGTH = 96;

const BINDING_PATTERN = /^[0-9a-f]{64}$/;

const YEAR_IN_SECONDS = 31536000;

/**
 * One-way binding for a Principal. SHA-256 over a namespaced prefix.
 *
 * Not a credential and not an authenticator: it never proves who the caller is,
 * and on its own it grants nothing. It exists so that a preference written for
 * one Principal cannot be honoured for another on the same browser.
 */
export async function diagnosticsPrincipalBinding(principalId: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`${BINDING_PREFIX}${principalId}`) as BufferSource,
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * Resolve the stored value for one exact Principal binding. Fail-closed.
 *
 * No trimming, no case folding, no URI decoding, no legacy aliases and no
 * partial matches — a value that is not exactly what this module writes carries
 * no authority, and carrying no authority means OFF.
 */
export interface ResolvedDiagnosticsPreference {
  readonly enabled: boolean;
  /** Ordering only. `0` means "nothing trustworthy was stored". */
  readonly generation: number;
}

/** What every untrusted state resolves to. */
export const DIAGNOSTICS_OFF: ResolvedDiagnosticsPreference = { enabled: false, generation: 0 };

export function parseDiagnosticsPreference(
  value: string | undefined | null,
  expectedBinding: string,
): ResolvedDiagnosticsPreference {
  if (typeof value !== "string") return DIAGNOSTICS_OFF;
  if (value.length === 0 || value.length > MAX_VALUE_LENGTH) return DIAGNOSTICS_OFF;
  if (!BINDING_PATTERN.test(expectedBinding)) return DIAGNOSTICS_OFF;

  const segments = value.split(SEPARATOR);
  if (segments.length !== 4) return DIAGNOSTICS_OFF;

  const [version, binding, state, rawGeneration] = segments;
  if (version !== DIAGNOSTICS_PREFERENCE_VERSION) return DIAGNOSTICS_OFF;
  if (!BINDING_PATTERN.test(binding)) return DIAGNOSTICS_OFF;
  if (binding !== expectedBinding) return DIAGNOSTICS_OFF;
  if (!GENERATION_PATTERN.test(rawGeneration)) return DIAGNOSTICS_OFF;

  const generation = Number.parseInt(rawGeneration, 36);
  if (!Number.isSafeInteger(generation) || generation < 1) return DIAGNOSTICS_OFF;

  // Only `on` turns diagnostics on. `off` and every unrecognised token are OFF,
  // so a future or corrupted state token can never fail open. A well-formed
  // OFF still carries its generation, because ordering an OFF matters too.
  return { enabled: state === ON, generation };
}

/** The next generation after whatever is currently stored. */
export function nextDiagnosticsGeneration(current: number): number {
  return current >= MAX_GENERATION ? MAX_GENERATION : current + 1;
}

/** The exact value this application writes. */
export function diagnosticsPreferenceValue(
  enabled: boolean,
  binding: string,
  generation = 1,
): string {
  return [
    DIAGNOSTICS_PREFERENCE_VERSION,
    binding,
    enabled ? ON : OFF,
    generation.toString(36),
  ].join(SEPARATOR);
}

/**
 * Strict first-party `Set-Cookie` for the server-owned preference endpoint.
 *
 * `HttpOnly` is what keeps page script from forging ON; `SameSite=Lax` and the
 * route's own same-origin admission are what keep another site from writing it.
 */
export function serializeDiagnosticsPreference(
  enabled: boolean,
  binding: string,
  { secure = true, generation = 1 }: { secure?: boolean; generation?: number } = {},
): string {
  return [
    `${DIAGNOSTICS_COOKIE}=${diagnosticsPreferenceValue(enabled, binding, generation)}`,
    "Path=/",
    `Max-Age=${YEAR_IN_SECONDS}`,
    "HttpOnly",
    "SameSite=Lax",
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}

/**
 * `Set-Cookie` that removes the preference outright.
 *
 * Used on sign-out. Binding alone already prevents another Principal from
 * inheriting ON, but leaving a stale value on the browser is state we have no
 * reason to keep, so sign-out clears it as well.
 */
export function clearDiagnosticsPreference({ secure = true }: { secure?: boolean } = {}): string {
  return [
    `${DIAGNOSTICS_COOKIE}=`,
    "Path=/",
    "Max-Age=0",
    "HttpOnly",
    "SameSite=Lax",
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}
