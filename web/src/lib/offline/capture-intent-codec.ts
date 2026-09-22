/**
 * The v2 queued Capture intent: what is encrypted, and what merely authenticates it.
 *
 * A queued note used to be encrypted raw text and a plaintext journal row. That
 * was enough while a note carried nothing but its words. It is not enough now
 * that it carries a Project, because **which Project a note belongs to is part
 * of the note**: a queue that stored the Project beside the ciphertext would let
 * anything that can write to IndexedDB refile somebody's note without touching
 * the bytes AES-GCM protects.
 *
 * So `projectId` lives **inside the authenticated ciphertext and nowhere else**.
 * It is not a journal column and it is not in the additional authenticated data.
 * Putting it in the AAD would disclose the association in plaintext while adding
 * no integrity this construction does not already give: AES-GCM authenticates
 * the ciphertext, so changing Project A to B — even where the same person owns
 * both — fails decryption outright.
 *
 * What *is* in the AAD is the row's journal identity: the tag, the version, the
 * entry ID, the Principal, the idempotency key, the kind and the enqueue
 * timestamp. Those are repeated inside the encrypted tuple and compared on
 * decode, which is what binds one envelope to one journal row. Moving a payload
 * under a different entry, or rewriting the journal metadata around it, fails.
 *
 * **Legacy rows are historical and stay historical.** An entry written before
 * this codec has no version marker, decrypts as raw text with no AAD, and its
 * Project is null — not "unknown", not "inferred from current scope", null,
 * because that is what was true when it was queued. Nothing here rewrites those
 * bytes, and this module makes no retroactive claim about their integrity: v1
 * metadata was never cryptographically bound to its payload.
 *
 * **What this does not defend against.** Same-origin script that can reach the
 * stored `CryptoKey` can produce a valid v2 envelope. So can the authenticated
 * application itself. This raises the cost of tampering at rest; it is not a
 * defence against a compromised origin, a compromised profile, or a compromised
 * device, and the canonical backend still reauthorizes every replayed Project.
 */
import { isCaptureKind, type CaptureKind } from "@/lib/capture/contract";
import { isProjectId } from "@/lib/project-scope/scope";

/** The AAD tag. Distinct from the content tag so one can never be read as the other. */
export const CAPTURE_INTENT_ENVELOPE_TAG = "mypa.offline.capture";

/** The plaintext tuple tag. */
export const CAPTURE_INTENT_CONTENT_TAG = "mypa.offline.capture.intent";

/** The per-record application schema version. **Not** an IndexedDB version. */
export const CAPTURE_INTENT_SCHEMA_VERSION = 2;

/**
 * A decode sanity bound on the authored text, in UTF-16 code units.
 *
 * The real admission bound is the queue's own `MAX_QUEUED_BYTES`, enforced at
 * enqueue over the actual ciphertext. This one exists so a corrupt or hostile
 * payload cannot make the decoder allocate without limit before that check is
 * ever reached. It is deliberately generous.
 */
export const MAX_CAPTURE_INTENT_TEXT_LENGTH = 1_000_000;

/**
 * The closed protocol reasons. Every one is a field class or a state; none of
 * them carries authored text, decrypted bytes, a Project name or a raw
 * exception.
 */
export type CaptureQueueProtocolReason =
  | "unsupported_version"
  | "authentication_failed"
  | "invalid_utf8"
  | "malformed_intent"
  | "metadata_mismatch"
  | "intent_conflict"
  | "key_unavailable"
  | "receipt_invalid"
  | "transport_unconfirmed"
  | "session_changed";

/** A content-free queue-protocol failure. The message is the reason and nothing more. */
export class CaptureQueueProtocolError extends Error {
  readonly reason: CaptureQueueProtocolReason;

  constructor(reason: CaptureQueueProtocolReason) {
    super(reason);
    this.name = "CaptureQueueProtocolError";
    this.reason = reason;
  }
}

