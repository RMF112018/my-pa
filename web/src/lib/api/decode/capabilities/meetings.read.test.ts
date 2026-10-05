// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/python/success.json";
import { decodeMeetingsRead } from "./meetings.read";
import { isCanonicalTimezoneKey } from "../../work-route";

const canonical = fixtures["meetings.read"];
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
const decode = decodeMeetingsRead;

// Canonical domain validator, UpdateMeeting and MeetingView serializer agree
// on these URL cases; accepted values remain byte-for-byte caller content.
const canonicalMeetingUrls = [
  ["ordinary_https", "https://example.invalid/ab", true],
  ["internal_nbsp", "https://example.invalid/a\u00a0b", true],
  ["internal_feff", "https://example.invalid/a\ufeffb", true],
  ["trailing_feff", "https://example.invalid/ab\ufeff", true],
  ["unicode_netloc", "https://exa\u00a0mple.invalid/ab", true],
  ["ipvfuture", "https://[v1.example]/ab", true],
  ["unicode_scheme", "\ufeffhttps://example.invalid/ab", false],
  ["ascii_space", "https://example.invalid/a b", false],
  ["http", "http://example.invalid/ab", false],
  ["credentials", "https://user:pass@example.invalid/ab", false],
  ["empty_credentials", "https://@example.invalid/ab", false],
  ["outer_nbsp", "https://example.invalid/ab\u00a0", false],
  ["port_overflow", "https://example.invalid:65536/ab", false],
  ["empty_port", "https://example.invalid:/ab", true],
  ["ipv6", "https://[::1]/ab", true],
  ["bad_bracket", "https://[broken]/ab", false],
  ["uppercase_scheme", "HTTPS://example.invalid/Ab?b=2&a=1#Raw", true],
  ["outer_nel", "https://example.invalid/a\u0085", false],
  ["internal_nel", "https://example.invalid/a\u0085b", true],
  ["outer_separator", "\u001chttps://example.invalid/", false],
  ["leading_feff", "\ufeffhttps://example.invalid/", false],
  ["ascii_tab", "https://example.invalid/a\tb", false],
  ["ascii_del", "https://example.invalid/a\u007fb", false],
  ["unicode_netloc_fullwidth_letter", "https://\uff45xample.invalid/", true],
  ["nfkc_slash", "https://exam\uff0fple.invalid/", false],
  ["nfkc_colon", "https://example.invalid\uff1a80/", false],
  ["nfkc_at", "https://exam\uff20ple.invalid/", false],
  ["nfkc_hash", "https://exam\uff03ple.invalid/", false],
  ["nfkc_question", "https://exam\uff1fple.invalid/", false],
  ["empty_password", "https://:@example.invalid/", false],
  ["no_hostname", "https:///path", false],
  ["backslash_hostname", "https://exa\\mple.invalid/", true],
  ["port_zero", "https://example.invalid:0/", true],
  ["port_max", "https://example.invalid:65535/", true],
  ["port_leading_zeros", "https://example.invalid:0000080/", true],
  ["port_plus", "https://example.invalid:+80/", false],
  ["port_negative", "https://example.invalid:-1/", false],
  ["port_unicode", "https://example.invalid:\uff18\uff10/", false],
  ["port_two", "https://example.invalid:80:90/", false],
  ["bracketed_ipv4", "https://[127.0.0.1]/", false],
  ["bracket_prefix", "https://abc[::1]/", false],
  ["bracket_suffix", "https://[::1]abc/", false],
  ["unmatched_closing", "https://::1]/", false],
  ["ipvfuture_upper_v", "https://[V1.example]/", false],
  ["ipvfuture_missing_body", "https://[v1.]/", false],
  ["ipvfuture_unicode_body", "https://[vF.a\u00a0b]/", true],
  ["ipv6_scope", "https://[fe80::1%eth0]/", true],
  ["ipv6_unicode_scope", "https://[fe80::1%\u00a0eth]/", true],
  ["ipv6_empty_scope", "https://[fe80::1%]/", false],
  ["ipv6_multiple_scope", "https://[fe80::1%a%b]/", false],
  ["ipv6_ipv4", "https://[::ffff:192.0.2.1]/", true],
  ["ipv6_ipv4_leading_zero", "https://[::ffff:192.000.2.1]/", false],
  ["ipv6_too_many_groups", "https://[1:2:3:4:5:6:7:8:9]/", false],
  ["ipv6_bad_compression", "https://[1:2:3:4:5:6:7:8::]/", false],
  ["path_raw_escapes", "https://example.invalid/a%2Fb\\c?z=%23#frag", true],
  ["limit_2048", "https://example.invalid/" + "a".repeat(2024), true],
  ["limit_2049", "https://example.invalid/" + "a".repeat(2025), false],
  ["unicode_codepoint_limit", "https://example.invalid/" + "\ud83d\ude00".repeat(2024), true],
] as const;

