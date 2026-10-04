/**
 * Explicit WP03B package proof; invoke this file by name on the frozen head.
 * Browser fetches below reach the shipped BFF, canonical Python gateway and an
 * isolated synthetic database. Backend-only calls create synthetic fixtures or
 * arrange Capture lifecycle; they are not browser admissions. The Task mutation
 * presentation test alone intercepts transport, and is labeled accordingly. No
 * new Project/Meeting/Document authoring UI is claimed by these API admissions.
 */
import { expect, test, type Page } from "@playwright/test";
import { DEAD_GATEWAY_URL } from "../playwright.config";
import { EMPTINESS_CLAIMS, expectState, signIn } from "./fixtures";

type Body = Record<string, unknown>;
type Answer = { status: number; body: Body; cacheControl: string | null };
type Meeting = { meeting_id: string; version: number; title: string };
type Disclosure = { coverage: string; truncated: boolean; nextCursor?: string; limitations: string[] };

// Synthetic sessions must never enter trace/video artifacts.
test.use({ trace: "off", video: "off", screenshot: "off" });

function key(): string { return `wp03b-${crypto.randomUUID()}`; }

async function api(page: Page, path: string, method = "GET", body?: Body): Promise<Answer> {
  return page.evaluate(async ({ path, method, body }) => {
    const response = await fetch(path, {
      method, cache: "no-store",
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { status: response.status, body: await response.json() as Body,
      cacheControl: response.headers.get("cache-control") };
  }, { path, method, body });
}

/** Canonical fixture arrangement, exclusively at the owned loopback gateway. */
async function arrange(capability: string, payload: Body): Promise<Body> {
  const origin = process.env.MYPA_E2E_GATEWAY_URL ?? "http://127.0.0.1:9099";
  const url = new URL(origin);
  expect(url.hostname).toBe("127.0.0.1");
  expect(url.protocol).toBe("http:");
  const response = await fetch(`${origin}/v1/${capability}`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ contract_version: "v1", request_id: `req_${crypto.randomUUID().replaceAll("-", "")}`,
      purpose: capability.startsWith("meetings.") ? "meeting_authoring" : capability.startsWith("documents.") ? "document_authoring" : "capture_authoring",
      // Canonical local_principal() correlation identity; gateway authentication
      // remains the fixed synthetic local-operator context, not this field.
      principal_id: "prn_24abf5d2d0c25e1c82f6e72425e9ed37",
      requested_at: new Date().toISOString(), payload }),
  });
  expect(response.status, capability).toBe(200);
  const envelope = await response.json() as { result: Body | null; error: unknown };
  expect(envelope.error, capability).toBeNull();
  expect(envelope.result, capability).not.toBeNull();
  return envelope.result!;
}

function success(answer: Answer): Body {
  expect(answer.status).toBe(200);
  expect(answer.body.shape).toBe("backend");
  expect(answer.body.error).toBeUndefined();
  expect(answer.cacheControl).toContain("private");
  expect(answer.cacheControl).toContain("no-store");
  return answer.body;
}

function refused(answer: Answer, status: number, errorClass: string): void {
  expect(answer.status).toBe(status);
  expect(answer.body.error).toMatchObject({ errorClass });
  expect(answer.body.shape).toBeUndefined();
  expect(answer.body.created).toBeUndefined();
  expect(answer.cacheControl).toContain("no-store");
  const serialized = JSON.stringify(answer.body);
  expect(serialized).not.toMatch(/safe_details|request_digest|CaptureWithdrawnError|capture_withdrawn/);
}

