/**
 * The standalone-plane answers of `reports.read`, `reports.list` and
 * `reports.search` (WP07 contract Amendment A1), closed.
 *
 * These are NOT the legacy `DECODERS` entries: those stay the pipeline shapes
 * byte for byte, so every Intelligence consumer keeps its base behaviour. These
 * decoders are reached only through `STANDALONE_REPORT_DECODERS` and
 * `invokeStandaloneReports` (lib/api/gateway.ts), by the /api/reports routes.
 *
 * - read: Python `service._general_read_payload` (a `grpt_` read).
 * - list/search: the catalog handler's page `{plane, items, next_cursor}` with
 *   items discriminated by their own `plane`: `_standalone_catalog_item` or (on
 *   the `all` plane only) `_intelligence_catalog_item`; search items carry a
 *   `snippet`, list items never do.
 *
 * `held` is the only hold datum and is decoded as a boolean. Body and data are
 * returned as decoded; nothing here logs or echoes them.
 */
import { closed, isRecord, ok } from "../primitives";
import type { Decoder } from "../types";
import {
  arrayOf,
  boolean,
  checked,
  digest,
  enumeration,
  identifier,
  integer,
  nullable,
  strictObject,
  text,
  timestamp,
  type Decoded,
} from "./continuity.projects.create";
import {
  REPORT_CHANGE_KINDS,
  REPORT_CONTENT_ENCODINGS,
  REPORT_CONTENT_FORMATS,
  REPORT_LIFECYCLE_STATES,
  REPORT_STORAGE_KINDS,
  STANDALONE_PLANE,
  base64Chunk,
  count,
  jsonRecord,
  positiveCount,
  reportContentId,
  reportCreator,
  reportId,
  reportVersionId,
  type ReportContentEncoding,
  type ReportContentFormat,
} from "./_general-report-helpers";
import {
  ARTIFACT_KIND_PATTERN,
  ARTIFACT_STATES,
  INTELLIGENCE_STAGES,
} from "./reports.read";

const invalid = () => closed("upstream_contract_invalid", "Invalid capability success contract");

const calendarDate = checked(text(10, 10), (value) => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return y >= 1 && m >= 1 && m <= 12 && d >= 1 && d <= days[m - 1];
});

// --- reports.read (standalone) ------------------------------------------------

/** WP06 T16: where an omitted body or `encoded` is read, verified, in ranges. */
function chunkedReadPointer<const P extends "decoded" | "original">(part: P) {
  return strictObject({
    capability: enumeration(["reports.transfer.read_chunk"] as const),
    part: enumeration([part] as const),
    byte_count: count,
    sha256: digest,
  });
}
const bodyPointer = chunkedReadPointer("decoded");
const encodedPointer = chunkedReadPointer("original");
export type StandaloneChunkedReadPointer = Decoded<typeof bodyPointer> | Decoded<typeof encodedPointer>;

const contentFacts = strictObject({
  content_id: reportContentId,
  format: enumeration(REPORT_CONTENT_FORMATS),
  encoding: enumeration(REPORT_CONTENT_ENCODINGS),
  storage_kind: enumeration(REPORT_STORAGE_KINDS),
  decoded_sha256: digest,
  decoded_byte_count: count,
  canonical_sha256: nullable(digest),
  original_sha256: digest,
  original_byte_count: count,
});
type ContentFacts = Decoded<typeof contentFacts>;
const FACT_KEYS = [
  "content_id",
  "format",
  "encoding",
  "storage_kind",
  "decoded_sha256",
  "decoded_byte_count",
  "canonical_sha256",
  "original_sha256",
  "original_byte_count",
] as const;
const BODY_KEYS = ["body", "data", "body_omitted", "body_chunked_read"] as const;
const ENCODED_KEYS = ["encoded", "encoded_omitted", "encoded_chunked_read"] as const;

export type StandaloneReportContent = ContentFacts & {
  readonly body?: string;
  readonly data?: unknown;
  readonly body_omitted?: "exceeds_response_bound";
  readonly body_chunked_read?: Decoded<typeof bodyPointer>;
  readonly encoded?: string;
  readonly encoded_omitted?: "exceeds_response_bound";
  readonly encoded_chunked_read?: Decoded<typeof encodedPointer>;
};

