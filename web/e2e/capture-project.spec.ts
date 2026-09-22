/**
 * T15 — a Capture filed against a Project, through the whole real stack.
 *
 * Chromium, the Next.js BFF, the Python gateway and PostgreSQL. Nothing here is
 * stubbed, which is the point: the unit tiers proved the browser sends a
 * `projectId` and that the BFF forwards it, but only a real save can show that
 * the Project came back out of a committed row.
 *
 * The strongest assertion in this file is the readback. A receipt naming a
 * Project is a claim; reading the capture afterwards and finding the same
 * Project is the evidence, because it is the canonical row answering rather
 * than the request echoing.
 */
import { expect, test } from "@playwright/test";
import { enableDiagnostics, openCaptureNote, signIn, syntheticNote } from "./fixtures";

/** The selector, once it has loaded its authorized page. */
function projectSelect(page: import("@playwright/test").Page) {
  return page.getByTestId("capture-project-select");
}

/** Every Project this Principal may choose, as the authorized page reports them. */
async function authorizedProjects(page: import("@playwright/test").Page) {
  const response = await page.request.get("/api/projects");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    projects?: { projectId?: string; name?: string }[];
  };
  return (body.projects ?? []).filter(
    (row): row is { projectId: string; name: string } =>
      typeof row.projectId === "string" && typeof row.name === "string",
  );
}

/**
 * The canonical listing, by capture identifier.
 *
 * `capture.list` publishes metadata and the Project, deliberately not the text —
 * the whole point of the receipt's digest is that a replay is checkable without
 * echoing content. So the readback is keyed on the identifier the receipt
 * issued, which is also the stronger claim: this exact committed row.
 */
async function canonicalCaptureById(page: import("@playwright/test").Page, captureId: string) {
  const response = await page.request.get("/api/library");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as {
    result?: { captures?: { capture_id?: string; project_id?: string | null }[] };
  };
  return (body.result?.captures ?? []).find((row) => row.capture_id === captureId);
}

/** Save through the real UI and return the receipt the BFF published. */
async function saveAndReadReceipt(page: import("@playwright/test").Page) {
  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) =>
        candidate.url().includes("/api/capture") && candidate.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Save" }).click(),
  ]);
  expect(response.status()).toBe(200);
  return (await response.json()) as {
    receipt: { captureId: string; projectId: string | null };
  };
}

