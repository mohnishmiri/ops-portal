/**
 * Tests for AccessDenied component.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";
import AccessDenied from "./AccessDenied";

function setup(props: { resourceName?: string } = {}) {
  render(
    <MemoryRouter>
      <AccessDenied {...props} />
    </MemoryRouter>
  );
}

describe("AccessDenied", () => {
  it("renders the Access Denied heading", () => {
    setup();
    expect(screen.getByRole("heading", { name: /access denied/i })).toBeInTheDocument();
  });

  it("shows generic message when no resourceName is provided", () => {
    setup();
    expect(screen.getByText(/this page/i)).toBeInTheDocument();
  });

  it("shows the resource name when provided", () => {
    setup({ resourceName: "AKS Operations" });
    expect(screen.getByText("AKS Operations")).toBeInTheDocument();
  });

  it("includes a link back to home", () => {
    setup();
    const link = screen.getByRole("link", { name: /back to home/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/");
  });

  it("includes contact admin message", () => {
    setup();
    expect(screen.getByText(/contact your administrator/i)).toBeInTheDocument();
  });
});
