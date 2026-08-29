import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CodeBlock } from "@/components/code-block";

const SHORT = "line 1\nline 2\nline 3";
const LONG = Array.from({ length: 20 }, (_, i) => `line ${i + 1}`).join("\n");

describe("CodeBlock", () => {
  it("renders short content without a collapse trigger", () => {
    render(<CodeBlock>{SHORT}</CodeBlock>);
    expect(screen.getByText("line 1")).toBeInTheDocument();
    expect(screen.getByText("line 3")).toBeInTheDocument();
    expect(screen.queryByText(/Show \d+ more lines/)).not.toBeInTheDocument();
  });

  it("collapses long content behind a 'Show N more lines' trigger and expands on click", () => {
    render(<CodeBlock>{LONG}</CodeBlock>);
    expect(screen.getByText("line 1")).toBeInTheDocument();
    expect(screen.queryByText("line 20")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Show \d+ more lines/ }));

    expect(screen.getByText("line 20")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collapse" })).toBeInTheDocument();
  });

  it("copies its content to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<CodeBlock label="diff">{SHORT}</CodeBlock>);
    fireEvent.click(screen.getByRole("button", { name: "Copy to clipboard" }));

    expect(writeText).toHaveBeenCalledWith(SHORT);
  });
});
