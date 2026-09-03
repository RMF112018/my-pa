/**
 * Single validator for safe relative `next` return paths.
 *
 * Callers decide the default when this returns `null`. No open redirects.
 */

function isSafeRelativePath(value: string): boolean {
  if (!value.startsWith("/") || value.startsWith("//")) return false;
  if (/[\s\\]/.test(value)) return false;
  if (/%2f|%5c/i.test(value)) return false;
  const lower = value.toLowerCase();
  if (
    lower.includes("http:") ||
    lower.includes("https:") ||
    lower.includes("javascript:") ||
    lower.includes("data:") ||
    lower.includes("vbscript:")
  ) {
    return false;
  }
  return true;
}

/** Allow only a relative path starting with exactly one `/`. Otherwise `null`. */
export function safeReturnPath(raw: string | null | undefined): string | null {
  if (typeof raw !== "string" || raw.length === 0) return null;
  if (!isSafeRelativePath(raw)) return null;
  try {
    const decoded = decodeURIComponent(raw);
    if (decoded !== raw && !isSafeRelativePath(decoded)) return null;
  } catch {
    return null;
  }
  return raw;
}
