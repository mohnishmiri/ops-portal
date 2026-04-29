/**
 * Tests for ProtectedRoute component.
 *
 * ProtectedRoute depends on two contexts (AuthContext + PermissionsContext),
 * so both are mocked to control the scenario under test.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

// ── Mock contexts ─────────────────────────────────────────────────────────────

vi.mock("../contexts/AuthContext", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../contexts/PermissionsContext", () => ({
  usePermissions: vi.fn(),
}));

import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import ProtectedRoute from "./ProtectedRoute";

const PAGE_CONTENT = "Protected Page Content";

function setup(authOverrides = {}, permOverrides = {}) {
  vi.mocked(useAuth).mockReturnValue({ isAdmin: false, ...authOverrides } as any);
  vi.mocked(usePermissions).mockReturnValue({
    isLoading: false,
    canViewModule: () => true,
    canViewPage: () => true,
    ...permOverrides,
  } as any);

  render(
    <MemoryRouter>
      <ProtectedRoute module="aks_operations" page="aks_main" label="AKS Operations">
        <div>{PAGE_CONTENT}</div>
      </ProtectedRoute>
    </MemoryRouter>
  );
}

describe("ProtectedRoute — admin bypass", () => {
  it("renders children immediately for admin users regardless of permissions", () => {
    setup({ isAdmin: true });
    expect(screen.getByText(PAGE_CONTENT)).toBeInTheDocument();
  });
});

describe("ProtectedRoute — loading state", () => {
  it("shows a spinner while permissions are loading", () => {
    setup({}, { isLoading: true });
    // Children should not be visible yet
    expect(screen.queryByText(PAGE_CONTENT)).not.toBeInTheDocument();
    // A spinner element is rendered (div with animate-spin class)
    const spinner = document.querySelector(".animate-spin");
    expect(spinner).toBeInTheDocument();
  });
});

describe("ProtectedRoute — access granted", () => {
  it("renders children when module and page access is granted", () => {
    setup({}, { canViewModule: () => true, canViewPage: () => true });
    expect(screen.getByText(PAGE_CONTENT)).toBeInTheDocument();
  });
});

describe("ProtectedRoute — access denied", () => {
  it("shows AccessDenied when module access is denied", () => {
    setup({}, { canViewModule: () => false, canViewPage: () => true });
    expect(screen.queryByText(PAGE_CONTENT)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /access denied/i })).toBeInTheDocument();
    expect(screen.getByText("AKS Operations")).toBeInTheDocument();
  });

  it("shows AccessDenied when page access is denied", () => {
    setup({}, { canViewModule: () => true, canViewPage: () => false });
    expect(screen.queryByText(PAGE_CONTENT)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /access denied/i })).toBeInTheDocument();
  });

  it("uses label prop in the denied message", () => {
    setup({}, { canViewModule: () => false });
    expect(screen.getByText("AKS Operations")).toBeInTheDocument();
  });
});

describe("ProtectedRoute — no module or page specified", () => {
  it("renders children when no module/page guards are specified", () => {
    vi.mocked(useAuth).mockReturnValue({ isAdmin: false } as any);
    vi.mocked(usePermissions).mockReturnValue({
      isLoading: false,
      canViewModule: () => false,
      canViewPage: () => false,
    } as any);

    render(
      <MemoryRouter>
        <ProtectedRoute>
          <div>{PAGE_CONTENT}</div>
        </ProtectedRoute>
      </MemoryRouter>
    );
    // No module/page → open route, children always shown
    expect(screen.getByText(PAGE_CONTENT)).toBeInTheDocument();
  });
});
