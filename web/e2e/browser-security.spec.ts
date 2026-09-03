import { expect, test } from "@playwright/test";
import { LIVE_URL } from "../playwright.config";
import { signIn, syntheticNote } from "./fixtures";

const OPAQUE_SID = /^[0-9a-f]{64}$/;
const ATTACKER_ORIGIN = "https://attacker.example";

type CaptureEnvelope = {
  created?: boolean;
  status?: string;
  receiptId?: string;
  error?: { code?: string; errorClass?: string };
};

async function sessionSid(page: import("@playwright/test").Page, origin: string): Promise<string> {
  const cookies = await page.context().cookies(origin);
  const cookie = cookies.find((entry) => entry.name === "mypa_session");
  expect(cookie, "signed-in context must carry mypa_session").toBeDefined();
  expect(cookie!.httpOnly).toBe(true);
  expect(cookie!.value).toMatch(OPAQUE_SID);
  return cookie!.value;
}

async function nodeCapturePost(options: {
  cookie: string;
  body: { text: string; idempotencyKey: string };
  origin?: string;
}): Promise<{ status: number; body: CaptureEnvelope }> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    cookie: `mypa_session=${options.cookie}`,
  };
  if (options.origin !== undefined) {
    headers.origin = options.origin;
  }
  const response = await fetch(`${LIVE_URL}/api/capture`, {
    method: "POST",
    headers,
    body: JSON.stringify(options.body),
  });
  return { status: response.status, body: (await response.json()) as CaptureEnvelope };
}

async function inPageCapture(
  page: import("@playwright/test").Page,
  body: { text: string; idempotencyKey: string },
): Promise<{ status: number; body: CaptureEnvelope }> {
  return page.evaluate(async (payload) => {
    const response = await fetch("/api/capture", {
      method: "POST",
      cache: "no-store",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    return { status: response.status, body: (await response.json()) as CaptureEnvelope };
  }, body);
}

function expectCrossSiteRefusal(status: number, body: CaptureEnvelope): void {
  expect(status, "cross-site Capture must be 403").toBe(403);
  expect(body.error?.code).toBe("cross_site_request");
  if (body.error?.errorClass !== undefined) {
    expect(body.error.errorClass).toBe("authorization");
  }
}

test.describe("browser mutation admission", () => {
  test("cross-origin Capture POST is 403 and does not mutate", async ({ page, playwright }) => {
    await signIn(page);
    const sid = await sessionSid(page, LIVE_URL);
    const idempotencyKey = crypto.randomUUID();
    const text = syntheticNote(`wp05-cross-${idempotencyKey}`);

    const attacker = await playwright.request.newContext({
      extraHTTPHeaders: {
        origin: ATTACKER_ORIGIN,
        cookie: `mypa_session=${sid}`,
      },
    });
    try {
      const refused = await attacker.post(`${LIVE_URL}/api/capture`, {
        data: { text, idempotencyKey },
      });
      expectCrossSiteRefusal(refused.status(), (await refused.json()) as CaptureEnvelope);
    } finally {
      await attacker.dispose();
    }

    const replay = await inPageCapture(page, { text, idempotencyKey });
    expect(replay.status, "same-origin retry with the unused key must succeed").toBe(200);
    expect(replay.body.created, "the 403 must not have consumed the idempotency key").toBe(true);
  });

  test("same-origin authenticated Capture still works", async ({ page }) => {
    await signIn(page);
    const idempotencyKey = crypto.randomUUID();
    const created = await inPageCapture(page, {
      text: syntheticNote(`wp05-same-${idempotencyKey}`),
      idempotencyKey,
    });
    expect(created.status, "same-origin Capture must not be 403").not.toBe(403);
    expect(created.status, "persisted or synthetic Capture receipt is 200").toBe(200);
    expect(created.body.created).toBe(true);
  });

  test("missing Origin Capture POST is 403", async ({ page }) => {
    await signIn(page);
    const sid = await sessionSid(page, LIVE_URL);
    const refused = await nodeCapturePost({
      cookie: sid,
      body: {
        text: syntheticNote(`wp05-missing-${crypto.randomUUID()}`),
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expectCrossSiteRefusal(refused.status, refused.body);
  });

  test("cross-origin Work PATCH is 403", async ({ page }) => {
    await signIn(page);
    const sid = await sessionSid(page, LIVE_URL);
    const response = await fetch(`${LIVE_URL}/api/tasks/tsk_e2e_wp05_not_a_real_task`, {
      method: "PATCH",
      headers: {
        "content-type": "application/json",
        origin: ATTACKER_ORIGIN,
        cookie: `mypa_session=${sid}`,
      },
      body: JSON.stringify({
        title: syntheticNote("wp05-work-patch"),
        expectedVersion: 1,
        idempotencyKey: crypto.randomUUID(),
      }),
    });
    expectCrossSiteRefusal(response.status, (await response.json()) as CaptureEnvelope);
  });
});
