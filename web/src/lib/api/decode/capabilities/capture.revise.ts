import type { Decoder } from "../types";
import { strictObject, nullable, text, integer, boolean, identifier, timestamp, digest, type Decoded } from "./continuity.projects.create";
const receipt = strictObject({
  receipt_id: identifier("rcpt"), capture_id: identifier("cap"), version_id: identifier("capver"),
  version_number: integer(1), idempotency_key: text(1,128), content_sha256: digest,
  project_id: nullable(identifier("prj")), issued_at: timestamp, created: boolean,
});
// The canonical key remains server-side; the Capture route owns redaction.
export type CaptureReviseResult = Decoded<typeof receipt>;
export const decodeCaptureRevise: Decoder<CaptureReviseResult> = receipt;
