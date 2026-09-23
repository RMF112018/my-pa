/**
 * R01-WP09: Constraint and Category authoring over the real stack.
 *
 * Browser → same-origin BFF → the thirteen R01-WP09 authoring routes → the
 * server-only gateway transport → the Python `constraint_authoring`
 * capabilities → the Constraint Management service, its row locks, its
 * idempotency ledger and its append-only history → the isolated, disposable
 * PostgreSQL that `e2e/stack.sh` creates, migrates, seeds and drops. No fixture
 * satisfies any assertion here; every answer is read back from the database
 * through the existing read routes.
 *
 * **This is a transport journey, not a screen.** WP09 ships no authoring UI
 * (that is WP10), and this spec deliberately renders none: it signs in through
 * the real sign-in page so the session cookie is a real one, then exercises
 * the routes from inside the page's origin, exactly as
 * `project-controls-settings.spec.ts` does for the settings write.
 *
 * **Run it alone, in its own `npm run e2e` invocation.** It mutates the seeded
 * Register — it adds Categories and Constraints to `prj_e2ecst0000000001` and
 * closes one — and `constraints-read-plane.spec.ts` asserts exact seed counts
 * (two open Constraints, one active Category, one omitted Project). With
 * `workers: 1` and alphabetical order this file would run first in a shared
 * invocation and break those assertions. Every `npm run e2e` drops and
 * re-creates the disposable database, so a separate invocation isolates the two
 * without weakening either (plan §13 D3); CI runs it as its own `e2e-critical`
 * step for exactly this reason. Never add it to another spec list.
 *
 * Malformed-success refusal and cross-*Principal* isolation are not provable
 * here — the real stack runs one `local_operator` Principal and emits only
 * well-formed success — and are proven at the unit, security and backend
 * database tiers instead.
 */
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures";

/** Mirrors the Constraint seed step in `e2e/stack.sh`. */
const PROJECT = "prj_e2ecst0000000001";
const UNCONFIGURED_PROJECT = "prj_e2ecst0000000002";
const SEEDED_CATEGORY = "ccat_e2ecst0000000001";
const SEEDED_CONSTRAINT = "cst_e2ecst0000000001";
const SEEDED_CONSTRAINT_VERSION = 2;

const BASE = "/api/project-controls/projects";

/**
 * Every key the safe decoders must have projected away. The check is over
 * object *keys*, not the serialized text: a published BIC is legitimately
 * `{"kind": "principal"}`, and a value is not a leaked field.
 */
const FORBIDDEN_KEY = /principal|idempotency|digest|client_?context|correlation|recorded/i;

type Answer = {
  status: number;
  cacheControl: string | null;
  body: Record<string, unknown>;
};

type Json = Record<string, unknown>;

async function call(
  page: Page,
  method: "GET" | "POST" | "PATCH",
  path: string,
  payload?: Json,
): Promise<Answer> {
  return page.evaluate(
    async ({ target, verb, document }) => {
      const response = await fetch(target, {
        method: verb,
        cache: "no-store",
        credentials: "same-origin",
        headers: document === undefined ? undefined : { "content-type": "application/json" },
        body: document === undefined ? undefined : JSON.stringify(document),
      });
      return {
        status: response.status,
        cacheControl: response.headers.get("cache-control"),
        body: (await response.json()) as Record<string, unknown>,
      };
    },
    { target: `${BASE}${path}`, verb: method, document: payload },
  );
}

/**
 * A unique, backend-shaped idempotency key (`^[A-Za-z0-9_-]{8,128}$`). The run
 * stamp keeps a retried test from replaying a previous attempt's write.
 */
const RUN = Date.now().toString(36);
function key(step: string): string {
  return `e2e-cstm-${RUN}-${step}`;
}

/** Every object key anywhere in a JSON value. */
function keysOf(value: unknown, into: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) keysOf(item, into);
  } else if (value !== null && typeof value === "object") {
    for (const [name, entry] of Object.entries(value)) {
      into.push(name);
      keysOf(entry, into);
    }
  }
  return into;
}

/**
 * The transport invariants every answer here must hold, success or refusal:
 * the expected status, `private, no-store`, no identity/idempotency/digest/
 * telemetry/recording-time key anywhere in the published body, and the caller's
 * own idempotency key never echoed back.
 */
