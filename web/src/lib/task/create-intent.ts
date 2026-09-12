/**
 * Task create-session intent: one human intent → one idempotency key.
 * Lives outside React form state so unmount cannot erase unresolved intents.
 */

import { isDefinitiveAttemptFailure, type ApiFailure } from "@/lib/api/work-client";
import {
  classifyMutationError,
  isAmbiguousMutationFailure,
  type MutationError,
} from "@/lib/task/mutation-state";

export type CreateIntentPhase =
  | "draft"
  | "pending"
  | "ambiguous"
  | "failed"
  | "confirmed"
  | "abandoned";

export interface TaskCreateRequest {
  title: string;
  description?: string;
  priority?: string;
  dueAt?: string;
  commitmentId?: string;
  role?: string;
  projectId?: string;
  situationId?: string;
  clientContext?: string;
}

export interface CreateIntentHooks<TResult = unknown> {
  /** Called after confirmed server result, before feedback. */
  reconcile?: (result: TResult) => void | Promise<void>;
  /** Called after reconcile, before intent retirement. */
  feedback?: (result: TResult) => void | Promise<void>;
  /** Sync client validation before freeze/dispatch. Throw or return message to refuse. */
  validate?: (request: TaskCreateRequest) => void;
}

export interface CreateIntentSnapshot {
  readonly intentId: string;
  readonly idempotencyKey: string;
  readonly createdAt: number;
  readonly phase: CreateIntentPhase;
  readonly draft: TaskCreateRequest;
  readonly frozenRequest?: TaskCreateRequest;
  readonly result?: unknown;
  readonly error?: MutationError;
  readonly dispatching: boolean;
}

export type CreateDispatchFn<TResult = unknown> = (args: {
  request: TaskCreateRequest;
  idempotencyKey: string;
  intentId: string;
}) => Promise<TResult>;

function cloneRequest(request: TaskCreateRequest): TaskCreateRequest {
  return { ...request };
}

function materialSignature(request: TaskCreateRequest): string {
  return JSON.stringify({
    title: request.title ?? "",
    description: request.description ?? "",
    priority: request.priority ?? "",
    dueAt: request.dueAt ?? "",
    commitmentId: request.commitmentId ?? "",
    role: request.role ?? "",
    projectId: request.projectId ?? "",
    situationId: request.situationId ?? "",
    clientContext: request.clientContext ?? "",
  });
}

function requestsMateriallyEqual(a: TaskCreateRequest, b: TaskCreateRequest): boolean {
  return materialSignature(a) === materialSignature(b);
}

function mintIntentId(): string {
  return crypto.randomUUID();
}

function idempotencyKeyFor(intentId: string): string {
  // Domain IDEMPOTENCY_KEY_PATTERN is [A-Za-z0-9_-]{8,128} — no colons.
  return `task-create-${intentId}`;
}

export class CreateIntentSession {
  readonly intentId: string;
  readonly idempotencyKey: string;
  readonly createdAt: number;
  private phase: CreateIntentPhase = "draft";
  private draft: TaskCreateRequest;
  private frozenRequest?: TaskCreateRequest;
  private result?: unknown;
  private error?: MutationError;
  private dispatchToken: symbol | null = null;
  private retired = false;

  constructor(initialDraft: TaskCreateRequest = { title: "" }, intentId = mintIntentId()) {
    this.intentId = intentId;
    this.idempotencyKey = idempotencyKeyFor(intentId);
    this.createdAt = Date.now();
    this.draft = cloneRequest(initialDraft);
  }

  snapshot(): CreateIntentSnapshot {
    return {
      intentId: this.intentId,
      idempotencyKey: this.idempotencyKey,
      createdAt: this.createdAt,
      phase: this.phase,
      draft: cloneRequest(this.draft),
      frozenRequest: this.frozenRequest ? cloneRequest(this.frozenRequest) : undefined,
      result: this.result,
      error: this.error,
      dispatching: this.dispatchToken !== null,
    };
  }

  getPhase(): CreateIntentPhase {
    return this.phase;
  }

  getDraft(): TaskCreateRequest {
    return cloneRequest(this.draft);
  }

  getFrozenRequest(): TaskCreateRequest | undefined {
    return this.frozenRequest ? cloneRequest(this.frozenRequest) : undefined;
  }

  isRetired(): boolean {
    return this.retired;
  }

