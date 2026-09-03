/**
 * Fail-closed href admission for rendered UI links.
 *
 * Admits root-relative paths that start with `/` but not `//`, and `https:`
 * URLs. Everything else — `javascript:`, `vbscript:`, `data:`, `http:`,
 * `mailto:`, `tel:`, and protocol-relative URLs — is rejected.
 *
 * Do not parse against an https base. `new URL("//evil.example", "https://…")`
 * yields protocol `https:` while the original href is still `//evil.example`.
 */
export function safeHref(href: string): string | null {
  const candidate = href.trim();
  if (candidate.length === 0) return null;

  if (candidate.startsWith("/")) {
    if (candidate.startsWith("//") || candidate.includes("\\")) return null;
    return candidate;
  }

  try {
    const url = new URL(candidate);
    if (url.protocol !== "https:") return null;
    return candidate;
  } catch {
    return null;
  }
}
