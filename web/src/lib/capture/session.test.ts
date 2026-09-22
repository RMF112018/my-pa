// @vitest-environment node
/**
 * T10 — every local Capture transition (C03).
 *
 * The reducer is pure, so each of these is a statement about what the shell will
 * and will not do, checked directly rather than through a rendered surface. The
 * ones that matter most are the negatives: what a global navigation cannot do,
 * what a late reply cannot do, and what closing a dialog does not cancel.
 */
import { describe, expect, it } from "vitest";
import {
  activeDraft,
  beginCaptureExperience,
  captureIntentEquals,
  captureSessionReducer,
  freezeCaptureIntent,
  hasUnresolvedIntent,
  isEditable,
  type CaptureSessionState,
} from "./session";
import type { FrozenCaptureIntent } from "./contract";

const PRINCIPAL_A = "aaaa0001-0000-0000-0000-000000000001";
const PRINCIPAL_B = "bbbb0002-0000-0000-0000-000000000002";
const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";

function open(projectId: string | null = PROJECT_A, epoch = 1): CaptureSessionState {
  return beginCaptureExperience({
    experienceId: "exp-1",
    principalId: PRINCIPAL_A,
    sessionEpoch: epoch,
    projectId,
  });
}

function typed(state: CaptureSessionState, text: string): CaptureSessionState {
  return captureSessionReducer(state, { type: "edit_draft", form: state.form, text });
}

describe("a fresh experience reads global scope once", () => {
  it("starts under the global Project and resolves its name", () => {
    const state = open(PROJECT_A);
    expect(state.projectId).toBe(PROJECT_A);
    expect(state.projectName).toEqual({ kind: "resolving" });
    expect(state.modalOwner).toBe("capture");
    expect(state.outcome).toBe("editable");
  });

  it("starts with No Project under ALL_PROJECTS, and infers no last-used one", () => {
    const state = open(null);
    expect(state.projectId).toBeNull();
    expect(state.projectName).toEqual({ kind: "none" });
  });

  it("reinitializes from global scope on a later open rather than reusing the local one", () => {
    let state = open(PROJECT_A);
    state = captureSessionReducer(state, { type: "select_project", projectId: PROJECT_B });
    expect(state.projectId).toBe(PROJECT_B);
    state = captureSessionReducer(state, {
      type: "open",
      experienceId: "exp-2",
      principalId: PRINCIPAL_A,
      sessionEpoch: 1,
      projectId: null,
    });
    expect(state.projectId).toBeNull();
    expect(state.noteDraft).toBe("");
  });
});

describe("local selection is local", () => {
  it("changes only the local ID and invalidates the name request", () => {
    const state = captureSessionReducer(open(PROJECT_A), {
      type: "select_project",
      projectId: PROJECT_B,
    });
    expect(state.projectId).toBe(PROJECT_B);
    expect(state.nameEpoch).toBe(1);
    expect(state.projectName).toEqual({ kind: "resolving" });
  });

  it("keeps the draft text across a Project change", () => {
    let state = typed(open(PROJECT_A), "synthetic note");
    state = captureSessionReducer(state, { type: "select_project", projectId: null });
    expect(state.noteDraft).toBe("synthetic note");
    expect(state.projectId).toBeNull();
  });

  it("ignores a name that answers a superseded request", () => {
    let state = open(PROJECT_A);
    state = captureSessionReducer(state, { type: "select_project", projectId: PROJECT_B });
    const stale = captureSessionReducer(state, {
      type: "project_name",
      nameEpoch: 0,
      name: { kind: "named", name: "North tower" },
    });
    expect(stale).toBe(state);
    const current = captureSessionReducer(state, {
      type: "project_name",
      nameEpoch: 1,
      name: { kind: "named", name: "South slab" },
    });
    expect(current.projectName).toEqual({ kind: "named", name: "South slab" });
  });

  it("is inert to a global scope change, open or not", () => {
    const state = open(PROJECT_A);
    expect(
      captureSessionReducer(state, { type: "global_scope_changed", projectId: PROJECT_B }),
    ).toBe(state);
  });
});

describe("the two forms keep separate drafts", () => {
  it("preserves both, with no request and no key, across a switch", () => {
    let state = typed(open(PROJECT_A), "a quick note");
    state = captureSessionReducer(state, { type: "select_form", form: "conversation_log" });
    expect(state.form).toBe("conversation_log");
    expect(activeDraft(state)).toBe("");
    state = typed(state, "a conversation");
    expect(state.noteDraft).toBe("a quick note");
    expect(state.conversationDraft).toBe("a conversation");
    // Same local Project throughout.
    expect(state.projectId).toBe(PROJECT_A);
    expect(state.intent).toBeNull();
  });
});