test("real synthetic stack: authenticated success for all twelve admissions, conflicts and page disclosure", async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page);
  const project = success(await api(page, "/api/projects", "POST", {
    name: "WP03B synthetic Project", idempotencyKey: key(),
  }));
  const projectId = project.project_id as string;
  expect(project.version).toBe(1);
  const update = { name: "WP03B synthetic Project updated", expectedVersion: 1, idempotencyKey: key() };
  const updated = success(await api(page, `/api/projects/${projectId}`, "PATCH", update));
  expect(updated.version).toBe(2);
  expect(success(await api(page, `/api/projects/${projectId}`, "PATCH", update)).replayed).toBe(true);
  refused(await api(page, `/api/projects/${projectId}`, "PATCH", {
    ...update, idempotencyKey: key(),
  }), 409, "conflict");
  expect(success(await api(page, `/api/projects/${projectId}/close`, "POST", {
    expectedVersion: 2, idempotencyKey: key(),
  })).state).toBe("closed");

  const capture = await api(page, "/api/capture", "POST", { text: "WP03B synthetic original", idempotencyKey: key() });
  expect(capture.status).toBe(200);
  const captureId = (capture.body.receipt as { captureId: string }).captureId;
  expect(captureId).toMatch(/^cap_/);
  const revised = success(await api(page, `/api/capture/${captureId}`, "PATCH", {
    text: "WP03B synthetic successor", idempotencyKey: key(), occurredAt: "2026-10-04T12:00:00Z",
  }));
  expect(revised.version_number).toBe(2);
  expect(revised.idempotency_key).toBeUndefined();

  const marker = key();
  const seeded = await arrange("meetings.create", {
    title: marker, start_at: "2026-10-04T12:00:00Z", timezone_name: "UTC",
    series_title: "WP03B synthetic series", idempotency_key: key(),
  });
  const meeting = seeded.meeting as Meeting & { meeting_series_id: string };
  await arrange("meetings.create", {
    title: `${marker} second`, start_at: "2026-10-05T12:00:00Z", timezone_name: "UTC", idempotency_key: key(),
  });
  expect(success(await api(page, `/api/meetings/${meeting.meeting_id}`)).meeting).toMatchObject({ title: marker, version: 1 });
  const listed = success(await api(page, "/api/meetings?pageSize=1&timeScope=all"));
  expect((listed.meetings as Meeting[])).toHaveLength(1);
  const disclosure = listed.disclosure as Disclosure;
  expect(disclosure.coverage).toBe("partial");
  expect(disclosure.truncated).toBe(true);
  expect(disclosure.nextCursor).toMatch(/^mtg_/);
  expect(disclosure.limitations).toBeInstanceOf(Array);
  const continued = success(await api(page, `/api/meetings?pageSize=1&timeScope=all&after=${disclosure.nextCursor}`));
  expect((continued.meetings as Meeting[])[0]!.meeting_id).not.toBe((listed.meetings as Meeting[])[0]!.meeting_id);
  expect((success(await api(page, `/api/meetings/search?q=${marker}&timeScope=all`)).meetings as Meeting[])).toHaveLength(2);
  const meetingPatch = { title: `${marker} changed`, expectedVersion: 1, idempotencyKey: key() };
  const meetingUpdated = success(await api(page, `/api/meetings/${meeting.meeting_id}`, "PATCH", meetingPatch));
  expect(meetingUpdated.meeting).toMatchObject({ title: meetingPatch.title, version: 2 });
  refused(await api(page, `/api/meetings/${meeting.meeting_id}`, "PATCH", { ...meetingPatch, idempotencyKey: key() }), 409, "conflict");
  // Transport admits safe ZoneInfo key shape; the canonical backend owns lookup.
  refused(await api(page, `/api/meetings/${meeting.meeting_id}`, "PATCH", {
    timezoneName: "Etc/WP03B_Not_A_Zone", expectedVersion: 2, idempotencyKey: key(),
  }), 400, "validation");
  expect(success(await api(page, `/api/meetings/${meeting.meeting_id}`)).meeting).toMatchObject({ version: 2 });
  for (const [timezoneName, expectedVersion] of [["Factory", 2], ["posix/UTC", 3]] as const) {
    expect(success(await api(page, `/api/meetings/${meeting.meeting_id}`, "PATCH", {
      timezoneName, expectedVersion, idempotencyKey: key(),
    })).meeting).toMatchObject({ timezone_name: timezoneName, version: expectedVersion + 1 });
  }
  const series = seeded.series as { meeting_series_id: string; version: number };
  expect(success(await api(page, `/api/meetings/series/${series.meeting_series_id}`, "PATCH", {
    title: "WP03B synthetic renamed series", expectedVersion: series.version, idempotencyKey: key(),
  })).series).toMatchObject({ title: "WP03B synthetic renamed series" });
  expect(success(await api(page, `/api/meetings/${meeting.meeting_id}`)).meeting).toMatchObject({ title: meetingPatch.title });

  const document = await arrange("documents.create", {
    title: "WP03B synthetic document", media_type: "text/plain", content: Buffer.from("WP03B synthetic bytes").toString("base64"), idempotency_key: key(),
  });
  const documentId = (document.receipt as { document_id: string }).document_id;
  const metadata = success(await api(page, `/api/documents/${documentId}`));
  expect(metadata.version).toMatchObject({ content_base64: null });
  const bytes = success(await api(page, `/api/documents/${documentId}?includeBytes=true`));
  expect(bytes.version).toMatchObject({ content_base64: Buffer.from("WP03B synthetic bytes").toString("base64") });
  expect(JSON.stringify(bytes)).not.toMatch(/principal_id|storage_path|file:\/\//);
  expect(success(await api(page, `/api/documents/${documentId}/archive`, "POST", {}))).toMatchObject({ state: "archived", changed: true });
  expect(success(await api(page, `/api/documents/${documentId}/archive`, "POST", {}))).toMatchObject({ state: "archived", changed: false });
  expect(success(await api(page, `/api/documents/${documentId}/restore`, "POST", {}))).toMatchObject({ state: "active", changed: true });
  expect(success(await api(page, `/api/documents/${documentId}/restore`, "POST", {}))).toMatchObject({ state: "active", changed: false });
});

