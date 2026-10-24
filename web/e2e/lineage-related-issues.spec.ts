/**
 * Record lineage S1 — the related-Issue panel on a real synthetic stack
 * (contract sections 7.4 and 10, AT-024 browser rows).
 *
 * The browser reads only through the shipped BFF (`/api/records/...` and
 * `/api/meetings/.../notes/...`), the canonical Python gateway with the lineage
 * plane switched on (`MY_PA_LINEAGE_ENABLED=true` in `e2e/stack.sh`), and the
 * disposable database. The Issue, Task, Meeting and lineage rows are arranged
 * directly at the owned loopback gateway: S1 has no browser write control, and
 * the attested membership and association writes are admitted only for the
 * local operator, which is what that gateway is. Every value is synthetic.
 */
import { createHash } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

type Body = Record<string, unknown>;

// Synthetic sessions must never enter trace/video artifacts.
test.use({ trace: "off", video: "off", screenshot: "off" });

function key(): string { return `lineage-e2e-${crypto.randomUUID()}`; }

/** Canonical fixture arrangement, exclusively at the owned loopback gateway. */
async function arrange(capability: string, purpose: string, payload: Body): Promise<Body> {
  const origin = process.env.MYPA_E2E_GATEWAY_URL ?? "http://127.0.0.1:9099";
  const url = new URL(origin);
  expect(url.hostname).toBe("127.0.0.1");
  expect(url.protocol).toBe("http:");
  const response = await fetch(`${origin}/v1/${capability}`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ contract_version: "v1", request_id: `req_${crypto.randomUUID().replaceAll("-", "")}`,
      purpose,
      // Canonical local_principal() correlation identity; gateway authentication
      // remains the fixed synthetic local-operator context, not this field.
      principal_id: "prn_24abf5d2d0c25e1c82f6e72425e9ed37",
      requested_at: new Date().toISOString(), payload }),
  });
  const envelope = await response.json() as { result: Body | null; error: unknown };
  expect(envelope.error, capability).toBeNull();
  expect(response.status, capability).toBe(200);
  expect(envelope.result, capability).not.toBeNull();
  return envelope.result!;
}

async function createIssue(title: string): Promise<string> {
  const created = await arrange("issues.create", "issue_authoring", { title, idempotency_key: key() });
  return (created.issue as { issue_id: string }).issue_id;
}

async function createTask(title: string): Promise<string> {
  const created = await arrange("tasks.create", "task_authoring", {
    title, origin_kind: "direct_principal", idempotency_key: key(),
  });
  return (created.task as { task_id: string }).task_id;
}

async function addMember(issueId: string, taskId: string): Promise<void> {
  await arrange("issues.memberships.add", "issue_authoring", {
    issue_id: issueId, member: { family: "task", record_id: taskId }, role: "work", idempotency_key: key(),
  });
}

const sha256 = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");