function expectSafe(answer: Answer, status: number, sentKey?: string): void {
  expect(answer.status, JSON.stringify(answer.body)).toBe(status);
  expect(answer.cacheControl).toBe("private, no-store");
  const published = structuredClone(answer.body);
  const error = published.error as Json | undefined;
  if (status >= 400 && error !== undefined && "correlationId" in error) {
    // The one exemption, and only on a refusal: the shared refusal envelope
    // (`lib/api/gateway.ts`, since UI-IMP-WP06) carries the gateway's own
    // support reference. The browser cannot choose it — no authoring field map
    // admits a correlation id — so it is the server's minted identifier, and
    // its shape is pinned here rather than ignored.
    expect(error.correlationId).toMatch(/^corr_[0-9a-f]{32}$/);
    delete error.correlationId;
  }
  expect(keysOf(published).filter((name) => FORBIDDEN_KEY.test(name))).toEqual([]);
  if (sentKey !== undefined) expect(JSON.stringify(answer.body)).not.toContain(sentKey);
}

function errorCode(answer: Answer): unknown {
  return (answer.body.error as Json | undefined)?.code;
}

type Receipt = Json & { outcome: string; beforeVersion: number; afterVersion: number };

/**
 * A decoded single-record answer, with the disposition/version parity the
 * decoder promises re-checked on the wire: `applied` advances the receipt by
 * exactly one and the record is the version the receipt produced.
 */
function applied(answer: Answer, recordKey: "constraint" | "category"): { record: Json; receipt: Receipt } {
  expect(answer.body.shape).toBe("backend");
  expect(answer.body.disposition).toBe("applied");
  const record = answer.body[recordKey] as Json;
  const receipt = answer.body.receipt as Receipt;
  expect(record, `the answer must carry a ${recordKey}`).toBeTruthy();
  expect(receipt.outcome).toBe("applied");
  expect(receipt.afterVersion).toBe(receipt.beforeVersion + 1);
  expect(record.version).toBe(receipt.afterVersion);
  expect(record.projectId).toBe(PROJECT);
  expect(receipt.projectId).toBe(PROJECT);
  return { record, receipt };
}

async function readConstraint(page: Page, constraintId: string, projectId = PROJECT): Promise<Answer> {
  return call(page, "GET", `/${projectId}/constraints/${constraintId}`);
}

