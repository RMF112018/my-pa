/**
 * `project_controls.configure`: state which calendar one Project's dates mean.
 *
 * The same `project_controls` object the status read carries, plus the
 * `disposition` that says which of the three accepted outcomes produced it.
 * `disposition` is a closed three-member vocabulary and `rejected` is not a
 * member: a rejected configure is raised as an error envelope and never reaches
 * a success decoder, so admitting the name here would describe a response this
 * capability does not emit.
 *
 * A configure that returns at all left the Project configured, whichever
 * outcome it was, which is why `state` is decoded as the literal `configured`
 * rather than as the two-member vocabulary. For a `replayed` answer the three
 * settings values are the ledger's snapshot of what the *original* attempt
 * produced — this decoder asserts their shape, not their freshness.
 *
 * No receipt is decoded because none is published. The receipt is read back
 * through the settings history, which is its own authorized read.
 */
import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeConfiguredProjectControls,
  PROJECT_CONTROLS_DISPOSITIONS,
  type ConfiguredProjectControls,
  type ProjectControlsDisposition,
} from "./_project-controls-helpers";
import { fail, oneOf, pick } from "./_read-helpers";

export type { ConfiguredProjectControls, ProjectControlsDisposition };

export interface ProjectControlsConfigureResult {
  readonly disposition: ProjectControlsDisposition;
  readonly projectControls: ConfiguredProjectControls;
}

export const decodeProjectControlsConfigure: Decoder<ProjectControlsConfigureResult> = (
  input,
) => {
  const known = pick(input, ["disposition", "project_controls"]);
  if (!known.ok) return known;
  const disposition = oneOf(known.value.disposition, PROJECT_CONTROLS_DISPOSITIONS);
  if (!disposition.ok) return disposition;
  if (known.value.project_controls === undefined) {
    return fail("a required object was missing");
  }
  const settings = decodeConfiguredProjectControls(known.value.project_controls);
  if (!settings.ok) return settings;
  return ok({ disposition: disposition.value, projectControls: settings.value });
};
