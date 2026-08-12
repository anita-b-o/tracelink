import { mkdir } from "node:fs/promises";
import { test as setup, expect } from "@playwright/test";

setup("authenticate development owner", async ({ page }) => {
  await mkdir("test-results/.auth", { recursive: true });
  await page.goto("/login");
  await page.getByLabel("Email").fill("e2e@example.com");
  await page.getByLabel("Password").fill("e2e-password-secure");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Investigations" })).toBeVisible();
  await page.context().storageState({ path: "test-results/.auth/user.json" });
});
