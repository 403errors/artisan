import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Page from "../page";

describe("Home page scaffold", () => {
  it("renders without crashing", () => {
    render(<Page />);
    expect(document.body).toBeTruthy();
  });
});