/** No horizontal page scroll at this width. */
async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("related Issues on a Task are keyboard reachable and readable at phone width", async ({ page }) => {
  test.setTimeout(120_000);
  const viewport = page.viewportSize();
  if (viewport === null || viewport.width > 430) await page.setViewportSize({ width: 390, height: 844 });

  const marker = key();
  const issueTitle = `Synthetic lineage Issue ${marker}`;
  const issueId = await createIssue(issueTitle);
  const taskId = await createTask(`Synthetic lineage Task ${marker}`);
  await addMember(issueId, taskId);

  // An originating passage on an exact note version, scoped to the Issue.
  const body = "Synthetic lineage note: confirm the crane pick plan before Friday.";
  const passage = "confirm the crane pick plan";
  const start = Array.from(body.slice(0, body.indexOf(passage))).length;
  const end = start + Array.from(passage).length;
  const meeting = await arrange("meetings.create", "meeting_authoring", {
    title: `Synthetic lineage Meeting ${marker}`, start_at: "2026-10-04T12:00:00Z", timezone_name: "UTC",
    notes_markdown: body, idempotency_key: key(),
  });
  const meetingId = (meeting.meeting as { meeting_id: string }).meeting_id;
  const versions = await arrange("meetings.notes.versions", "meeting_read", { meeting_id: meetingId });
  const noteVersionId = (versions.versions as { note_version_id: string }[])[0]!.note_version_id;
  const note = await arrange("meetings.notes.read_version", "meeting_note_history_read", {
    meeting_id: meetingId, note_version_id: noteVersionId,
  });
  await arrange("records.associations.assert", "record_lineage_authoring", {
    from_record: { family: "task", record_id: taskId },
    to_record: { family: "meeting_note_version", record_id: noteVersionId },
    relation_type: "originated_from",
    context_issue_id: issueId,
    idempotency_key: key(),
    evidence_anchors: [{
      family: "meeting_note_version", root_id: meetingId, version_kind: "immutable_version",
      version_id: noteVersionId, source_sha256: (note.note as { content_sha256: string }).content_sha256,
      passage_start_cp: start, passage_end_cp: end, passage_sha256: sha256(passage), role: "origin",
    }],
  });

  await signIn(page);
  await page.goto(`/work/tasks/${taskId}`);
  const panel = page.getByRole("region", { name: "Related Issues" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText(`Issue: ${issueTitle}`)).toBeVisible();
  await expect(panel.getByText("State: open")).toBeVisible();
  await expect(panel.getByText("Member of this Issue as work")).toBeVisible();
  await expect(panel.getByText("Originated from a Meeting note version")).toBeVisible();
  await expect(panel.getByText(/Recorded by: local operator/).first()).toBeVisible();
  await expect(panel.getByText(`Meeting note version 1, characters ${start}–${end}`)).toBeVisible();
  await expect(panel.getByText(passage)).toHaveCount(0);

  // Reach the anchor's disclosure from the keyboard alone and open it.
  const open = panel.getByRole("button", { name: "Open note version" });
  await expect(open).toHaveAttribute("aria-expanded", "false");
  let focused = false;
  for (let step = 0; step < 80 && !focused; step += 1) {
    await page.keyboard.press("Tab");
    focused = await open.evaluate((element) => element === document.activeElement);
  }
  expect(focused, "the note-version disclosure is reachable by Tab").toBe(true);
  await page.keyboard.press("Enter");
  const close = panel.getByRole("button", { name: "Hide note version" });
  await expect(close).toHaveAttribute("aria-expanded", "true");
  await expect(panel.getByText(passage, { exact: true })).toBeVisible();
  await expect(panel.getByText(body)).toBeVisible();

  // Readable at phone width: inside the viewport and no sideways page scroll.
  const box = await panel.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  await expectNoHorizontalScroll(page);
});

test("an ambiguous record asks for an Issue before showing lineage", async ({ page }) => {
  test.setTimeout(120_000);
  const marker = key();
  const first = `Synthetic first Issue ${marker}`;
  const second = `Synthetic second Issue ${marker}`;
  const firstId = await createIssue(first);
  const secondId = await createIssue(second);
  const taskId = await createTask(`Synthetic shared Task ${marker}`);
  await addMember(firstId, taskId);
  await addMember(secondId, taskId);

  await signIn(page);
  const lineageReads: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/related-issues")) lineageReads.push(new URL(request.url()).search);
  });
  await page.goto(`/work/tasks/${taskId}`);
  const panel = page.getByRole("region", { name: "Related Issues" });
  const group = panel.getByRole("group", { name: /belongs to several Issues. Choose one/ });
  await expect(group).toBeVisible();
  await expect(group.getByRole("radio")).toHaveCount(2);
  for (const radio of await group.getByRole("radio").all()) await expect(radio).not.toBeChecked();
  // No lineage is shown, and no Issue is chosen, before the user chooses.
  await expect(panel.getByText(/Member of this Issue/)).toHaveCount(0);
  await expect(panel.getByText(/^Issue: /)).toHaveCount(0);

  await group.getByRole("radio", { name: new RegExp(`^${second}`) }).check();
  await expect(panel.getByText(`Issue: ${second}`)).toBeVisible();
  await expect(panel.getByText("Member of this Issue as work")).toBeVisible();
  // The candidates stay offered, with the user's own choice checked.
  const chosen = panel.getByRole("group", { name: /belongs to several Issues/ });
  await expect(chosen.getByRole("radio", { name: new RegExp(`^${second}`) })).toBeChecked();
  await expect(chosen.getByRole("radio", { name: new RegExp(`^${first}`) })).not.toBeChecked();
  // Only lineage reads of this record: unscoped until the choice, then exactly
  // one under the chosen Issue. (The dev server's React Strict Mode may repeat
  // the mount-time read; the component test pins one read per render.)
  const chosenAt = lineageReads.indexOf(`?issueId=${secondId}`);
  expect(chosenAt).toBeGreaterThan(0);
  expect(lineageReads.slice(0, chosenAt).every((search) => search === "")).toBe(true);
  expect(lineageReads.slice(chosenAt)).toEqual([`?issueId=${secondId}`]);
});
