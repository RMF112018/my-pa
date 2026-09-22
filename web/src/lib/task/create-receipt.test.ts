// @vitest-environment node
/**
 * T13 — the Task create result gate (C08).
 *
 * The question is narrow: what may be announced as "Task created"? Only a
 * canonical mutation that answers the request that was sent. Everything else is
 * ambiguous — not a refusal, because the backend may well have committed — and
 * the intent stays unresolved under the same key.
 */
import { describe, expect, it } from "vitest";
import {
  isUnreadableCreateResponse,
  unverifiedTaskCreateError,
  verifyTaskCreateResult,
} from "./create-receipt";
import { taskCreateResponse } from "./testing/task-mutation-fixture";
import type { TaskCreateRequest } from "./create-intent";
import type { ApiFailure } from "@/lib/api/work-client";

const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";
const REQUEST: TaskCreateRequest = { title: "Coordinate the review" };

describe("unverifiedTaskCreateError", () => {
  it("is the existing unavailable classification, with actionable product language", () => {
    const error = unverifiedTaskCreateError();
    expect(error).toBeInstanceOf(Error);
    expect(error.status).toBe(503);
    expect(error.code).toBe("unavailable");
    expect(error.errorClass).toBe("unavailable");
    expect(error.message).toBe(
      "Task confirmation could not be verified. Retry the same create.",
    );
    // It must never claim nothing was created: that is exactly what is unknown.
    expect(error.message).not.toMatch(/not created|nothing was/i);
  });
});

describe("isUnreadableCreateResponse", () => {
  it("recognises the transport's invalid-shape 503 and nothing else", () => {
    const contract: ApiFailure = new Error("unreadable");
    contract.status = 503;
    contract.code = "upstream_contract_invalid";
    expect(isUnreadableCreateResponse(contract)).toBe(true);

    const refused: ApiFailure = new Error("refused");
    refused.status = 409;
    refused.code = "conflict";
    expect(isUnreadableCreateResponse(refused)).toBe(false);
    expect(isUnreadableCreateResponse(new Error("plain"))).toBe(false);
    expect(isUnreadableCreateResponse("not an error")).toBe(false);
  });
});

describe("a canonical create is accepted", () => {
  it("returns the decoded mutation for a No Project create", () => {
    const result = verifyTaskCreateResult(taskCreateResponse(), REQUEST);
    expect(result.task.project_id).toBeNull();
    expect(result.history.action).toBe("create");
    expect(result.replayed).toBe(false);
  });

  it("returns the decoded mutation for a Project-bearing create", () => {
    const result = verifyTaskCreateResult(
      taskCreateResponse({ projectId: PROJECT_A }),
      { ...REQUEST, projectId: PROJECT_A },
    );
    expect(result.task.project_id).toBe(PROJECT_A);
  });

  it("accepts a canonical replay whose current version has moved on", () => {
    // A replay can return a Task later work has already advanced. The history
    // entry describes this create; the row's current version need not match it.
    const body = taskCreateResponse({ replayed: true });
    body.task.version = 7;
    const result = verifyTaskCreateResult(body, REQUEST);
    expect(result.replayed).toBe(true);
    expect(result.task.version).toBe(7);
    expect(result.history.after_version).toBe(1);
  });
});

describe("a create that cannot be verified is ambiguous", () => {
  function refuses(input: unknown, request: TaskCreateRequest = REQUEST) {
    expect(() => verifyTaskCreateResult(input, request)).toThrow(
      "Task confirmation could not be verified",
    );
    try {
      verifyTaskCreateResult(input, request);
    } catch (error) {
      expect((error as ApiFailure).errorClass).toBe("unavailable");
    }
  }

  it("refuses anything that is not a backend-shaped record", () => {
    refuses(null);
    refuses([taskCreateResponse()]);
    refuses("created");
    const noShape = taskCreateResponse() as Record<string, unknown>;
    delete noShape.shape;
    refuses(noShape);
    refuses({ ...taskCreateResponse(), shape: "synthetic" });
  });

  it("refuses a body the canonical decoder rejects", () => {
    const missingHistory = taskCreateResponse() as Record<string, unknown>;
    delete missingHistory.history;
    refuses(missingHistory);

    const badLifecycle = taskCreateResponse();
    (badLifecycle.task as Record<string, unknown>).lifecycle_state = "invented";
    refuses(badLifecycle);

    const badReplayed = taskCreateResponse() as Record<string, unknown>;
    badReplayed.replayed = "false";
    refuses(badReplayed);
  });

  it("refuses a Project that is not the one the request asked for", () => {
    refuses(taskCreateResponse({ projectId: PROJECT_B }), { ...REQUEST, projectId: PROJECT_A });
    // A create that named no Project must come back with null, not a Project.
    refuses(taskCreateResponse({ projectId: PROJECT_A }), REQUEST);
    // And a create that named one must not come back with null.
    refuses(taskCreateResponse({ projectId: null }), { ...REQUEST, projectId: PROJECT_A });
  });

  it("refuses history that describes a different Task", () => {
    refuses(taskCreateResponse({ historyTaskId: "tsk_cccccccc33333333" }));
  });

  it("refuses history that is not an applied create", () => {
    refuses(taskCreateResponse({ action: "update" }));
    refuses(taskCreateResponse({ outcome: "rejected" }));
    refuses(taskCreateResponse({ outcome: "no_op" }));
  });

  it("carries no authored title, Project identifier or raw body in the failure", () => {
    try {
      verifyTaskCreateResult(taskCreateResponse({ projectId: PROJECT_B }), {
        title: "Confidential title",
        projectId: PROJECT_A,
      });
      expect.unreachable("a Project mismatch must not verify");
    } catch (error) {
      const message = (error as Error).message;
      expect(message).not.toContain("Confidential title");
      expect(message).not.toContain(PROJECT_A);
      expect(message).not.toContain(PROJECT_B);
    }
  });
});