describe("Capture to Task and back", () => {
  it("suspends rather than ends the experience, keeping context and drafts", () => {
    let state = typed(open(PROJECT_A), "synthetic note");
    state = captureSessionReducer(state, { type: "to_task" });
    expect(state.modalOwner).toBe("task");
    expect(state.experienceId).toBe("exp-1");
    expect(state.noteDraft).toBe("synthetic note");
    expect(state.projectId).toBe(PROJECT_A);
    // Nothing was captured or queued on the way.
    expect(state.intent).toBeNull();
    expect(state.outcome).toBe("editable");
  });

  it("adopts the Project the Task sheet actually returned", () => {
    let state = captureSessionReducer(open(PROJECT_B), { type: "to_task" });
    state = captureSessionReducer(state, { type: "task_back", projectId: PROJECT_A });
    expect(state.modalOwner).toBe("capture");
    // A frozen Task intent against A resumed, so Capture shows A rather than the
    // B it proposed. It is never silently relabelled the other way.
    expect(state.projectId).toBe(PROJECT_A);
  });

  it("does not move a Capture Project that is itself frozen", () => {
    let state = typed(open(PROJECT_A), "synthetic note");
    state = captureSessionReducer(state, {
      type: "freeze",
      intent: freezeCaptureIntent(state, "cap-1"),
    });
    state = captureSessionReducer(state, { type: "task_back", projectId: PROJECT_B });
    expect(state.projectId).toBe(PROJECT_A);
  });
});

describe("freezing, and what it disables", () => {
  it("freezes Principal, epoch, kind, trimmed text, Project and key together", () => {
    const state = typed(open(PROJECT_A), "  synthetic note  ");
    const intent = freezeCaptureIntent(state, "cap-1");
    expect(intent).toEqual({
      principalId: PRINCIPAL_A,
      sessionEpoch: 1,
      captureKind: "quick_note",
      text: "synthetic note",
      idempotencyKey: "cap-1",
      projectId: PROJECT_A,
    });
    // Exactly `trim()`: no normalization, no case folding, no newline rewrite.
    expect(freezeCaptureIntent(typed(state, "Café\nsecond"), "k").text).toBe(
      "Café\nsecond",
    );
  });

  it("blocks text, kind and Project edits while a submission is in flight", () => {
    let state = typed(open(PROJECT_A), "synthetic note");
    state = captureSessionReducer(state, {
      type: "freeze",
      intent: freezeCaptureIntent(state, "cap-1"),
    });
    expect(isEditable(state)).toBe(false);
    expect(captureSessionReducer(state, { type: "edit_draft", form: "quick_note", text: "x" })).toBe(
      state,
    );
    expect(captureSessionReducer(state, { type: "select_form", form: "conversation_log" })).toBe(
      state,
    );
    expect(captureSessionReducer(state, { type: "select_project", projectId: PROJECT_B })).toBe(
      state,
    );
  });
});

describe("results, and the ones that must not land", () => {
  function submitted() {
    const editable = typed(open(PROJECT_A), "synthetic note");
    return captureSessionReducer(editable, {
      type: "freeze",
      intent: freezeCaptureIntent(editable, "cap-1"),
    });
  }

  it("retires the intent and clears only the submitted draft on a verified success", () => {
    let state = submitted();
    state = captureSessionReducer(state, { type: "select_form", form: "conversation_log" });
    // (ignored while frozen — the conversation draft is untouched either way)
    state = captureSessionReducer(state, {
      type: "result",
      experienceId: "exp-1",
      sessionEpoch: 1,
      outcome: "persisted",
    });
    expect(state.outcome).toBe("persisted");
    expect(state.intent).toBeNull();
    expect(state.noteDraft).toBe("");
  });

  it("keeps the frozen intent authoritative on an ambiguous result", () => {
    const state = captureSessionReducer(submitted(), {
      type: "result",
      experienceId: "exp-1",
      sessionEpoch: 1,
      outcome: "ambiguous",
    });
    expect(state.outcome).toBe("ambiguous");
    expect(state.intent?.idempotencyKey).toBe("cap-1");
    expect(hasUnresolvedIntent(state)).toBe(true);
    // Still not editable: a retry resends exactly this.
    expect(isEditable(state)).toBe(false);
  });

  it("returns to editable on a definitive refusal, keeping the form and the Project", () => {
    const state = captureSessionReducer(submitted(), {
      type: "result",
      experienceId: "exp-1",
      sessionEpoch: 1,
      outcome: "refused",
    });
    expect(state.outcome).toBe("refused");
    expect(state.intent).toBeNull();
    expect(state.projectId).toBe(PROJECT_A);
    expect(state.noteDraft).toBe("synthetic note");
    expect(isEditable(state)).toBe(true);
  });

  it("transfers ownership to the queue only on a committed enqueue", () => {
    const state = captureSessionReducer(submitted(), {
      type: "result",
      experienceId: "exp-1",
      sessionEpoch: 1,
      outcome: "enqueued",
    });
    expect(state.outcome).toBe("enqueued");
    expect(state.noteDraft).toBe("");
  });

  it("drops a result belonging to a different experience", () => {
    const state = submitted();
    expect(
      captureSessionReducer(state, {
        type: "result",
        experienceId: "exp-old",
        sessionEpoch: 1,
        outcome: "persisted",
      }),
    ).toBe(state);
  });

  it("drops a result from a superseded authentication epoch", () => {
    const state = submitted();
    expect(
      captureSessionReducer(state, {
        type: "result",
        experienceId: "exp-1",
        sessionEpoch: 0,
        outcome: "persisted",
      }),
    ).toBe(state);
  });
});

