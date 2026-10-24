// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import type { PrincipalSession } from "@/contracts/identity";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";

const {
  requirePrincipal,
  invokeGateway,
  resolveServing,
  backendDisclosure,
  transportLimitations,
  gatewayRefusal,
} = vi.hoisted(() => ({
  requirePrincipal: vi.fn(),
  invokeGateway: vi.fn(),
  resolveServing: vi.fn(),
  backendDisclosure: vi.fn(() => ({ coverage: "complete" })),
  transportLimitations: vi.fn(() => []),
  gatewayRefusal: vi.fn((_scope, status, error) =>
    Response.json({ state: "unavailable", error }, { status }),
  ),
}));

vi.mock("@/lib/api/guard", () => ({ requirePrincipal }));
vi.mock("@/lib/api/gateway", () => ({ invokeGateway, backendDisclosure, transportLimitations }));
vi.mock("@/lib/api/serving", () => ({ resolveServing, gatewayRefusal }));

import { GET } from "./[meetingId]/notes/[noteVersionId]/route";

const PRINCIPAL = {
  principalId: "aaaaaaaa-1111-1111-1111-111111111111",
  identityProvider: "synthetic",
  identitySubject: "synthetic:aaaaaaaa",
  tid: "tenant",
  oid: "object",
  upn: "operator@example.invalid",
  displayName: "Operator",
  lifecycleState: "active",
  synthetic: true,
} satisfies PrincipalSession;

const MEETING_ID = "mtg_aaaaaaaa11111111";
const NOTE_VERSION_ID = "mnote_aaaaaaaa11111111";
const NOTE = fixtures["meetings.notes.read_version"];

async function read(query: string, meetingId = MEETING_ID, noteVersionId = NOTE_VERSION_ID) {
  const request = new NextRequest(`http://localhost:3000/api/meetings/${meetingId}/notes/${noteVersionId}${query}`);
  return GET(request, { params: Promise.resolve({ meetingId, noteVersionId }) });
}

beforeEach(() => {
  vi.resetAllMocks();
  requirePrincipal.mockResolvedValue({ ok: true, principal: PRINCIPAL });
  resolveServing.mockReturnValue({ kind: "backend" });
  backendDisclosure.mockReturnValue({ coverage: "complete" });
  transportLimitations.mockReturnValue([]);
  gatewayRefusal.mockImplementation((_scope, status, error) => Response.json({ state: "unavailable", error }, { status }));
});

describe("GET /api/meetings/[meetingId]/notes/[noteVersionId]", () => {
  it("calls meetings.notes.read_version only with an explicit includeBody", async () => {
    for (const query of ["", "?includeBody=1", "?includeBody=yes", "?include_body=true", "?includeBody=true&includeBody=true", "?includeBody=true&extra=1"]) {
      const response = await read(query);
      expect(response.status, query || "(none)").toBe(400);
    }
    for (const [meetingId, noteVersionId] of [["mtg_short", NOTE_VERSION_ID], [MEETING_ID, "capver_aaaaaaaa11111111"]] as const) {
      expect((await read("?includeBody=true", meetingId, noteVersionId)).status).toBe(400);
    }
    expect(invokeGateway).not.toHaveBeenCalled();

    invokeGateway.mockResolvedValue({ ok: true, result: NOTE, disclosure: {} });
    const response = await read("?includeBody=true");
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(invokeGateway).toHaveBeenCalledOnce();
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "meetings.notes.read_version", {
      include_body: true,
      meeting_id: MEETING_ID,
      note_version_id: NOTE_VERSION_ID,
    });
    expect((await response.json()).note).toEqual(NOTE.note);

    // A body the request did not ask for is refused rather than relayed.
    invokeGateway.mockClear();
    const unasked = await read("?includeBody=false");
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "meetings.notes.read_version", {
      include_body: false,
      meeting_id: MEETING_ID,
      note_version_id: NOTE_VERSION_ID,
    });
    expect(unasked.status).toBe(503);
  });
});
