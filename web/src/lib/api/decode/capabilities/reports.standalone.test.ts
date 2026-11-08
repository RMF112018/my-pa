// @vitest-environment node
/**
 * WP07 Amendment A1: the standalone-plane decoders accept the committed
 * Python-built variants (fixtures/python/reports.standalone.json) and refuse
 * malformed ones; the legacy `DECODERS` entries still refuse every one of them.
 */
import { describe, expect, it } from "vitest";
import variants from "../fixtures/python/reports.standalone.json";
import legacy from "../fixtures/python/success.json";
import { DECODERS } from "../index";
import { STANDALONE_REPORT_DECODERS, type StandaloneReportCapability } from "../standalone";
import {
  decodeStandaloneReportList,
  decodeStandaloneReportRead,
  decodeStandaloneReportSearch,
} from "./reports.standalone";
import { expectClosedContract } from "./_general-report-test-kit";

type Json = Record<string, unknown>;
const variant = (name: keyof typeof variants): Json => structuredClone(variants[name]) as Json;
function without(input: Json, key: string): Json {
  const copy = { ...input };
  delete copy[key];
  return copy;
}
const capabilityOf = (name: string) => name.split(".").slice(0, 2).join(".") as StandaloneReportCapability;

describe("standalone report variants (Python _general_read_payload / catalog items)", () => {
  it("decodes every committed variant through STANDALONE_REPORT_DECODERS, unchanged", () => {
    const names = Object.keys(variants);
    expect(names.length).toBeGreaterThan(0);
    for (const name of names) {
      const payload = variant(name as keyof typeof variants);
      expect(STANDALONE_REPORT_DECODERS[capabilityOf(name)](payload), name).toEqual({ ok: true, value: payload });
    }
  });

  it("is never accepted by the legacy DECODERS entries (Intelligence keeps base behaviour)", () => {
    for (const name of Object.keys(variants)) {
      expect(DECODERS[capabilityOf(name)](variant(name as keyof typeof variants)).ok, name).toBe(false);
    }
  });

  it("does not accept the legacy pipeline shapes", () => {
    for (const capability of ["reports.read", "reports.list", "reports.search"] as const) {
      expect(STANDALONE_REPORT_DECODERS[capability](legacy[capability]).ok, capability).toBe(false);
    }
  });

  it("holds every read variant closed (metadata, manifest and json data are data)", () => {
    // A textual read without its body is exactly an include_body=false read.
    expectClosedContract(decodeStandaloneReportRead, variant("reports.read.markdown"), ["metadata"], ["content.body"]);
    for (const name of [
      "reports.read.mixed",
      "reports.read.gzip",
      "reports.read.omitted",
      "reports.read.no_body",
    ] as const) {
      expectClosedContract(decodeStandaloneReportRead, variant(name), ["metadata", "content.data"]);
    }
    expectClosedContract(
      decodeStandaloneReportRead,
      variant("reports.read.json"),
      ["metadata", "manifest", "content.data"],
      ["manifest", "content.data"],
    );
  });

  it("decodes held as a boolean and the omitted read's two read_chunk pointers", () => {
    const decoded = decodeStandaloneReportRead(variant("reports.read.omitted"));
    expect(decoded.ok).toBe(true);
    if (!decoded.ok) return;
    expect(decoded.value.held).toBe(true);
    expect(decoded.value.content.body_omitted).toBe("exceeds_response_bound");
    expect(decoded.value.content.body_chunked_read?.part).toBe("decoded");
    expect(decoded.value.content.encoded_omitted).toBe("exceeds_response_bound");
    expect(decoded.value.content.encoded_chunked_read?.part).toBe("original");
    expect(decodeStandaloneReportRead({ ...variant("reports.read.omitted"), held: "true" }).ok).toBe(false);
  });

  it("refuses a body half that does not match the format or the omission rules", () => {
    const markdown = variant("reports.read.markdown");
    const content = markdown.content as Json;
    const read = (patch: Json) => decodeStandaloneReportRead({ ...markdown, content: { ...content, ...patch } });
    expect(read({ data: { k: 1 } }).ok).toBe(false); // markdown carries no data
    expect(read({ body: 7 }).ok).toBe(false);
    expect(read({ body_omitted: "exceeds_response_bound" }).ok).toBe(false); // omitted beside a body
    expect(read({ encoded: "AAAA" }).ok).toBe(false); // identity has no encoded
    const json = variant("reports.read.json");
    expect(decodeStandaloneReportRead({ ...json, content: { ...(json.content as Json), body: "x" } }).ok).toBe(false);
    const mixed = variant("reports.read.mixed");
    expect(decodeStandaloneReportRead({ ...mixed, content: without(mixed.content as Json, "data") }).ok).toBe(false);
    const omitted = variant("reports.read.omitted");
    const omittedContent = omitted.content as Json;
    expect(
      decodeStandaloneReportRead({ ...omitted, content: without(omittedContent, "body_chunked_read") }).ok,
    ).toBe(false);
    expect(
      decodeStandaloneReportRead({
        ...omitted,
        content: { ...omittedContent, body_chunked_read: { ...(omittedContent.body_chunked_read as Json), part: "original" } },
      }).ok,
    ).toBe(false);
    const gzip = variant("reports.read.gzip");
    expect(decodeStandaloneReportRead({ ...gzip, content: without(gzip.content as Json, "encoded") }).ok).toBe(false);
    const noBody = variant("reports.read.no_body");
    expect(
      decodeStandaloneReportRead({ ...noBody, content: { ...(noBody.content as Json), body: "x", extra: 1 } }).ok,
    ).toBe(false);
  });

  it("holds the catalog pages closed and discriminates items by their own plane", () => {
    expectClosedContract(decodeStandaloneReportList, variant("reports.list.standalone"));
    expectClosedContract(decodeStandaloneReportList, variant("reports.list.all"));
    expectClosedContract(decodeStandaloneReportSearch, variant("reports.search.all"));
    const all = variant("reports.list.all");
    const items = all.items as Json[];
    // The standalone plane never lists a pipeline artifact.
    expect(decodeStandaloneReportList({ ...all, plane: "standalone" }).ok).toBe(false);
    expect(decodeStandaloneReportList({ ...all, plane: "intelligence" }).ok).toBe(false);
    expect(decodeStandaloneReportList({ ...all, items: [{ ...items[0], plane: "intelligence" }] }).ok).toBe(false);
    // A list item has no snippet; a search item must have one.
    expect(decodeStandaloneReportList({ ...all, items: [{ ...items[0], snippet: "x" }] }).ok).toBe(false);
    const search = variant("reports.search.all");
    const unsnipped = without((search.items as Json[])[0], "snippet");
    expect(decodeStandaloneReportSearch({ ...search, items: [unsnipped] }).ok).toBe(false);
    expect(decodeStandaloneReportList({ ...all, items: [{ ...items[0], held: 0 }] }).ok).toBe(false);
  });
});
