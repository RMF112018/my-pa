// @vitest-environment node
/**
 * C01: new browser-authored text is normalized **once**, by the existing
 * `trim()` behaviour at the browser/BFF boundary, before key ownership and
 * hashing are frozen. No Unicode normalization, case folding, newline rewrite,
 * fuzzy comparison or truncation is introduced.
 *
 * An independent review found this clause unguarded at the two sites that
 * matter: the `/api/capture` accepted text and the text the offline codec
 * seals. A first version of this file only exercised `contentSha256`, which
 * `receipt.test.ts` already guarded — so it caught neither escape and added no
 * detection. This version drives the route and the codec themselves.
 *
 * Why it matters: if either site normalized, the backend would persist and hash
 * normalized bytes while `verifyCaptureReceipt` hashes the frozen unnormalized
 * text. Every capture containing a composed character would return
 * `digest_mismatch` — permanently ambiguous online, and on replay never
 * deletable, stalling at the five-failure bound — with the suite green.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";

import type { PrincipalSession } from "@/contracts/identity";

/**
 * "é" as one composed code point (U+00E9), and as "e" plus a combining acute
 * (U+0065 U+0301). They render identically, compare unequal, and NFC/NFD
 * convert between them — which is exactly what must not happen here.
 */
const COMPOSED = "café notes";
const DECOMPOSED = "café notes";

const {
  requirePrincipal,
  readCleanBody,
  invokeGateway,
  resolveServing,
  backendDisclosure,
  transportLimitations,
  gatewayRefusal,
  admitBrowserMutation,
  captureAdmissions,
  syntheticDisclosure,
} = vi.hoisted(() => ({
  requirePrincipal: vi.fn(),
  readCleanBody: vi.fn(),
  invokeGateway: vi.fn(),
  resolveServing: vi.fn(),
  backendDisclosure: vi.fn(() => ({ coverage: "complete" })),
  transportLimitations: vi.fn(() => []),
  gatewayRefusal: vi.fn((_scope: string, status: number, error: unknown) =>
    NextResponse.json({ error }, { status }),
  ),
  admitBrowserMutation: vi.fn((): NextResponse | null => null),
  captureAdmissions: { admit: vi.fn() },
  syntheticDisclosure: vi.fn(() => ({ coverage: "synthetic" })),
}));

vi.mock("@/lib/api/guard", () => ({ requirePrincipal, readCleanBody }));
vi.mock("@/lib/api/gateway", () => ({ invokeGateway, backendDisclosure, transportLimitations }));
vi.mock("@/lib/api/serving", () => ({ resolveServing, gatewayRefusal }));
vi.mock("@/lib/http/mutation-admission", () => ({ admitBrowserMutation }));
vi.mock("@/lib/capture/idempotency", () => ({ captureAdmissions }));
vi.mock("@/lib/fixtures/pulse", () => ({ syntheticDisclosure }));

import { POST } from "@/app/api/capture/route";
import { contentSha256 } from "./receipt";
import {
  decodeCaptureIntentV2,
  encodeCaptureIntentV2,
} from "@/lib/offline/capture-intent-codec";

const PRINCIPAL = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "synthetic:aaaa0001",
  tid: "tenant",
  oid: "object",
  upn: "operator@example.invalid",
  displayName: "Operator",
  lifecycleState: "active",
  synthetic: true,
} satisfies PrincipalSession;

const KEY = "idem-normalize-0001";

async function send(body: Record<string, unknown>) {
  readCleanBody.mockResolvedValue({ ok: true, body });
  return POST(
    new NextRequest("http://localhost:3000/api/capture", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "http://localhost:3000" },
      body: JSON.stringify(body),
    }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  admitBrowserMutation.mockReturnValue(null);
  requirePrincipal.mockResolvedValue({ ok: true, principal: PRINCIPAL });
  resolveServing.mockReturnValue({ kind: "backend" });
  backendDisclosure.mockReturnValue({ coverage: "complete" });
  transportLimitations.mockReturnValue([]);
  gatewayRefusal.mockImplementation((_scope: string, status: number, error: unknown) =>
    NextResponse.json({ error }, { status }),
  );
});

