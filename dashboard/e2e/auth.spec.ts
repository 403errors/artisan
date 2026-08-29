import { test, expect } from "@playwright/test";

import { signInAsTestUser } from "./helpers";

test.describe("unauthenticated access", () => {
  test("GET /api/tickets returns 401 with no ticket data", async ({ page }) => {
    const res = await page.request.get("/api/tickets");
    expect(res.status()).toBe(401);
    const body = await res.body();
    expect(body.length).toBe(0);
  });

  test("navigating to /tickets redirects to /signin", async ({ page }) => {
    await page.goto("/tickets");
    await expect(page).toHaveURL(/\/signin/);
  });
});

test.describe("authenticated access (test provider)", () => {
  test("signed-in request to /tickets succeeds", async ({ page }) => {
    await signInAsTestUser(page);
    await page.goto("/tickets");
    await expect(page).toHaveURL(/\/tickets/);
    await expect(page.getByRole("heading", { name: "Tickets" })).toBeVisible();
  });
});
