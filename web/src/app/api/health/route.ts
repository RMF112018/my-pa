/**
 * Unauthenticated liveness — process is up and the auth mode is a usable web
 * value. No Principal, no database, no paths, no env echo.
 *
 * Live JSON is only `{ ok: true, status: "live" }`, and only when `NODE_ENV`
 * is a known Node environment and `MYPA_AUTH_MODE` is `synthetic` or `passkey`
 * (with `synthetic` refused in production). Anything else is 503
 * `{ error: { code: "misconfigured" } }` with no secret, stack, or configured
 * value in the body.
 */
import { NextResponse, type NextRequest } from "next/server";
import { authMode } from "@/lib/auth/mode";

const NO_STORE = { "Cache-Control": "no-store" } as const;

const NODE_ENVS = new Set(["development", "production", "test"]);

function nodeEnvParses(): boolean {
  const configured = process.env.NODE_ENV?.trim() ?? "";
  return NODE_ENVS.has(configured);
}

function live(): boolean {
  if (!nodeEnvParses()) return false;
  authMode();
  return true;
}

function misconfigured(): NextResponse {
  return NextResponse.json({ error: { code: "misconfigured" } }, { status: 503, headers: NO_STORE });
}

export async function GET(_request: NextRequest): Promise<NextResponse> {
  try {
    if (!live()) return misconfigured();
    return NextResponse.json({ ok: true, status: "live" }, { headers: NO_STORE });
  } catch {
    return misconfigured();
  }
}
