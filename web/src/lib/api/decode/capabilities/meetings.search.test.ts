// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/python/success.json";
import { decodeMeetingsSearch } from "./meetings.search";

const canonical = fixtures["meetings.search"];
function payload(): Record<string, unknown> { return structuredClone(canonical); }
type Path = readonly (string | number)[];
function at(input: Record<string, unknown>, path: Path): Record<string, unknown> {
  let value: unknown = input;
  for (const key of path) value = (value as Record<string | number, unknown>)[key];
  return value as Record<string, unknown>;
}
function objects(value: unknown, path: Path = []): Path[] {
  if (Array.isArray(value)) return value.flatMap((item, index) => objects(item, [...path, index]));
  if (value === null || typeof value !== "object") return [];
  return [path, ...Object.entries(value).flatMap(([key,item]) => objects(item, [...path,key]))];
}
function leaves(value: unknown, path: Path = []): {path: Path; value: unknown}[] {
  if (Array.isArray(value)) return value.flatMap((item, index) => leaves(item, [...path,index]));
  if (value !== null && typeof value === "object") return Object.entries(value).flatMap(([key,item]) => leaves(item,[...path,key]));
  return [{path, value}];
}
function replace(input: Record<string, unknown>, path: Path, value: unknown) {
  at(input,path.slice(0,-1))[String(path[path.length-1])] = value;
  return input;
}
const decode = decodeMeetingsSearch;

