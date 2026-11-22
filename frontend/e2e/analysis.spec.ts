import { readFile } from "node:fs/promises";
import path from "node:path";

import { type Download, type Page, expect, test } from "@playwright/test";

const SAMPLE = path.resolve(__dirname, "../../data/samples/sales.csv");
const PASSWORD = "e2e-password-123";

function uniqueEmail(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

async function readDownload(download: Download): Promise<string> {
  const file = await download.path();
  return readFile(file, "utf-8");
}

async function register(page: Page, email: string) {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText(email)).toBeVisible();
}

test("unauthenticated visitors are sent to sign in", async ({ page }) => {
  await page.goto("/datasets");
  await expect(page).toHaveURL(/\/login\?next=%2Fdatasets/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("pages send security headers", async ({ page }) => {
  const response = await page.goto("/login");
  const headers = response?.headers() ?? {};
  const csp = headers["content-security-policy"] ?? "";
  for (const directive of ["default-src 'self'", "object-src 'none'", "frame-ancestors 'none'"]) {
    expect(csp).toContain(directive);
  }
  // The production build must not allow eval (only the dev server needs it).
  expect(csp).not.toContain("unsafe-eval");
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(headers["x-powered-by"]).toBeUndefined();
});

test("upload, profile, analyse, follow up, revisit, and isolation between users", async ({
  page,
  browser,
}) => {
  const owner = uniqueEmail("owner");
  await register(page, owner);

  // Upload the sample dataset and see its real profile.
  await page.getByRole("link", { name: "Datasets" }).click();
  await expect(page.getByText("No datasets yet")).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles(SAMPLE);
  await page.getByLabel("Name (optional)").fill("E2E sales");
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page).toHaveURL(/\/datasets\/[0-9a-f-]{36}$/);
  const datasetUrl = page.url();
  await expect(page.getByRole("heading", { name: "E2E sales" })).toBeVisible();
  const rowsFact = page.locator("dl > div").filter({ has: page.getByText("Rows", { exact: true }) });
  await expect(rowsFact.locator("dd")).toHaveText("7,620");
  await expect(page.getByRole("rowheader", { name: /Order Date/ })).toBeVisible();
  await page.getByRole("tab", { name: "Rows" }).click();
  await expect(page.getByText("Rows 1 to 50 of 7,620")).toBeVisible();

  // Ask a question: live activity, then a grounded answer with a chart and evidence.
  await page.getByRole("button", { name: "Ask a question" }).click();
  await expect(page).toHaveURL(/\/conversations\/[0-9a-f-]{36}$/);
  const conversationUrl = page.url();
  const composer = page.getByLabel("Ask a question about this dataset");
  await composer.fill("Why did revenue decrease in Q3?");
  await composer.press("Enter");

  const firstRun = page.locator("article").first();
  await expect(firstRun.getByText("What the data shows")).toBeVisible({ timeout: 60_000 });
  await expect(firstRun.getByText(/West contributed most of the decline/)).toBeVisible();
  await expect(firstRun.locator("mark").first()).toBeVisible(); // verified figures highlighted
  await expect(firstRun.getByText("-34.5%")).toBeVisible();
  await expect(firstRun.locator("figure .main-svg").first()).toBeVisible(); // Plotly rendered
  await firstRun.getByRole("button", { name: "Show the computed result r1" }).click();
  await expect(firstRun.getByRole("cell", { name: "West", exact: true })).toBeVisible();

  // Exports are real browser downloads of the loaded data.
  const csvDownload = page.waitForEvent("download");
  await firstRun.getByRole("button", { name: /^Download r1 as CSV/ }).click();
  const csv = await csvDownload;
  expect(csv.suggestedFilename()).toMatch(/^r1-.*\.csv$/);
  expect(await readDownload(csv)).toContain("West");
  const reportDownload = page.waitForEvent("download");
  await firstRun
    .getByRole("button", { name: "Download this analysis as a Markdown report" })
    .click();
  const report = await reportDownload;
  expect(report.suggestedFilename()).toBe("why-did-revenue-decrease-in-q3.md");
  expect(await readDownload(report)).toContain("## What the data shows");
  await firstRun.getByText(/How this was answered/).click();
  await expect(firstRun.getByText("Inspecting dataset")).toBeVisible();
  await expect(firstRun.getByText(/^Comparing periods: Sum of Revenue/)).toBeVisible();

  // Follow-up question in the same conversation.
  await firstRun.getByRole("button", { name: /Which products drove the decline/ }).click();
  await expect(composer).toHaveValue(/Which products drove the decline/);
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.locator("article")).toHaveCount(2);
  await expect(page.locator("article").nth(1).getByText("What the data shows")).toBeVisible({
    timeout: 60_000,
  });

  // The conversation and its analyses persist and appear in history.
  await page.goto("/history");
  await expect(page.getByRole("link", { name: "Why did revenue decrease in Q3?" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Which products drove the decline/ })).toBeVisible();
  await page.reload();
  await page.getByRole("link", { name: "Why did revenue decrease in Q3?" }).click();
  await expect(page).toHaveURL(new RegExp(new URL(conversationUrl).pathname));
  await expect(page.locator("article")).toHaveCount(2);

  // A history link lands on its own question, not the top of the conversation.
  await page.goto("/history");
  await page.getByRole("link", { name: /Which products drove the decline/ }).click();
  const secondQuestion = page.locator("article").nth(1).getByRole("heading").first();
  await expect(secondQuestion).toBeInViewport();

  // Rename from the conversation; the list shows the new title.
  await page.getByRole("button", { name: "Rename" }).click();
  await page.getByLabel("Conversation title").fill("Q3 revenue review");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { name: "Q3 revenue review", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: "Conversations" }).click();
  await page.getByRole("link", { name: "Q3 revenue review" }).click();
  await expect(page.locator("article")).toHaveCount(2);

  // Sign out, then a different user cannot see or open any of it.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);

  const otherContext = await browser.newContext();
  const intruder = await otherContext.newPage();
  await register(intruder, uniqueEmail("intruder"));
  await intruder.goto("/datasets");
  await expect(intruder.getByText("No datasets yet")).toBeVisible();
  await intruder.goto(datasetUrl);
  await expect(intruder.getByText("Dataset not found")).toBeVisible();
  await intruder.goto(conversationUrl);
  await expect(intruder.getByText("Conversation not found")).toBeVisible();
  await intruder.goto("/history");
  await expect(intruder.getByText("No analyses yet")).toBeVisible();
  await intruder.goto("/conversations");
  await expect(intruder.getByText("No conversations yet")).toBeVisible();
  await otherContext.close();
});

