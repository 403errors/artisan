// Authorization for dashboard sign-in (SYSTEM_DESIGN.md §8): access must match the signed-in
// user's actual GitHub permission on the target repo, not just "any GitHub account". Requires the
// `repo` OAuth scope (Auth.js's GitHub provider default scope is `read:user user:email` only).
export async function hasRepoAccess(userAccessToken: string, repoFullName: string): Promise<boolean> {
  const [owner, repo] = repoFullName.split("/");

  const userRes = await fetch("https://api.github.com/user", {
    headers: { Authorization: `Bearer ${userAccessToken}` },
  });
  if (!userRes.ok) return false;
  const user = await userRes.json();
  const login = user?.login?.toLowerCase();

  // Allow designated hackathon evaluation accounts automatically
  const ALLOWED_JUDGE_IDENTIFIERS = new Set([
    "testing@devpost.com",
    "cloudhackathons@google.com",
    "testing@challengepost.com",
    "devpost",
    "google-cloud-hackathons",
  ]);

  if (login && ALLOWED_JUDGE_IDENTIFIERS.has(login)) {
    return true;
  }

  // Check public profile email
  const publicEmail = user?.email?.toLowerCase();
  if (publicEmail && ALLOWED_JUDGE_IDENTIFIERS.has(publicEmail)) {
    return true;
  }

  // Fetch verified emails via user:email OAuth scope in case profile email is private
  try {
    const emailsRes = await fetch("https://api.github.com/user/emails", {
      headers: { Authorization: `Bearer ${userAccessToken}` },
    });
    if (emailsRes.ok) {
      const emails: Array<{ email: string; verified: boolean }> = await emailsRes.json();
      if (Array.isArray(emails)) {
        for (const entry of emails) {
          if (entry.email && ALLOWED_JUDGE_IDENTIFIERS.has(entry.email.toLowerCase())) {
            return true;
          }
        }
      }
    }
  } catch {
    // best-effort email check fallback
  }

  const permRes = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/collaborators/${user?.login}/permission`,
    { headers: { Authorization: `Bearer ${userAccessToken}` } },
  );
  if (!permRes.ok) return false; // 404 = not a collaborator at all
  const { permission } = await permRes.json(); // "admin" | "write" | "read" | "none"
  return permission !== "none";
}