  /**
   * Update draft fields. Blocked while ambiguous (frozen request may still commit)
   * or while a dispatch is in flight. After definitive failure, material change
   * requires minting a new session via the store (see `CreateIntentStore.replaceAfterMaterialEdit`).
   */
  updateDraft(partial: Partial<TaskCreateRequest>): void {
    this.assertNotRetired();
    if (this.phase === "ambiguous") {
      throw new Error("material create edits are blocked while the prior attempt is ambiguous");
    }
    if (this.dispatchToken !== null || this.phase === "pending") {
      throw new Error("create draft cannot change while a dispatch is in flight");
    }
    if (this.phase === "confirmed" || this.phase === "abandoned") {
      throw new Error(`create draft cannot change in phase ${this.phase}`);
    }
    this.draft = cloneRequest({ ...this.draft, ...partial });
  }

  /** Pre-dispatch cancel. Unresolved pending/ambiguous intents are retained by the store. */
  abandon(): void {
    this.assertNotRetired();
    if (this.phase === "pending" || this.phase === "ambiguous") {
      throw new Error("cannot abandon an unresolved create intent; dismiss UI only");
    }
    if (this.phase === "confirmed") {
      this.retired = true;
      return;
    }
    this.phase = "abandoned";
    this.retired = true;
  }

  /**
   * Lifecycle: sync validate → acquire sync mutex → freeze → pending → dispatch.
   * Concurrent submit while pending returns `{ refused: true }` with no second network call.
   */
  async submit<TResult>(
    dispatch: CreateDispatchFn<TResult>,
    hooks: CreateIntentHooks<TResult> = {},
  ): Promise<{ refused: true; reason: string } | { refused: false; result: TResult }> {
    this.assertNotRetired();

    if (this.phase === "ambiguous" && this.frozenRequest) {
      return this.retry(dispatch, hooks);
    }

    if (this.dispatchToken !== null || this.phase === "pending") {
      return { refused: true, reason: "create dispatch already in flight" };
    }

    if (this.phase === "confirmed") {
      return { refused: true, reason: "create intent already confirmed" };
    }

    if (this.phase === "abandoned") {
      return { refused: true, reason: "create intent abandoned" };
    }

    if (
      this.phase === "failed" &&
      this.frozenRequest &&
      !requestsMateriallyEqual(this.draft, this.frozenRequest)
    ) {
      return {
        refused: true,
        reason: "material create edit after definitive failure requires a new intent",
      };
    }

    const candidate =
      this.phase === "failed" && this.frozenRequest && requestsMateriallyEqual(this.draft, this.frozenRequest)
        ? cloneRequest(this.frozenRequest)
        : cloneRequest(this.draft);

    try {
      hooks.validate?.(candidate);
    } catch (error) {
      this.phase = "failed";
      this.error = classifyMutationError(error);
      this.frozenRequest = undefined;
      return { refused: true, reason: this.error.message };
    }

    if (!candidate.title.trim()) {
      this.phase = "failed";
      this.error = { subtype: "validation", message: "title is required" };
      return { refused: true, reason: this.error.message };
    }

    const token = Symbol("create-dispatch");
    this.dispatchToken = token;
    this.frozenRequest = cloneRequest(candidate);
    this.draft = cloneRequest(candidate);
    this.phase = "pending";
    this.error = undefined;
    this.result = undefined;

    try {
      const result = await dispatch({
        request: cloneRequest(this.frozenRequest),
        idempotencyKey: this.idempotencyKey,
        intentId: this.intentId,
      });
      if (this.dispatchToken !== token) {
        return { refused: true, reason: "create dispatch ownership lost" };
      }
      await this.confirm(result, hooks);
      return { refused: false, result };
    } catch (error) {
      this.settleFailure(error);
      throw error;
    } finally {
      if (this.dispatchToken === token) this.dispatchToken = null;
    }
  }

  /** Same-key retry for ambiguous transport results only. */
  async retry<TResult>(
    dispatch: CreateDispatchFn<TResult>,
    hooks: CreateIntentHooks<TResult> = {},
  ): Promise<{ refused: true; reason: string } | { refused: false; result: TResult }> {
    this.assertNotRetired();
    if (this.phase !== "ambiguous" || !this.frozenRequest) {
      return { refused: true, reason: "retry requires an ambiguous frozen create request" };
    }
    if (this.dispatchToken !== null) {
      return { refused: true, reason: "create dispatch already in flight" };
    }

    const token = Symbol("create-retry");
    this.dispatchToken = token;
    this.phase = "pending";
    this.error = undefined;

    try {
      const result = await dispatch({
        request: cloneRequest(this.frozenRequest),
        idempotencyKey: this.idempotencyKey,
        intentId: this.intentId,
      });
      if (this.dispatchToken !== token) {
        return { refused: true, reason: "create dispatch ownership lost" };
      }
      await this.confirm(result, hooks);
      return { refused: false, result };
    } catch (error) {
      this.settleFailure(error);
      throw error;
    } finally {
      if (this.dispatchToken === token) this.dispatchToken = null;
    }
  }

