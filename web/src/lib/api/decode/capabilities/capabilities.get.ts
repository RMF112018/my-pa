import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredBoolean,
  requiredInt,
  requiredNullableInt,
  requiredNullableString,
  requiredString,
  requiredStringArray,
} from "./_read-helpers";

export const AVAILABILITIES = [
  "available",
  "decision_gated",
  "unavailable",
  "not_implemented",
] as const;

export type Availability = (typeof AVAILABILITIES)[number];

export const READINESS_STATES = [
  "not_implemented",
  "contracts_only",
  "degraded",
  "ready",
] as const;

export type ReadinessState = (typeof READINESS_STATES)[number];

export const WORKER_PLANE_STATES = [
  "idle_or_not_required",
  "working",
  "worker_absent",
  "worker_stale",
  "unavailable",
] as const;

export type WorkerPlaneState = (typeof WORKER_PLANE_STATES)[number];

export interface CapabilityStatus {
  readonly name: string;
  readonly version: string;
  readonly availability: Availability;
  readonly operator_only: boolean;
}

export interface ContentTypeStatus {
  readonly media_type: string;
  readonly availability: Availability;
}

export interface EffectiveLimits {
  readonly max_page_size: number;
  readonly default_page_size: number;
  readonly max_fetch_bytes: number;
  readonly max_enrollment_depth: number;
}

export interface CapabilityManifest {
  readonly contract_version: string;
  readonly contract_family: string;
  readonly capabilities: readonly CapabilityStatus[];
  readonly content_types: readonly ContentTypeStatus[];
  readonly limits: EffectiveLimits;
}

export interface ReadinessReport {
  readonly state: ReadinessState;
  readonly contract_version: string;
  readonly implemented_capabilities: number;
  readonly total_capabilities: number;
  readonly limitations: readonly string[];
}

export interface WorkerPlane {
  readonly plane: string;
  readonly state: WorkerPlaneState;
  readonly backlog: number | null;
  readonly dead_lettered: number | null;
  readonly last_heartbeat_at: string | null;
}

export interface CapabilitiesGetResult {
  readonly manifest: CapabilityManifest;
  readonly readiness: ReadinessReport;
  readonly worker_planes: readonly WorkerPlane[];
}

function decodeCapabilityStatus(input: unknown): DecodeResult<CapabilityStatus> {
  const known = pick(input, ["name", "version", "availability", "operator_only"]);
  if (!known.ok) return known;
  const name = requiredString(known.value.name);
  if (!name.ok) return name;
  const version = requiredString(known.value.version);
  if (!version.ok) return version;
  const availability = oneOf(known.value.availability, AVAILABILITIES);
  if (!availability.ok) return availability;
  const operatorOnly = requiredBoolean(known.value.operator_only);
  if (!operatorOnly.ok) return operatorOnly;
  return ok({
    name: name.value,
    version: version.value,
    availability: availability.value,
    operator_only: operatorOnly.value,
  });
}

function decodeContentType(input: unknown): DecodeResult<ContentTypeStatus> {
  const known = pick(input, ["media_type", "availability"]);
  if (!known.ok) return known;
  const mediaType = requiredString(known.value.media_type);
  if (!mediaType.ok) return mediaType;
  const availability = oneOf(known.value.availability, AVAILABILITIES);
  if (!availability.ok) return availability;
  return ok({ media_type: mediaType.value, availability: availability.value });
}

function decodeLimits(input: unknown): DecodeResult<EffectiveLimits> {
  const known = pick(input, [
    "max_page_size",
    "default_page_size",
    "max_fetch_bytes",
    "max_enrollment_depth",
  ]);
  if (!known.ok) return known;
  const maxPage = requiredInt(known.value.max_page_size);
  if (!maxPage.ok) return maxPage;
  const defaultPage = requiredInt(known.value.default_page_size);
  if (!defaultPage.ok) return defaultPage;
  const maxFetch = requiredInt(known.value.max_fetch_bytes);
  if (!maxFetch.ok) return maxFetch;
  const maxDepth = requiredInt(known.value.max_enrollment_depth);
  if (!maxDepth.ok) return maxDepth;
  return ok({
    max_page_size: maxPage.value,
    default_page_size: defaultPage.value,
    max_fetch_bytes: maxFetch.value,
    max_enrollment_depth: maxDepth.value,
  });
}

