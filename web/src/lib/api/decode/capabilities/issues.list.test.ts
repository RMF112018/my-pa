// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/python/success.json";
import { decodeIssuesList } from "./issues.list";

/* `issues.list` (S1 section 7.1; S3 section 6.4 adds `restricted`), from the committed Python dump. */
const canonical = fixtures["issues.list"];
type Json = Record<string, unknown>;
function payload(): Json { return structuredClone(canonical) as Json; }

describe("issues.list strict canonical success", () => {
  it("decodes a keyset page of Issues", () => {
    expect(decodeIssuesList(canonical)).toEqual({ ok: true, value: canonical });
    const last = payload(); last.next_cursor = null;
    expect(decodeIssuesList(last).ok).toBe(true);
  });

  it("refuses an unknown key, a description and a malformed cursor", () => {
    const extra = payload(); extra.total = 2;
    expect(decodeIssuesList(extra).ok).toBe(false);
    const description = payload(); (description.issues as Json[])[0]!.description = "x";
    expect(decodeIssuesList(description).ok).toBe(false);
    for (const cursor of ["prj_aaaaaaaa11111111", "eyJ2IjoxfQ", 3]) {
      const value = payload(); value.next_cursor = cursor;
      expect(decodeIssuesList(value).ok, String(cursor)).toBe(false);
    }
  });
});
