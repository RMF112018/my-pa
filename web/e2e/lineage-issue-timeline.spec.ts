/**
 * Record lineage S3 — the Issue view and the minimal Meeting view on a real
 * synthetic stack (contract sections 7.6 and 10, AT-024 browser rows).
 *
 * The browser reads only through the shipped BFF (`/api/issues/...`,
 * `/api/records/...` and `/api/meetings/...`), the canonical Python gateway
 * with the lineage plane switched on (`MY_PA_LINEAGE_ENABLED=true` in
 * `e2e/stack.sh`), and the disposable database. The Issues, Task, Meeting and
 * lineage rows are arranged directly at the owned loopback gateway: S3 has no
 * browser write control, and the attested lineage writes are admitted only for
 * the local operator, which is what that gateway is. Every value is synthetic.
 *
 * Each test runs at the geometry of the project that runs it (`desktop`,
 * `tablet`, `mobile`): the phone, tablet and desktop widths are the projects'
 * own emulation profiles, not a resized desktop window.
 */
import { createHash } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

type Body = Record<string, unknown>;

// Synthetic sessions must never enter trace/video artifacts.
test.use({ trace: "off", video: "off", screenshot: "off" });

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

function key(): string { return `lineage-s3-e2e-${crypto.randomUUID()}`; }

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

async function addMember(issueId: string, family: string, recordId: string, role: string): Promise<void> {
  await arrange("issues.memberships.add", "issue_authoring", {
    issue_id: issueId, member: { family, record_id: recordId }, role, idempotency_key: key(),
  });
}

async function createMeeting(title: string, notes?: string): Promise<string> {
  const meeting = await arrange("meetings.create", "meeting_authoring", {
    title, start_at: "2026-10-04T12:00:00Z", timezone_name: "UTC",
    ...(notes === undefined ? {} : { notes_markdown: notes }), idempotency_key: key(),
  });
  return (meeting.meeting as { meeting_id: string }).meeting_id;
}

const sha256 = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");

/** An Issue with a Task member that originated from an exact note passage. */
async function arrangeIssue(marker: string): Promise<{ issueId: string; issueTitle: string; body: string; passage: string }> {
  const issueTitle = `Synthetic S3 Issue ${marker}`;
  const issueId = await createIssue(issueTitle);
  const taskId = await createTask(`Synthetic S3 Task ${marker}`);
  await addMember(issueId, "task", taskId, "work");
  const body = "Synthetic S3 note: confirm the crane pick plan before Friday.";
  const passage = "confirm the crane pick plan";
  const start = Array.from(body.slice(0, body.indexOf(passage))).length;
  const end = start + Array.from(passage).length;
  const meetingId = await createMeeting(`Synthetic S3 Meeting ${marker}`, body);
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
  return { issueId, issueTitle, body, passage };
}

/** No horizontal page scroll at this width. */
async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

async function tabTo(page: Page, target: ReturnType<Page["getByRole"]>): Promise<boolean> {
  for (let step = 0; step < 120; step += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => element === document.activeElement)) return true;
  }
  return false;
}