function decodeManifest(input: unknown): DecodeResult<CapabilityManifest> {
  const known = pick(input, [
    "contract_version",
    "contract_family",
    "capabilities",
    "content_types",
    "limits",
  ]);
  if (!known.ok) return known;
  const contractVersion = requiredString(known.value.contract_version);
  if (!contractVersion.ok) return contractVersion;
  const contractFamily = requiredString(known.value.contract_family);
  if (!contractFamily.ok) return contractFamily;
  if (known.value.capabilities === undefined) return fail("a required array was omitted");
  const capabilities = decodeItems(known.value.capabilities, decodeCapabilityStatus);
  if (!capabilities.ok) return capabilities;
  if (known.value.content_types === undefined) return fail("a required array was omitted");
  const contentTypes = decodeItems(known.value.content_types, decodeContentType);
  if (!contentTypes.ok) return contentTypes;
  const limits = decodeLimits(known.value.limits);
  if (!limits.ok) return limits;
  return ok({
    contract_version: contractVersion.value,
    contract_family: contractFamily.value,
    capabilities: capabilities.value,
    content_types: contentTypes.value,
    limits: limits.value,
  });
}

function decodeReadiness(input: unknown): DecodeResult<ReadinessReport> {
  const known = pick(input, [
    "state",
    "contract_version",
    "implemented_capabilities",
    "total_capabilities",
    "limitations",
  ]);
  if (!known.ok) return known;
  const state = oneOf(known.value.state, READINESS_STATES);
  if (!state.ok) return state;
  const contractVersion = requiredString(known.value.contract_version);
  if (!contractVersion.ok) return contractVersion;
  const implemented = requiredInt(known.value.implemented_capabilities);
  if (!implemented.ok) return implemented;
  const total = requiredInt(known.value.total_capabilities);
  if (!total.ok) return total;
  const limitations = requiredStringArray(known.value.limitations);
  if (!limitations.ok) return limitations;
  return ok({
    state: state.value,
    contract_version: contractVersion.value,
    implemented_capabilities: implemented.value,
    total_capabilities: total.value,
    limitations: limitations.value,
  });
}

function decodeWorkerPlane(input: unknown): DecodeResult<WorkerPlane> {
  const known = pick(input, [
    "plane",
    "state",
    "backlog",
    "dead_lettered",
    "last_heartbeat_at",
  ]);
  if (!known.ok) return known;
  const plane = requiredString(known.value.plane);
  if (!plane.ok) return plane;
  const state = oneOf(known.value.state, WORKER_PLANE_STATES);
  if (!state.ok) return state;
  const backlog = requiredNullableInt(known.value.backlog);
  if (!backlog.ok) return backlog;
  const deadLettered = requiredNullableInt(known.value.dead_lettered);
  if (!deadLettered.ok) return deadLettered;
  const heartbeat = requiredNullableString(known.value.last_heartbeat_at);
  if (!heartbeat.ok) return heartbeat;
  return ok({
    plane: plane.value,
    state: state.value,
    backlog: backlog.value,
    dead_lettered: deadLettered.value,
    last_heartbeat_at: heartbeat.value,
  });
}

export const decodeCapabilitiesGet: Decoder<CapabilitiesGetResult> = (input) => {
  const known = pick(input, ["manifest", "readiness", "worker_planes"]);
  if (!known.ok) return known;
  if (known.value.manifest === undefined) return fail("a required field was missing");
  if (known.value.readiness === undefined) return fail("a required field was missing");
  if (known.value.worker_planes === undefined) return fail("a required array was omitted");
  const manifest = decodeManifest(known.value.manifest);
  if (!manifest.ok) return manifest;
  const readiness = decodeReadiness(known.value.readiness);
  if (!readiness.ok) return readiness;
  const planes = decodeItems(known.value.worker_planes, decodeWorkerPlane);
  if (!planes.ok) return planes;
  return ok({
    manifest: manifest.value,
    readiness: readiness.value,
    worker_planes: planes.value,
  });
};