// F4: source-derived Python 3.12 urllib boundary cases; accepted raw text is retained.
const canonicalSeparatorUrls = [
  ["ipvfuture_ls_only", "https://[v1.\u2028]/", true],
  ["ipvfuture_ls_prefix", "https://[v1.\u2028ab]/", true],
  ["ipvfuture_ls_middle", "https://[v1.a\u2028b]/", true],
  ["ipvfuture_ls_suffix", "https://[v1.ab\u2028]/", true],
  ["ipvfuture_ps_only", "https://[v1.\u2029]/", true],
  ["ipvfuture_ps_prefix", "https://[v1.\u2029ab]/", true],
  ["ipvfuture_ps_middle", "https://[v1.a\u2029b]/", true],
  ["ipvfuture_ps_suffix", "https://[v1.ab\u2029]/", true],
  ["ipvfuture_cr_only", "https://[v1.\r]/", false],
  ["ipvfuture_cr_prefix", "https://[v1.\rab]/", false],
  ["ipvfuture_cr_middle", "https://[v1.a\rb]/", false],
  ["ipvfuture_cr_suffix", "https://[v1.ab\r]/", false],
  ["ipvfuture_lf_only", "https://[v1.\n]/", false],
  ["ipvfuture_lf_prefix", "https://[v1.\nab]/", false],
  ["ipvfuture_lf_middle", "https://[v1.a\nb]/", false],
  ["ipvfuture_lf_suffix", "https://[v1.ab\n]/", false],
  ["ipvfuture_ls_version", "https://[v\u20281.ab]/", false],
  ["ipvfuture_ls_before_dot", "https://[v1\u2028.ab]/", false],
  ["url_ls_trailing", "https://[v1.ab]/\u2028", false],
  ["url_ls_path_internal", "https://[v1.ab]/a\u2028b", true],
  ["ipvfuture_ps_version", "https://[v\u20291.ab]/", false],
  ["ipvfuture_ps_before_dot", "https://[v1\u2029.ab]/", false],
  ["url_ps_trailing", "https://[v1.ab]/\u2029", false],
  ["url_ps_path_internal", "https://[v1.ab]/a\u2029b", true],
] as const;

describe("meetings.read strict canonical success", () => {
  it.each(canonicalMeetingUrls)("matches canonical URL case %s and preserves accepted text", (_case, url, accepted) => {
    const value = replace(payload(), ["meeting", "virtual_meeting_url"], url);
    const result = decode(value);
    expect(result.ok).toBe(accepted);
    if (accepted) expect(result).toEqual({ok:true,value});
  });
  it.each(canonicalSeparatorUrls)("matches canonical separator case %s and preserves accepted text", (_case, url, accepted) => {
    const value = replace(payload(), ["meeting", "virtual_meeting_url"], url);
    const result = decode(value);
    expect(result.ok).toBe(accepted);
    if (accepted) expect(result).toEqual({ok:true,value});
  });
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
  it("accepts standalone null series and notes; validates nested identities and enums", () => {
    const value = payload(); const meeting=at(value,["meeting"]);
    meeting.meeting_series_id=null; meeting.series_title=null; meeting.series_version=null; meeting.notes=null;
    expect(decode(value).ok).toBe(true);
    expect(decode(replace(payload(),["meeting","attendees",0,"response_status"],"invalid")).ok).toBe(false);
    expect(decode(replace(payload(),["meeting","attendees",0,"entity_id"],"prj_aaaaaaaa11111111")).ok).toBe(false);
    expect(decode(replace(payload(),["meeting","end_at"],"2026-08-08T12:00:00Z")).ok).toBe(false);
    expect(decode(replace(payload(),["meeting","notes","version_number"],0)).ok).toBe(false);
    expect(decode(replace(payload(),["meeting","timezone_name"],"../Invalid/Zone")).ok).toBe(false);
    expect(decode(replace(payload(),["meeting","attendees"],null)).ok).toBe(false);
    expect(decode(replace(payload(),["meeting","virtual_meeting_url"],"http://example.invalid")).ok).toBe(false);
  });
  it("accepts bounded canonical ZoneInfo keys without duplicating host availability", () => {
    for (const value of ["Factory", "posix/UTC", "Invalid/Zone", "a".repeat(64), "😀".repeat(64)]) {
      expect(decode(replace(payload(),["meeting","timezone_name"],value)).ok, value).toBe(true);
      expect(decode(replace(payload(),["meeting","timezone_name"],value)).ok).toBe(isCanonicalTimezoneKey(value));
    }
    for (const value of [null, 1, "", "a".repeat(65), "😀".repeat(65), " UTC", "UTC\u001c", "/UTC", "posix//UTC", "./UTC", "posix/../UTC", "posix\\UTC", "UTC\u0000", "\ud800"]) {
      expect(decode(replace(payload(),["meeting","timezone_name"],value)).ok).toBe(false);
      expect(decode(replace(payload(),["meeting","timezone_name"],value)).ok).toBe(isCanonicalTimezoneKey(value));
    }
  });
  it("preserves canonical nonblank content and Python whitespace semantics", () => {
    const paths: Path[] = [["meeting", "title"], ["meeting", "series_title"], ["meeting", "notes", "body_markdown"]];
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
    const bounds: {path: Path; maximum: number}[] = [{"path": ["meeting", "title"], "maximum": 200}, {"path": ["meeting", "series_title"], "maximum": 200}, {"path": ["meeting", "notes", "body_markdown"], "maximum": 100000}];
    for (const {path, maximum} of bounds) {
      const value = replace(payload(), path, "😀".repeat(maximum));
      expect(decode(value), path.join(".")).toEqual({ok:true,value});
      expect(decode(replace(payload(), path, "😀".repeat(maximum+1))).ok, path.join(".")).toBe(false);
    }
  });
  it("compares aware Meeting ranges at canonical microsecond precision", () => {
    const start: Path = ["meeting", "start_at"];
    const end: Path = ["meeting", "end_at"];
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
