import type { Page } from "@playwright/test";

export async function signInAsTestUser(page: Page) {
  const csrfRes = await page.request.get("/api/auth/csrf");
  const { csrfToken } = await csrfRes.json();
  await page.request.post("/api/auth/callback/e2e-test-login", {
    form: { csrfToken, login: "e2e-test-user", callbackUrl: "/tickets" },
  });
}
