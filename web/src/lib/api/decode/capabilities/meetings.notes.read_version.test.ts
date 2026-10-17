// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/python/success.json";
import { decodeMeetingsNotesReadVersion } from "./meetings.notes.read_version";

const canonical = fixtures["meetings.notes.read_version"];
type Json = Record<string, unknown>;
function payload(): Json & { note: Json } { return structuredClone(canonical) as Json & { note: Json }; }
const decode = decodeMeetingsNotesReadVersion;

describe("meetings.notes.read_version strict canonical success", () => {
  it("decodes a note version with and without a body", () => {
    expect(decode(canonical)).toEqual({ ok: true, value: canonical });
    const metadata = payload();
    delete metadata.note.body_markdown;
    expect(decode(metadata)).toEqual({ ok: true, value: metadata });
    expect(decode(metadata).ok && "body_markdown" in (decode(metadata) as { value: { note: Json } }).value.note).toBe(false);
  });

  it("refuses an unknown key", () => {
    for (const target of ["top", "note"] as const) {
      for (const key of ["unexpected", "principal_id", "passage_sha256", "body"]) {
        const value = payload();
        (target === "top" ? value : value.note)[key] = "synthetic-private";
        expect(decode(value).ok, `${target}.${key}`).toBe(false);
      }
    }
  });

  it("requires every other key and refuses a body that is not the counted text", () => {
    for (const key of Object.keys(canonical.note).filter((name) => name !== "body_markdown")) {
      const value = payload(); delete value.note[key];
      expect(decode(value).ok, key).toBe(false);
    }
    const missing = payload(); delete (missing as Json).evidence_availability;
    expect(decode(missing).ok).toBe(false);
    const empty = payload(); empty.note.body_markdown = "";
    expect(decode(empty).ok).toBe(false);
    const miscounted = payload(); miscounted.note.body_markdown = "Synthetic";
    expect(decode(miscounted).ok).toBe(false);
    const availability = payload(); availability.evidence_availability = "archived";
    expect(decode(availability).ok).toBe(false);
  });
});
