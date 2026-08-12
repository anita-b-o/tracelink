import { expect, test } from "@playwright/test";

test("register, logout, login, protected redirect, and cross-user isolation", async ({ page }) => {
  const suffix = Date.now();
  const ownerEmail = `owner-${suffix}@example.com`;
  const otherEmail = `other-${suffix}@example.com`;
  const password = "e2e-secure-password";

  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByRole("link", { name: "Create an account" }).click();
  await page.getByLabel("Display name").fill("Owner");
  await page.getByLabel("Email").fill(ownerEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Register" }).click();
  await expect(
    page.getByRole("heading", { name: "Investigations", exact: true }),
  ).toBeVisible();

  await page.getByRole("main").getByRole("link", { name: "New investigation" }).click();
  await page.getByLabel(/Title/).fill(`Private ${suffix}`);
  await page.getByLabel(/Original query/).fill("Private cross-user investigation");
  await page.getByRole("checkbox", { name: /Start automatically/ }).uncheck();
  await page.getByRole("button", { name: /Create investigation/ }).click();
  await expect(page).toHaveURL(/\/investigations\/[0-9a-f-]+$/);
  const privateUrl = page.url();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(ownerEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.getByRole("button", { name: "Log out" }).click();
  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page).toHaveURL(/\/register$/);
  await page.getByLabel("Display name").fill("Other");
  await page.getByLabel("Email").fill(otherEmail);
  await page.getByLabel("Password").fill(password);
  const secondRegistration = page.waitForResponse(
    (response) =>
      response.url().includes("/api/auth/register") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Register" }).click();
  expect((await secondRegistration).status()).toBe(201);
  await expect(
    page.getByRole("heading", { name: "Investigations", exact: true }),
  ).toBeVisible();
  await page.goto(privateUrl);
  await expect(page.getByText(/Not found|resource not found/i)).toBeVisible();
});