test("deleting a conversation, then its dataset, removes them from every list", async ({ page }) => {
  await register(page, uniqueEmail("cleanup"));
  await page.getByRole("link", { name: "Datasets" }).first().click();
  await page.locator('input[type="file"]').setInputFiles(SAMPLE);
  await page.getByLabel("Name (optional)").fill("Cleanup sales");
  await page.getByRole("button", { name: "Upload" }).click();
  await page.getByRole("button", { name: "Ask a question" }).click();
  await expect(page).toHaveURL(/\/conversations\/[0-9a-f-]{36}$/);

  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Delete conversation" }).click();
  await expect(page).toHaveURL(/\/datasets\/[0-9a-f-]{36}$/);
  await expect(page.getByText("No questions asked yet")).toBeVisible();

  await page.getByRole("button", { name: "Ask a question" }).click();
  await expect(page).toHaveURL(/\/conversations\/[0-9a-f-]{36}$/);
  await page.getByRole("link", { name: "Conversations", exact: true }).click();
  // By role: Next's route announcer repeats page titles as plain text.
  await expect(page.getByRole("link", { name: "Analysis of Cleanup sales" })).toBeVisible();

  await page.getByRole("link", { name: "Datasets", exact: true }).click();
  await page.getByRole("link", { name: "Cleanup sales", exact: true }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Delete dataset" }).click();
  await expect(page.getByText("No datasets yet")).toBeVisible();
  await page.getByRole("link", { name: "Conversations", exact: true }).click();
  await expect(page.getByText("No conversations yet")).toBeVisible();
});