describe("closing is not cancelling", () => {
  it("closes the surface but retains an unresolved submitted intent", () => {
    let state = typed(open(PROJECT_A), "synthetic note");
    state = captureSessionReducer(state, {
      type: "freeze",
      intent: freezeCaptureIntent(state, "cap-1"),
    });
    state = captureSessionReducer(state, {
      type: "result",
      experienceId: "exp-1",
      sessionEpoch: 1,
      outcome: "ambiguous",
    });
    state = captureSessionReducer(state, { type: "close" });
    expect(state.modalOwner).toBe("none");
    expect(hasUnresolvedIntent(state)).toBe(true);
    expect(state.intent?.idempotencyKey).toBe("cap-1");

    // An explicit reopen resumes the same experience and the same intent.
    state = captureSessionReducer(state, { type: "reopen" });
    expect(state.modalOwner).toBe("capture");
    expect(state.experienceId).toBe("exp-1");
    expect(state.intent?.idempotencyKey).toBe("cap-1");
  });

  it("clears only this experience's unsent drafts on an explicit discard", () => {
    let state = typed(open(PROJECT_A), "synthetic note");
    state = captureSessionReducer(state, { type: "select_form", form: "conversation_log" });
    state = typed(state, "a conversation");
    state = captureSessionReducer(state, { type: "discard_unsent" });
    expect(state.noteDraft).toBe("");
    expect(state.conversationDraft).toBe("");
    // The Project selection and the experience survive; nothing global moved.
    expect(state.projectId).toBe(PROJECT_A);
    expect(state.experienceId).toBe("exp-1");
  });

  it("refuses to discard while an intent is unresolved", () => {
    let state = typed(open(PROJECT_A), "synthetic note");
    state = captureSessionReducer(state, {
      type: "freeze",
      intent: freezeCaptureIntent(state, "cap-1"),
    });
    expect(captureSessionReducer(state, { type: "discard_unsent" })).toBe(state);
  });
});

describe("an authentication change", () => {
  it("invalidates name results and closes the surface without rebinding the intent", () => {
    let state = typed(open(PROJECT_A), "synthetic note");
    state = captureSessionReducer(state, {
      type: "freeze",
      intent: freezeCaptureIntent(state, "cap-1"),
    });
    const before = state.intent!;
    state = captureSessionReducer(state, {
      type: "principal_changed",
      principalId: PRINCIPAL_B,
      sessionEpoch: 2,
    });
    expect(state.modalOwner).toBe("none");
    expect(state.nameEpoch).toBe(1);
    // The unresolved intent keeps its original Principal. It is never reissued
    // under whoever signed in afterwards.
    expect(state.intent).toEqual(before);
    expect(state.intent?.principalId).toBe(PRINCIPAL_A);
  });

  it("is a no-op when nothing actually changed", () => {
    const state = open(PROJECT_A);
    expect(
      captureSessionReducer(state, {
        type: "principal_changed",
        principalId: PRINCIPAL_A,
        sessionEpoch: 1,
      }),
    ).toBe(state);
  });
});

describe("captureIntentEquals", () => {
  const base: FrozenCaptureIntent = {
    principalId: PRINCIPAL_A,
    sessionEpoch: 1,
    captureKind: "quick_note",
    text: "synthetic note",
    idempotencyKey: "cap-1",
    projectId: PROJECT_A,
  };

  it("compares the tuple exactly, Project and null included", () => {
    expect(captureIntentEquals(base, { ...base })).toBe(true);
    expect(captureIntentEquals(base, { ...base, projectId: PROJECT_B })).toBe(false);
    expect(captureIntentEquals(base, { ...base, projectId: null })).toBe(false);
    expect(captureIntentEquals({ ...base, projectId: null }, { ...base, projectId: null })).toBe(
      true,
    );
    expect(captureIntentEquals(base, { ...base, text: "other" })).toBe(false);
    expect(captureIntentEquals(base, { ...base, captureKind: "conversation_log" })).toBe(false);
    expect(captureIntentEquals(base, { ...base, idempotencyKey: "cap-2" })).toBe(false);
    expect(captureIntentEquals(base, { ...base, principalId: PRINCIPAL_B })).toBe(false);
  });

  it("does not treat the in-memory epoch as identity", () => {
    expect(captureIntentEquals(base, { ...base, sessionEpoch: 99 })).toBe(true);
  });

  it("handles the absent intent", () => {
    expect(captureIntentEquals(null, null)).toBe(true);
    expect(captureIntentEquals(base, null)).toBe(false);
  });
});
