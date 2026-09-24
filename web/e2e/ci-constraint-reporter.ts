import path from "node:path";
import type { Reporter, TestCase, TestResult } from "@playwright/test/reporter";

const SPEC = "web/e2e/constraints-mutations.spec.ts";
const ABSOLUTE_SPEC = path.join(process.cwd(), "e2e", "constraints-mutations.spec.ts");

// This temporary CI diagnostic is bound to the declarations and assertion
// lines at this exact spec revision. A moved or unrecognised failure is silent.
const CASES = [
  {
    id: "CONSTRAINT_AUTHORING_JOURNEY",
    category: "authoring",
    title: "the Constraint authoring journey writes through the BFF to PostgreSQL",
    declarationLine: 170,
    assertionLines: new Set([
      114, 181, 183, 184, 185, 194, 196, 197, 198, 207, 216, 218, 230, 232, 243, 244,
      245, 248, 249, 250, 252, 253, 254, 259, 260, 261, 264, 265, 269, 272,
      280, 281, 293, 297, 298, 299, 300, 304, 306, 307, 308, 309, 310,
      311, 312, 313, 322, 324, 325, 333, 334, 335, 348, 350, 351, 353,
      354, 355, 372, 374, 382, 384, 385, 386, 388, 389, 390,
    ]),
  },
  {
    id: "CONSTRAINT_CROSS_PROJECT_REFUSAL",
    category: "project-boundary",
    title: "a record addressed through another owned Project is not found and not changed",
    declarationLine: 393,
    assertionLines: new Set([
      114, 397, 398, 403, 404, 412, 413, 422, 423, 426, 427, 435, 443, 444, 446,
    ]),
  },
  {
    id: "CONSTRAINT_FIELD_REFUSAL",
    category: "request-validation",
    title: "an undeclared or Principal-naming body field is refused before a write",
    declarationLine: 449,
    assertionLines: new Set([114, 457, 458, 467, 470, 474, 476]),
  },
] as const;

/** Emits one fixed annotation at most; every unrecognised location fails closed. */
export default class ConstraintCiReporter implements Reporter {
  private emitted = false;

  onTestEnd(test: TestCase, result: TestResult): void {
    if (this.emitted || test.expectedStatus !== "passed" || result.status !== "failed") return;
    if (test.parent?.project()?.name !== "desktop") return;
    if (test.location?.file !== ABSOLUTE_SPEC) return;

    const admitted = CASES.find(
      (entry) => entry.title === test.title && entry.declarationLine === test.location.line,
    );
    if (!admitted) return;

    const line = result.errors?.find(
      (error) =>
        error.location?.file === ABSOLUTE_SPEC &&
        admitted.assertionLines.has(error.location.line),
    )?.location?.line;
    if (line === undefined) return;

    this.emitted = true;
    process.stdout.write(
      `::error file=${SPEC},line=${line},title=${admitted.id}::category=${admitted.category}\n`,
    );
  }
}
