/**
 * Enforcing browser security headers for the Next response.
 *
 * Production HTML from `next build` (`web/.next/server/app/index.html` and the
 * matching standalone copy) emits two inline scripts with empty attributes —
 * `(self.__next_f=self.__next_f||[]).push([0])` and a follow-up
 * `self.__next_f.push([1, ...])` — and no `nonce=` on those tags (RSC payload
 * has `"nonce":"$undefined"`). There is no per-request nonce mechanism this
 * helper can wire without new dependencies, so `script-src` includes
 * `'unsafe-inline'`. First-party production chunks and `public/sw.js` contain
 * no `eval(` / `new Function`, so `'unsafe-eval'` is omitted.
 *
 * HSTS is ingress/WP-29, not Next: emitting it here would attach to localhost
 * HTTP. CORS stays closed: no `Access-Control-Allow-Origin`.
 */

export type BrowserSecurityHeader = { key: string; value: string };

const PRODUCTION_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "connect-src 'self'",
  "worker-src 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
].join("; ");

const PERMISSIONS_POLICY = [
  "camera=()",
  "microphone=()",
  "geolocation=()",
  "payment=()",
  "usb=()",
  "magnetometer=()",
  "gyroscope=()",
  "accelerometer=()",
  "browsing-topics=()",
  "interest-cohort=()",
  "publickey-credentials-get=(self)",
  "publickey-credentials-create=(self)",
].join(", ");

/** Production browser headers. Next `headers()` must emit this set. */
export function browserSecurityHeaders(): BrowserSecurityHeader[] {
  return [
    { key: "Content-Security-Policy", value: PRODUCTION_CSP },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: PERMISSIONS_POLICY },
  ];
}
