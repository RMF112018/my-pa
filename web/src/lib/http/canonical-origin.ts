/** Server-only canonical HTTPS origin for the private NAS application. */
export function canonicalOrigin(): string {
  const configured = process.env.MYPA_CANONICAL_ORIGIN?.trim();
  if (!configured) {
    if (process.env.NODE_ENV !== "production") return "http://localhost:3000";
    throw new Error("MYPA_CANONICAL_ORIGIN must be configured");
  }
  let parsed: URL;
  try {
    parsed = new URL(configured);
  } catch {
    throw new Error("MYPA_CANONICAL_ORIGIN must be an absolute HTTPS origin");
  }
  if (
    (parsed.protocol !== "https:" &&
      (process.env.NODE_ENV === "production" || !["localhost", "127.0.0.1"].includes(parsed.hostname))) ||
    parsed.username ||
    parsed.password ||
    parsed.port ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash ||
    !parsed.hostname
  ) {
    throw new Error("MYPA_CANONICAL_ORIGIN must be an HTTPS hostname origin on port 443");
  }
  return parsed.origin;
}

export function canonicalUrl(path: string): URL {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("canonical URL path must be root-relative");
  }
  return new URL(path, canonicalOrigin());
}
