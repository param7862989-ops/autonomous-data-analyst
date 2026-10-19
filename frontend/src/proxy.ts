import { type NextRequest, NextResponse } from "next/server";

/**
 * Must match `experimental.proxyClientMaxBodySize` in next.config.ts. Next.js truncates bodies
 * beyond that size before the rewrite reaches the backend, which would surface as a bare 500,
 * so oversized uploads are answered here with the API's normal 413 error envelope.
 */
const MAX_PROXIED_BODY_BYTES = 26 * 1024 * 1024;

export function proxy(request: NextRequest) {
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (request.method === "POST" && declared > MAX_PROXIED_BODY_BYTES) {
    return NextResponse.json(
      {
        error: {
          code: "payload_too_large",
          message: "The file is larger than the 25 MB upload limit.",
          details: { limit_bytes: MAX_PROXIED_BODY_BYTES },
          request_id: null,
        },
      },
      { status: 413 },
    );
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/datasets"],
};
