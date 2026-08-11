import { expect, test } from "@playwright/test";

test("accept entity candidate and reject relationship candidate",async({page})=>{
  await page.goto("/");
  await page.getByRole("link",{name:"Review and graph fixture"}).click();
  await page.getByRole("button",{name:"Review"}).click();
  await expect(page.getByRole("button",{name:"Accept match"})).toBeVisible();
  await page.getByRole("button",{name:"Accept match"}).click();
  await expect(page.getByText("No entity candidates")).toBeVisible();
  await expect(page.getByRole("button",{name:"Reject"})).toBeVisible();
  await page.getByRole("button",{name:"Reject"}).click();
  await expect(page.getByText("No relationship candidates")).toBeVisible();
});
