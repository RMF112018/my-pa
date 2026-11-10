// @vitest-environment node
/**
 * WP08 C-WP07 R1 #4 / #6: the identity-key check the report forms share with
 * the BFF guard, the read answer's closed `identity_keys_withheld` flag, and
 * the JSON number scanner (source text) with its parsed-value counterpart.
 */
import { describe, expect, it } from "vitest";
import standalone from "@/lib/api/decode/fixtures/python/reports.standalone.json";
import { FORBIDDEN_IDENTITY_FIELDS } from "@/contracts/identity";
import { rejectCallerSuppliedPrincipal } from "@/lib/auth/claims";
import {
  CONTENT_LOCK_MESSAGES,
  IDENTITY_KEYS_MESSAGE,
  UNSAFE_NUMBER_MESSAGE,
  contentLockOf,
  decodeReportReadAnswer,
  hasUnsafeJsonNumber,
  hasUnsafeNumberValue,
  holdsIdentityKeys,
  jsonSubmitProblem,
  losesStrippedIdentityKeys,
} from "./content-guards";

describe("holdsIdentityKeys (the BFF's own check, as a predicate)", () => {
  it.each(FORBIDDEN_IDENTITY_FIELDS.map((key) => [key]))("refuses %s at any depth", (key) => {
    expect(holdsIdentityKeys({ [key]: "x" })).toBe(true);
    expect(holdsIdentityKeys({ rows: [{ nested: { [key]: 1 } }] })).toBe(true);
    expect(holdsIdentityKeys([[{ [key]: null }]])).toBe(true);
  });

  it("answers exactly as rejectCallerSuppliedPrincipal does", () => {
    const samples: unknown[] = [
      { rows: [1, 2], ok: true }, { principal: "x", id: "y", "principal_id ": 1 }, ["principal_id"],
      "principal_id", 42, null, { a: { tid: 1 } }, { oid: [] },
    ];
    for (const sample of samples) {
      let thrown = false;
      try { rejectCallerSuppliedPrincipal(sample); } catch { thrown = true; }
      expect(holdsIdentityKeys(sample)).toBe(thrown);
    }
  });

  it("names the refused keys in its message without any data value", () => {
    for (const key of FORBIDDEN_IDENTITY_FIELDS) expect(IDENTITY_KEYS_MESSAGE).toContain(key);
  });
});

describe("losesStrippedIdentityKeys (what publicResult removes)", () => {
  it("is true only for principal_id / principalId keys, at any depth", () => {
    expect(losesStrippedIdentityKeys({ principal_id: 1 })).toBe(true);
    expect(losesStrippedIdentityKeys([{ deep: { principalId: "x" } }])).toBe(true);
    expect(losesStrippedIdentityKeys({ tid: 1, oid: 2 })).toBe(false);
    expect(losesStrippedIdentityKeys({ rows: ["principal_id"] })).toBe(false);
    expect(losesStrippedIdentityKeys(undefined)).toBe(false);
  });
});

describe("decodeReportReadAnswer", () => {
  const read = standalone["reports.read.json"] as Record<string, unknown>;

  it("decodes a read without the flag exactly as the gateway read", () => {
    const decoded = decodeReportReadAnswer(structuredClone(read));
    expect(decoded.ok).toBe(true);
    expect(decoded.ok && "identity_keys_withheld" in decoded.value).toBe(false);
  });

  it("keeps identity_keys_withheld: true", () => {
    const decoded = decodeReportReadAnswer({ ...structuredClone(read), identity_keys_withheld: true });
    expect(decoded).toMatchObject({ ok: true, value: { identity_keys_withheld: true, report_id: read.report_id } });
  });

  it.each([[false], ["true"], [1], [null]])("refuses identity_keys_withheld: %j", (flag) => {
    expect(decodeReportReadAnswer({ ...structuredClone(read), identity_keys_withheld: flag }).ok).toBe(false);
  });

  it("still refuses a read the gateway decoder refuses", () => {
    expect(decodeReportReadAnswer({ identity_keys_withheld: true }).ok).toBe(false);
    expect(decodeReportReadAnswer({ ...structuredClone(read), extra: 1 }).ok).toBe(false);
  });
});

describe("hasUnsafeJsonNumber (source text)", () => {
  it.each([
    ["9007199254740991", false],
    ["-9007199254740991", false],
    ["9007199254740992", true],
    ["-9007199254740993", true],
    ["12345678901234567890", true],
    ['{"a":[1,2,{"b":99999999999999999999}]}', true],
    ['{"id":"99999999999999999999"}', false],
    ['{"k\\"99999999999999999999":1}', false],
    ['["\\\\", 99999999999999999999]', true],
    ["1e400", true],
    ["-1E400", true],
    ["1e20", true],
    ["1.5e3", false],
    ["0.1", false],
    ["1.0", false],
    ["0.30000000000000004", false],
    ["1.00000000000000001", true],
    ["-0", false],
    ["0e999", false],
    ["1e-400", true],
    ['{"rows":[1,2],"ok":true,"n":null}', false],
    ["", false],
  ])("%s -> %s", (text, unsafe) => {
    expect(hasUnsafeJsonNumber(text)).toBe(unsafe);
  });
});

describe("hasUnsafeNumberValue (already parsed)", () => {
  it("flags numbers beyond the safe range and non-finite numbers, at any depth", () => {
    expect(hasUnsafeNumberValue(JSON.parse('{"a":[{"b":9007199254740993}]}'))).toBe(true);
    expect(hasUnsafeNumberValue([Number.POSITIVE_INFINITY])).toBe(true);
    expect(hasUnsafeNumberValue({ a: Number.MAX_SAFE_INTEGER, b: -Number.MAX_SAFE_INTEGER, c: 0.1, d: "99999999999999999999" })).toBe(false);
  });
});

describe("the forms' checks", () => {
  it("jsonSubmitProblem: identity keys first, then unsafe numbers, else null", () => {
    expect(jsonSubmitProblem('{"principal_id":1}', { principal_id: 1 })).toBe(IDENTITY_KEYS_MESSAGE);
    const big = '{"n":12345678901234567890}';
    expect(jsonSubmitProblem(big, JSON.parse(big))).toBe(UNSAFE_NUMBER_MESSAGE);
    expect(jsonSubmitProblem('{"n":1}', { n: 1 })).toBeNull();
  });

  it("contentLockOf: the read flag, the identity check, then numbers (text when it was read in chunks)", () => {
    expect(contentLockOf({ withheld: true, data: { rows: [] } })).toBe("identity");
    expect(contentLockOf({ data: { a: { tid: "x" } } })).toBe("identity");
    expect(contentLockOf({ data: JSON.parse("[9007199254740993]") })).toBe("precision");
    expect(contentLockOf({ data: [1], text: '{"body":"9007199254740993","data":[1.00000000000000001]}' })).toBe("precision");
    expect(contentLockOf({ data: { rows: [1] } })).toBeNull();
    expect(contentLockOf({})).toBeNull();
    expect(Object.keys(CONTENT_LOCK_MESSAGES).sort()).toEqual(["identity", "precision"]);
  });
});