/** The immutable journal identity of one queued entry. Carried in the AAD. */
export interface CaptureIntentEnvelope {
  readonly entryId: string;
  readonly principalId: string;
  readonly idempotencyKey: string;
  readonly captureKind: CaptureKind;
  /** The enqueued event's own `at`: epoch milliseconds, frozen at first enqueue. */
  readonly queuedAt: number;
}

/** The full v2 intent: the journal identity plus the content only the key reveals. */
export interface CaptureIntentV2 extends CaptureIntentEnvelope {
  readonly text: string;
  readonly projectId: string | null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** The enqueue timestamp contract: a finite, non-negative, safe integer. */
function isQueuedAt(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function utf8(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

/**
 * The additional authenticated data for one entry.
 *
 * Fixed order, compact JSON, UTF-8. No Project: see the module note. A caller
 * that reorders or reshapes this produces bytes that will not decrypt anything
 * this module sealed, which is the intended outcome.
 */
export function captureIntentAdditionalData(envelope: CaptureIntentEnvelope): Uint8Array {
  return utf8(
    JSON.stringify([
      CAPTURE_INTENT_ENVELOPE_TAG,
      CAPTURE_INTENT_SCHEMA_VERSION,
      envelope.entryId,
      envelope.principalId,
      envelope.idempotencyKey,
      envelope.captureKind,
      envelope.queuedAt,
    ]),
  );
}

/** The canonical plaintext serialization of one v2 intent. Fixed order, compact JSON. */
function serializeIntent(intent: CaptureIntentV2): string {
  return JSON.stringify([
    CAPTURE_INTENT_CONTENT_TAG,
    CAPTURE_INTENT_SCHEMA_VERSION,
    intent.entryId,
    intent.principalId,
    intent.idempotencyKey,
    intent.captureKind,
    intent.queuedAt,
    intent.text,
    intent.projectId,
  ]);
}

/** Encode one v2 intent to the bytes that get sealed. */
export function encodeCaptureIntentV2(intent: CaptureIntentV2): Uint8Array {
  if (!isNonEmptyString(intent.entryId)) throw new CaptureQueueProtocolError("malformed_intent");
  if (!isNonEmptyString(intent.principalId)) throw new CaptureQueueProtocolError("malformed_intent");
  if (!isNonEmptyString(intent.idempotencyKey)) {
    throw new CaptureQueueProtocolError("malformed_intent");
  }
  if (!isCaptureKind(intent.captureKind)) throw new CaptureQueueProtocolError("malformed_intent");
  if (!isQueuedAt(intent.queuedAt)) throw new CaptureQueueProtocolError("malformed_intent");
  if (typeof intent.text !== "string" || intent.text.length > MAX_CAPTURE_INTENT_TEXT_LENGTH) {
    throw new CaptureQueueProtocolError("malformed_intent");
  }
  if (intent.projectId !== null && !isProjectId(intent.projectId)) {
    throw new CaptureQueueProtocolError("malformed_intent");
  }
  return utf8(serializeIntent(intent));
}

/**
 * Decode sealed v2 bytes against the journal row they claim to belong to.
 *
 * Every check is exact and every failure is fatal. There is no permissive object
 * form, no unknown-field tolerance, no trimming, no defaulted Project and no
 * fallback parser: a payload this function cannot fully account for is a payload
 * that keeps its bytes and never gets uploaded.
 *
 * The final reserialization comparison is what closes the last gap — it rejects
 * a tuple that parses to the right values through a different encoding, so what
 * was sealed is byte-for-byte what is read back.
 */
export function decodeCaptureIntentV2(
  bytes: Uint8Array,
  expected: CaptureIntentEnvelope,
): CaptureIntentV2 {
  let text: string;
  try {
    // Fatal UTF-8: a lone surrogate or a truncated sequence is corruption, not
    // something to substitute U+FFFD into and carry on with.
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new CaptureQueueProtocolError("invalid_utf8");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new CaptureQueueProtocolError("malformed_intent");
  }

  if (!Array.isArray(parsed) || parsed.length !== 9) {
    throw new CaptureQueueProtocolError("malformed_intent");
  }
  const [tag, version, entryId, principalId, idempotencyKey, captureKind, queuedAt, body, project] =
    parsed as readonly unknown[];

  if (tag !== CAPTURE_INTENT_CONTENT_TAG) throw new CaptureQueueProtocolError("malformed_intent");
  if (version !== CAPTURE_INTENT_SCHEMA_VERSION) {
    throw new CaptureQueueProtocolError("unsupported_version");
  }
  if (!isNonEmptyString(entryId)) throw new CaptureQueueProtocolError("malformed_intent");
  if (!isNonEmptyString(principalId)) throw new CaptureQueueProtocolError("malformed_intent");
  if (!isNonEmptyString(idempotencyKey)) throw new CaptureQueueProtocolError("malformed_intent");
  if (!isCaptureKind(captureKind)) throw new CaptureQueueProtocolError("malformed_intent");
  if (!isQueuedAt(queuedAt)) throw new CaptureQueueProtocolError("malformed_intent");
  if (typeof body !== "string" || body.length > MAX_CAPTURE_INTENT_TEXT_LENGTH) {
    throw new CaptureQueueProtocolError("malformed_intent");
  }
  if (project !== null && !isProjectId(project)) {
    throw new CaptureQueueProtocolError("malformed_intent");
  }

  // The metadata inside the sealed tuple must be the metadata of the row this
  // payload was read from. AES-GCM already binds them through the AAD; this is
  // the same statement checked in the clear, so a decode that somehow succeeded
  // against the wrong row still fails here.
  if (
    entryId !== expected.entryId ||
    principalId !== expected.principalId ||
    idempotencyKey !== expected.idempotencyKey ||
    captureKind !== expected.captureKind ||
    queuedAt !== expected.queuedAt
  ) {
    throw new CaptureQueueProtocolError("metadata_mismatch");
  }

  const intent: CaptureIntentV2 = {
    entryId,
    principalId,
    idempotencyKey,
    captureKind,
    queuedAt,
    text: body,
    projectId: project,
  };
  if (serializeIntent(intent) !== text) {
    throw new CaptureQueueProtocolError("malformed_intent");
  }
  return intent;
}

/** What a stored record's version markers say this payload is. */
export type CapturePayloadVersion = "legacy" | "v2" | "unsupported";

function markerOf(record: unknown): unknown {
  if (typeof record !== "object" || record === null) return Symbol.for("not-a-record");
  return (record as Record<string, unknown>)["schemaVersion"];
}

/**
 * Which protocol a stored entry and payload pair declares.
 *
 * Deliberately reads raw `unknown` values rather than trusting the TypeScript
 * annotation on the record types: the whole point is to classify persisted input
 * that may be corrupt, partially written, or written by something else.
 *
 * "Legacy" means the historical **absence** of a marker on both records — not a
 * guess from payload shape and not a literal `1`. One marker present and the
 * other absent, a mismatched pair, a wrong type, or any other version is
 * `unsupported`: the row keeps its bytes and is never uploaded.
 */
export function detectCapturePayloadVersion(
  entry: unknown,
  payload: unknown,
): CapturePayloadVersion {
  const entryMarker = markerOf(entry);
  const payloadMarker = markerOf(payload);
  if (typeof entryMarker === "symbol" || typeof payloadMarker === "symbol") return "unsupported";
  if (entryMarker === undefined && payloadMarker === undefined) return "legacy";
  if (
    entryMarker === CAPTURE_INTENT_SCHEMA_VERSION &&
    payloadMarker === CAPTURE_INTENT_SCHEMA_VERSION
  ) {
    return "v2";
  }
  return "unsupported";
}
