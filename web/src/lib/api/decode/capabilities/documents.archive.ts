import type { Decoder } from "../types";
import { strictObject, boolean, enumeration, type Decoded } from "./continuity.projects.create";
const result = strictObject({state: enumeration(["archived"]), changed: boolean});
export type DocumentsArchiveResult = Decoded<typeof result>;
export const decodeDocumentsArchive: Decoder<DocumentsArchiveResult> = result;
