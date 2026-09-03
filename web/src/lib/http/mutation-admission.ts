import { NextResponse } from "next/server";

import { isSameOrigin } from "@/lib/http/origin";

const CROSS_SITE_REFUSAL = {
  error: {
    errorClass: "authorization",
    code: "cross_site_request",
    message: "this endpoint refuses cross-site requests",
  },
} as const;

/** `null` means admitted. Origin only — never reads the body. */
export function admitBrowserMutation(request: Request): Response | null {
  if (isSameOrigin(request)) return null;
  const response = NextResponse.json(CROSS_SITE_REFUSAL, { status: 403 });
  response.headers.set("cache-control", "private, no-store");
  return response;
}
