import { test, expect } from "@playwright/test";

import { signInAsTestUser } from "./helpers";

// Mirrors the Python side's `_require_credentials()` skip-if-no-ADC convention
// (agents/tests/test_firestore_client.py) — this hits the real Firestore database, so it's
// skipped rather than failing when no ticket data is reachable in the current environment.
test("renders at least one ticket card when Firestore has data", async ({ page }) => {
  await signInAsTestUser(page);
  await page.goto("/tickets");
  await expect(page.getByRole("heading", { name: "Tickets" })).toBeVisible();

  const emptyState = page.getByText("No tickets yet.");
  if (await emptyState.isVisible().catch(() => false)) {
    test.skip(true, "no ticket data in Firestore for this environment");
  }

  await expect(page.getByRole("link", { name: /^View /i }).first()).toBeVisible();
});