/** The body half, exactly as `_general_read_payload` writes it for this format. */
function bodyHalf(
  input: Record<string, unknown>,
  format: ReportContentFormat,
): ReturnType<Decoder<Partial<StandaloneReportContent>>> {
  const present = BODY_KEYS.filter((key) => Object.hasOwn(input, key));
  if (present.length === 0) return ok({});
  if (Object.hasOwn(input, "body_omitted") || Object.hasOwn(input, "body_chunked_read")) {
    if (present.length !== 2 || input.body_omitted !== "exceeds_response_bound") return invalid();
    const pointer = bodyPointer(input.body_chunked_read);
    if (!pointer.ok) return pointer;
    return ok({ body_omitted: "exceeds_response_bound", body_chunked_read: pointer.value });
  }
  const wantsBody = format !== "json";
  const wantsData = format === "json" || format === "mixed";
  if (Object.hasOwn(input, "body") !== wantsBody || Object.hasOwn(input, "data") !== wantsData) {
    return invalid();
  }
  if (wantsBody && typeof input.body !== "string") return invalid();
  return ok({
    ...(wantsBody ? { body: input.body as string } : {}),
    ...(wantsData ? { data: input.data } : {}),
  });
}

/** The `encoded` half: only a `gzip+base64` version, and only with the body half. */
function encodedHalf(
  input: Record<string, unknown>,
  encoding: ReportContentEncoding,
  bodyIncluded: boolean,
): ReturnType<Decoder<Partial<StandaloneReportContent>>> {
  const present = ENCODED_KEYS.filter((key) => Object.hasOwn(input, key));
  if (encoding !== "gzip+base64" || !bodyIncluded) return present.length === 0 ? ok({}) : invalid();
  if (Object.hasOwn(input, "encoded")) {
    if (present.length !== 1) return invalid();
    const encoded = base64Chunk(input.encoded);
    return encoded.ok ? ok({ encoded: encoded.value }) : encoded;
  }
  if (present.length !== 2 || input.encoded_omitted !== "exceeds_response_bound") return invalid();
  const pointer = encodedPointer(input.encoded_chunked_read);
  if (!pointer.ok) return pointer;
  return ok({ encoded_omitted: "exceeds_response_bound", encoded_chunked_read: pointer.value });
}

const decodeContent: Decoder<StandaloneReportContent> = (input) => {
  if (!isRecord(input)) return invalid();
  const allowed = new Set<string>([...FACT_KEYS, ...BODY_KEYS, ...ENCODED_KEYS]);
  if (Object.keys(input).some((key) => !allowed.has(key))) return invalid();
  const facts: Record<string, unknown> = {};
  for (const key of FACT_KEYS) if (Object.hasOwn(input, key)) facts[key] = input[key];
  const decodedFacts = contentFacts(facts);
  if (!decodedFacts.ok) return decodedFacts;
  const body = bodyHalf(input, decodedFacts.value.format);
  if (!body.ok) return body;
  const bodyIncluded = Object.keys(body.value).length > 0;
  // A gzip version read with its body always says something about `encoded`.
  if (decodedFacts.value.encoding === "gzip+base64" && bodyIncluded &&
      !ENCODED_KEYS.some((key) => Object.hasOwn(input, key))) return invalid();
  const encoded = encodedHalf(input, decodedFacts.value.encoding, bodyIncluded);
  if (!encoded.ok) return encoded;
  return ok({ ...decodedFacts.value, ...body.value, ...encoded.value });
};

const association = strictObject({
  ordinal: count,
  target_kind: enumeration([
    "project",
    "entity",
    "standalone_report",
    "intelligence_report",
    "external_source",
  ] as const),
  target_ref: text(1),
  target_version_ref: nullable(text(1)),
  relation: text(1),
  verification: enumeration(["asserted", "verified"] as const),
});

const readFields = {
  plane: enumeration(STANDALONE_PLANE),
  report_id: reportId,
  created_at: timestamp,
  creator: reportCreator,
  head_version_id: reportVersionId,
  head_version_number: integer(1),
  lifecycle_state: enumeration(REPORT_LIFECYCLE_STATES),
  lifecycle_revision: count,
  held: boolean,
  version_id: reportVersionId,
  version_number: integer(1),
  supersedes_version_id: nullable(reportVersionId),
  change_kind: enumeration(REPORT_CHANGE_KINDS),
  change_reason: nullable(text()),
  title: text(1),
  type: nullable(text(1)),
  topics: arrayOf(text(1)),
  tags: arrayOf(text(1)),
  summary: nullable(text()),
  report_date: nullable(calendarDate),
  coverage_period: nullable(strictObject({ start: nullable(timestamp), end: nullable(timestamp) })),
  metadata: jsonRecord,
  recorded_at: timestamp,
  author: reportCreator,
  content: decodeContent,
  manifest_sha256: digest,
  associations: arrayOf(association),
};
const readWithoutManifest = strictObject(readFields);
const readWithManifest = strictObject({ ...readFields, manifest: jsonRecord });

