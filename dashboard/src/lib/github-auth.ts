// Authorization for dashboard sign-in (SYSTEM_DESIGN.md §8): access must match the signed-in
// user's actual GitHub permission on the target repo, not just "any GitHub account". Requires the
// `repo` OAuth scope (Auth.js's GitHub provider default scope is `read:user user:email` only).
export async function hasRepoAccess(userAccessToken: string, repoFullName: string): Promise<boolean> {
  const [owner, repo] = repoFullName.split("/");

  const userRes = await fetch("https://api.github.com/user", {
    headers: { Authorization: `Bearer ${userAccessToken}` },
  });
  if (!userRes.ok) return false;
  const { login } = await userRes.json();

  const permRes = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/collaborators/${login}/permission`,
    { headers: { Authorization: `Bearer ${userAccessToken}` } },
  );
  if (!permRes.ok) return false; // 404 = not a collaborator at all
  const { permission } = await permRes.json(); // "admin" | "write" | "read" | "none"
  return permission !== "none";
}
