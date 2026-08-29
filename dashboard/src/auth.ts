import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import GitHub from "next-auth/providers/github";

import { TARGET_REPO } from "@/lib/config";
import { hasRepoAccess } from "@/lib/github-auth";

const E2E_TEST_MODE = process.env.AUTH_E2E_TEST_MODE === "1";

export const { handlers, signIn, signOut, auth } = NextAuth({
  // Needed both for local dev on a non-default port and for Cloud Run's dynamic *.run.app
  // hostname (Sprint 7) — Auth.js otherwise rejects any host it wasn't told to trust up front.
  trustHost: true,
  providers: [
    GitHub({
      clientId: process.env.GITHUB_ID,
      clientSecret: process.env.GITHUB_SECRET,
      // Default scope is `read:user user:email` only — `repo` is required for the collaborator-
      // permission check below (SYSTEM_DESIGN.md §8).
      authorization: { params: { scope: "read:user user:email repo" } },
    }),
    // Deliberately gated behind a dedicated flag (not NODE_ENV) so it can never activate in a
    // real deployment by accident. Lets Playwright get an authenticated session without driving a
    // real GitHub OAuth consent screen. No password/secret check by design — safety comes
    // entirely from AUTH_E2E_TEST_MODE never being set outside test/CI runs.
    ...(E2E_TEST_MODE
      ? [
          Credentials({
            id: "e2e-test-login",
            name: "E2E Test Login",
            credentials: { login: { label: "Login", type: "text" } },
            async authorize(creds) {
              return { id: "e2e-test-user", name: String(creds?.login ?? "e2e-test-user") };
            },
          }),
        ]
      : []),
  ],
  callbacks: {
    async signIn({ account }) {
      if (account?.provider === "e2e-test-login") return E2E_TEST_MODE;
      if (!account?.access_token) return false;
      return hasRepoAccess(account.access_token, TARGET_REPO);
    },
    async jwt({ token, account, profile }) {
      if (account?.access_token) token.accessToken = account.access_token;
      // GitHub's profile carries the real username as `login` — needed as the `actor` on manual
      // dashboard actions (retry/escalate/mark-done) so the audit trail records who did what,
      // not just a display name.
      if (typeof profile?.login === "string") token.login = profile.login;
      return token;
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken as string | undefined;
      session.login = token.login as string | undefined;
      return session;
    },
  },
  pages: {
    signIn: "/signin",
    error: "/access-denied",
  },
});
