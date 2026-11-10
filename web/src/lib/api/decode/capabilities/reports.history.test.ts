// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsHistory } from "./reports.history";
import { canonicalFixture, expectClosedContract } from "./_general-report-test-kit";

const versions = canonicalFixture("reports.history");

/** A `lifecycle` page: the versions page's root facts with lifecycle items. */
const lifecycle = {
  ...versions,
  lifecycle_state: "archived",
  lifecycle_revision: 1,
  held: false,
  entries: "lifecycle",
  items: [
    {
      event_id: "grlev_aaaaaaaa11111111",
      lifecycle_revision: 1,
      operation: "archive",
      prior_state: "active",
      resulting_state: "archived",
      reason: null,
      transitioned_at: "2026-08-09T12:00:00.000Z",
    },
  ],
  next_cursor: "grlev_aaaaaaaa11111111",
};

describe("reports.history closed success (Python _general_history_payload)", () => {
  it("accepts the committed versions page and refuses every malformed variant", () => {
    // items[1] carries the manifest include_manifests asked for: data, not contract.
    expectClosedContract(decodeReportsHistory, versions, ["items.1.manifest"], ["items.1.manifest"]);
  });
  it("decodes held as a boolean and never coerces it", () => {
    const decoded = decodeReportsHistory(versions);
    expect(decoded.ok && decoded.value.held).toBe(true);
    expect(decodeReportsHistory({ ...versions, held: "true" }).ok).toBe(false);
    expect(decodeReportsHistory({ ...versions, held: 1 }).ok).toBe(false);
  });
  it("accepts a lifecycle page and refuses every malformed variant of it", () => {
    expectClosedContract(decodeReportsHistory, lifecycle);
  });
  it("refuses items that do not match the page's own entries", () => {
    expect(decodeReportsHistory({ ...versions, entries: "lifecycle" }).ok).toBe(false);
    expect(decodeReportsHistory({ ...lifecycle, entries: "versions" }).ok).toBe(false);
    expect(decodeReportsHistory({ ...versions, entries: "events" }).ok).toBe(false);
  });
  it("refuses a manifest that is not an object and a body in a version item", () => {
    const items = versions.items as Record<string, unknown>[];
    expect(decodeReportsHistory({ ...versions, items: [{ ...items[1], manifest: [] }] }).ok).toBe(false);
    expect(decodeReportsHistory({ ...versions, items: [{ ...items[0], body: "x" }] }).ok).toBe(false);
  });
});
