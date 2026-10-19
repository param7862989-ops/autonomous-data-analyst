// Copy static assets next to the standalone server so `npm start` serves the same build that
// the Docker image runs (Next.js does not copy them into .next/standalone itself).
import { cpSync, existsSync } from "node:fs";

const target = ".next/standalone";
if (!existsSync(target)) {
  console.error("No .next/standalone directory; run `next build` first.");
  process.exit(1);
}
cpSync(".next/static", `${target}/.next/static`, { recursive: true });
if (existsSync("public")) cpSync("public", `${target}/public`, { recursive: true });
console.log("Standalone server prepared.");