async function activeCategories(page: Page): Promise<Json[]> {
  const answer = await call(page, "GET", `/${PROJECT}/constraint-categories?state=active`);
  expectSafe(answer, 200);
  return answer.body.categories as Json[];
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("the Constraint authoring journey writes through the BFF to PostgreSQL", async ({ page }) => {
  test.setTimeout(240_000);

  // 1. Category create → update; a second Category created and deactivated.
  const createKey = key("cat-create");
  const created = await call(page, "POST", `/${PROJECT}/constraint-categories`, {
    prefix: "7",
    title: "Logistics",
    displayOrder: 2,
    idempotencyKey: createKey,
  });
  expectSafe(created, 200, createKey);
  const { record: logistics, receipt: logisticsReceipt } = applied(created, "category");
  expect(logisticsReceipt.beforeVersion).toBe(0);
  expect(logistics.prefix).toBe("7");
  expect(logistics.state).toBe("active");
  const logisticsId = logistics.categoryId as string;

  const renameKey = key("cat-update");
  const renamed = await call(page, "PATCH", `/${PROJECT}/constraint-categories/${logisticsId}`, {
    expectedVersion: logistics.version,
    title: "Logistics and access",
    idempotencyKey: renameKey,
  });
  expectSafe(renamed, 200, renameKey);
  const { record: logisticsRenamed } = applied(renamed, "category");
  expect(logisticsRenamed.categoryId).toBe(logisticsId);
  expect(logisticsRenamed.title).toBe("Logistics and access");
  expect(logisticsRenamed.version).toBe((logistics.version as number) + 1);

  const spareKey = key("cat-spare");
  const spare = await call(page, "POST", `/${PROJECT}/constraint-categories`, {
    prefix: "9",
    title: "Temporary",
    displayOrder: 3,
    idempotencyKey: spareKey,
  });
  expectSafe(spare, 200, spareKey);
  const { record: spareRecord } = applied(spare, "category");
  const retireKey = key("cat-deactivate");
  const retired = await call(
    page,
    "POST",
    `/${PROJECT}/constraint-categories/${spareRecord.categoryId as string}/deactivate`,
    { expectedVersion: spareRecord.version, idempotencyKey: retireKey },
  );
  expectSafe(retired, 200, retireKey);
  const { record: retiredRecord } = applied(retired, "category");
  expect(retiredRecord.state).not.toBe("active");

  // 2. Reorder the Project's scheme, then replay and conflict. The backend's
  // reorder names *every* Category of the Project in any state
  // (`reorder_categories` lists with `include_states=None`), so the deactivated
  // one is part of the order too; the active list alone is refused as
  // `constraint_category_reorder_is_not_the_whole_project`.
  const schemeAnswer = await call(
    page,
    "GET",
    `/${PROJECT}/constraint-categories?state=active&state=inactive&state=archived`,
  );
  expectSafe(schemeAnswer, 200);
  const scheme = schemeAnswer.body.categories as Json[];
  expect(scheme.map((entry) => entry.categoryId).sort()).toEqual(
    [SEEDED_CATEGORY, logisticsId, spareRecord.categoryId as string].sort(),
  );
  const reversed = [...scheme].reverse();
  const reorderKey = key("cat-reorder");
  const reorderBody = {
    orderedCategoryIds: reversed.map((entry) => entry.categoryId as string),
    expectedVersions: reversed.map((entry) => entry.version as number),
    idempotencyKey: reorderKey,
  };
  const reordered = await call(page, "POST", `/${PROJECT}/constraint-categories/reorder`, reorderBody);
  expectSafe(reordered, 200, reorderKey);
  expect(reordered.body.shape).toBe("backend");
  expect(reordered.body.disposition).toBe("applied");
  const ordered = reordered.body.categories as Json[];
  const receipts = reordered.body.receipts as Receipt[];
  expect(ordered.map((entry) => entry.categoryId)).toEqual(reorderBody.orderedCategoryIds);
  expect(receipts.map((entry) => entry.categoryId)).toEqual(reorderBody.orderedCategoryIds);
  ordered.forEach((entry, index) => expect(entry.displayOrder).toBe(index));
  receipts.forEach((entry, index) => {
    expect(entry.outcome).toBe("applied");
    expect(entry.beforeVersion).toBe(reorderBody.expectedVersions[index]);
    expect(entry.afterVersion).toBe(entry.beforeVersion + 1);
  });

  // The same key and the same body is the same request: replayed, not re-applied.
  const replayed = await call(page, "POST", `/${PROJECT}/constraint-categories/reorder`, reorderBody);
  expectSafe(replayed, 200, reorderKey);
  expect(replayed.body.disposition).toBe("replayed");
  expect((replayed.body.categories as Json[]).map((entry) => entry.categoryId)).toEqual(
    reorderBody.orderedCategoryIds,
  );
  expect(replayed.body.receipts as Receipt[]).toHaveLength(1);
  expect((replayed.body.receipts as Receipt[])[0].categoryId).toBe(reorderBody.orderedCategoryIds[0]);
  const afterReplay = (
    await call(page, "GET", `/${PROJECT}/constraint-categories?state=active&state=inactive&state=archived`)
  ).body.categories as Json[];
  expect(afterReplay).toHaveLength(reorderBody.orderedCategoryIds.length);
  for (const entry of afterReplay) {
    const index = reorderBody.orderedCategoryIds.indexOf(entry.categoryId as string);
    expect(entry.version, "a replay must not write again").toBe(receipts[index].afterVersion);
  }

  // The same key with a different body is a different request under a used key.
  const collided = await call(page, "POST", `/${PROJECT}/constraint-categories/reorder`, {
    ...reorderBody,
    expectedVersions: [reorderBody.expectedVersions[0] + 1, ...reorderBody.expectedVersions.slice(1)],
  });
  expectSafe(collided, 409, reorderKey);
  expect(errorCode(collided)).toBe("conflict");

  // 3. Create a Constraint directly in its published state, then read it back.
  const publishKey = key("cst-create-published");
  const published = await call(page, "POST", `/${PROJECT}/constraints`, {
    categoryId: logisticsId,
    description: "Steel delivery gate access",
    dateIdentified: "2026-09-01",
    dueDate: "2026-10-15",
    bic: [{ kind: "principal" }],
    idempotencyKey: publishKey,
  });
  expectSafe(published, 200, publishKey);
  // One receipt for the whole create-and-publish: `applied` parity is checked
  // above; the create's own version step is the service's, not restated here.
  const { record: steel } = applied(published, "constraint");
  expect(steel.lifecycleState).toBe("identified");
  expect(steel.categoryId).toBe(logisticsId);
  expect(steel.constraintCode).toBe("7.01");
  expect(steel.bic).toEqual([{ kind: "principal", entityId: null, label: null }]);
  const steelId = steel.constraintId as string;

  const steelRead = await readConstraint(page, steelId);
  expectSafe(steelRead, 200);
  const steelLive = steelRead.body.constraint as Json;
  expect(steelLive.constraintId).toBe(steelId);
  expect(steelLive.projectId).toBe(PROJECT);
  expect(steelLive.version).toBe(steel.version);
  expect(steelLive.status).toBe("identified");
  expect(steelLive.constraintCode).toBe("7.01");
  expect(steelLive.description).toBe("Steel delivery gate access");
  expect((steelLive.category as Json).categoryId).toBe(logisticsId);
  expect(steelLive.isPublished).toBe(true);

  // 4. Update against the current version; the same version again is stale.
  const updateKey = key("cst-update");
  const updated = await call(page, "PATCH", `/${PROJECT}/constraints/${steelId}`, {
    expectedVersion: steel.version,
    currentUpdate: "Gate keys issued to the steel erector",
    idempotencyKey: updateKey,
  });
  expectSafe(updated, 200, updateKey);
  const { record: steelUpdated } = applied(updated, "constraint");
  expect(steelUpdated.version).toBe((steel.version as number) + 1);
  expect(steelUpdated.currentUpdate).toBe("Gate keys issued to the steel erector");

  const staleKey = key("cst-update-stale");
  const stale = await call(page, "PATCH", `/${PROJECT}/constraints/${steelId}`, {
    expectedVersion: steel.version,
    currentUpdate: "A write from a stale screen",
    idempotencyKey: staleKey,
  });
  expectSafe(stale, 409, staleKey);
  expect(errorCode(stale)).toBe("conflict");
  expect((await readConstraint(page, steelId)).body.constraint).toMatchObject({
    version: steelUpdated.version,
    currentUpdate: "Gate keys issued to the steel erector",
  });

  // 5. One representative terminal operation, then readback.
  const closeKey = key("cst-close");
  const closed = await call(page, "POST", `/${PROJECT}/constraints/${steelId}/close`, {
    expectedVersion: steelUpdated.version,
    completionDate: "2026-09-20",
    closureCommentary: "Gate access confirmed on site",
    idempotencyKey: closeKey,
  });
  expectSafe(closed, 200, closeKey);
  const { record: steelClosed } = applied(closed, "constraint");
  expect(steelClosed.lifecycleState).toBe("closed");
  expect(steelClosed.completionDate).toBe("2026-09-20");
  const closedRead = await readConstraint(page, steelId);
  expectSafe(closedRead, 200);
  expect((closedRead.body.constraint as Json).status).toBe("closed");
  expect((closedRead.body.constraint as Json).version).toBe(steelClosed.version);

  // 6. A Draft, then its Publish. Filed under the Category this journey
  // created rather than the seeded one: `stack.sh` inserts the seeded `1.01`
  // and `1.02` rows directly, without advancing that Category's code
  // allocator, so a Publish there would be issued `1.01` again and collide
  // with the seed. A Category whose every code the service itself issued is
  // the honest fixture for the allocator.
  const draftKey = key("cst-draft");
  const drafted = await call(page, "POST", `/${PROJECT}/constraints/drafts`, {
    categoryId: logisticsId,
    description: "Temporary power for the hoist",
    dateIdentified: "2026-09-02",
    dueDate: "2026-10-30",
    bic: [{ kind: "principal" }],
    idempotencyKey: draftKey,
  });
  expectSafe(drafted, 200, draftKey);
  const { record: draft } = applied(drafted, "constraint");
  expect(draft.lifecycleState).toBe("draft");
  const draftId = draft.constraintId as string;

  const releaseKey = key("cst-publish");
  const released = await call(page, "POST", `/${PROJECT}/constraints/${draftId}/publish`, {
    expectedVersion: draft.version,
    idempotencyKey: releaseKey,
  });
  expectSafe(released, 200, releaseKey);
  const { record: releasedRecord } = applied(released, "constraint");
  expect(releasedRecord.constraintId).toBe(draftId);
  expect(releasedRecord.lifecycleState).toBe("identified");
  expect(releasedRecord.constraintCode).toBe("7.02");
  const releasedRead = await readConstraint(page, draftId);
  expectSafe(releasedRead, 200);
  expect((releasedRead.body.constraint as Json).status).toBe("identified");
  expect((releasedRead.body.constraint as Json).version).toBe(releasedRecord.version);
});

test("a record addressed through another owned Project is not found and not changed", async ({
  page,
}) => {
  const before = await readConstraint(page, SEEDED_CONSTRAINT);
  expectSafe(before, 200);
  expect((before.body.constraint as Json).version).toBe(SEEDED_CONSTRAINT_VERSION);

  // The detail read's own not-found through the wrong Project is the reference
  // answer: a mutation there must be indistinguishable from it.
  const readElsewhere = await readConstraint(page, SEEDED_CONSTRAINT, UNCONFIGURED_PROJECT);
  expectSafe(readElsewhere, 404);
  expect(errorCode(readElsewhere)).toBe("not_found");

  const patchKey = key("xprj-update");
  const patched = await call(page, "PATCH", `/${UNCONFIGURED_PROJECT}/constraints/${SEEDED_CONSTRAINT}`, {
    expectedVersion: SEEDED_CONSTRAINT_VERSION,
    description: "Rewritten through the wrong Project",
    idempotencyKey: patchKey,
  });
  expectSafe(patched, 404, patchKey);
  expect(patched.body).toEqual(readElsewhere.body);

  const moveKey = key("xprj-transition");
  const moved = await call(
    page,
    "POST",
    `/${UNCONFIGURED_PROJECT}/constraints/${SEEDED_CONSTRAINT}/transition`,
    { expectedVersion: SEEDED_CONSTRAINT_VERSION, toState: "pending", idempotencyKey: moveKey },
  );
  expectSafe(moved, 404, moveKey);
  expect(moved.body).toEqual(readElsewhere.body);

  const after = await readConstraint(page, SEEDED_CONSTRAINT);
  expectSafe(after, 200);
  expect(after.body.constraint).toMatchObject({
    version: SEEDED_CONSTRAINT_VERSION,
    status: "identified",
    description: "Switchgear submittal outstanding",
  });

  const categories = await activeCategories(page);
  const seeded = categories.find((entry) => entry.categoryId === SEEDED_CATEGORY);
  expect(seeded, "the seeded Category is active before the attempt").toBeTruthy();
  const retireKey = key("xprj-cat-deactivate");
  const retired = await call(
    page,
    "POST",
    `/${UNCONFIGURED_PROJECT}/constraint-categories/${SEEDED_CATEGORY}/deactivate`,
    { expectedVersion: seeded!.version, idempotencyKey: retireKey },
  );
  expectSafe(retired, 404, retireKey);
  expect(errorCode(retired)).toBe("not_found");
  const stillActive = (await activeCategories(page)).find((entry) => entry.categoryId === SEEDED_CATEGORY);
  expect(stillActive).toMatchObject({ state: "active", version: seeded!.version });
});

test("an undeclared or Principal-naming body field is refused before a write", async ({ page }) => {
  const unknownKey = key("refuse-unknown");
  const unknown = await call(page, "PATCH", `/${PROJECT}/constraints/${SEEDED_CONSTRAINT}`, {
    expectedVersion: SEEDED_CONSTRAINT_VERSION,
    description: "Smuggled alongside an undeclared field",
    projectId: UNCONFIGURED_PROJECT,
    idempotencyKey: unknownKey,
  });
  expectSafe(unknown, 400, unknownKey);
  expect(errorCode(unknown)).toBe("invalid_request");

  const principalKey = key("refuse-principal");
  const principal = await call(page, "POST", `/${PROJECT}/constraint-categories`, {
    prefix: "8",
    title: "Claimed for another Principal",
    principalId: "synthetic-b",
    idempotencyKey: principalKey,
  });
  expectSafe(principal, 400, principalKey);
  // `readCleanBody`'s own refusal, ahead of the field map: a caller naming a
  // Principal is told so rather than being told the field is merely unknown.
  expect(errorCode(principal)).toBe("caller_supplied_principal");

  // Neither refusal reached the service: the record and the scheme are as seeded.
  const after = await readConstraint(page, SEEDED_CONSTRAINT);
  expect((after.body.constraint as Json).version).toBe(SEEDED_CONSTRAINT_VERSION);
  const scheme = await activeCategories(page);
  expect(scheme.some((entry) => entry.title === "Claimed for another Principal")).toBe(false);
});