  /**
   * Success order: mark confirmed → reconcile → feedback → retire.
   * Hook failures must not roll a confirmed create back into ambiguous/failed.
   */
  private async confirm<TResult>(result: TResult, hooks: CreateIntentHooks<TResult>): Promise<void> {
    this.phase = "confirmed";
    this.result = result;
    this.error = undefined;
    try {
      await hooks.reconcile?.(result);
    } catch {
      // List refresh / barrier work is best-effort after the server accepted create.
    }
    try {
      await hooks.feedback?.(result);
    } catch {
      // Feedback is best-effort; the create itself already confirmed.
    }
    this.retired = true;
  }

  private settleFailure(error: unknown): void {
    const classified = classifyMutationError(error);
    const ambiguous =
      isAmbiguousMutationFailure(error) ||
      (!isDefinitiveAttemptFailure(error) && classified.subtype !== "contract");
    if (ambiguous) {
      this.phase = "ambiguous";
      this.error = classified;
      return;
    }
    // Definitive: preserve draft; keep frozen for unchanged re-auth retry identity.
    this.phase = "failed";
    this.error = classified;
    if (!this.frozenRequest) this.frozenRequest = cloneRequest(this.draft);
  }

  private assertNotRetired(): void {
    if (this.retired && this.phase !== "confirmed") {
      throw new Error("create intent is retired");
    }
  }
}

/**
 * Store owned by Task runtime / AppShell — not React form state.
 * Unmount of a create form must not erase unresolved intents.
 */
export class CreateIntentStore {
  private sessions = new Map<string, CreateIntentSession>();
  private activeSessionId: string | undefined;

  /** Mint create_intent_id when the create session opens, before submit can race. */
  openSession(initialDraft: TaskCreateRequest = { title: "" }): CreateIntentSession {
    const session = new CreateIntentSession(initialDraft);
    this.sessions.set(session.intentId, session);
    this.activeSessionId = session.intentId;
    return session;
  }

  getSession(intentId: string): CreateIntentSession | undefined {
    return this.sessions.get(intentId);
  }

  getActiveSession(): CreateIntentSession | undefined {
    return this.activeSessionId ? this.sessions.get(this.activeSessionId) : undefined;
  }

  /** Resume an unresolved (pending/ambiguous) intent instead of minting a new one. */
  getUnresolvedSession(): CreateIntentSession | undefined {
    for (const session of this.sessions.values()) {
      const phase = session.getPhase();
      if (phase === "pending" || phase === "ambiguous") return session;
    }
    return undefined;
  }

  /**
   * After definitive known-non-applied failure, a material draft change requires a
   * new deliberate intent (never dedupe by title/date/content across sessions).
   */
  replaceAfterMaterialEdit(session: CreateIntentSession, nextDraft: TaskCreateRequest): CreateIntentSession {
    if (session.getPhase() !== "failed") {
      throw new Error("new create intent after edit requires a definitive failed session");
    }
    const prior = session.getFrozenRequest() ?? session.getDraft();
    if (requestsMateriallyEqual(prior, nextDraft)) {
      session.updateDraft(nextDraft);
      return session;
    }
    session.abandon();
    this.sessions.delete(session.intentId);
    return this.openSession(nextDraft);
  }

  /** Drop terminal sessions; keep unresolved for shell feedback/retry. */
  pruneTerminal(): void {
    for (const [id, session] of this.sessions) {
      const phase = session.getPhase();
      if (phase === "confirmed" || phase === "abandoned" || session.isRetired()) {
        this.sessions.delete(id);
      }
    }
    if (this.activeSessionId && !this.sessions.has(this.activeSessionId)) {
      this.activeSessionId = undefined;
    }
  }

  clearAll(): void {
    this.sessions.clear();
    this.activeSessionId = undefined;
  }
}

/** Convenience: classify create failures using work-client definitive rules. */
export function isCreateAmbiguousFailure(error: unknown): boolean {
  return isAmbiguousMutationFailure(error) || !isDefinitiveAttemptFailure(error as ApiFailure);
}

export function createIntentStore(): CreateIntentStore {
  return new CreateIntentStore();
}
