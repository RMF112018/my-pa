/**
 * `project_controls.status`: whether one Project's Constraint calendar is stated.
 *
 * The whole answer is one `project_controls` object. There is no page, no
 * cursor and no filter, because the question is one row's presence and — when
 * present — that row's three public values.
 *
 * A missing `project_controls` key is a contract failure rather than an empty
 * answer: "not configured" is a `state` this capability returns explicitly, so
 * an absent object cannot be read as one.
 */
import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeProjectControlsSettings,
  type ProjectControlsSettings,
} from "./_project-controls-helpers";
import { fail, pick } from "./_read-helpers";

export type { ProjectControlsSettings };

export interface ProjectControlsStatusResult {
  readonly projectControls: ProjectControlsSettings;
}

export const decodeProjectControlsStatus: Decoder<ProjectControlsStatusResult> = (input) => {
  const known = pick(input, ["project_controls"]);
  if (!known.ok) return known;
  if (known.value.project_controls === undefined) {
    return fail("a required object was missing");
  }
  const settings = decodeProjectControlsSettings(known.value.project_controls);
  if (!settings.ok) return settings;
  return ok({ projectControls: settings.value });
};