describe("C01 — the BFF forwards the exact bytes it was given", () => {
  it("sends the composed text to the gateway without normalizing it", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: {
        receipt_id: "rcpt_aaaaaaaa11111111",
        capture_id: "cap_aaaaaaaa11111111",
        version_id: "capver_aaaaaaaa11111111",
        version_number: 1,
        idempotency_key: KEY,
        content_sha256: await contentSha256(COMPOSED),
        project_id: null,
        issued_at: "2026-09-23T12:00:00Z",
        created: true,
      },
      disclosure: {},
    });

    await send({ text: COMPOSED, idempotencyKey: KEY, captureKind: "quick_note" });

    // The payload the route actually handed the gateway. Any normalization at
    // the route — NFC or NFD — moves these bytes and fails here.
    const payload = invokeGateway.mock.calls[0]![2] as { text: string };
    expect(payload.text).toBe(COMPOSED);
    expect(payload.text).not.toBe(DECOMPOSED);
    expect([...payload.text]).toHaveLength([...COMPOSED].length);
  });

  it("still trims, because trim is the one permitted normalization", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: {
        receipt_id: "rcpt_aaaaaaaa11111111",
        capture_id: "cap_aaaaaaaa11111111",
        version_id: "capver_aaaaaaaa11111111",
        version_number: 1,
        idempotency_key: KEY,
        content_sha256: await contentSha256(COMPOSED),
        project_id: null,
        issued_at: "2026-09-23T12:00:00Z",
        created: true,
      },
      disclosure: {},
    });

    // Surrounding whitespace goes; interior spacing and code points do not.
    await send({ text: `  ${COMPOSED}  `, idempotencyKey: KEY, captureKind: "quick_note" });

    const payload = invokeGateway.mock.calls[0]![2] as { text: string };
    expect(payload.text).toBe(COMPOSED);
  });
});

describe("C01 — the offline codec seals the exact bytes it was given", () => {
  it("round-trips composed text without normalizing it", async () => {
    const intent = {
      entryId: "entry-normalize-0001",
      principalId: PRINCIPAL.principalId,
      idempotencyKey: KEY,
      captureKind: "quick_note" as const,
      queuedAt: 1_700_000_000_000,
      text: COMPOSED,
      projectId: null,
    };

    // `decodeCaptureIntentV2` takes the sealed bytes plus the immutable envelope
    // it must agree with, so the envelope is passed back in unchanged.
    const decoded = decodeCaptureIntentV2(encodeCaptureIntentV2(intent), {
      entryId: intent.entryId,
      principalId: intent.principalId,
      idempotencyKey: intent.idempotencyKey,
      captureKind: intent.captureKind,
      queuedAt: intent.queuedAt,
    });

    expect(decoded.text).toBe(COMPOSED);
    expect(decoded.text).not.toBe(DECOMPOSED);
    expect([...decoded.text]).toHaveLength([...COMPOSED].length);
  });
});

describe("C01 — the digest itself distinguishes the two forms", () => {
  it("treats composed and decomposed text as different content", async () => {
    expect(COMPOSED).not.toBe(DECOMPOSED);
    expect(COMPOSED.normalize("NFD")).toBe(DECOMPOSED);

    // Pinned digests, computed independently of this implementation:
    //   python3 -c "import hashlib; print(hashlib.sha256('café notes'.encode()).hexdigest())"
    expect(await contentSha256(COMPOSED)).toBe(
      "a39134b0215692786a3506400b52c5a1c527119159747b22c9e04bbd8b8a8c36",
    );
    expect(await contentSha256(DECOMPOSED)).toBe(
      "baa900a03be0ed28fe50aac7a26cd7574e1e3cae7463fb1f5d6135063697cf5e",
    );
  });

  it("does not case-fold", async () => {
    expect(await contentSha256("Note")).not.toBe(await contentSha256("note"));
  });

  it("does not rewrite newlines", async () => {
    expect(await contentSha256("a\r\nb")).not.toBe(await contentSha256("a\nb"));
  });
});
