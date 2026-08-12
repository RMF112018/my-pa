/** Begin the server-side Entra authorization-code + PKCE flow. */
import { NextResponse } from "next/server";

import {
  beginEntraAuthorization,
  ENTRA_FLOW_COOKIE_NAME,
  ENTRA_FLOW_MAX_AGE_SECONDS,
} from "@/lib/auth/entra-code-flow";
import { authMode } from "@/lib/auth/mode";
import { SESSION_COOKIE_OPTIONS } from "@/lib/auth/session";

export const runtime = "nodejs";

export async function GET() {
  try {
    if (authMode() !== "entra") {
      return NextResponse.json(
        { error: { code: "entra_sign_in_disabled", message: "Entra sign-in is not enabled" } },
        { status: 404 },
      );
    }
    const started = await beginEntraAuthorization();
    const response = NextResponse.redirect(started.location);
    response.cookies.set(ENTRA_FLOW_COOKIE_NAME, started.state, {
      ...SESSION_COOKIE_OPTIONS,
      maxAge: ENTRA_FLOW_MAX_AGE_SECONDS,
    });
    return response;
  } catch {
    return NextResponse.json(
      {
        error: {
          code: "entra_sign_in_unavailable",
          message: "Entra sign-in is not configured or could not be started",
        },
      },
      { status: 503 },
    );
  }
}
