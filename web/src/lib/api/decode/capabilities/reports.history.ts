/**
 * `reports.history` (WP07 U2): Python `service._general_history_payload`, closed.
 *
 * `entries` decides the item shape: a `versions` page carries
 * `_history_version_item`s (a `manifest` only when `include_manifests` asked
 * for it), a `lifecycle` page `_history_lifecycle_item`s. A page whose items do
 * not match its own `entries` is refused. `held` is the root's hold cache, the
 * only hold datum, decoded as a boolean.
 */
import { closed, isRecord } from "../primitives";
import type { Decoder } from "../types";
import {
  arrayOf,
  boolean,
  digest,
  enumeration,
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
  REPORT_LIFECYCLE_OPERATIONS,
  REPORT_LIFECYCLE_STATES,
  REPORT_STORAGE_KINDS,
  STANDALONE_PLANE,
  count,
  jsonRecord,
  reportContentId,
  reportCreator,
  reportId,
  reportLifecycleEventId,
  reportVersionId,
} from "./_general-report-helpers";

const invalid = () => closed("upstream_contract_invalid", "Invalid capability success contract");

const versionFields = {
  version_id: reportVersionId,
  version_number: integer(1),
  supersedes_version_id: nullable(reportVersionId),
  change_kind: enumeration(REPORT_CHANGE_KINDS),
  change_reason: nullable(text()),
  title: text(1),
  recorded_at: timestamp,
  content: strictObject({
    content_id: reportContentId,
    format: enumeration(REPORT_CONTENT_FORMATS),
    encoding: enumeration(REPORT_CONTENT_ENCODINGS),
    storage_kind: enumeration(REPORT_STORAGE_KINDS),
    decoded_sha256: digest,
    decoded_byte_count: count,
    canonical_sha256: nullable(digest),
    original_sha256: digest,
  }),
  manifest_sha256: digest,
  author: reportCreator,
};
const versionWithoutManifest = strictObject(versionFields);
const versionWithManifest = strictObject({ ...versionFields, manifest: jsonRecord });

export type ReportHistoryVersionItem = Decoded<typeof versionWithoutManifest> & {
  readonly manifest?: Readonly<Record<string, unknown>>;
};

const decodeVersionItem: Decoder<ReportHistoryVersionItem> = (input) =>
  isRecord(input) && Object.hasOwn(input, "manifest")
    ? versionWithManifest(input)
    : versionWithoutManifest(input);

const lifecycleItem = strictObject({
  event_id: reportLifecycleEventId,
  lifecycle_revision: integer(1),
  operation: enumeration(REPORT_LIFECYCLE_OPERATIONS),
  prior_state: enumeration(REPORT_LIFECYCLE_STATES),
  resulting_state: enumeration(REPORT_LIFECYCLE_STATES),
  reason: nullable(text()),
  transitioned_at: timestamp,
});

export type ReportHistoryLifecycleItem = Decoded<typeof lifecycleItem>;

const pageFields = {
  plane: enumeration(STANDALONE_PLANE),
  report_id: reportId,
  head_version_id: reportVersionId,
  head_version_number: integer(1),
  lifecycle_state: enumeration(REPORT_LIFECYCLE_STATES),
  lifecycle_revision: count,
  held: boolean,
  next_cursor: nullable(text(1)),
};
const versionsPage = strictObject({
  ...pageFields,
  entries: enumeration(["versions"] as const),
  items: arrayOf(decodeVersionItem),
});
const lifecyclePage = strictObject({
  ...pageFields,
  entries: enumeration(["lifecycle"] as const),
  items: arrayOf(lifecycleItem),
});

export type ReportsHistoryVersionsResult = Decoded<typeof versionsPage>;
export type ReportsHistoryLifecycleResult = Decoded<typeof lifecyclePage>;
/** Discriminated by `entries`. */
export type ReportsHistoryResult = ReportsHistoryVersionsResult | ReportsHistoryLifecycleResult;

export const decodeReportsHistory: Decoder<ReportsHistoryResult> = (input) => {
  if (!isRecord(input)) return invalid();
  if (input.entries === "versions") return versionsPage(input);
  if (input.entries === "lifecycle") return lifecyclePage(input);
  return invalid();
};