describe("meetings.search strict canonical success", () => {
  it("accepts and preserves the canonical Python serializer fixture", () => {
    expect(decode(canonical)).toEqual({ok:true,value:canonical});
  });
  it("requires every canonical key at every object depth, including nullable keys", () => {
    for (const path of objects(canonical)) {
      for (const key of Object.keys(at(payload(),path))) {
        const value = payload(); delete at(value,path)[key];
        expect(decode(value).ok, `${path.join(".")}.${key}`).toBe(false);
      }
    }
  });
  it("rejects wrong primitive types without coercion", () => {
    for (const leaf of leaves(canonical)) {
      const wrong = typeof leaf.value === "string" ? 17 : typeof leaf.value === "number" ? "1" : typeof leaf.value === "boolean" ? "false" : {};
      expect(decode(replace(payload(),leaf.path,wrong)).ok,leaf.path.join(".")).toBe(false);
    }
    expect(decode([]).ok).toBe(false);
    for (const path of objects(canonical).filter((path) => path.length > 0)) {
      expect(decode(replace(payload(),path,[])).ok,path.join(".")).toBe(false);
    }
  });
  it("refuses top-level and nested unknown and private/arbitration fields", () => {
    for (const path of objects(canonical)) {
      for (const key of ["unexpected", "principal_id", "owner_principal_id", "request_digest", "storage_path", "safe_details", "text", "owner_id", "uri"]) {
        const value = payload(); at(value,path)[key] = "synthetic-private";
        expect(decode(value).ok, `${path.join(".")}.${key}`).toBe(false);
      }
    }
  });
  it("distinguishes required nullable fields from omitted and undefined", () => {
    for (const leaf of leaves(canonical).filter((leaf) => leaf.value === null)) {
      expect(decode(replace(payload(),leaf.path,null)).ok).toBe(true);
      expect(decode(replace(payload(),leaf.path,undefined)).ok,leaf.path.join(".")).toBe(false);
    }
  });
  it("validates canonical identifiers, enums, aware calendar timestamps and safe integers", () => {
    const enumKeys = ["state", "status", "availability", "response_status", "action", "actor", "outcome", "media_type", "relationship_status_code"];
    for (const leaf of leaves(canonical)) {
      const key = String(leaf.path[leaf.path.length-1]);
      let wrong: unknown[] = [];
      if (enumKeys.includes(key)) wrong = ["invalid-enum"];
      if (typeof leaf.value === "string" && /^[a-z]+_[A-Za-z0-9]{8,64}$/.test(leaf.value)) wrong = ["wrong_aaaaaaaa11111111", leaf.value+"\n", leaf.value.slice(0,leaf.value.indexOf("_")+1)+"short", leaf.value+"!", leaf.value.split("_")[0]+"_"+"a".repeat(65)];
      if (key.endsWith("_at") && typeof leaf.value === "string") wrong = ["2026-02-30T12:00:00Z", "2026-08-09T12:00:00", "2026-08-09T24:00:00Z", "2026-08-09T12:60:00Z", "2026-08-09T12:00:00+24:00", leaf.value+"\n"];
      if (typeof leaf.value === "number") wrong = [-1, 1.5, Number.MAX_SAFE_INTEGER+1, Number.NaN, Number.POSITIVE_INFINITY];
      if (typeof leaf.value === "number" && (key === "version" || key === "version_number" || key === "series_version" || key === "after_version" || key === "byte_size")) wrong.push(0);
      if (key === "content_sha256") wrong = ["A".repeat(64), "a".repeat(63), "a".repeat(64)+"\n", "g".repeat(64)];
      for (const invalid of wrong) expect(decode(replace(payload(),leaf.path,invalid)).ok,leaf.path.join(".")).toBe(false);
    }
  });
  it("requires a page array and leaves partial/cursor disclosure to the envelope", () => {
    expect(decode({meetings:[]})).toEqual({ok:true,value:{meetings:[]}});
    expect(decode({meetings:null}).ok).toBe(false);
    expect(decode({...canonical,next_cursor:"opaque"}).ok).toBe(false);
    expect(decode(replace(payload(),["meetings",0,"attendee_count"],101)).ok).toBe(false);
    expect(decode(replace(payload(),["meetings",0,"attachment_count"],51)).ok).toBe(false);
    expect(decode(replace(payload(),["meetings",0,"series_version"],0)).ok).toBe(false);
    expect(decode(replace(payload(),["meetings",0,"description"],"private")).ok).toBe(false);
  });
  it("preserves canonical nonblank content and Python whitespace semantics", () => {
    const paths: Path[] = [["meetings", 0, "title"], ["meetings", 0, "series_title"]];
    // Python str.isspace includes NEL and C0 separators, and excludes FEFF.
    const spaces = ["\u0009", "\u000a", "\u000b", "\u000c", "\u000d", "\u001c", "\u001d", "\u001e", "\u001f", " ", "\u0085", "\u00a0", "\u1680", ...Array.from({length:11}, (_, index) => String.fromCodePoint(0x2000+index)), "\u2028", "\u2029", "\u202f", "\u205f", "\u3000"];
    for (const path of paths) {
      for (const content of ["\ufeff", "\u0085\ufeff\u001c", "  retained content\u0085", "😀"]) {
        const value = replace(payload(), path, content);
        expect(decode(value), path.join(".")).toEqual({ok:true,value});
      }
      for (const content of ["", ...spaces, spaces.join("")]) {
        expect(decode(replace(payload(), path, content)).ok, path.join(".")).toBe(false);
      }
    }
  });
  it("counts bounded titles and notes in Unicode code points", () => {
    const bounds: {path: Path; maximum: number}[] = [{"path": ["meetings", 0, "title"], "maximum": 200}, {"path": ["meetings", 0, "series_title"], "maximum": 200}];
    for (const {path, maximum} of bounds) {
      const value = replace(payload(), path, "😀".repeat(maximum));
      expect(decode(value), path.join(".")).toEqual({ok:true,value});
      expect(decode(replace(payload(), path, "😀".repeat(maximum+1))).ok, path.join(".")).toBe(false);
    }
  });
  it("compares aware Meeting ranges at canonical microsecond precision", () => {
    const start: Path = ["meetings", 0, "start_at"];
    const end: Path = ["meetings", 0, "end_at"];
    const cases = [
      ["2026-08-09T12:00:00.000001Z", "2026-08-09T12:00:00.000002Z", true],
      ["2026-08-09T12:00:00.000002Z", "2026-08-09T12:00:00.000001Z", false],
      ["2026-08-09T12:00:00.000002Z", "2026-08-09T12:00:00.000002Z", true],
      ["2026-08-09T12:00:00.000002Z", "2026-08-09T13:00:00.000002+01:00", true],
      ["2026-08-09T12:00:00.000002Z", "2026-08-09T13:00:00.000001+01:00", false],
      ["2026-08-09T11:00:00.000002-01:00", "2026-08-09T12:00:00.000003Z", true],
    ] as const;
    for (const [startAt, endAt, accepted] of cases) {
      const value = replace(replace(payload(), start, startAt), end, endAt);
      expect(decode(value).ok, `${startAt} -> ${endAt}`).toBe(accepted);
      if (accepted) expect(decode(value)).toEqual({ok:true,value});
    }
  });
});
