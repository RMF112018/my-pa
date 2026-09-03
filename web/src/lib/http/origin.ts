/**
 * Cross-site request refusal for state-changing routes.
 *
 * The session cookie is `sameSite: "lax"`, which stops a cross-site *form* POST
 * from carrying it but is not a general CSRF defence — and sign-out is exactly
 * the request an attacker gains something from forging. So the two
 * state-changing session routes check where the request came from, and fail
 * closed when they cannot tell.
 *
 * Two signals, and the stricter one wins:
 *
 * * `Sec-Fetch-Site` is the browser's own statement about the relationship
 *   between the initiator and the target. `same-site` and `cross-site` are
 *   refused — `same-site` covers a sibling subdomain, which is not this origin.
 *   `same-origin` and `none` may still reject; they never voucher a request
 *   that omitted `Origin`.
 * * `Origin` is compared to the trusted origin. Production uses
 *   `canonicalOrigin()` (`MYPA_CANONICAL_ORIGIN`); Host and `X-Forwarded-Host`
 *   never establish this trust boundary. Outside production the trusted origin
 *   is `new URL(request.url).origin`.
 *
 * A request that omits `Origin` is refused. That is the fail-closed direction
 * and it costs nothing real: every browser that can run this application sends
 * `Origin` on a same-origin `fetch` with a method other than GET, and the app's
 * own sign-in page uses `fetch`. A non-browser client that wants this route can
 * send an `Origin` header, which is a deliberate act rather than an accident.
 */

/** `true` when this request is safe to treat as same-origin. */
import { canonicalOrigin } from "@/lib/http/canonical-origin";

export function isSameOrigin(request: Request): boolean {
  const fetchSite = request.headers.get("sec-fetch-site");
  if (fetchSite !== null && fetchSite !== "same-origin" && fetchSite !== "none") return false;

  const origin = request.headers.get("origin");
  if (origin !== null) {
    try {
      const trustedOrigin =
        process.env.NODE_ENV === "production" ? canonicalOrigin() : new URL(request.url).origin;
      return new URL(origin).origin === trustedOrigin;
    } catch {
      return false;
    }
  }
  return false;
}
