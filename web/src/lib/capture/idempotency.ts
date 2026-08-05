/**
 * Per-principal capture idempotency — WP-03.
 *
 * The Python capture plane enforces `UNIQUE (principal_id, idempotency_key)`
 * at Alembic revision `e7f3a9c2d514` (ADR-005, PKL-MYPA-D-WP03-001). Until
 * the web gateway is wired to that pipeline, this in-memory admission mirror
 * pins the same contract at the BFF boundary so the dialog, the client
 * wrapper, and the tests exercise real semantics rather than a stub that
 * mints a fresh receipt on every replay:
 *
 * - the idempotency key is scoped to the authenticated principal — two
 *   principals may submit the same key and each receives their own receipt;
 * - a replay (same principal, same key, same content) returns the original
 *   receipt with `created = false`;
 * - the same key with different content is a conflict, never a silent
 *   overwrite;
 * - the store holds a content digest, never the capture text (QC-AC-041
 *   discipline: capture text appears in no receipt and no admission record).
 */

export interface AdmissionReceipt {
  receiptId: string;
  created: boolean;
}

export type AdmissionOutcome =
  | { ok: true; receipt: AdmissionReceipt }
  | { ok: false; conflict: true };

interface StoredAdmission {
  receiptId: string;
  contentDigest: string;
}

/** FNV-1a over UTF-16 code units — deterministic, dependency-free digest. */
function contentDigest(text: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return `fnv1a:${(hash >>> 0).toString(16).padStart(8, "0")}:${text.length}`;
}

export class CaptureAdmissionStore {
  // principalId -> idempotencyKey -> admission record (digest only, no text).
  private readonly byPrincipal = new Map<string, Map<string, StoredAdmission>>();

  admit(principalId: string, idempotencyKey: string, text: string): AdmissionOutcome {
    let partition = this.byPrincipal.get(principalId);
    if (!partition) {
      partition = new Map();
      this.byPrincipal.set(principalId, partition);
    }
    const digest = contentDigest(text);
    const existing = partition.get(idempotencyKey);
    if (existing) {
      if (existing.contentDigest !== digest) {
        return { ok: false, conflict: true };
      }
      return { ok: true, receipt: { receiptId: existing.receiptId, created: false } };
    }
    const receiptId = `rcpt-${crypto.randomUUID()}`;
    partition.set(idempotencyKey, { receiptId, contentDigest: digest });
    return { ok: true, receipt: { receiptId, created: true } };
  }
}

/** Module-scoped store shared by the capture route within one server process. */
export const captureAdmissions = new CaptureAdmissionStore();
