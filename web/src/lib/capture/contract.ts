/**
 * The one browser Capture request contract (C02).
 *
 * Before this module the browser, the BFF and the offline queue each carried
 * their own idea of what a Capture submission was, and the Project a user had
 * selected was dropped somewhere between them without anyone being told. These
 * types are the single shared vocabulary for that request, its frozen intent and
 * the acknowledgement the backend actually issued.
 *
 * **Project identity is validated, never repaired.** `parseCaptureProject`
 * accepts omission and explicit null as "No Project" and otherwise requires the
 * existing `isProjectId` shape from `lib/project-scope/scope.ts`. It does not
 * trim, coerce, case-fold or pad an identifier: a request that names a Project
 * this tier cannot recognise is a validation refusal *before* the gateway is
 * invoked, because silently falling back to null would file the note against no
 * Project while telling the user it was filed against theirs.
 *
 * **The kinds are closed and are the Python `CaptureKind`'s.** Task and
 * Constraint are not Capture kinds in this repository and are not added here.
 */
import { isProjectId } from "@/lib/project-scope/scope";

/** The two kinds the Python `CaptureKind` admits. */
export const CAPTURE_KINDS = ["quick_note", "conversation_log"] as const;

export type CaptureKind = (typeof CAPTURE_KINDS)[number];

/** Shape validation only; ownership comes from the canonical Project read. */
export function isCaptureKind(value: unknown): value is CaptureKind {
  return typeof value === "string" && (CAPTURE_KINDS as readonly string[]).includes(value);
}

/** A Project selection, where `null` is the explicit "No Project" choice. */
export type CaptureProjectId = string | null;

/** The closed set of reasons this contract refuses a browser body. */
export type CaptureContractFailure = "invalid_project_id" | "invalid_capture_kind";

/**
 * A content-free refusal. It names the field class and nothing else: no authored
 * text, no raw body, no Project name, no exception payload.
 */
export class CaptureContractError extends Error {
  readonly reason: CaptureContractFailure;

  constructor(reason: CaptureContractFailure) {
    super(reason);
    this.name = "CaptureContractError";
    this.reason = reason;
  }
}

/** What a browser sends to `/api/capture`. `projectId` may be omitted or null. */
export interface CaptureCreateBody {
  readonly text: string;
  readonly captureKind: CaptureKind;
  readonly idempotencyKey: string;
  readonly projectId?: string | null;
}

/**
 * One frozen Capture intent.
 *
 * `sessionEpoch` is an in-memory stale-response generation counter. It is
 * authority freshness, not credential material, and is never part of the
 * canonical idempotency identity or the backend payload digest.
 */
export interface FrozenCaptureIntent {
  readonly principalId: string;
  readonly sessionEpoch: number;
  readonly captureKind: CaptureKind;
  readonly text: string;
  readonly idempotencyKey: string;
  readonly projectId: CaptureProjectId;
}

/**
 * The acknowledgement the BFF emits only for a receipt the backend committed.
 *
 * `receipt.projectId` is copied from the persisted gateway result. It is never a
 * request echo, never read from local context, and never defaulted.
 */
export interface PersistedCaptureAck {
  readonly shape: "backend";
  readonly status: "persisted";
  readonly captureKind: CaptureKind;
  readonly created: boolean;
  readonly receipt: {
    readonly receiptId: string;
    readonly captureId: string;
    readonly versionId: string;
    readonly versionNumber: number;
    readonly idempotencyKey: string;
    readonly contentSha256: string;
    readonly principalId: string;
    readonly issuedAt: string;
    readonly projectId: CaptureProjectId;
  };
}

/**
 * The Project a Capture request selected, or null for No Project.
 *
 * `present` distinguishes "the key was absent" from "the caller sent a value".
 * Both omission and an explicit `null` mean No Project. Anything else must
 * satisfy `isProjectId` exactly — empty and whitespace strings, padded
 * identifiers, booleans, numbers, arrays and objects all raise
 * `CaptureContractError` so the caller is refused rather than quietly filed
 * against no Project.
 */
export function parseCaptureProject(value: unknown, present: boolean): string | null {
  if (!present) return null;
  if (value === null) return null;
  if (!isProjectId(value)) throw new CaptureContractError("invalid_project_id");
  return value;
}

/**
 * The Capture kind a request selected.
 *
 * Kept beside the Project parser because the public route's historical default
 * (`quick_note` when the key is absent or null) is compatibility the new UI does
 * not rely on: it always sends an explicit kind.
 */
export function parseCaptureKind(value: unknown, present: boolean): CaptureKind {
  if (!present || value === null || value === undefined) return "quick_note";
  if (!isCaptureKind(value)) throw new CaptureContractError("invalid_capture_kind");
  return value;
}
