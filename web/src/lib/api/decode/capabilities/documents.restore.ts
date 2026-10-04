import type { Decoder } from "../types";
import { strictObject, boolean, enumeration, type Decoded } from "./continuity.projects.create";
const result = strictObject({state: enumeration(["active"]), changed: boolean});
export type DocumentsRestoreResult = Decoded<typeof result>;
export const decodeDocumentsRestore: Decoder<DocumentsRestoreResult> = result;
