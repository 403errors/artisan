import { describe, expect, it, vi } from "vitest";

const { authMock, getTicketMock, publishManualActionMock } = vi.hoisted(() => ({
  authMock: vi.fn(),
  getTicketMock: vi.fn(),
  publishManualActionMock: vi.fn(),
}));

vi.mock("@/auth", () => ({ auth: authMock }));
vi.mock("@/lib/tickets", () => ({ getTicket: getTicketMock }));
vi.mock("@/lib/pubsub", () => ({ publishManualAction: publishManualActionMock }));

import { postManualAction } from "@/lib/ticket-actions-server";

const TICKET = {
  id: "t1",
  githubRepo: "403errors/artisan-demo",
  githubIssueNumber: 10,
};

describe("postManualAction", () => {
  it("returns 401 when there is no session", async () => {
    authMock.mockResolvedValue(null);

    const res = await postManualAction("t1", "retry_gate2");

    expect(res.status).toBe(401);
    expect(publishManualActionMock).not.toHaveBeenCalled();
  });

  it("returns 404 when the ticket doesn't exist", async () => {
    authMock.mockResolvedValue({ login: "octocat" });
    getTicketMock.mockResolvedValue(null);

    const res = await postManualAction("t1", "retry_gate2");

    expect(res.status).toBe(404);
    expect(publishManualActionMock).not.toHaveBeenCalled();
  });

  it("publishes a manual_action envelope and returns 202 with an actionId", async () => {
    authMock.mockResolvedValue({ login: "octocat" });
    getTicketMock.mockResolvedValue(TICKET);
    publishManualActionMock.mockResolvedValue("message-id-1");

    const res = await postManualAction("t1", "retry_gate2");
    const payload = await res.json();

    expect(res.status).toBe(202);
    expect(payload.actionId).toBeTruthy();
    expect(publishManualActionMock).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "manual_action",
        action: "retry_gate2",
        repo: "403errors/artisan-demo",
        issue_number: 10,
        actor: "octocat",
      }),
    );
  });

  it("includes reason only when given", async () => {
    authMock.mockResolvedValue({ login: "octocat" });
    getTicketMock.mockResolvedValue(TICKET);
    publishManualActionMock.mockResolvedValue("message-id-1");

    await postManualAction("t1", "escalate", "taking too long");

    expect(publishManualActionMock).toHaveBeenCalledWith(
      expect.objectContaining({ reason: "taking too long" }),
    );

    publishManualActionMock.mockClear();
    await postManualAction("t1", "mark_done");
    expect(publishManualActionMock).toHaveBeenCalledWith(
      expect.not.objectContaining({ reason: expect.anything() }),
    );
  });

  it("falls back to the session user's name when login is absent", async () => {
    authMock.mockResolvedValue({ user: { name: "Sam" } });
    getTicketMock.mockResolvedValue(TICKET);
    publishManualActionMock.mockResolvedValue("message-id-1");

    await postManualAction("t1", "mark_done");

    expect(publishManualActionMock).toHaveBeenCalledWith(expect.objectContaining({ actor: "Sam" }));
  });
});