test("the Issue page is keyboard reachable at phone, tablet and desktop width", async ({ page }) => {
  test.setTimeout(120_000);
  const { issueId, issueTitle, body, passage } = await arrangeIssue(key());

  await signIn(page);
  await page.goto(`/work/issues/${issueId}`);
  await expect(page.getByRole("heading", { level: 1, name: issueTitle })).toBeVisible();
  const crumbs = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(crumbs.getByRole("link", { name: "Issues" })).toHaveAttribute("href", "/work/issues");
  const timeline = page.getByRole("region", { name: "Timeline" });
  await expect(timeline.getByText("Issue created")).toBeVisible();
  await expect(timeline.getByText("Member recorded: a Task as work")).toBeVisible();
  await expect(timeline.getByText("A Task originated from a Meeting note version: recorded")).toBeVisible();
  const lineage = page.getByRole("region", { name: "Lineage" });
  const records = lineage.getByRole("table", { name: "Records" });
  await expect(records.getByText("Reached from a Task via originated from")).toBeVisible();
  await expect(lineage.getByRole("table", { name: "Links" })).toBeVisible();
  await expect(page.getByText(passage, { exact: true })).toHaveCount(0);

  // Reach the cited note version's disclosure from the keyboard alone and open it.
  const open = lineage.getByRole("button", { name: "Open note version" });
  await expect(open).toHaveAttribute("aria-expanded", "false");
  expect(await tabTo(page, open), "the note-version drilldown is reachable by Tab").toBe(true);
  await page.keyboard.press("Enter");
  await expect(lineage.getByRole("button", { name: "Hide note version" })).toHaveAttribute("aria-expanded", "true");
  await expect(lineage.getByText(passage, { exact: true })).toBeVisible();
  await expect(lineage.getByText(body)).toBeVisible();
  await expect(lineage.getByText("Version 1 (current)")).toBeVisible();

  // Readable at this project's width: inside the viewport and no sideways page scroll.
  for (const region of [timeline, lineage]) {
    const box = await region.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  }
  await expectNoHorizontalScroll(page);
});

test("a Meeting in 3 Issues asks for one before showing lineage", async ({ page }) => {
  test.setTimeout(120_000);
  const marker = key();
  const titles = [1, 2, 3].map((number) => `Synthetic S3 Issue ${number} ${marker}`);
  const issueIds: string[] = [];
  for (const title of titles) issueIds.push(await createIssue(title));
  const meetingTitle = `Synthetic S3 shared Meeting ${marker}`;
  const meetingId = await createMeeting(meetingTitle);
  for (const issueId of issueIds) await addMember(issueId, "meeting", meetingId, "discussion");

  await signIn(page);
  const lineageReads: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/related-issues")) lineageReads.push(new URL(request.url()).search);
  });
  await page.goto(`/work/meetings/${meetingId}`);
  await expect(page.getByRole("heading", { level: 1, name: meetingTitle })).toBeVisible();
  const panel = page.getByRole("region", { name: "Related Issues" });
  const group = panel.getByRole("group", { name: /belongs to several Issues. Choose one/ });
  await expect(group).toBeVisible();
  await expect(group.getByRole("radio")).toHaveCount(3);
  for (const radio of await group.getByRole("radio").all()) await expect(radio).not.toBeChecked();
  await expect(panel.getByText(/^Issue: /)).toHaveCount(0);
  await expect(panel.getByText(/Member of this Issue/)).toHaveCount(0);

  await group.getByRole("radio", { name: new RegExp(`^${titles[1]}`) }).check();
  const chosen = panel.getByRole("link", { name: `Issue: ${titles[1]}` });
  await expect(chosen).toBeVisible();
  await expect(chosen).toHaveAttribute("href", `/work/issues/${issueIds[1]}`);
  await expect(panel.getByText("Member of this Issue as discussion")).toBeVisible();
  const chosenAt = lineageReads.indexOf(`?issueId=${issueIds[1]}`);
  expect(chosenAt).toBeGreaterThan(0);
  expect(lineageReads.slice(0, chosenAt).every((search) => search === "")).toBe(true);
  await expectNoHorizontalScroll(page);
});

test("the Issue page has no detectable accessibility violations", async ({ page }) => {
  test.setTimeout(120_000);
  const { issueId, issueTitle } = await arrangeIssue(key());
  await signIn(page);
  await page.goto(`/work/issues/${issueId}`);
  await expect(page.getByRole("heading", { level: 1, name: issueTitle })).toBeVisible();
  await expect(page.getByRole("table", { name: "Records" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Timeline" }).getByText("Issue created")).toBeVisible();
  const issueScan = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(issueScan.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);

  await page.goto("/work/issues");
  await expect(page.getByRole("link", { name: issueTitle })).toBeVisible();
  const indexScan = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(indexScan.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
});
