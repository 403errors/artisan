import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TraceLinks } from "@/components/trace-links";

describe("TraceLinks", () => {
  it("renders nothing when there are no trace ids", () => {
    const { container } = render(<TraceLinks traceIds={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders each entry's label and trace id, linked to Cloud Trace", () => {
    render(
      <TraceLinks
        traceIds={[
          { traceId: "a".repeat(32), label: "Gate 1: intake sufficient" },
          { traceId: "b".repeat(32), label: "Gate 2: verification passed" },
        ]}
      />,
    );

    expect(screen.getByText("Gate 1: intake sufficient")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(32))).toBeInTheDocument();
    expect(screen.getByText("Gate 2: verification passed")).toBeInTheDocument();
    expect(screen.getByText("b".repeat(32))).toBeInTheDocument();

    const link = screen.getByText("Gate 1: intake sufficient").closest("a");
    expect(link).toHaveAttribute("href", expect.stringContaining("a".repeat(32)));
  });

  it("does not render the old stale 'known gap' note", () => {
    render(<TraceLinks traceIds={[{ traceId: "a".repeat(32), label: "Gate 1: intake sufficient" }]} />);
    expect(screen.queryByText(/known gap/i)).not.toBeInTheDocument();
  });
});
