import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

// SignOutButton pulls in the server-only @/auth module; mock it so the nav can
// render in jsdom without bootstrapping Auth.js.
vi.mock("@/components/sign-out-button", () => ({
  SignOutButton: () => <button type="submit">Sign out</button>,
}));

import { DashboardNav } from "@/components/dashboard-nav";

describe("DashboardNav", () => {
  it("links to the tickets page", () => {
    render(<DashboardNav />);
    expect(screen.getByRole("link", { name: "Tickets" })).toHaveAttribute("href", "/tickets");
  });

  it("does not show a separate 'Awaiting human' link (folded into ticket filters)", () => {
    render(<DashboardNav />);
    expect(screen.queryByRole("link", { name: "Awaiting human" })).not.toBeInTheDocument();
  });

  it("shows the sign-out button", () => {
    render(<DashboardNav />);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});
