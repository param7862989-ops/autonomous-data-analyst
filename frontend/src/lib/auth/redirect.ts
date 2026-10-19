/**
 * Validate a post-login redirect target. Only same-origin, absolute paths are allowed, so a
 * crafted `?next=` link cannot send a user to another site (open redirect).
 */
export function safeNextPath(raw: string | null | undefined, fallback = "/"): string {
  if (!raw) return fallback;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\")) return fallback;
  // Reject control characters, which some browsers strip before resolving the URL.
  if (/[\u0000-\u001f\u007f]/.test(raw)) return fallback;
  if (raw.startsWith("/login") || raw.startsWith("/register")) return fallback;
  return raw;
}

export function loginPathFor(pathname: string): string {
  const next = safeNextPath(pathname, "");
  return next && next !== "/" ? `/login?next=${encodeURIComponent(next)}` : "/login";
}
