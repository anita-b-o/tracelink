import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

test("Vercel Preview supports the persisted investigation journey", async ({
  page,
  request,
}) => {
  const uniqueId = `${Date.now()}-${randomUUID().slice(0, 8)}`;
  const email = `preview-smoke-${uniqueId}@example.com`;
  const password = `Tl!${randomUUID()}Aa1`;
  const title = `Preview smoke ${uniqueId}`;

  const readiness = await request.get("/api/health/ready");
  expect(readiness.status()).toBe(200);

  await page.goto("/login");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

  await page.getByRole("link", { name: "Create an account" }).click();
  await page.getByLabel("Display name").fill("Preview Smoke");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Register" }).click();
  await expect(
    page.getByRole("heading", { name: "Investigations", exact: true }),
  ).toBeVisible();

  await page.getByRole("main").getByRole("link", { name: "New investigation" }).click();
  await page.getByLabel(/Title/).fill(title);
  await page
    .getByLabel(/Original query/)
    .fill("Verify the deployed Preview investigation workflow and persisted task state.");
  await page.getByRole("checkbox", { name: /Start automatically/ }).uncheck();
  await page.getByRole("button", { name: /Create investigation/ }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("DRAFT", { exact: true })).toBeVisible();
  const workspaceUrl = page.url();

  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByText("DRAFT", { exact: true })).toBeHidden({ timeout: 30_000 });
  await page
    .getByLabel("Investigation workspace")
    .getByRole("button", { name: "Tasks", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "Research tasks", exact: true })).toBeVisible();
  await expect(page.locator("tbody tr").first()).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Investigations", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("main").getByText(title, { exact: true })).toBeVisible();

  await page.goto(workspaceUrl);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await page.getByLabel("Investigation workspace").getByRole("button", { name: "Graph" }).click();
  await expect(page.getByTestId("graph-canvas")).toBeVisible();
});
