// @vitest-environment node
/**
 * T03 — the browser Capture contract (C01/C02).
 *
 * The question this file answers is narrow and load-bearing: when is a Project
 * selection "No Project", and when is it a refusal? A parser that answered
 * "refusal" with `null` would file a user's note against nothing while the UI
 * said it went to their Project, so every malformed input here must raise rather
 * than return.
 */
import { describe, expect, it } from "vitest";
import {
  CAPTURE_KINDS,
  CaptureContractError,
  isCaptureKind,
  parseCaptureKind,
  parseCaptureProject,
  type CaptureCreateBody,
  type FrozenCaptureIntent,
} from "./contract";

const PROJECT_A = "prj_aaaaaaaa11111111";
const PROJECT_B = "prj_bbbbbbbb22222222";

describe("parseCaptureProject", () => {
  it("treats omission as No Project", () => {
    expect(parseCaptureProject(undefined, false)).toBeNull();
  });

  it("treats an explicit null as No Project", () => {
    expect(parseCaptureProject(null, true)).toBeNull();
  });

  it("accepts a well-formed Project identifier unchanged", () => {
    expect(parseCaptureProject(PROJECT_A, true)).toBe(PROJECT_A);
    expect(parseCaptureProject(PROJECT_B, true)).toBe(PROJECT_B);
  });

  it("refuses an empty or whitespace string rather than reading it as No Project", () => {
    for (const value of ["", " ", "\t", "\n", "   "]) {
      expect(() => parseCaptureProject(value, true)).toThrow(CaptureContractError);
    }
  });

  it("refuses a padded identifier rather than trimming it", () => {
    for (const value of [` ${PROJECT_A}`, `${PROJECT_A} `, `\t${PROJECT_A}\n`]) {
      expect(() => parseCaptureProject(value, true)).toThrow(CaptureContractError);
    }
  });

  it("refuses scalars, arrays and objects", () => {
    for (const value of [true, false, 0, 1, 42, [PROJECT_A], { projectId: PROJECT_A }, {}, []]) {
      expect(() => parseCaptureProject(value, true)).toThrow(CaptureContractError);
    }
  });

  it("refuses an identifier that is not the canonical Project shape", () => {
    for (const value of ["prj_short", "PRJ_AAAAAAAA11111111", "proj_aaaaaaaa11111111", "aaaaaaaa11111111"]) {
      expect(() => parseCaptureProject(value, true)).toThrow(CaptureContractError);
    }
  });

  it("names the field class and nothing else in its refusal", () => {
    try {
      parseCaptureProject("prj_not-a-project", true);
      expect.unreachable("a malformed Project must not parse");
    } catch (error) {
      expect(error).toBeInstanceOf(CaptureContractError);
      expect((error as CaptureContractError).reason).toBe("invalid_project_id");
      expect((error as CaptureContractError).message).toBe("invalid_project_id");
      expect((error as CaptureContractError).message).not.toContain("prj_not-a-project");
    }
  });

  it("returns null only for omission or explicit null, never for a present undefined", () => {
    // `'projectId' in body` is false when the key is absent, which is the only
    // way a caller omits it. A present key holding `undefined` cannot survive
    // JSON at all, so it is refused rather than quietly read as No Project.
    expect(() => parseCaptureProject(undefined, true)).toThrow(CaptureContractError);
  });
});

describe("the closed Capture kinds", () => {
  it("admits exactly the two Python CaptureKind values", () => {
    expect([...CAPTURE_KINDS]).toEqual(["quick_note", "conversation_log"]);
  });

  it("rejects Task and Constraint as Capture kinds", () => {
    for (const value of ["task", "constraint", "voice_memo", "", null, 1, {}]) {
      expect(isCaptureKind(value)).toBe(false);
      if (value !== null) expect(() => parseCaptureKind(value, true)).toThrow(CaptureContractError);
    }
  });

  it("defaults an absent or null kind to quick_note for the existing public route", () => {
    expect(parseCaptureKind(undefined, false)).toBe("quick_note");
    expect(parseCaptureKind(null, true)).toBe("quick_note");
  });

  it("carries an explicit conversation log through", () => {
    expect(parseCaptureKind("conversation_log", true)).toBe("conversation_log");
  });
});

describe("browser normalization happens once, at the boundary", () => {
  it("the frozen intent holds the already-trimmed text and does not re-normalize", () => {
    const authored = "  a note about the café with  inner   spacing\nand Mixed Case \n";
    const accepted = authored.trim();
    const intent: FrozenCaptureIntent = {
      principalId: "aaaa0001-0000-0000-0000-000000000001",
      sessionEpoch: 1,
      captureKind: "quick_note",
      text: accepted,
      idempotencyKey: "k1",
      projectId: PROJECT_A,
    };
    // Exactly `trim()` and nothing more: no Unicode normalization, no case
    // folding, no newline rewrite, no collapsing of interior whitespace.
    expect(intent.text).toBe("a note about the café with  inner   spacing\nand Mixed Case");
    expect(intent.text).not.toBe(intent.text.normalize("NFC"));
    expect(intent.text).not.toBe(intent.text.toLowerCase());
    expect(intent.text).toContain("\n");
    expect(intent.text.trim()).toBe(intent.text);
  });

  it("a body may omit projectId entirely and still type-check", () => {
    const body: CaptureCreateBody = {
      text: "a note",
      captureKind: "quick_note",
      idempotencyKey: "k1",
    };
    expect(parseCaptureProject(
      (body as { projectId?: string | null }).projectId,
      "projectId" in body,
    )).toBeNull();
  });
});
