import type { NextConfig } from "next";

// Where the Next.js server forwards /api/* requests. The browser only ever talks to the Next.js
// origin, so the backend's HttpOnly session cookie is first-party in every environment.
// Note: with `output: "standalone"` the config is serialized at build time, so this value must be
// provided when running `next build` (the Dockerfile passes it as a build argument).
const backendUrl = (process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const isDev = process.env.NODE_ENV !== "production";

const contentSecurityPolicy = [
  "default-src 'self'",
  // Next.js injects inline bootstrap scripts; dev mode additionally needs eval for fast refresh.
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self'${isDev ? " ws: wss:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  experimental: {
    // Next.js buffers request bodies passing through the /api rewrite and silently truncates
    // them at 10 MB by default. Keep this just above the backend's MAX_UPLOAD_BYTES (25 MB) plus
    // multipart overhead; the backend enforces the real limit.
    proxyClientMaxBodySize: "26mb",
    // Profiling a maximum-size upload can take longer than the 30 s default on a small host.
    proxyTimeout: 120_000,
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
  async headers() {
    return [
      {
        // API responses carry the backend's own (stricter) headers.
        source: "/((?!api/).*)",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
