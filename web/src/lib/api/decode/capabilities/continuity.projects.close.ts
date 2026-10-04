import type { Decoder } from "../types";
import { projectMutation } from "./continuity.projects.update";
import { checked, type Decoded } from "./continuity.projects.create";
export type ContinuityProjectsCloseResult = Decoded<typeof projectMutation>;
export const decodeContinuityProjectsClose: Decoder<ContinuityProjectsCloseResult> = checked(
  projectMutation,
  (value) => value.state === "closed",
);
