import { redirect } from "next/navigation";

import { auth } from "@/auth";

// Per-page auth gate for Server Components (pages, not API routes — those do their own explicit
// `await auth()` 401 check instead, see app/api/tickets/*). Deliberately not middleware-based:
// Auth.js v5's `authorized` callback affects every `auth()` call app-wide, not just requests a
// middleware matcher scopes it to — verified empirically it broke the API routes' own 401s too.
export async function requireSession() {
  const session = await auth();
  if (!session) redirect("/signin");
  return session;
}
