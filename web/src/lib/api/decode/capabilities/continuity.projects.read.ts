import type { Decoder } from "../types";
import { decodeProjectRow, type ProjectRow } from "./continuity.projects";

/** `continuity.projects.read` returns the canonical Project payload directly. */
export type ContinuityProjectsReadResult = ProjectRow;

export const decodeContinuityProjectsRead: Decoder<ContinuityProjectsReadResult> = decodeProjectRow;
