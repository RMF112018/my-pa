// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { decodeKnowledgeAssertionsRead } from "./knowledge.assertions.read";

const SUCCESS = JSON.parse(
  readFileSync(join(process.cwd(), "src/lib/api/decode/fixtures/python/success.json"), "utf8"),
) as Record<string, Record<string, unknown>>;

const PAYLOAD = SUCCESS["knowledge.assertions.read"]!;
const ASSERTION = PAYLOAD.assertion as Record<string, unknown>;

describe("decodeKnowledgeAssertionsRead", () => {
  it("decodes the committed Python assertion_view payload byte-for-byte", () => {
    const decoded = decodeKnowledgeAssertionsRead(PAYLOAD);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value).toEqual(PAYLOAD);
  });

  it("fails closed when the assertion object is missing", () => {
    expect(decodeKnowledgeAssertionsRead({}).ok).toBe(false);
    expect(decodeKnowledgeAssertionsRead({ assertion: null }).ok).toBe(false);
  });

  it("fails closed on a missing required key or a token outside the Python vocabulary", () => {
    for (const key of ["assertion_id", "predicate_code", "lifecycle", "value", "version"]) {
      const { [key]: _, ...rest } = ASSERTION;
      expect(decodeKnowledgeAssertionsRead({ assertion: rest }).ok, key).toBe(false);
    }
    for (const [key, value] of [
      ["lifecycle", "live"],
      ["value_type", "number"],
      ["epistemic_status", "guessed"],
      ["classification", "public"],
      ["subject_kind", "capture"],
      ["qualifier", "text"],
    ] as const) {
      expect(
        decodeKnowledgeAssertionsRead({ assertion: { ...ASSERTION, [key]: value } }).ok,
        key,
      ).toBe(false);
    }
  });

  it("ignores keys the contract does not name", () => {
    const decoded = decodeKnowledgeAssertionsRead({
      assertion: { ...ASSERTION, evidence_text: "never rendered" },
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(JSON.stringify(decoded.value)).not.toContain("never rendered");
  });
});
