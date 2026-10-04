import type { Decoder } from "../types";
import { strictObject, checked, nullable, text, integer, boolean, enumeration, identifier, timestamp, digest, type Decoded } from "./continuity.projects.create";
import { mediaType } from "./meetings.read";
const base64 = checked(text(4), (value) => /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.exec(value)?.[0] === value && Buffer.from(value, "base64").toString("base64") === value);
const version = strictObject({
  document_id: identifier("mdoc"), version_id: identifier("mdver"), version_number: integer(1), supersedes_version_id: nullable(identifier("mdver")),
  title: text(1,200), media_type: mediaType, content_sha256: digest, byte_size: integer(1), recorded_at: timestamp,
  is_current: boolean, state: enumeration(["active", "archived"]), content_base64: nullable(base64),
});
const read = strictObject({version});
export type DocumentsReadResult = Decoded<typeof read>;
export const decodeDocumentsRead: Decoder<DocumentsReadResult> = read;
