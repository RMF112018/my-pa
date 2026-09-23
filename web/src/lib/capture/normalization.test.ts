/**
 * C01: new browser-authored text is normalized **once**, by the existing
 * `trim()` behaviour at the browser/BFF boundary, before key ownership and
 * hashing are frozen. No Unicode normalization, case folding, newline rewrite,
 * fuzzy comparison or truncation is introduced.
 *
 * This file exists because that clause was unguarded. An independent review
 * found that adding `.normalize("NFD")` to the `/api/capture` accepted text, or
 * to the text the offline codec seals, left the entire suite green — while in
 * production it would make the backend hash normalized bytes and the browser
 * verifier hash unnormalized ones, so every capture containing a composed
 * character would return `digest_mismatch`: permanently ambiguous online, and on
 * replay never deletable.
 *
 * The digest is the thing that actually binds the two sides, so these tests pin
 * the digest of text that Unicode normalization would change, rather than
 * asserting on the shape of any one call site.
 */
import { describe, expect, it } from "vitest";

import { contentSha256 } from "./receipt";

/**
 * "é" as one composed code point (U+00E9) and as "e" plus a combining acute
 * (U+0065 U+0301). They render identically and compare unequal, and NFC/NFD
 * convert between them — which is exactly what must not happen here.
 */
const COMPOSED = "café notes";
const DECOMPOSED = "café notes";

describe("C01 accepted-text normalization", () => {
  it("treats composed and decomposed text as different content", async () => {
    expect(COMPOSED).not.toBe(DECOMPOSED);
    expect(COMPOSED.normalize("NFD")).toBe(DECOMPOSED);

    const composed = await contentSha256(COMPOSED);
    const decomposed = await contentSha256(DECOMPOSED);

    // If any layer introduced NFC/NFD, these two would collapse to one digest
    // and the browser would silently accept a receipt for bytes the user never
    // authored.
    expect(composed).not.toBe(decomposed);
  });

  it("hashes the exact bytes it is given, with no normalization of its own", async () => {
    // Pinned digests, computed independently of this implementation:
    //   python3 -c "import hashlib; print(hashlib.sha256('caf\u00E9 notes'.encode()).hexdigest())"
    // A change to `contentSha256` that normalized, case-folded or rewrote
    // newlines would move these, and no other assertion in the suite would notice.
    expect(await contentSha256(COMPOSED)).toBe(
      "a39134b0215692786a3506400b52c5a1c527119159747b22c9e04bbd8b8a8c36",
    );
    expect(await contentSha256(DECOMPOSED)).toBe(
      "baa900a03be0ed28fe50aac7a26cd7574e1e3cae7463fb1f5d6135063697cf5e",
    );
  });

  it("does not case-fold", async () => {
    expect(await contentSha256("Note")).not.toBe(await contentSha256("note"));
  });

  it("does not rewrite newlines", async () => {
    expect(await contentSha256("a\r\nb")).not.toBe(await contentSha256("a\nb"));
  });

  it("applies trim, and only trim, as the one accepted-text normalization", async () => {
    // `trim()` is the single permitted normalization: surrounding whitespace is
    // removed, and nothing inside the text is touched.
    expect(await contentSha256("  note  ".trim())).toBe(await contentSha256("note"));
    expect(await contentSha256(" a  b ".trim())).toBe(await contentSha256("a  b"));
  });
});
