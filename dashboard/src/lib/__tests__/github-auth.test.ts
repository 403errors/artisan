import { afterEach, describe, expect, it, vi } from "vitest";

import { hasRepoAccess } from "@/lib/github-auth";

function stubFetchSequence(...responses: Array<{ ok: boolean; status?: number; body: unknown }>) {
  const fetchMock = vi.fn();
  for (const r of responses) {
    fetchMock.mockResolvedValueOnce({
      ok: r.ok,
      status: r.status ?? (r.ok ? 200 : 404),
      json: async () => r.body,
    } as Response);
  }
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("hasRepoAccess", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns false when the user lookup fails", async () => {
    stubFetchSequence({ ok: false, body: {} });
    expect(await hasRepoAccess("token", "acme/demo")).toBe(false);
  });

  it.each(["admin", "write", "read"])("grants access for collaborator permission %s", async (perm) => {
    stubFetchSequence(
      { ok: true, body: { login: "octocat" } },
      { ok: true, body: { permission: perm } },
    );
    expect(await hasRepoAccess("token", "acme/demo")).toBe(true);
  });

  it("denies access when the collaborator permission is none", async () => {
    stubFetchSequence(
      { ok: true, body: { login: "octocat" } },
      { ok: true, body: { permission: "none" } },
    );
    expect(await hasRepoAccess("token", "acme/demo")).toBe(false);
  });

  it("denies access when the user is not a collaborator (404)", async () => {
    stubFetchSequence(
      { ok: true, body: { login: "octocat" } },
      { ok: false, status: 404, body: {} },
    );
    expect(await hasRepoAccess("token", "acme/demo")).toBe(false);
  });

  it("queries the permission endpoint for the signed-in user and repo", async () => {
    const fetchMock = stubFetchSequence(
      { ok: true, body: { login: "octocat" } },
      { ok: true, body: { permission: "write" } },
    );
    await hasRepoAccess("token", "acme/demo");
    expect(fetchMock.mock.calls[1][0]).toBe(
      "https://api.github.com/repos/acme/demo/collaborators/octocat/permission",
    );
  });
});
