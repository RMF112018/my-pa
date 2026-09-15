// @vitest-environment node
/**
 * R01-WP05: the two Project Controls decoders, against the exact Python shape.
 *
 * These cases are the transcription check. The payloads below are written out
 * in full rather than built from a helper, so that a drift between
 * `_project_controls_settings_payload` and this decoder is visible as a diff in
 * this file rather than inferred from a factory.
 *
 * What the decoders guarantee, and what these cases therefore assert:
 * a missing or mistyped required field is refused, a value outside the closed
 * `state` or `disposition` vocabulary is refused, and the documented pairing
 * between `state` and the three values beneath it is enforced. Unknown extra
 * response keys are *ignored*, not refused — the accepted BFF policy — and
 * there is a case below pinning that, so nobody later reads the absence of an
 * extras test as an oversight.
 */
import { describe, expect, it } from "vitest";
import {
  decodeProjectControlsConfigure,
  type ProjectControlsConfigureResult,
} from "./project_controls.configure";
import {
  decodeProjectControlsStatus,
  type ProjectControlsStatusResult,
} from "./project_controls.status";

const PROJECT = "prj_aaaaaaaa11111111";
/** Python `datetime.isoformat()` — the `+00:00` offset form, not a `Z` suffix. */
const UPDATED_AT = "2026-09-02T15:00:00+00:00";

const CONFIGURED = {
  project_controls: {
    project_id: PROJECT,
    state: "configured",
    timezone_name: "America/New_York",
    settings_version: 3,
    settings_updated_at: UPDATED_AT,
  },
};

const NOT_CONFIGURED = {
  project_controls: {
    project_id: PROJECT,
    state: "not_configured",
    timezone_name: null,
    settings_version: null,
    settings_updated_at: null,
  },
};

const APPLIED = {
  disposition: "applied",
  project_controls: {
    project_id: PROJECT,
    state: "configured",
    timezone_name: "America/New_York",
    settings_version: 1,
    settings_updated_at: UPDATED_AT,
  },
};

function expectOk<T>(result: { ok: boolean }, message = "expected a decode to succeed"): T {
  expect(result.ok, message).toBe(true);
  return (result as { ok: true; value: T }).value;
}

describe("project_controls.status", () => {
  it("decodes a configured Project into the five published values", () => {
    const value = expectOk<ProjectControlsStatusResult>(
      decodeProjectControlsStatus(CONFIGURED),
    );
    expect(value).toEqual({
      projectControls: {
        projectId: PROJECT,
        state: "configured",
        timezoneName: "America/New_York",
        settingsVersion: 3,
        settingsUpdatedAt: UPDATED_AT,
      },
    });
  });

  it("decodes a not_configured Project, keeping the four null values explicit", () => {
    const value = expectOk<ProjectControlsStatusResult>(
      decodeProjectControlsStatus(NOT_CONFIGURED),
    );
    expect(value.projectControls.state).toBe("not_configured");
    expect(value.projectControls.timezoneName).toBeNull();
    expect(value.projectControls.settingsVersion).toBeNull();
    expect(value.projectControls.settingsUpdatedAt).toBeNull();
    expect(value.projectControls.projectId).toBe(PROJECT);
  });

  it.each([
    ["a non-record input", 7],
    ["null", null],
    ["an array", []],
    ["an empty object", {}],
    ["a null project_controls", { project_controls: null }],
    ["a non-record project_controls", { project_controls: "configured" }],
  ])("refuses %s", (_name, input) => {
    expect(decodeProjectControlsStatus(input).ok).toBe(false);
  });

  it.each([
    "project_id",
    "state",
    "timezone_name",
    "settings_version",
    "settings_updated_at",
  ])("refuses a payload missing the required key %s", (key) => {
    const mutated = { ...CONFIGURED.project_controls } as Record<string, unknown>;
    delete mutated[key];
    expect(decodeProjectControlsStatus({ project_controls: mutated }).ok).toBe(false);
  });

  it.each([
    ["a state outside the closed vocabulary", { state: "enabled" }],
    ["the disposition vocabulary used as a state", { state: "applied" }],
    ["a state sent with the wrong case", { state: "Configured" }],
    ["a null state", { state: null }],
    ["a numeric project_id", { project_id: 1 }],
    ["a null project_id", { project_id: null }],
    ["a version sent as a string", { settings_version: "3" }],
    ["a fractional version", { settings_version: 1.5 }],
    ["a numeric timezone", { timezone_name: 42 }],
    ["a numeric timestamp", { settings_updated_at: 1_759_000_000 }],
  ])("refuses %s", (_name, patch) => {
    const input = { project_controls: { ...CONFIGURED.project_controls, ...patch } };
    expect(decodeProjectControlsStatus(input).ok).toBe(false);
  });

  it.each([
    ["a configured row with a null timezone", "configured", { timezone_name: null }],
    ["a configured row with a null version", "configured", { settings_version: null }],
    ["a configured row with a null timestamp", "configured", { settings_updated_at: null }],
    ["a not_configured row carrying a timezone", "not_configured", { timezone_name: "UTC" }],
    ["a not_configured row carrying a version", "not_configured", { settings_version: 2 }],
    [
      "a not_configured row carrying a timestamp",
      "not_configured",
      { settings_updated_at: UPDATED_AT },
    ],
  ])("refuses %s, because state and its values must agree", (_name, state, patch) => {
    const base = state === "configured" ? CONFIGURED : NOT_CONFIGURED;
    const input = { project_controls: { ...base.project_controls, ...patch } };
    expect(decodeProjectControlsStatus(input).ok).toBe(false);
  });

  it("ignores an unknown response key rather than claiming to reject it", () => {
    const value = expectOk<ProjectControlsStatusResult>(
      decodeProjectControlsStatus({
        project_controls: { ...CONFIGURED.project_controls, created_at: UPDATED_AT },
        an_extra_top_level_key: true,
      }),
    );
    expect(value.projectControls).toEqual({
      projectId: PROJECT,
      state: "configured",
      timezoneName: "America/New_York",
      settingsVersion: 3,
      settingsUpdatedAt: UPDATED_AT,
    });
    expect(value.projectControls).not.toHaveProperty("created_at");
  });

  it("drops a principal_id the payload should never carry", () => {
    const value = expectOk<ProjectControlsStatusResult>(
      decodeProjectControlsStatus({
        project_controls: { ...CONFIGURED.project_controls, principal_id: "syn-aaaa0001" },
      }),
    );
    expect(JSON.stringify(value)).not.toContain("syn-aaaa0001");
    expect(value.projectControls).not.toHaveProperty("principal_id");
  });
});