test("real synthetic stack: invalid, unknown and duplicate inputs fail closed", async ({ page }) => {
  await signIn(page);
  // The existing identity guard's safe400 contract names its code, not class.
  const identityRefusal = await api(page, "/api/projects", "POST", {
    name: "synthetic", idempotencyKey: key(), principalId: "caller-forbidden",
  });
  expect(identityRefusal.status).toBe(400);
  expect(identityRefusal.body.error).toMatchObject({ code: "caller_supplied_principal" });
  expect(identityRefusal.body.shape).toBeUndefined();
  expect(identityRefusal.body.created).toBeUndefined();
  expect(identityRefusal.cacheControl).toContain("private");
  expect(identityRefusal.cacheControl).toContain("no-store");
  for (const [path, method, body] of [
    ["/api/capture/cap_bad", "PATCH", { text: "synthetic", idempotencyKey: key() }],
    ["/api/meetings?pageSize=1&pageSize=2", "GET", undefined],
    ["/api/meetings?unknown=1", "GET", undefined],
    ["/api/meetings/search?query=synthetic", "GET", undefined],
    ["/api/documents/mdoc_synthetic0001?includeBytes=1", "GET", undefined],
    ["/api/documents/mdoc_synthetic0001?includeBytes=true&includeBytes=false", "GET", undefined],
    ["/api/meetings/mtg_synthetic0001", "PATCH", { title: "synthetic", expectedVersion: 1, idempotencyKey: key(), attendeesReplace: [{ email: "synthetic@example.invalid", unknown: true }] }],
  ] as Array<[string, string, Body | undefined]>) refused(await api(page, path, method, body), 400, "validation");
});

test("real synthetic stack: archived Capture exact replay, changed-key conflict, new refusal and restore", async ({ page }) => {
  await signIn(page);
  const original = await api(page, "/api/capture", "POST", { text: "WP03B synthetic lifecycle root", idempotencyKey: key() });
  expect(original.status).toBe(200);
  const captureId = (original.body.receipt as { captureId: string }).captureId;
  expect(captureId).toMatch(/^cap_/);
  const request = { text: "WP03B synthetic bound revision", idempotencyKey: key(), occurredAt: "2026-10-04T12:00:00Z" };
  const accepted = success(await api(page, `/api/capture/${captureId}`, "PATCH", request));
  await arrange("capture.archive", { capture_id: captureId, expected_lifecycle_revision: 0, idempotency_key: key(), reason: "WP03B synthetic fixture" });
  const replay = success(await api(page, `/api/capture/${captureId}`, "PATCH", request));
  expect(replay.created).toBe(false);
  for (const field of ["receipt_id", "capture_id", "version_id", "version_number"]) expect(replay[field]).toBe(accepted[field]);
  refused(await api(page, `/api/capture/${captureId}`, "PATCH", { ...request, text: "WP03B synthetic changed intent" }), 409, "conflict");
  refused(await api(page, `/api/capture/${captureId}`, "PATCH", { ...request, idempotencyKey: key() }), 403, "authorization");
  // A new key reaches ownership lookup; changing captureId under a bound key
  // would correctly conflict before lookup and would not be an absence probe.
  refused(await api(page, "/api/capture/cap_absent00000001", "PATCH", { ...request, idempotencyKey: key() }), 404, "not_found");
  await arrange("capture.restore", { capture_id: captureId, expected_lifecycle_revision: 1, idempotency_key: key(), reason: "WP03B synthetic restore" });
  expect(success(await api(page, `/api/capture/${captureId}`, "PATCH", { ...request, idempotencyKey: key() })).version_number).toBe(3);
});

