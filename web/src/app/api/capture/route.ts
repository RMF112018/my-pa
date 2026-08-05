/**
 * Capture stub — WP-02.
 *
 * Acknowledges a capture with a synthetic receipt. The real pipeline
 * (source persistence, spans, proposals) lands in WP-03. The contract —
 * principal from session only, disclosure on every response — is pinned now.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

export async function POST(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;

  const text = parsed.body["text"];
  if (typeof text !== "string" || text.trim().length === 0) {
    return NextResponse.json(
      { error: { code: "empty_capture", message: "capture text must be non-empty" } },
      { status: 400 },
    );
  }

  return NextResponse.json({
    receiptId: `rcpt-${crypto.randomUUID()}`,
    status: "acknowledged_not_persisted",
    disclosure: syntheticDisclosure("capture"),
  });
}
