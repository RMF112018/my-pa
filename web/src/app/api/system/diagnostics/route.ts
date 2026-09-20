/**
 * `POST /api/system/diagnostics` — the only way diagnostic visibility changes.
 *
 * There is exactly one control in the product and exactly one write behind it.
 * No `GET` here mutates anything, no query parameter is read, and no other
 * route sets `my-pa-diagnostics`; a second writer would be a second policy for
 * a preference whose whole point is that it has one.
 *
 * **The gate order is the repository's order, and body parsing is last.**
 *
 * 1. `admitBrowserMutation` — same-origin only, decided from `Origin` and
 *    `Sec-Fetch-Site` alone, and it never reads the body. A cross-site caller
 *    is refused before this route has looked at anything it sent.
 * 2. `requirePrincipal` — the acting Principal comes from the opaque session
 *    SID, never from the payload. Dead or missing session is `401`; a session
 *    authority that cannot answer is `503`, not `401`.
 * 3. `readCleanBody` — JSON object or `400`, and a body carrying identity
 *    fields is refused outright rather than ignored.
 * 4. Only then, the closed vocabulary below.
 *
 * **The body vocabulary is one key.** `enabled` must be a real boolean; `"true"`
 * is not one. Any other key is a `400` rather than a silent ignore, so a caller
 * that thinks it is setting something is told that it is not. There is no
 * principal, no version override and no scope field to disagree with the
 * session — the Principal is fixed by the cookie and the version is ours.
 *
 * **What the response means.** A `200` means this server produced the
 * `Set-Cookie`. It is deliberately not described to the browser as "saved":
 * whether the browser kept it is a fact about the browser, and the client
 * re-reads server-resolved state rather than trusting this status line. This
 * route therefore returns the state it wrote and nothing else — no echo of the
 * request, no diagnostic detail, and `private, no-store` so no shared cache can
 * ever hand one Principal's preference to another.
 */
import { NextResponse, type NextRequest } from "next/server";

import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";
import {
  DIAGNOSTICS_COOKIE,
  diagnosticsPrincipalBinding,
  nextDiagnosticsGeneration,
  parseDiagnosticsPreference,
  serializeDiagnosticsPreference,
} from "@/lib/diagnostics/preference";

/** The complete accepted body vocabulary. Every other key is refused. */
const ALLOWED_FIELDS = new Set(["enabled"]);

function refuse(code: string, message: string, status: number): NextResponse {
  const response = NextResponse.json({ error: { code, message } }, { status });
  response.headers.set("cache-control", "private, no-store");
  return response;
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const blocked = admitBrowserMutation(request);
  if (blocked) return blocked as NextResponse;

  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const unknown = Object.keys(body).filter((key) => !ALLOWED_FIELDS.has(key));
  if (unknown.length > 0) {
    // The message names *our* vocabulary, never the caller's keys. Echoing the
    // rejected names would make an authenticated endpoint an unbounded
    // reflection channel for caller-controlled text, which buys nothing: a
    // client that sent the wrong field can read the contract.
    return refuse("unsupported_field", "only 'enabled' is accepted", 400);
  }

  const enabled = body["enabled"];
  if (typeof enabled !== "boolean") {
    return refuse("bad_request", "'enabled' must be a boolean", 400);
  }

  let binding: string;
  try {
    binding = await diagnosticsPrincipalBinding(guard.principal.principalId);
  } catch {
    return refuse("authority_unavailable", "preference authority unavailable", 503);
  }

  // Every accepted write advances the generation, so a client can order this
  // answer against a cached payload it may still be holding and refuse to be
  // moved backwards by one.
  const current = parseDiagnosticsPreference(
    request.cookies.get(DIAGNOSTICS_COOKIE)?.value,
    binding,
  );
  const generation = nextDiagnosticsGeneration(current.generation);

  const response = NextResponse.json({ enabled, generation });
  response.headers.set("cache-control", "private, no-store");
  response.headers.append(
    "set-cookie",
    serializeDiagnosticsPreference(enabled, binding, {
      secure: process.env.NODE_ENV === "production",
      generation,
    }),
  );
  return response;
}
