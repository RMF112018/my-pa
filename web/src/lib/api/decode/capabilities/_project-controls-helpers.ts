/**
 * The one `project_controls` object both Project Controls capabilities carry.
 *
 * `project_controls.status` and `project_controls.configure` publish the same
 * five-key object, for the reason the Python side gives in
 * `_project_controls_settings_payload`: a client decodes a Project's
 * configuration once rather than twice. This module is therefore the single
 * transcription of that shape, and the two capability decoders differ only in
 * what surrounds it.
 *
 * **What this decoder guarantees, precisely.** It refuses a missing or mistyped
 * required field and refuses a `state` outside its closed two-member
 * vocabulary. It does *not* refuse an unknown extra key: `pick` drops one, and
 * the accepted BFF policy is that a response extra is ignored rather than
 * rejected. Claiming otherwise would be a guarantee this layer does not make.
 *
 * The four values beneath `state` are non-null exactly when `state` is
 * `configured`, and that pairing is enforced here rather than left to the
 * caller — a `configured` row with a null timezone, or a `not_configured` row
 * carrying a version, is a contract failure and not a shape a consumer should
 * have to branch on.
 *
 * `principal_id` is absent from the wire and is absent from these types. There
 * is no key to strip because the Python payload never names one.
 */
import { ok, type DecodeResult } from "../primitives";
import {
  fail,
  oneOf,
  pick,
  requiredInt,
  requiredNullableInt,
  requiredNullableString,
  requiredString,
} from "./_read-helpers";

/** `ProjectControlsState` — the closed two-member vocabulary. */
export const PROJECT_CONTROLS_STATES = ["configured", "not_configured"] as const;

export type ProjectControlsState = (typeof PROJECT_CONTROLS_STATES)[number];

/** `ProjectControlsDisposition` — the closed three-member vocabulary. */
export const PROJECT_CONTROLS_DISPOSITIONS = ["applied", "no_op", "replayed"] as const;

export type ProjectControlsDisposition = (typeof PROJECT_CONTROLS_DISPOSITIONS)[number];

const SETTINGS_KEYS = [
  "project_id",
  "state",
  "timezone_name",
  "settings_version",
  "settings_updated_at",
] as const;

/**
 * One Project's Constraint-settings state, as the status read carries it.
 *
 * Published in camelCase, which is this route family's convention: every
 * Constraint decoder reads the Python snake_case and publishes `projectId`,
 * `averageOpenAgeBusinessDays`, `syncHealth`. A settings object spelled
 * differently from the Overview object beside it would be a second convention
 * inside one API.
 */
export interface ProjectControlsSettings {
  readonly projectId: string;
  readonly state: ProjectControlsState;
  readonly timezoneName: string | null;
  readonly settingsVersion: number | null;
  readonly settingsUpdatedAt: string | null;
}

/**
 * The same object once a configure has returned: `state` is `configured` by
 * construction, so the three settings values are non-null rather than nullable.
 */
export interface ConfiguredProjectControls {
  readonly projectId: string;
  readonly state: "configured";
  readonly timezoneName: string;
  readonly settingsVersion: number;
  readonly settingsUpdatedAt: string;
}

export function decodeProjectControlsSettings(
  input: unknown,
): DecodeResult<ProjectControlsSettings> {
  const known = pick(input, SETTINGS_KEYS);
  if (!known.ok) return known;
  const projectId = requiredString(known.value.project_id);
  if (!projectId.ok) return projectId;
  const state = oneOf(known.value.state, PROJECT_CONTROLS_STATES);
  if (!state.ok) return state;
  const timezoneName = requiredNullableString(known.value.timezone_name);
  if (!timezoneName.ok) return timezoneName;
  const settingsVersion = requiredNullableInt(known.value.settings_version);
  if (!settingsVersion.ok) return settingsVersion;
  const settingsUpdatedAt = requiredNullableString(known.value.settings_updated_at);
  if (!settingsUpdatedAt.ok) return settingsUpdatedAt;

  // The pairing the Python payload states as an invariant: each of the three
  // values is present exactly when the Project is configured. Checked per field
  // rather than "all or nothing", because a half-populated row — a
  // `not_configured` state still carrying a version, say — is precisely the
  // malformed shape a consumer branching on `state` would be misled by.
  const configured = state.value === "configured";
  if (
    (timezoneName.value !== null) !== configured ||
    (settingsVersion.value !== null) !== configured ||
    (settingsUpdatedAt.value !== null) !== configured
  ) {
    return fail("a required field was not consistent with the reported state");
  }

  return ok({
    projectId: projectId.value,
    state: state.value,
    timezoneName: timezoneName.value,
    settingsVersion: settingsVersion.value,
    settingsUpdatedAt: settingsUpdatedAt.value,
  });
}

/** The configure response's object: `configured`, with all three values present. */
export function decodeConfiguredProjectControls(
  input: unknown,
): DecodeResult<ConfiguredProjectControls> {
  const known = pick(input, SETTINGS_KEYS);
  if (!known.ok) return known;
  const projectId = requiredString(known.value.project_id);
  if (!projectId.ok) return projectId;
  const state = oneOf(known.value.state, ["configured"] as const);
  if (!state.ok) return state;
  const timezoneName = requiredString(known.value.timezone_name);
  if (!timezoneName.ok) return timezoneName;
  const settingsVersion = requiredInt(known.value.settings_version);
  if (!settingsVersion.ok) return settingsVersion;
  const settingsUpdatedAt = requiredString(known.value.settings_updated_at);
  if (!settingsUpdatedAt.ok) return settingsUpdatedAt;
  return ok({
    projectId: projectId.value,
    state: state.value,
    timezoneName: timezoneName.value,
    settingsVersion: settingsVersion.value,
    settingsUpdatedAt: settingsUpdatedAt.value,
  });
}