describe("project_controls.configure", () => {
  it.each(["applied", "no_op", "replayed"])("decodes the %s disposition", (disposition) => {
    const value = expectOk<ProjectControlsConfigureResult>(
      decodeProjectControlsConfigure({ ...APPLIED, disposition }),
    );
    expect(value.disposition).toBe(disposition);
    expect(value.projectControls).toEqual({
      projectId: PROJECT,
      state: "configured",
      timezoneName: "America/New_York",
      settingsVersion: 1,
      settingsUpdatedAt: UPDATED_AT,
    });
  });

  it.each([
    ["rejected, which is raised as an error and never returned", "rejected"],
    ["an unknown verb", "updated"],
    ["the wrong case", "Applied"],
    ["a state value used as a disposition", "configured"],
    ["the empty string", ""],
  ])("refuses the disposition %s", (_name, disposition) => {
    expect(decodeProjectControlsConfigure({ ...APPLIED, disposition }).ok).toBe(false);
  });

  it.each([
    ["a missing disposition", { project_controls: APPLIED.project_controls }],
    ["a null disposition", { ...APPLIED, disposition: null }],
    ["a numeric disposition", { ...APPLIED, disposition: 1 }],
    ["a missing project_controls", { disposition: "applied" }],
    ["a null project_controls", { disposition: "applied", project_controls: null }],
    ["an empty object", {}],
  ])("refuses %s", (_name, input) => {
    expect(decodeProjectControlsConfigure(input).ok).toBe(false);
  });

  it("refuses a not_configured state, which a returning configure never produces", () => {
    const input = { disposition: "applied", project_controls: NOT_CONFIGURED.project_controls };
    expect(decodeProjectControlsConfigure(input).ok).toBe(false);
  });

  it.each([
    ["a null timezone", { timezone_name: null }],
    ["a null version", { settings_version: null }],
    ["a null timestamp", { settings_updated_at: null }],
    ["a missing timezone", { timezone_name: undefined }],
    ["a version sent as a string", { settings_version: "1" }],
  ])("refuses %s, because a configure answer has all three values", (_name, patch) => {
    const input = {
      disposition: "applied",
      project_controls: { ...APPLIED.project_controls, ...patch },
    };
    expect(decodeProjectControlsConfigure(input).ok).toBe(false);
  });

  it("ignores an unknown response key, including a receipt it does not publish", () => {
    const value = expectOk<ProjectControlsConfigureResult>(
      decodeProjectControlsConfigure({
        ...APPLIED,
        receipt: { history_id: "hst_aaaaaaaa11111111" },
        project_controls: { ...APPLIED.project_controls, created_at: UPDATED_AT },
      }),
    );
    expect(value).toEqual({
      disposition: "applied",
      projectControls: {
        projectId: PROJECT,
        state: "configured",
        timezoneName: "America/New_York",
        settingsVersion: 1,
        settingsUpdatedAt: UPDATED_AT,
      },
    });
    expect(value).not.toHaveProperty("receipt");
  });

  it("types a decoded configure so `state` is the literal configured", () => {
    const value = expectOk<ProjectControlsConfigureResult>(
      decodeProjectControlsConfigure(APPLIED),
    );
    const state: "configured" = value.projectControls.state;
    const version: number = value.projectControls.settingsVersion;
    const zone: string = value.projectControls.timezoneName;
    expect([state, version, zone]).toEqual(["configured", 1, "America/New_York"]);
  });
});