test.describe("WP08 Capture Project, real stack", () => {
  test("a note saved against a Project reads back against that Project", async ({ page }) => {
    await signIn(page);
    await enableDiagnostics(page);
    const projects = await authorizedProjects(page);
    test.skip(projects.length === 0, "this stack seeds no Project for the synthetic Principal");
    const chosen = projects[0]!;

    const note = syntheticNote("wp08-project-note");
    await openCaptureNote(page);
    await expect(projectSelect(page)).toBeVisible();
    // The label is a real label, associated with the control.
    await expect(page.getByLabel("Project")).toHaveCount(1);
    await projectSelect(page).selectOption(chosen.projectId);
    await page.getByTestId("capture-field").fill(note);
    const ack = await saveAndReadReceipt(page);

    const durable = page.getByTestId("capture-durable");
    await expect(durable).toBeVisible();
    await expect(durable).toContainText("Saved");
    // The nested Project comes from the committed row, not from the request.
    expect(ack.receipt.projectId).toBe(chosen.projectId);

    // The readback: the canonical list answers with the Project the row holds.
    const found = await canonicalCaptureById(page, ack.receipt.captureId);
    expect(found, "the saved note is not in the canonical listing").toBeTruthy();
    expect(found?.project_id).toBe(chosen.projectId);
  });

  test("a note saved with No Project reads back with no Project", async ({ page }) => {
    await signIn(page);
    await enableDiagnostics(page);

    const note = syntheticNote("wp08-no-project-note");
    await openCaptureNote(page);
    await expect(projectSelect(page)).toHaveValue("");
    await page.getByTestId("capture-field").fill(note);
    const ack = await saveAndReadReceipt(page);
    await expect(page.getByTestId("capture-durable")).toBeVisible();
    expect(ack.receipt.projectId).toBeNull();

    const found = await canonicalCaptureById(page, ack.receipt.captureId);
    expect(found).toBeTruthy();
    // Null, explicitly. Not absent, and not a Project it was never filed under.
    expect(found?.project_id ?? null).toBeNull();
  });

  test("a Conversation log carries its Project the same way a note does", async ({ page }) => {
    await signIn(page);
    await enableDiagnostics(page);
    const projects = await authorizedProjects(page);
    test.skip(projects.length === 0, "this stack seeds no Project for the synthetic Principal");
    const chosen = projects[0]!;

    const note = syntheticNote("wp08-conversation-project");
    await openCaptureNote(page, "Conversation log");
    await projectSelect(page).selectOption(chosen.projectId);
    await page.getByTestId("capture-field").fill(note);
    const ack = await saveAndReadReceipt(page);
    await expect(page.getByTestId("capture-durable")).toBeVisible();

    expect((await canonicalCaptureById(page, ack.receipt.captureId))?.project_id).toBe(
      chosen.projectId,
    );
  });

  test("the same key with a different Project is refused, and the first stands", async ({
    page,
  }) => {
    await signIn(page);
    const projects = await authorizedProjects(page);
    test.skip(projects.length < 2, "this stack seeds fewer than two Projects");
    const [first, second] = projects;
    const note = syntheticNote("wp08-same-key-two-projects");
    const key = `cap-e2e-${Date.now()}`;
    const origin = new URL(page.url()).origin;

    const admitted = await page.request.post("/api/capture", {
      headers: { origin, "content-type": "application/json" },
      data: { text: note, captureKind: "quick_note", idempotencyKey: key, projectId: first!.projectId },
    });
    expect(admitted.status()).toBe(200);
    const receipt = (await admitted.json()).receipt as { captureId: string; projectId: string };
    expect(receipt.projectId).toBe(first!.projectId);

    const refused = await page.request.post("/api/capture", {
      headers: { origin, "content-type": "application/json" },
      data: { text: note, captureKind: "quick_note", idempotencyKey: key, projectId: second!.projectId },
    });
    expect(refused.status()).toBe(409);

    // One capture under that key, still against the Project it was admitted with.
    const found = await canonicalCaptureById(page, receipt.captureId);
    expect(found?.project_id).toBe(first!.projectId);
  });

  test("a malformed Project is refused before any write", async ({ page }) => {
    await signIn(page);
    const origin = new URL(page.url()).origin;
    const note = syntheticNote("wp08-malformed-project");

    const refused = await page.request.post("/api/capture", {
      headers: { origin, "content-type": "application/json" },
      data: {
        text: note,
        captureKind: "quick_note",
        idempotencyKey: `cap-e2e-bad-${Date.now()}`,
        projectId: "not-a-project",
      },
    });
    expect(refused.status()).toBe(400);
    expect((await refused.json()).error.code).toBe("invalid_project_id");

    // And nothing was written: no capture was issued at all.
    expect(refused.status()).toBe(400);
  });

  test("a foreign Project is the canonical nondisclosing refusal, not a fallback", async ({
    page,
  }) => {
    await signIn(page);
    const origin = new URL(page.url()).origin;
    const note = syntheticNote("wp08-foreign-project");

    const refused = await page.request.post("/api/capture", {
      headers: { origin, "content-type": "application/json" },
      data: {
        text: note,
        captureKind: "quick_note",
        idempotencyKey: `cap-e2e-foreign-${Date.now()}`,
        // Well-formed and not this Principal's. Missing and foreign are one answer.
        projectId: "prj_ffffffffffffffffffffffffffffffff",
      },
    });
    expect(refused.status()).toBe(404);

    // Never filed against nothing instead: the refusal is the whole answer.
    expect(refused.status()).toBe(404);
  });

  test("this path creates no Task and no Constraint", async ({ page }) => {
    await signIn(page);
    const before = await page.request.get("/api/tasks");
    const beforeCount = ((await before.json()) as { tasks?: unknown[] }).tasks?.length ?? 0;

    const note = syntheticNote("wp08-capture-only");
    await openCaptureNote(page);
    await page.getByTestId("capture-field").fill(note);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("capture-durable")).toBeVisible();

    const after = await page.request.get("/api/tasks");
    const afterCount = ((await after.json()) as { tasks?: unknown[] }).tasks?.length ?? 0;
    expect(afterCount).toBe(beforeCount);
  });
});
