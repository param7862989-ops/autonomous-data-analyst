import { type NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "ada_session";

/**
 * Optimistic redirect for visitors with no session cookie at all, so they see the sign-in page
 * instead of a loading state. It never grants access: the backend validates the session on every
 * API request, and an expired cookie is handled client-side.
 */
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const { pathname, search } = request.nextUrl;
  const login = new URL("/login", request.url);
  if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(login);
}

export const config = {
  // Not API routes (uploads must not be buffered by the proxy layer), static assets, or the
  // sign-in pages themselves.
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico|login|register).*)"],
};
