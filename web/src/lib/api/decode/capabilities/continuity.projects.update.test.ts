// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/python/success.json";
import { decodeContinuityProjectsUpdate } from "./continuity.projects.update";

const canonical = fixtures["continuity.projects.update"];
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
const decode = decodeContinuityProjectsUpdate;

describe("continuity.projects.update strict canonical success", () => {
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
  it("validates nonempty canonical participation rows and closed nullable timestamps", () => {
    const value = payload(); value.canonical_participations = [{participant_entity_id:"ent_aaaaaaaa11111111",role_code:null,relationship_status_code:"active",participation_id:"eppt_aaaaaaaa11111111",state:"active"}];
    expect(decode(value).ok).toBe(true);
    (value.canonical_participations as Record<string,unknown>[])[0].principal_id = "private";
    expect(decode(value).ok).toBe(false);
    expect(decode(replace(payload(),["closed_at"],"2026-02-30T12:00:00Z")).ok).toBe(false);
  });
});