test("real browser offline: Capture revise fails transport and never adds a Capture-create queue entry", async ({ page, context }) => {
  await signIn(page);
  // Count only synthetic queue stores; never inspect key, payload or event values.
  const counts = () => page.evaluate(async () => {
    const databases = await indexedDB.databases();
    if (!databases.some((entry) => entry.name === "mypa-offline")) return [0, 0];
    return new Promise<number[]>((resolve, reject) => {
      const open = indexedDB.open("mypa-offline");
      open.onerror = () => reject(new Error("synthetic queue count unavailable"));
      open.onsuccess = async () => {
        const db = open.result;
        const result = await Promise.all(["events", "payloads"].map((name) => new Promise<number>((resolve, reject) => {
          const count = db.transaction(name, "readonly").objectStore(name).count();
          count.onsuccess = () => resolve(count.result);
          count.onerror = () => reject(new Error("synthetic queue count failed"));
        })));
        db.close(); resolve(result);
      };
    });
  });
  const before = await counts();
  await context.setOffline(true);
  const failed = await page.evaluate(async () => {
    try {
      await fetch("/api/capture/cap_synthetic0001", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: "WP03B synthetic offline revise", idempotencyKey: "wp03b-offline-revise" }) });
      return false;
    } catch { return true; }
  });
  expect(failed).toBe(true);
  expect(await counts()).toEqual(before);
  await expect(page.getByTestId("capture-queued")).toHaveCount(0);
  await context.setOffline(false);
});

test("real dead gateway: first-load unavailable is not empty", async ({ page }) => {
  await signIn(page, DEAD_GATEWAY_URL);
  refused(await api(page, "/api/meetings"), 503, "unavailable");
  await page.goto(`${DEAD_GATEWAY_URL}/work`);
  await expectState(page, "state-unavailable", "unavailable");
  await expect(page.locator('[data-state="empty"]')).toHaveCount(0);
  const text = await page.getByTestId("state-unavailable").textContent() ?? "";
  for (const claim of EMPTINESS_CLAIMS) expect(text).not.toMatch(claim);
});

test("synthetic intercepted transport: shipped Task UI presents ambiguous mutation without false success or retry", async ({ page }) => {
  await signIn(page);
  await page.goto("/work?view=unscheduled");
  let calls = 0;
  await page.route("**/api/tasks", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    calls += 1;
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { errorClass: "unavailable", code: "gateway_unreachable", message: "synthetic transport unavailable" } }) });
  });
  await page.getByRole("button", { name: "New task", exact: true }).click();
  const sheet = page.getByTestId("task-create-sheet");
  await sheet.getByLabel("Title", { exact: true }).fill("WP03B synthetic ambiguous Task");
  await sheet.getByRole("button", { name: "Create", exact: true }).click();
  await expect(sheet).toContainText("Create may still have succeeded");
  await expect(sheet.getByRole("button", { name: "Retry same create", exact: true })).toBeVisible();
  await expect(sheet.getByLabel("Title", { exact: true })).toHaveAttribute("readonly", "");
  await expect(page.getByText("Task created: WP03B synthetic ambiguous Task", { exact: true })).toHaveCount(0);
  await expect(sheet).toBeVisible();
  expect(calls).toBe(1);
});
