import { test, expect } from "@playwright/test";

import { signInAsTestUser } from "./helpers";

test("drilling into a ticket shows its status and links", async ({ page }) => {
  await signInAsTestUser(page);
  await page.goto("/tickets");

  const firstCard = page.getByRole("link", { name: /^View /i }).first();
  if (!(await firstCard.isVisible().catch(() => false))) {
    test.skip(true, "no ticket data in Firestore for this environment");
  }

  await firstCard.click();
  await expect(page).toHaveURL(/\/tickets\/.+/);
  await expect(page.getByRole("link", { name: "GitHub issue" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Jira ticket" })).toBeVisible();
});
