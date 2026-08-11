import { expect, test } from "@playwright/test";

test("graph renders, opens an edge, and applies filters",async({page})=>{
  await page.goto("/");
  await page.getByRole("link",{name:"Review and graph fixture"}).click();
  await page.getByRole("button",{name:"Graph"}).click();
  await expect(page).toHaveURL(/tab=graph/);
  const graph=page.getByTestId("graph-canvas");
  await expect(graph.locator(".react-flow__node")).toHaveCount(3);
  await expect(graph.locator(".react-flow__edge")).toHaveCount(1);
  await graph.locator(".react-flow__edge-interaction").click({force:true});
  await expect(page.getByRole("dialog",{name:"Graph relationship"})).toBeVisible();
  await expect(page.getByRole("dialog").getByText("DIRECTOR_OF")).toBeVisible();
  await page.getByRole("button",{name:"Close detail"}).click();
  await page.getByLabel("Graph entity type").selectOption("PERSON");
  await expect(graph.locator(".react-flow__node")).toHaveCount(1);
});