export type StandaloneReportReadResult = Decoded<typeof readWithoutManifest> & {
  readonly manifest?: Readonly<Record<string, unknown>>;
};

export const decodeStandaloneReportRead: Decoder<StandaloneReportReadResult> = (input) =>
  isRecord(input) && Object.hasOwn(input, "manifest")
    ? readWithManifest(input)
    : readWithoutManifest(input);

// --- reports.list / reports.search (standalone | all) -------------------------

const standaloneItemFields = {
  plane: enumeration(STANDALONE_PLANE),
  report_id: reportId,
  title: text(1),
  type: nullable(text(1)),
  topics: arrayOf(text(1)),
  tags: arrayOf(text(1)),
  summary: nullable(text()),
  report_date: nullable(calendarDate),
  lifecycle_state: enumeration(REPORT_LIFECYCLE_STATES),
  lifecycle_revision: count,
  head_version_id: reportVersionId,
  head_version_number: positiveCount,
  created_at: timestamp,
  updated_at: timestamp,
  creator: reportCreator,
  held: boolean,
};
const artifactKind = checked(text(), (value) => ARTIFACT_KIND_PATTERN.test(value));
const intelligenceItemFields = {
  plane: enumeration(["intelligence"] as const),
  report_id: identifier("rpt"),
  title: text(1),
  type: artifactKind,
  report_date: calendarDate,
  created_at: timestamp,
  cycle_run_id: identifier("micr"),
  stage: enumeration(INTELLIGENCE_STAGES),
  artifact_kind: artifactKind,
  focus_area_id: nullable(text(1)),
  source_lane: nullable(text(1)),
  content_sha256: digest,
  artifact_state: enumeration(ARTIFACT_STATES),
};
const standaloneListItem = strictObject(standaloneItemFields);
const intelligenceListItem = strictObject(intelligenceItemFields);
const standaloneSearchItem = strictObject({ ...standaloneItemFields, snippet: text() });
const intelligenceSearchItem = strictObject({ ...intelligenceItemFields, snippet: text() });

export type StandaloneCatalogItem = Decoded<typeof standaloneListItem>;
export type IntelligenceCatalogItem = Decoded<typeof intelligenceListItem>;
export type StandaloneCatalogSearchItem = Decoded<typeof standaloneSearchItem>;
export type IntelligenceCatalogSearchItem = Decoded<typeof intelligenceSearchItem>;

export interface StandaloneCatalogPage<S, I> {
  readonly plane: "standalone" | "all";
  readonly items: readonly (S | I)[];
  readonly next_cursor: string | null;
}
export type StandaloneReportListResult = StandaloneCatalogPage<StandaloneCatalogItem, IntelligenceCatalogItem>;
export type StandaloneReportSearchResult = StandaloneCatalogPage<
  StandaloneCatalogSearchItem,
  IntelligenceCatalogSearchItem
>;

function catalogPage<S, I>(standalone: Decoder<S>, intelligence: Decoder<I>): Decoder<StandaloneCatalogPage<S, I>> {
  return (input) => {
    if (!isRecord(input)) return invalid();
    const keys = Object.keys(input);
    if (keys.length !== 3 || !["plane", "items", "next_cursor"].every((key) => Object.hasOwn(input, key))) {
      return invalid();
    }
    const plane = input.plane;
    if (plane !== "standalone" && plane !== "all") return invalid();
    if (!Array.isArray(input.items)) return invalid();
    const items: (S | I)[] = [];
    for (const item of input.items) {
      const itemPlane = isRecord(item) ? item.plane : undefined;
      // The standalone plane never lists a pipeline artifact.
      const decoded =
        itemPlane === "standalone"
          ? standalone(item)
          : itemPlane === "intelligence" && plane === "all"
            ? intelligence(item)
            : invalid();
      if (!decoded.ok) return decoded;
      items.push(decoded.value);
    }
    const cursor = nullable(text(1))(input.next_cursor);
    if (!cursor.ok) return cursor;
    return ok({ plane, items, next_cursor: cursor.value });
  };
}

export const decodeStandaloneReportList: Decoder<StandaloneReportListResult> = catalogPage(
  standaloneListItem,
  intelligenceListItem,
);
export const decodeStandaloneReportSearch: Decoder<StandaloneReportSearchResult> = catalogPage(
  standaloneSearchItem,
  intelligenceSearchItem,
);
