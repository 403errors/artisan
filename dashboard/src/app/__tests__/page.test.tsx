import { describe, expect, it, vi, beforeEach } from "vitest";

const redirectMock = vi.fn();
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirectMock(url) }));

const authMock = vi.fn();
vi.mock("@/auth", () => ({ auth: () => authMock() }));

import Home from "../page";

describe("Home page redirect", () => {
  beforeEach(() => {
    redirectMock.mockReset();
    authMock.mockReset();
  });

  it("redirects signed-out users to /signin", async () => {
    authMock.mockResolvedValue(null);
    await Home();
    expect(redirectMock).toHaveBeenCalledWith("/signin");
  });

  it("redirects signed-in users to /tickets", async () => {
    authMock.mockResolvedValue({ user: { name: "test" } });
    await Home();
    expect(redirectMock).toHaveBeenCalledWith("/tickets");
  });
});
